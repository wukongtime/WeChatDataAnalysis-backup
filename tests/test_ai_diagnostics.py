"""诊断只写元数据，覆盖真实日志、关联上下文及本机入口边界。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import logging
import shutil
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from wechat_decrypt_tool.ai import diagnostics as d
from wechat_decrypt_tool.ai.diagnostics_http import diagnostic_request
from wechat_decrypt_tool.routers.ai import router


def records(path):
    return [json.loads(line.split('运行诊断 ', 1)[1]) for line in path.read_text(encoding='utf-8').splitlines() if '运行诊断 ' in line]


def test_key_events_limit_volume_without_changing_other_logs(ai_file_diagnostics):
    details = ['messages.page.finished', 'index.batch.finished', 'index.commit.finished',
               'inference.encode.finished', 'media.page.finished', 'summary.segment.finished',
               'summary.run_rule.started', 'summary.rule.skipped', 'agent.context.segment.finished',
               'agent.budget.consumed', 'model.call.first_token', 'client.sse.open']
    for _ in range(1000):
        for name in details:
            d.event(name, count=100)
    assert records(ai_file_diagnostics) == []
    keys = ['summary.task.created', 'summary.task.state', 'agent.run.terminal',
            'agent.tool.action.finished', 'model.call.started', 'model.call.finished',
            'search.run.finished', 'client.notification.shown', 'client.notification.ack',
            'client.sse.recovered']
    for name in keys:
        d.event(name)
    d.event('media.page.finished', level=logging.WARNING, reason_code='missing')
    d.event('index.batch.finished', error=ValueError('SECRET'))
    d.event('agent.analysis.failed', status='failed')
    assert len(records(ai_file_diagnostics)) == len(keys) + 3
    # 同一个文件 handler 仍完整接收其他模块的 INFO/DEBUG，策略不挂到全局。
    ordinary = logging.Logger('wechat_decrypt_tool.chat', logging.DEBUG)
    ordinary.handlers = d.logger.handlers[:]
    ordinary.info('普通模块信息保持原样')
    ordinary.debug('普通模块调试保持原样')
    text = ai_file_diagnostics.read_text(encoding='utf-8')
    assert '普通模块信息保持原样' in text and '普通模块调试保持原样' in text
    assert 'SECRET' not in text


def test_detail_events_available_at_debug_with_same_redaction(ai_file_diagnostics):
    d.logger.setLevel(logging.DEBUG)
    d.event('media.page.finished', count=3, content='SECRET', request={'key':'SECRET'})
    assert records(ai_file_diagnostics) == [{'count':3}]
    assert 'SECRET' not in ai_file_diagnostics.read_text(encoding='utf-8')


def test_progress_is_per_execution_and_bounded(ai_file_diagnostics, monkeypatch):
    monkeypatch.setattr(d, '_progress_times', d.OrderedDict())
    with patch.object(d.time, 'monotonic', return_value=1):
        for _ in range(1000):
            d.event('index.checkpoint.committed', task_id='a', execution_id='one', processed=100, committed=True)
        d.event('index.checkpoint.committed', task_id='b', execution_id='one', committed=True)
        d.event('index.checkpoint.committed', task_id='a', execution_id='two', committed=True)
    assert len(records(ai_file_diagnostics)) == 3
    with patch.object(d.time, 'monotonic', return_value=61):
        d.event('index.checkpoint.committed', task_id='a', execution_id='one', processed=10000, committed=True)
    assert len(records(ai_file_diagnostics)) == 4
    assert records(ai_file_diagnostics)[-1]['processed'] == 10000
    for i in range(600):
        d.event('download.progress', task_id=str(i))
    assert len(d._progress_times) == 512


def test_concurrent_correlations_and_executor(ai_file_diagnostics):
    @d.observed('test.request')
    async def work(task_id):
        with d.bind(task_id=task_id):
            await asyncio.sleep(0)
            with ThreadPoolExecutor(max_workers=1) as executor:
                await d.executor_call(executor, lambda: d.event('test.thread'))
            d.event('test.done')
    async def run():
        await asyncio.gather(work('a'*32), work('b'*32))
    asyncio.run(run())
    values = records(ai_file_diagnostics)
    groups = {id: {x['trace_id'] for x in values if x.get('task_id')==id} for id in ['a'*32,'b'*32]}
    assert len(groups['a'*32]) == len(groups['b'*32]) == 1
    assert groups['a'*32].isdisjoint(groups['b'*32])
    assert d.context.get() == {}


def test_exception_sentinel_and_remote_stack(ai_file_diagnostics):
    try:
        raise ValueError('SECRET_CHAT_PROMPT_API_KEY_123')
    except ValueError as error:
        d.event('test.failed', error=error, request={'prompt':'SECRET_CHAT_PROMPT_API_KEY_123'}, text='SECRET_CHAT_PROMPT_API_KEY_123')
        d.event('test.child', **d.exception_fields(error))
    text = ai_file_diagnostics.read_text(encoding='utf-8')
    assert 'SECRET_CHAT_PROMPT_API_KEY_123' not in text
    assert 'ValueError' in text and 'test_ai_diagnostics.py' in text and 'test_exception_sentinel_and_remote_stack' in text


def test_resume_keeps_trace_but_changes_execution(ai_file_diagnostics):
    class Store:
        def get(self, kind, id): return {'trace_id':'c'*32}
    class Service:
        store = Store()
        @d.observed('test.execute', id_field='run_id', execution=True)
        async def execute(self, id): pass
    asyncio.run(Service().execute('a'*32)); asyncio.run(Service().execute('a'*32))
    values = records(ai_file_diagnostics)
    assert {x['trace_id'] for x in values} == {'c'*32}
    assert len({x['execution_id'] for x in values}) == 2


def test_background_failure_is_bounded_and_recovers(ai_file_diagnostics):
    failures = d.RepeatedFailures()
    with patch.object(d.time, 'monotonic', return_value=1):
        for _ in range(20): failures.report('test', ValueError('SECRET'))
    with patch.object(d.time, 'monotonic', return_value=62): failures.report('test', ValueError('SECRET'))
    failures.recovered('test')
    values = records(ai_file_diagnostics)
    assert len(values) == 3 and values[1]['count'] == 20 and not failures.items


@pytest.mark.parametrize('payload,status', [
    ({'events':[{'event':'request.failed','metadata':{'origin':'frontend','http_status':500,'trace_id':'a'*32}}]},200),
    ({'events':[{'event':'arbitrary text','metadata':{}}]},422),
    ({'events':[{'event':'request.failed','metadata':{'message':'SECRET'}}]},422),
    ({'events':[{'event':'request.failed','metadata':{'reason_code':'SECRET'}}]},422),
    ({'events':[{'event':'request.failed','metadata':{'trace_id':'SECRET'}}]},422),
    ({'events':[{'event':'request.failed','metadata':{}}]*51},422),
    ({'events':[{'event':'request.failed','metadata':{'message':'x'*65536}}]},413),
])
def test_diagnostics_ingest_limits(ai_file_diagnostics,payload,status):
    app = FastAPI(); app.include_router(router)
    app.middleware('http')(diagnostic_request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1)),base_url='http://localhost') as client:
            response = await client.post('/api/ai/diagnostics/events',json=payload,headers={d.HEADER:'b'*32})
            assert response.status_code == status
            assert response.headers[d.HEADER] == 'b'*32
    asyncio.run(run())
    assert 'SECRET' not in ai_file_diagnostics.read_text(encoding='utf-8')


def test_diagnostics_reject_remote_and_sanitize_server_exception(ai_file_diagnostics):
    app = FastAPI(); app.include_router(router)
    app.middleware('http')(diagnostic_request)
    @app.get('/api/ai/test-error')
    async def bad(): raise ValueError('SECRET_SERVER_ERROR')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('8.8.8.8',1)),base_url='http://localhost') as client:
            response = await client.post('/api/ai/diagnostics/events',json={'events':[]})
            assert response.status_code == 403
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',1)),base_url='http://localhost') as client:
            response = await client.get('/api/ai/test-error')
            assert response.status_code == 500 and response.json()['diagnostic_id'] == response.headers['X-WCDA-AI-Diagnostic']
            assert 'SECRET' not in response.text
    asyncio.run(run())
    assert 'SECRET' not in ai_file_diagnostics.read_text(encoding='utf-8')


def test_daily_rollover_concurrent_and_output_switch(tmp_path,monkeypatch):
    from wechat_decrypt_tool import logging_config as lc, app_paths
    output = [tmp_path/'one']
    monkeypatch.setattr(app_paths,'get_output_dir',lambda:output[0])
    class Clock:
        value = datetime(2026,9,9,23,59,59)
        @classmethod
        def now(cls): return cls.value
    monkeypatch.setattr(lc,'datetime',Clock)
    monkeypatch.setenv('WECHAT_TOOL_ENABLE_CONSOLE_LOG','0')
    first = lc.setup_logging()
    import uvicorn
    uvicorn.Config(FastAPI(), log_config=None)
    handler = next(h for h in logging.getLogger().handlers if isinstance(h,lc.RecreatingFileHandler))
    logging.getLogger('rollover').info('before-midnight')
    Clock.value = datetime(2026,9,10,0,0,0)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i:logging.getLogger('rollover').info('row-%s',i),range(100)))
    second = lc.get_log_file_path()
    assert second.name == '10_wechat_tool.log' and second != first
    assert 'row-' not in first.read_text(encoding='utf-8')
    assert second.read_text(encoding='utf-8').count('row-') == 100
    lc.setup_logging()
    assert next(h for h in logging.getLogger().handlers if isinstance(h,lc.RecreatingFileHandler)) is handler
    for name in ('uvicorn','uvicorn.access','uvicorn.error','fastapi'):
        logging.getLogger(name).info('unique-'+name)
        assert second.read_text(encoding='utf-8').count('unique-'+name+'\n') == 1
    handler.close(); shutil.rmtree(second.parent)
    logging.getLogger('rollover').info('recreated')
    assert 'recreated' in second.read_text(encoding='utf-8')
    output[0] = tmp_path/'two'
    third = lc.get_log_file_path()
    assert third.is_relative_to(output[0])
    assert handler is next(h for h in logging.getLogger().handlers if isinstance(h,lc.RecreatingFileHandler))


@pytest.mark.parametrize('level',['INFO','DEBUG'])
def test_sdk_and_dependency_content_boundary(tmp_path,monkeypatch,level):
    from wechat_decrypt_tool import logging_config as lc, app_paths
    monkeypatch.setattr(app_paths,'get_output_dir',lambda:tmp_path)
    monkeypatch.setenv('WECHAT_TOOL_ENABLE_CONSOLE_LOG','0')
    monkeypatch.setenv('WECHAT_TOOL_LOG_LEVEL',level)
    path = lc.setup_logging()
    for name in ('anthropic._base_client','openai._base_client','httpx','httpcore','langchain_core'):
        logging.getLogger(name).error('SECRET_SDK_PROMPT')
    with d.bind(trace_id='a'*32):
        try: raise ValueError('SECRET_EXCEPTION_BODY')
        except ValueError: logging.getLogger('legacy').exception('SECRET_LEGACY_TEXT')
        d.event('test.safe', count=2)
    logging.getLogger('uvicorn.access').info('%s %s %s %s %s','localhost','GET','/api/ai/materials?query=SECRET_SEARCH&q=SECRET_KEYWORD','HTTP/1.1',200)
    text = path.read_text(encoding='utf-8')
    assert 'SECRET' not in text
    assert 'test.safe' in text and 'ValueError' in text


@pytest.mark.parametrize('status,attempts',[(401,1),(429,3),(500,3),(408,3)])
def test_model_failures_keep_call_ids_and_safe_causes(tmp_path,ai_file_diagnostics,monkeypatch,status,attempts):
    from wechat_decrypt_tool.ai.providers import ModelService, ProviderFailure
    from wechat_decrypt_tool.ai.storage import AIStore
    class Client:
        async def ainvoke(self,*args,**kwargs):
            error = RuntimeError('SECRET_MODEL_ERROR')
            error.status_code = status
            raise error
    async def sleep(*args): pass
    monkeypatch.setattr(asyncio,'sleep',sleep)
    service = ModelService(AIStore(tmp_path/'db')); service.client = lambda profile: Client()
    with pytest.raises(ProviderFailure): asyncio.run(service.invoke({'id':'a'*32},'SECRET_PROMPT'))
    audit = service.store.list('usage')
    values = records(ai_file_diagnostics)
    calls = {r['call_id'] for r in values if r.get('call_id')}
    assert calls == {r['id'] for r in audit} and len(calls) == attempts
    assert all(r['status']=='failed' and r['trace_id'] for r in audit)
    assert all(r['queue_ms'] >= 0 for r in values if r.get('status') == 'failed' and r.get('call_id'))
    assert any(r.get('http_status')==status and r.get('frames') for r in values)
    assert 'SECRET' not in ai_file_diagnostics.read_text(encoding='utf-8')


def test_stream_characters_do_not_create_events(tmp_path,ai_file_diagnostics):
    from langchain_core.messages import AIMessageChunk
    from wechat_decrypt_tool.ai.agent_model import AgentModel
    from wechat_decrypt_tool.ai.providers import ModelService
    from wechat_decrypt_tool.ai.storage import AIStore
    class Client:
        async def astream(self,*args,**kwargs):
            for _ in range(1000): yield AIMessageChunk(content='SECRET_ANSWER')
    service = ModelService(AIStore(tmp_path/'db')); service.client = lambda profile: Client()
    value = asyncio.run(AgentModel(service).call({'id':'a'*32,'model':'test','protocol':'openai'},[], 'account'))
    assert len(value) == len('SECRET_ANSWER')*1000
    assert len(records(ai_file_diagnostics)) <= 8
    assert any(r.get('status') == 'success' and r.get('queue_ms', -1) >= 0 for r in records(ai_file_diagnostics))
    assert 'SECRET_ANSWER' not in ai_file_diagnostics.read_text(encoding='utf-8')


def test_index_rollback_never_reports_checkpoint_committed(tmp_path,ai_file_diagnostics):
    from wechat_decrypt_tool.local_search.index import SemanticIndex
    index = SemanticIndex(tmp_path/'index.sqlite3')
    def fail(): raise RuntimeError('SECRET_TRANSACTION')
    with pytest.raises(RuntimeError): index.commit('generation',[],[],[],{'id':'a'*32,'offset':100},fail)
    assert index.progress('a'*32) is None
    text = ai_file_diagnostics.read_text(encoding='utf-8')
    assert 'index.transaction.rolled_back' in text
    assert 'checkpoint.committed' not in text and 'SECRET_TRANSACTION' not in text


def test_download_initialization_failure_returns_safe_pipe_diagnostic(monkeypatch):
    from wechat_decrypt_tool.local_search import downloads
    class Pipe:
        values = []
        def send(self,value): self.values.append(value)
        def close(self): pass
    def fail(*args): raise ImportError('SECRET_COMPONENT_PATH')
    monkeypatch.setattr(downloads,'_download_worker',fail)
    pipe = Pipe(); downloads.download_worker(pipe,'root',{})
    assert pipe.values[0]['error'] == 'load'
    assert pipe.values[0]['diagnostic_fields']['error_type'] == 'ImportError'
    assert 'SECRET_COMPONENT_PATH' not in json.dumps(pipe.values)
