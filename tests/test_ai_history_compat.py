"""账号级历史兼容：旧范围字段不隐藏回答，读取不裁剪历史原文。"""
import asyncio
import pytest

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from test_ai_continuous_v2 import material


@pytest.mark.parametrize('legacy_revision', [None, 0])
def test_old_history_sources_and_people_survive_scope_revision(service, legacy_revision):
    async def run():
        thread, task = await idle_run(service)
        row = material(1, 'friend', '甲说乙负责安排场地')
        row['sender_id'] = 'sender-a'
        person = 'f' * 24
        answer = f'[[person:{person}]]负责安排。[[{row["source"]}]]'
        service.update(task['id'], evidence={row['source']: row}, answer=answer,
                       references={person: {'id': person, 'kind': 'person', 'name': '乙', 'username': 'person-b',
                                            'sources': [row['source']], 'mentioned_sources': [row['source']]}},
                       scope_revision=legacy_revision)
        service.finish(task['id'], 'completed')
        saved = service.thread(thread['id'], 'account')
        saved.update(scope=['another'], scope_revision=9, account_wide=False)
        saved['messages'][-1]['citations'] = []
        saved['messages'][-1]['references'] = []
        service.store.put('agent_thread', saved)
        recovered = type(service)(service.ai, service.tools, service.model)
        result = recovered.public_thread(thread['id'], 'account')['messages'][-1]
        assert result['text'] == answer
        assert result['references'][0]['name'] == '乙'
        assert result['citations'][0]['sender_id'] == 'sender-a'
        assert recovered.public_run(task['id'], 'account')['answer'] == answer
        page = recovered.material_page(task['id'], 'account')
        assert page['total'] == 1 and page['items'][0]['text'] == row['text']
        assert 'username=sender-a' in page['items'][0]['sender_avatar_path']
        assert recovered.run(task['id'])['evidence'][row['source']] == row
        assert recovered.thread(thread['id'], 'account') == saved
        with pytest.raises(ValueError):
            recovered.public_thread(thread['id'], 'other-account')
        with pytest.raises(ValueError):
            recovered.material_page(task['id'], 'other-account')
        with pytest.raises(ValueError):
            recovered.material_page(task['id'], 'account', version=99)
    asyncio.run(run())
