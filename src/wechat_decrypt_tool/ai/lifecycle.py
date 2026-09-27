"""AI 服务统一启停诊断，独立于其他后台服务的生命周期。"""
import logging
import threading
from importlib.metadata import PackageNotFoundError, version

from .diagnostics import observed, event


def _maintain_store(store, name):
    """在后台回收过期事件并压缩数据库，避免大型遗留库拖慢启动。"""
    try:
        deduplicated, removed, freed = store.maintain()
        event('storage.maintenance.finished', component=name, events_deduplicated=deduplicated,
              events_removed=removed, bytes_freed=freed)
    except Exception as error:
        event('storage.maintenance.failed', level=logging.WARNING, component=name, error=error)


@observed('lifecycle.start')
async def start_services():
    for package in ('deepagents', 'langchain-openai', 'langchain-anthropic', 'langgraph', 'onnxruntime', 'sqlite-vec', 'tokenizers'):
        try:
            event('runtime.component', component=package, runtime=version(package))
        except PackageNotFoundError as error:
            event('runtime.component.missing', level=logging.WARNING, component=package, error=error)
    from .service import get_ai_service
    from .agent_service import get_agent_service
    from ..local_search.service import get_local_search
    get_ai_service().store.recover_interrupted_usage()
    get_ai_service().start()
    await get_agent_service().start()
    await get_local_search().start()
    for name, store in (('summary', get_ai_service().store), ('search', get_local_search().store)):
        threading.Thread(target=_maintain_store, args=(store, name), name=f'ai-store-maintenance-{name}', daemon=True).start()


@observed('lifecycle.stop')
async def stop_services():
    from .service import get_ai_service
    from .agent_service import get_agent_service
    from ..local_search.service import get_local_search
    for name, factory in (('search',get_local_search),('summary',get_ai_service),('agent',get_agent_service)):
        try:
            await factory().stop()
        except Exception as error:
            event('lifecycle.service.stop_failed', level=logging.ERROR, component=name, error=error)
