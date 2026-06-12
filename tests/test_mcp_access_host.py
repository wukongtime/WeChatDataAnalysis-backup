import importlib
import logging
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _close_logging_handlers() -> None:
    for logger_name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(logger_name)
        for handler in lg.handlers[:]:
            try:
                handler.close()
            except Exception:
                pass
            try:
                lg.removeHandler(handler)
            except Exception:
                pass


class TestMcpAccessHost(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_data_dir = os.environ.get("WECHAT_TOOL_DATA_DIR")
        self._prev_host = os.environ.get("WECHAT_TOOL_HOST")
        self._prev_port = os.environ.get("WECHAT_TOOL_PORT")
        self._td = TemporaryDirectory()
        os.environ["WECHAT_TOOL_DATA_DIR"] = self._td.name
        os.environ.pop("WECHAT_TOOL_HOST", None)
        os.environ.pop("WECHAT_TOOL_PORT", None)

        import wechat_decrypt_tool.app_paths as app_paths
        import wechat_decrypt_tool.runtime_settings as runtime_settings
        import wechat_decrypt_tool.routers.admin as admin_router

        importlib.reload(app_paths)
        importlib.reload(runtime_settings)
        importlib.reload(admin_router)

        self.runtime_settings = runtime_settings
        self.admin_router = admin_router

    def tearDown(self) -> None:
        _close_logging_handlers()

        if self._prev_data_dir is None:
            os.environ.pop("WECHAT_TOOL_DATA_DIR", None)
        else:
            os.environ["WECHAT_TOOL_DATA_DIR"] = self._prev_data_dir

        if self._prev_host is None:
            os.environ.pop("WECHAT_TOOL_HOST", None)
        else:
            os.environ["WECHAT_TOOL_HOST"] = self._prev_host

        if self._prev_port is None:
            os.environ.pop("WECHAT_TOOL_PORT", None)
        else:
            os.environ["WECHAT_TOOL_PORT"] = self._prev_port

        self._td.cleanup()

    def _client(self) -> TestClient:
        app = FastAPI()
        app.include_router(self.admin_router.router)
        return TestClient(app, client=("127.0.0.1", 52010))

    def test_mcp_access_reports_lan_endpoint_when_lan_enabled(self) -> None:
        self.runtime_settings.write_backend_host_setting(self.runtime_settings.LAN_BACKEND_HOST)
        self.runtime_settings.write_backend_port_setting(12092)
        client = self._client()

        with patch.object(self.admin_router, "get_lan_access_host", return_value="192.168.1.23"):
            resp = client.get("/api/admin/mcp-access")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["host"], "0.0.0.0")
        self.assertEqual(payload["access_host"], "192.168.1.23")
        self.assertEqual(payload["accessHost"], "192.168.1.23")
        self.assertEqual(payload["mcp_endpoint"], "http://192.168.1.23:12092/mcp")
        self.assertEqual(payload["mcpEndpoint"], "http://192.168.1.23:12092/mcp")
        self.assertEqual(payload["skill_bundle_url"], "http://192.168.1.23:12092/mcp/skill/bundle")
        self.assertEqual(payload["skill_markdown_url"], "http://192.168.1.23:12092/mcp/skill")

    def test_mcp_access_keeps_loopback_endpoint_when_lan_disabled(self) -> None:
        self.runtime_settings.write_backend_host_setting(self.runtime_settings.LOOPBACK_BACKEND_HOST)
        self.runtime_settings.write_backend_port_setting(12092)
        client = self._client()

        with patch.object(self.admin_router, "get_lan_access_host", return_value="192.168.1.23"):
            resp = client.get("/api/admin/mcp-access")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["host"], "127.0.0.1")
        self.assertEqual(payload["access_host"], "127.0.0.1")
        self.assertEqual(payload["mcp_endpoint"], "http://127.0.0.1:12092/mcp")


class TestNetworkAccessHost(unittest.TestCase):
    def test_get_lan_access_host_prefers_physical_private_ipv4(self) -> None:
        import wechat_decrypt_tool.network_access as network_access

        with patch.object(network_access, "_add_psutil_candidates") as mocked_psutil, patch.object(
            network_access, "_add_route_candidates"
        ) as mocked_route, patch.object(network_access, "_add_hostname_candidates") as mocked_hostname:

            def add_psutil(candidates, seen):
                network_access._add_candidate(candidates, seen, "172.18.0.2", interface_name="Docker", source_order=0)
                network_access._add_candidate(candidates, seen, "192.168.1.23", interface_name="Wi-Fi", source_order=0)

            mocked_psutil.side_effect = add_psutil
            mocked_route.side_effect = lambda candidates, seen: network_access._add_candidate(
                candidates, seen, "10.0.0.9", source_order=1
            )
            mocked_hostname.side_effect = lambda candidates, seen: None

            self.assertEqual(network_access.get_lan_access_host(), "192.168.1.23")

    def test_get_lan_access_host_falls_back_when_no_candidate(self) -> None:
        import wechat_decrypt_tool.network_access as network_access

        with patch.object(network_access, "_add_psutil_candidates", return_value=None), patch.object(
            network_access, "_add_route_candidates", return_value=None
        ), patch.object(network_access, "_add_hostname_candidates", return_value=None):
            self.assertEqual(network_access.get_lan_access_host(default="127.0.0.1"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
