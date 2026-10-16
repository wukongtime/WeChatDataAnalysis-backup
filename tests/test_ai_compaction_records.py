"""压缩提示的用量顺序、摘要持久化与历史访问隔离。"""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain.agents.middleware.types import ModelRequest

from test_ai_deepagents import make_service
from test_ai_deep_contracts import prepared
from test_ai_sawtooth import middleware, batch
from wechat_decrypt_tool.ai.deep_backend import TaskBackend
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.ai.agent_service import AgentService
from wechat_decrypt_tool.ai.service import AIService
from wechat_decrypt_tool.routers import ai_agent


def client_for(service, monkeypatch):
    monkeypatch.setattr(ai_agent, 'get_agent_service', lambda: service)
    monkeypatch.setattr(ai_agent, 'account_name', lambda value: value)
    app = FastAPI()
    app.dependency_overrides[ai_agent.local_only] = lambda: None
    app.include_router(ai_agent.router)
    return TestClient(app)


def test_compaction_high_water_and_individual_summaries_survive_restart(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    events, jobs = [], []
    async def check():
        gateway = await prepared(service)
        backend = TaskBackend(service, gateway.id, gateway.version)
        def progress(job_id, text, status, details):
            events.append((status, details.copy()))
            assert 'summary' not in details, 'SSE 不重复携带长摘要'
            service.timeline_item(gateway.id, 'notice', text, item_id='context:' + job_id, status=status, context_job=details)
        mw = middleware(backend, model_window=24000, publish=lambda used: events.append(('usage', used)), progress=progress)
        async def summarize(request, selected, manifest):
            assert events[-1][0] == 'usage', '调用摘要模型前必须已推送本次高水位'
            assert events[-1][1] == events[-2][1]['before']
            return f'第 {len(jobs) + 1} 次摘要：报价100元。'
        monkeypatch.setattr(mw, 'summarize_prefix', summarize)
        request = ModelRequest(model=mw.model, messages=batch(), state={})
        for _ in range(2):
            await mw.compact(request, request.messages)
            job = service.workspace.get(gateway.id, gateway.version, 'context:event')['context_revision']
            jobs.append(job)
        assert events[-1][0] == 'usage' and events[-1][1] < events[-2][1]['before']
        # 长任务后重启仍可看到每次分隔，不能只剩最新压缩。
        for i in range(205):
            service.timeline_item(gateway.id, 'notice', f'第{i}步')
        service.update(gateway.id, status='completed', version=gateway.version + 1)
        return gateway.id, gateway.version
    run_id, version = asyncio.run(check())
    restored = AgentService(AIService(AIStore(tmp_path)))
    client = client_for(restored, monkeypatch)
    for i, job in enumerate(jobs):
        response = client.get(f'/api/ai/agent/runs/{run_id}/context-compactions/{job}', params={'account': 'account', 'version': version})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['summary'] == f'第 {i + 1} 次摘要：报价100元。'
        assert data['model_window'] == 24000 and data['before'] > data['after']
    timeline = restored.public_run(run_id, 'account')['timeline']
    assert len([item for item in timeline if item.get('context_job')]) == 2
    path = f'/api/ai/agent/runs/{run_id}/context-compactions/{jobs[0]}'
    for query in ({'account': 'other', 'version': version}, {'account': 'account', 'version': version + 1}, {'account': 'account', 'version': version + 2}):
        assert client.get(path, params=query).status_code == 404
    assert client.get(path.replace(run_id, 'foreign'), params={'account': 'account', 'version': version}).status_code == 404


@pytest.mark.parametrize('match', [True, False])
def test_legacy_record_only_reads_its_own_snapshot(tmp_path, monkeypatch, match):
    service, _ = make_service(tmp_path, monkeypatch)
    gateway = asyncio.run(prepared(service))
    service.workspace.put(gateway.id, gateway.version, 'context:job:old', 'context_compaction', {'id': 'old', 'status': 'completed', 'before': 1000, 'after': 300})
    service.workspace.put(gateway.id, gateway.version, 'context:event', 'context_snapshot', {'context_revision': 'old' if match else 'new', 'summary_message': {'data': {'content': '<compacted-summary>\n旧版摘要\n</compacted-summary>'}}})
    client = client_for(service, monkeypatch)
    response = client.get(f'/api/ai/agent/runs/{gateway.id}/context-compactions/old', params={'account': 'account', 'version': gateway.version})
    assert response.status_code == 200
    assert response.json()['summary'] == ('旧版摘要' if match else None)
