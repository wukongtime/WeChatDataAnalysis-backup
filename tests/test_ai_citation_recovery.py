"""来源预算、校验重试与调用审计的联动。"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material
from wechat_decrypt_tool.ai.agent_budget import size
from wechat_decrypt_tool.ai.agent_citation_check import check_quoted_sources
from wechat_decrypt_tool.ai.agent_continuous import ContinuousContext
from wechat_decrypt_tool.ai.agent_model import AgentModel






@pytest.mark.parametrize('budget', [1024, 4096, 32768])
def test_note_source_excerpts_fit_budget_without_changing_originals(budget):
    rows = {f'{i:024x}': {'source': f'{i:024x}', 'text': ('中文"\\\n🙂' * (i * 200)),
                          'time': 1789047091, 'username': 'group', 'sender': '甲'} for i in range(4)}
    before = json.dumps(rows, ensure_ascii=False)
    run = {'evidence': SimpleNamespace(get_many=lambda keys: {k: rows[k] for k in keys}), 'timezone_offset': 28800}
    payload = {'summary': {'items': [{'text': '阶段笔记', 'sources': list(rows)}]}}
    ContinuousContext.attach_note_sources(SimpleNamespace(budget=lambda _: budget), run, payload)
    actual = payload['note_sources']
    assert size(actual['items']) <= budget // 10
    assert len(actual['items']) + actual['omitted'] == len(rows)
    assert json.dumps(rows, ensure_ascii=False) == before
    for item in actual['items']:
        assert item['sent_at'] == '2026-09-10T21:31:31+08:00'
        if 'text' in item:
            assert rows[item['source']]['text'].startswith(item['text'])
            assert item['text_truncated'] == (item['text'] != rows[item['source']]['text'])
    if budget == 32768:
        assert len(actual['items']) == 4
        assert all('text' in item for item in actual['items'])


def test_wrong_source_retry_keeps_full_report_request_and_audits_both_calls(service):
    async def run():
        a, b = 'a' * 24, 'b' * 24
        phrase = '今晚明华有没有选手'
        originals = {a: {'text': phrase}, b: {'text': '家里经常吃'}}
        seen, deltas = [], []
        class Streaming:
            async def astream(self, messages, **kwargs):
                seen.append(messages)
                source = b if len(seen) == 1 else a
                yield AIMessageChunk(content=f'“{phrase}” [[{source}]]',
                                     usage_metadata=dict(input_tokens=30, output_tokens=10, total_tokens=40))
        with patch.object(service.ai.models, 'client', return_value=Streaming()), patch('asyncio.sleep', new=AsyncMock()):
            result = await AgentModel(service.ai.models).call(service.ai.models.resolve(), [], 'account',
                on_delta=deltas.append, validate=lambda text: check_quoted_sources(text, originals, {}))
        assert result == f'“{phrase}” [[{a}]]'
        assert None in deltas and len(seen) == 2
        correction = seen[1][-1].content
        assert '保留用户要求的范围、事实与详细程度' in correction
        assert phrase in correction and a in correction
        usage = service.store.list('usage', 'account')
        assert sorted(u['status'] for u in usage) == ['failed', 'success']
        assert any(u.get('error_code') == 'citation_mismatch' for u in usage)
        assert all(u['usage_known'] for u in usage)
        assert phrase not in json.dumps(usage, ensure_ascii=False)
    asyncio.run(run())
