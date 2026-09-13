"""模拟升级前已存任务，明确覆盖旧协议恢复；新版运行在 v2 专项中验证。"""
from unittest.mock import patch

import pytest
from test_ai_agent import service as base_agent_service


@pytest.fixture
def legacy_service(base_agent_service):
    service = base_agent_service
    create, submit = service.create_thread, service.submit

    async def create_old(account, username, title):
        thread = await create(account, username, title)
        thread.update(scope=[username], account_wide=False)
        return service.store.put('agent_thread', thread)

    async def submit_old(id, account, data):
        thread = service.thread(id, account)
        scope, revision = thread['scope'], thread['scope_revision']
        with patch.object(service, 'launch'):
            run = await submit(id, account, data)
        thread = service.thread(id, account)
        thread.update(scope=scope, scope_revision=revision, account_wide=False)
        service.store.put('agent_thread', thread)
        record = service.store.get('agent_run', run['id'])
        record['engine_version'] = 1
        record.pop('query_scope', None)
        service.store.put('agent_run', record)
        service.workspace.restrict(run['id'], scope, {})
        service.launch(run['id'])
        return service.run(run['id'])

    service.create_thread, service.submit = create_old, submit_old
    return service
