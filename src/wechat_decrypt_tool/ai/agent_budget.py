"""Agent 请求预算；未知分词器使用 UTF-8 字节上界，避免按模型名称猜窗口。"""
import json
from contextvars import ContextVar

from .providers import ProviderFailure

active_budget = ContextVar('agent_input_budget', default=None)


class ContextOverflow(ProviderFailure):
    pass


def size(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return len(value.encode('utf-8'))


def input_limit(profile):
    limit = active_budget.get() or profile.get('input_budget', 12000)
    window = profile.get('context_window')
    if window:
        limit = min(limit, max(512, int(window) - output_limit(profile) - 512))
    return int(limit)


def output_limit(profile):
    return min(4096, max(256, int(profile.get('context_window') or 32768) // 4))


def check_request(profile, messages, extra=None):
    # 计入消息封装与工具 Schema；这是保守预算，不冒充供应商实际 Token 用量。
    def content_size(content):
        if isinstance(content,list):
            # 图片是独立模态输入，Base64 传输体积不是文本 Token；为每张图片单独预留预算。
            return sum(4096 if isinstance(part,dict) and part.get('type')=='image_url' else size(part) for part in content)
        return size(content)
    amount = sum(content_size(getattr(m, 'content', m)) + 32 for m in messages) + size(extra or '') + 256
    if amount > input_limit(profile):
        raise ContextOverflow('请求超过当前上下文预算，需要继续分段整理。')
    return amount


def is_context_error(exc):
    text = str(exc).lower()
    return any(x in text for x in ('context_length_exceeded', 'maximum context', 'context window',
        'prompt is too long', 'input is too long', 'too many input tokens', 'request too large'))


def pieces(text, limit):
    """不破坏 Unicode 字符边界，分段后可完整拼回原文。"""
    current, amount = [], 0
    for char in text:
        weight = len(char.encode('utf-8'))
        if current and amount + weight > limit:
            yield ''.join(current)
            current, amount = [], 0
        current.append(char)
        amount += weight
    if current:
        yield ''.join(current)
