"""完整活动流程：唯一主覆盖、引用约束、一次读取和恢复后的缓存复用。"""
import asyncio
import json
from datetime import timezone, timedelta

import pytest

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material
from wechat_decrypt_tool.ai.agent_events import (
    POLICY, EventBatch, EventReview, EventGrounding, eligible, packets, validate_events, review_sources, generate)


from wechat_decrypt_tool.ai.agent_model import ActionFormatError
from wechat_decrypt_tool.ai.model_execution import call_policy


def event(source='m1', quote='明晚八点打球，打完吃饭'):
    return {'summary': '邀约明晚打球后吃饭，尚未确认成行。', 'status': '邀约或安排',
            'tone': '明确表述', 'evidence': [{'source': source, 'quote': quote}]}


def test_partition_has_exact_coverage_and_preserves_full_text_and_neighbours():
    rows = {f'{i:024x}': {**material(i), 'time':1788192000+i, 'text':'正文'*100} for i in range(1, 180)}
    groups = packets(rows, timezone(timedelta(hours=8)), byte_limit=5000)
    sources = [s for batch in groups for s in batch['primary']]
    assert len(sources) == len(set(sources)) == len(rows)
    assert set(sources) == set(rows)
    assert all(batch['context'] for batch in groups)
    assert all(not set(batch['primary']).intersection(batch['context']) for batch in groups)


def test_local_review_does_not_expand_transitively_to_all_messages():
    rows = {f'{i:024x}': {**material(i), 'time':1788192000+i} for i in range(1,101)}
    selected = review_sources([event(source=f'{50:024x}')], set(), set(rows), rows)
    assert len(selected) == 7


def test_quote_source_must_belong_to_this_request():
    rows = {'a': {'text':'明晚八点打球，打完吃饭'}, 'b':{'text':'另一天的活动'}}
    assert validate_events({'events':[event()]}, {'m1':'a'}, rows, {'a'})['events'][0]['evidence'][0]['source'] == 'a'
    with pytest.raises(ActionFormatError):
        validate_events({'events':[event(quote='已经吃过饭了')]}, {'m1':'a'}, rows, {'a'})
    with pytest.raises(ActionFormatError):
        validate_events({'events':[event(source='b', quote='另一天的活动')]}, {'m1':'a'}, rows, {'a','b'})


def test_semantic_aliases_do_not_require_another_model_call():
    from wechat_decrypt_tool.ai.agent_events import ActivityEvent
    normalized = ActivityEvent.model_validate({**event(), 'status':'邀约', 'tone':'玩笑'})
    assert normalized.status == '邀约或安排' and normalized.tone == '玩笑或调侃'
    unknown = ActivityEvent.model_validate({**event(), 'status':'未知分类', 'tone':'未知语气'})
    assert unknown.status == '尚未确定' and unknown.tone == '猜测或含糊'
    assert EventBatch.model_validate({'activities':[event()]}).events


def test_quote_repair_only_uses_exact_unique_original_spans():
    from wechat_decrypt_tool.ai.agent_events import resolve_quote
    rows = {'a': {'text':'时间：周四\n组织者：甲\n地点：球馆', 'sender':'甲'},
            'b': {'text':'在家附近“旅游”', 'sender':'乙'}}
    assert resolve_quote('a', '时间：周四\n地点：球馆', set(rows), rows) == ('a', rows['a']['text'])
    assert resolve_quote('wrong', '乙：在家附近‘旅游’', set(rows), rows) == ('b', rows['b']['text'])
    assert resolve_quote('a', '时间：周五\n地点：球馆', set(rows), rows) is None
    rows['c'] = rows['b']
    assert resolve_quote('wrong', '在家附近“旅游”', set(rows), rows) is None


def test_draft_mismatch_is_marked_and_final_review_still_requires_real_quote():
    rows = {'a':{'text':'你喜欢的那个', 'sender':'甲'}}
    value = {'events':[event(source='m1', quote='你喜欢的那个也在')]}
    draft = validate_events(value, {'m1':'a'}, rows, {'a'}, draft=True)
    assert draft['events'][0]['evidence'][0] == {'source':'a','quote':'你喜欢的那个','needs_review':True}
    with pytest.raises(ActionFormatError):
        validate_events(value, {'m1':'a'}, rows, {'a'})


def test_summary_preserves_original_quote_qualifiers():
    from wechat_decrypt_tool.ai.agent_events import preserve_quoted_terms
    value = {**event(quote='这算是“训练”吧'), 'summary':'称这算是训练。'}
    assert preserve_quoted_terms(value)['summary'] == '称这算是“训练”。'


def test_published_report_does_not_add_facts_from_freeform_summary():
    from wechat_decrypt_tool.ai.agent_events import render, evidence_note
    row = {'text':'来这里喝一杯？', 'time':1788192001, 'sender':'乙'}
    item = {**event(source='a',quote=row['text']), 'summary':'甲昨晚在海边餐厅已经喝酒。'}
    answer = render({'2026-09-01':[item]}, {'a':row}, timezone(timedelta(hours=8)),1788192000,1788278400)
    assert '乙' in answer and row['text'] in answer
    assert all(word not in answer for word in ('甲','海边餐厅','昨晚'))
    assert '海边餐厅' not in evidence_note(item, {'a':row})['text']


def test_explicit_last_cancellation_is_distinct_from_conditional_cancellation():
    from wechat_decrypt_tool.ai.agent_events import preserve_explicit_cancellation
    rows = {'a':{'time':1},'b':{'time':2}}
    item = {**event(source='a',quote='#接龙 明晚打球'),'evidence':[
        {'source':'a','quote':'#接龙 明晚打球'},{'source':'b','quote':'人数不足炸车'}]}
    assert preserve_explicit_cancellation(item,rows)['status'] == '取消或退出'
    item['status']='邀约或安排'
    item['evidence'][1]['quote']='如果人数不足就炸车'
    assert preserve_explicit_cancellation(item,rows)['status'] == '邀约或安排'


def test_plans_and_changed_drinking_location_do_not_require_city_whitelist():
    from wechat_decrypt_tool.ai.agent_events import review_candidates
    rows = {'a':{'text':'四月打算去大理'},'b':{'text':'十二月回长沙'},
            'c':{'text':'不过要去另一个地方喝，来不来'},'d':{'text':'明天有没有米酒'}}
    assert review_candidates(rows,set(rows)) == set(rows)


def test_reply_excerpt_retains_original_speaker_context():
    from wechat_decrypt_tool.ai.agent_events import finalize_event
    row = {'time':1,'text':'暂时不去\n乙\n下周去杭州吗？','sender':'甲',
           'media':{'quoteTitle':'乙','quoteContent':'下周去杭州吗？'}}
    value = finalize_event(event(source='a',quote='下周去杭州吗？'),{'a':row})
    assert value['evidence'][0]['quote'] == row['text']
    own = finalize_event(event(source='a',quote='暂时不去'),{'a':row})
    assert own['evidence'][0]['quote'] == '暂时不去'


def test_roster_and_court_assignment_do_not_prove_attendance():
    from wechat_decrypt_tool.ai.agent_events import finalize_event
    rows = {'a':{'time':1},'b':{'time':2}}
    item = {**event(source='a',quote='1号场：甲、乙'),'status':'实际发生或结果',
            'evidence':[{'source':'a','quote':'1号场：甲、乙'}, {'source':'b','quote':'我们在三号场'}]}
    assert finalize_event(item,rows)['status'] == '邀约或安排'
    item['evidence'][1]['quote']='已经到了三号场，刚打完一局'
    assert finalize_event(item,rows)['status'] == '实际发生或结果'


async def prepared(service):
    _, run = await idle_run(service)
    service.update(run['id'], report_policy=POLICY, input_digest='完整整理活动及聚餐，不分析图片',
                   intent={'mode':'timeline'}, query_filters={'conversations':['friend']}, query_scope=['friend'],
                   time_range={'start':1788192000,'end':1788278400}, timezone_offset=28800)
    return service.run(run['id'])


















