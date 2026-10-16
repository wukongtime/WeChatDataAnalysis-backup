"""分类选择保留数据源标识，同时兼容旧版预览数据。"""
import asyncio
from unittest.mock import patch

from wechat_decrypt_tool.ai.agent_tools import ChatTools


def test_conversations_preserve_category_and_legacy_fallback():
    targets = [
        {'username': 'room@chatroom', 'name': '讨论', 'isGroup': True},
        {'username': 'person', 'name': '名字中有群', 'isGroup': False},
        {'username': 'legacy@chatroom', 'displayName': '旧数据'},
        {'username': 'explicit', 'isGroup': True},
    ]
    with patch('wechat_decrypt_tool.chat_export_service.get_chat_export_targets_preview', return_value={'targets': targets}) as preview:
        result = asyncio.run(ChatTools().conversations('test-account'))
    assert [item['isGroup'] for item in result] == [True, False, True, True]
    assert [item['name'] for item in result] == ['讨论', '名字中有群', '旧数据', 'explicit']
    preview.assert_called_once_with(account='test-account', include_hidden=True, include_official=False)
