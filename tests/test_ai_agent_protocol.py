import asyncio
import json
import httpx
import httpcore
from unittest.mock import patch, AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from test_ai_agent import service, submit, SOURCE
from wechat_decrypt_tool.ai.agent_model import AgentModel, AgentFailure, ActionFormatError
from wechat_decrypt_tool.ai.agent_schemas import AgentAction

USAGE = dict(input_tokens=30, output_tokens=10, total_tokens=40)


def response(args=None, **kwargs):
    calls = [] if args is None else [dict(name='chat_action', args=a, id=str(i)) for i,a in enumerate(args)]
    return AIMessage(content=kwargs.pop('content', ''), tool_calls=calls, usage_metadata=USAGE, **kwargs)


class Client:
    def __init__(self, values):
        self.values, self.requests, self.choices = list(values), [], []

    def bind_tools(self, tools, **kwargs):
        self.choices.append(kwargs)
        return self

    async def ainvoke(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def call(service, client):
    async def run():
        with patch.object(service.ai.models, 'client', return_value=client), patch('asyncio.sleep', new=AsyncMock()):
            return await AgentModel(service.ai.models).call(service.ai.models.resolve(), [], 'account', decision=True)
    return asyncio.run(run())


def test_prose_is_corrected_without_losing_usage(service):
    client = Client([response(content='以下是最近的重要讨论'), response([{'action':'answer'}])])
    assert call(service, client).action == 'answer'
    assert client.choices[0]['tool_choice'] == 'chat_action'
    assert '上一动作未执行' in client.requests[1][0][-1].content
    audits = service.store.list('usage', 'account')
    assert len(audits) == 2
    assert all(a['usage_known'] and a['usage'] == USAGE for a in audits)
    assert any(a.get('error_code') == 'invalid_json' for a in audits)


def test_multiple_reads_validated_and_terminal_mix_repaired(service):
    client=Client([response([{'action':'read_messages','offset':0},{'action':'answer'}]),
                   response([{'action':'read_messages','offset':0},{'action':'read_messages','offset':50}])])
    actions=call(service,client)
    assert [a.offset for a in actions] == [0,50]


@pytest.mark.parametrize('first,code', [
    (response([{'action':'search_messages','query':''}]), 'invalid_arguments'),
    (response([{'action':'read_context'}]), 'invalid_arguments'),
    (response(content=''), 'empty_response'),
    (response(content='```json\n{"action":\n```'), 'invalid_json'),
    (response([{'action':'answer'}],response_metadata={'finish_reason':'length'}), 'output_truncated'),
])
def test_invalid_results_are_corrected(service,first,code):
    client=Client([first,response([{'action':'answer','progress':{'invalid':'ignored'}}])])
    result=call(service,client)
    assert result.action=='answer' and result.progress==''
    assert any(a.get('error_code')==code for a in service.store.list('usage','account'))
    if code=='output_truncated':
        assert client.requests[1][1]['max_tokens']==8192


class HttpError(Exception):
    def __init__(self, status, text='error'):
        self.status_code=status
        super().__init__(text)


def test_force_rejected_keeps_tools_with_auto_choice(service):
    client=Client([HttpError(400,'tool_choice not supported'),response([{'action':'answer'}])])
    assert call(service,client).action=='answer'
    assert [choice['tool_choice'] for choice in client.choices]==['chat_action','auto']
    assert 'response_format' not in client.requests[1][1]


def test_confirmed_compatibility_survives_recreated_model_without_extra_request(service):
    first = Client([HttpError(400, 'tool_choice not supported'), response([{'action': 'answer'}])])
    assert call(service, first).action == 'answer'
    second = Client([response([{'action': 'answer'}])])
    assert call(service, second).action == 'answer'
    assert [choice['tool_choice'] for choice in second.choices] == ['auto']
    assert len(service.store.list('usage', 'account')) == 3
    state = service.store.list('agent_model_compatibility')[0]
    assert state['disabled'] == ['no_force']
    assert not any(key in state for key in ('api_key', 'base_url', 'messages', 'model'))


@pytest.mark.parametrize('change', ['model', 'revision', 'base_url', 'expired'])
def test_compatibility_rechecks_changed_or_expired_service(service, change):
    first = Client([HttpError(400, 'tool_choice not supported'), response([{'action': 'answer'}])])
    assert call(service, first).action == 'answer'
    profile = service.ai.models.resolve()
    if change == 'expired':
        state = service.store.list('agent_model_compatibility')[0]
        service.store.put('agent_model_compatibility', {**state, 'expires_at': 0})
    elif change == 'revision':
        profile[change] = (profile.get(change) or 0) + 1
    else:
        profile[change] = str(profile.get(change) or '') + '-changed'
    second = Client([response([{'action': 'answer'}])])
    async def run():
        with patch.object(service.ai.models, 'client', return_value=second):
            return await AgentModel(service.ai.models).call(profile, [], 'account', decision=True)
    assert asyncio.run(run()).action == 'answer'
    assert [choice['tool_choice'] for choice in second.choices] == ['chat_action']


def test_unavailable_tools_still_fall_back_to_json(service):
    client=Client([HttpError(400,'tool_choice not supported'),
                   HttpError(400,'tools not supported'),response(content='{"action":"answer"}')])
    assert call(service,client).action=='answer'
    assert [choice['tool_choice'] for choice in client.choices]==['chat_action','auto']
    assert client.requests[2][1]['response_format']=={'type':'json_object'}


@pytest.mark.parametrize('code,category,count',[(401,'authentication',1),(429,'rate_limit',3),(503,'service',3)])
def test_error_classification_and_request_bound(service,code,category,count):
    client=Client([HttpError(code)]*3)
    with pytest.raises(AgentFailure) as error:
        call(service,client)
    assert error.value.detail['category']==category
    assert len(client.requests)==count


@pytest.mark.parametrize('error_type', [httpx.RemoteProtocolError, httpcore.RemoteProtocolError, httpcore.ReadError])
def test_broken_remote_stream_is_retryable_and_preserves_visible_text(service, error_type):
    async def run():
        class BrokenStream:
            async def astream(self, *args, **kwargs):
                yield AIMessageChunk(content='已经显示的报告正文')
                raise error_type('peer closed connection without complete message')
        deltas = []
        with patch.object(service.ai.models, 'client', return_value=BrokenStream()):
            with pytest.raises(AgentFailure) as error:
                await AgentModel(service.ai.models).call(service.ai.models.resolve(), [], 'account', on_delta=deltas.append)
        assert error.value.detail['category'] == 'connection'
        assert error.value.detail['retryable'] is True
        assert deltas == ['已经显示的报告正文']
        audit = service.store.list('usage', 'account')
        assert len(audit) == 1 and audit[0]['error_type'] == error_type.__name__
        assert not audit[0]['usage_known']
    asyncio.run(run())












def test_answer_citation_correction_preserves_failed_usage(service):
    async def run():
        attempts=0
        class Streaming:
            async def astream(self,*args,**kwargs):
                nonlocal attempts
                attempts+=1
                yield AIMessageChunk(content='错误[[missing]]' if attempts==1 else '有效回答',usage_metadata=USAGE)
        chunks=[]
        def validate(text):
            if 'missing' in text: raise ActionFormatError('unknown_citation')
        with patch.object(service.ai.models,'client',return_value=Streaming()):
            result=await AgentModel(service.ai.models).call(service.ai.models.resolve(),[],'account',on_delta=chunks.append,validate=validate)
        assert result=='有效回答' and None in chunks and attempts==2
        assert all(x['usage_known'] for x in service.store.list('usage','account'))
    asyncio.run(run())


def test_continuation_retry_preserves_prefix_instruction_and_audits_failed_stream(service):
    async def run():
        attempts, seen = [], []
        class Streaming:
            async def astream(self, messages, **kwargs):
                attempts.append(messages)
                yield AIMessageChunk(content='重新输出标题' if len(attempts) == 1 else '接写剩余正文', usage_metadata=USAGE)
        def delta(text):
            if text == '重新输出标题':
                raise ActionFormatError('invalid_continuation')
            seen.append(text)
        with patch.object(service.ai.models, 'client', return_value=Streaming()):
            result = await AgentModel(service.ai.models).call(service.ai.models.resolve(), [], 'account', on_delta=delta, continuation=True)
        assert result == '接写剩余正文' and seen == [None, '接写剩余正文']
        correction = attempts[1][-1].content
        assert '原回答前缀保持不变' in correction
        assert '请重新输出简短完整' not in correction
        usage = service.store.list('usage', 'account')
        assert sorted(u['status'] for u in usage) == ['failed', 'success']
        assert all(u['usage_known'] for u in usage)
    asyncio.run(run())
