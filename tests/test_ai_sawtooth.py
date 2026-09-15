"""连续上下文与两次锯齿压缩，使用隔离存储和可控模型验证。"""
import asyncio
import json

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from test_ai_deepagents import make_service, execute, action
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.deep_backend import TaskBackend
from wechat_decrypt_tool.ai.deep_sawtooth import SawtoothSummarization, SUMMARY_INSTRUCTION
from wechat_decrypt_tool.ai.deep_context import context_tokens, ContextRecoveryRequired
from wechat_decrypt_tool.ai.deep_conversation import effective_messages, close_interrupted_calls


def middleware(backend, **kwargs):
    return SawtoothSummarization(backend=backend, model=FakeListChatModel(responses=['关键事实：报价100元。']),
        input_capacity=20000, summary_capacity=20000, trigger=('tokens', 8000), keep=('tokens', 1600),
        token_counter=context_tokens, **kwargs)


def batch(text='原文' * 1500):
    return [HumanMessage(content='最初要求'),
        AIMessage(content='', tool_calls=[{'name': 'read_messages', 'args': {}, 'id': 'read1'}]),
        ToolMessage(content=text, tool_call_id='read1'), AIMessage(content='已读取原文'),
        HumanMessage(content='继续建议' * 150)]


def test_under_pressure_keeps_large_tool_results_verbatim(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend)
        messages = batch('中间事实：报价100元。' + 'x' * 2500)
        async def handler(request):
            assert request.messages == messages
            return ModelResponse(result=[AIMessage(content='好')])
        await mw.awrap_model_call(ModelRequest(model=mw.model, messages=messages, state={}), handler)
        assert not backend.files()
    asyncio.run(check())


def test_two_sawteeth_prefix_replay_and_durable_recovery(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    calls = []
    async def summarize(self, messages, **kwargs):
        calls.append(messages)
        assert '<context_compaction>' in messages[-1].content
        return AIMessage(content='关键事实：报价100元。')
    monkeypatch.setattr(FakeListChatModel, 'ainvoke', summarize)
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend)
        messages = batch()
        system = SystemMessage(content='固定系统说明')
        async def handler(request):
            assert context_tokens([system, *request.messages]) < 8000
            return ModelResponse(result=[AIMessage(content='回答')])
        request = ModelRequest(model=mw.model, system_message=system, messages=messages, state={})
        response = await mw.awrap_model_call(request, handler)
        first = response.command.update['_summarization_event']
        assert calls[0][:-1] == [system, *messages[:first['cutoff_index']]]
        assert calls[0][0] is system
        assert first['cutoff_index'] not in (2, 3), '不能截断工具调用与返回'
        assert len(calls) == 1
        # 未回写图状态时，仅凭事务记录也能恢复，不重复摘要。
        await middleware(backend).awrap_model_call(request, handler)
        assert len(calls) == 1
        newer = [*messages, AIMessage(content='继续记录' * 700), HumanMessage(content='最新问题' * 150)]
        second_request = ModelRequest(model=mw.model, system_message=system, messages=newer,
            state={'_summarization_event': first})
        second = await middleware(backend).awrap_model_call(second_request, handler)
        assert len(calls) == 2
        second_event = second.command.update['_summarization_event']
        assert second_event['cutoff_index'] > first['cutoff_index']
        assert backend.data(first['file_path']) and backend.data(second_event['file_path'])
        restored = effective_messages(service, gateway.id, gateway.version, {'messages': newer})
        assert restored[0] == second_event['summary_message']
        assert backend.grep('最初要求', '/context/history').matches
        assert request.messages == messages and not request.state
    asyncio.run(check())


def test_failed_summary_never_replaces_history(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def invalid(self, messages, **kwargs):
        return AIMessage(content='摘要到一半', response_metadata={'finish_reason': 'length'})
    monkeypatch.setattr(FakeListChatModel, 'ainvoke', invalid)
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend, summary_attempts=1)
        messages = batch()
        async def handler(request):
            assert request.messages == messages, '有安全空间时沿用原历史，不用目录代替'
            return ModelResponse(result=[AIMessage(content='继续')])
        await mw.awrap_model_call(ModelRequest(model=mw.model, messages=messages, state={}), handler)
        assert service.workspace.get(gateway.id, gateway.version, 'context:event') is None
        assert backend.files()
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['cancel', 'source', 'revision', 'commit'])
def test_compaction_failures_keep_original_checkpoint(tmp_path, monkeypatch, failure):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        from wechat_decrypt_tool.ai.agent_service import Revised
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend, summary_attempts=1)
        original_put = service.workspace.put_pieces
        def write(run_id, version, pieces):
            if failure == 'commit' and any(item[0] == 'context:event' for item in pieces):
                raise RuntimeError('模拟事务写入失败')
            return original_put(run_id, version, pieces)
        monkeypatch.setattr(service.workspace, 'put_pieces', write)
        async def summarize(self, messages, **kwargs):
            if failure == 'cancel':
                raise asyncio.CancelledError()
            if failure == 'revision':
                service.update(gateway.id, version=gateway.version + 1)
            return AIMessage(content='虚构来源：[[' + 'f' * 24 + ']]' if failure == 'source' else '有效的简短摘要')
        monkeypatch.setattr(FakeListChatModel, 'ainvoke', summarize)
        messages = batch()
        request = ModelRequest(model=mw.model, messages=messages, state={})
        async def handler(current):
            assert failure == 'source' and current.messages == messages
            return ModelResponse(result=[AIMessage(content='沿用完整上下文')])
        if failure == 'source':
            await mw.awrap_model_call(request, handler)
        else:
            expected = {'cancel': asyncio.CancelledError, 'revision': Revised, 'commit': RuntimeError}[failure]
            with pytest.raises(expected):
                await mw.awrap_model_call(request, handler)
        assert service.workspace.get(gateway.id, gateway.version, 'context:event') is None
        assert request.messages == messages and request.state == {}
    asyncio.run(check())


def test_cross_turn_retains_tool_text_and_readonly_archive_after_restart(tmp_path, monkeypatch):
    text = '关键线索：报价100元；' + '不可自动移除' * 550
    service, client = make_service(tmp_path, monkeypatch, responses=[
        action('write_file', {'file_path': '/notes/facts.txt', 'content': text}),
        action('read_file', {'file_path': '/notes/facts.txt'}), AIMessage(content='已保存线索'),
        AIMessage(content='第二轮回答'), AIMessage(content='第三轮回答')])
    profile = service.store.get('profile', 'model')
    service.store.put('profile', {**profile, 'context_window': 262144, 'model_overrides': {'context_window': 262144}}, id='model')
    async def check():
        thread, first = await execute(service, '记录这段内容')
        assert first['status'] == 'completed', first.get('error')
        _, second = await execute(service, '继续建议', 'two', thread)
        assert second['status'] == 'completed', second.get('error')
        assert any(isinstance(m, ToolMessage) and '报价100元' in str(m.content) for m in client.requests[-1]), [(m.type, str(m.content)[:200]) for m in client.requests[-1]]
        from wechat_decrypt_tool.ai.agent_service import AgentService
        restarted = AgentService(service.ai, service.tools)
        _, third = await execute(restarted, '再继续', 'three', thread)
        assert third['status'] == 'completed', third.get('error')
        # backend 只在活动任务中开放，恢复状态仅用于测试只读接口。
        restarted.update(third['id'], status='running')
        backend = TaskBackend(restarted, third['id'], 1)
        assert backend.read('/notes/facts.txt').file_data['content'] == text
        assert backend.write('/notes/facts.txt', '篡改').error
        assert any(isinstance(m, ToolMessage) and '报价100元' in str(m.content) for m in client.requests[-1])
        other = await restarted.create_thread('account', 'friend', '另一对话')
        run = await restarted.submit(other['id'], 'account', {'text': '你好', 'request_id': 'other'})
        restarted.workers[run['id']].cancel()
        await asyncio.gather(restarted.workers[run['id']], return_exceptions=True)
        restarted.update(run['id'], status='running', context_origins=[{'run_id': first['id'], 'version': 1}])
        assert TaskBackend(restarted, run['id'], 1).data('/notes/facts.txt') is None
    asyncio.run(check())


def test_interrupted_tool_pairs_are_closed_without_reexecution():
    messages = [AIMessage(content='', tool_calls=[{'name': 'read_messages', 'args': {}, 'id': 'a'},
        {'name': 'read_messages', 'args': {}, 'id': 'b'}]), ToolMessage(content='已得到结果', tool_call_id='a')]
    restored = close_interrupted_calls(messages)
    assert restored[:2] == messages
    assert restored[-1].tool_call_id == 'b' and '中断' in restored[-1].content


def test_two_real_graph_compactions_then_restart_and_locate_original(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    profile = service.store.get('profile', 'model')
    service.store.put('profile', {**profile, 'context_window': 262144,
        'model_overrides': {'context_window': 262144}}, id='model')
    source_id = 'a' * 24
    summary_calls = []
    original_stream = client.astream
    async def priced_stream(messages, **kwargs):
        # 此测试验证水位曲线，不能用基础调度夹具恒定 100 tokens 的虚构用量校准大上下文。
        amount = context_tokens(messages, tools=client.definitions)
        async for chunk in original_stream(messages, **kwargs):
            yield chunk.model_copy(update={'usage_metadata': {'input_tokens': amount, 'output_tokens': 10, 'total_tokens': amount + 10}})
    client.astream = priced_stream
    original_next = client.next
    def respond(messages):
        if '<context_compaction>' in str(messages[-1].content):
            client.requests.append(messages)
            summary_calls.append(messages)
            return AIMessage(content='关键发现及来源：报价100元。[[' + source_id + ']]\n未完成工作：继续用户的新要求。')
        return original_next(messages)
    client.next = respond
    async def check():
        from wechat_decrypt_tool.ai.deep_checkpoints import checkpoint_session
        from wechat_decrypt_tool.ai.agent_service import AgentService
        gateway = await prepared(service)
        gateway.save_messages([{'source': source_id, 'username': 'friend', 'anchor': 'db:1',
            'time': 10, 'sender': '甲', 'text': '报价100元', 'media': {}}])
        client.responses[:] = [AIMessage(content='第一轮答案'), AIMessage(content='第二轮答案'),
            action('read_file', {'file_path': '/materials/' + source_id + '.json'}),
            AIMessage(content='原文确认报价100元。[[' + source_id + ']]')]
        run = service.run(gateway.id)
        messages = [HumanMessage(content='最初事实：报价100元。[[' + source_id + ']]')]
        for index in range(30):
            messages += [HumanMessage(content=f'讨论{index}：' + '讨论' * 667), AIMessage(content='记录' * 667)]
        messages.append(HumanMessage(content='请继续'))
        async with checkpoint_session(service) as saver:
            graph, _ = service.graph(run, saver)
            result = await graph.ainvoke({'messages': messages}, {'configurable': {'thread_id': service.checkpoint_id(run, 1)}})
        service.update(run['id'], answer=result['messages'][-1].content)
        service.finish(run['id'], 'completed')
        assert len(summary_calls) == 1
        first_manifest = service.workspace.get(run['id'], 1, 'context:event')['file_path']
        thread = service.thread(run['thread_id'], 'account')
        _, second = await execute(service, '补充说明。' * 11000, 'second', thread)
        assert second['status'] == 'completed', second.get('error')
        assert len(summary_calls) == 2
        second_manifest = service.workspace.get(second['id'], 1, 'context:event')['file_path']
        restarted = AgentService(service.ai, service.tools)
        _, third = await execute(restarted, '回查第一轮的报价并给出处', 'third', thread)
        assert third['status'] == 'completed', third.get('error')
        assert third['citations'][0]['text'] == '报价100元'
        assert len(summary_calls) == 2, '回查不能因换轮再次摘要'
        restarted.update(third['id'], status='running')
        backend = TaskBackend(restarted, third['id'], 1)
        assert backend.data(first_manifest) and backend.data(second_manifest)
        assert backend.grep('最初事实', '/context/history').matches
        # 完整清理整个对话及其检查点、资料和上下文投影。
        restarted.update(third['id'], status='completed')
        await restarted.delete_thread(thread['id'], 'account')
        with restarted.store.connection() as db:
            assert db.execute('SELECT count(*) FROM agent_piece').fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM agent_material').fetchone()[0] == 0
    asyncio.run(check())
