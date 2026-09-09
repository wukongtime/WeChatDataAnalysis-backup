import sys
from pathlib import Path

import pytest

from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.local_search.catalog import model_spec
from wechat_decrypt_tool.local_search.gpu import GPUComponent, gpu_devices
from wechat_decrypt_tool.local_search.inference import LocalInference


@pytest.mark.parametrize('strategy', ['cpu', 'auto', 'cuda'])
def test_macos_cpu_does_not_attempt_windows_component(monkeypatch, strategy):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'is_file', lambda _: True)
    engine = LocalInference(gpu_root='stale-windows-component')
    engine.key = ('model', model_spec('bge-small-zh')['revision'], 'cpu', 0)

    class Pipe:
        def send(self, request): pass
        def close(self): pass

    engine.pipe = Pipe()
    monkeypatch.setattr(engine, '_receive', lambda *args: {'vectors': [[1., 0.]]})
    monkeypatch.setattr('wechat_decrypt_tool.local_search.inference.mp.get_context', lambda *args: pytest.fail('不应创建 GPU 工作进程'))
    engine.encode('model', model_spec('bge-small-zh'), ['合成消息'], strategy)
    assert engine.status['actual_device'] == 'cpu'
    assert engine.status['using_fallback'] == (strategy == 'cuda')
    assert not engine.gpu_failed
    if strategy != 'cuda': assert engine.status['reason'] == ''
    engine.close()


def test_macos_gpu_catalog_is_unavailable_without_calling_nvidia(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr('wechat_decrypt_tool.local_search.gpu.subprocess.run', lambda *a, **kw: pytest.fail('macOS 不执行 nvidia-smi'))
    engine = LocalInference()
    component = GPUComponent(tmp_path / 'component', AIStore(tmp_path / 'state'), engine)
    assert gpu_devices() == []
    assert component.status()['platform'] == 'darwin'
    assert not component.status()['supported']
    assert 'CPU' in component.status()['reason']
