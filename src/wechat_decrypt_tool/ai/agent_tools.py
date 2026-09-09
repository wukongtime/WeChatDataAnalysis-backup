"""只读工具适配器：所有数据均通过已有聊天服务获取。"""
from .diagnostics import observed, executor_call
import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from starlette.requests import Request


def local_request():
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': [],
                    'scheme': 'http', 'server': ('127.0.0.1', 10392), 'client': ('127.0.0.1', 0), 'query_string': b''})


def normalize(account, username, raw, name=''):
    anchor = str(raw.get('id') or raw.get('anchorId') or '')
    if not anchor:
        return None
    return {'source': hashlib.sha256(f'{account}:{username}:{anchor}'.encode()).hexdigest()[:24],
            'anchor': anchor, 'username': username, 'name': name or raw.get('conversationName') or username,
            'time': int(raw.get('createTime') or raw.get('create_time') or 0),
            'sender': raw.get('senderDisplayName') or raw.get('senderName') or raw.get('senderUsername') or '',
            'kind': raw.get('renderType', 'text'),
            'text': '\n'.join(str(raw.get(k) or '') for k in ('content', 'title', 'quoteTitle', 'quoteContent', 'voiceTranscript') if raw.get(k)),
            'match_methods': [m for m in raw.get('matchMethods', []) if m in ('keyword', 'semantic')],
            'media': raw}


class ChatTools:
    @asynccontextmanager
    async def open_pages(self, account, username, start, end, offset, checkpoint):
        """整次运行复用同一消息流；SQLite 游标在专用线程推进和关闭。"""
        from .messages import iter_message_pages
        closing = threading.Event()
        def check():
            if closing.is_set(): raise RuntimeError('读取已停止')
            checkpoint()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='agent-reader')
        stream = iter_message_pages(account,username,start,end,page_offset=offset,page_size=50,
            max_batch_chars=12000,checkpoint=check)
        loop = asyncio.get_running_loop()
        try:
            yield lambda: executor_call(executor,next,stream,None)
        finally:
            closing.set()
            try:
                await asyncio.shield(executor_call(executor,stream.close))
            finally:
                executor.shutdown(wait=False)

    @observed('agent.read.conversations')
    async def conversations(self, account):
        from ..chat_export_service import get_chat_export_targets_preview
        result = await asyncio.to_thread(get_chat_export_targets_preview, account=account, include_hidden=True, include_official=False)
        return [{'username': x['username'], 'name': x.get('name') or x.get('displayName') or x['username'],
                 'isGroup': x.get('isGroup', x['username'].endswith('@chatroom'))} for x in result['targets']]

    @observed('agent.read.search')
    async def search(self, account, username, query, start, end, offset):
        from ..routers.chat import search_chat_messages
        result = await search_chat_messages(local_request(), q=query, account=account, username=username,
                                           start_time=start, end_time=end, offset=offset, limit=50, source='auto',
                                           allow_native_enrichment=False, retrieval_mode='hybrid')
        messages = [normalize(account, username, x) for x in result.get('hits', [])]
        device_note = result.get('device',{}).get('reason','')
        return {'messages': [x for x in messages if x], 'has_more': result.get('hasMore', False),
                'retrieval_mode':result.get('retrievalMode','keyword'),'device':result.get('device'),
                'match_counts': {method: sum(method in x.get('match_methods', []) for x in messages if x)
                                 for method in ('keyword', 'semantic')},
                'warning': '；'.join(filter(None,[result.get('coverage', {}).get('message') or '搜索索引来自本地快照；尚未解析的图片内容不在文字搜索范围内。',device_note])),
                'data_source': 'snapshot_index', 'start': start, 'end': end}

    @observed('agent.read.read')
    async def read(self, account, username, start, end, offset):
        # 直接复用范围读取器，固定截止时间。分页按稳定来源排序，避免同秒消息遗漏。
        from .messages import read_messages
        result = await asyncio.to_thread(read_messages, account, username, start, end, None, page_offset=offset)
        # 数据渠道与单条消息编号分开命名，避免模型把 realtime 当作消息引用。
        result['data_source'] = result.pop('source', 'auto')
        values = result['messages']
        for item in values:
            item['name'] = result['name']
        return {**result, 'messages': values, 'start': start, 'end': end}

    @observed('agent.read.context')
    async def context(self, account, evidence):
        from ..routers.chat import get_chat_messages_around
        result = await get_chat_messages_around(local_request(), username=evidence['username'], anchor_id=evidence['anchor'],
                                               account=account, before=10, after=10, source='auto')
        values = [normalize(account, evidence['username'], x, evidence.get('name', '')) for x in result.get('messages', [])]
        return {'messages': [x for x in values if x], 'warning': result.get('warning', ''), 'data_source': result.get('source', 'auto')}
