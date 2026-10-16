"""媒体服务不可用时，真实 Agent 图仍应根据文字完成回答。"""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from test_ai_deepagents import NoData, action, execute, make_service
from wechat_decrypt_tool.ai.providers import ModelService, ProviderFailure
from wechat_decrypt_tool.ai.storage import AIStore


def test_payment_required_is_explained_sanitized_and_not_retried(tmp_path):
    calls = []

    class Client:
        async def ainvoke(self, *args, **kwargs):
            calls.append(1)
            error = RuntimeError('secret token in provider error')
            error.status_code = 402
            raise error

    service = ModelService(AIStore(tmp_path))
    service.client = lambda _: Client()
    with pytest.raises(ProviderFailure, match='HTTP 402') as caught:
        asyncio.run(service.invoke({'id': 'vision'}, '图片分析'))
    assert '计费状态' in str(caught.value)
    assert 'secret' not in str(caught.value)
    assert len(calls) == 1
    audit = service.store.list('usage')[0]
    assert audit['status'] == 'failed' and audit['http_status'] == 402
    assert audit['error_category'] == 'payment_required'
    assert 'secret' not in json.dumps(audit)


@pytest.mark.parametrize('third_available', [False, True])
def test_parallel_media_failures_preserve_text_answer_and_other_results(tmp_path, monkeypatch, third_available):
    class Messages(NoData):
        async def read(self, account, username, start, end, offset, **kwargs):
            page = await super().read(account, username, start, end, offset, **kwargs)
            page['messages'].extend({'source': char * 24, 'username': username,
                'anchor': char, 'time': end - 1, 'sender': '甲', 'kind': 'image',
                'text': '[图片]', 'media': {}} for char in 'bcd')
            return page

    calls = []

    def read(_):
        run = service.store.list('agent_run')[0]
        return action('read_messages', {'scope_handle': run['scope_handle']})

    def media(_):
        run = service.store.list('agent_run')[0]
        return AIMessage(content='', tool_calls=[{'name': 'analyze_media',
            'args': {'scope_handle': run['scope_handle'], 'source': char * 24},
            'id': 'media-' + char, 'type': 'tool_call'} for char in 'bcd'])

    final = '文字中提到报价100元。两张图片未能分析，图片内容无法确认。'

    def answer(messages):
        results = {m.tool_call_id: (m.status, json.loads(m.content)) for m in messages
            if isinstance(m, ToolMessage) and m.tool_call_id.startswith('media-')}
        assert len(results) == 3
        for char in 'bc':
            status, body = results['media-' + char]
            assert status == 'error' and body['available'] is False
            assert 'HTTP 402' in body['error']
            assert '继续' in body['instruction']
        assert results['media-d'][1]['available'] is third_available
        if not third_available:
            assert '本机' in results['media-d'][1]['note']
        return AIMessage(content=final)

    service, client = make_service(tmp_path, monkeypatch,
        [action('select_chat_scope', {}), read, media, answer], tools=Messages())

    async def enrich(account, message, options, profile, guard, **kwargs):
        guard()
        calls.append(message['source'])
        await asyncio.sleep(0)
        if message['source'][0] in 'bc':
            raise ProviderFailure('模型服务拒绝请求（HTTP 402），请检查该服务账户的余额、额度或计费状态。')
        return {**message, 'text': '[图片]\n灯是红色' if third_available else '[图片]\n[附件未分析]',
            'coverage': '已分析' if third_available else '本机附件或图片缺失，请先在微信中下载并刷新'}

    monkeypatch.setattr(service.ai.media, 'enrich', enrich)

    async def check():
        _, run = await execute(service, '最近聊了什么？需要时查看图片。')
        assert run['status'] == 'completed', run.get('error')
        assert run['answer'] == final
        # 内部历史压缩可能额外调用模型；业务循环只能执行这四轮。
        business_requests = [messages for messages in client.requests
            if not any('<history_fragment>' in str(m.content) for m in messages)]
        assert len(business_requests) == 4
        assert sorted(calls) == [char * 24 for char in 'bcd']
        items = [item for item in run['timeline'] if item['kind'] == 'tool'
            and item['text'] == '分析图片与附件']
        assert len(items) == 3
        failed = [item for item in items if item['status'] == 'failed']
        assert len(failed) == 2
        assert all('HTTP 402' in item['result']['note'] for item in failed)
        saved = service.run(run['id'])
        assert saved['read_count'] == 4
        assert all(saved['evidence'][char * 24]['text'] == '[图片]' for char in 'bcd')

    asyncio.run(check())
