from typing import Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class AgentControl(RuntimeError):
    """停止与补充指令造成的流程切换，不属于供应商错误。"""
    pass


class AgentSettings(BaseModel):
    # 仅用于接收旧客户端请求，忽略历史额度字段。
    pass


class ThreadInput(BaseModel):
    account: str = Field(min_length=1)
    username: str = Field(min_length=1)
    title: str = Field('新的对话', min_length=1, max_length=100)


class ThreadUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=100)
    scope: list[str] | None = Field(None, min_length=1, max_length=2000)


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=1048576)
    request_id: str = Field(min_length=1, max_length=100)
    effort: Literal['moderate', 'deep'] = 'moderate'
    profile_id: str = ''
    vision_profile_id: str = ''

    @field_validator('text')
    @classmethod
    def text_bytes(cls, value):
        if len(value.encode('utf-8')) > 1048576:
            raise ValueError('输入超过 1 MiB，请分次发送。')
        if not value.strip():
            raise ValueError('请输入问题。')
        return value


class AgentAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['find_conversations', 'search_messages', 'read_messages', 'read_context', 'analyze_media', 'search_material', 'read_material', 'read_results', 'answer', 'clarify']
    query: str = Field('', max_length=500)
    username: str = ''
    source: str = Field('', description='单条消息编号，必须原样复制 evidence 中某条消息的 source；data_source 是数据渠道，不能作为消息编号。')
    start: int | None = Field(None, ge=0)
    end: int | None = Field(None, ge=0)
    offset: int = Field(0, ge=0, le=1000000)
    conversation_offset: int = Field(0, ge=0, le=2000)
    days: Literal[30, 90, 0] = 30
    question: str = Field('', max_length=1000)
    progress: str = ''

    @field_validator('question', mode='before')
    @classmethod
    def clarification_only(cls, value, info):
        # 某些兼容服务把答案正文放入无关字段；非澄清动作不使用该字段。
        return value if info.data.get('action') == 'clarify' else ''

    @field_validator('progress', mode='before')
    @classmethod
    def optional_progress(cls, value):
        # 旁白不是执行参数，异常旁白不能阻断合法读取。
        return value.strip() if isinstance(value, str) and len(value) <= 240 else ''

    @model_validator(mode='after')
    def required_arguments(self):
        if self.action == 'search_messages' and not self.query.strip():
            raise ValueError('search_messages requires query')
        if self.action in ('read_context', 'analyze_media', 'read_material') and not self.source:
            raise ValueError('source required')
        if self.action == 'clarify' and not self.question.strip():
            raise ValueError('clarify requires question')
        return self


TOOL_DESCRIPTION = '''只读工具：find_conversations 按 query 查会话；search_messages 关键词和语义混合检索；read_messages 读消息页；read_context 读 source 前后文；analyze_media 读图片附件。
search_material 检索任务原文和发现；read_material 按 source、字符 offset 读原文；read_results 按 offset 读分析结果或程序统计。
source 原样复制消息编号，不能填 data_source/realtime/decrypted/snapshot_index。username 留空按 conversation_offset 选授权会话；消息页 offset 每页增加 50。start/end 是本机时区 Unix 秒，日期未知 days 依次 30、90、0。
answer 结束查找；clarify 用 question 澄清，均须单独调用。progress 仅写实际发现或调整，普通分页留空。'''
