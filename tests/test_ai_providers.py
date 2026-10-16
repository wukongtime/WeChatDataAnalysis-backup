import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wechat_decrypt_tool.ai.providers import PRESETS, ModelService, ProviderFailure
from wechat_decrypt_tool.ai.schemas import Summary
from wechat_decrypt_tool.ai.storage import AIStore


@pytest.mark.parametrize("base,expected", [
    ("https://example.com/", "https://example.com/v1"),
    ("https://example.com/api/coding/v3", "https://example.com/api/coding/v3"),
    ("https://example.com/v1/chat/completions", "https://example.com/v1"),
    ("https://example.com/proxy/models", "https://example.com/proxy"),
    ("https://example.com/v1beta/openai/", "https://example.com/v1beta/openai"),
    ("https://example.com/v1beta/openai/models", "https://example.com/v1beta/openai"),
    ("https://example.com/v1beta/openai/chat/completions", "https://example.com/v1beta/openai"),
    ("https://example.com/v1beta/openai/responses", "https://example.com/v1beta/openai"),
    ("https://example.com/api/paas/v4/", "https://example.com/api/paas/v4"),
    ("https://example.com/compatible-mode/v1", "https://example.com/compatible-mode/v1"),
])
def test_upstream_model_url(base, expected):
    from wechat_decrypt_tool.ai.providers import model_base_url
    assert model_base_url(base) == expected


def test_model_payload_formats_and_capabilities():
    from wechat_decrypt_tool.ai.providers import parse_model_catalog
    entries = [" new-model ", {"model": "new-model"}, {"name": "picture", "input_modalities": ["text", "image"]}, {"id": "text", "capabilities": {"vision": False}}, None, {"id": ""}]
    expected = [{"id": "new-model", "vision": None}, {"id": "picture", "vision": True}, {"id": "text", "vision": False}]
    for payload in (entries, {"data": entries}, {"models": entries}, {"items": {"data": entries}}):
        parsed = parse_model_catalog(payload)
        assert [{key: item[key] for key in ('id', 'vision')} for item in parsed] == expected
        assert parsed[1]['modalities']['input'] == ['text', 'image']
    assert parse_model_catalog({"error": "unauthorized"}) == []


def test_anthropic_catalog_pagination_and_auth(tmp_path, monkeypatch):
    import httpx
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers["x-api-key"] == "dummy"
        assert request.url.path == "/v1/models"
        if request.url.params.get("after_id"):
            return httpx.Response(200, json={"data": [{"id": "next"}], "has_more": False})
        return httpx.Response(200, json={"data": [{"id": "first"}], "has_more": True, "last_id": "first"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = asyncio.run(ModelService(AIStore(tmp_path)).models({"base_url": "https://example.com", "protocol": "anthropic", "api_key": "dummy"}))
    assert result == ["first", "next"] and len(requests) == 2


def test_catalog_returns_and_persists_upstream_capabilities(tmp_path, monkeypatch):
    import httpx
    original = httpx.AsyncClient
    def respond(request):
        return httpx.Response(200, json={'data':[{'id':'fixture','context_length':64000,
            'top_provider':{'max_completion_tokens':8000},'architecture':{'input_modalities':['text']},
            'supported_parameters':['temperature','tools']}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    models = ModelService(AIStore(tmp_path))
    models.metadata.data = {'openai':{'models':{'fixture':{'reasoning':True,
        'limit':{'context':128000,'output':16384},'modalities':{'input':['text','image']}}}}}
    profile = {'id':'selected','model':'fixture','provider':'openai','protocol':'openai','base_url':'https://api.example/v1'}
    detail = asyncio.run(models.catalog(profile))[0]
    assert detail['limit'] == {'context':64000,'output':8000}
    assert detail['vision'] is False and detail['tool_call'] is True
    assert detail['structured_output'] is False
    models.store.put('profile',profile,id='selected')
    assert models.resolve('selected')['context_window'] == 64000


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p["provider"])
def test_real_langchain_adapter_against_local_mock(tmp_path, preset):
    protocol = preset["protocol"]
    base_path = urlparse(preset["base_url"]).path.rstrip("/") or "/v1"
    requests = []
    catalog_requests = []
    response_text = json.dumps({"overview": "测试总结", "topics": [], "conclusions": [], "todos": []}, ensure_ascii=False)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            catalog_requests.append(self.path)
            encoded = json.dumps({"data": [{"id": "test"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(encoded)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), body))
            if protocol == "anthropic":
                payload = {"id": "msg_test", "type": "message", "role": "assistant", "model": "test", "content": [{"type": "text", "text": response_text}], "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 20}}
            else:
                payload = {"id": "chatcmpl-test", "object": "chat.completion", "created": 1, "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}
            encoded = json.dumps(payload).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        service = ModelService(AIStore(tmp_path))
        # 只替换主机，保留各供应商真实的基础路径，防止模型列表与推理路径不一致。
        profile = {**preset, "id": "profile", "model": "test", "base_url": f"http://127.0.0.1:{server.server_port}" + urlparse(preset["base_url"]).path, "api_key": "" if preset["provider"] in {"ollama", "lmstudio"} else "dummy"}
        assert asyncio.run(service.models(profile)) == ["test"]
        assert catalog_requests == [base_path + "/models"]
        result = asyncio.run(service.invoke(profile, "资料：有人提出需要确认交付时间", Summary, account="account"))
        assert result["overview"] == "测试总结"
        assert len(requests) == 1
        assert requests[0][0] == base_path + ("/messages" if protocol == "anthropic" else "/chat/completions")
        assert service.store.list("usage", "account")[0]["usage"]["input_tokens"] == 10
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_authentication_error_is_sanitized_and_not_retried(tmp_path):
    calls = []
    class Client:
        async def ainvoke(self, *args, **kwargs):
            calls.append(1)
            error = RuntimeError("secret token in provider error")
            error.status_code = 401
            raise error
    service = ModelService(AIStore(tmp_path)); service.client = lambda p: Client()
    with pytest.raises(ProviderFailure) as error:
        asyncio.run(service.invoke({"id": "profile"}, "测试"))
    assert error.value.authentication
    assert "secret" not in str(error.value)
    assert len(calls) == 1
    audit = service.store.list("usage")[0]
    assert audit["status"] == "failed" and audit["http_status"] == 401
    assert audit["usage_known"] is False
    assert "secret" not in json.dumps(audit)


def test_invalid_json_retry_keeps_each_billable_attempt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from wechat_decrypt_tool.ai.providers import audit_task_id
    calls = []
    class Client:
        async def ainvoke(self, *args, **kwargs):
            calls.append(1)
            return SimpleNamespace(content='invalid' if len(calls) == 1 else '{"overview":"ok","topics":[],"conclusions":[],"todos":[]}', usage_metadata={"input_tokens": 12, "output_tokens": 3})
    async def no_wait(*args):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    service = ModelService(AIStore(tmp_path)); service.client = lambda p: Client()
    async def run():
        token = audit_task_id.set("task-1")
        try:
            await service.invoke({"id": "p", "model": "mock"}, "private chat", Summary, account="a")
        finally:
            audit_task_id.reset(token)
    asyncio.run(run())
    rows = service.store.list("usage")
    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"failed", "success"}
    assert all(r["task_id"] == "task-1" and r["usage_known"] for r in rows)
    assert sum(r["usage"]["input_tokens"] for r in rows) == 24
    assert "private chat" not in json.dumps(rows)


def test_cancelled_request_remains_in_audit(tmp_path):
    class Client:
        async def ainvoke(self, *args, **kwargs):
            raise asyncio.CancelledError()
    service = ModelService(AIStore(tmp_path)); service.client = lambda p: Client()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.invoke({"id": "p"}, "test"))
    row = service.store.list("usage")[0]
    assert row["status"] == "cancelled" and row["usage_known"] is False
    assert row["finished_at"] >= row["started_at"]


@pytest.mark.parametrize('bad', ['', 'private model text', '{"overview":123}'])
def test_schema_retry_adds_safe_feedback_and_explicit_json_mode(tmp_path, monkeypatch, bad):
    from types import SimpleNamespace
    calls = []
    class Client:
        async def ainvoke(self, messages, **kwargs):
            calls.append((list(messages), kwargs))
            return SimpleNamespace(content=bad if len(calls) == 1 else '{"overview":"ok","topics":[],"conclusions":[],"todos":[]}',
                usage_metadata={'input_tokens': 10, 'output_tokens': 2}, response_metadata={'finish_reason': 'stop'})
    async def no_wait(*args): pass
    monkeypatch.setattr(asyncio, 'sleep', no_wait)
    service = ModelService(AIStore(tmp_path)); service.client = lambda p: Client()
    result = asyncio.run(service.invoke({'id':'p', 'protocol':'openai', 'model_metadata':{'structured_output':True}}, 'private source', Summary))
    assert result['overview'] == 'ok'
    assert len(calls) == 2
    assert all(kwargs['response_format'] == {'type':'json_object'} for _, kwargs in calls)
    correction = calls[1][0][-1].content
    assert '上次结果未通过' in correction
    assert 'private model text' not in correction and 'private source' not in correction
    rows = service.store.list('usage')
    failed = next(r for r in rows if r['status'] == 'failed')
    assert failed['validation_errors'] and failed['response_chars'] == len(bad)
    assert failed['finish_reason'] == 'stop'
    assert 'private' not in json.dumps(rows)


def test_unsupported_json_mode_falls_back_without_changing_profile(tmp_path):
    from types import SimpleNamespace
    calls = []
    class Client:
        async def ainvoke(self, messages, **kwargs):
            calls.append(kwargs)
            if 'response_format' in kwargs:
                error = RuntimeError('unsupported'); error.status_code = 400
                raise error
            return SimpleNamespace(content='{"overview":"ok","topics":[],"conclusions":[],"todos":[]}', usage_metadata={})
    profile = {'id':'p', 'protocol':'openai', 'model_metadata':{'structured_output':True}}
    service = ModelService(AIStore(tmp_path)); service.client = lambda p: Client()
    assert asyncio.run(service.invoke(profile, '资料', Summary))['overview'] == 'ok'
    assert len(calls) == 2 and 'response_format' not in calls[1]
    assert profile['model_metadata']['structured_output'] is True


def test_xiaomi_settings_profile_uses_confirmed_capabilities_without_invented_effort(tmp_path):
    from wechat_decrypt_tool.ai.schemas import ProviderInput
    from wechat_decrypt_tool.ai.providers import analysis_messages

    preset = next(p for p in PRESETS if p['provider'] == 'xiaomi')
    saved = ProviderInput(**preset, model='mimo-v2.5', api_key='test-only').model_dump()
    service = ModelService(AIStore(tmp_path))
    # 目录列出多模态和窗口；JSON 能力由官方文档补充，不制造推理等级。
    service.metadata.data = {'xiaomi': {'api': preset['base_url'], 'models': {
        'mimo-v2.5': {'reasoning': True, 'reasoning_options': [{'type': 'toggle'}],
            'limit': {'context': 1048576, 'output': 131072},
            'modalities': {'input': ['text', 'image', 'audio', 'video'], 'output': ['text']}}
    }}}
    service.store.put('profile', saved, id='xiaomi-profile')
    profile = service.resolve_turn('xiaomi-profile')
    assert profile['context_window'] == 1048576 and profile['vision'] is True
    metadata = profile['model_metadata']
    assert metadata['structured_output'] is True
    assert metadata['field_sources']['structured_output'] == 'provider-docs'
    assert not metadata.get('reasoning_efforts')
    with pytest.raises(ProviderFailure, match='未声明'):
        service.resolve_turn('xiaomi-profile', reasoning_effort='high')
    client = service.client(profile)
    payload = client._get_request_payload(analysis_messages('测试', Summary),
        response_format={'type': 'json_object'}, max_tokens=131072)
    assert payload['model'] == 'mimo-v2.5'
    assert payload['max_completion_tokens'] == 131072
    assert payload['response_format'] == {'type': 'json_object'}
    assert 'reasoning_effort' not in payload
    assert service.store.get('profile', 'xiaomi-profile')['model'] == 'mimo-v2.5'


@pytest.mark.parametrize('changes', [
    {'base_url': 'https://proxy.example/v1'}, {'base_url': 'https://api.xiaomimimo.com:8443/v1'},
    {'base_url': 'https://api.xiaomimimo.com/proxy/v1'},
    {'protocol': 'anthropic'}, {'model': 'mimo-v2.5-future'},
])
def test_documented_xiaomi_capabilities_do_not_leak_to_other_endpoints(tmp_path, changes):
    from wechat_decrypt_tool.ai.model_catalog import ModelCatalog
    profile = {'provider': 'xiaomi', 'base_url': 'https://api.xiaomimimo.com/v1',
        'protocol': 'openai', 'model': 'mimo-v2.5', **changes}
    assert ModelCatalog(tmp_path).automatic(profile) is None


def test_xiaomi_explicit_upstream_and_manual_capabilities_override_documentation(tmp_path):
    service = ModelService(AIStore(tmp_path))
    profile = {'id': 'p', 'provider': 'xiaomi', 'base_url': 'https://api.xiaomimimo.com/v1',
        'protocol': 'openai', 'model': 'mimo-v2.5'}
    service.metadata.remember(profile, [{'id': 'mimo-v2.5', 'structured_output': False}])
    metadata = service.metadata.automatic(profile)
    assert metadata['structured_output'] is False
    assert metadata['field_sources']['structured_output'] == 'upstream'
    profile['model_overrides'] = {'structured_output': True}
    metadata = service.metadata.enrich(profile)['model_metadata']
    assert metadata['structured_output'] is True
    assert metadata['field_sources']['structured_output'] == 'manual'


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-v4-flash-vision-exp'])
def test_official_deepseek_auxiliary_toggle_preserves_explicit_reasoning(model):
    from wechat_decrypt_tool.ai.model_execution import model_policy
    profile = {'provider': 'deepseek', 'protocol': 'openai', 'model': model,
        'base_url': 'https://api.deepseek.com/v1', 'api_key': 'test-only'}
    with model_policy(auxiliary=True):
        assert ModelService.client(profile).extra_body == {'thinking': {'type': 'disabled'}}
        explicit = ModelService.client({**profile, 'reasoning_effort': 'high'})
        assert explicit.reasoning_effort == 'high'
        assert explicit.extra_body == {'thinking': {'type': 'enabled'}}
        assert not ModelService.client({**profile, 'base_url': 'https://proxy.example/v1'}).extra_body
        assert not ModelService.client({**profile, 'model': 'deepseek-unknown'}).extra_body
    assert not ModelService.client(profile).extra_body
