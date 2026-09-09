import asyncio
import json
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


def test_force_rejected_uses_json_protocol(service):
    client=Client([HttpError(400,'tool_choice not supported'),response(content='{"action":"answer"}')])
    assert call(service,client).action=='answer'
    assert len(client.choices)==1
    assert client.requests[1][1]['response_format']=={'type':'json_object'}


@pytest.mark.parametrize('code,category,count',[(401,'authentication',1),(429,'rate_limit',3),(503,'service',3)])
def test_error_classification_and_request_bound(service,code,category,count):
    client=Client([HttpError(code)]*3)
    with pytest.raises(AgentFailure) as error:
        call(service,client)
    assert error.value.detail['category']==category
    assert len(client.requests)==count


def test_four_pages_then_bad_decision_recovers_without_reading_twice(service):
    async def run():
        async def read(account,username,start,end,offset):
            service.tools.calls.append(offset)
            return {'messages':[dict(source=f'{i:024x}',anchor=str(i),username=username,name='好友',time=end-1,sender='甲',kind='text',text='讨论事项',media={}) for i in range(offset,offset+50)],'has_more':offset<150}
        service.tools.read=read
        client=Client([response([{'action':'read_messages','username':'friend','offset':n}]) for n in (0,50,100,150)] +
                      [response(content='自由文字'),response([{'action':'answer'}])])
        async def stream(*args,**kwargs):
            yield AIMessageChunk(content='已核对讨论。[[000000000000000000000001]]',usage_metadata=USAGE)
        client.astream=stream
        service.model=AgentModel(service.ai.models)
        with patch.object(service.ai.models,'client',return_value=client):
            thread,task=await submit(service,'最近讨论了哪些重要的事？')
            await service.workers[task['id']]
        result=service.public_run(task['id'],'account')
        assert result['status']=='completed',result['error']
        assert service.tools.calls==[0,50,100,150]
        assert result['read_count']==200
        assert len([i for i in result['timeline'] if i['kind']=='tool'])==4
        assert any(i['kind']=='notice' for i in result['timeline'])
        assert result['usage']['unknown']==0 and result['usage']['calls']==7
    asyncio.run(run())


@pytest.mark.parametrize('action,invalid_source,batch', [
    ('read_context', 'realtime', False),
    ('read_context', 'f' * 24, True),
    ('analyze_media', 'snapshot_index', False),
])
def test_unknown_message_source_is_corrected_before_tools_run(service, action, invalid_source, batch):
    async def run():
        invalid = [{'action': action, 'source': invalid_source}]
        if batch:
            invalid.insert(0, {'action': 'read_messages', 'offset': 50})
        client = Client([response([{'action': 'read_messages'}]), response(invalid),
                         response([{'action': action, 'source': SOURCE}]), response([{'action': 'answer'}])])
        async def stream(*args, **kwargs):
            yield AIMessageChunk(content=f'已核对讨论。[[{SOURCE}]]', usage_metadata=USAGE)
        client.astream = stream
        context = AsyncMock(return_value={'messages': []})
        enrich = AsyncMock(return_value={'source': SOURCE, 'username': 'friend', 'anchor': 'db:table:1',
                        'time': 1, 'text': '已分析图片', 'media': {}})
        service.model = AgentModel(service.ai.models)
        with patch.object(service.ai.models, 'client', return_value=client), \
             patch.object(service.tools, 'context', context), patch.object(service.ai.media, 'enrich', enrich):
            _, task = await submit(service)
            await service.workers[task['id']]
        result = service.public_run(task['id'], 'account')
        assert result['status'] == 'completed', result['error']
        assert result['read_count'] == 1
        assert len(service.tools.calls) == 1
        assert context.await_count == (1 if action == 'read_context' else 0)
        assert enrich.await_count == (1 if action == 'analyze_media' else 0)
        assert all(i['status'] == 'completed' for i in result['timeline'] if i['kind'] == 'tool')
        audits = service.store.list('usage', 'account')
        assert len(audits) == 5 and all(a['usage_known'] for a in audits)
        assert len([a for a in audits if a.get('error_code') == 'unknown_source']) == 1
        assert 'evidence' in client.requests[2][0][-1].content
    asyncio.run(run())


def test_unknown_source_retry_is_bounded_and_legacy_pending_can_resume(service):
    async def run():
        client = Client([response([{'action': 'read_messages'}])] +
                        [response([{'action': 'read_context', 'source': 'realtime'}])] * 3)
        service.model = AgentModel(service.ai.models)
        with patch.object(service.ai.models, 'client', return_value=client):
            _, task = await submit(service)
            await service.workers[task['id']]
        failed = service.run(task['id'])
        assert failed['status'] == 'failed'
        assert failed['error_info']['category'] == 'protocol'
        assert '消息编号无效' in failed['error'] and '允许范围' not in failed['error']
        assert failed['read_count'] == 1 and len(client.requests) == 4
        assert failed.get('pending_actions', []) == []
        # 模拟旧版持久化的无效动作与歧义元数据，直接重试已有任务。
        service.update(task['id'], pending_actions=[AgentAction(action='read_context', source='realtime').model_dump()],
                       observations=failed['observations'] + [{'source': 'realtime', 'returned': 1}])
        repaired = Client([response([{'action': 'read_context', 'source': SOURCE}]), response([{'action': 'answer'}])])
        async def stream(*args, **kwargs):
            yield AIMessageChunk(content=f'继续回答。[[{SOURCE}]]', usage_metadata=USAGE)
        repaired.astream = stream
        context = AsyncMock(return_value={'messages': []})
        with patch.object(service.ai.models, 'client', return_value=repaired), patch.object(service.tools, 'context', context):
            await service.resume(task['id'], 'account')
            await service.workers[task['id']]
        assert service.run(task['id'])['status'] == 'completed'
        assert len(service.tools.calls) == 1 and context.await_count == 1
        sent = json.loads(repaired.requests[0][0][1].content)
        assert sent['evidence'][0]['source'] == SOURCE
        assert any(o.get('data_source') == 'realtime' for o in sent['observations'])
        assert all(o.get('source') != 'realtime' for o in sent['observations'])
    asyncio.run(run())


@pytest.mark.parametrize('foreign,category', [(False, 'protocol'), (True, 'scope')])
def test_tool_distinguishes_invalid_source_from_scope_violation(service, foreign, category):
    async def run():
        _, task = await submit(service)
        await service.workers[task['id']]
        service.update(task['id'], status='running')
        source = 'f' * 24
        if foreign:
            evidence = service.run(task['id'])['evidence']
            evidence[source] = {**evidence[SOURCE], 'source': source, 'username': 'another'}
            service.update(task['id'], evidence=evidence)
        context = AsyncMock()
        with patch.object(service.tools, 'context', context), pytest.raises(AgentFailure) as error:
            await service.execute_tool(task['id'], AgentAction(action='read_context', source=source))
        assert error.value.detail['category'] == category
        assert error.value.detail['retryable'] is (not foreign)
        context.assert_not_awaited()
    asyncio.run(run())


def test_resume_keeps_pending_batch_and_completed_tool(service):
    async def run():
        service.model.actions=[[AgentAction(action='read_messages',username='friend'),AgentAction(action='read_messages',username='friend',offset=50)],AgentAction(action='answer')]
        original=service.tools.read
        broken=True
        async def read(*args):
            if args[-1]==50 and broken:
                raise RuntimeError('private source content must not enter error')
            return await original(*args)
        service.tools.read=read
        _,task=await submit(service)
        await service.workers[task['id']]
        assert service.run(task['id'])['error_info']['category']=='data_source'
        assert len(service.tools.calls)==1
        broken=False
        await service.resume(task['id'],'account');await service.workers[task['id']]
        assert service.run(task['id'])['status']=='completed'
        assert len(service.tools.calls)==2
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


def test_message_offset_never_becomes_conversation_offset(service):
    async def run():
        service.model.actions=[AgentAction(action='read_messages',offset=200),AgentAction(action='answer')]
        _,task=await submit(service)
        await service.workers[task['id']]
        assert service.tools.calls[0][-1]==200
        assert service.tools.calls[0][1]=='friend'
        assert service.run(task['id'])['status']=='completed'
    asyncio.run(run())


def test_timeline_revisions_replay_and_history_are_persistent(service):
    async def run():
        thread,task=await submit(service)
        await service.workers[task['id']]
        detail=service.public_run(task['id'],'account')
        assert len({i['id'] for i in detail['timeline']})==len(detail['timeline'])
        assert [i['seq'] for i in detail['timeline']]==list(range(1,len(detail['timeline'])+1))
        assert all(i['status']!='running' for i in detail['timeline'])
        assert service.public_thread(thread['id'],'account')['runs'][0]['id']==task['id']
        events=service.store.events(account='account')
        updates=[e['body']['timeline_item'] for e in events if 'timeline_item' in e['body']]
        tools=[i for i in updates if i['kind']=='tool']
        assert tools[0]['id']==tools[-1]['id']
        assert tools[0]['revision']<tools[-1]['revision']
        assert 'tool_cache' not in detail and 'pending_actions' not in detail
    asyncio.run(run())
