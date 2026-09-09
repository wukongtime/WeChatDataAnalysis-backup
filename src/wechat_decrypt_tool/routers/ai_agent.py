import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse

from .ai import local_only, account_name
from ..ai.agent_schemas import ThreadInput, ThreadUpdate, TurnInput, AgentSettings
from ..ai.agent_service import get_agent_service

router = APIRouter(prefix='/api/ai/agent', dependencies=[Depends(local_only)])


def thread(id, account):
    try:
        return get_agent_service().public_thread(id, account_name(account))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@router.get('/settings')
def settings():
    return get_agent_service().settings()


@router.put('/settings')
def update_settings(body: AgentSettings):
    # 旧版本写入请求保持兼容，但不再保存或启用人工额度。
    return get_agent_service().settings()


@router.get('/threads')
def threads(account: str, username: str = ''):
    store = get_agent_service().store
    owner = account_name(account)
    records = store.list('agent_thread', owner)
    result = []
    for record in records:
        if username and record['username'] != username:
            continue
        item = {k: v for k, v in record.items() if k not in ('messages', 'memory')}
        # 列表只返回最新任务的状态，不加载证据或把回答内容带入列表。
        latest = store.get('agent_run', record['latest_run']) if record.get('latest_run') else None
        item['latest_run_status'] = latest.get('status', '') if latest and latest.get('account') == owner and latest.get('thread_id') == record['id'] else ''
        result.append(item)
    return result


@router.post('/threads')
async def create_thread(body: ThreadInput):
    try:
        return await get_agent_service().create_thread(account_name(body.account), body.username, body.title)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/threads/{id}')
def get_thread(id: str, account: str):
    return thread(id, account)


@router.patch('/threads/{id}')
async def edit_thread(id: str, account: str, body: ThreadUpdate):
    record = thread(id, account)
    try:
        return await get_agent_service().edit_thread(id, record['account'], **body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.delete('/threads/{id}')
async def delete_thread(id: str, account: str):
    record = thread(id, account)
    await get_agent_service().delete_thread(id, record['account'])
    return {'status': 'success'}


@router.post('/threads/{id}/messages')
async def submit(id: str, account: str, body: TurnInput):
    record = thread(id, account)
    try:
        run = await get_agent_service().submit(id, record['account'], body.model_dump())
        return get_agent_service().public_run(run['id'], record['account'])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/runs/{id}')
def get_run(id: str, account: str):
    try:
        return get_agent_service().public_run(id, account_name(account))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post('/runs/{id}/{action}')
async def run_action(id: str, action: str, account: str):
    service = get_agent_service()
    try:
        account = account_name(account)
        service.run(id, account)
        if action == 'stop':
            await service.stop_run(id, account)
        elif action == 'continue':
            await service.resume(id, account)
        else:
            raise HTTPException(404, '操作不存在')
        return service.public_run(id, account)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/runs/{id}/materials')
def materials(id: str, account: str, kind: str = Query('sources', pattern='^(sources|findings|statistics)$'),
              offset: int = Query(0,ge=0), limit: int = Query(20,ge=1,le=100),
              query: str = Query('',max_length=500), version: int | None = None):
    try:
        return get_agent_service().material_page(id,account_name(account),kind,offset,limit,query,version)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None


@router.get('/runs/{id}/materials/{source}')
def material(id: str, source: str, account: str, offset: int = Query(0,ge=0), version: int | None = None):
    service=get_agent_service()
    try:
        run=service.authorize_material(id,account_name(account),version)
        value=run['evidence'].get(source)
        if not value: raise ValueError('来源不存在或已不在读取范围。')
        text=value['text'][offset:offset+6000]
        return service.public_source(value) | {'text':text,'offset':offset,'next_offset':offset+len(text) if offset+len(text)<len(value['text']) else None}
    except ValueError as exc:
        raise HTTPException(404,str(exc)) from None


@router.get('/events')
async def events(request: Request, account: str, after: int | None = None):
    account = account_name(account)
    try:
        cursor = max(after or 0, int(request.headers.get('last-event-id', str(get_agent_service().store.latest_event_id() if after is None else after))))
    except ValueError:
        cursor = max(0, after or 0)
    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            for event in get_agent_service().store.events(after=cursor, account=account):
                cursor = event['id']
                if event['kind'] == 'agent':
                    yield f"id: {event['id']}\ndata: {json.dumps(event['body'], ensure_ascii=False)}\n\n"
            yield ': heartbeat\n\n'
            await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
