"""使用真实 DeepAgents 图与确定性模型验证迁移行为，不调用外部服务。"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat_decrypt_tool.ai.agent_service import AgentService
from wechat_decrypt_tool.ai.service import AIService
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.ai.providers import ModelService
from wechat_decrypt_tool.ai.deep_backend import TaskBackend
from wechat_decrypt_tool.ai.deep_model import DeepChatModel
from wechat_decrypt_tool.ai.deep_tools import ChatGateway


class NoData:
    def __init__(self):
        self.calls = []

    async def conversations(self, account):
        self.calls.append('conversations')
        return [{'username': 'friend', 'name': '好友'}]

    async def read(self, account, username, start, end, offset, **kwargs):
        self.calls.append('read')
        return {'messages': [{'source': 'a' * 24, 'username': username, 'anchor': 'db:1',
            'time': end - 1, 'sender': '甲', 'sender_id': 'person-a', 'kind': 'text', 'text': '报价100元', 'media': {}}], 'has_more': False}

    async def search(self, account, username, query, start, end, offset):
        return await self.read(account, username, start, end, offset)


def action(name, args):
    return AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': str(time.time_ns()), 'type': 'tool_call'}])


def last_result(messages):
    from langchain_core.messages import ToolMessage
    return json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))


class ScriptedClient:
    def __init__(self, responses=None):
        self.responses = responses or [AIMessage(content='你好！有什么可以帮你？')]
        self.requests = []
        self.definitions = []

    def bind_tools(self, definitions, **kwargs):
        self.definitions = definitions
        return self

    def next(self, messages):
        self.requests.append(messages)
        # 内部摘要独立于业务脚本，分段数变化不能消耗下一条工具调用或最终回答。
        if any('<history_fragment>' in str(m.content) or '<context_compaction>' in str(m.content) for m in messages):
            return AIMessage(content='保留用户要求和已读取信息，依据程序状态继续未完成的分页与提交。')
        if any('完整报告遗漏核查。' in str(m.content) for m in messages if m.type == 'system'):
            page = json.loads(messages[1].content)['original_page']
            return AIMessage(content=json.dumps({'checks': [{'source': row['source'], 'verdict': 'irrelevant',
                'reason': '此场景只验证图调度；遗漏判断另有独立测试'} for row in page]}))
        response = self.responses.pop(0)
        return response(messages) if callable(response) else response

    async def astream(self, messages, **kwargs):
        result = self.next(messages)
        if isinstance(result, Exception):
            raise result
        yield AIMessageChunk(content=result.content, tool_calls=result.tool_calls,
            usage_metadata={'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110},
            response_metadata=result.response_metadata, id='response:' + str(len(self.requests)))

    async def ainvoke(self, messages, **kwargs):
        result = self.next(messages)
        result.usage_metadata = {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110}
        return result


def make_service(tmp_path, monkeypatch, responses=None, tools=None, compatible=False):
    store = AIStore(tmp_path)
    store.put('profile', dict(name='test', model='fixture', protocol='openai', base_url='http://localhost:1/v1',
        api_key='never-save-secret', vision=False, revision=1, context_window=32768,
        model_overrides={'context_window': 32768}), id='model')
    store.put('defaults', {'text': 'model'}, id='global')
    models = ModelService(store)
    client = ScriptedClient(responses)
    monkeypatch.setattr(models, 'client', lambda _: client)
    original = models.resolve
    def resolve(*args, **kwargs):
        profile = original(*args, **kwargs)
        if compatible:
            profile['model_metadata'] = {**profile.get('model_metadata', {}), 'tool_call': False}
        return profile
    monkeypatch.setattr(models, 'resolve', resolve)
    service = AgentService(AIService(store, models), tools or NoData())
    return service, client


async def execute(service, text='你好', request='one', thread=None):
    thread = thread or await service.create_thread('account', 'friend', '新的对话')
    run = await service.submit(thread['id'], 'account', {'text': text, 'request_id': request})
    await service.workers[run['id']]
    return thread, service.public_run(run['id'], 'account')


@pytest.mark.parametrize('compatible', [False, True])
def test_greeting_uses_real_graph_and_one_model_without_directory(tmp_path, monkeypatch, compatible):
    responses = [AIMessage(content=json.dumps({'type': 'final', 'content': '你好！'}, ensure_ascii=False))] if compatible else None
    service, client = make_service(tmp_path, monkeypatch, responses, compatible=compatible)
    async def check():
        _, run = await execute(service)
        assert run['status'] == 'completed', run.get('error')
        assert '你好' in run['answer']
        assert run['engine'] == 'deepagents' and run['engine_version'] == 3
        assert len(client.requests) == 1
        assert service.tools.calls == []
        assert not service.index_workers
        assert run['coverage_state'] == 'not_applicable'
        assert run['usage']['calls'] == 1 and run['used']['models'] == 1
        assert not any(t['kind'] == 'tool' for t in run.get('timeline', []))
        assert b'never-save-secret' not in (tmp_path / 'deepagents_checkpoints.sqlite3').read_bytes()
    asyncio.run(check())


@pytest.mark.parametrize('compatible', [False, True])
def test_public_progress_precedes_tools_and_survives_final_answer(tmp_path, monkeypatch, compatible):
    first = '我会先读取最近的聊天，整理大家提到的安排。'
    second = '已确定当前聊天范围，接下来读取具体消息。'
    def reply(name, args, text):
        if compatible:
            return AIMessage(content=json.dumps({'type': 'tools', 'content': text,
                'calls': [{'name': name, 'arguments': args}]}, ensure_ascii=False))
        message = action(name, args)
        message.content = text
        return message
    def read(_):
        run = service.store.list('agent_run')[0]
        return reply('read_messages', {'scope_handle': run['scope_handle']}, second)
    final = '聊天中提到报价100元。[[' + 'a' * 24 + ']]'
    service, client = make_service(tmp_path, monkeypatch, [reply('select_chat_scope', {}, first), read,
        AIMessage(content=json.dumps({'type': 'final', 'content': final}, ensure_ascii=False) if compatible else final)], compatible=compatible)
    original_read = service.tools.read
    async def inspect_read(*args, **kwargs):
        current = service.store.list('agent_run')[0]
        progress = [item for item in current['timeline'] if item['kind'] == 'progress']
        assert [item['text'] for item in progress] == [first, second]
        assert current['answer'] == ''
        return await original_read(*args, **kwargs)
    service.tools.read = inspect_read
    async def check():
        _, run = await execute(service, '最近聊了哪些安排？')
        assert run['status'] == 'completed', run.get('error')
        assert run['answer'] == final
        records = [item for item in run['timeline'] if item['kind'] in ('tool', 'progress')]
        assert [item['kind'] for item in records] == ['progress', 'tool', 'progress', 'tool']
        assert [item['text'] for item in records if item['kind'] == 'progress'] == [first, second]
        assert all(item['status'] == 'completed' for item in records)
        assert len(client.requests) == run['usage']['calls'] == 3
        # 检查真正发给模型的提示词，避免新版规划过滤了沟通要求但脚本仍返回阶段文字。
        assert service.run(run['id'])['subtask_plan_version'] == 2
        for request in client.requests:
            system = '\n'.join(str(message.content) for message in request if message.type == 'system')
            assert '鼓励在长任务中主动分享简短的阶段性进展' in system
            assert '不要求每次读取、搜索或工具调用都回复' in system
            assert '不必等到重大新发现才开口' in system
            assert '避免长任务从头到尾只显示工具记录' in system
            assert '写在面向用户的 assistant 正文中' in system
        for definition in client.definitions:
            params = definition['function']['parameters']
            assert 'progress_message' not in params.get('required', [])
            assert 'progress_message' not in params.get('properties', {})
        events = service.store.events(account='account')
        assert len([e for e in events if e['body'].get('timeline_item', {}).get('kind') == 'progress']) == 2
        # 历史快照仍有同一组真实进展，后续正文和完成事件不会覆盖它们。
        assert service.public_run(run['id'], 'account')['timeline'] == run['timeline']
    asyncio.run(check())


def test_stage_report_can_follow_multiple_tools_without_pre_announcements(tmp_path, monkeypatch):
    scope = {}
    report = '已读完本页聊天，发现对方给出了100元报价，尚未看到成交确认。'
    def read(messages):
        scope.update(last_result(messages))
        return action('read_messages', {'scope_handle': scope['scope_handle']})
    def commit(messages):
        page = last_result(messages)
        message = action('commit_findings', {'scope_handle': scope['scope_handle'], 'page_id': page['page_id'],
            'findings': [{'text': '对方报价100元', 'sources': ['a' * 24]}]})
        message.content = report
        return message
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {'complete': True}), read, commit,
        AIMessage(content='对方报价100元。[[' + 'a' * 24 + ']]')])
    async def check():
        _, run = await execute(service, '完整整理聊天中的报价')
        assert run['status'] == 'completed', run['error']
        records = [item for item in run['timeline'] if item['kind'] in ('tool', 'progress')]
        assert [item['kind'] for item in records] == ['tool', 'tool', 'progress', 'tool']
        assert records[2]['text'] == report
        assert records[1]['finished_at'] <= records[2]['started_at']
        assert run['usage']['calls'] == len(client.requests) == 4
    asyncio.run(check())


def test_optional_progress_can_be_omitted_without_retry(tmp_path, monkeypatch):
    def read(messages):
        return action('read_messages', {'scope_handle': last_result(messages)['scope_handle']})
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {}), read,
        AIMessage(content='聊天提到报价100元。[[' + 'a' * 24 + ']]')])
    async def check():
        _, run = await execute(service, '最近讨论了哪些重要的事？')
        assert run['status'] == 'completed', run['error']
        assert len(client.requests) == run['usage']['calls'] == 3
        assert not any(item['kind'] == 'progress' for item in run['timeline'])
        assert len([item for item in run['timeline'] if item['kind'] == 'tool']) == 2
    asyncio.run(check())


def test_legacy_resume_is_rejected_and_restart_is_idempotent(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        thread, run = await execute(service)
        service.update(run['id'], engine_version=2, status='failed')
        with pytest.raises(ValueError, match='legacy_restart_required'):
            await service.resume(run['id'], 'account')
        client.responses.append(AIMessage(content='你好！'))
        fresh = await service.restart(run['id'], 'account', 'restart')
        await service.workers[fresh['id']]
        again = await service.restart(run['id'], 'account', 'restart')
        assert fresh['id'] == again['id'] != run['id']
        assert service.run(fresh['id'])['restarted_from'] == run['id']
    asyncio.run(check())


def test_virtual_files_cannot_escape_or_cross_runs(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running', finished_at=None)
        backend = TaskBackend(service, run['id'], 1)
        assert backend.write('/notes/a.txt', '一\n二\n三').error is None
        first = backend.read('/notes/a.txt', 0, 2)
        assert first.next_offset == 2 and first.file_data['content'] == '一\n二'
        assert backend.read('/notes/a.txt', 2, 2).file_data['content'] == '三'
        assert backend.write('/../outside', 'bad').error
        assert backend.write('C:\\secret', 'bad').error
        assert backend.write('/materials/fake.json', 'bad').error
        service.update(run['id'], version=2)
        with pytest.raises(Exception):
            backend.read('/notes/a.txt')
    asyncio.run(check())


def test_full_read_commits_sources_and_completes_real_graph(tmp_path, monkeypatch):
    scope = {}
    def read(messages):
        scope.update(last_result(messages))
        return action('read_messages', {'scope_handle': scope['scope_handle']})
    def commit(messages):
        page = last_result(messages)
        return action('commit_findings', {'scope_handle': scope['scope_handle'], 'page_id': page['page_id'],
            'findings': [{'text': '报价100元', 'sources': ['a' * 24], 'quote': '报价100元'}]})
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {'complete': True}), read,
        commit, AIMessage(content='报价100元。[[' + 'a' * 24 + ']]')])
    async def check():
        _, run = await execute(service, '完整总结聊天')
        assert run['status'] == 'completed', run['error']
        assert run['coverage_state'] == 'complete'
        assert run['analysis']['analyzed'] == 1
        assert run['source_count'] == 1
        assert run['usage']['calls'] == 4  # 正文生成后直接结束，不追加证据或遗漏核查。
    asyncio.run(check())


def test_full_scope_cannot_answer_early_and_resume_continues(tmp_path, monkeypatch):
    scope = {}
    def early(messages):
        scope.update(last_result(messages))
        return AIMessage(content='暂时没有结论')
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {'complete': True}), early,
        AIMessage(content='未读完'), AIMessage(content='仍未读完')])
    async def check():
        _, run = await execute(service, '完整报告')
        assert run['status'] == 'failed', run['error']
        client.responses.extend([action('read_messages', {'scope_handle': scope['scope_handle']}),
            lambda m: action('commit_findings', {'scope_handle': scope['scope_handle'], 'page_id': last_result(m)['page_id'], 'findings': []}),
            AIMessage(content='未发现符合要求的事项'), AIMessage(content='{"checks":[{"id":0,"verdict":"supported","reason":"与原文一致","source":"aaaaaaaaaaaaaaaaaaaaaaaa","quote":"报价100元"}]}')])
        await service.resume(run['id'], 'account')
        await service.workers[run['id']]
        saved = service.public_run(run['id'], 'account')
        assert saved['status'] == 'completed', saved['error']
        assert service.tools.calls.count('read') == 1
    asyncio.run(check())


def test_count_is_programmatic_and_does_not_require_model_notes(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {'mode': 'statistics'}),
        lambda m: action('count_messages', {'scope_handle': last_result(m)['scope_handle']}), AIMessage(content='共1条消息')])
    async def check():
        _, run = await execute(service, '统计消息数')
        assert run['status'] == 'completed', run['error']
        assert run['read_count'] == 1
        assert run['analysis']['complete']
    asyncio.run(check())


def test_legacy_official_subagent_receives_bound_scope_and_parent_sources(tmp_path, monkeypatch):
    child_scope = {}
    def delegate(messages):
        return action('task', {'scope_handle': last_result(messages)['scope_handle'], 'subagent_type': 'range-analyst', 'description': '分析分配范围全部消息'})
    def read(messages):
        child_scope.update(last_result(messages))
        return action('read_messages', {'scope_handle': child_scope['scope_handle']})
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {'complete': True}), delegate,
        action('select_chat_scope', {}), read,
        lambda m: action('commit_findings', {'scope_handle': child_scope['scope_handle'], 'page_id': last_result(m)['page_id'],
            'findings': [{'text': '报价100元', 'sources': ['a' * 24]}]}),
        AIMessage(content='报价100元。[[' + 'a' * 24 + ']]'), AIMessage(content='查证报价100元。[[' + 'a' * 24 + ']]')])
    async def check():
        thread = await service.create_thread('account', 'friend', '新的对话')
        pending = await service.submit(thread['id'], 'account', {'text': '完整分析', 'request_id': 'legacy'})
        service.update(pending['id'], subtask_plan_version=0)
        await service.workers[pending['id']]
        run = service.public_run(pending['id'], 'account')
        assert run['status'] == 'completed', run['error']
        assert run['source_count'] == 1
        assert run['analysis']['complete']
        assert run['usage']['calls'] == 7  # 父子任务均不追加回答后的核查调用。
        children = [r for r in service.store.list('agent_run') if r.get('parent_run_id') == run['id']]
        assert len(children) == 1 and children[0]['status'] == 'completed'
    asyncio.run(check())


@pytest.mark.parametrize('directory_size', [1, 779, 2000])
def test_initial_request_does_not_load_or_embed_directory(tmp_path, monkeypatch, directory_size):
    service, client = make_service(tmp_path, monkeypatch)
    async def forbidden(*args, **kwargs):
        raise AssertionError(f'问候不能加载 {directory_size} 个会话或刷新模型目录')
    monkeypatch.setattr(service.tools, 'conversations', forbidden)
    monkeypatch.setattr(service.ai.models.metadata, 'refresh', forbidden)
    async def check():
        _, run = await execute(service)
        assert run['status'] == 'completed', run['error']
        assert len(client.requests) == 1
        from wechat_decrypt_tool.ai.agent_budget import request_size
        assert request_size(client.requests[0], client.definitions) < 12000
    asyncio.run(check())


@pytest.mark.parametrize('invalid', ['broken', '{"type":"final","content":""}', '{"type":"tools","calls":[{"name":"execute","arguments":{}}]}'])
def test_json_protocol_repairs_at_most_twice_without_second_answer_call(tmp_path, monkeypatch, invalid):
    service, client = make_service(tmp_path, monkeypatch, [AIMessage(content=invalid), AIMessage(content=invalid),
        AIMessage(content='{"type":"final","content":"你好"}')], compatible=True)
    async def check():
        _, run = await execute(service)
        assert run['status'] == 'completed', run['error']
        assert len(client.requests) == 3 and run['usage']['calls'] == 3
        assert not service.tools.calls
    asyncio.run(check())


def test_json_failure_is_recoverable_and_never_exposed_as_answer(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, [AIMessage(content='not json')] * 3, compatible=True)
    async def check():
        _, run = await execute(service)
        assert run['status'] == 'failed' and run['can_resume']
        assert run['answer'] == '' and run['usage']['calls'] == 3
    asyncio.run(check())


@pytest.mark.parametrize('status', [400, 422])
def test_explicit_native_capability_rejection_caches_json_mode(tmp_path, monkeypatch, status):
    class Unsupported(Exception):
        status_code = status
    service, client = make_service(tmp_path, monkeypatch, [Unsupported('tools not supported'),
        AIMessage(content='{"type":"final","content":"你好"}'), AIMessage(content='{"type":"final","content":"再见"}')])
    async def check():
        thread, first = await execute(service)
        _, second = await execute(service, '再见', request='second', thread=thread)
        assert first['status'] == second['status'] == 'completed'
        assert first['usage']['calls'] == 2 and second['usage']['calls'] == 1
        assert len(client.requests) == 3
    asyncio.run(check())


def test_all_statistics_cannot_silently_become_latest_500(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_tools import ChatGateway
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service, '统计全部消息')
        service.update(run['id'], status='running', finished_at=None)
        gateway = ChatGateway(service, run['id'], 1)
        with pytest.raises(ValueError, match='不是分页大小'):
            await gateway.select(mode='statistics', message_count=500)
        assert not gateway.scopes()
        result = await gateway.select(mode='statistics')
        assert gateway.scope(result['scope_handle'])['message_count'] is None
    asyncio.run(check())


def test_scope_handles_are_run_version_bound_and_dates_are_half_open(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_tools import ChatGateway
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running', finished_at=None)
        gateway = ChatGateway(service, run['id'], 1)
        selected = await gateway.select(time_phrase='昨天')
        scope = gateway.scope(selected['scope_handle'])
        assert scope['end'] - scope['start'] == 86400
        assert gateway.permits(scope, {'username': 'friend', 'time': scope['end'] - 1})
        assert not gateway.permits(scope, {'username': 'friend', 'time': scope['end']})
        recent = gateway.interval('最近一个月', '', '')
        assert recent['end'] == run['cutoff']
        assert 28 * 86400 <= recent['end'] - recent['start'] <= 31 * 86400
        with pytest.raises(ValueError):
            gateway.scope('invented')
        service.update(run['id'], version=2)
        with pytest.raises(Exception):
            gateway.scope(selected['scope_handle'])
        assert not ChatGateway(service, run['id'], 2).scopes()
    asyncio.run(check())


def test_read_material_preserves_long_original_and_rejects_outside_scope(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_tools import ChatGateway
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running', finished_at=None)
        gateway = ChatGateway(service, run['id'], 1)
        selected = await gateway.select()
        original = {'source': 'b' * 24, 'username': 'friend', 'time': run['cutoff'] - 1, 'text': '长消息🙂' * 4000, 'sender': '甲'}
        gateway.save_messages([original])
        reader = next(t for t in gateway.tools() if t.name == 'read_material')
        parts, offset = [], 0
        while True:
            page = await reader.ainvoke({'scope_handle': selected['scope_handle'], 'source': original['source'], 'text_offset': offset})
            message = page['messages'][0]
            parts.append(message['text'])
            offset = message.get('next_text_offset')
            if offset is None:
                break
        assert ''.join(parts) == original['text']
        assert service.run(run['id'])['evidence'][original['source']]['text'] == original['text']
        with pytest.raises(ValueError):
            await reader.ainvoke({'scope_handle': selected['scope_handle'], 'source': 'c' * 24})
    asyncio.run(check())


def test_analyst_without_reads_cannot_claim_coverage(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_tools import ChatGateway
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running', finished_at=None, child_role='range-analyst',
            bound_scope={'conversations': ['friend'], 'start': 10, 'end': run['cutoff']})
        gateway = ChatGateway(service, run['id'], 1)
        assert not gateway.validate_complete()
        with pytest.raises(ValueError, match='时间区间'):
            await gateway.select(start='1970-01-01T00:00:00')
    asyncio.run(check())


def test_startup_does_not_rerun_old_jobs_and_creates_consistent_backup(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], engine_version=2, status='running')
        await service.start()
        saved = service.public_run(run['id'], 'account')
        assert saved['status'] == 'interrupted' and saved['restart_required']
        assert len(client.requests) == 1
        import sqlite3
        with sqlite3.connect(tmp_path / 'before-deepagents-v3.sqlite3') as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    asyncio.run(check())


def test_deleting_thread_removes_checkpoints_and_internal_files(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        thread, run = await execute(service)
        service.update(run['id'], status='running', finished_at=None)
        TaskBackend(service, run['id'], 1).write('/notes/test.txt', '内部笔记')
        await service.delete_thread(thread['id'], 'account')
        assert service.store.get('agent_run', run['id']) is None
        with service.store.connection() as db:
            assert db.execute('SELECT count(*) FROM agent_piece WHERE run_id=?', (run['id'],)).fetchone()[0] == 0
        import sqlite3
        with sqlite3.connect(tmp_path / 'deepagents_checkpoints.sqlite3') as db:
            assert db.execute('SELECT count(*) FROM checkpoints').fetchone()[0] == 0
    asyncio.run(check())


def test_only_business_tools_and_virtual_notes_are_available(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {}), AIMessage(content='需要进一步明确问题')])
    async def check():
        _, run = await execute(service, '查聊天')
        assert run['status'] == 'completed', run['error']
        names = {d['function']['name'] for d in client.definitions}
        assert {'select_chat_scope', 'read_messages', 'read_file'} <= names
        assert 'task' not in names  # 尚未形成有效并行计划时不公开委派入口。
        assert not {'execute', 'web_search', 'shell', 'send_message'} & names
        assert 'plan_parallel_work' not in names  # 仅选择范围还没有实际分析回执。
    asyncio.run(check())


@pytest.mark.parametrize('source', ['a' * 24, 'c' * 24])
def test_answer_finishes_without_post_generation_review_or_repair(tmp_path, monkeypatch, source):
    answer = f'报价100元。[[{source}]]'
    service, client = make_service(tmp_path, monkeypatch, [action('select_chat_scope', {}),
        lambda m: action('read_messages', {'scope_handle': last_result(m)['scope_handle']}),
        AIMessage(content=answer)])
    async def forbidden(*args, **kwargs):
        pytest.fail('正文生成后不应执行核查或自动修复')
    monkeypatch.setattr(service, 'validate_deep_answer', forbidden)
    async def check():
        thread, run = await execute(service, '报价多少')
        assert run['status'] == 'completed', run['error']
        assert run['answer'] == answer
        assert run['usage']['calls'] == len(client.requests) == 3
        assert service.tools.calls.count('read') == 1
        assert service.thread(thread['id'], 'account')['messages'][-1]['text'] == answer
        events = [e['body'] for e in service.store.events(account='account') if e['body'].get('run_id') == run['id']]
        assert events[-1]['type'] == 'run_snapshot' and events[-1]['status'] == 'completed'
        assert events[-1]['patch']['answer'] == answer
        assert all(item['status'] == 'completed' for item in run['timeline'] if item['kind'] == 'answer')
        assert {record['purpose'] for record in service.store.list('usage')} == {'deepagents_agent'}
    asyncio.run(check())
