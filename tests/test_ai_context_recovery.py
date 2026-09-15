"""生产上下文恢复合同：软目标、归档、分段恢复、请求隔离和读取投影。"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage, message_to_dict

from test_ai_deepagents import make_service
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.deep_context import DurableSummarization, context_tokens, ContextRecoveryRequired
from wechat_decrypt_tool.ai.agent_budget import size, input_limit, model_output_limit
from wechat_decrypt_tool.ai.context_meter import ContextMeter
from wechat_decrypt_tool.ai.deep_model import DeepChatModel
from wechat_decrypt_tool.ai.deep_runtime import RuntimeEvents


class Archive:
    def __init__(self):
        self.files = {}

    def data(self, path):
        return self.files.get(path)

    def write(self, path, text):
        self.files[path] = {'content': text}
        return SimpleNamespace(error=None)


def mw(archive, budget=65536, **kwargs):
    return DurableSummarization(backend=archive, model=FakeListChatModel(responses=['摘要']),
        token_counter=context_tokens, trigger=('tokens', 8000), keep=('tokens', 1000),
        trim_tokens_to_summarize=budget, summary_prompt='整理历史：{messages}', **kwargs)


def archived_original(archive, path):
    index = json.loads(archive.data(path)['content'])
    return ''.join(archive.data(chunk['path'])['content'] for chunk in index['chunks'])


def test_real_failure_size_13010_is_accepted_and_cached(monkeypatch):
    archive, calls = Archive(), []
    text = '甲' * 4336 + 'ab'
    assert size(text) == 13010

    async def respond(self, messages, **kwargs):
        calls.append(messages)
        return AIMessage(content=text, response_metadata={'finish_reason': 'stop'})

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', respond)
    source = [HumanMessage(content='保留待办、否定条件与来源')]
    assert asyncio.run(mw(archive)._acreate_summary(source)) == text
    assert asyncio.run(mw(archive)._acreate_summary(source)) == text
    assert len(calls) == 1


@pytest.mark.parametrize('bad', [AIMessage(content=''), AIMessage(content='错误前缀', response_metadata={'finish_reason': 'length'}),
                              AIMessage(content='无穷长的草稿' * 20000)])
def test_bad_summary_preserves_archive_without_committing_a_directory(monkeypatch, bad):
    archive, calls, events = Archive(), [], []

    async def respond(self, messages, **kwargs):
        calls.append(messages)
        return bad

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', respond)
    source = [HumanMessage(content='必须保留开头' + '中文😀资料' * 12000 + '末尾尚未完成 cursor-99')]
    with pytest.raises(ContextRecoveryRequired):
        asyncio.run(mw(archive, progress=lambda *args: events.append(args))._acreate_summary(source))
    job = next(json.loads(v['content']) for k, v in archive.files.items() if k.startswith('/context/jobs/'))
    assert job['status'] == 'failed' and job['attempt'] == 0
    assert not job.get('result')
    manifests = [k for k in archive.files if k.endswith('/index.json')]
    assert archived_original(archive, manifests[0]) == json.dumps(message_to_dict(source[0]), ensure_ascii=False)
    assert events[-1][2] != 'completed'
    assert len(calls) == 3


def test_cancelled_second_fragment_resumes_without_repeating_first(monkeypatch):
    archive, accepted, requests = Archive(), [], []
    cancel_once = True

    async def respond(self, messages, **kwargs):
        nonlocal cancel_once
        fragment = messages[0].content.split('<history_fragment>\n')[1].rsplit('\n</history_fragment>', 1)[0]
        requests.append(fragment)
        if len(requests) == 2 and cancel_once:
            cancel_once = False
            raise asyncio.CancelledError()
        accepted.append(fragment)
        return AIMessage(content='已处理部分的简要记忆')

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', respond)
    source = [HumanMessage(content='头部要求' + '连续原文😀' * 1600 + '最后待办')]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(mw(archive, budget=5500)._acreate_summary(source))
    persisted = next(json.loads(v['content']) for k, v in archive.files.items() if k.startswith('/context/jobs/'))
    assert persisted['segments'] == 1 and persisted['offset'] > 0
    asyncio.run(mw(archive, budget=5500)._acreate_summary(source))
    assert requests[1] == requests[2]
    assert ''.join(accepted) == json.dumps(message_to_dict(source[0]), ensure_ascii=False)


def test_consumed_tool_payload_and_current_batch_stay_intact():
    archive = Archive()
    old = ToolMessage(content=json.dumps({'messages': [{'text': '旧原文' * 3000}], 'scope_handle': 'scope1'}), tool_call_id='old')
    current = ToolMessage(content='最新原文' * 3000, tool_call_id='new')
    messages = [HumanMessage(content='要求'), AIMessage(content='', tool_calls=[{'name': 'read_messages', 'args': {}, 'id': 'old'}]),
        old, AIMessage(content='已读旧页', tool_calls=[{'name': 'read_messages', 'args': {}, 'id': 'new'}]), current]
    middleware = mw(archive)
    request = ModelRequest(model=middleware.model, messages=messages, state={'messages': messages})
    effective = middleware._get_effective_messages(request)
    assert effective[2] == old
    assert effective[-1] == current and messages[2] == old
    assert context_tokens(effective) == context_tokens(messages)
    count = len(archive.files)
    assert middleware._get_effective_messages(request) == effective
    assert len(archive.files) == count


def test_pressure_count_uses_same_meter_with_system_and_tools():
    seen = []
    def measure(messages, tools):
        seen.append((messages, tools))
        return 1234
    middleware = mw(Archive(), measure_request=measure)
    system = SystemMessage(content='系统')
    message = HumanMessage(content='用户')
    assert middleware._count_tokens([message], system, []) == 1234
    assert seen[0] == ([system, message], [])


def test_capacity_reserves_actual_output_and_meter_separates_summary():
    profile = {'context_window': 1000000, 'model_metadata': {'limit': {'output': 384000}}}
    assert model_output_limit(profile) == 8192
    assert input_limit(profile) == 991296
    meter = ContextMeter()
    source = [HumanMessage(content='中文原文' * 1000)]
    meter.observe({**profile, 'context_purpose': 'summary'}, source, None, {'input_tokens': 100})
    assert meter.measure({**profile, 'context_purpose': 'agent'}, source) == context_tokens(source)


def test_summary_does_not_publish_main_context_and_search_refreshes_coverage(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        gateway.save_messages([{'source': 'a' * 24, 'username': 'friend', 'anchor': 'db:1', 'time': 10,
            'sender': '甲', 'sender_id': 'person-a', 'kind': 'text', 'text': '待确认', 'media': {}}])
        run = service.run(gateway.id)
        assert run['analysis']['coverage'][0]['read'] == run['read_count'] == 1
        assert run['analysis']['tracked'] is False
        published = []
        monkeypatch.setattr(service, 'publish_context', lambda *args: published.append(args))
        model = DeepChatModel(service=service, run_id=gateway.id, input_version=gateway.version, purpose='summary')
        await model.ainvoke([HumanMessage(content='<history_fragment>测试</history_fragment>')])
        assert not published
        request = ModelRequest(model=model, messages=[], tools=gateway.tools(), state={})
        prepared_request = RuntimeEvents(service, gateway).prepare_model_request(request)
        assert run['input_digest'] in prepared_request.system_message.content
    asyncio.run(check())
