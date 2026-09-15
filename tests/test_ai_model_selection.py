"""验证全局模型保存、删除后的空选择和当前轮次模型快照。"""
import asyncio
from unittest.mock import Mock

import httpx
from fastapi import FastAPI

from wechat_decrypt_tool.ai.model_selection import selected_model
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.routers import ai
from test_ai_deepagents import make_service


def test_selected_model_api_persists_migrates_and_clears_deleted_service(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    monkeypatch.setattr(ai, 'get_ai_service', lambda: service.ai)
    monkeypatch.setattr(service.ai.models.metadata, 'refresh_in_background', lambda: None)
    service.ai.models.metadata.remember(service.store.get('profile', 'model'), [{'id': 'manual-model', 'reasoning_efforts': ['high']}])
    app = FastAPI(); app.include_router(ai.router)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1)), base_url='http://localhost') as client:
            settings = (await client.get('/api/ai/settings')).json()
            assert settings['selected_model']['profile_id'] == 'model'
            choice = {'profile_id': 'model', 'model_id': 'manual-model', 'reasoning_effort': 'high'}
            response = await client.put('/api/ai/selected-model', json=choice)
            assert response.status_code == 200, response.text
            assert response.json() == choice
            assert selected_model(AIStore(tmp_path)) == choice
            assert service.store.get('profile', 'model')['model'] == 'fixture'
            assert service.store.get('defaults', 'global')['text'] == 'model'
            assert 'never-save-secret' not in (await client.get('/api/ai/settings')).text
            assert (await client.put('/api/ai/selected-model', json={**choice, 'profile_id': 'missing'})).status_code == 404
            assert (await client.put('/api/ai/selected-model', json={**choice, 'reasoning_effort': 'invalid'})).status_code == 422
            assert selected_model(service.store) == choice
            service.store.put('profile', {**service.store.get('profile', 'model'), 'id': 'other'}, id='other')
            assert (await client.delete('/api/ai/profiles/model')).status_code == 200
            assert (await client.get('/api/ai/settings')).json()['selected_model'] == {'unavailable': True}
            assert selected_model(AIStore(tmp_path)) == {'unavailable': True}
    asyncio.run(check())


def test_unknown_alternate_model_does_not_inherit_image_support(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    raw = service.store.get('profile', 'model')
    service.store.put('profile', {**raw, 'vision': True, 'model_overrides': {'vision': True}}, id='model')
    assert service.ai.models.resolve_turn('model')['vision'] is True
    assert service.ai.models.resolve_turn('model', 'unknown-model')['vision'] is False


def test_first_service_and_legacy_default_bootstrap(tmp_path):
    store = AIStore(tmp_path)
    assert selected_model(store) == {}
    store.put('profile', {'model': 'first'}, id='first')
    store.put('defaults', {'text': 'missing'}, id='global')
    assert selected_model(store)['model_id'] == 'first'
    store.put('profile', {'model': 'second'}, id='second')
    assert selected_model(store)['profile_id'] == 'first'


def test_turn_uses_selected_model_and_never_legacy_vision(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    service.launch = Mock()
    raw = service.store.get('profile', 'model')
    service.store.put('profile', {**raw, 'id': 'old-vision', 'vision': True}, id='old-vision')
    service.store.put('defaults', {'text': 'model', 'vision': 'old-vision'}, id='global')
    service.ai.models.metadata.remember(raw, [{'id': 'image-model', 'vision': True, 'limit': {'context': 32768}}])
    async def check():
        thread = await service.create_thread('account', 'friend', '新的对话')
        first = await service.submit(thread['id'], 'account', {'text': '你好', 'request_id': 'first'})
        assert first['vision'] == {}
        # 运行中的补充不更换模型。
        supplement = await service.submit(thread['id'], 'account', {'text': '补充', 'request_id': 'second', 'profile_id': 'model', 'model_id': 'image-model'})
        assert supplement['profile']['model'] == 'fixture' and supplement['vision'] == {}
        service.update(first['id'], status='completed')
        service.store.put('selected_model', {'profile_id': 'model', 'model_id': 'image-model'}, id='global')
        next_run = await service.submit(thread['id'], 'account', {'text': '新问题', 'request_id': 'third'})
        assert next_run['profile']['model'] == 'image-model'
        assert next_run['vision']['model'] == 'image-model'
        assert service.profile(next_run, True)['api_key'] == raw['api_key']
    asyncio.run(check())
