"""时间窗口必须完整推进；这些测试不调用模型或用户聊天数据。"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat_decrypt_tool.ai.agent_reading import read_window
from wechat_decrypt_tool.ai.agent_budget import size, message_payload


def message(index, timestamp, text='测试消息'):
    return {'source': f'{index:024x}', 'identity': f's:{index}', 'username': 'group',
            'time': timestamp, 'sender': '甲', 'text': text, 'anchor': str(index)}


def reader(messages):
    async def page(start, end, capacity, cursor):
        rows = [m for m in messages if start <= m['time'] < end and
                (not cursor or m['time'] > cursor['time'] or
                 (m['time'] == cursor['time'] and m['identity'] not in cursor['ids']))]
        result = []
        for m in rows:
            if result and size([message_payload(x) for x in [*result, m]]) > capacity:
                break
            result.append(m)
        return {'messages': result, 'has_more': len(result) < len(rows), 'source': 'synthetic'}
    return page


def test_empty_tail_finishes_without_persisting_doubling_steps():
    async def run():
        calls = []
        async def page(start, end, capacity, cursor):
            calls.append((start, end))
            return {'messages': [], 'has_more': False}
        result = await read_window(page, 0, 2**31, 1024, {'next_time': 150, 'window_seconds': 2})
        assert calls == [(150, 152), (152, 2**31)]
        assert result['complete'] and result['actual_range'] == {'start': 150, 'end': 2**31}
    asyncio.run(run())


def test_adjacent_windows_same_second_and_empty_intervals_have_no_loss():
    async def run():
        messages = [message(i, 5 if i < 50 else 9) for i in range(80)]
        state, received = None, []
        for _ in range(200):
            result = await read_window(reader(messages), 0, 10, 650, state)
            received.extend(m['source'] for m in result['messages'])
            state = result['next_state']
            if not result['has_more']:
                break
        else:
            pytest.fail('时间游标没有终止')
        assert received == [m['source'] for m in messages]
        assert len(received) == len(set(received))
    asyncio.run(run())


def test_long_message_fragments_reassemble_exactly():
    async def run():
        original = message(1, 3, '中文🧪内容\n' * 500)
        state, parts = None, []
        for _ in range(200):
            result = await read_window(reader([original]), 3, 4, 600, state)
            for item in result['messages']:
                assert item.get('text_offset', 0) == len(''.join(parts))
                parts.append(item['text'])
            state = result['next_state']
            if not result['has_more']:
                break
        assert ''.join(parts) == original['text']
    asyncio.run(run())


def test_failed_read_never_advances_caller_state():
    async def broken(*args):
        raise OSError('读取失败')
    state = {'next_time': 3, 'db_cursor': {'time': 3, 'ids': ['s:1']}}
    with pytest.raises(OSError):
        asyncio.run(read_window(broken, 0, 5, 500, state))
    assert state == {'next_time': 3, 'db_cursor': {'time': 3, 'ids': ['s:1']}}


def test_released_budget_expands_small_window_in_one_saved_step():
    async def run():
        messages = [message(i, i + 100) for i in range(100)]
        state = {'next_time': 100, 'window_seconds': 1}
        result = await read_window(reader(messages), 100, 200, 16000, state)
        assert len(result['messages']) > 20
        assert size([message_payload(m) for m in result['messages']]) <= 16000
        assert state == {'next_time': 100, 'window_seconds': 1}
        received = result['messages'][:]
        while result['has_more']:
            result = await read_window(reader(messages), 100, 200, 16000, result['next_state'])
            received.extend(result['messages'])
        assert [m['source'] for m in received] == [m['source'] for m in messages]
    asyncio.run(run())


def test_shrinking_after_partial_page_never_rewinds_past_message_cursor():
    async def run():
        messages = [message(i, i, '正文') for i in range(100)]
        capacity = size([message_payload(m) for m in messages[:50]])
        first = await read_window(reader(messages), 0, 100, capacity)
        # 正文预算刚好容纳 50 条，但分片元信息使本页在区间结束前停止。
        assert first['next_state']['db_cursor']['time'] > first['next_state']['next_time']
        received = first['messages'][:]
        state = first['next_state']
        for _ in range(200):
            result = await read_window(reader(messages), 0, 100, 750, state)
            if state.get('db_cursor'):
                assert result['actual_range']['start'] >= state['db_cursor']['time']
            received.extend(result['messages'])
            state = result['next_state']
            if not result['has_more']:
                break
        else:
            pytest.fail('预算缩小后游标没有完成')
        assert [m['source'] for m in received] == [m['source'] for m in messages]
    asyncio.run(run())


def test_adaptive_windows_keep_exact_messages_with_fewer_repeated_probes():
    async def read_all(retain_window):
        messages = [message(i, 10000 + i * 3) for i in range(180)]
        calls = 0
        original_reader = reader(messages)
        async def counted(*args):
            nonlocal calls
            calls += 1
            return await original_reader(*args)
        state, received = None, []
        for index in range(1000):
            # 模拟剩余预算减小和整理后释放，不能把上次窗口当成读取权限。
            capacity = 650 if index % 5 else 1400
            result = await read_window(counted, 0, 2000000, capacity, state)
            received.extend(m['source'] for m in result['messages'])
            state = result['next_state']
            if not result['has_more']:
                assert received == [m['source'] for m in messages]
                return calls
            assert state['next_time'] >= result['actual_range']['start']
            if not retain_window:
                state.pop('window_seconds', None)
        pytest.fail('时间窗口没有终止')
    adaptive = asyncio.run(read_all(True))
    original = asyncio.run(read_all(False))
    assert adaptive < original / 2
