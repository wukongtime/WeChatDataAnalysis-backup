"""真实 MiMo 用例暴露的通用缺陷；离线验证范围、安全与状态约束。"""
import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from test_ai_deepagents import make_service
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.agent_references import normalize_answer_references, valid_answer_references
from wechat_decrypt_tool.ai.deep_tools import ChatGateway
from wechat_decrypt_tool.ai.deep_runtime import RuntimeEvents
from wechat_decrypt_tool.ai.deep_validation import evidence_issues
from wechat_decrypt_tool.ai.deep_model import DeepChatModel
from wechat_decrypt_tool.ai.deep_validation import temporal_issues


def test_notification_time_is_not_an_event_timestamp():
    from datetime import datetime
    source = {'a' * 24: {'text': '新版已经上线，发布完成。', 'time': int(datetime.fromisoformat('2026-09-08T10:05:00+08:00').timestamp())}}
    assert temporal_issues('当天10:05成功发布。', source, 28800)
    assert temporal_issues('按期上线。', source, 28800)
    assert temporal_issues('最终在该时间点完成了发布。', source, 28800)
    assert not temporal_issues('无法确定是否在该时间点完成发布。', source, 28800)
    assert not temporal_issues('10:05有人报告发布完成，实际时刻无法确定。', source, 28800)
    assert not temporal_issues('阿明在2026年9月8日10:05宣布：“新版已经上线，发布完成。”', source, 28800)
    assert not temporal_issues('预计10:05完成。', source, 28800)
    assert not temporal_issues('所有消息均已按时间顺序列出。', source, 28800)
    assert not temporal_issues('| 10:05 | 阿明 | 新版已经上线，发布完成。 |', source, 28800)
    explicit = {'a' * 24: {**source['a' * 24], 'text': '于10:00完成发布，准时上线。'}}
    assert not temporal_issues('10:00实际完成发布，准时上线。', explicit, 28800)
    planned = {**source, 'b' * 24: {'text': '确认改为10:00发布。', 'time': 0}}
    assert temporal_issues('最终按新日期9月8日10:00完成发布。', planned, 28800)
    assert not temporal_issues('确认10:00发布。', planned, 28800)


def test_union_coverage_does_not_cross_filters_or_pending_pages():
    base = dict(conversations=['a', 'b'], start=100, end=300, sender='', message_count=None,
                complete_required=False, read_complete=False, pending_page='', mode='search')
    completed = [{**base, 'conversations': [u], 'read_complete': True, 'complete_required': True} for u in ['a', 'b']]
    assert ChatGateway.scope_covered(base, [base, *completed], analyzed=True)
    assert not ChatGateway.scope_covered(base, completed[:1])
    assert not ChatGateway.scope_covered(base, [{**s, 'sender': 'someone'} for s in completed])
    assert not ChatGateway.scope_covered(base, [{**s, 'mode': 'statistics'} for s in completed])
    assert not ChatGateway.scope_covered(base, [{**s, 'message_count': 3} for s in completed])
    assert not ChatGateway.scope_covered({**base, 'pending_page': 'real-page'}, completed)
    assert not ChatGateway.scope_covered(base, [{**s, 'warnings': ['离线快照']} for s in completed])
    assert ChatGateway.scope_covered(base, [{**s, 'warnings': ['离线快照']} for s in completed], ignore_warnings=True)
    partial = [{**completed[0], 'end': 190}, {**completed[0], 'start': 200}, completed[1]]
    assert not ChatGateway.scope_covered(base, partial)


def test_known_reference_aliases_are_repaired_without_accepting_unknown_ids():
    known, unknown = 'a' * 24, 'b' * 24
    originals = {known: {'source': known}}
    for prefix in ['source', 'source_id', 'message', 'message_id']:
        assert normalize_answer_references(f'`[[{prefix}:{known}]]`', originals, {}) == f'[[{known}]]'
        result = normalize_answer_references(f'[[{prefix}:{unknown}]]', originals, {})
        assert not valid_answer_references(result, originals, {})
    second = 'c' * 24
    both = {**originals, second: {'source': second}}
    assert normalize_answer_references(f'[[{known}][{second}]]', both, {}) == f'[[{known}]] [[{second}]]'
    assert normalize_answer_references(f'[[{known}][{unknown}]]', both, {}) == f'[[{known}][{unknown}]]'


def test_reported_date_range_cannot_omit_its_own_evidence():
    from datetime import datetime
    from wechat_decrypt_tool.ai.deep_validation import reported_scope_issues
    timestamp = int(datetime.fromisoformat('2026-09-08T10:05:00+08:00').timestamp())
    run = {'cutoff': timestamp, 'timezone_offset': 28800}
    originals = {'a' * 24: {'time': timestamp}}
    assert reported_scope_issues('覆盖范围为2026年9月1日08:00至9月7日08:10', run, originals)
    assert not reported_scope_issues('覆盖范围为2026年9月1日至9月9日', run, originals)
    assert reported_scope_issues('最近7天（9月6日至9月7日）', run, originals)
    assert reported_scope_issues('最后一条消息为9-07', run, originals)
    assert not reported_scope_issues('最后一条消息为9-08', run, originals)
    run['scope_names'] = {'a': '项目群', 'b': '出行群'}
    originals = {'a': {'username': 'a', 'time': timestamp}, 'b': {'username': 'b', 'time': timestamp - 86400}}
    assert not reported_scope_issues('项目群最后一条为9-08，出行群最后一条为9-07。', run, originals)


def test_program_metadata_normalization_preserves_event_dates_and_quotes():
    from wechat_decrypt_tool.ai.deep_validation import normalize_program_facts
    run = {'timezone_offset': 0, 'scope_names': {'group': '项目讨论群'},
           'analysis': {'coverage': [{'username': 'group', 'read': 7, 'complete': True}]}}
    originals = {'a' * 24: {'time': 0}}
    text = '来源：[[' + 'a' * 24 + ']]（2026-09-08 10:05）\n活动日期为2026-09-08 10:05。\n项目讨论群共8条消息。\n原话：“项目讨论群共8条消息。”'
    result = normalize_program_facts(text, run, originals)
    assert '（1970-01-01 00:00）' in result and '活动日期为2026-09-08 10:05' in result
    assert '\n项目讨论群共7条消息' in result and '原话：“项目讨论群共8条消息。”' in result


def test_ordinary_answer_can_use_snapshot_without_claiming_full_coverage(tmp_path, monkeypatch):
    from test_ai_deepagents import action, last_result, execute
    service, client = make_service(tmp_path, monkeypatch)
    original_read = service.tools.read
    async def snapshot(*args, **kwargs):
        return {**await original_read(*args, **kwargs), 'warning': '实时源不可用，读取已解密快照'}
    service.tools.read = snapshot
    client.responses = [action('select_chat_scope', {'complete': True}),
        lambda m: action('read_messages', {'scope_handle': last_result(m)['scope_handle']}),
        lambda m: action('commit_findings', {'scope_handle': last_result(m)['scope_handle'], 'page_id': last_result(m)['page_id'], 'findings': []}),
        AIMessage(content='可用快照中报价100元。')]
    async def validate(id, version, text):
        return text
    monkeypatch.setattr(service, 'validate_deep_answer', validate)
    async def check():
        _, run = await execute(service, '报价多少？')
        assert run['status'] == 'completed' and not run['analysis']['complete']
        assert not run['needs_source_refresh'] and '资料说明' in run['answer']
    asyncio.run(check())


def test_selected_scope_without_read_cannot_finish(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        await gateway.select()
        events = RuntimeEvents(service, gateway)
        state = {'messages': [AIMessage(content='系统不能读取聊天，请手动提供。')]}
        result = await events.aafter_model(state, None)
        assert result['jump_to'] == 'model' and '尚未读取' in result['messages'][0].content
        service.timeline_item(gateway.id, 'tool', '读取聊天记录', action='read_messages', status='completed', result={'returned': 0})
        assert await events.aafter_model(state, None) is None
    asyncio.run(check())


def test_different_empty_queries_count_but_paginated_search_can_continue(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        events = RuntimeEvents(service, gateway)
        async def empty(request):
            return ToolMessage(content=json.dumps({'messages': [], 'has_more': False}), tool_call_id=request.tool_call['id'])
        for i in range(3):
            request = SimpleNamespace(tool_call={'id': str(i), 'name': 'search_messages', 'args': {'query': str(i), 'scope_handle': scope['scope_handle']}})
            await events.awrap_tool_call(request, empty)
        assert events.empty_searches == 3
        async def next_page(request):
            return ToolMessage(content=json.dumps({'messages': [], 'has_more': True, 'next_offset': 20}), tool_call_id=request.tool_call['id'])
        await events.awrap_tool_call(request, next_page)
        assert events.empty_searches == 3
        assert 'read_messages' in events.recovery()['search_guidance']
    asyncio.run(check())


def test_summary_review_receives_later_confirmation_sources(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        originals = {c * 24: {'source': c * 24, 'username': 'friend', 'text': text, 'time': i + 1, 'sender': '甲'}
                     for i, (c, text) in enumerate([('a', '计划发布'), ('b', '建议延期'), ('c', '确认日期'), ('d', '已经发布')])}
        draft = '最终已确认且发布。\n\n' + '\n\n'.join(f'{m["text"]} [[{key}]]' for key, m in originals.items())
        async def review(model, messages, **kwargs):
            paragraphs = json.loads(messages[1].content.split('\n', 1)[1])
            payload = json.JSONDecoder().raw_decode(messages[2].content.split('\n', 1)[1])[0]
            if any(p['text'] == '最终已确认且发布。' for p in paragraphs):
                assert {m['source'] for m in payload['original_wechat_messages']} == set(originals)
            return AIMessage(content=json.dumps({'checks': [{'id': p['id'], 'verdict': 'not_factual', 'reason': '此用例只验证材料传递'} for p in paragraphs]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        assert await evidence_issues(service, service.run(gateway.id), 1, draft, originals) == []
        # 局部修复可能不再重复后续消息编号，已加载的原文仍必须保留。
        revised = '最终已确认且发布。\n\n初始计划 [[' + 'a' * 24 + ']]'
        assert await evidence_issues(service, service.run(gateway.id), 1, revised, originals) == []
    asyncio.run(check())


def test_pending_page_exposes_commit_instead_of_repeated_read(tmp_path, monkeypatch):
    from langchain_core.messages import SystemMessage
    service, _ = make_service(tmp_path, monkeypatch)
    class Request(SimpleNamespace):
        def override(self, **values):
            return Request(**{**vars(self), **values})
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(complete=True)
        page = await gateway.read_next(scope['scope_handle'])
        events = RuntimeEvents(service, gateway)
        request = Request(tools=gateway.tools(), system_message=SystemMessage(content='测试'))
        definitions = events.prepare_model_request(request).tools
        by_name = {(t['function']['name'] if isinstance(t, dict) else t.name): t for t in definitions}
        assert 'read_messages' not in by_name and 'search_messages' not in by_name
        params = by_name['commit_findings']['function']['parameters']['properties']
        assert params['page_id']['enum'] == [page['page_id']]
        assert params['scope_handle']['enum'] == [scope['scope_handle']]
        gateway.commit(scope['scope_handle'], page['page_id'], [])
        service.update(gateway.id, child_role='range-analyst')
        definitions = events.prepare_model_request(request).tools
        names = {t['function']['name'] if isinstance(t, dict) else t.name for t in definitions}
        assert not names & {'commit_findings', 'search_messages', 'search_live_messages'}
    asyncio.run(check())


def test_review_missing_proof_can_only_use_matching_cited_original(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        source = 'a' * 24
        original = {'source': source, 'username': 'friend', 'sender': '甲', 'text': '确认下周三下午开会。', 'time': 10}
        async def review(model, messages, **kwargs):
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '与原文一致', 'source': '', 'quote': ''}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        draft = '原话：“确认下周三下午开会。” [[' + source + ']]'
        assert await evidence_issues(service, service.run(gateway.id), 1, draft, {source: original}) == []
        from wechat_decrypt_tool.ai.providers import ProviderFailure
        import pytest
        with pytest.raises(ProviderFailure):
            await evidence_issues(service, service.run(gateway.id), 1, '原话：“完全编造的另外一句话。” [[' + source + ']]', {source: original})
    asyncio.run(check())


def test_only_review_correction_and_repair_restore_reasoning(tmp_path, monkeypatch):
    from langchain_core.messages import HumanMessage
    from wechat_decrypt_tool.ai.model_execution import call_policy
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        captured = []
        original_client = service.ai.models.client
        def create(profile):
            captured.append(call_policy.get().auxiliary)
            return original_client(profile)
        monkeypatch.setattr(service.ai.models, 'client', create)
        client.responses.extend([AIMessage(content='{}'), AIMessage(content='{}'), AIMessage(content='[]'), AIMessage(content='摘要')])
        for purpose in ['evidence_review', 'evidence_adjudication', 'citation_repair', 'summary']:
            await DeepChatModel(service=service, run_id=gateway.id, input_version=1, purpose=purpose).ainvoke([HumanMessage(content='测试')])
        assert captured == [True, False, False, True]
    asyncio.run(check())


def test_known_errors_are_repaired_before_semantic_review(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        await gateway.select(complete=True)
        events = []
        async def repair(model, messages, **kwargs):
            events.append('repair')
            return AIMessage(content=json.dumps([{'old': '周一', 'new': '周日'}]))
        async def review(service, run, version, text, *args):
            events.append('review')
            assert '周日' in text
            return []
        async def omissions(*args):
            events.append('omissions')
            return []
        monkeypatch.setattr(DeepChatModel, 'ainvoke', repair)
        monkeypatch.setattr('wechat_decrypt_tool.ai.deep_validation.evidence_issues', review)
        monkeypatch.setattr('wechat_decrypt_tool.ai.deep_omissions.omission_issues', omissions)
        result = await service.validate_deep_answer(gateway.id, 1, '2026年9月13日（周一）没有安排。')
        assert '周日' in result
        assert events == ['repair', 'review', 'omissions']
    asyncio.run(check())


def test_aggregate_completion_requires_every_coverage_row(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        run = service.run(gateway.id)
        run['analysis'] = {'coverage': [{'username': 'a', 'complete': True}, {'username': 'b', 'complete': True}]}
        async def review(model, messages, **kwargs):
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '两个会话均完整',
                'evidence_kind': 'program', 'username': '', 'field': 'complete', 'value': True}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        assert await evidence_issues(service, run, 1, '全部会话的消息已读取完成。', {}) == []
        run['analysis']['coverage'][1]['complete'] = False
        import pytest
        from wechat_decrypt_tool.ai.providers import ProviderFailure
        with pytest.raises(ProviderFailure):
            await evidence_issues(service, run, 1, '全部会话的消息已读取完成。', {})
    asyncio.run(check())


def test_review_escalates_only_unfinished_paragraphs(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        calls = []
        async def review(model, messages, **kwargs):
            pending = json.loads(messages[1].content.split('\n', 1)[1])
            calls.append((model.purpose, [p['id'] for p in pending]))
            return AIMessage(content=json.dumps({'checks': [{'id': pending[0]['id'], 'verdict': 'not_factual', 'reason': '处理说明'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        assert await evidence_issues(service, service.run(gateway.id), 1, '分析如下。\n\n以下为整理结果。', {}) == []
        assert calls == [('evidence_review', [0, 1]), ('evidence_adjudication', [1])]
    asyncio.run(check())


def test_global_metadata_must_equal_actual_query_scope(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        run = service.run(gateway.id)
        run['time_range'] = {'start': 100, 'end': 200}
        proposed = {'start': 100, 'end': 200}
        async def review(model, messages, **kwargs):
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '范围一致',
                'evidence_kind': 'metadata', 'field': 'time_range', 'value': proposed}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        assert await evidence_issues(service, run, 1, '分析范围由查询边界确定。', {}) == []
        proposed['end'] = 300
        import pytest
        from wechat_decrypt_tool.ai.providers import ProviderFailure
        with pytest.raises(ProviderFailure):
            await evidence_issues(service, run, 1, '另一项范围说明。', {})
    asyncio.run(check())


def test_ordinary_overview_checks_speaker_and_event_state(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        source = 'a' * 24
        gateway.save_messages([{'source': source, 'username': 'friend', 'sender': '甲', 'sender_id': 'account',
            'time': gateway.scope(scope['scope_handle'])['end'] - 1, 'text': '周末要不要一起出去？'}])
        service.update(gateway.id, input_digest='最近讨论了哪些重要的事？')
        before = f'对方提议周末出游，已经成行。[[{source}]]'
        after = f'你提议周末出游，是否成行尚不明确。[[{source}]]'
        calls = []
        async def response(model, messages, **kwargs):
            calls.append(model.purpose)
            if model.purpose == 'citation_repair':
                return AIMessage(content=json.dumps([{'old': before, 'new': after}]))
            payload = json.JSONDecoder().raw_decode(messages[2].content.split('\n', 1)[1])[0]
            assert payload['original_wechat_messages'][0]['is_self'] is True
            supported = after in messages[1].content
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported' if supported else 'unsupported',
                'reason': '发言来自本人，且只有提议，没有成行证据', 'source': source, 'quote': '周末要不要一起出去？'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', response)
        assert await service.validate_deep_answer(gateway.id, 1, before) == after
        assert calls == ['evidence_review', 'evidence_adjudication', 'citation_repair', 'evidence_review']
    asyncio.run(check())


def test_matrix_accepts_count_tables_without_hiding_wrong_total():
    from tools.verify_deepagents_matrix import answer_count_matches
    assert answer_count_matches('| 项目 | 条数 |\n| 消息总数 | 5 |', 5)
    assert answer_count_matches('| 阿明消息数 | 2 |', 2, '阿明')
    assert answer_count_matches('总共 **5** 条消息。', 5)
    assert not answer_count_matches('| 消息总数 | 6 |\n其中小林发了5条。', 5)
    assert not answer_count_matches('| 日期 | 5 |', 5)


def test_review_false_alarm_is_checked_before_rewriting_answer(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        source = 'a' * 24
        originals = {source: {'source': source, 'username': 'friend', 'sender': '甲', 'time': 10, 'text': '计划下周发布，尚未上线。'}}
        calls = []
        async def review(model, messages, **kwargs):
            calls.append(model.purpose)
            if model.purpose == 'evidence_review':
                return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'unsupported', 'reason': '误把明确标注的计划当成已完成'}]}))
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '原段落明确是计划',
                'source': source, 'quote': '计划下周发布，尚未上线。'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        assert await evidence_issues(service, service.run(gateway.id), 1, f'计划下周发布，尚未上线。[[{source}]]', originals) == []
        assert calls == ['evidence_review', 'evidence_adjudication']
    asyncio.run(check())


def test_local_repair_keeps_corner_quote_message_reference(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        await gateway.read_next(scope['scope_handle'])
        service.update(gateway.id, input_digest='请引用原文')
        source = 'a' * 24
        before = f'2026年9月13日（周一），甲说「报价100元」。[[{source}]]'
        corrected = '2026年9月13日（周日），甲说「报价100元」。'
        async def response(model, messages, **kwargs):
            if model.purpose == 'citation_repair':
                return AIMessage(content=json.dumps([{'id': 0, 'text': corrected}]))
            assert source in messages[1].content
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '原话有消息依据',
                'source': source, 'quote': '报价100元'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', response)
        answer = await service.validate_deep_answer(gateway.id, 1, before)
        assert '周日' in answer and f'「报价100元」 [[{source}]]' in answer
    asyncio.run(check())
