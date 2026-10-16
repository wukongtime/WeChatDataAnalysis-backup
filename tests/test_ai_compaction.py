"""上下文改进的行为回归：追问连续性、检查点隔离、失败原子性和用量校准。"""
import asyncio
import copy
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from wechat_decrypt_tool.ai.agent_budget import ContextOverflow, request_size, active_budget, check_request
from wechat_decrypt_tool.ai.agent_history import HistoryCheckpoint, recent_boundary
from wechat_decrypt_tool.ai.compaction_policy import CompactionPolicy
from wechat_decrypt_tool.ai.context_meter import ContextMeter, active_meter


def seed_history(service, thread, task):
    current = service.thread(thread['id'], 'account')
    rows = []
    for index in range(6):
        prior = {'id': f'past-{index}', 'account': 'account', 'thread_id': thread['id'],
                 'query_filters': task.get('query_filters')}
        service.store.put('agent_run', prior)
        for role in ('user', 'assistant'):
            rows.append({'id': f'{role}-{index}', 'run_id': prior['id'], 'role': role,
                         'text': (f'第{index}轮内容。' * 100) + ('更正：聚餐改为周五19点。' if role == 'user' else '第二件事是订场。')})
    current['messages'] = rows + current['messages']
    service.store.put('agent_thread', current)
    return rows


def note_result():
    return {'text': '讨论活动安排。聚餐已改为周五19点；订场仍待确认。',
            'instructions': [{'message_id': 'user-0', 'quote': '更正：聚餐改为周五19点。'}]}








def test_retained_tail_never_splits_supplemented_turn():
    rows = [{'id': str(i), 'run_id': turn, 'text': '长消息' * 50} for i, turn in enumerate(['a','a','b','b','b','c','c'])]
    assert recent_boundary(rows, 1, 2) == 2


@pytest.mark.parametrize('config', [{'pressure_ratio': .5, 'target_ratio': .6}, {'recent_ratio': .4},
                                    {'unknown': 1}, {'summary_attempts': 0}])
def test_invalid_policy_fails_before_model_call(config):
    with pytest.raises(ValidationError):
        CompactionPolicy.model_validate(config)


def test_usage_calibration_is_conservative_for_new_suffix_and_isolates_models():
    profile = {'id': 'p', 'model': 'test', 'protocol': 'openai', 'revision': 1}
    messages = [SystemMessage(content='固定说明'), HumanMessage(content='稳定历史。' * 2000)]
    meter = ContextMeter()
    initial = meter.measure(profile, messages)
    meter.observe(profile, messages, None, {'input_tokens': 5000})
    calibrated = meter.measure(profile, messages)
    assert 5000 < calibrated < initial
    extended = [messages[0], HumanMessage(content=messages[1].content + '新增内容🙂' * 100)]
    # 已存在消息被改写时不复用旧锚点；追加完整新消息才保持请求前缀一致。
    assert meter.measure(profile, extended) == request_size(extended)
    appended = [*messages, AIMessage(content='新增内容🙂' * 100)]
    assert calibrated < meter.measure(profile, appended) < request_size(appended)
    assert meter.measure({**profile, 'model': 'different'}, messages) == initial
    assert meter.measure({**profile, 'revision': 2}, messages) == initial
    assert meter.measure(profile, messages, {'tools': ['new']}) == request_size(messages, {'tools': ['new']})
    # 持久化只含指纹和数字；恢复后可继续使用。
    assert '稳定历史' not in json.dumps(meter.samples, ensure_ascii=False)
    assert ContextMeter(meter.samples).measure(profile, messages) == calibrated
    meter.invalidate()
    assert meter.measure(profile, messages) == initial


def test_preflight_uses_same_meter_and_unknown_usage_never_relaxes_budget():
    profile = {'id': 'p', 'model': 'test'}
    messages = [HumanMessage(content='长历史。' * 2000)]
    meter = ContextMeter()
    token = active_budget.set(10000)
    meter_token = active_meter.set(meter)
    try:
        for usage in ({}, {'input_tokens': 0}, {'input_tokens': True}):
            meter.observe(profile, messages, None, usage)
        with pytest.raises(ContextOverflow):
            check_request(profile, messages)
        meter.observe(profile, messages, None, {'input_tokens': 4000})
        assert check_request(profile, messages) == meter.measure(profile, messages)
    finally:
        active_meter.reset(meter_token)
        active_budget.reset(token)






def test_model_response_updates_meter_without_persisting_prompt(tmp_path):
    from langchain_core.messages import AIMessageChunk
    from wechat_decrypt_tool.ai.agent_model import AgentModel
    from wechat_decrypt_tool.ai.providers import ModelService
    from wechat_decrypt_tool.ai.storage import AIStore
    async def run():
        models = ModelService(AIStore(tmp_path))
        model = AgentModel(models)
        class Client:
            async def astream(self, *args, **kwargs):
                yield AIMessageChunk(content='完成', usage_metadata={'input_tokens': 500, 'output_tokens': 2, 'total_tokens': 502})
        profile = {'id': 'p', 'model': 'fake', 'protocol': 'openai'}
        messages = [HumanMessage(content='不得记录的私人文本。' * 100)]
        meter = ContextMeter()
        token = active_meter.set(meter)
        try:
            with patch.object(models, 'client', return_value=Client()):
                assert await model.call(profile, messages, 'account') == '完成'
            assert meter.samples[0]['input_tokens'] == 500
            assert meter.measure(profile, messages) < request_size(messages)
            assert '不得记录' not in json.dumps(models.store.list('usage', 'account'), ensure_ascii=False)
        finally:
            active_meter.reset(token)
    asyncio.run(run())


def test_internal_checkpoint_data_is_not_returned_to_frontend(service):
    async def run():
        thread, task = await idle_run(service)
        meter = service.context_meter(task)
        messages = [HumanMessage(content='历史。' * 300)]
        meter.observe(service.profile(task), messages, None, {'input_tokens': 500})
        assert service.thread(thread['id'], 'account')['context_meter_samples']
        assert 'context_meter_samples' not in service.public_thread(thread['id'], 'account')
        recovered = type(service)(service.ai, service.tools, service.model)
        assert recovered.context_meter(task).measure(service.profile(task), messages) < request_size(messages)
    asyncio.run(run())




def test_sdk_truncation_keeps_usage_and_does_not_retry_identical_summary(tmp_path):
    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion
    from openai.types.completion_usage import CompletionUsage
    from wechat_decrypt_tool.ai.providers import ModelService
    from wechat_decrypt_tool.ai.storage import AIStore
    async def run():
        models = ModelService(AIStore(tmp_path))
        calls = []
        class Client:
            async def ainvoke(self, *args, **kwargs):
                calls.append(1)
                raise LengthFinishReasonError(completion=ChatCompletion(
                    id='synthetic', choices=[], created=1, model='fake', object='chat.completion',
                    usage=CompletionUsage(prompt_tokens=200, completion_tokens=4096, total_tokens=4296)))
        with patch.object(models, 'client', return_value=Client()):
            with pytest.raises(ContextOverflow, match='截断'):
                await models.invoke({'id':'p', 'model':'fake', 'protocol':'openai'}, '虚构资料', HistoryCheckpoint, account='synthetic')
        assert len(calls) == 1
        usage = models.store.list('usage', 'synthetic')[0]
        assert usage['usage_known'] and usage['usage']['input_tokens'] == 200
        assert usage['usage']['output_tokens'] == 4096
        assert usage['error_code'] == 'output_truncated' and usage['status'] == 'failed'
    asyncio.run(run())


def test_api_preserves_compaction_policy_when_older_client_saves_profile(tmp_path):
    import httpx
    from fastapi import FastAPI
    from wechat_decrypt_tool.ai.service import AIService
    from wechat_decrypt_tool.ai.storage import AIStore
    from wechat_decrypt_tool.routers import ai
    async def run():
        instance = AIService(AIStore(tmp_path))
        app = FastAPI()
        app.include_router(ai.router)
        body = {'name':'测试模型', 'model':'fake', 'base_url':'http://localhost:1234/v1',
                'compaction_policy': {'recent_turns': 3, 'pressure_ratio': .85}}
        with patch.object(ai, 'get_ai_service', return_value=instance):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
                created = await client.post('/api/ai/profiles', json=body)
                assert created.status_code == 200
                identifier = created.json()['id']
                body.pop('compaction_policy')
                updated = await client.put('/api/ai/profiles/' + identifier, json=body)
                assert updated.status_code == 200
                assert updated.json()['compaction_policy']['recent_turns'] == 3
                assert updated.json()['compaction_policy']['pressure_ratio'] == .85
                bad = await client.put('/api/ai/profiles/' + identifier, json={**body, 'compaction_policy': {'pressure_ratio': .4}})
                assert bad.status_code == 422
    asyncio.run(run())
