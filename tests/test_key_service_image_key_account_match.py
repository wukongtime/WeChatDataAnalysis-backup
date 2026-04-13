import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


import wechat_decrypt_tool.key_service as key_service


class TestKeyServiceImageKeyAccountMatch(unittest.TestCase):
    def test_local_image_keys_do_not_match_by_substring(self) -> None:
        remote_result = {
            "wxid": "wxid_demo_extra",
            "xor_key": "0x8A",
            "aes_key": "BBBBBBBBBBBBBBBB",
        }

        with mock.patch.object(
            key_service,
            "try_get_local_image_keys",
            return_value=[
                {"wxid": "wxid_demo", "xor_key": "0x01", "aes_key": "AAAAAAAAAAAAAAAA"},
            ],
        ), mock.patch.object(
            key_service,
            "_resolve_account_dir",
            return_value=Path("D:/tmp/output/databases/wxid_demo_extra"),
        ), mock.patch.object(
            key_service,
            "_resolve_account_wxid_dir",
            return_value=Path("D:/tmp/xwechat_files/wxid_demo_extra"),
        ), mock.patch.object(
            key_service,
            "upsert_account_keys_in_store",
        ) as upsert_mock, mock.patch.object(
            key_service,
            "fetch_and_save_remote_keys",
            new=mock.AsyncMock(return_value=remote_result),
        ) as remote_mock:
            result = asyncio.run(key_service.get_image_key_integrated_workflow("wxid_demo_extra"))

        self.assertEqual(result, remote_result)
        remote_mock.assert_awaited_once_with("wxid_demo_extra", wxid_dir=None, db_storage_path=None)
        upsert_mock.assert_not_called()

    def test_local_image_keys_require_exact_account_match(self) -> None:
        with mock.patch.object(
            key_service,
            "try_get_local_image_keys",
            return_value=[
                {"wxid": "wxid_demo", "xor_key": "0x01", "aes_key": "AAAAAAAAAAAAAAAA"},
                {"wxid": "wxid_demo_extra", "xor_key": "0x8A", "aes_key": "BBBBBBBBBBBBBBBB"},
            ],
        ), mock.patch.object(
            key_service,
            "_resolve_account_dir",
            return_value=Path("D:/tmp/output/databases/wxid_demo_extra"),
        ), mock.patch.object(
            key_service,
            "_resolve_account_wxid_dir",
            return_value=Path("D:/tmp/xwechat_files/wxid_demo_extra"),
        ), mock.patch.object(
            key_service,
            "upsert_account_keys_in_store",
        ) as upsert_mock, mock.patch.object(
            key_service,
            "fetch_and_save_remote_keys",
            new=mock.AsyncMock(side_effect=AssertionError("remote should not be called")),
        ):
            result = asyncio.run(key_service.get_image_key_integrated_workflow("wxid_demo_extra"))

        self.assertEqual(result["wxid"], "wxid_demo_extra")
        self.assertEqual(result["xor_key"], "0x8A")
        self.assertEqual(result["aes_key"], "BBBBBBBBBBBBBBBB")
        upsert_mock.assert_called_once_with(
            account="wxid_demo_extra",
            image_xor_key="0x8A",
            image_aes_key="BBBBBBBBBBBBBBBB",
        )

    def test_fetch_remote_keys_can_use_db_storage_path_without_decrypted_output(self) -> None:
        with TemporaryDirectory() as temp_dir:
            wxid_dir = Path(temp_dir) / "xwechat_files" / "wxid_v4mbduwqtzpt22"
            db_storage_dir = wxid_dir / "db_storage"
            db_storage_dir.mkdir(parents=True, exist_ok=True)

            class _FakeResponse:
                status_code = 200

                @staticmethod
                def json():
                    return {
                        "xorKey": "138",
                        "aesKey": "c3f3366e23628242",
                        "nickName": "demo",
                    }

            class _FakeAsyncClient:
                def __init__(self, *args, **kwargs):
                    pass

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

                async def post(self, url, data=None, files=None):
                    self.last_url = url
                    self.last_data = data
                    self.last_files = files
                    return _FakeResponse()

            with mock.patch.object(
                key_service,
                "_resolve_account_dir",
                side_effect=AssertionError("should not require decrypted account dir"),
            ), mock.patch.object(
                key_service,
                "get_wechat_internal_global_config",
                side_effect=[b"global-config", b"crc-bytes"],
            ), mock.patch.object(
                key_service.httpx,
                "AsyncClient",
                _FakeAsyncClient,
            ), mock.patch.object(
                key_service,
                "upsert_account_keys_in_store",
            ) as upsert_mock:
                result = asyncio.run(
                    key_service.fetch_and_save_remote_keys(
                        "wxid_v4mbduwqtzpt22",
                        db_storage_path=str(db_storage_dir),
                    )
                )

        self.assertEqual(result["wxid"], "wxid_v4mbduwqtzpt22")
        self.assertEqual(result["xor_key"], "0x8A")
        self.assertEqual(result["aes_key"], "c3f3366e23628242")
        upsert_mock.assert_called_once_with(
            account="wxid_v4mbduwqtzpt22",
            image_xor_key="0x8A",
            image_aes_key="c3f3366e23628242",
        )


if __name__ == "__main__":
    unittest.main()
