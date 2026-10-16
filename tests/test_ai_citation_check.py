"""只校验有确定原文依据的直接引文错配，不冒充完整语义验收。"""
import pytest

from wechat_decrypt_tool.ai.agent_citation_check import check_quoted_sources, mask_code
from wechat_decrypt_tool.ai.agent_model import ActionFormatError

A, B, PERSON = 'a' * 24, 'b' * 24, 'c' * 24
QUOTE = '今晚明华有没有选手'
ORIGINALS = {A: {'text': QUOTE}, B: {'text': '家里经常吃'}}


@pytest.mark.parametrize('answer', [
    f'330问：“{QUOTE}”。[[{B}]]',
    f'| 邀约 | “{QUOTE}” | [[{B}]] |',
    f'- “{QUOTE}” [[{B}]]\n- 其他消息 [[{A}]]',
    f'1. “{QUOTE}” [[{B}]]\n2. 其他消息 [[{A}]]',
    f'“{QUOTE}” [[{B}]]\n\n前一条消息 [[{A}]]',
    f'"{QUOTE}" [[{B}]]',
])
def test_known_quote_with_wrong_message_is_rejected(answer):
    with pytest.raises(ActionFormatError) as error:
        check_quoted_sources(answer, ORIGINALS, {})
    assert str(error.value) == 'citation_mismatch'
    assert A in error.value.correction and QUOTE in error.value.correction
    assert error.value.fields == ['quoted_sources']


@pytest.mark.parametrize('answer', [
    f'“{QUOTE}” [[{A.upper()}]]',
    f'“今晚 明华 有没有选手” [[{A}]] [[{B}]]',
    f'“未能在原文中找到的改写” [[{B}]]',
    f'今晚有人询问明华是否组局。[[{B}]]',
    f'“{QUOTE}”',
    f'`“{QUOTE}”` [[{B}]]',
    f'```text\n“{QUOTE}” [[{B}]]\n```',
    f'~~~text\n“{QUOTE}” [[{B}]]\n~~~~',
    f'```text\n“{QUOTE}” [[{B}]]',
])
def test_valid_or_undetermined_binding_is_not_guessed(answer):
    check_quoted_sources(answer, ORIGINALS, {})


def test_person_capsule_uses_discussed_person_not_message_sender():
    originals = {A: {'text': '阿忠今天负责安排场地'}, B: {'text': '今天没有这个安排'}}
    refs = {PERSON: {'name': '阿忠', 'kind': 'person'}}
    quote = f'“[[person:{PERSON.upper()}]]今天负责安排场地”'
    check_quoted_sources(f'{quote} [[{A}]]', originals, refs)
    with pytest.raises(ActionFormatError):
        check_quoted_sources(f'{quote} [[{B}]]', originals, refs)


def test_old_prefix_remains_immutable_but_new_quotes_are_checked():
    prefix = f'“{QUOTE}” [[{B}]]，'
    check_quoted_sources(prefix + '继续说明。', ORIGINALS, {}, len(prefix))
    with pytest.raises(ActionFormatError):
        check_quoted_sources(prefix + f'新的引文：“{QUOTE}” [[{B}]]', ORIGINALS, {}, len(prefix))
    # 引文跨越停止点时不能通过重试改掉已显示的半句。
    check_quoted_sources(f'“{QUOTE}” [[{B}]]', ORIGINALS, {}, 4)


def test_code_mask_keeps_positions_and_does_not_consume_later_paragraph():
    answer = f'```text\n“{QUOTE}” [[{B}]]\n````\n\n“{QUOTE}” [[{B}]]'
    masked = mask_code(answer)
    assert len(masked) == len(answer)
    assert [i for i, c in enumerate(masked) if c == '\n'] == [i for i, c in enumerate(answer) if c == '\n']
    with pytest.raises(ActionFormatError):
        check_quoted_sources(answer, ORIGINALS, {})


def test_duplicate_actual_sources_do_not_force_one_arbitrary_id():
    originals = {**ORIGINALS, B: {'text': QUOTE}}
    check_quoted_sources(f'“{QUOTE}” [[{B}]]', originals, {})


def test_structured_note_sources_apply_to_each_paragraph():
    with pytest.raises(ActionFormatError):
        check_quoted_sources(f'“{QUOTE}”\n\n后续说明', ORIGINALS, {}, source_ids=[B])
    check_quoted_sources(f'“{QUOTE}”\n\n后续说明', ORIGINALS, {}, source_ids=[A])
