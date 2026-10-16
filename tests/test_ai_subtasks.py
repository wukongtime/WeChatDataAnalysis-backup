"""子智能体真实编排使用合成消息及确定性模型，不调用付费接口。"""
import asyncio
import json
import time
from unittest.mock import patch

import pytest

from test_ai_agent import service
from wechat_decrypt_tool.ai.agent_subtasks import Subtasks
from wechat_decrypt_tool.ai.model_scheduler import Scheduler, ModelSlots, model_group, model_priority
from wechat_decrypt_tool.ai.agent_schemas import AgentAction


def test_shared_model_slots_limit_and_cancellation():
    async def run():
        slots = [ModelSlots(), ModelSlots()]
        active = peak = 0
        release = asyncio.Event()
        async def task(i):
            nonlocal active, peak
            async with slots[i % 2]:
                active += 1
                peak = max(peak, active)
                try:
                    await release.wait()
                finally:
                    active -= 1
        tasks = [asyncio.create_task(task(i)) for i in range(20)]
        await asyncio.sleep(.01)
        assert active == 4
        tasks[10].cancel()
        tasks[0].cancel()
        await asyncio.sleep(.01)
        assert active == 4
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert peak == 4 and active == 0
    asyncio.run(run())


def test_priority_round_robin_and_rate_limit():
    async def run():
        scheduler = Scheduler(1)
        release = asyncio.Event()
        order = []
        async def task(name, priority, block=False):
            t = model_group.set(name); p = model_priority.set(priority)
            try:
                async with scheduler.slot():
                    order.append(name)
                    if block: await release.wait()
            finally:
                model_priority.reset(p); model_group.reset(t)
        first = asyncio.create_task(task('A', 0, True))
        await asyncio.sleep(0)
        tasks = [asyncio.create_task(task(name, priority)) for name, priority in [('background',1),('A',0),('B',0),('A',0),('B',0)]]
        await asyncio.sleep(0); release.set()
        await asyncio.gather(first, *tasks)
        assert order == ['A','B','A','B','A','background']
        scheduler.limit=4; scheduler.throttled()
        assert scheduler.limit == 2
    asyncio.run(run())


async def parent_run(service, mode='overview', scope=None):
    thread = await service.create_thread('account', 'friend', '新的对话')
    with patch.object(service, 'launch'):
        run = await service.submit(thread['id'], 'account', {'text':'总结讨论的重要事情', 'request_id':'test'})
    scope = scope or ['friend','another']
    end = int(time.time())
    interval = {'start':end-1000, 'end':end}
    return service.update(run['id'], status='running', applied_version=1,
        input_digest='总结讨论的重要事情', intent={'mode':mode,'objective':'总结讨论的重要事情'},
        query_scope=scope, query_filters={'conversations':scope,'time_range':interval,'sender':None},
        time_range=interval)








