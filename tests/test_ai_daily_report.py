"""逐日复核不得接受伪引文、跨日冒充、报名当结果；失败仅重做未通过日期。"""
import asyncio
import json

import pytest

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material
from wechat_decrypt_tool.ai.agent_model import ActionFormatError, AgentFailure
from wechat_decrypt_tool.ai.agent_report import DailyReport, validate_day, generate_report, applicable
from wechat_decrypt_tool.ai.model_execution import call_policy


def result(source='r1', quote='明晚八点约球', kind='邀约', text='有人邀请明晚八点打球，尚未确认举行。'):
    return {'items': [{'kind': kind, 'text': text, 'evidence': [{'source': source, 'quote': quote}]}]}


@pytest.mark.parametrize('change,code', [
    ({'quote': '已经打完'}, 'report_quote_mismatch'),
])
def test_unverified_claims_fail(change, code):
    source = 'a' * 24
    with pytest.raises(ActionFormatError, match=code):
        validate_day(result(**change), {'r1': source}, {source: {'text': '明晚八点约球'}}, {source})


def test_signup_is_not_completion_and_neighbor_is_not_current_day():
    source = 'a' * 24
    rows = {source: {'text': '#接龙 明晚八点约球'}}
    with pytest.raises(ActionFormatError, match='report_signup_not_completion'):
        validate_day(result(kind='实际活动或结果'), {'r1': source}, rows, {source})
    assert validate_day(result(), {'r1': source}, rows, set())['items'] == []
    with pytest.raises(ActionFormatError, match='report_quote_mismatch'):
        validate_day(result(quote='虚构旧消息'), {'r1': source}, rows, set())


def test_context_deduplication_does_not_bypass_primary_candidate_review():
    a, b = 'a' * 24, 'b' * 24
    rows = {a: {'text': '明晚八点约球'}, b: {'text': '还在香港'}}
    with pytest.raises(ActionFormatError, match='report_unreviewed_topic'):
        validate_day(result(), {'r1': a, 'r2': b}, rows, {b}, {b})


def test_long_exact_evidence_is_preserved_without_truncation():
    source = 'a' * 24
    quote = '#接龙 明晚八点约球\n' + '\n'.join(f'{i}. 报名参与者' for i in range(1, 50))
    verified = validate_day(result(quote=quote), {'r1': source}, {source: {'text': quote}}, {source})
    assert verified['items'][0]['evidence'][0]['quote'] == quote




def test_unverified_prose_is_never_rendered_and_travel_requires_review():
    from wechat_decrypt_tool.ai.agent_report import activity_candidates, render_day
    a, b = 'a' * 24, 'b' * 24
    rows = {a: {'text': '今晚去哪里A钱', 'time': 1788192060}, b: {'text': '还在HK', 'time': 1788192070}}
    verified = validate_day(result(quote='今晚去哪里A钱', text='9月3日无陌主持AA聚餐[[fake]]。'), {'r1': a}, rows, {a})
    rendered = render_day('2026-09-01', verified, rows)
    assert '今晚去哪里A钱' in rendered and '[[' + a + ']]' in rendered
    assert all(word not in rendered for word in ('AA', '9月3日', '无陌', 'fake'))
    assert activity_candidates(rows, {a, b}) == {b}
    with pytest.raises(ActionFormatError, match='report_unreviewed_topic'):
        validate_day(result(quote='今晚去哪里A钱', text='约A钱，活动具体内容不明。'), {'r1': a, 'r2': b}, rows, {a, b}, {b})


async def prepared(service):
    _, task = await idle_run(service)
    rows = [{**material(i, text='明晚八点约球'), 'time': 1788192000 + (i - 1) * 86400 + 60} for i in (1, 2)]
    service.update(task['id'], evidence={r['source']: r for r in rows},
        active_material=[], pending_material=[], time_range={'start': 1788192000, 'end': 1788364800},
        timezone_offset=28800, report_policy='daily_evidence_v1', intent={'mode': 'timeline'},
        input_digest='完整整理活动讨论并保留原文出处',
        analysis={'complete': True, 'coverage': []}, note_key='notes')
    service.workspace.put(task['id'], task['version'], 'notes', 'stage_note', {'notes': {'items': []}})
    return task, rows












