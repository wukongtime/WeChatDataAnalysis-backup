import os
import sys
import json
import sqlite3
import unittest
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TestChatEditStore(unittest.TestCase):
    def setUp(self):
        self._prev_data_dir = os.environ.get("WECHAT_TOOL_DATA_DIR")
        self._td = TemporaryDirectory()
        os.environ["WECHAT_TOOL_DATA_DIR"] = self._td.name

        import wechat_decrypt_tool.app_paths as app_paths
        import wechat_decrypt_tool.chat_edit_store as chat_edit_store

        importlib.reload(app_paths)
        importlib.reload(chat_edit_store)

        self.app_paths = app_paths
        self.store = chat_edit_store

    def tearDown(self):
        if self._prev_data_dir is None:
            os.environ.pop("WECHAT_TOOL_DATA_DIR", None)
        else:
            os.environ["WECHAT_TOOL_DATA_DIR"] = self._prev_data_dir
        self._td.cleanup()

    def test_ensure_schema_creates_db(self):
        self.store.ensure_schema()
        db_path = self.app_paths.get_output_dir() / "message_edits.db"
        self.assertTrue(db_path.exists())

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='message_edits' LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row)
        finally:
            conn.close()

    def test_blob_hex_roundtrip(self):
        payload = {"a": b"\x00\xff", "nested": {"b": memoryview(b"\x01\x02")}}
        dumped = self.store.dumps_json_with_blobs(payload)
        self.assertIn("0x00ff", dumped.lower())
        self.assertIn("0x0102", dumped.lower())

        loaded = self.store.loads_json_with_blobs(dumped)
        self.assertEqual(loaded["a"], b"\x00\xff")
        self.assertEqual(loaded["nested"]["b"], b"\x01\x02")

    def test_message_id_format_parse(self):
        mid = self.store.format_message_id("message_0", "Msg_foo", 123)
        self.assertEqual(mid, "message_0:Msg_foo:123")

        db, table, local_id = self.store.parse_message_id(mid)
        self.assertEqual(db, "message_0")
        self.assertEqual(table, "Msg_foo")
        self.assertEqual(local_id, 123)

        with self.assertRaises(ValueError):
            self.store.parse_message_id("bad")

    def test_upsert_original_once_does_not_overwrite_snapshot(self):
        now1 = 1000
        now2 = 2000
        self.store.upsert_original_once(
            account="wxid_me",
            session_id="wxid_you",
            db="message_0",
            table_name="Msg_foo",
            local_id=1,
            original_msg={"local_id": 1, "message_content": "hello", "compress_content": b"\x01"},
            original_resource={"message_id": 9, "packed_info": b"\x02"},
            now_ms=now1,
        )

        self.store.upsert_original_once(
            account="wxid_me",
            session_id="wxid_you",
            db="message_0",
            table_name="Msg_foo",
            local_id=1,
            original_msg={"local_id": 1, "message_content": "SHOULD_NOT_OVERWRITE", "compress_content": b"\x03"},
            original_resource={"message_id": 9, "packed_info": b"\x04"},
            now_ms=now2,
        )

        mid = self.store.format_message_id("message_0", "Msg_foo", 1)
        item = self.store.get_message_edit("wxid_me", "wxid_you", mid)
        self.assertIsNotNone(item)
        self.assertEqual(int(item["first_edited_at"]), now1)
        self.assertEqual(int(item["last_edited_at"]), now2)
        self.assertEqual(int(item["edit_count"]), 2)

        original_msg = self.store.loads_json_with_blobs(item["original_msg_json"])
        self.assertEqual(original_msg["message_content"], "hello")
        self.assertEqual(original_msg["compress_content"], b"\x01")

        original_res = self.store.loads_json_with_blobs(item["original_resource_json"])
        self.assertEqual(int(original_res["message_id"]), 9)
        self.assertEqual(original_res["packed_info"], b"\x02")

    def test_update_message_edit_local_id_moves_primary_key(self):
        self.store.upsert_original_once(
            account="wxid_me",
            session_id="wxid_you",
            db="message_0",
            table_name="Msg_foo",
            local_id=10,
            original_msg={"local_id": 10, "message_content": "hello"},
            original_resource=None,
            now_ms=1234,
        )

        ok = self.store.update_message_edit_local_id(
            account="wxid_me",
            session_id="wxid_you",
            db="message_0",
            table_name="Msg_foo",
            old_local_id=10,
            new_local_id=11,
        )
        self.assertTrue(ok)

        old_mid = self.store.format_message_id("message_0", "Msg_foo", 10)
        new_mid = self.store.format_message_id("message_0", "Msg_foo", 11)
        self.assertIsNone(self.store.get_message_edit("wxid_me", "wxid_you", old_mid))
        self.assertIsNotNone(self.store.get_message_edit("wxid_me", "wxid_you", new_mid))

    def test_list_sessions_counts(self):
        self.store.upsert_original_once(
            account="wxid_me",
            session_id="u1",
            db="message_0",
            table_name="Msg_foo",
            local_id=1,
            original_msg={"local_id": 1, "message_content": "a"},
            original_resource=None,
            now_ms=100,
        )
        self.store.upsert_original_once(
            account="wxid_me",
            session_id="u1",
            db="message_0",
            table_name="Msg_foo",
            local_id=2,
            original_msg={"local_id": 2, "message_content": "b"},
            original_resource=None,
            now_ms=200,
        )
        self.store.upsert_original_once(
            account="wxid_me",
            session_id="u2",
            db="message_0",
            table_name="Msg_foo",
            local_id=3,
            original_msg={"local_id": 3, "message_content": "c"},
            original_resource=None,
            now_ms=300,
        )

        stats = self.store.list_sessions("wxid_me")
        by_sid = {s["session_id"]: s for s in stats}
        self.assertEqual(int(by_sid["u1"]["msg_count"]), 2)
        self.assertEqual(int(by_sid["u1"]["last_edited_at"]), 200)
        self.assertEqual(int(by_sid["u2"]["msg_count"]), 1)
        self.assertEqual(int(by_sid["u2"]["last_edited_at"]), 300)


if __name__ == "__main__":
    unittest.main()

