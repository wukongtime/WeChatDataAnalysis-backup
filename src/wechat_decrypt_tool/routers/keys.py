from typing import Optional

from fastapi import APIRouter

from ..key_store import get_account_keys_from_store
from ..key_service import get_db_key_workflow
from ..media_helpers import _load_media_keys, _resolve_account_dir
from ..path_fix import PathFixRoute

router = APIRouter(route_class=PathFixRoute)


@router.get("/api/keys", summary="获取账号已保存的密钥")
async def get_saved_keys(account: Optional[str] = None):
    """获取账号的数据库密钥与图片密钥（用于前端自动回填）"""
    account_name: Optional[str] = None
    account_dir = None

    try:
        account_dir = _resolve_account_dir(account)
        account_name = account_dir.name
    except Exception:
        # 账号可能尚未解密；仍允许从全局 store 读取（如果传入了 account）
        account_name = str(account or "").strip() or None

    keys: dict = {}
    if account_name:
        keys = get_account_keys_from_store(account_name)

    # 兼容：如果 store 里没有图片密钥，尝试从账号目录的 _media_keys.json 读取
    if account_dir and isinstance(keys, dict):
        try:
            media = _load_media_keys(account_dir)
            if keys.get("image_xor_key") in (None, "") and media.get("xor") is not None:
                keys["image_xor_key"] = f"0x{int(media['xor']):02X}"
            if keys.get("image_aes_key") in (None, "") and str(media.get("aes") or "").strip():
                keys["image_aes_key"] = str(media.get("aes") or "").strip()
        except Exception:
            pass

    # 仅返回需要的字段
    result = {
        "db_key": str(keys.get("db_key") or "").strip(),
        "image_xor_key": str(keys.get("image_xor_key") or "").strip(),
        "image_aes_key": str(keys.get("image_aes_key") or "").strip(),
        "updated_at": str(keys.get("updated_at") or "").strip(),
    }

    return {
        "status": "success",
        "account": account_name,
        "keys": result,
    }


@router.get("/api/get_db_key", summary="自动获取微信数据库密钥")
async def get_wechat_db_key():
    """
    自动流程：
    1. 结束微信进程
    2. 启动微信
    3. 根据版本注入 Hook
    4. 抓取密钥并返回
    """
    try:
        # 不需要async吧，我相信fastapi的线程池
        db_key = get_db_key_workflow()

        return {
            "status": 0,
            "errmsg": "ok",
            "data": {
                "db_key": db_key
            }
        }

    except TimeoutError:
        return {
            "status": -1,
            "errmsg": "获取超时，请确保微信没有开启自动登录 或者 加快手速",
            "data": {}
        }
    except Exception as e:
        return {
            "status": -1,
            "errmsg": f"获取失败: {str(e)}",
            "data": {}
        }
