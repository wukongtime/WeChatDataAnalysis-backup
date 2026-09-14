"""普通问答在首次取得资料后判断是否收尾，完整分析保留覆盖约束。"""
import asyncio
import json

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage

from test_ai_deepagents import action, execute, last_result, make_service
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.deep_model import DeepChatModel
from wechat_decrypt_tool.ai.deep_runtime import RuntimeEvents


def execution_state(service, gateway):
    model = DeepChatModel(service=service, run_id=gateway.id, input_version=gateway.version)
    request = ModelRequest(model=model, messages=[], tools=gateway.tools(), state={})
    result = RuntimeEvents(service, gateway).prepare_model_request(request)
    return json.loads(result.system_message.content.split('当前执行状态（程序元数据）：')[-1])


def test_checkpoint_starts_with_first_source_without_tool_quota(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        assert 'answer_checkpoint' not in execution_state(service, gateway)
        scope = await gateway.select()
        assert 'answer_checkpoint' not in execution_state(service, gateway)
        await gateway.read_next(scope['scope_handle'])
        # 直接调用网关模拟恢复后已有原文、没有工具时间线的情况。
        assert execution_state(service, gateway)['answer_checkpoint']

    asyncio.run(check())


@pytest.mark.parametrize('kind', ['explicit', 'mixed_scopes', 'range_analyst'])
def test_complete_analysis_does_not_receive_early_answer_guidance(tmp_path, monkeypatch, kind):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        full = await gateway.select(complete=True)
        await gateway.read_next(full['scope_handle'])
        if kind == 'explicit':
            service.update(gateway.id, input_digest='完整分析聊天')
        elif kind == 'mixed_scopes':
            await gateway.select(start='2026-01-01', complete=False)
        else:
            service.update(gateway.id, child_role='range-analyst')
        assert 'answer_checkpoint' not in execution_state(service, gateway)
        assert not gateway.validate_complete()

    asyncio.run(check())


def test_graph_can_answer_after_one_search_with_more_results_available(tmp_path, monkeypatch):
    def search(messages):
        return action('search_messages', {'scope_handle': last_result(messages)['scope_handle'], 'query': '报价'})

    def answer(messages):
        prompt = next(m.content for m in messages if m.type == 'system')
        if isinstance(prompt, list):
            prompt = ''.join(part.get('text', '') for part in prompt if isinstance(part, dict))
        state, _ = json.JSONDecoder().raw_decode(prompt.split('当前执行状态（程序元数据）：')[-1])
        assert state['answer_checkpoint']
        assert last_result(messages)['has_more']
        return AIMessage(content='已查记录中的报价为100元。[[aaaaaaaaaaaaaaaaaaaaaaaa]]')

    service, client = make_service(tmp_path, monkeypatch, responses=[action('select_chat_scope', {}), search, answer])
    original_search = service.tools.search

    async def more_results(*args, **kwargs):
        result = await original_search(*args, **kwargs)
        return {**result, 'has_more': True, 'next_offset': 1}

    service.tools.search = more_results

    async def check():
        _, run = await execute(service, '报价多少？')
        assert run['status'] == 'completed', run.get('error')
        assert '100元' in run['answer']
        assert len(client.requests) == 3
        assert service.tools.calls.count('read') == 1
        assert not run.get('needs_continuation')

    asyncio.run(check())
