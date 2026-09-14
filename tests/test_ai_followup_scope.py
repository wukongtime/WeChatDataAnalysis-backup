"""续聊范围：历史保留、执行前校验、条件快照与时间输入的集成回归。"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from test_ai_deepagents import make_service, execute, action, last_result
from test_ai_deep_contracts import prepared
from wechat_decrypt_tool.ai.agent_service import AgentService
from wechat_decrypt_tool.ai.deep_runtime import RuntimeEvents
from wechat_decrypt_tool.ai.deep_tools import ChatGateway


class Request(SimpleNamespace):
    def override(self, **values):
        return Request(**{**vars(self), **values})


def current_state(messages):
    content = next(str(m.content) for m in messages if isinstance(m, SystemMessage))
    return json.JSONDecoder().raw_decode(content.rsplit('当前执行状态（程序元数据）：', 1)[1])[0]


@pytest.mark.parametrize('compatible', [False, True])
def test_real_graph_followup_and_restart_preserve_history_but_select_fresh_scope(tmp_path, monkeypatch, compatible):
    service, client = make_service(tmp_path, monkeypatch, compatible=compatible)
    def reply(name, args):
        return AIMessage(content=json.dumps({'type': 'tools', 'calls': [{'name': name, 'arguments': args}]})) if compatible else action(name, args)
    def final():
        text = '记录中有报价100元。[[' + 'a' * 24 + ']]'
        return AIMessage(content=json.dumps({'type': 'final', 'content': text})) if compatible else AIMessage(content=text)
    def search(messages):
        state = current_state(messages)
        return reply('search_messages', {'scope_handle': state['scopes'][0]['scope_handle'], 'query': '报价'})
    states = []
    def followup(messages):
        state = current_state(messages)
        states.append(state)
        assert state['scopes'] == [] and state['next_tool'] == 'select_chat_scope'
        assert state['select_chat_scope_args'] == {'conversations': ['friend']}
        assert state['reuse_previous_scope_args'] == {'reuse_previous': True}
        assert any('报价100元' in str(m.content) for m in messages)
        assert 'search_messages' not in [t['function']['name'] for t in client.definitions]
        return reply('select_chat_scope', state['reuse_previous_scope_args'])
    client.responses[:] = [reply('select_chat_scope', {}), search, final(),
        followup, search, final(), followup, search, final()]
    async def check():
        thread, first = await execute(service, '查看报价')
        assert first['status'] == 'completed', first.get('error')
        _, second = await execute(service, '继续查看报价', 'two', thread)
        restarted = AgentService(service.ai, service.tools)
        _, third = await execute(restarted, '再次查看报价', 'three', thread)
        for run in (second, third):
            assert run['status'] == 'completed', run.get('error')
            assert all(t['status'] == 'completed' for t in run['timeline'] if t['kind'] == 'tool')
        assert [s['run_id'] for s in states] == [second['id'], third['id']]
    asyncio.run(check())


@pytest.mark.parametrize('via_api', [False, True])
def test_native_parallel_old_calls_recover_without_querying(tmp_path, monkeypatch, via_api):
    service, client = make_service(tmp_path, monkeypatch)
    old = {}
    def read(messages):
        old.update(last_result(messages))
        return action('read_messages', {'scope_handle': old['scope_handle']})
    def stale(messages):
        assert current_state(messages)['scopes'] == []
        return AIMessage(content='', tool_calls=[{'id': 'stale' + str(i), 'name': 'search_messages',
            'args': {'scope_handle': old['scope_handle'], 'query': q}, 'type': 'tool_call'}
            for i, q in enumerate(('借钱', '微信转账'))])
    def recover(messages):
        failures = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.tool_call_id.startswith('stale')]
        assert len(failures) == 2
        assert all(f['error_code'] == 'scope_required' for f in failures)
        assert service.tools.calls.count('read') == 1
        return action('select_chat_scope', failures[0]['recovery']['reuse_previous_scope_args'])
    def search(messages):
        return action('search_messages', {'scope_handle': last_result(messages)['scope_handle'], 'query': '报价'})
    final = AIMessage(content='记录中有报价100元。[[' + 'a' * 24 + ']]')
    client.responses[:] = [action('select_chat_scope', {}), read, final, stale, recover, search, final]
    async def check():
        if via_api:
            from fastapi import FastAPI
            from httpx import ASGITransport, AsyncClient
            from wechat_decrypt_tool.routers import ai_agent
            app = FastAPI()
            app.include_router(ai_agent.router)
            app.dependency_overrides[ai_agent.local_only] = lambda: None
            monkeypatch.setattr(ai_agent, 'get_agent_service', lambda: service)
            monkeypatch.setattr(ai_agent, 'account_name', lambda name: name)
            # 使用桌面界面实际调用的路由，数据与模型均隔离到本测试。
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as api:
                response = await api.post('/api/ai/agent/threads', json={'account': 'account', 'username': 'friend'})
                assert response.status_code == 200
                thread = response.json()
                runs = []
                for index, question in enumerate(('查看报价', '继续查看报价')):
                    response = await api.post(f'/api/ai/agent/threads/{thread["id"]}/messages',
                        params={'account': 'account'}, json={'text': question, 'request_id': str(index)})
                    assert response.status_code == 200
                    run_id = response.json()['id']
                    await service.workers[run_id]
                    response = await api.get(f'/api/ai/agent/runs/{run_id}', params={'account': 'account'})
                    assert response.status_code == 200
                    runs.append(response.json())
                first, second = runs
        else:
            thread, first = await execute(service, '查看报价')
            _, second = await execute(service, '继续查看报价', 'two', thread)
        assert first['status'] == second['status'] == 'completed', second.get('error')
        failures = [t for t in second['timeline'] if t['kind'] == 'tool' and t['status'] == 'failed']
        assert len(failures) == 2
        assert all(t['result']['error_code'] == 'scope_required' for t in failures)
        assert service.tools.calls.count('read') == 2
    asyncio.run(check())


@pytest.mark.parametrize('name', ['search_messages', 'search_live_messages', 'read_messages', 'commit_findings',
    'read_context', 'count_messages', 'search_material', 'read_material', 'analyze_media', 'task'])
def test_every_scoped_tool_is_checked_before_handler(tmp_path, monkeypatch, name):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        events = RuntimeEvents(service, gateway)
        async def forbidden(_):
            pytest.fail('无效范围不能执行底层工具')
        request = Request(tool_call={'id': 'bad', 'name': name, 'args': {'scope_handle': 'old'}})
        result = await events.awrap_tool_call(request, forbidden)
        assert json.loads(result.content)['error_code'] == 'scope_required'
        first = await gateway.select(start=10, end=100)
        second = await gateway.select(start=100, end=200)
        result = await events.awrap_tool_call(request, forbidden)
        body = json.loads(result.content)
        assert body['error_code'] == 'invalid_scope_handle'
        assert {s['scope_handle'] for s in body['recovery']['scopes']} == {first['scope_handle'], second['scope_handle']}
    asyncio.run(check())


def test_json_compatibility_invalid_handle_uses_same_recovery(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, compatible=True)
    def reply(name, args):
        return AIMessage(content=json.dumps({'type': 'tools', 'calls': [{'name': name, 'arguments': args}]}))
    def recover(messages):
        result = json.loads(next(str(m.content).removeprefix('已执行工具返回的资料：')
            for m in reversed(messages) if str(m.content).startswith('已执行工具返回的资料：')))
        assert result['error_code'] == 'invalid_scope_handle'
        assert service.tools.calls.count('read') == 0
        return reply('search_messages', {'scope_handle': result['recovery']['scopes'][0]['scope_handle'], 'query': '报价'})
    client.responses[:] = [reply('select_chat_scope', {}),
        reply('search_messages', {'scope_handle': 'historical-missing', 'query': '报价'}), recover,
        AIMessage(content=json.dumps({'type': 'final', 'content': '记录中有报价100元。[[' + 'a' * 24 + ']]'}))]
    async def check():
        _, run = await execute(service, '查看报价')
        assert run['status'] == 'completed', run.get('error')
        assert service.tools.calls.count('read') == 1
        failed = [t for t in run['timeline'] if t['kind'] == 'tool' and t['status'] == 'failed']
        assert len(failed) == 1 and failed[0]['result']['error_code'] == 'invalid_scope_handle'
    asyncio.run(check())


def test_supplement_snapshot_survives_repeated_supplement_and_restart(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        selected = await gateway.select(start=100, end=200, complete=True)
        await gateway.read_next(selected['scope_handle'])
        thread_id = service.run(gateway.id)['thread_id']
        # 暂停调度仅为观察提交事务后的状态，不访问真实服务。
        monkeypatch.setattr(service, 'launch', lambda _: None)
        second = await service.submit(thread_id, 'account', {'text': '继续', 'request_id': 'two'})
        fresh = ChatGateway(service, second['id'], second['version'])
        assert fresh.scopes() == []
        assert fresh.previous_filters()['time_range'] == {'start': 100, 'end': 200}
        third = await service.submit(thread_id, 'account', {'text': '补充说明', 'request_id': 'three'})
        restarted = AgentService(service.ai, service.tools)
        fresh = ChatGateway(restarted, third['id'], third['version'])
        inherited = await fresh.select(reuse_previous=True)
        state = fresh.scope(inherited['scope_handle'])
        assert (state['start'], state['end']) == (100, 200)
        assert state['cursor'] == state['pending_page'] == ''
        assert not state['read_complete'] and state['pages'] == 0
        # 老版本缺少快照时不能猜测沿用更早一轮。
        restarted.update(third['id'], version=third['version'] + 1)
        assert ChatGateway(restarted, third['id'], third['version'] + 1).previous_filters() == {}
    asyncio.run(check())


@pytest.mark.parametrize('foreign', ['thread', 'account', 'no_scope'])
def test_previous_scope_origin_is_validated(tmp_path, monkeypatch, foreign):
    service, client = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        selected = await gateway.select(start=100, end=200) if foreign != 'no_scope' else None
        service.update(gateway.id, status='completed')
        client.responses.append(AIMessage(content='你好'))
        _, new = await execute(service, '你好', 'new')
        service.update(new['id'], status='running', previous_run_id=gateway.id)
        if foreign == 'account':
            service.update(gateway.id, account='foreign')
        elif foreign == 'no_scope':
            service.update(new['id'], thread_id=service.run(gateway.id)['thread_id'])
        fresh = ChatGateway(service, new['id'], 1)
        assert 'reuse_previous_scope_args' not in RuntimeEvents(service, fresh).recovery()
        if selected:
            with pytest.raises(ValueError):
                await fresh.select(reuse_previous=True)
            with pytest.raises(ValueError):
                fresh.scope(selected['scope_handle'])
        else:
            assert fresh.previous_filters() == {}
    asyncio.run(check())


@pytest.mark.parametrize('value', [1789352309, '1789352309', '2026-09-14T10:18:29+08:00'])
def test_scope_time_accepts_seconds_and_iso_at_tool_boundary(tmp_path, monkeypatch, value):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        service.update(gateway.id, cutoff=1790000000)
        select = next(t for t in gateway.tools() if t.name == 'select_chat_scope')
        result = await select.ainvoke({'start': 0, 'end': value})
        assert result['time_range'] == {'start': 0, 'end': 1789352309}
        assert gateway.interval('', 0, 1790000001)['end'] == 1790000000
    asyncio.run(check())


@pytest.mark.parametrize('value', [True, False, 1789352309.5, 1789352309.0, '1789352309.5',
    1789352309000, '1789352309000', '2026-02-30', -1])
def test_scope_time_rejects_invalid_units_and_types(tmp_path, monkeypatch, value):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service)
        with pytest.raises(ValueError, match='时间格式'):
            gateway.interval('', 0, value)
        select = next(t for t in gateway.tools() if t.name == 'select_chat_scope')
        with pytest.raises(ValueError):
            await select.ainvoke({'end': value})
    asyncio.run(check())


def test_explicit_dates_are_applied_before_parsing_bad_model_dates(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        gateway = await prepared(service, '查看2026年9月1日00:00到2026年9月11日00:00的消息')
        service.update(gateway.id, cutoff=1790000000, timezone_offset=28800)
        scope = await gateway.select(start='错误日期', end='1789352309000')
        assert scope['time_range'] == {'start': 1788192000, 'end': 1789056000}
    asyncio.run(check())
