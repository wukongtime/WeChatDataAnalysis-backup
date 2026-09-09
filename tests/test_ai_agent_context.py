"""大范围检索、预算、分段恢复与任务隔离的行为回归。"""
import asyncio
import hashlib
import json
import time
import tracemalloc
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from test_ai_agent import service, submit
from wechat_decrypt_tool.ai.agent_context import ContextIntent, Findings, Background
from wechat_decrypt_tool.ai.agent_budget import size, pieces, active_budget, check_request, ContextOverflow
from wechat_decrypt_tool.ai.agent_schemas import AgentAction, TurnInput
from wechat_decrypt_tool.ai.providers import model_attempt_hook


def setup_analysis(service, mode='overview', total=121):
    counts={'extract':0,'merge':0,'intent':0,'requests':[]}
    async def invoke(profile,prompt,schema=None,**kwargs):
        hook=model_attempt_hook.get()
        if hook:hook()
        counts['requests'].append(size(prompt))
        if schema is ContextIntent:
            counts['intent']+=1
            now=int(time.time())
            return {'mode':mode,'start':now-3*86400,'end':now,'time_phrase':'最近三天','objective':'找出日期变化和未解决事项'}
        if schema is Background:return {'text':'保留原问题的对象、时间与用户纠正。'}
        if schema is Findings:
            if '\n资料：' in prompt:
                counts['extract']+=1
                rows=json.loads(prompt.split('\n资料：',1)[1])
                return {'overview':'阶段结果','items':[{'text':m['text'],'sources':[m['source']],'needs_check':False} for m in rows if '关键' in m['text'] and not m.get('context_only')]}
            counts['merge']+=1
            values=json.loads(prompt.split('\n摘要：',1)[1])
            return {'overview':'合并结果','items':[m for v in values for m in v['items']]}
        raise AssertionError(schema)
    async def read(account,username,start,end,offset):
        service.tools.calls.append((username,offset))
        messages=[]
        for i in range(offset,min(total,offset+50)):
            messages.append({'source':hashlib.md5(f'{username}:{i}'.encode()).hexdigest()[:24],
                'anchor':str(i),'username':username,'time':start+i,'sender':'同名人','sender_id':username+':member',
                'kind':'text','text':f'关键变化{i}' if i in (0,60,total-1) else '日常消息','media':{}})
        return {'messages':messages,'has_more':offset+50<total,'data_source':'realtime','warning':''}
    async def call(profile,messages,account,decision=False,on_delta=None,validate=None):
        hook=model_attempt_hook.get()
        if hook:hook()
        counts['requests'].append(sum(size(m.content) for m in messages))
        if decision:return AgentAction(action='answer')
        payload=json.loads(messages[-1].content)
        text='已完成范围分析。'+''.join(item['text']+''.join('[['+s+']]' for s in item['sources']) for item in payload.get('summary',{}).get('items',[]))
        on_delta(text)
        return text
    service.ai.models.invoke=invoke
    service.tools.read=read
    service.model.call=call
    # 测试完整流程不通过无限循环绕过生产额度；单独验证耗尽后的恢复。
    service.store.put('agent_settings',{'moderate':{'tools':200,'models':400,'media':8,'seconds':300}},id='global')
    return counts


@pytest.mark.parametrize('mode',['overview','timeline','list'])
def test_overview_cannot_answer_before_every_chat_and_page(service,mode):
    async def run():
        counts=setup_analysis(service,mode)
        thread=await service.create_thread('account','friend','新分析')
        await service.edit_thread(thread['id'],'account',scope=['friend','project@chatroom'])
        _,task=await submit(service,'最近三天这些群聊了什么',thread=thread)
        await service.workers[task['id']]
        result=service.public_run(task['id'],'account')
        assert result['status']=='completed',result.get('error')
        assert result['analysis']['complete'] and result['analysis']['analyzed']==242
        assert service.tools.calls==[(u,o) for u in ('friend','project@chatroom') for o in (0,50,100)]
        findings=service.material_page(task['id'],'account','findings',limit=100)
        assert len(findings['items'])==6
        assert all(x['citations'] for x in findings['items'])
        assert all('关键变化'+str(i) in result['answer'] for i in (0,60,120))
        assert all('[['+s+']]' in result['answer'] for item in findings['items'] for s in item['sources'])
        if mode=='list':assert result['answer'].startswith('已保存 **6 条分析发现**')
        assert max(counts['requests'])<12000
        assert 'evidence' not in service.store.get('agent_run',task['id'])
    asyncio.run(run())


def test_statistics_exact_and_names_do_not_merge_across_chats(service):
    async def run():
        counts=setup_analysis(service,'statistics',121)
        thread=await service.create_thread('account','friend','统计')
        await service.edit_thread(thread['id'],'account',scope=['friend','project@chatroom'])
        _,task=await submit(service,'统计最近三天每天每个人发了多少消息',thread=thread)
        await service.workers[task['id']]
        result=service.run(task['id'])
        assert result['status']=='completed',result.get('error')
        page=service.material_page(task['id'],'account','statistics')
        assert page['total_messages']==242 and sum(x['count'] for x in page['items'])==242
        assert len({x['username'] for x in page['items']})==2
        assert sum(x['count'] for x in page['daily_totals'])==242
        assert sum(x['count'] for x in page['sender_ranking'])==242
        assert len(page['sender_ranking'])==2
        assert counts['extract']==0 and counts['merge']==0
    asyncio.run(run())


def test_budget_resume_does_not_repeat_completed_segments(service):
    async def run():
        counts=setup_analysis(service,total=121)
        service.store.put('agent_settings',{'moderate':{'tools':1,'models':400,'media':8,'seconds':300}},id='global')
        _,task=await submit(service,'最近三天聊了什么')
        await service.workers[task['id']]
        assert service.run(task['id'])['status']=='budget'
        first=counts['extract']
        await service.resume(task['id'],'account')
        await service.workers[task['id']]
        assert service.run(task['id'])['status']=='budget'
        assert service.tools.calls==[('friend',0),('friend',50)]
        assert counts['extract']>first
        await service.resume(task['id'],'account')
        await service.workers[task['id']]
        assert service.run(task['id'])['status']=='completed'
        assert service.tools.calls==[('friend',0),('friend',50),('friend',100)]
    asyncio.run(run())


def test_material_versions_and_account_revocation(service):
    async def run():
        setup_analysis(service,total=2)
        thread,task=await submit(service,'最近三天聊了什么')
        await service.workers[task['id']]
        with pytest.raises(ValueError):service.material_page(task['id'],'other')
        with pytest.raises(ValueError):service.material_page(task['id'],'account',version=99)
        await service.edit_thread(thread['id'],'account',scope=['another'])
        with pytest.raises(ValueError):service.material_page(task['id'],'account')
        _,next_task=await submit(service,'统计另一个会话','changed',thread)
        assert service.public_run(next_task['id'],'account')['source_count']==0
        await service.workers[next_task['id']]
        await service.delete_thread(thread['id'],'account')
        with service.store.connection() as db:
            assert db.execute('SELECT count(*) FROM agent_material').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM agent_piece').fetchone()[0]==0
    asyncio.run(run())


def test_utf8_limit_and_long_message_split():
    TurnInput(text='a'*1048576,request_id='one')
    with pytest.raises(ValidationError):TurnInput(text='中'*349526,request_id='two')
    original='第一天😀\n第二天报价更改。'*1000
    parts=list(pieces(original,300))
    assert ''.join(parts)==original and all(size(x)<=300 for x in parts)
    assert AgentAction(action='answer',question='无关正文'*1000).question==''
    with pytest.raises(ValidationError):AgentAction(action='clarify',question='过长问题'*1000)


def test_followup_inherits_time_then_replaces_it(service):
    async def run():
        setup_analysis(service,'statistics',2)
        original=service.ai.models.invoke
        turns=0
        async def invoke(profile,prompt,schema=None,**kwargs):
            nonlocal turns
            if schema is ContextIntent:
                turns+=1
                if turns==2:return {'mode':'statistics','followup':True,'objective':'同一范围继续按发言人统计'}
                if turns==3:return {'mode':'statistics','followup':True,'objective':'上周统计','start':100,'end':200}
            return await original(profile,prompt,schema,**kwargs)
        service.ai.models.invoke=invoke
        thread,first=await submit(service,'最近三天发了多少消息')
        await service.workers[first['id']]
        interval=service.run(first['id'])['time_range']
        _,second=await submit(service,'按发言人呢','two',thread)
        await service.workers[second['id']]
        assert service.run(second['id'])['time_range']==interval
        _,third=await submit(service,'那上周呢','three',thread)
        await service.workers[third['id']]
        assert service.run(third['id'])['time_range']=={'start':100,'end':200}
        fresh=await service.create_thread('account','friend','全新对话')
        assert not fresh.get('task_context') and not fresh.get('memory')
    asyncio.run(run())


def test_short_history_with_large_messages_is_compacted_and_keeps_original(service):
    async def run():
        setup_analysis(service,'statistics',1)
        thread,first=await submit(service,'最近三天统计')
        await service.workers[first['id']]
        t=service.thread(thread['id'],'account')
        huge='请保留用户纠正：按新日期，不按旧日期。'*500
        t['messages'].append({'id':'huge','role':'user','text':huge,'run_id':first['id']})
        service.store.put('agent_thread',t)
        _,second=await submit(service,'继续','second',thread)
        await service.workers[second['id']]
        actual=service.thread(thread['id'],'account')
        assert actual.get('memory') and actual['memory']['through']=='huge'
        assert next(m for m in actual['messages'] if m['id']=='huge')['text']==huge
        assert service.run(second['id'])['status']=='completed',service.run(second['id']).get('error')
    asyncio.run(run())


def test_window_error_reduces_pending_segment_instead_of_resending_same_payload(service):
    async def run():
        setup_analysis(service,total=50)
        original=service.ai.models.invoke
        failed=[]
        retried=[]
        async def invoke(profile,prompt,schema=None,**kwargs):
            if schema is Findings and '\n资料：' in prompt:
                if not failed:
                    failed.append(size(prompt))
                    raise ContextOverflow('maximum context length')
                retried.append(size(prompt))
            return await original(profile,prompt,schema,**kwargs)
        service.ai.models.invoke=invoke
        _,task=await submit(service,'最近三天聊了什么')
        await service.workers[task['id']]
        result=service.run(task['id'])
        assert result['input_budget']==6000
        assert result['status']=='completed',result.get('error')
        assert retried[0] < failed[0]
    asyncio.run(run())


def test_large_attachment_text_preserves_every_character_and_source(service):
    async def run():
        setup_analysis(service,total=1)
        original=service.ai.models.invoke
        read=service.tools.read
        text='附件第一天的交付日期。'*500+'附件最后一天改期，仍需确认。'
        async def invoke(profile,prompt,schema=None,**kwargs):
            value=await original(profile,prompt,schema,**kwargs)
            if schema is ContextIntent:value['media']=True
            return value
        async def attachment(*args):
            page=await read(*args)
            for m in page['messages']:m['kind']='file'
            return page
        async def enrich(account,message,*args,**kwargs):return dict(message,text=text)
        service.ai.models.invoke=invoke
        service.tools.read=attachment
        service.ai.media.enrich=enrich
        _,task=await submit(service,'总结附件内容')
        await service.workers[task['id']]
        result=service.run(task['id'])
        assert result['status']=='completed',result.get('error')
        chunks=service.workspace.page(task['id'],1,'chunk',limit=100)['items']
        fragments=sorted((m for c in chunks for m in c['messages'] if not m['context_only']),key=lambda m:m['text_offset'])
        assert ''.join(m['text'] for m in fragments)==text
        assert len({m['source'] for m in fragments})==1
        assert result['evidence'][fragments[0]['source']]['text']==text
        assert result['analysis']['segments']>1
    asyncio.run(run())


def test_material_api_pages_utf8_input_and_stale_version(service):
    import httpx
    from fastapi import FastAPI
    from wechat_decrypt_tool.routers import ai_agent
    app=FastAPI(); app.include_router(ai_agent.router)
    async def run():
        setup_analysis(service,'statistics',51)
        thread,task=await submit(service,'最近三天消息统计')
        await service.workers[task['id']]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1)),base_url='http://localhost') as client:
            url=f'/api/ai/agent/runs/{task["id"]}/materials'
            first=await client.get(url,params={'account':'account','limit':20,'version':1})
            last=await client.get(url,params={'account':'account','offset':40,'limit':20,'version':1})
            assert first.status_code==last.status_code==200
            assert len(first.json()['items'])==20 and first.json()['has_more']
            assert len(last.json()['items'])==11 and not last.json()['has_more']
            assert (await client.get(url,params={'account':'another'})).status_code==409
            assert (await client.get(url,params={'account':'account','version':2})).status_code==409
            source=first.json()['items'][0]['source']
            assert (await client.get(url+'/'+source,params={'account':'account','version':1})).status_code==200
            invalid=await client.post(f'/api/ai/agent/threads/{thread["id"]}/messages',params={'account':'account'},json={'text':'中'*349526,'request_id':'too-big'})
            assert invalid.status_code==422
    with patch.object(ai_agent,'get_agent_service',return_value=service),patch.object(ai_agent,'account_name',side_effect=lambda x:x):asyncio.run(run())


def test_known_small_window_reserves_output_and_checks_actual_requests(service):
    async def run():
        setup_analysis(service,'statistics',2)
        profile=service.store.get('profile','model')
        profile['context_window']=8192
        service.store.put('profile',profile)
        original=service.model.call
        async def call(profile,messages,*args,**kwargs):
            from wechat_decrypt_tool.ai.agent_schemas import TOOL_DESCRIPTION
            extra={'description':TOOL_DESCRIPTION,'parameters':AgentAction.model_json_schema()} if kwargs.get('decision') else None
            check_request(profile,messages,extra)
            return await original(profile,messages,*args,**kwargs)
        service.model.call=call
        _,task=await submit(service,'最近三天统计')
        await service.workers[task['id']]
        result=service.run(task['id'])
        assert service.budget(result)==5632
        assert result['status']=='completed',result.get('error')
    asyncio.run(run())


def test_conflict_checks_reuse_source_context_without_claiming_resolution(service):
    from unittest.mock import AsyncMock
    async def run():
        setup_analysis(service,'statistics',1)
        _,task=await submit(service,'统计最近三天')
        await service.workers[task['id']]
        current=service.update(task['id'],status='running')
        source=next(current['evidence'].values())
        for i in range(2):
            service.workspace.put(task['id'],1,'check:'+str(i),'finding',{'text':f'第{i}个日期说法待核实','sources':[source['source']],'needs_check':True})
        service.tools.context=AsyncMock(return_value={'messages':[source]})
        assert await service.check_findings(task['id'],current['analysis'])
        assert await service.check_findings(task['id'],current['analysis'])
        assert not await service.check_findings(task['id'],current['analysis'])
        assert service.tools.context.await_count==1
        findings=service.workspace.page(task['id'],1,'finding')['items']
        assert all(item['checked'] and item['needs_check'] for item in findings)
    asyncio.run(run())


def test_store_100000_sources_with_bounded_working_set(service):
    evidence=service.workspace.evidence('synthetic-large')
    tracemalloc.start()
    for offset in range(0,100000,100):
        evidence.put_many({'source':f'{i:024x}','anchor':str(i),'username':'friend','time':100+i,
            'sender':'甲','sender_id':'member','text':'合成测试消息'} for i in range(offset,offset+100))
    _,peak=tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(evidence)==100000 and peak<16*1024*1024
    assert len(list(evidence.rows(offset=99990,limit=20)))==10
    stats=service.workspace.statistics('synthetic-large')
    assert stats['total_messages']==100000 and sum(row['count'] for row in stats['items'])==100000
