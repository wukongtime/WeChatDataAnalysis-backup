"""SDK 适配的真实字段合同；使用官方响应类型，不访问网络。"""
import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai.types.chat import ChatCompletionChunk, ChatCompletion

from wechat_decrypt_tool.ai.reasoning_client import ReasoningClient


def test_tool_binding_copies_without_recursion_and_preserves_reasoning():
    client = ReasoningClient({'model': 'fixture'}, SimpleNamespace())
    bound = client.bind_tools([{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}], tool_choice='auto')
    assert not client.options and bound.options['tool_choice'] == 'auto'
    history = [HumanMessage(content='查找'), AIMessage(content='', additional_kwargs={'reasoning_content': '内部字段应原样保留'},
        tool_calls=[{'id': 'call', 'name': 'lookup', 'args': {'names': ['甲']}, 'type': 'tool_call'}]), ToolMessage(content='已找到', tool_call_id='call')]
    result = client.messages(history)
    assert result[1]['reasoning_content'] == '内部字段应原样保留'
    assert result[2]['tool_call_id'] == 'call'
    assert '"names": ["甲"]' == result[1]['tool_calls'][0]['function']['arguments'][1:-1]


def test_official_stream_fields_usage_and_close(monkeypatch):
    client = ReasoningClient({'model': 'fixture'}, SimpleNamespace())
    requests, closed = [], []
    class Stream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append('stream')
        async def __aiter__(self):
            for delta, finish, usage in [({'role': 'assistant', 'reasoning_content': '内部'}, None, None),
                ({'content': '你好'}, 'stop', None), ({}, None, {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25, 'completion_tokens_details': {'reasoning_tokens': 2}})]:
                yield ChatCompletionChunk.model_validate({'id': 'response', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fixture',
                    'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}] if usage is None else [], 'usage': usage})
    class SDK:
        def __init__(self): self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append('client')
        async def create(self, **kwargs): requests.append(kwargs); return Stream()
    monkeypatch.setattr(client, 'client', SDK)
    async def check():
        result = None
        async for part in client.astream([HumanMessage(content='你好')], stream_usage=True):
            result = part if result is None else result + part
        assert result.content == '你好' and result.additional_kwargs['reasoning_content'] == '内部'
        assert result.usage_metadata['output_token_details']['reasoning'] == 2
        assert requests[0]['stream_options'] == {'include_usage': True}
        assert closed == ['stream', 'client']
    asyncio.run(check())


def test_official_nonstream_tool_reply(monkeypatch):
    client = ReasoningClient({'model': 'fixture'}, SimpleNamespace())
    class SDK:
        def __init__(self): self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def create(self, **kwargs):
            return ChatCompletion.model_validate({'id': 'response', 'object': 'chat.completion', 'created': 1, 'model': 'fixture', 'choices': [{'index': 0,
                'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'reasoning_content': '保留这段内部状态',
                    'tool_calls': [{'id': 'call', 'type': 'function', 'function': {'name': 'lookup', 'arguments': '{"names":["甲"]}'}}]}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14}})
    monkeypatch.setattr(client, 'client', SDK)
    async def check():
        result = await client.ainvoke([HumanMessage(content='查找')])
        assert result.tool_calls[0]['args'] == {'names': ['甲']}
        assert result.additional_kwargs['reasoning_content'] == '保留这段内部状态'
    asyncio.run(check())
