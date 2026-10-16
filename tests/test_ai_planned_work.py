"""主模型规划门禁与异步官方图回归；全部使用构造资料和模拟模型。"""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

from test_ai_deepagents import make_service, execute, action, last_result
from test_ai_parallel_analysis import Data
from wechat_decrypt_tool.ai.deep_tools import ChatGateway
from wechat_decrypt_tool.ai.deep_planning import MainWork, BranchWork


def test_normal_question_can_search_six_targets_then_read_and_check_context(tmp_path, monkeypatch):
    """复现借、还、欠之后继续核对具体金额，不能被固定次数拦截。"""
    queries = ['借', '还', '欠', '2200', '1500 周转', '转账']
    data = Data(8, text='这笔往来还需要根据原文核实方向')
    searched = []
    async def search(account, username, query, start, end, offset):
        searched.append(query)
        return {'messages': [data.rows[queries.index(query)]], 'has_more': False}
    async def context(account, original):
        return {'messages': [original, data.rows[7]]}
    data.search, data.context = search, context
    scope = {}
    service, client = make_service(tmp_path, monkeypatch, tools=data)
    def search_step(query):
        def invoke(messages):
            scope.update(scope_handle=last_result(messages).get('scope_handle', scope.get('scope_handle')))
            names = {d['function']['name'] for d in client.definitions}
            assert {'search_messages', 'read_messages', 'read_context'} <= names
            return action('search_messages', {'scope_handle': scope['scope_handle'], 'query': query})
        return invoke
    client.responses = [action('select_chat_scope', {}), *(search_step(q) for q in queries),
        lambda _: action('read_messages', {'scope_handle': scope['scope_handle']}),
        lambda _: action('read_context', {'scope_handle': scope['scope_handle'], 'source': data.rows[0]['source']}),
        AIMessage(content='这些往来的方向尚未全部确认，暂不能给出可靠欠款总额。[[' + data.rows[0]['source'] + ']]')]
    async def check():
        _, run = await execute(service, '能统计一下他欠了我多少钱吗？')
        assert run['status'] == 'completed', run.get('error')
        assert searched == queries
        calls = [t for t in run['timeline'] if t.get('kind') == 'tool']
        assert len(calls) == 9 and all(t['status'] == 'completed' for t in calls)
        assert service.subtasks.summary(service.run(run['id']))['total'] == 0
    asyncio.run(check())


async def prepare(service, question='能分析一下往来约定吗？'):
    _, run = await execute(service)
    service.update(run['id'], status='running', finished_at=None, input_digest=question, cutoff=2_000_000_000)
    gateway = ChatGateway(service, run['id'], 1)
    selected = await gateway.select(conversations=['friend'])
    scope = selected['scope_handle']
    first = await gateway.read_next(scope)
    receipt = service.planned_work.receipt(gateway.guard(), 'read_messages', first, {'scope_handle': scope})
    second = await gateway.read_next(scope)
    service.planned_work.receipt(gateway.guard(), 'read_messages', second, {'scope_handle': scope})
    return gateway, scope, receipt, first['messages'][0]['source'], second['messages'][0]['source']


def make_plan(service, gateway, scope, receipt, main_source, branch_source, **changes):
    values = dict(preliminary_analysis='目前原文有两项不同约定，需要分别核对其成立条件。', evidence_handles=[receipt],
        parallel_reason='两组约定有各自独立的原文，主线判断第一项时可同时核查第二项。',
        main_work=MainWork(scope_handle=scope, source_ids=[main_source], description='核对第一项约定的前置条件，保留未达成条件及变化。', expected_output='第一项约定的条件与来源'),
        branches=[BranchWork(scope_handle=scope, source_ids=[branch_source], title='核查第二项约定', role='fact-checker',
            description='核查第二项约定是否存在明确取消，保留取消条件和真实来源。', expected_output='第二项约定的局部事实与疑点')])
    values.update(changes)
    return service.planned_work.plan(gateway, **values)


def test_scope_never_spawns_or_prereads_even_complete(tmp_path, monkeypatch):
    data = Data(60)
    service, _ = make_service(tmp_path, monkeypatch, tools=data)
    async def check():
        _, run = await execute(service)
        for question in ('统计一下他欠了多少钱', '完整分析多年来的全部聊天'):
            service.update(run['id'], status='running', input_digest=question)
            gateway = ChatGateway(service, run['id'], 1)
            result = await gateway.select(conversations=['friend'], complete=True)
            assert not data.calls
            assert 'plan_handle' not in result
            assert service.subtasks.summary(gateway.guard())['total'] == 0
            assert result.get('execution_mode') != 'parallel'
    asyncio.run(check())


@pytest.mark.parametrize('invalid', ['no_receipt', 'waiting_main', 'overlap', 'dependency', 'too_many', 'duplicate'])
def test_invalid_plans_cannot_start(tmp_path, monkeypatch, invalid):
    service, _ = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        main = MainWork(scope_handle=scope, source_ids=[first], description='核对第一项约定的前置条件，保留未达成条件及变化。', expected_output='第一项约定的条件与来源')
        branch = BranchWork(scope_handle=scope, source_ids=[second], title='核查第二项约定', role='fact-checker', description='核查第二项约定是否存在明确取消，保留条件和来源。', expected_output='第二项约定的局部事实与疑点')
        changes = {}
        if invalid == 'no_receipt': changes['evidence_handles'] = ['fake']
        if invalid == 'waiting_main': changes['main_work'] = main.model_copy(update={'description': '等待全部子任务完成后汇总各分支结果'})
        if invalid == 'overlap': changes['branches'] = [branch.model_copy(update={'source_ids': [first]})]
        if invalid == 'dependency': changes['branches'] = [branch.model_copy(update={'depends_on': ['not-completed']})]
        if invalid == 'too_many': changes['branches'] = [branch] * 4
        if invalid == 'duplicate': changes['branches'] = [branch] * 2
        with pytest.raises(ValueError):
            make_plan(service, gateway, scope, receipt, first, second, **changes)
        assert not service.planned_work.jobs(gateway.guard())
    asyncio.run(check())


def test_unplanned_task_and_changed_description_are_blocked(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        with pytest.raises(ValueError, match='parallel_plan_required'):
            service.planned_work.binding(gateway, {'scope_handle': scope})
        planned = make_plan(service, gateway, scope, receipt, first, second)
        branch = planned['branches'][0]
        with pytest.raises(ValueError, match='完整说明'):
            service.planned_work.binding(gateway, {'plan_handle': planned['plan_handle'], 'branch_handle': branch['id'],
                'scope_handle': scope, 'subagent_type': branch['role'], 'description': '原始问题'})
        assert not service.planned_work.jobs(gateway.guard())
    asyncio.run(check())


def test_child_first_request_has_material_and_last_commit_ends_graph(tmp_path, monkeypatch):
    service, client = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        planned = make_plan(service, gateway, scope, receipt, first, second)
        plan = service.planned_work.get(gateway.guard(), planned['plan_handle'])
        branch = plan['branches'][0]
        def commit(messages):
            material = json.loads(next(m.content.split('：', 1)[1] for m in messages if str(m.content).startswith('程序已读取的分支资料')))
            assert material['messages'][0]['source'] == second
            assert branch['description'] in str(messages)
            assert branch['expected_output'] in str(messages)
            return action('commit_findings', {'scope_handle': material['scope_handle'], 'page_id': material['page_id'],
                'findings': [{'text': '第二项记录中出现一项约定。', 'sources': [second]}]})
        client.responses = [commit]
        before = len(client.requests)
        handle = service.planned_work.launch(gateway.guard(), plan, branch)
        assert not service.planned_work.jobs(gateway.guard())[0].get('finished_at')
        with pytest.raises(ValueError, match='主线'):
            await service.planned_work.wait(gateway, plan['id'], [])
        service.planned_work.main_result(gateway, plan['id'], '第一项约定的条件需要保留，原文没有证明已经履行。', [first])
        waited = await service.planned_work.wait(gateway, plan['id'], [])
        assert waited['all_settled']
        job = service.planned_work.jobs(gateway.guard())[0]
        assert job['status'] == 'completed', job
        assert len(client.requests) - before == 1
        with pytest.raises(ValueError, match='全部分支事实'):
            service.planned_work.close(gateway, plan['id'], '两项约定都有原文记录，但其状态无法直接合并。', [first, second], [])
        result = service.planned_work.results(gateway, handle['task_handle'])
        assert result['total'] == 1
        service.planned_work.close(gateway, plan['id'], '两项约定都有原文记录，但其状态无法直接合并。', [first, second], [])
        assert service.planned_work.ready(gateway.guard())
    asyncio.run(check())


def test_official_task_returns_before_child_and_main_keeps_working(tmp_path, monkeypatch):
    from langchain_core.messages import AIMessageChunk
    service, client = make_service(tmp_path, monkeypatch, tools=Data(2, text='约定在条件达成后执行'))
    state = {'step': 0, 'child_calls': 0}
    async def check():
        child_entered, main_worked = asyncio.Event(), asyncio.Event()
        async def stream(messages, **kwargs):
            # 提示词变长可能触发真实压缩；摘要请求不能消耗主线脚本的下一步工具调用。
            if any('<history_fragment>' in str(m.content) or '<context_compaction>' in str(m.content) for m in messages):
                yield AIMessageChunk(content='保留两项约定的来源、分支发现和待完成的主线汇总，按程序状态继续。')
                return
            client.requests.append(messages)
            if '你是隔离的聊天证据分析员' in str(messages[0].content):
                state['child_calls'] += 1
                child_entered.set()
                await asyncio.wait_for(main_worked.wait(), 10)
                material = json.loads(next(m.content.split('：', 1)[1] for m in messages if str(m.content).startswith('程序已读取的分支资料')))
                response = action('commit_findings', {'scope_handle': material['scope_handle'], 'page_id': material['page_id'],
                    'findings': [{'text': '第二项约定有前置条件，不能认定已经执行。', 'sources': [state['second']]}]})
            else:
                step = state['step']; state['step'] += 1
                if step == 0: response = action('select_chat_scope', {})
                elif step == 1:
                    state['scope'] = last_result(messages)['scope_handle']
                    response = action('read_messages', {'scope_handle': state['scope']})
                elif step == 2:
                    result = last_result(messages)
                    state.update(receipt=result['observation_handle'], first=result['messages'][0]['source'])
                    response = action('read_messages', {'scope_handle': state['scope']})
                elif step == 3:
                    state['second'] = last_result(messages)['messages'][0]['source']
                    response = action('plan_parallel_work', {'preliminary_analysis': '资料存在两项独立约定，均涉及需要满足的前置条件。', 'evidence_handles': [state['receipt']],
                        'parallel_reason': '两项约定使用独立来源，主线分析第一项时可以同时核查第二项的条件。',
                        'main_work': {'scope_handle': state['scope'], 'source_ids': [state['first']], 'description': '判断第一项约定的前置条件，区分计划和已经执行的事实。', 'expected_output': '第一项约定的状态与原文来源'},
                        'branches': [{'scope_handle': state['scope'], 'source_ids': [state['second']], 'title': '第二项约定核查', 'role': 'fact-checker',
                            'description': '核查第二项约定的前置条件是否已经满足，保留无法确认的疑点。', 'expected_output': '第二项约定的条件事实与来源'}]})
                elif step == 4:
                    result = last_result(messages); branch = result['branches'][0]
                    state['plan'] = result['plan_handle']
                    response = action('task', {'plan_handle': state['plan'], 'branch_handle': branch['id'], 'scope_handle': state['scope'],
                        'subagent_type': branch['role'], 'description': branch['description']})
                elif step == 5:
                    state['task'] = last_result(messages)['task_handle']
                    await asyncio.wait_for(child_entered.wait(), 10)
                    main_worked.set()
                    response = action('record_main_analysis', {'plan_handle': state['plan'], 'analysis': '第一项约定仍附带前置条件，现有原文不能证明已经履行。', 'sources': [state['first']]})
                elif step == 6: response = action('wait_subtasks', {'plan_handle': state['plan']})
                elif step == 7: response = action('read_results', {'task_handle': state['task']})
                elif step == 8: response = action('finish_parallel_work', {'plan_handle': state['plan'], 'synthesis': '两项约定分别有前置条件，两份原文均无法证明条件已经满足。', 'sources': [state['first'], state['second']]})
                else: response = AIMessage(content='两项约定都带有前置条件，尚不能确认已经执行。[[' + state['first'] + ']][[' + state['second'] + ']]')
            yield AIMessageChunk(content=response.content, tool_calls=response.tool_calls, id='model:' + str(len(client.requests)))
        client.astream = stream
        _, run = await execute(service, '比较两项往来约定的条件和状态')
        assert run['status'] == 'completed', run.get('error')
        assert main_worked.is_set() and state['child_calls'] == 1
        assert state['step'] == 10
        assert run['subtasks']['total'] == run['subtasks']['completed'] == 1
    asyncio.run(check())


def test_many_pages_stay_one_branch_and_resume_reuses_completed(tmp_path, monkeypatch):
    from test_ai_parallel_analysis import fake_workers
    data = Data(32)
    for message in data.rows[2:]: message['username'] = 'other'
    service, _ = make_service(tmp_path, monkeypatch, tools=data)
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        service.update(gateway.id, input_digest='完整分析两个聊天的约定变化')
        other = await gateway.select(conversations=['other'])
        planned = make_plan(service, gateway, scope, receipt, first, second, branches=[BranchWork(
            scope_handle=other['scope_handle'], title='另一聊天的约定变化', role='range-analyst',
            description='提取另一聊天中约定的状态变化，记录取消与未满足的条件。', expected_output='全部局部事实、来源和状态疑点')])
        stats = fake_workers(service, monkeypatch, delay=.01)
        plan = service.planned_work.get(gateway.guard(), planned['plan_handle'])
        service.planned_work.launch(gateway.guard(), plan, plan['branches'][0])
        service.planned_work.main_result(gateway, plan['id'], '主线约定仅记录了条件，目前没有履行完成的直接依据。', [first])
        await service.planned_work.wait(gateway, plan['id'], [])
        jobs = service.planned_work.jobs(gateway.guard())
        assert len(jobs) == 1 and jobs[0]['status'] == 'completed'
        assert len(stats['commits']) == 30
        child = service.run(jobs[0]['child_run_id'])
        assert service.workspace.get(child['id'], 1, 'scope:' + child['scope_handle'])['pages'] == 30
        service.planned_work.restore(gateway.guard())
        assert len(stats['runs']) == 1
    asyncio.run(check())


def test_cancel_before_worker_starts_settles_all_counts(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        planned = make_plan(service, gateway, scope, receipt, first, second)
        parent = gateway.guard()
        plan = service.planned_work.get(parent, planned['plan_handle'])
        service.planned_work.launch(parent, plan, plan['branches'][0])
        service.finish(parent['id'], 'cancelled', '模拟用户停止')
        await service.planned_work.cancel(parent)
        summary = service.subtasks.summary(service.run(parent['id']))
        assert summary['running'] == summary['queued'] == 0
        assert summary['interrupted'] == 1
        assert not [r for r in service.store.list('agent_run') if r.get('parent_run_id')]
    asyncio.run(check())


def test_query_branch_no_match_uses_no_model_and_does_not_claim_full_scope(tmp_path, monkeypatch):
    data = Data(3)
    async def search(*args, **kwargs): return {'messages': [], 'has_more': False, 'warning': '索引未覆盖不可用附件'}
    data.search = search
    service, client = make_service(tmp_path, monkeypatch, tools=data)
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        other = await gateway.select(conversations=['other'])
        planned = make_plan(service, gateway, scope, receipt, first, second, branches=[BranchWork(
            scope_handle=other['scope_handle'], title='另一聊天的取消证据', role='retrieval-analyst', query='取消',
            description='查找另一聊天中明确取消约定的证据，保留未命中和数据缺口。', expected_output='取消证据或明确的未命中范围')])
        before = len(client.requests)
        parent = gateway.guard(); plan = service.planned_work.get(parent, planned['plan_handle'])
        handle = service.planned_work.launch(parent, plan, plan['branches'][0])
        service.planned_work.main_result(gateway, plan['id'], '主线已有条件约定，但仍没有条件已满足的直接证据。', [first])
        await service.planned_work.wait(gateway, plan['id'], [])
        assert len(client.requests) == before
        result = service.planned_work.results(gateway, handle['task_handle'])
        assert result['status'] == 'completed', result
        assert result['total'] == 0 and result['warnings']
        assert not gateway.scope(other['scope_handle'])['read_complete']
    asyncio.run(check())


def test_old_cancelled_task_only_gets_new_version_when_user_resumes(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, _, _, _, _ = await prepare(service)
        service.update(gateway.id, status='cancelled', subtask_plan_version=1)
        launched = []
        monkeypatch.setattr(service, 'launch', lambda id: launched.append(id))
        assert not launched
        result = await service.resume(gateway.id, 'account')
        assert result['version'] == 2 and result['subtask_plan_version'] == 2
        assert not result['scope_handle'] and result['subtasks'] == {}
        assert len(result['evidence']) == 2 and launched == [gateway.id]
        assert not service.planned_work.rows(result, 'work_plan')
    asyncio.run(check())


def test_three_branches_plus_main_share_four_model_slots(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.model_scheduler import scheduler
    from test_ai_parallel_analysis import fake_workers
    data = Data(4)
    service, _ = make_service(tmp_path, monkeypatch, tools=data)
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        gateway.save_messages([], data.rows[2:])
        branches = [BranchWork(scope_handle=scope, source_ids=[m['source']], title=f'核查约定 {i}', role='fact-checker',
            description=f'核查第 {i} 项约定的前置条件，保留状态变化及来源。', expected_output='约定的具体条件与状态事实') for i, m in enumerate(data.rows[1:], 2)]
        planned = make_plan(service, gateway, scope, receipt, first, second, branches=branches)
        stats = fake_workers(service, monkeypatch, delay=.01)
        worker = service.execute
        entered = asyncio.Event()
        async def scheduled(id):
            async with scheduler().slot():
                if scheduler().active == 4: entered.set()
                await entered.wait()
                await worker(id)
        monkeypatch.setattr(service, 'execute', scheduled)
        parent = gateway.guard(); plan = service.planned_work.get(parent, planned['plan_handle'])
        async with scheduler().slot():
            handles = [service.planned_work.launch(parent, plan, b) for b in plan['branches']]
            again = service.planned_work.launch(parent, plan, plan['branches'][0])
            assert again['reused'] and again['task_handle'] == handles[0]['task_handle']
            await asyncio.wait_for(entered.wait(), 5)
            assert scheduler().active == 4
            service.planned_work.main_result(gateway, plan['id'], '第一项约定的状态仍受条件约束，需要保留尚未满足的前提。', [first])
        while not (await service.planned_work.wait(gateway, plan['id'], []))['all_settled']:
            await asyncio.sleep(0)
        assert len(service.planned_work.jobs(parent)) == 3
        assert stats['peak'] == 3
        assert not scheduler().active
    asyncio.run(check())


def test_revision_discards_late_result_and_preserves_new_version(tmp_path, monkeypatch):
    from test_ai_parallel_analysis import fake_workers
    service, _ = make_service(tmp_path, monkeypatch, tools=Data(3))
    async def check():
        gateway, scope, receipt, first, second = await prepare(service)
        planned = make_plan(service, gateway, scope, receipt, first, second)
        fake_workers(service, monkeypatch, delay=.1)
        parent = gateway.guard(); plan = service.planned_work.get(parent, planned['plan_handle'])
        service.planned_work.launch(parent, plan, plan['branches'][0])
        pending = list(service.planned_work.tasks.values())
        await asyncio.sleep(.02)
        service.update(parent['id'], version=2, analysis={}, subtasks={})
        await asyncio.gather(*pending, return_exceptions=True)
        current = service.run(parent['id'])
        assert current['version'] == 2 and current['subtasks'] == {}
        assert service.workspace.page(parent['id'], 2, 'finding')['total'] == 0
        assert not service.planned_work.tasks
    asyncio.run(check())
