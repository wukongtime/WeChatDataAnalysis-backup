"""不同电脑和运行中内存变化下的批量保护。"""
from types import SimpleNamespace

import pytest

from wechat_decrypt_tool.local_search.reading import choose_read_batch_size


@pytest.mark.parametrize('total,available,requested,expected', [
    (4, 2, 0, 100),
    (8, 5, 0, 500),
    (16, 8, 0, 1000),
    (64, 40, 0, 1000),
    (32, 0.5, 0, 100),
    (32, 2, 2000, 500),
    (32, 8, 2000, 2000),
    (32, 8, 100, 100),
])
def test_memory_limits(total, available, requested, expected, monkeypatch):
    monkeypatch.setattr('psutil.virtual_memory', lambda: SimpleNamespace(total=total * 1024**3, available=available * 1024**3))
    assert choose_read_batch_size(requested) == expected


def test_memory_pressure_is_rechecked_and_failed_probe_is_conservative(monkeypatch):
    memory = SimpleNamespace(total=32 * 1024**3, available=8 * 1024**3)
    monkeypatch.setattr('psutil.virtual_memory', lambda: memory)
    assert choose_read_batch_size(2000) == 2000
    memory.available = 512 * 1024**2
    assert choose_read_batch_size(2000) == 100
    def unavailable():
        raise OSError('系统信息不可用')
    monkeypatch.setattr('psutil.virtual_memory', unavailable)
    assert choose_read_batch_size() == 100
