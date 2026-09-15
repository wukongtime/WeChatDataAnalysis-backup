"""新版完整运行链路：真实调度、持久化及预算，仅替换数据源与模型。"""
import asyncio
import json
from unittest.mock import patch

import pytest

from test_ai_agent import service, FakeTools
from test_ai_global_assistant import idle_run
from wechat_decrypt_tool.ai.agent_budget import request_size
from wechat_decrypt_tool.ai.agent_continuous import StageNotes
from wechat_decrypt_tool.ai.agent_context import ContextIntent
from wechat_decrypt_tool.ai.agent_reading import read_window
from wechat_decrypt_tool.ai.agent_schemas import AgentAction
from wechat_decrypt_tool.ai.agent_tools import ChatTools
from wechat_decrypt_tool.ai.messages import filter_after
from wechat_decrypt_tool.ai.agent_references import material_references, cited_references, valid_answer_references, normalize_answer_references


def test_known_untyped_reference_is_normalized_without_guessing_or_retyping_sources():
    source, person, image, unknown = (f'{i:024x}' for i in range(1, 5))
    refs = {person: {'id': person, 'kind': 'person', 'sources': [source]},
            image: {'id': image, 'kind': 'image', 'source': source},
            source: {'id': source, 'kind': 'person', 'sources': [source]}}
    text = f'[[{source}]] [[{person}]] [[{image}]] [[{unknown}]]'
    expected = f'[[{source}]] [[person:{person}]] [[image:{image}]] [[{unknown}]]'
    assert normalize_answer_references(text, {source}, refs) == expected
    assert normalize_answer_references(f'[[person:{image}]]', {source}, refs) == f'[[person:{image}]]'
    assert not valid_answer_references(expected, {source}, refs)
    assert normalize_answer_references(f'[[{person}]]', set(), refs) == f'[[{person}]]'










@pytest.mark.parametrize('kind', ['source', 'person', 'image'])
def test_continuation_checks_each_fragment_and_rejects_restart_or_unclosed_reference(kind):
    from wechat_decrypt_tool.ai.agent_references import valid_answer_continuation
    source, ref_id = 'a' * 24, 'b' * 24
    evidence = {source: {}}
    refs = {ref_id: {'kind': kind, 'sources': [source], 'source': source}}
    marker = f'[[{source}]]' if kind == 'source' else f'[[{kind}:{ref_id}]]'
    split = len(marker) - 10
    prefix = '# 已保存的完整标题\n\n原回答：' + marker[:split]
    end = marker[split:]
    for count in range(len(end)):
        assert valid_answer_continuation(prefix, end[:count], evidence, refs)
        assert not valid_answer_continuation(prefix, end[:count], evidence, refs, complete=True)
    assert valid_answer_continuation(prefix, end + '后续事实。', evidence, refs, complete=True)
    assert not valid_answer_continuation(prefix, '# 重新生成', evidence, refs)
    assert not valid_answer_continuation(prefix, end + '# 已保存的完整标题\n\n从头开始', evidence, refs)
    assert not valid_answer_continuation(prefix, end + '尚未闭合 [[aaaa', evidence, refs, complete=True)
    complete_prefix = '# 已保存的完整标题\n\n已有内容。'
    assert not valid_answer_continuation(complete_prefix, complete_prefix, evidence, refs)
    assert valid_answer_continuation(complete_prefix, '后续正常内容。', evidence, refs, complete=True)


























def material(index, username='friend', text=None):
    return {'source': f'{index:024x}', 'identity': f's:{index}', 'anchor': f'a:{index}', 'username': username,
            'sender': '甲', 'sender_id': 'person-a', 'time': 100 + index // 3,
            'text': text or f'第 {index} 条消息', 'media': {}}




def test_statistics_source_examples_are_bounded_and_restricted_to_current_material(service):
    async def run():
        _, task = await idle_run(service)
        rows = [{**material(i), 'sender_id': f'person-{i % 20}'} for i in range(1, 81)]
        from wechat_decrypt_tool.ai.deep_tools import ChatGateway
        ChatGateway(service, task['id'], task['version']).save_messages(rows)
        # 同一发送者的来源按时间、来源标识稳定选择，重建服务不改变。
        people = [f'person-{i}' for i in range(20)]
        first = service.workspace.statistics_sources(task['id'], people, limit=7)
        recovered = type(service)(service.ai, service.tools, service.model)
        assert first == recovered.workspace.statistics_sources(task['id'], people, limit=7)
        assert len(first) == 7
        assert len({row['sender_id'] for row in first}) == 7
        for row in first:
            expected = min((m for m in rows if m['sender_id'] == row['sender_id']), key=lambda m: (m['time'], m['source']))
            assert row['source'] == expected['source']
            assert row['username'] == expected['username']
            assert 'text' not in row
        assert recovered.workspace.statistics_sources('another-run', people) == []
        assert recovered.workspace.statistics_sources(task['id'], ['not-in-this-run']) == []
    asyncio.run(run())








class MemoryTools(FakeTools):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    async def time_window(self, account, username, start, end, capacity, state=None, checkpoint=None):
        async def page(lo, hi, budget, cursor):
            checkpoint()
            self.calls.append((username, lo, hi, cursor))
            rows = filter_after([m for m in self.rows if m['username'] == username and lo <= m['time'] < hi], cursor or {'time': 0, 'ids': []})
            return {'messages': rows[:7], 'has_more': len(rows) > 7, 'data_source': 'test_memory'}
        return await read_window(page, start, end, capacity, state)






def test_latest_n_is_global_after_sender_filter(service):
    rows = [material(i, 'friend' if i % 2 else 'another') for i in range(1, 40)]
    for m in rows:
        m['sender_id'] = 'wanted' if int(m['source'], 16) % 3 else 'other'
    def pages(account, username, start, end, **kw):
        selected = [m for m in rows if m['username'] == username and start <= m['time'] <= end]
        if kw.get('count'): selected = selected[-kw['count']:]
        yield {'messages': selected, 'name': username}
    async def run():
        with patch('wechat_decrypt_tool.ai.messages.iter_message_pages', pages):
            result = await ChatTools().recent_set('account', ['friend', 'another'], 0, 1000, 5, lambda: None, 'wanted')
        expected = sorted([m for m in rows if m['sender_id'] == 'wanted'], key=lambda m: (m['time'], m['source']))[-5:]
        assert [m['source'] for m in result['messages']] == [m['source'] for m in expected]
    asyncio.run(run())


def test_recent_selection_prunes_only_before_current_boundary_second():
    bounds = []
    rows = [{**material(1, 'friend'), 'time': 100}, {**material(2, 'friend'), 'time': 110},
            {**material(3, 'another'), 'time': 100}, {**material(4, 'another'), 'time': 1}]
    def pages(account, username, start, end, **kwargs):
        bounds.append((username, start))
        yield {'messages': [m for m in rows if m['username'] == username and start <= m['time'] <= end]}
    with patch('wechat_decrypt_tool.ai.messages.iter_message_pages', pages):
        result = asyncio.run(ChatTools().recent_set('a', ['friend', 'another'], 0, 200, 2, lambda: None))
    assert bounds == [('friend', 0), ('another', 100)]
    assert {m['source'] for m in result['messages']} == {rows[1]['source'], rows[2]['source']}






def test_references_separate_speaker_subject_and_image_with_ambiguous_names():
    m = material(1, text='甲提到了乙和同名的人')
    m.update(kind='image', media={'imageMd5': 'a' * 32})
    contacts = [{'username': 'person-b', 'name': '乙乙'}, {'username': 'x', 'name': '同名'}, {'username': 'y', 'name': '同名'}]
    m['text'] += '，乙乙需要核实'
    refs = material_references('account', [m], contacts)
    people = [r for r in refs.values() if r['kind'] == 'person']
    assert {r['username'] for r in people} == {'person-a', 'person-b'}
    image = next(r for r in refs.values() if r['kind'] == 'image')
    assert image['source'] == m['source'] and 'md5=' in image['path']
    assert refs == material_references('account', [m], contacts, json.loads(json.dumps(refs)))
    assert not cited_references(f"[[person:{image['id']}]]", refs)
    assert cited_references(f"[[image:{image['id']}]]", refs) == [image]
    assert not set(refs) & set(material_references('other-account', [m], contacts))
    assert valid_answer_references(f"[[image:{image['id']}]] [[{m['source']}]]", {m['source']: m}, refs)
    assert not valid_answer_references(f"[[person:{image['id']}]]", {m['source']: m}, refs)
    assert not valid_answer_references(f"[[image:{image['id']}]]", {}, refs)






