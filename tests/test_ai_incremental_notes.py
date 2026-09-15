"""逐批提取必须保留早期事实；预读不能绕过同秒游标或跨任务复用。"""
import asyncio
import json

import pytest

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material
from wechat_decrypt_tool.ai.agent_notes import saved_notes, compact_batch_payload
from wechat_decrypt_tool.ai.agent_tools import ChatTools
from wechat_decrypt_tool.ai.messages import filter_after
from wechat_decrypt_tool.ai.agent_notes import check_inferred_weekdays, remove_wrong_date_expansions
from wechat_decrypt_tool.ai.agent_model import ActionFormatError
from wechat_decrypt_tool.ai.model_execution import model_policy
from wechat_decrypt_tool.ai.providers import ModelService
from wechat_decrypt_tool.ai.agent_notes import encode_answer_sources, decode_answer_sources, normalize_date_headings


def test_answer_aliases_roundtrip_without_rewriting_original_text():
    source = 'a' * 24
    payload = {'evidence': [{'source': source, 'text': source}], 'summary': {'items': [{'sources': [source]}]}}
    encoded, aliases = encode_answer_sources(payload, [source])
    assert encoded['evidence'][0] == {'source': 's1', 'text': source}
    assert encoded['summary']['items'][0]['sources'] == ['s1']
    prefix = '原文[[s'
    assert decode_answer_sources(prefix, aliases) == prefix
    assert decode_answer_sources(prefix + '1]]', aliases) == '原文[[' + source + ']]'
    assert decode_answer_sources('[[s999]]', aliases) == '[[s999]]'
    assert decode_answer_sources('[[s1], [s1]]', aliases) == '[[' + source + ']] [[' + source + ']]'
    assert decode_answer_sources('[[s1], [s999]]', aliases) == '[[s1], [s999]]'
    assert decode_answer_sources('[[s1, 普通文字]]', aliases) == '[[s1, 普通文字]]'
    from wechat_decrypt_tool.ai.agent_notes import encode_citation_feedback
    feedback = json.dumps({'quote': '原文片段', 'candidate_sources': [source, 'b' * 24]}, ensure_ascii=False)
    restored = json.loads(encode_citation_feedback(feedback, aliases))
    assert restored == {'quote': '原文片段', 'candidate_sources': ['s1', 'b' * 24]}


def test_calendar_header_normalization_preserves_quoted_event_text():
    text = '### **2026年9月1日（星期一）**\n原文：“2026年9月1日（星期一）”。'
    assert normalize_date_headings(text) == text.replace('日（星期一）**', '日（星期二）**')
    from wechat_decrypt_tool.ai.agent_notes import answer_year
    run = {'time_range': {'start': 1788192000, 'end': 1789056000}, 'timezone_offset': 28800}
    short = '### **9月1日（周一）**\n原文：“9月1日（周一）”。'
    assert normalize_date_headings(short, answer_year(run)) == short.replace('日（周一）**', '日（星期二）**')
    assert normalize_date_headings(short) == short
    assert normalize_date_headings('#### **2026年9月1日 (星期一)**') == '#### **2026年9月1日 (星期二)**'
    assert answer_year({'time_range': {'start': 0, 'end': 1789056000}}) is None




def test_auxiliary_thinking_control_is_scoped_and_preserves_explicit_effort():
    profile = {'protocol': 'openai', 'base_url': 'https://api.xiaomimimo.com/v1', 'model': 'mimo-v2.5'}
    with model_policy(auxiliary=True):
        assert ModelService.client(profile).extra_body == {'thinking': {'type': 'disabled'}}
        assert not ModelService.client({**profile, 'base_url': 'https://proxy.example/v1'}).extra_body
        explicit = ModelService.client({**profile, 'reasoning_effort': 'high'})
        # 显式档位应启用 MiMo 思考，不能被辅助请求的默认关闭策略覆盖。
        assert explicit.extra_body == {'thinking': {'type': 'enabled'}}
        assert explicit.reasoning_effort == 'high'
    assert not ModelService.client(profile).extra_body


def test_invented_weekday_date_is_rejected_but_original_conflict_is_preserved():
    rows = {'s': {'time': 1788225830, 'text': '周三晚八点'}}
    with pytest.raises(ActionFormatError, match='inferred_calendar_mismatch'):
        check_inferred_weekdays('周三（9月3日）约球', rows, ['s'], 28800)
    check_inferred_weekdays('周三（9月2日）约球', rows, ['s'], 28800)
    rows['s']['text'] = '周三（9月3日）'
    check_inferred_weekdays('原文写周三（9月3日），时间有矛盾', rows, ['s'], 28800)


def test_compact_batch_preserves_text_fragments_and_distinct_sender_identity():
    originals = [{'source': str(i) * 24, 'username': 'group', 'sender_id': f'user{i}', 'sender': '同名',
                  'text': '完整正文🙂', 'sent_at': '2026-09-01T08:00:00+08:00', 'text_offset': 12,
                  'next_text_offset': 18} for i in (1, 2)]
    payload, mapping = compact_batch_payload({'evidence': originals, 'objective': '按时间整理'})
    assert mapping == {'m1': originals[0]['source'], 'm2': originals[1]['source']}
    assert payload['evidence'][0]['person'] != payload['evidence'][1]['person']
    assert payload['evidence'][0]['sender'] == '同名'
    for before, after in zip(originals, payload['evidence']):
        assert all(before[k] == after[k] for k in ('text', 'sent_at', 'text_offset', 'next_text_offset'))


def test_wrong_expansion_is_removed_without_guessing_an_activity_date():
    rows = {'s': {'time': 1788225830, 'text': '周三晚八点'}}
    result, changes = remove_wrong_date_expansions('周三（9月3日）约球', rows, ['s'], 28800)
    assert result == '周三约球' and len(changes) == 1
    assert remove_wrong_date_expansions('周三（9月2日）约球', rows, ['s'], 28800)[0] == '周三（9月2日）约球'
    rows['s']['text'] = '周三（9月3日）晚八点'
    assert remove_wrong_date_expansions('原文写周三（9月3日）', rows, ['s'], 28800)[1] == []
    rows['s']['text'] = '有空再约'
    assert remove_wrong_date_expansions('周三（9月3日）约球', rows, ['s'], 28800)[1] == []




@pytest.mark.parametrize('capacity', [1000, 3000])
def test_prefetch_reuses_local_page_with_exact_same_second_coverage(monkeypatch, capacity):
    from wechat_decrypt_tool.ai import messages
    rows = [{**material(i, text='测试原文' * 4), 'time': 10, 'identity': f's:{i}'} for i in range(1, 101)]
    calls = []
    def pages(account, username, start, end, **kwargs):
        calls.append((account, kwargs.get('cursor')))
        selected = filter_after(rows, kwargs['cursor']) if kwargs.get('cursor') else rows
        yield {'messages': selected, 'has_more': False, 'source': 'realtime', 'name': username}
    monkeypatch.setattr(messages, 'iter_message_pages', pages)
    async def run():
        tools = ChatTools()
        state, actual = None, []
        for _ in range(150):
            page = await tools.time_window('account', 'friend', 10, 11, capacity, state, session='run:1')
            actual.extend(m['source'] for m in page['messages'])
            state = page['next_state']
            if not state:
                break
        assert actual == [r['source'] for r in rows]
        assert len(calls) == 1
        await tools.time_window('account', 'friend', 10, 11, capacity, session='other:1')
        assert len(calls) == 2
        tools.release_read_session('run')
        assert all(key[0] != 'run:1' for key in tools._time_pages)
    asyncio.run(run())
