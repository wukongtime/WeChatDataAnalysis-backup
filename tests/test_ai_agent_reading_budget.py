"""动态读取的容量、完整性和窗口变化回归，全部使用本地合成资料。"""
import asyncio
import json

import pytest

from test_ai_message_pages import message_source
from test_ai_agent import submit
from legacy_agent_fixture import base_agent_service, legacy_service


@pytest.fixture
def service(legacy_service):
    return legacy_service
from test_ai_agent_context import setup_analysis
from wechat_decrypt_tool.ai.agent_budget import (
    ContextOverflow, active_budget, check_request, input_limit, material_limit,
    message_payload, size,
)
from wechat_decrypt_tool.ai.agent_context import AgentContext, Findings
from wechat_decrypt_tool.ai.agent_tools import ChatTools
from wechat_decrypt_tool.ai.messages import iter_message_pages
from wechat_decrypt_tool.ai.providers import analysis_messages


@pytest.mark.parametrize('stamp,offset,expected', [
    (1789047091, 28800, '2026-09-10T21:31:31+08:00'),
    (0, 0, '1970-01-01T00:00:00+00:00'),
    (0, -25200, '1969-12-31T17:00:00-07:00'),
    (0, 20700, '1970-01-01T05:45:00+05:45'),
])
def test_message_time_is_program_formatted_and_counted_in_same_budget(stamp, offset, expected):
    original = {'source':'a'*24,'username':'group','sender':'甲','text':'消息','time':stamp}
    result = message_payload(original, offset)
    assert result['sent_at'] == expected and result['time'] == stamp
    assert 'sent_at' not in original
    assert size(result) == size(message_payload(original, 0))
    assert size(result) > size({k:v for k,v in result.items() if k != 'sent_at'})


def test_saved_task_clock_uses_its_offset_instead_of_current_machine_zone():
    from wechat_decrypt_tool.ai.agent_context import task_now
    assert task_now({'cutoff':0,'timezone_offset':-25200}) == '1969-12-31T17:00:00-07:00'
    assert task_now({'cutoff':1789047091,'timezone_offset':28800}) == '2026-09-10T21:31:31+08:00'


@pytest.mark.parametrize('window', [8192, 32768, 131072, 1000000, None])
def test_material_budget_tracks_window_and_runtime_reduction(window):
    profile = {'context_window': window}
    initial = input_limit(profile)
    limit = material_limit(profile, initial)
    assert limit == int((window or 32768) * 0.1)
    token = active_budget.set(initial // 2)
    try:
        assert material_limit(profile, initial // 2) <= limit // 2 + 1
        assert material_limit(profile, initial, initial-600) == 88
        with pytest.raises(ContextOverflow):
            material_limit(profile, initial, initial-512)
    finally:
        active_budget.reset(token)


@pytest.mark.parametrize('window', [8192, 32768, 131072, 1000000, None])
def test_extraction_chunks_fit_complete_request_including_schema(window):
    profile = {'context_window':window, 'protocol':'anthropic'}
    context = AgentContext()
    context.profile = lambda run: profile
    run = {'intent':{'objective':'保留日期变化和待确认事项', 'mode':'list'}}
    capacity = context.reading_capacity(run)
    original = '中文 😀 English "quoted" \\ \n\t' * 500
    message = {'source':'s'*24, 'username':'chat', 'time':100, 'sender':'甲', 'text':original}
    chunks = list(context.message_chunks([message], capacity))
    parts = [m for chunk in chunks for m in chunk if not m.get('context_only')]
    assert ''.join(m['text'] for m in parts) == original
    assert [m.get('text_offset',0) for m in parts] == [sum(len(p['text']) for p in parts[:i]) for i in range(len(parts))]
    for chunk in chunks:
        assert size(chunk) <= capacity
        for item in chunk:
            offset = item.get('text_offset',0)
            assert original[offset:offset+len(item['text'])] == item['text']
        check_request(profile, analysis_messages(context.extraction_prompt(run,chunk), Findings), Findings.model_json_schema())


def test_unfit_metadata_fails_without_truncating_identity():
    message = {'source':'s'*24, 'username':'群'*1000, 'time':1, 'sender':'甲', 'text':'正文'}
    with pytest.raises(ContextOverflow):
        list(AgentContext.message_chunks([message], 512))
    assert message['username'] == '群'*1000 and message['text'] == '正文'


def test_context_preflight_rejects_full_request_before_model_call():
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    context = AgentContext()
    context.guard = lambda id:{'id':id,'account':'a','input_budget':4096}
    context.profile = lambda run:{'context_window':8192}
    invoke = AsyncMock()
    context.ai = SimpleNamespace(models=SimpleNamespace(invoke=invoke))
    with pytest.raises(ContextOverflow):
        asyncio.run(context.context_call('test','原文'*3000,Findings))
    invoke.assert_not_awaited()


def test_reader_budgets_resolved_display_names(message_source,monkeypatch):
    from wechat_decrypt_tool import chat_helpers
    message_source(20)
    monkeypatch.setattr(chat_helpers,'_pick_display_name',lambda contact,fallback:'长名字'*15)
    pages = list(iter_message_pages('a','chat',0,200,page_size=1000,max_batch_bytes=1024,
        message_weight=lambda m:size(message_payload(m))))
    assert sum(len(p['messages']) for p in pages) == 20
    assert all(size([message_payload(m) for m in p['messages']]) <= 1024 for p in pages)


@pytest.mark.parametrize('budget', [13107, 26214])
def test_reader_obeys_serialized_budget_without_fixed_100_limit_and_shrinks_live(message_source, budget):
    state = message_source(500)
    for row in state['rows']:
        row.raw_text = 'x'
    async def run():
        nonlocal budget
        pages = []
        async with ChatTools().open_pages('a','chat',0,200,0,lambda:None,max_batch_bytes=lambda:budget) as read:
            first = await read()
            assert 0 < len(first['messages']) <= 1000
            # 带可读时间的来源也占预算；较小窗口不再假定必然放下 100 条。
            if budget == 26214:
                assert len(first['messages']) > 100
            assert size([message_payload(m) for m in first['messages']]) <= budget
            pages.append(first)
            budget = 1024
            while pages[-1]['has_more']:
                page = await read()
                assert size([message_payload(m) for m in page['messages']]) <= budget
                pages.append(page)
        rows = [m for page in pages for m in page['messages']]
        assert len(rows) == len({m['source'] for m in rows}) == 500
        offset = 0
        for page in pages:
            offset += len(page['messages'])
            assert page['next_offset'] == (offset if page['has_more'] else None)
        assert state['opens'] == state['closed'] == 1
        assert len(state['threads']) == 1
    asyncio.run(run())


def test_large_window_respects_1000_message_cap(message_source):
    message_source(2100)
    async def run():
        async with ChatTools().open_pages('a','chat',0,200,0,lambda:None,max_batch_bytes=1000000) as read:
            pages = [await read(),await read(),await read()]
        assert [len(page['messages']) for page in pages] == [1000,1000,100]
    asyncio.run(run())


def test_oversized_single_message_is_complete_and_next_page_is_not_lost(message_source):
    state = message_source(4)
    text = '长消息😀"\\' * 5000
    state['rows'][1].raw_text = text
    pages = list(iter_message_pages('a','chat',0,200,page_size=1000,max_batch_bytes=1024,
        message_weight=lambda m:size(message_payload(m))))
    assert [len(page['messages']) for page in pages] == [1,1,2]
    assert pages[1]['messages'][0]['text'] == text
    assert [page['next_offset'] for page in pages] == [1,2,None]
    fragments = list(AgentContext.message_chunks(pages[1]['messages'],1024))
    assert all(size(chunk) <= 1024 for chunk in fragments)
    assert ''.join(m['text'] for chunk in fragments for m in chunk if not m.get('context_only')) == text


def test_recent_count_resume_uses_actual_offset_under_new_budget(message_source):
    message_source(500)
    async def run():
        tools = ChatTools()
        first = await tools.read('a','chat',None,200,0,count=175,max_batch_bytes=4000)
        rows = first['messages'][:]
        async with tools.open_pages('a','chat',None,200,first['next_offset'],lambda:None,count=175,max_batch_bytes=700) as read:
            while True:
                page = await read()
                rows.extend(page['messages'])
                if not page['has_more']:
                    break
        assert len(rows) == len({m['source'] for m in rows}) == 175
        assert {int(m['anchor']) for m in rows} == set(range(326,501))
    asyncio.run(run())


def test_search_next_offset_counts_raw_hits_before_normalization(monkeypatch, tmp_path):
    from wechat_decrypt_tool.routers import chat
    from wechat_decrypt_tool import chat_helpers
    # 保留真实的新鲜度检查，账号目录使用没有索引的独立临时目录。
    monkeypatch.setattr(chat_helpers, '_resolve_account_dir', lambda _: tmp_path)
    async def search(*args, **kwargs):
        return {'hits':[{'id':'one'}, {}, {'id':'three'}], 'hasMore':True}
    monkeypatch.setattr(chat,'search_chat_messages',search)
    result = asyncio.run(ChatTools().search('a','chat','query',0,200,17))
    assert result['next_offset'] == 20 and len(result['messages']) == 2
    assert result['freshness']['latest_realtime_included'] is False


def test_answer_evidence_uses_budget_beyond_100_candidates():
    class Evidence:
        def __init__(self):
            self.values = [{'source':str(i),'username':'c','time':1,'sender':'a','text':'x'} for i in range(150)]
        def __len__(self):return len(self.values)
        def rows(self, **kwargs):return iter(self.values)
    profile = {'context_window':1000000}
    run = {'evidence':Evidence()}
    context = AgentContext()
    context.guard = lambda id:run
    context.profile = lambda run:profile
    context.context_payload = lambda id:{'summary':{},'evidence':[]}
    context.update = lambda *args,**kwargs:None
    messages = context.bounded_prompt('test','仅依据资料回答',answer=True)
    evidence = json.loads(messages[-1].content)['evidence']
    assert len(evidence) == 150
    assert size(evidence) <= material_limit(profile,input_limit(profile))
    check_request(profile,messages)




