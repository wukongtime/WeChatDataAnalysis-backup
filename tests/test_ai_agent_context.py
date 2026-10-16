"""旧版本任务的大范围读取、预算、分段恢复与隔离回归；新版本见 test_ai_continuous_v2.py。"""
import asyncio
import hashlib
import json
import time
import tracemalloc
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from test_ai_agent import submit
from legacy_agent_fixture import base_agent_service, legacy_service


@pytest.fixture
def service(legacy_service):
    return legacy_service
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
    async def read(account,username,start,end,offset, *, max_batch_bytes=None):
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












def test_utf8_limit_and_long_message_split():
    TurnInput(text='a'*1048576,request_id='one')
    with pytest.raises(ValidationError):TurnInput(text='中'*349526,request_id='two')
    original='第一天😀\n第二天报价更改。'*1000
    parts=list(pieces(original,300))
    assert ''.join(parts)==original and all(size(x)<=300 for x in parts)
    assert AgentAction(action='answer',question='无关正文'*1000).question==''
    with pytest.raises(ValidationError):AgentAction(action='clarify',question='过长问题'*1000)
