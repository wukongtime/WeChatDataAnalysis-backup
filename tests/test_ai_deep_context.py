"""摘要预算回归：完整分段、工具配对、超限恢复与失败不提交。"""
import asyncio
import json

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.exceptions import ContextOverflowError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, message_to_dict
from langchain_core.messages.utils import trim_messages

from test_ai_deepagents import make_service
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.deep_backend import TaskBackend
from wechat_decrypt_tool.ai.deep_context import DurableSummarization, context_tokens
from wechat_decrypt_tool.ai.agent_budget import request_size
from wechat_decrypt_tool.ai.providers import ProviderFailure


def history():
    return [HumanMessage(content='保留最初要求'),
        AIMessage(content='', tool_calls=[{'name': 'read_messages', 'args': {'cursor': '第一页'}, 'id': 'read1'}]),
        ToolMessage(content='开头来源甲\n' + '中文😀单行资料' * 700 + '\n结尾来源乙', tool_call_id='read1'),
        AIMessage(content='尚未读取第二页')]


def middleware(backend=None, **options):
    return DurableSummarization(backend=backend, model=FakeListChatModel(responses=['累计摘要']),
        token_counter=context_tokens, summary_prompt='整理以下历史，保留要求和游标：\n{messages}',
        **{'trigger': ('tokens', 8000), 'keep': ('tokens', 1000),
           'trim_tokens_to_summarize': 5500, **options})


def test_all_history_reaches_summary_even_without_recent_human(monkeypatch):
    messages, requests = history(), []
    assert not trim_messages(messages, max_tokens=5500, token_counter=context_tokens,
        start_on='human', strategy='last', allow_partial=True, include_system=True)

    async def summarize(self, messages, **kwargs):
        requests.append(messages[0].content)
        assert request_size(messages) <= 5500
        assert kwargs['config']['metadata']['lc_source'] == 'summarization'
        return AIMessage(content='累计摘要')

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', summarize)
    result = asyncio.run(middleware()._acreate_summary(messages))
    fragments = [r.split('<history_fragment>\n', 1)[1].rsplit('\n</history_fragment>', 1)[0] for r in requests]
    expected = '\n'.join(json.dumps(message_to_dict(m), ensure_ascii=False, default=str) for m in messages)
    assert ''.join(fragments) == expected
    assert len(requests) > 1 and result == '累计摘要'
    assert all('<previous_summary>\n累计摘要\n' in r for r in requests[1:])


def test_summary_provider_overflow_shrinks_fragment_without_skipping(monkeypatch):
    accepted, attempts = [], []

    async def summarize(self, messages, **kwargs):
        attempts.append(request_size(messages))
        if request_size(messages) > 3000:
            raise ContextOverflowError('测试供应商实际窗口更小')
        accepted.append(messages[0].content.split('<history_fragment>\n', 1)[1].rsplit('\n</history_fragment>', 1)[0])
        return AIMessage(content='摘要')

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', summarize)
    messages = history()
    assert asyncio.run(middleware()._acreate_summary(messages)) == '摘要'
    assert attempts[0] > 3000 and all(n <= 3000 for n in attempts[1:])
    assert ''.join(accepted) == '\n'.join(json.dumps(message_to_dict(m), ensure_ascii=False) for m in messages)


def test_history_below_total_budget_can_still_be_summarized():
    # 对应原问题：总预算没超，仅摘要子预算放不下一轮工具交互。
    messages = history()
    messages[2] = ToolMessage(content='x' * 6000, tool_call_id='read1')
    assert 5500 < context_tokens(messages) < 10000
    assert asyncio.run(middleware()._acreate_summary(messages)) == '累计摘要'


def test_summary_cancellation_does_not_continue_to_next_fragment(monkeypatch):
    calls = []

    async def cancelled(self, messages, **kwargs):
        calls.append(1)
        raise asyncio.CancelledError()

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(middleware()._acreate_summary(history()))
    assert calls == [1]


@pytest.mark.parametrize('text', ['', '超长' * 4000, 'Previous conversation was too long to summarize.'],
                         ids=['empty', 'oversized', 'placeholder'])
def test_invalid_summary_is_bounded_and_never_returned(monkeypatch, text):
    calls = []

    async def summarize(self, messages, **kwargs):
        calls.append(1)
        return AIMessage(content=text)

    monkeypatch.setattr(FakeListChatModel, 'ainvoke', summarize)
    with pytest.raises(ProviderFailure, match='有效的精简摘要'):
        asyncio.run(middleware()._acreate_summary([HumanMessage(content='原文')]))
    assert len(calls) == 3


@pytest.mark.parametrize('mode', ['below_threshold', 'after_compaction', 'single_human', 'tool_batch'])
def test_real_middleware_compacts_and_archives_before_retry(tmp_path, monkeypatch, mode):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        messages = history()
        if mode == 'single_human':
            messages = [HumanMessage(content='超长输入😀' * 1200)]
        elif mode == 'tool_batch':
            messages = messages[:-1]
        limits = {'trigger': ('tokens', 1000000)} if mode == 'below_threshold' else {}
        mw = middleware(backend, **limits)
        request = ModelRequest(model=mw.model, messages=messages, state={'messages': messages})
        calls = []

        async def handler(current):
            calls.append(current.messages)
            if mode in ('below_threshold', 'after_compaction') and len(calls) == 1:
                raise ContextOverflowError('模拟主请求上下文超限')
            assert backend.files(), '调用压缩后的主模型之前必须完成归档'
            assert request_size(current.messages) < 5500
            return ModelResponse(result=[AIMessage(content='最终正文')])

        response = await mw.awrap_model_call(request, handler)
        event = response.command.update['_summarization_event']
        assert backend.data(event['file_path']) is not None
        assert response.model_response.result[0].content == '最终正文'
        assert len(calls) == (2 if mode in ('below_threshold', 'after_compaction') else 1)
        assert request.messages == messages and '_summarization_event' not in request.state
        if mode == 'tool_batch':
            assert event['cutoff_index'] == len(messages)
            assert len(calls[-1]) == 1
    asyncio.run(check())


def test_archive_failure_blocks_compacted_model_call(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend)
        monkeypatch.setattr(backend, 'data', lambda path: None)
        request = ModelRequest(model=mw.model, messages=history(), state={'messages': history()})

        async def forbidden(current):
            pytest.fail('归档核验失败后不能调用主模型')

        with pytest.raises(ProviderFailure, match='历史资料未能保存'):
            await mw.awrap_model_call(request, forbidden)
        assert '_summarization_event' not in request.state
    asyncio.run(check())


def test_persistent_overflow_stops_without_committing(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        mw = middleware(backend, trim_tokens_to_summarize=16000)
        request = ModelRequest(model=mw.model, messages=history(), state={'messages': history()})
        calls = []

        async def overflow(current):
            calls.append(1)
            raise ContextOverflowError('持续超限')

        with pytest.raises(ProviderFailure, match='自动压缩后仍超过'):
            await mw.awrap_model_call(request, overflow)
        assert len(calls) == 3
        assert backend.files() and '_summarization_event' not in request.state
    asyncio.run(check())


def test_provider_overflow_recovers_through_real_graph_and_model_adapter(tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    service, client = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        client.responses.extend([ValueError('maximum context length exceeded'), AIMessage(content='恢复后的正文')])
        original_next = client.next

        def respond(messages):
            if any('<history_fragment>' in str(m.content) for m in messages):
                client.requests.append(messages)
                return AIMessage(content='保留历史要求，继续回答当前问题。')
            return original_next(messages)

        client.next = respond
        messages = [HumanMessage(content='早先要求' * 300), AIMessage(content='历史讨论' * 300),
                    HumanMessage(content='请根据历史回答')]
        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'overflow.sqlite3')) as saver:
            graph, _ = service.graph(service.run(gateway.id), saver)
            config = {'configurable': {'thread_id': 'overflow'}}
            result = await graph.ainvoke({'messages': messages}, config)
            snapshot = await graph.aget_state(config)
        assert result['messages'][-1].content == '恢复后的正文'
        assert snapshot.values['_summarization_event']['file_path']
        assert TaskBackend(service, gateway.id, gateway.version).files()
        audits = service.store.list('usage')
        assert any(u['purpose'] == 'deepagents_summary' and u['status'] == 'success' for u in audits)
        assert any(u['status'] == 'failed' for u in audits)
    asyncio.run(check())
