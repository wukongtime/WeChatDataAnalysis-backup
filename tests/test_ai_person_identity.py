"""人物身份的元数据和歧义回归；不写入用户账号数据。"""
import sqlite3

import pytest

from wechat_decrypt_tool.ai.agent_references import material_references, reference_id


def message(**raw):
    return {'source': 'a' * 24, 'username': 'room@chatroom', 'anchor': 'db:table:1',
            'sender_id': 'speaker', 'sender': '发言人', 'text': '@同名 请确认', 'media': raw}


@pytest.mark.parametrize('metadata', [{'atUsernames': ['target']}, {'quoteUsername': 'target'}])
def test_explicit_identity_resolves_same_name_without_changing_sender(metadata):
    directory = [{'username': name, 'name': '同名'} for name in ('target', 'other')]
    refs = material_references('account', [message(**metadata)], directory)
    target = refs[reference_id('person', 'account', 'target')]
    assert target['mentioned_sources'] == ['a' * 24]
    assert reference_id('person', 'account', 'other') not in refs
    sender = refs[reference_id('person', 'account', 'speaker')]
    assert sender['name'] == '发言人' and not sender['mentioned_sources']
    restored = material_references('account', [message(**metadata)], directory, refs)
    assert restored == refs


def test_explicit_identity_uses_current_group_name_and_ignores_all_members_marker():
    directory = [{'username': 'target', 'name': '全局名字'},
                 {'username': 'target', 'name': '本群名片', 'conversation': 'room@chatroom'},
                 {'username': 'target', 'name': '其他群名片', 'conversation': 'other@chatroom'}]
    refs = material_references('account', [message(atUsernames=['target', 'notify@all'])], directory)
    assert refs[reference_id('person', 'account', 'target')]['name'] == '本群名片'
    assert reference_id('person', 'account', 'notify@all') not in refs
    unknown = material_references('account', [message(atUsernames=['unknown'])], directory)
    assert unknown[reference_id('person', 'account', 'unknown')]['name'] == 'unknown'


@pytest.mark.parametrize('text,expected', [('3300元', False), ('x330', False), ('330_2', False),
                                         ('请330确认', True), ('@330 请确认', True)])
def test_numeric_name_is_not_inferred_from_amount_or_longer_identifier(text, expected):
    refs = material_references('account', [{**message(), 'text': text}], [{'username': 'target', 'name': '330'}])
    assert (reference_id('person', 'account', 'target') in refs) is expected


@pytest.mark.parametrize('source_column', ['source', 'msg_source', None])
def test_readonly_snapshot_row_preserves_optional_mention_metadata(tmp_path, monkeypatch, source_column):
    from wechat_decrypt_tool import chat_export_service as reader
    path = tmp_path / 'message_0.db'
    xml = '<msgsource><atuserlist>target</atuserlist></msgsource>'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE Msg_test (local_id INTEGER, server_id INTEGER, local_type INTEGER, '
                   'sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER, message_content TEXT, '
                   'compress_content BLOB' + (f', {source_column} TEXT' if source_column else '') + ')')
        db.execute('INSERT INTO Msg_test VALUES (1,2,1,3,4,100,?,NULL' + (',?' if source_column else '') + ')',
                   ('@同名 请确认', xml) if source_column else ('@同名 请确认',))
    original = path.read_bytes()
    monkeypatch.setattr(reader, '_iter_message_db_paths', lambda _: [path])
    monkeypatch.setattr(reader, '_resolve_msg_table_name', lambda *args: 'Msg_test')
    monkeypatch.setattr(reader, 'resolve_account_self_username', lambda _: 'account')
    monkeypatch.setattr(reader, 'resolve_account_self_rowid', lambda *args, **kwargs: (None, ''))
    monkeypatch.setattr(reader, '_wcdb_resolve_account_native_wxid', lambda _: '')
    rows = list(reader._iter_rows_for_conversation(account_dir=tmp_path, conv_username='room@chatroom',
                                                   start_time=0, end_time=200))
    assert len(rows) == 1
    assert rows[0].msg_source == (xml.encode() if source_column else None)
    assert path.read_bytes() == original


def test_realtime_row_preserves_native_at_metadata(tmp_path, monkeypatch):
    from wechat_decrypt_tool import chat_export_service as reader
    monkeypatch.setattr(reader, 'resolve_account_self_username', lambda _: 'account')
    xml = '<msgsource><atuserlist>target</atuserlist></msgsource>'
    row = reader._normalize_realtime_message_item_for_export({'msg_source': xml, 'message_content': '@同名'},
        account_dir=tmp_path, conv_username='room@chatroom', self_username='account')
    assert row.msg_source == xml
