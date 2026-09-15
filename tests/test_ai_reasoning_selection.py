"""目录档位、服务隔离、真实 SDK 请求参数和跨轮保存回归，不调用付费模型。"""
import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import HumanMessage

from wechat_decrypt_tool.ai.model_reasoning import controls, request_options, validate
from wechat_decrypt_tool.ai.model_selection import selected_model
from wechat_decrypt_tool.ai.providers import ModelService, ProviderFailure, parse_model_catalog
from wechat_decrypt_tool.ai.storage import AIStore
from wechat_decrypt_tool.routers import ai
from test_ai_deepagents import make_service


def configured(tmp_path, protocol='openai', url='https://api.openai.com/v1', declared=None):
    service = ModelService(AIStore(tmp_path))
    service.metadata.data = {'fixture-provider': {'api': url, 'models': {
        'fixture': {'name': '测试模型', 'reasoning_options': declared or [{'type': 'effort', 'values': ['low', 'medium', 'high', 'max']}], 'limit': {'context': 32768, 'output': 16384}},
        'toggle-only': {'reasoning_options': [{'type': 'toggle'}]},
    }}}
    service.store.put('profile', {'provider': 'fixture-provider', 'model': 'fixture', 'base_url': url,
        'protocol': protocol, 'api_key': 'test-only'}, id='p')
    return service


def test_catalog_levels_manual_priority_and_endpoint_isolation(tmp_path):
    service = configured(tmp_path)
    raw = service.store.get('profile', 'p')
    assert service.resolve_turn('p', reasoning_effort='max')['reasoning_effort'] == 'max'
    # 同名模型可以有基础资料，但未知代理不能继承官方请求参数。
    proxy = service.metadata.enrich({**raw, 'base_url': 'https://proxy.example/v1'})
    assert proxy['model_metadata']['reasoning_controls']['efforts'] == []
    service.store.put('profile', {**raw, 'model_overrides': {'reasoning_efforts': ['low', 'high']}}, id='p')
    assert service.resolve('p')['model_metadata']['reasoning_controls']['efforts'] == ['low', 'high']
    with pytest.raises(ProviderFailure): service.resolve_turn('p', reasoning_effort='max')
    with pytest.raises(ProviderFailure): service.resolve_turn('p', 'unknown', 'high')
    service.store.put('profile', {**raw, 'model_overrides': {'reasoning_efforts': []}}, id='p')
    with pytest.raises(ProviderFailure): service.resolve_turn('p', reasoning_effort='high')


@pytest.mark.parametrize('provider,url,protocol', [
    ('openai', 'https://api.openai.com/v1', 'openai'), ('anthropic', 'https://api.anthropic.com', 'anthropic'),
    ('google', 'https://generativelanguage.googleapis.com/v1beta/openai', 'openai'), ('groq', 'https://api.groq.com/openai/v1', 'openai'),
])
def test_native_catalog_without_api_field_still_exposes_levels(tmp_path, provider, url, protocol):
    service = configured(tmp_path, protocol, url)
    entry = service.metadata.data['fixture-provider']
    entry.pop('api')
    service.metadata.data = {provider: entry}
    raw = service.store.get('profile', 'p')
    service.store.put('profile', {**raw, 'provider': provider}, id='p')
    assert service.resolve_turn('p', reasoning_effort='high')['reasoning_effort'] == 'high'


def test_same_host_coding_endpoint_uses_its_own_catalog(tmp_path):
    service = configured(tmp_path, url='https://open.bigmodel.cn/api/paas/v4')
    normal = service.metadata.data['fixture-provider']
    service.metadata.data = {'zhipuai': normal, 'zhipuai-coding-plan': {**normal, 'api': 'https://open.bigmodel.cn/api/coding/paas/v4',
        'models': {'fixture': {'reasoning_options': [{'type': 'effort', 'values': ['low', 'high']}]}}}}
    p = service.store.get('profile', 'p')
    p.update(base_url='https://open.bigmodel.cn/api/coding/paas/v4', provider='zhipu')
    service.store.put('profile', p, id='p')
    assert service.resolve('p')['model_metadata']['reasoning_controls']['efforts'] == ['low', 'high']


@pytest.mark.parametrize('protocol,url,choice,expected', [
    ('openai', 'https://api.openai.com/v1', {'reasoning_effort': 'high'}, {'reasoning_effort': 'high'}),
    ('openai', 'https://api.deepseek.com/v1', {'reasoning_effort': 'max'}, {'reasoning_effort': 'max', 'extra_body': {'thinking': {'type': 'enabled'}}}),
    ('openai', 'https://api.deepseek.com/v1', {'thinking_mode': 'disabled'}, {'extra_body': {'thinking': {'type': 'disabled'}}}),
    ('openai', 'https://api.xiaomimimo.com/v1', {'thinking_mode': 'enabled'}, {'extra_body': {'thinking': {'type': 'enabled'}}}),
    ('openai', 'https://api.moonshot.cn/v1', {'thinking_mode': 'disabled'}, {'extra_body': {'thinking': {'type': 'disabled'}}}),
    ('openai', 'https://open.bigmodel.cn/api/paas/v4', {'thinking_mode': 'disabled'}, {'extra_body': {'thinking': {'type': 'disabled'}}}),
    ('openai', 'https://ark.cn-beijing.volces.com/api/v3', {'thinking_mode': 'disabled'}, {'extra_body': {'thinking': {'type': 'disabled'}}}),
    ('openai', 'https://api.siliconflow.cn/v1', {'thinking_budget': 2048}, {'extra_body': {'enable_thinking': True, 'thinking_budget': 2048}}),
    ('openai', 'https://dashscope.aliyuncs.com/compatible-mode/v1', {'thinking_budget': 2048}, {'extra_body': {'enable_thinking': True, 'thinking_budget': 2048}}),
    ('openai', 'https://openrouter.ai/api/v1', {'reasoning_effort': 'high'}, {'extra_body': {'reasoning': {'effort': 'high'}}}),
    ('openai', 'https://openrouter.ai/api/v1', {'thinking_budget': 2048}, {'extra_body': {'reasoning': {'max_tokens': 2048}}}),
    ('openai', 'https://generativelanguage.googleapis.com/v1beta/openai', {'thinking_budget': 2048}, {'extra_body': {'google': {'thinking_config': {'thinking_budget': 2048}}}}),
    ('anthropic', 'https://api.anthropic.com', {'reasoning_effort': 'high'}, {'output_config': {'effort': 'high'}}),
    ('anthropic', 'https://api.anthropic.com', {'thinking_budget': 2048}, {'thinking': {'type': 'enabled', 'budget_tokens': 2048}}),
])
def test_sdk_payload_uses_provider_format_and_reset_omits_override(tmp_path, protocol, url, choice, expected):
    declared = [{'type': 'effort', 'values': ['low', 'high', 'max']}, {'type': 'toggle'}, {'type': 'budget_tokens', 'min': 1024}]
    service = configured(tmp_path, protocol, url, declared)
    profile = service.resolve_turn('p', **choice)
    payload = service.client(profile)._get_request_payload([HumanMessage(content='测试')])
    for key, value in expected.items(): assert payload[key] == value
    default = service.resolve_turn('p')
    assert request_options(default) == {}
    restored = service.client(default)._get_request_payload([HumanMessage(content='测试')])
    for key in ('reasoning_effort', 'thinking', 'output_config', 'extra_body'): assert key not in restored


@pytest.mark.parametrize('choice', [
    {'effort': 'invented'}, {'mode': 'adaptive'}, {'budget': True}, {'budget': 1024.5},
    {'budget': 8192}, {'budget': 1}, {'effort': 'high', 'budget': 2048},
    {'effort': 'high', 'mode': 'disabled'}, {'budget': 2048, 'mode': 'disabled'},
])
def test_unsupported_or_conflicting_selection_rejected_before_model_call(tmp_path, choice):
    service = configured(tmp_path, url='https://openrouter.ai/api/v1', declared=[{'type': 'effort', 'values': ['high']}, {'type': 'toggle'}, {'type': 'budget_tokens', 'min': 1024}])
    with pytest.raises(ProviderFailure): validate(service.resolve('p'), **choice)


def test_budget_respects_actual_output_capacity_and_unsupported_wire(tmp_path):
    meta = {'reasoning_options': [{'type': 'budget_tokens', 'min': 1024}], 'limit': {'context': 8192, 'output': 2000}}
    assert controls({'protocol': 'anthropic'}, meta)['budget'] == {'min': 1024, 'max': 1999}
    assert controls({'protocol': 'openai', 'base_url': 'https://unknown.example'}, meta)['budget'] is None
    # reasoning=true 不是可调档位；目录/上游不声明时保留默认。
    assert not controls({}, {'reasoning': True})['adjustable']
    item = parse_model_catalog({'data': [{'id': 'native', 'reasoning_options': [{'type': 'effort', 'values': ['low', 'high']}, {'type': 'budget_tokens', 'min': True}]}]})[0]
    assert item['reasoning_options'] == [{'type': 'effort', 'values': ['low', 'high']}]


def test_capability_endpoint_saved_selection_restart_and_turn_snapshot(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    service.launch = Mock()
    monkeypatch.setattr(ai, 'get_ai_service', lambda: service.ai)
    async def no_network(): pass
    monkeypatch.setattr(service.ai.models.metadata, 'refresh', no_network)
    raw = service.store.get('profile', 'model')
    raw.update(base_url='https://openrouter.ai/api/v1')
    service.store.put('profile', raw, id='model')
    service.ai.models.metadata.remember(raw, [{'id': 'fixture', 'reasoning_options': [{'type': 'toggle'}, {'type': 'budget_tokens', 'min': 1024}]}])
    app = FastAPI(); app.include_router(ai.router)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1)), base_url='http://localhost') as client:
            cap = await client.get('/api/ai/profiles/model/model-capabilities?model_id=fixture')
            assert cap.status_code == 200
            assert cap.json()['metadata']['reasoning_controls']['budget']['min'] == 1024
            assert raw['api_key'] not in cap.text
            assert not (await client.get('/api/ai/profiles/model/model-capabilities?model_id=unknown')).json()['metadata']['reasoning_controls']['adjustable']
            choice = {'profile_id': 'model', 'model_id': 'fixture', 'reasoning_effort': None, 'thinking_budget': 2048}
            response = await client.put('/api/ai/selected-model', json=choice)
            assert response.status_code == 200, response.text
            assert selected_model(AIStore(tmp_path)) == choice
            restarted = ModelService(AIStore(tmp_path))
            assert restarted.resolve_turn('model', thinking_budget=2048)['thinking_budget'] == 2048
            assert (await client.put('/api/ai/selected-model', json={**choice, 'thinking_budget': True})).status_code == 422
            assert selected_model(service.store) == choice
            thread = await service.create_thread('account', 'friend', '测试')
            run = await service.submit(thread['id'], 'account', {'text': '开始', 'request_id': 'one'})
            assert run['profile']['thinking_budget'] == 2048
            off = {**choice, 'thinking_budget': None, 'thinking_mode': 'disabled'}
            assert (await client.put('/api/ai/selected-model', json=off)).status_code == 200
            supplement = await service.submit(thread['id'], 'account', {'text': '补充', 'request_id': 'two'})
            assert supplement['profile']['thinking_budget'] == 2048
            service.update(run['id'], status='completed')
            following = await service.submit(thread['id'], 'account', {'text': '下一轮', 'request_id': 'three'})
            assert following['profile']['thinking_mode'] == 'disabled'
            assert following['profile']['thinking_budget'] is None
            reset = {**choice, 'thinking_budget': None}
            assert (await client.put('/api/ai/selected-model', json=reset)).status_code == 200
            assert selected_model(AIStore(tmp_path)) == {key: value for key, value in choice.items() if key != 'thinking_budget'}
    asyncio.run(check())
