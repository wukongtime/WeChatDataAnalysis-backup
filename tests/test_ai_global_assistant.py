"""新版账号级助手行为，独立于旧范围权限测试。"""
import asyncio
import json
import time
from unittest.mock import patch

import pytest

from test_ai_agent import service, SOURCE
from wechat_decrypt_tool.ai.agent_context import ContextIntent, explicit_clock_range
from wechat_decrypt_tool.ai.agent_continuous import StageNotes
from wechat_decrypt_tool.ai.agent_schemas import AgentAction, ThreadInput
from wechat_decrypt_tool.ai.agent_tools import normalize
from wechat_decrypt_tool.ai.agent_global import resolve_directory_name
from wechat_decrypt_tool.ai.agent_live_search import live_search_continuation
from wechat_decrypt_tool.ai.providers import ProviderFailure


def test_decorated_conversation_name_preserves_ambiguity():
    contacts = [
        {'username': 'first@chatroom', 'name': '羽毛球🏸'},
        {'username': 'second@chatroom', 'name': '羽毛球🎾'},
    ]
    assert resolve_directory_name(contacts[:1], '羽毛球') == contacts[:1]
    assert resolve_directory_name(contacts, '羽毛球') == contacts
    assert resolve_directory_name(contacts, '羽毛球🏸') == contacts[:1]
    assert resolve_directory_name(contacts, 'second@chatroom') == contacts[1:]
    assert resolve_directory_name(contacts, '🏸') == []
    assert resolve_directory_name(contacts, '羽毛') == []


def test_late_failure_cannot_reclassify_or_double_count_stopped_run(service):
    async def run():
        _, task = await idle_run(service)
        service.finish(task['id'], 'cancelled', '已停止')
        stopped = service.store.get('agent_run', task['id'])
        service.finish(task['id'], 'failed', '迟到的读取错误')
        assert service.store.get('agent_run', task['id']) == stopped
        service.update(task['id'], status='running', finished_at=None, segment_started=time.time())
        service.finish(task['id'], 'completed')
        resumed = service.store.get('agent_run', task['id'])
        assert resumed['status'] == 'completed'
        assert resumed['elapsed_seconds'] >= stopped['elapsed_seconds']
    asyncio.run(run())






def test_live_search_continuation_preserves_selected_conversation_offset():
    action = AgentAction(action='search_messages', query='报价', conversation_offset=2, start=10, end=20)
    result = live_search_continuation(action, {'next_live_cursor': 'live:saved'})
    assert result['conversation_offset'] == 2
    assert result['start'] == 10 and result['end'] == 20


def test_keyword_hit_keeps_gap_cursor_without_forcing_scan():
    action = AgentAction(action='search_messages', query='原话')
    result = {'data_source': 'snapshot_index', 'match_counts': {'keyword': 1, 'semantic': 50},
              'next_live_cursor': 'live:saved', 'has_more': True}
    assert live_search_continuation(action, result) is None
    assert result['next_live_cursor'] == 'live:saved' and result['has_more'] is True












async def idle_run(service, text='查找报价'):
    thread = await service.create_thread('account', '', '新的对话')
    with patch.object(service, 'launch'):
        run = await service.submit(thread['id'], 'account', {'text': text, 'request_id': 'initial'})
    service.update(run['id'], status='running')
    from wechat_decrypt_tool.ai.deep_tools import ChatGateway
    await ChatGateway(service, run['id'], run['version']).select(all_chats=True)
    return thread, service.run(run['id'])




@pytest.mark.parametrize('status,expected', [('error', '遇到错误'), ('paused', '已暂停'),
                                           ('running', '后台渐进补齐'), ('done', '覆盖范围以已保存记录为准')])
def test_index_status_does_not_describe_paused_or_failed_job_as_building(service, monkeypatch, status, expected):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from wechat_decrypt_tool.local_search import service as local_module
    async def run():
        _, task = await idle_run(service)
        local = SimpleNamespace(ensure_global=AsyncMock(return_value={'status': status}),
                                config=lambda _: {'enabled': True, 'model': 'bge-small-zh'},
                                downloads=SimpleNamespace(available=lambda _: True))
        monkeypatch.setattr(local_module, 'get_local_search', lambda: local)
        await service.prepare_global_index('account', task['id'])
        result = service.run(task['id'])['index_status']
        assert result['status'] == status and expected in result['message']
        assert result['partial'] is True
    asyncio.run(run())


def test_person_mentions_use_only_the_source_group_and_preserve_ambiguity():
    from wechat_decrypt_tool.ai.agent_references import material_references, reference_id
    base = {'source': SOURCE, 'anchor': 'one', 'username': 'group-one@chatroom',
            'sender_id': 'speaker', 'sender': '甲', 'text': '请群名片核对安排', 'time': 10}
    directory = [{'username': 'subject', 'name': '群名片', 'conversation': 'group-one@chatroom'}]
    refs = material_references('account', [base], directory)
    subject_id = reference_id('person', 'account', 'subject')
    assert refs[subject_id]['mentioned_sources'] == [SOURCE]
    assert reference_id('person', 'account', 'speaker') != subject_id
    assert subject_id not in material_references('account', [{**base, 'username': 'group-two@chatroom'}], directory)
    ambiguous = [*directory, {**directory[0], 'username': 'another-subject'}]
    assert subject_id not in material_references('account', [base], ambiguous)






@pytest.mark.parametrize('phrase', [
    '2026年9月10日21:29到21:32',
    '2026-09-10 21:29 至 2026-09-10 21:32',
    '2026/09/10 21：29～21：32',
    '2026-09-10T21:29:00–21:32:00',
])
def test_explicit_clock_range_does_not_expand_end_minute(phrase):
    assert explicit_clock_range(phrase, 28800) == {'start': 1789046940, 'end': 1789047120}
    assert explicit_clock_range(phrase, 0) == {'start': 1789075740, 'end': 1789075920}


def test_explicit_clock_range_preserves_seconds_and_requires_cross_day_date():
    assert explicit_clock_range('2026年9月10日23:59:59到2026年9月11日00:00:01', 28800) == {
        'start': 1789055999, 'end': 1789056001}
    assert explicit_clock_range('昨天21:29到21:32', 28800) is None
    assert explicit_clock_range('2026年9月10日21:29到21:32 UTC', 28800) is None
    with pytest.raises(ValueError):
        explicit_clock_range('2026年9月10日23:59到00:01', 28800)




@pytest.mark.parametrize('phrase', [
    '北京时间2026年9月1日00:00至9月11日00:00之前',
    '北京时间2026年9月1日00:00至9月11日00:00之前的聊天',
    '2026年9月1日00:00至11日00:00',
    '从中国标准时间2026年9月1日00:00到2026年9月11日00:00以前',
    '2026-09-01 00:00–09-11 00:00',
])
def test_explicit_range_inherits_omitted_end_date_parts(phrase):
    assert explicit_clock_range(phrase, 28800) == {'start': 1788192000, 'end': 1789056000}


def test_beijing_range_uses_requested_zone_on_another_platform():
    assert explicit_clock_range('北京时间2026年9月1日00:00至9月11日00:00之前', 0) == {
        'start': 1788192000, 'end': 1789056000}
    with pytest.raises(ValueError):
        explicit_clock_range('2026年12月31日00:00至1月1日00:00', 28800)










def test_global_source_identity_uses_hit_conversation():
    raw = {'id': 'same-anchor', 'username': 'group-b', 'senderUsername': 'person-b', 'content': '报价'}
    result = normalize('account', '', raw)
    assert result['username'] == 'group-b'
    assert result['sender_id'] == 'person-b'
    assert result['source'] != normalize('other-account', '', raw)['source']
    assert normalize('account', '', {'id': 'same-anchor'}) is None


def test_account_directory_keeps_readable_chats_missing_from_live_sessions(monkeypatch):
    from wechat_decrypt_tool import chat_export_service
    from wechat_decrypt_tool.ai.agent_tools import ChatTools
    calls = []
    def preview(*, account, source='auto', include_hidden, include_official):
        assert account == 'account' and include_hidden and not include_official
        calls.append(source)
        return {'source': 'realtime' if source == 'auto' else 'decrypted', 'targets':
                [{'username': 'both@chatroom', 'name': '实时群名'}, {'username': 'new-private', 'name': '新私聊'}]
                if source == 'auto' else
                [{'username': 'both@chatroom', 'name': '旧群名'}, {'username': 'archived-private', 'name': '历史私聊'}]}
    monkeypatch.setattr(chat_export_service, 'get_chat_export_targets_preview', preview)
    directory = asyncio.run(ChatTools().conversations('account'))
    assert [p['username'] for p in directory] == ['both@chatroom', 'new-private', 'archived-private']
    assert directory[0]['name'] == '实时群名'
    assert calls == ['auto', 'decrypted']


def test_snapshot_account_directory_does_not_require_live_connection(monkeypatch):
    from wechat_decrypt_tool import chat_export_service
    from wechat_decrypt_tool.ai.agent_tools import ChatTools
    calls = []
    def preview(**kwargs):
        calls.append(kwargs)
        return {'source': 'decrypted', 'targets': [{'username': 'old', 'name': '历史'}]}
    monkeypatch.setattr(chat_export_service, 'get_chat_export_targets_preview', preview)
    assert asyncio.run(ChatTools().conversations('account')) == [{'username': 'old', 'name': '历史', 'isGroup': False}]
    assert len(calls) == 1




def test_resume_keeps_original_model_and_cutoff(service):
    async def run():
        thread, task = await idle_run(service)
        await service.stop_run(task['id'], 'account')
        profile = service.store.get('profile', 'model')
        service.store.put('profile', {**profile, 'model': 'changed-model', 'context_window': 4096})
        with patch.object(service, 'launch'):
            resumed = await service.resume(task['id'], 'account')
        assert resumed['profile']['model'] == task['profile']['model']
        assert resumed['cutoff'] == task['cutoff']
        assert resumed['segment_started'] >= task['segment_started']
        with patch.object(service, 'launch'):
            supplemented = await service.submit(thread['id'], 'account', {'text': '补充要求', 'request_id': 'next'})
        assert supplemented['cutoff'] == task['cutoff']
    asyncio.run(run())


def test_unsupported_native_effort_fails_without_modifying_profile(service):
    with pytest.raises(ProviderFailure):
        service.ai.models.resolve_turn('model', '', 'high')
    assert service.store.get('profile', 'model')['model'] == 'test'












