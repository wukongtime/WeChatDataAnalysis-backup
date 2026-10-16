"""正式 Agent 工具运行和取消必须协调后台索引，使用独立测试存储。"""
import asyncio

import pytest

from test_ai_agent import service
from test_ai_global_assistant import idle_run
from wechat_decrypt_tool.ai.agent_schemas import AgentAction
from wechat_decrypt_tool.local_search import service as local


