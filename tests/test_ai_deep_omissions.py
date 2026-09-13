"""遗漏核查的范围、原文校验与长消息分页，不请求外部模型。"""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

from test_ai_deepagents import make_service, execute
from wechat_decrypt_tool.ai.deep_tools import ChatGateway
from wechat_decrypt_tool.ai.deep_model import DeepChatModel
from wechat_decrypt_tool.ai.deep_omissions import omission_issues
from wechat_decrypt_tool.ai.providers import ProviderFailure
from wechat_decrypt_tool.ai.agent_budget import input_limit, size


@pytest.mark.parametrize('fault', ['', 'foreign', 'missing', 'fake_coverage'])
def test_omission_checks_uncited_original_and_rejects_invented_evidence(tmp_path, monkeypatch, fault):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running')
        gateway = ChatGateway(service, run['id'], 1)
        await gateway.select(complete=True)
        gateway.save_messages([{'source': 'a' * 24, 'username': 'friend', 'time': 10, 'text': '别打球了，球没什么好打的', 'sender': '甲'}])
        calls = []
        async def invoke(model, messages, **kwargs):
            payload = json.JSONDecoder().raw_decode(messages[1].content)[0]
            calls.append(payload)
            assert payload['original_page'][0]['text'].startswith('别打球了')
            item = {'source': ('b' if fault == 'foreign' else 'a') * 24,
                'verdict': 'covered' if fault == 'fake_coverage' else 'omitted', 'draft_quote': '草稿并没有这句话',
                'quote': '别打球了', 'reason': '活动建议包含劝阻，草稿未覆盖'}
            return AIMessage(content=json.dumps({'checks': [] if fault == 'missing' else [item]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        current = service.run(run['id'])
        if fault:
            with pytest.raises(ProviderFailure):
                await omission_issues(service, current, 1, '大家讨论吃饭。')
            assert len(calls) == 3
        else:
            issues = await omission_issues(service, current, 1, '大家讨论吃饭。')
            assert len(issues) == 1 and '别打球了' in issues[0]
            assert await omission_issues(service, current, 1, '大家讨论吃饭。') == issues
            assert len(calls) == 1
    asyncio.run(check())


def test_long_original_is_fully_checked_in_bounded_overlapping_fragments(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running')
        gateway = ChatGateway(service, run['id'], 1)
        await gateway.select(complete=True)
        text = ('安排\t"反斜杠\\"\n' * 12000) + '最后取消打球'
        gateway.save_messages([{'source': 'a' * 24, 'username': 'friend', 'time': 10, 'text': text, 'sender': '甲'},
            {'source': 'b' * 24, 'username': 'other', 'time': 10, 'text': '不能进入核查', 'sender': '乙'}])
        spans = []
        async def invoke(model, messages, **kwargs):
            assert size(messages[1].content) < input_limit(service.profile(service.run(run['id'])))
            values = json.loads(messages[1].content)['original_page']
            for value in values:
                assert value['username'] == 'friend'
                spans.append((value['text_offset'], value['text']))
            return AIMessage(content=json.dumps({'checks': [{'source': row['source'], 'verdict': 'irrelevant',
                'reason': '这里只验证长消息分页'} for row in values]}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        assert await omission_issues(service, service.run(run['id']), 1, '范围总结') == []
        end = 0
        for start, fragment in sorted(spans):
            assert start <= end and text[start:start + len(fragment)] == fragment
            end = max(end, start + len(fragment))
        assert end == len(text) and len(spans) > 1
    asyncio.run(check())


def test_partial_omission_checks_survive_failure_and_only_retry_missing_sources(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running')
        gateway = ChatGateway(service, run['id'], 1)
        await gateway.select(complete=True)
        gateway.save_messages([{'source': key * 24, 'username': 'friend', 'time': 10, 'text': '闲聊', 'sender': '甲'} for key in ('a', 'b')])
        calls = []
        async def invoke(model, messages, **kwargs):
            page = json.JSONDecoder().raw_decode(messages[1].content)[0]['original_page']
            calls.append([m['source'] for m in page])
            checks = [{'source': page[0]['source'], 'verdict': 'irrelevant', 'reason': '闲聊'}] if len(calls) in (1, 4) else []
            return AIMessage(content=json.dumps({'checks': checks}))
        monkeypatch.setattr(DeepChatModel, 'ainvoke', invoke)
        with pytest.raises(ProviderFailure):
            await omission_issues(service, service.run(run['id']), 1, '报告')
        assert calls == [[1, 2], [2], [2]]
        assert await omission_issues(service, service.run(run['id']), 1, '报告') == []
        assert calls[-1] == [2] and len(calls) == 4
    asyncio.run(check())


def test_first_evidence_review_uses_auxiliary_policy(tmp_path, monkeypatch):
    from wechat_decrypt_tool.ai.model_execution import call_policy
    service, client = make_service(tmp_path, monkeypatch)
    observed = []
    def factory(profile):
        observed.append(call_policy.get().auxiliary)
        return client
    service.ai.models.client = factory
    async def check():
        _, run = await execute(service)
        service.update(run['id'], status='running')
        client.responses = [AIMessage(content='{"checks":[]}')]
        await DeepChatModel(service=service, run_id=run['id'], input_version=1, purpose='evidence_review').ainvoke('核查')
        assert observed == [False, True]
    asyncio.run(check())
