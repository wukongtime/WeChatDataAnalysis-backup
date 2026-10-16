"""最近 N 条剪枝使用原消息上界；合成数据仅用于自动化边界测试。"""
import asyncio
import hashlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat_decrypt_tool.ai.recent_bounds import query_bounds, recent_bounds
from wechat_decrypt_tool.ai.agent_tools import ChatTools


def test_batched_original_bounds_span_databases_and_preserve_empty_ranges(tmp_path):
    users = [f'group{i}' for i in range(140)]
    paths = [tmp_path / f'message_{i}.db' for i in range(2)]
    for index, path in enumerate(paths):
        with sqlite3.connect(path) as db:
            for i, user in enumerate(users):
                table = 'Msg_' + hashlib.md5(user.encode()).hexdigest()
                db.execute(f'CREATE TABLE "{table}" (create_time INTEGER)')
                db.executemany(f'INSERT INTO "{table}" VALUES (?)', [(0,), (100,), (10 + i % 80 + index,)])
    calls = []
    def execute(path, sql):
        calls.append(sql)
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql)]
    result = query_bounds(paths, execute, [*users, 'absent'], 10, 100, lambda: None)
    assert result == {**{u: 11 + i % 80 for i, u in enumerate(users)}, 'absent': None}
    assert len(calls) == 8  # 每个库一次目录、三批时间上界，而非每个会话重复打开消息流。
    assert query_bounds(paths, execute, users, 99, 100, lambda: None) == dict.fromkeys(users)


def test_incomplete_native_response_is_rejected():
    table = 'Msg_' + hashlib.md5(b'group').hexdigest()
    def execute(path, sql):
        return [{'name': table}] if 'sqlite_master' in sql else []
    with pytest.raises(ValueError, match='不完整'):
        query_bounds([Path('message.db')], execute, ['group'], 0, 100, lambda: None)


def test_query_failure_falls_back_but_cancel_is_not_swallowed(tmp_path):
    with patch('wechat_decrypt_tool.chat_helpers._resolve_account_dir', return_value=tmp_path), \
         patch('wechat_decrypt_tool.account_source_policy.account_prefers_decrypted_snapshot', return_value=True), \
         patch('wechat_decrypt_tool.chat_export_service._iter_message_db_paths', return_value=[tmp_path / 'missing.db']):
        assert recent_bounds('a', ['group'], 0, 100, lambda: None) is None
        calls = 0
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('用户已停止')
        with pytest.raises(ValueError, match='用户已停止'):
            recent_bounds('a', ['group'], 0, 100, checkpoint)


@pytest.mark.parametrize('sender', [None, 'wanted'])
@pytest.mark.parametrize('available', [True, False])
def test_pruning_matches_exhaustive_selection_with_ties_and_sender(sender, available):
    rows = [{'username': u, 'time': t, 'source': f'{i:024x}', 'sender_id': who}
            for i, (u, t, who) in enumerate([
                ('older', 2, 'wanted'), ('newer', 30, 'other'), ('newer', 20, 'wanted'),
                ('tie', 20, 'wanted'), ('tie', 20, 'wanted'), ('newer', 19, 'wanted')], 1)]
    users = ['older', 'tie', 'empty', 'newer']
    bounds = {u: max((r['time'] for r in rows if r['username'] == u), default=None) for u in users}
    reads, progress = [], []
    def pages(account, username, start, end, **kw):
        reads.append(username)
        selected = sorted([r for r in rows if r['username'] == username and start <= r['time'] <= end],
                          key=lambda r: (r['time'], r['source']))
        if kw.get('count'):
            selected = selected[-kw['count']:]
        yield {'messages': selected}
    with patch('wechat_decrypt_tool.ai.recent_bounds.recent_bounds', return_value=bounds if available else None), \
         patch('wechat_decrypt_tool.ai.messages.iter_message_pages', pages):
        result = asyncio.run(ChatTools().recent_set('a', users, 0, 31, 2, lambda: None,
                                                   sender=sender, on_progress=progress.append))
    expected = sorted([r for r in rows if not sender or r['sender_id'] == sender], key=lambda r: (r['time'], r['source']))[-2:]
    assert result['messages'] == expected
    assert reads == (['newer', 'tie'] if available else users)
    assert [p['completed_conversations'] for p in progress] == [1, 2, 3, 4]
