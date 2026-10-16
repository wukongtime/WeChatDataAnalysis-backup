"""迁移后的业务合同：通过官方图、标准工具和隔离数据库验证。"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from test_ai_deepagents import make_service, execute, action, last_result, NoData
from wechat_decrypt_tool.ai.deep_tools import ChatGateway
from wechat_decrypt_tool.ai.deep_backend import TaskBackend
from wechat_decrypt_tool.ai.deep_runtime import RuntimeEvents, CHILD_SCOPE
from wechat_decrypt_tool.ai.agent_service import Revised
from wechat_decrypt_tool.ai.deep_validation import calendar_issues


def test_full_report_cannot_finish_without_a_scope(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch, responses=[AIMessage(content='已完整总结')] * 3)
    async def check():
        _, run = await execute(service, '完整总结这十天聊天')
        assert run['status'] == 'failed' and '完整范围' in run['error']
        assert run['used']['models'] == 3
        assert run['answer'] == '已完整总结'
    asyncio.run(check())


@pytest.mark.parametrize('path', ['/conversation_history/fake.md', '/large_tool_results/fake.json', '/materials/fake.json', '/home/user/report.md', '/notes/../forbidden.md'])
def test_model_cannot_modify_framework_or_original_files(tmp_path, monkeypatch, path):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        request = SimpleNamespace(tool_call={'id': 'write', 'name': 'write_file', 'args': {'file_path': path}})
        async def handler(_):
            pytest.fail('越界写入不应进入实际工具')
        result = await RuntimeEvents(service, gateway).awrap_tool_call(request, handler)
        assert result.status == 'error'
        assert not TaskBackend(service, gateway.id, gateway.version).files()
    asyncio.run(check())


def test_analyst_cannot_shrink_assignment_or_change_sender(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        bound = {'conversations': ['friend'], 'start': 100, 'end': 200, 'sender': 'person-a'}
        service.update(gateway.id, bound_scope=bound, child_role='range-analyst')
        with pytest.raises(ValueError, match='不能缩小'):
            await gateway.select(start='1970-01-01T00:02:00+00:00', end='1970-01-01T00:03:00+00:00')
        with pytest.raises(ValueError, match='发言人'):
            await gateway.select(sender='person-b')
    asyncio.run(check())


def test_long_fragment_offsets_survive_page_commit(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(complete=True)
        original = {'source': 'a' * 24, 'username': 'friend', 'anchor': 'db:1', 'time': 10,
            'sender': '甲', 'kind': 'text', 'text': '甲' * 5000, 'media': {}}
        async def read(*args, **kwargs):
            offset = int(args[4])
            return {'messages': [{**original, 'text': original['text'][offset:offset + 2500], 'text_offset': offset,
                'next_text_offset': 2500 if offset == 0 else None, 'total_length': 5000}], 'originals': [original],
                'has_more': offset == 0, 'next_offset': 2500}
        service.tools.read = read
        for expected_offset in [0, 2500]:
            page = await gateway.read_next(scope['scope_handle'])
            assert page['messages'][0]['text_offset'] == expected_offset
            gateway.commit(scope['scope_handle'], page['page_id'], [])
            covered = gateway.get(page['page_id'])['covered'][0]
            assert (covered['start'], covered['end']) == (expected_offset, expected_offset + 2500)
        assert gateway.validate_complete()
        assert len(service.run(gateway.id)['evidence']) == 1
        assert len(service.run(gateway.id)['evidence']['a' * 24]['text']) == 5000
    asyncio.run(check())


def test_file_claim_checks_intervening_words():
    from wechat_decrypt_tool.ai.deep_validation import file_claim_issues
    backend = SimpleNamespace(read=lambda path: SimpleNamespace(error='不存在'))
    assert file_claim_issues('已整理并保存到 /home/user/report.md', backend)
    assert not file_claim_issues('可以在内部笔记记录分析结果', backend)


def test_grouped_known_citations_normalize_and_malformed_markers_fail():
    from wechat_decrypt_tool.ai.agent_references import normalize_answer_references, valid_answer_references
    known = {'a' * 24: {}, 'b' * 24: {}}
    raw = '[[' + 'a' * 24 + '], [' + 'b' * 24 + ']]'
    fixed = normalize_answer_references(raw, known, {})
    assert fixed == '[[' + 'a' * 24 + ']] [[' + 'b' * 24 + ']]'
    assert valid_answer_references(fixed, known, {})
    assert not valid_answer_references(raw, known, {})
    raw_source = '[[source:' + 'a' * 24 + '], [source:' + 'b' * 24 + ']]'
    assert normalize_answer_references(raw_source, known, {}) == fixed
    assert not valid_answer_references('[[' + 'c' * 24 + '], [' + 'b' * 24 + ']]', known, {})
    assert not valid_answer_references('正文 [[abc', known, {})


def test_named_conversations_cannot_expand_to_account_or_finish_half(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        async def directory(account):
            return [{'username': 'a', 'name': '坦洲羽毛球🏸'}, {'username': 'b', 'name': '坦洲-珠海搭子'}, {'username': 'c', 'name': '其他聊天'}]
        service.tools.conversations = directory
        service.update(gateway.id, input_digest='完整读取坦洲羽毛球和坦洲-珠海搭子两个群')
        with pytest.raises(ValueError, match='不能扩大'):
            await gateway.select(all_chats=True)
        chosen = await gateway.select(conversations=['坦洲羽毛球'])
        state = gateway.scope(chosen['scope_handle'])
        state.update(read_complete=True, pending_page='')
        gateway.put('scope:' + chosen['scope_handle'], 'deep_scope', state)
        assert not gateway.validate_complete()
        assert service.run(gateway.id)['required_conversations'] == ['a', 'b']
    asyncio.run(check())


@pytest.mark.parametrize('all_requested', [False, True])
def test_exclusion_does_not_disable_positive_scope_guard(tmp_path, monkeypatch, all_requested):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        async def directory(account):
            return [{'username': 'group_a', 'name': '羽毛球活动群'}, {'username': 'group_b', 'name': '聚餐讨论群'},
                {'username': 'group_c', 'name': '无关工作群'}]
        service.tools.conversations = directory
        service.update(gateway.id, input_digest=('查询所有群' if all_requested else '查询羽毛球活动群') + '，排除聚餐讨论群')
        if not all_requested:
            with pytest.raises(ValueError, match='不能扩大'):
                await gateway.select(all_chats=True, exclude=['聚餐讨论群'])
        chosen = await gateway.select(all_chats=all_requested, conversations=None if all_requested else ['羽毛球活动群'])
        assert gateway.scope(chosen['scope_handle'])['conversations'] == (['group_a', 'group_c'] if all_requested else ['group_a'])
    asyncio.run(check())


def test_json_encoded_array_is_normalized_against_tool_schema(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch, responses=[
        action('select_chat_scope', {'conversations': '["friend"]'}), AIMessage(content='找到当前聊天')])
    async def check():
        _, run = await execute(service, '查当前聊天')
        assert run['status'] == 'completed'
        assert run['query_filters']['conversations'] == ['friend']
        assert run['used']['models'] == 2
    asyncio.run(check())


def test_explaining_report_capability_does_not_require_reading(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service, '解释你怎样做完整报告，不需要读取聊天')
        assert run['status'] == 'completed' and run['used']['models'] == 1
        assert not service.tools.calls
    asyncio.run(check())


def test_virtual_grep_is_consumable_by_official_filesystem_tool(tmp_path, monkeypatch):
    from deepagents.backends.utils import format_grep_matches
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        assert backend.write('/notes/facts.md', '第一行\n核查安排\n第三行').error is None
        result = backend.grep('核查', '/notes')
        assert result.matches == [{'path': '/notes/facts.md', 'line': 2, 'text': '核查安排'}]
        assert '核查安排' in format_grep_matches(result.matches, 'content')
    asyncio.run(check())


def test_long_scope_children_cover_disjoint_pages_and_reuse_commits(tmp_path, monkeypatch):
    import hashlib
    from datetime import datetime, timezone
    service, client = make_service(tmp_path, monkeypatch)
    reads, expected = [], set()
    async def directory(account):
        return [{'username': 'friend', 'name': '好友'}, {'username': 'other', 'name': '另一群'}]
    async def read(account, username, start, end, offset, **kwargs):
        reads.append((username, start, end, offset))
        source = hashlib.sha256(f'{username}:{start}:{offset}'.encode()).hexdigest()[:24]
        expected.add(source)
        return {'messages': [{'source': source, 'username': username, 'anchor': f'{start}:{offset}',
            'time': start + offset, 'sender': '甲', 'kind': 'text', 'text': '分片原文', 'media': {}}],
            'has_more': offset == 0, 'next_offset': 1 if offset == 0 else None}
    def respond(messages):
        client.requests.append(messages)
        # 分页测试模型也需支持内部摘要；摘要调用不应返回空正文的工具指令。
        if any('<history_fragment>' in str(m.content) for m in messages):
            return AIMessage(content='完整处理当前分配范围，保留读取和提交游标，以程序状态继续分页。')
        # 旧的范围选择消息可能已归档，模型仍能从每轮的程序状态取得真实句柄。
        state = next((json.JSONDecoder().raw_decode(str(m.text).rsplit('当前执行状态（程序元数据）：', 1)[1].lstrip())[0]
            for m in messages if m.type == 'system' and '当前执行状态（程序元数据）：' in str(m.text)), {})
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            if state.get('scopes') and all(s['analysis_complete'] for s in state['scopes']):
                return AIMessage(content='分片已处理。')
            return action('select_chat_scope', {})
        last = results[-1]
        value = json.loads(last.content)
        selected = next((json.loads(m.content) for m in results if m.name == 'select_chat_scope'), None)
        handle = selected['scope_handle'] if selected else state['scopes'][0]['scope_handle']
        if last.name == 'select_chat_scope' or (last.name == 'commit_findings' and value.get('has_more')):
            return action('read_messages', {'scope_handle': handle})
        if last.name == 'read_messages':
            return action('commit_findings', {'scope_handle': handle, 'page_id': value['page_id'],
                'findings': [{'text': '分片原文', 'sources': [value['messages'][0]['source']]}]})
        return AIMessage(content='分片已处理。')
    async def check():
        gateway = await prepared(service)
        service.tools.conversations, service.tools.read = directory, read
        scope_result = await gateway.select(conversations=['friend', 'other'], complete=True,
            start='2026-01-01T00:00:00+00:00', end='2026-04-11T00:00:00+00:00')
        scope = gateway.scope(scope_result['scope_handle'])
        client.next = respond
        binding = CHILD_SCOPE.set({'parent_id': gateway.id, 'scope': scope, 'role': 'range-analyst', 'call_id': 'long-scope'})
        try:
            await service.deep_child({'messages': [HumanMessage(content='读取分配范围并提交发现')]})
            first_calls, first_reads = len(client.requests), list(reads)
            await service.deep_child({'messages': [HumanMessage(content='恢复相同分配范围')]})
        finally:
            CHILD_SCOPE.reset(binding)
        assert len(client.requests) == first_calls and reads == first_reads
        children = [r for r in service.store.list('agent_run') if r.get('parent_run_id') == gateway.id]
        assert len(children) == 8 and all(r['status'] == 'completed' for r in children)
        assert len(reads) == len(set(reads)) == 16
        assert set(service.run(gateway.id)['evidence']) == expected and len(expected) == 16
        assert gateway.validate_complete()
        for username in ['friend', 'other']:
            ranges = sorted((r['bound_scope']['start'], r['bound_scope']['end']) for r in children if r['bound_scope']['conversations'] == [username])
            assert ranges[0][0] == int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
            assert ranges[-1][1] == int(datetime(2026, 4, 11, tzinfo=timezone.utc).timestamp())
            assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    asyncio.run(check())


def test_media_question_and_result_do_not_overwrite_original(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        original = {'source': 'a' * 24, 'username': 'friend', 'anchor': 'picture', 'time': 10, 'sender': '甲', 'kind': 'image', 'text': '[图片]', 'media': {}}
        gateway.save_messages([original])
        async def enrich(account, message, options, profile, guard, **kwargs):
            assert options['question'] == '灯是什么颜色？'
            return {**message, 'text': '[图片]\n灯是红色', 'coverage': '已分析'}
        monkeypatch.setattr(service.ai.media, 'enrich', enrich)
        tool = next(t for t in gateway.tools() if t.name == 'analyze_media')
        result = await tool.ainvoke({'scope_handle': scope['scope_handle'], 'source': original['source'], 'question': '灯是什么颜色？'})
        assert '红色' in result['analysis']
        assert service.run(gateway.id)['evidence'][original['source']]['text'] == '[图片]'
        assert TaskBackend(service, gateway.id, 1).data(result['result_path'])
    asyncio.run(check())


def test_internal_notes_survive_multiple_turns_without_querying_wechat(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, responses=[
        action('write_file', {'file_path': '/notes/preference.md', 'content': '本次 AI 对话称呼用户为小王'}), AIMessage(content='记住了')])
    async def check():
        thread, first = await execute(service, '在本次对话里叫我小王')
        assert first['status'] == 'completed', first['error']
        client.responses.append(AIMessage(content='你好，小王'))
        _, second = await execute(service, '你好', request='second', thread=thread)
        assert second['status'] == 'completed'
        client.responses.extend([action('read_file', {'file_path': '/history/notes.json'}), AIMessage(content='你让我叫你小王')])
        _, third = await execute(service, '刚才记下的称呼是什么？', request='third', thread=thread)
        assert third['status'] == 'completed', third['error']
        saved = service.workspace.get(third['id'], 1, 'file:' + service.run(third['id'])['prior_notes_path'])
        assert '小王' in saved['content']
        assert not service.tools.calls
        client.responses.append(AIMessage(content='另一个对话'))
        _, other = await execute(service, request='other')
        assert service.workspace.get(other['id'], 1, 'file:/history/notes.json') is None
    asyncio.run(check())


def test_current_notes_can_be_edited_and_read_without_chat_query(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, responses=[
        action('write_file', {'file_path': '/notes/name.md', 'content': '称呼小王'}),
        action('edit_file', {'file_path': '/notes/name.md', 'old_string': '小王', 'new_string': '小李'}),
        action('read_file', {'file_path': '/notes/name.md'}), AIMessage(content='已记下称呼小李')])
    async def check():
        _, run = await execute(service, '在本次对话记下我的称呼，改为小李')
        assert run['status'] == 'completed', run['error']
        assert not service.tools.calls
        assert '小李' in service.workspace.get(run['id'], 1, 'file:/notes/name.md')['content']
        assert any(t.get('function', {}).get('name') == 'edit_file' for t in client.definitions)
    asyncio.run(check())


def test_live_gap_cursor_is_bound_and_replayed_without_rereading(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select()
        calls = []
        async def segments(account, names, start, end):
            return {'segments': [{'username': 'friend', 'start': start, 'end': end}], 'warning': ''}
        async def page(account, segment, cursor, query, sender, guard):
            calls.append(cursor)
            return {'messages': [{'source': ('a' if cursor is None else 'b') * 24, 'anchor': str(cursor), 'username': 'friend', 'time': 10, 'sender': '甲', 'text': '匹配原文'}],
                'has_more': cursor is None, 'cursor': {'position': 1} if cursor is None else None, 'scanned': 1}
        service.tools.live_search_segments, service.tools.live_search_page = segments, page
        tool = next(t for t in gateway.tools() if t.name == 'search_live_messages')
        args = {'scope_handle': scope['scope_handle'], 'query': '匹配'}
        first = await tool.ainvoke(args)
        assert first['has_more'] and len(calls) == 1
        assert await tool.ainvoke(args) == first and len(calls) == 1
        with pytest.raises(ValueError, match='范围或关键词'):
            await tool.ainvoke({**args, 'query': '另一个', 'cursor_handle': first['cursor_handle']})
        second = await tool.ainvoke({**args, 'cursor_handle': first['cursor_handle']})
        assert not second['has_more'] and len(calls) == 2
        assert second['coverage'] == 'search_only'
        assert service.run(gateway.id)['coverage_state'] == 'partial'
    asyncio.run(check())


def test_evidence_review_caches_results_and_rejects_ungrounded_claim(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        source = 'a' * 24
        draft = '已经聚餐。[[' + source + ']]'
        client.responses.extend([AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'unsupported', 'reason': '原文只是邀约，不能证明实际发生'}]}, ensure_ascii=False)) for _ in range(2)])
        values = {source: {'source': source, 'text': '今晚一起吃饭？', 'time': 10, 'sender': '甲'}}
        issues = await evidence_issues(service, service.run(gateway.id), 1, draft, values)
        assert len(issues) == 1 and '邀约' in issues[0]
        calls = len(client.requests)
        assert await evidence_issues(service, service.run(gateway.id), 1, draft, values) == issues
        assert len(client.requests) == calls
    asyncio.run(check())


def test_review_recovery_reuses_successful_batches(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    from wechat_decrypt_tool.ai.providers import ProviderFailure
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        calls = {}
        async def invoke(model, messages, **kwargs):
            parts = json.loads(messages[1].content.split('\n', 1)[1])
            key = parts[0]['text']
            calls[key] = calls.get(key, 0) + 1
            if key == '第五段状态' and calls[key] == 1:
                raise ProviderFailure('模拟上游中断')
            return AIMessage(content=json.dumps({'checks': [{'id': p['id'], 'verdict': 'not_factual', 'reason': '处理状态'} for p in parts]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        draft = '\n\n'.join(['第一段状态', '第二段状态', '第三段状态', '第四段状态', '第五段状态'])
        with pytest.raises(ProviderFailure, match='模拟上游中断'):
            await evidence_issues(service, service.run(gateway.id), 1, draft, {})
        assert await evidence_issues(service, service.run(gateway.id), 1, draft, {}) == []
        assert calls == {'第一段状态': 1, '第五段状态': 2}
    asyncio.run(check())


def test_partial_review_retries_only_missing_paragraphs(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        requested = []
        async def invoke(model, messages, **kwargs):
            parts = json.loads(messages[1].content.split('\n', 1)[1])
            requested.append([p['id'] for p in parts])
            selected = parts[:1] if len(requested) == 1 else parts
            return AIMessage(content=json.dumps({'checks': [{'id': p['id'], 'verdict': 'not_factual', 'reason': '处理状态'} for p in selected]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        assert await evidence_issues(service, service.run(gateway.id), 1, '处理状态一\n\n处理状态二\n\n处理状态三', {}) == []
        assert requested == [[0, 1, 2], [1, 2]]
    asyncio.run(check())


def test_repeated_review_ids_keep_every_unsupported_claim(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        async def invoke(model, messages, **kwargs):
            return AIMessage(content=json.dumps({'checks': [
                {'id': 0, 'verdict': 'unsupported', 'reason': '邀约不证明到场'},
                {'id': 0, 'verdict': 'supported', 'reason': '部分发言得到支持'},
                {'id': 1, 'verdict': 'not_factual', 'reason': '处理状态'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        issues = await evidence_issues(service, service.run(gateway.id), 1, '邀约和到场\n\n处理状态', {})
        assert len(issues) == 1 and '邀约不证明到场' in issues[0]
    asyncio.run(check())


@pytest.mark.parametrize('value,valid', [('群甲', True), ('群乙', False)])
def test_metadata_review_checks_server_value_without_demanding_chat_quote(tmp_path, monkeypatch, value, valid):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    from wechat_decrypt_tool.ai.providers import ProviderFailure
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        run = service.run(gateway.id)
        run['scope_names'] = {'friend': '群甲'}
        original = {'source': 'a' * 24, 'username': 'friend', 'time': 10, 'sender': '甲', 'text': '发言正文无需重复群名'}
        calls = []
        async def invoke(model, messages, **kwargs):
            calls.append(messages)
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '由元数据证明',
                'evidence_kind': 'metadata', 'field': 'conversation_name', 'value': value, 'source': 'a' * 24, 'quote': ''}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        coroutine = evidence_issues(service, run, 1, '消息来自群甲。[[' + 'a' * 24 + ']]', {'a' * 24: original})
        if valid:
            assert await coroutine == [] and len(calls) == 1
        else:
            with pytest.raises(ProviderFailure):
                await coroutine
            assert len(calls) == 3
    asyncio.run(check())


@pytest.mark.parametrize('value,valid', [('0', True), ('5', False)])
def test_program_review_binds_empty_scope_to_heading_and_ledger(tmp_path, monkeypatch, value, valid):
    from wechat_decrypt_tool.ai.deep_validation import evidence_issues
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    from wechat_decrypt_tool.ai.providers import ProviderFailure
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        run = service.run(gateway.id)
        run.update(scope_names={'empty': '没有消息群', 'other': '另一个群'}, analysis={'complete': True, 'coverage': [
            {'username': 'empty', 'read': 0, 'complete': True}, {'username': 'other', 'read': 5, 'complete': True}]})
        async def invoke(model, messages, **kwargs):
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '完整台账证明',
                'evidence_kind': 'metadata', 'field': 'read', 'value': value, 'source': 'program_coverage', 'quote': ''}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        coroutine = evidence_issues(service, run, 1, '## 没有消息群\n\n这个群没有消息。', {})
        if valid:
            assert await coroutine == []
        else:
            with pytest.raises(ProviderFailure):
                await coroutine
    asyncio.run(check())


def test_late_model_result_is_audited_as_superseded(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        async def stream(messages, **kwargs):
            service.update(gateway.id, version=2)
            yield AIMessageChunk(content='迟到结果')
        client.astream = stream
        with pytest.raises(Revised):
            await DeepChatModel(service=service, run_id=gateway.id, input_version=1).ainvoke([HumanMessage(content='旧要求')])
        audits = service.store.list('usage')
        assert any(u['status'] == 'cancelled' and u.get('error_code') == 'superseded' for u in audits)
        assert service.run(gateway.id)['answer'] != '迟到结果'
    asyncio.run(check())


def test_final_validation_of_100000_sources_loads_only_cited_original(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.agent_workspace import Evidence
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        await gateway.select()
        with service.store.connection() as db:
            db.executemany('INSERT INTO agent_material VALUES(?,?,?,?,?,?)',
                ((gateway.id, f'{i:024x}', 'friend', 10, str(i), json.dumps({'source': f'{i:024x}', 'username': 'friend',
                    'time': 10, 'anchor': str(i), 'sender': '甲', 'text': '唯一的可验证原文'})) for i in range(100000)))
        def forbidden(*args, **kwargs):
            pytest.fail('有效引用的最终校验不能枚举全部原文')
        monkeypatch.setattr(Evidence, 'rows', forbidden)
        async def review(model, messages, **kwargs):
            payload = json.loads(messages[2].content.split('\n', 1)[1])
            sources = payload['original_wechat_messages']
            assert len(sources) == 1 and sources[0]['source'] == f'{99999:024x}'
            return AIMessage(content=json.dumps({'checks': [{'id': 0, 'verdict': 'supported', 'reason': '原文一致',
                'source': sources[0]['source'], 'quote': '唯一的可验证原文'}]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', review)
        answer = '甲说“唯一的可验证原文”。[[' + f'{99999:024x}' + ']]'
        assert await service.validate_deep_answer(gateway.id, gateway.version, answer) == answer
        assert len(service.run(gateway.id)['evidence']) == 100000
    asyncio.run(check())


@pytest.mark.parametrize('archived,summary', [(False, '摘要'), (True, 'Previous conversation was too long to summarize.')])
def test_summary_failure_does_not_release_history(tmp_path, monkeypatch, archived, summary):
    from deepagents.middleware.summarization import SummarizationMiddleware
    from wechat_decrypt_tool.ai.deep_context import DurableSummarization
    from wechat_decrypt_tool.ai.deep_model import DeepChatModel
    from wechat_decrypt_tool.ai.providers import ProviderFailure
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, 1)
        if archived:
            backend.write('/conversation_history/archive.md', '应当保留的历史')
        async def response(*args):
            return SimpleNamespace(command=SimpleNamespace(update={'_summarization_event': {'file_path': '/conversation_history/archive.md', 'summary_message': summary}}))
        monkeypatch.setattr(SummarizationMiddleware, 'awrap_model_call', response)
        middleware = DurableSummarization(backend=backend, model=DeepChatModel(service=service, run_id=gateway.id, input_version=1), trigger=('tokens', 10000), keep=('messages', 2))
        with pytest.raises(ProviderFailure):
            await middleware.awrap_model_call(None, None)
    asyncio.run(check())


async def prepared(service, text='查聊天'):
    _, run = await execute(service, text)
    # 本文件的手动分页合同保留旧检查点路径；新内容编排另有独立合同测试。
    service.update(run['id'], status='running', finished_at=None, subtask_plan_version=0)
    return ChatGateway(service, run['id'], run['version'])


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancelled'])
def test_tools_release_foreground_priority(tmp_path, monkeypatch, outcome):
    from wechat_decrypt_tool.local_search import service as local
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        index = local.LocalSearch(tmp_path / 'index')
        monkeypatch.setattr(local, '_service', index)
        entered, release = asyncio.Event(), asyncio.Event()
        scope = await gateway.select()
        request = SimpleNamespace(tool_call={'id': 'read', 'name': 'read_messages', 'args': {'scope_handle': scope['scope_handle']}})
        async def handler(_):
            assert index.foreground_queries == 1
            entered.set()
            await release.wait()
            if outcome == 'failure':
                raise ValueError('读取失败')
            return ToolMessage(content='原文', tool_call_id='read')
        task = asyncio.create_task(RuntimeEvents(service, gateway).awrap_tool_call(request, handler))
        await asyncio.wait_for(entered.wait(), 2)
        if outcome == 'cancelled':
            task.cancel()
        else:
            release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert index.foreground_queries == 0
        assert isinstance(result, asyncio.CancelledError if outcome == 'cancelled' else ToolMessage)
        if outcome == 'failure':
            assert result.status == 'error'
        await index.stop()
    asyncio.run(check())


@pytest.mark.parametrize('mutation', ['version', 'account', 'cancel'])
def test_late_read_cannot_commit_after_authority_changes(tmp_path, monkeypatch, mutation):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(complete=True)
        entered, release = asyncio.Event(), asyncio.Event()
        read = service.tools.read
        async def delayed(*args, **kwargs):
            entered.set()
            await release.wait()
            return await read(*args, **kwargs)
        service.tools.read = delayed
        task = asyncio.create_task(gateway.read_next(scope['scope_handle']))
        await asyncio.wait_for(entered.wait(), 2)
        if mutation == 'version':
            service.update(gateway.id, version=2)
        elif mutation == 'cancel':
            service.update(gateway.id, status='cancelled')
        else:
            service.store.purge_account('account')
        release.set()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        assert isinstance(result, BaseException)
        with service.store.connection() as db:
            assert db.execute('SELECT count(*) FROM agent_material WHERE run_id=?', (gateway.id,)).fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM agent_piece WHERE run_id=? AND kind='deep_page'", (gateway.id,)).fetchone()[0] == 0
    asyncio.run(check())


def test_findings_transaction_failure_retains_pending_page(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(complete=True)
        page = await gateway.read_next(scope['scope_handle'])
        original = service.workspace.put_pieces
        def fail(*args):
            raise OSError('模拟写盘失败')
        monkeypatch.setattr(service.workspace, 'put_pieces', fail)
        with pytest.raises(OSError):
            gateway.commit(scope['scope_handle'], page['page_id'], [])
        assert gateway.scope(scope['scope_handle'])['pending_page'] == page['page_id']
        assert len(service.run(gateway.id)['evidence']) == 1
        monkeypatch.setattr(service.workspace, 'put_pieces', original)
        gateway.commit(scope['scope_handle'], page['page_id'], [])
        assert gateway.validate_complete()
        assert gateway.commit(scope['scope_handle'], page['page_id'], [])['reused']
        assert service.tools.calls.count('read') == 1
    asyncio.run(check())


def test_foreign_source_never_releases_pending_page_even_with_valid_quote(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(complete=True)
        page = await gateway.read_next(scope['scope_handle'])
        for finding in ({'text': '报价', 'sources': ['b' * 24]}, {'text': '报价', 'sources': ['b' * 24], 'quote': '报价100元'}):
            with pytest.raises(ValueError):
                gateway.commit(scope['scope_handle'], page['page_id'], [finding])
            assert gateway.scope(scope['scope_handle'])['pending_page']
        assert not gateway.validate_complete()
    asyncio.run(check())


def test_followup_inherits_then_explicitly_clears_filters(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    async def people(_):
        return [{'username': 'person-a', 'name': '甲'}]
    service.tools.people = people
    async def check():
        gateway = await prepared(service, '最近12条消息')
        first = await gateway.select(sender='甲', message_count=12, time_phrase='昨天')
        old = service.run(gateway.id)
        service.update(gateway.id, status='completed')
        client.responses.append(AIMessage(content='继续查询'))
        _, new = await execute(service, '还有吗', request='second', thread=service.thread(old['thread_id'], 'account'))
        service.update(new['id'], status='running')
        fresh = ChatGateway(service, new['id'], new['version'])
        inherited = await fresh.select(reuse_previous=True)
        state = fresh.scope(inherited['scope_handle'])
        assert state['message_count'] == 12 and state['sender'] == 'person-a'
        assert inherited['time_range'] == first['time_range']
        cleared = await fresh.select(reuse_previous=True, sender='', clear_filters=['message_count', 'time_range'])
        state = fresh.scope(cleared['scope_handle'])
        assert state['sender'] == '' and state['message_count'] is None and state['start'] == 0
    asyncio.run(check())


def test_explicit_user_dates_override_model_epoch_and_timezone_is_respected(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service, '统计2026年9月1日00:00到2026年9月11日00:00的全部消息')
        service.update(gateway.id, cutoff=1790000000, timezone_offset=28800)
        selected = await gateway.select(start='2026-09-01T00:00', end='2026-09-11T00:01', mode='statistics')
        assert selected['time_range'] == {'start': 1788192000, 'end': 1789056000}
        assert gateway.interval('', '2026-09-01T00:00+08:00', '2026-09-11T00:00+08:00') == selected['time_range']
    asyncio.run(check())


def test_calendar_check_does_not_guess_relative_event_dates():
    run = {'cutoff': 1790000000, 'timezone_offset': 28800}
    assert calendar_issues('9/3（周三）活动', run)
    assert not calendar_issues('9/2（周三）活动', run)
    assert not calendar_issues('9/1 的消息写“周三打球”，活动是否举行尚未确认。', run)


def test_same_second_messages_and_replay_are_counted_once(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(mode='statistics')
        rows = [{'source': f'{i:024x}', 'username': 'friend', 'anchor': f'db:table:{i}', 'time': 10,
            'text': '同秒消息', 'sender': '同名', 'sender_id': f'p{i % 2}'} for i in range(7)]
        gateway.save_messages(rows)
        gateway.save_messages(rows)
        service.update(gateway.id, statistics_scope=scope['scope_handle'])
        stats = service.workspace.statistics(gateway.id)
        assert stats['total_messages'] == 7
        assert {r['sender_id']: r['count'] for r in stats['sender_ranking']} == {'p0': 4, 'p1': 3}
    asyncio.run(check())


def test_read_warnings_prevent_complete_statistics(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    read = service.tools.read
    async def warned(*args, **kwargs):
        return {**await read(*args, **kwargs), 'warning': '一个原文分库暂不可读'}
    service.tools.read = warned
    async def check():
        gateway = await prepared(service)
        scope = await gateway.select(mode='statistics')
        tool = next(t for t in gateway.tools() if t.name == 'count_messages')
        result = await tool.ainvoke({'scope_handle': scope['scope_handle']})
        assert not result['complete'] and result['warnings']
        assert not gateway.validate_complete()
    asyncio.run(check())


def test_main_stream_does_not_publish_child_or_summary_text(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        class ProjectionGraph:
            finished = False
            async def aget_state(self, config):
                return SimpleNamespace(next=(), values={'messages': [AIMessage(content='主回答')]} if self.finished else {})
            async def astream_events(self, *args, **kwargs):
                assert kwargs['version'] == 'v3'
                return self
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def __aiter__(self):
                run = service.store.list('agent_run')[0]
                for origin, purpose, content in [(run['id'], 'summary', '不得显示的摘要'), ('child', 'agent', '不得显示的子任务'), (run['id'], 'citation_repair', '不得显示的修复'), (run['id'], 'agent', '主回答')]:
                    metadata = {'langgraph_node': 'model', 'wechat_run_id': origin, 'wechat_purpose': purpose}
                    for payload in [{'event':'message-start', 'id':purpose},
                        {'event':'content-block-delta', 'delta':{'type':'reasoning-delta','reasoning':'不得显示的思考'}},
                        {'event':'content-block-delta', 'delta':{'type':'text-delta','text':content}}]:
                        yield {'method':'messages', 'params':{'namespace':[], 'data':(payload, metadata)}}
                self.finished = True
        monkeypatch.setattr(service, 'graph', lambda run, saver: (ProjectionGraph(), ChatGateway(service, run['id'], run['version'])))
        _, run = await execute(service)
        assert run['answer'] == '主回答'
        timeline = service.run(run['id'])['timeline']
        assert not any('不得显示' in x.get('text', '') for x in timeline)
        assert run['status'] == 'completed'
    asyncio.run(check())


def test_supplement_cancels_pending_model_and_uses_new_checkpoint(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch)
    entered = None
    async def check():
        entered = asyncio.Event()
        calls = []
        async def stream(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                entered.set()
                await asyncio.Future()
            yield AIMessageChunk(content='按补充要求回答', id='new')
        client.astream = stream
        thread = await service.create_thread('account', '', '新的对话')
        first = await service.submit(thread['id'], 'account', {'text': '先解释能力', 'request_id': '1'})
        await asyncio.wait_for(entered.wait(), 3)
        service.update(first['id'], partial_answer='旧版本前缀', answer_continuations=3)
        new = await service.submit(thread['id'], 'account', {'text': '只用一句话', 'request_id': '2'})
        await asyncio.wait_for(service.workers[new['id']], 10)
        result = service.public_run(new['id'], 'account')
        assert new['id'] == first['id'] and result['version'] == 2
        assert result['status'] == 'completed' and result['answer'] == '按补充要求回答'
        assert len(calls) == 2
        assert '只用一句话' in str(calls[-1])
    asyncio.run(check())


def test_framework_summary_archives_history_and_retains_originals(tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from wechat_decrypt_tool.ai.agent_budget import input_limit
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        await gateway.select()
        gateway.save_messages([{'source': 'a' * 24, 'username': 'friend', 'time': 10, 'text': '可回查原文'}])
        client.responses.append(AIMessage(content='最终正文'))
        original_next = client.next
        def summary_or_answer(messages):
            if any('<history_fragment>' in str(m.content) for m in messages):
                client.requests.append(messages)
                return AIMessage(content='内部摘要：保留用户要求及原文路径')
            return original_next(messages)
        client.next = summary_or_answer
        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'summary.sqlite3')) as saver:
            graph, _ = service.graph(service.run(gateway.id), saver)
            config = {'configurable': {'thread_id': 'summary-test'}, 'callbacks': []}
            messages = [HumanMessage(content='需要概述')]
            for i in range(30):
                messages.extend([HumanMessage(content='历史要求' * 200), AIMessage(content='历史回答' * 200)])
            messages.append(HumanMessage(content='现在直接回答'))
            result = await graph.ainvoke({'messages': messages}, config)
        audits = service.store.list('usage')
        assert result['messages'][-1].content == '最终正文', ([(u['purpose'], u.get('error_type'), u.get('error_code')) for u in audits],
            [(len(ms), sum(len(str(m.content)) for m in ms)) for ms in client.requests], list(result))
        assert any(u['purpose'] == 'deepagents_summary' for u in audits)
        assert service.run(gateway.id)['evidence']['a' * 24]['text'] == '可回查原文'
        backend = TaskBackend(service, gateway.id, 1)
        manifests = [path for path in backend.files() if path.startswith('/context/history/') and path.endswith('/index.json')]
        assert manifests
        assert any('历史要求' in ''.join(backend.data(part['path'])['content']
            for part in json.loads(backend.data(path)['content'])['chunks']) for path in manifests)
    asyncio.run(check())


def test_business_report_uses_names_and_dates_instead_of_internal_fields():
    from wechat_decrypt_tool.ai.deep_validation import report_display_issues
    text = "根据元数据字段conversation_name为'群甲'。\n\n发送时间记录于 sent_at 字段。"
    assert len(report_display_issues(text, '完整总结活动')) == 2
    assert report_display_issues(text, '解释元数据字段') == []
    assert report_display_issues('群甲在2026年9月1日讨论了活动。', '完整总结活动') == []
    assert len(report_display_issues('存在相关讨论，共2条：', '完整总结活动')) == 1
    assert report_display_issues('程序已完整读取3027条消息。', '完整总结活动') == []
