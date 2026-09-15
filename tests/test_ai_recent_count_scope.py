"""最近消息数量的自然表达必须落到数量范围，不能被误当成全历史请求。"""
import asyncio

import pytest
from langchain_core.messages import AIMessage

from test_ai_deepagents import NoData, action, execute, last_result, make_service
from test_ai_deep_contracts import prepared


@pytest.mark.parametrize('question', [
    '最近的100条消息再说什么？',
    '帮我看看最近的100条消息在说什么？',
    '最近100条消息在说什么？',
    '最后的100条消息',
    '最新的 100 条消息',
    '近 100 条消息',
])
def test_count_scope_accepts_natural_wording(tmp_path, monkeypatch, question):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        service.update(gateway.id, input_digest=question)
        result = await gateway.select(message_count=100)
        scope = gateway.scope(result['scope_handle'])
        assert scope['message_count'] == 100
        assert scope['start'] == 0 and scope['end'] == service.run(gateway.id)['cutoff']
        assert scope['conversations'] == ['friend']

    asyncio.run(check())


def test_wrong_count_feedback_preserves_requested_limit(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)

    async def check():
        gateway = await prepared(service)
        service.update(gateway.id, input_digest='昨天最近的100条消息在说什么？')
        with pytest.raises(ValueError, match='message_count 设为 100'):
            await gateway.select(message_count=50, time_phrase='昨天')
        assert not gateway.scopes()
        result = await gateway.select(message_count=100, time_phrase='昨天')
        scope = gateway.scope(result['scope_handle'])
        assert scope['message_count'] == 100
        assert scope['end'] - scope['start'] == 86400

    asyncio.run(check())


def test_recent_100_question_succeeds_without_scope_retries(tmp_path, monkeypatch):
    class RecentChat(NoData):
        async def recent_set(self, account, conversations, start, end, count, checkpoint, **kwargs):
            self.calls.append(('recent_set', list(conversations), start, end, count))
            checkpoint()
            return {'messages': [{'source': f'{i + 1:024x}', 'username': 'friend', 'anchor': f'db:{i}',
                'time': end - 100 + i, 'sender': '甲', 'kind': 'text', 'text': '讨论出行安排', 'media': {}}
                for i in range(count)]}

        async def read(self, *args, **kwargs):
            pytest.fail('最近100条应使用数量查询，不能退回遍历全部历史')

    tools = RecentChat()
    service, _ = make_service(tmp_path, monkeypatch, tools=tools, responses=[
        action('select_chat_scope', {'message_count': 100}),
        lambda messages: action('read_messages', {'scope_handle': last_result(messages)['scope_handle']}),
        AIMessage(content='最近100条消息主要讨论出行安排。'),
    ])
    # 本例验证数量范围和业务调用次数，窗口须容纳完整工具定义及这 100 条资料。
    # 小窗口压缩、无进展和恢复由 test_ai_sawtooth.py 单独覆盖。
    profile = service.store.get('profile', 'model')
    profile.update(context_window=131072, model_overrides={'context_window': 131072})
    service.store.put('profile', profile, id='model')

    async def check():
        _, run = await execute(service, '最近的100条消息再说什么？')
        assert run['status'] == 'completed', run.get('error')
        assert run['read_count'] == 100
        usage = service.store.list('usage')
        assert len(usage) == 3
        assert all(u.get('purpose') == 'deepagents_agent' for u in usage)
        assert [call[4] for call in tools.calls if isinstance(call, tuple)] == [100]
        steps = [item for item in run['timeline'] if item['kind'] == 'tool']
        assert [step['action'] for step in steps] == ['select_chat_scope', 'read_messages']
        assert all(step['status'] == 'completed' for step in steps)

    asyncio.run(check())
