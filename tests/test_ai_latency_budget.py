"""大窗口、挂起请求及旧任务拆批恢复；使用假模型，不发送用户数据。"""
import asyncio
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material
from wechat_decrypt_tool.ai.agent_budget import size, active_budget
from wechat_decrypt_tool.ai.agent_continuous import StageNotes
from wechat_decrypt_tool.ai.agent_model import AgentModel, AgentFailure
from wechat_decrypt_tool.ai.model_execution import (
    MATERIAL_BATCH_BYTES, model_policy, ResegmentModelError, RetryAnalysisBatch,
)
from wechat_decrypt_tool.ai.providers import ModelService, ProviderFailure
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.ai.agent_reading import read_window
from wechat_decrypt_tool.ai.messages import filter_after


def test_provider_deadline_stops_hung_call_and_releases_slot(tmp_path):
    async def run():
        cancelled = asyncio.Event()
        class Client:
            async def ainvoke(self, *args, **kwargs):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        models = ModelService(AIStore(tmp_path))
        models.client = lambda profile: Client()
        started = time.monotonic()
        with model_policy(seconds=.05, split_on_failure=True):
            with pytest.raises(ResegmentModelError):
                await models.invoke({'id': 'test', 'model': 'test'}, '测试')
        assert time.monotonic() - started < 2
        from wechat_decrypt_tool.ai.model_scheduler import scheduler
        assert cancelled.is_set() and scheduler().active == 0
        rows = models.store.list('usage')
        assert len(rows) == 1 and rows[0]['status'] == 'failed'
        assert rows[0]['error_category'] == 'timeout' and not rows[0]['usage_known']
    asyncio.run(run())


def test_provider_deadline_includes_queue_without_starting_request(tmp_path):
    async def run():
        models = ModelService(AIStore(tmp_path))
        models.semaphore = asyncio.Semaphore(0)
        models.client = lambda profile: pytest.fail('排队超时不能创建请求')
        with model_policy(seconds=.02):
            with pytest.raises(ProviderFailure, match='等待时间'):
                await models.invoke({'id': 'test'}, '测试')
        assert len(models.store.list('usage')) == 1
    asyncio.run(run())


@pytest.mark.parametrize('entry', ['provider', 'decision', 'answer'])
def test_expired_timeout_does_not_retry_before_clock_tick(tmp_path, monkeypatch, entry):
    from wechat_decrypt_tool.ai import providers, agent_model

    # Windows 粗粒度时钟可能在超时回调后仍落在截止时间之前；
    # 只固定业务层时钟，事件循环继续使用真实时钟，稳定复现这一边界。
    module = providers if entry == 'provider' else agent_model
    now = time.monotonic()
    monkeypatch.setattr(module, 'time', SimpleNamespace(time=time.time, monotonic=lambda: now))
    monkeypatch.setattr(agent_model, 'DECISION_SECONDS', .02)
    monkeypatch.setattr(agent_model, 'ANSWER_SECONDS', .02)

    async def run():
        models = ModelService(AIStore(tmp_path))
        models.semaphore = asyncio.Semaphore(0)
        models.client = lambda profile: pytest.fail('截止后不能发起模型请求')
        with model_policy(seconds=.02):
            with pytest.raises(ProviderFailure):
                if entry == 'provider':
                    await models.invoke({'id': 'p', 'model': 'test'}, '测试')
                else:
                    await AgentModel(models).call({'id': 'p', 'model': 'test'}, [], 'account', decision=entry == 'decision')
        rows = models.store.list('usage')
        assert len(rows) == 1
        assert rows[0]['status'] == 'failed' and rows[0]['error_category'] == 'timeout'

    asyncio.run(run())


@pytest.mark.parametrize('status', [500, 401])
def test_note_service_failure_splits_but_authentication_does_not(tmp_path, status):
    async def run():
        class Failure(Exception):
            status_code = status
        class Client:
            async def ainvoke(self, *args, **kwargs):
                raise Failure('上游异常')
        models = ModelService(AIStore(tmp_path))
        models.client = lambda profile: Client()
        expected = ResegmentModelError if status == 500 else ProviderFailure
        with model_policy(split_on_failure=True):
            with pytest.raises(expected):
                await models.invoke({'id': 'test'}, '测试')
        rows = models.store.list('usage')
        assert len(rows) == 1 and rows[0]['http_status'] == status
    asyncio.run(run())


def test_continuous_stream_cannot_extend_total_deadline(tmp_path, monkeypatch):
    async def run():
        stopped = asyncio.Event()
        class Client:
            async def astream(self, *args, **kwargs):
                try:
                    while True:
                        yield AIMessageChunk(content='字')
                        await asyncio.sleep(.005)
                finally:
                    stopped.set()
        models = ModelService(AIStore(tmp_path))
        models.client = lambda profile: Client()
        monkeypatch.setattr('wechat_decrypt_tool.ai.agent_model.ANSWER_SECONDS', .05)
        deltas = []
        with pytest.raises(AgentFailure) as error:
            await AgentModel(models).call({'id': 'p', 'model': 'test'}, [], 'account', on_delta=deltas.append)
        assert error.value.detail['category'] == 'timeout'
        from wechat_decrypt_tool.ai.model_scheduler import scheduler
        assert deltas and stopped.is_set() and scheduler().active == 0
        assert len(models.store.list('usage')) == 1
    asyncio.run(run())


def test_buffered_stream_checks_deadline_even_without_async_suspension(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai import agent_model
    monkeypatch.setattr(agent_model, 'ANSWER_SECONDS', .015)
    emitted = []
    async def run():
        class Client:
            async def astream(self, *args, **kwargs):
                for _ in range(50):
                    yield AIMessageChunk(content='字')
        models = ModelService(AIStore(tmp_path))
        models.client = lambda profile: Client()
        def delta(text):
            emitted.append(text)
            # 模拟同步保存流式回答；生成器下一片已就绪，没有 await 调度点。
            time.sleep(.002)
        with pytest.raises(AgentFailure):
            await AgentModel(models).call({'id': 'p', 'model': 'test', 'protocol': 'openai'}, [], 'account', on_delta=delta)
        assert len(emitted) < 50
        assert len(models.store.list('usage')) == 1
    asyncio.run(run())






@pytest.mark.parametrize('capacity', [10000, 1500])
@pytest.mark.parametrize('media_size', [0, 100000])
def test_budgeted_prefix_uses_cursor_without_repeated_range_probes(capacity, media_size):
    async def run():
        rows = [material(i) for i in range(1, 101)]
        for row in rows:
            row['media'] = {'local_attachment_metadata': 'x' * media_size}
        calls, received, state = [], [], None
        async def page(start, end, budget, cursor):
            calls.append((start, end))
            remaining = filter_after([m for m in rows if start <= m['time'] < end], cursor or {'time': 0, 'ids': []})
            return {'messages': remaining[:10], 'has_more': len(remaining) > 10, 'budgeted_page': True}
        while True:
            before = len(calls)
            result = await read_window(page, 0, 1000, capacity, state)
            assert len(calls) == before + 1
            received.extend(m['source'] for m in result['messages'])
            state = result['next_state']
            if not result['has_more']:
                break
        assert received == [m['source'] for m in rows]
        if capacity == 10000:
            assert len(calls) == 10
    asyncio.run(run())
