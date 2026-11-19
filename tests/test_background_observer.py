import json
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from wechat_control.auth_gate import StudioPluginUnauthorizedError
from wechat_control.background_observer import BackgroundObserver
from wechat_control.mcp_server import create_http_server


class SyntheticDesktop:
    def __init__(self):
        self.capabilities = {"status", "read_sessions", "ocr"}
        self.visible = False
        self.screen_permission = True
        self.frame_entered = threading.Event()
        self.frame_can_finish = threading.Event()
        self.frame_can_finish.set()
        self.calls = []

    def _require(self, capability):
        if capability not in self.capabilities:
            raise StudioPluginUnauthorizedError("test denied", capability)

    def _run_native(self, args, timeout):
        self.calls.append(args)
        if args == ["status"]:
            windows = [{"windowID": 17, "bounds": {"width": 800, "height": 600}}] if self.visible else []
            return {"ok": True, "wechatRunning": self.visible, "windows": windows,
                    "screenCaptureTrusted": self.screen_permission}
        if args != ["capture-ocr", "--no-activate", "--window-id", "17"]:
            raise AssertionError(f"Unexpected desktop action: {args!r}")
        self.frame_entered.set()
        if not self.frame_can_finish.wait(3):
            raise AssertionError("test did not release the simulated image")
        return {
            "ok": True, "windowID": 17, "imageWidth": 1600, "imageHeight": 1200,
            "elements": [
                {"text": "模拟会话甲", "center": {"x": 280, "y": 180}},
                {"text": "2", "center": {"x": 140, "y": 188}},
                {"text": "模拟会话乙", "center": {"x": 260, "y": 310}},
                {"text": "应该忽略的消息正文", "center": {"x": 1200, "y": 180}},
            ],
        }


class BackgroundObserverTest(unittest.TestCase):
    def setUp(self):
        self.desktop = SyntheticDesktop()
        self.observer = BackgroundObserver(self.desktop, interval=0.02)
        self.addCleanup(self.observer.close)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            state = self.observer.status()
            if predicate(state):
                return state
            time.sleep(0.01)
        self.fail(f"observer did not transition; last status was {self.observer.status()}")

    def test_passive_checks_track_window_state_and_only_keep_aggregate_data(self):
        self.assertEqual(self.observer.status()["state"], "standby")
        self.assertEqual(self.desktop.calls, [])
        self.observer.start()
        waiting = self.wait_for(lambda s: s["state"] == "waiting_no_visible_window")
        self.assertTrue(waiting["running"])
        self.assertIsNone(waiting["visibleSessions"])
        self.assertTrue(all(args == ["status"] for args in self.desktop.calls))
        self.desktop.screen_permission = False
        self.desktop.visible = True
        denied = self.wait_for(lambda s: s["errorCode"] == "screen_capture_denied")
        self.assertEqual(denied["state"], "failed")
        self.assertFalse(self.desktop.frame_entered.is_set())
        self.desktop.screen_permission = True
        sample = self.wait_for(lambda s: s["state"] == "running")
        self.assertEqual((sample["visibleSessions"], sample["unreadSessions"]), (2, 1))
        self.assertGreater(sample["checks"], waiting["checks"])
        self.assertIsNotNone(sample["lastCheckedAt"])
        self.assertNotIn("模拟会话", json.dumps(sample, ensure_ascii=False))
        self.desktop.visible = False
        waiting = self.wait_for(lambda s: s["state"] == "waiting_no_visible_window")
        self.assertIsNone(waiting["unreadSessions"])

    def test_revoke_during_capture_discards_sample_and_stops(self):
        self.desktop.visible = True
        self.desktop.frame_can_finish.clear()
        self.addCleanup(self.desktop.frame_can_finish.set)
        self.observer.start()
        self.assertTrue(self.desktop.frame_entered.wait(1))
        self.desktop.capabilities.remove("ocr")
        self.desktop.frame_can_finish.set()
        failed = self.wait_for(lambda s: not s["running"])
        self.assertEqual(failed["errorCode"], "authorization_required")
        self.assertIsNone(failed["visibleSessions"])
        self.assertEqual(len(self.desktop.calls), 2)

    def test_http_only_local_user_can_start_and_stop_an_inflight_check(self):
        self.desktop.visible = True
        self.desktop.frame_can_finish.clear()
        with patch("wechat_control.mcp_server.BackgroundObserver", return_value=self.observer):
            server = create_http_server(self.desktop, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(self.desktop.frame_can_finish.set)
        origin = f"http://127.0.0.1:{server.server_port}"

        def request(method, data=None, site=origin):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            try:
                headers = {"Content-Type": "application/json", "Origin": site}
                conn.request(method, "/api/background-observation",
                             body=json.dumps(data) if data is not None else None, headers=headers)
                response = conn.getresponse()
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        self.assertEqual(request("GET")[1]["state"], "standby")
        self.assertEqual(request("POST", {"action": "start"}, "https://outside.example")[0], 403)
        self.desktop.capabilities.remove("ocr")
        self.assertEqual(request("POST", {"action": "start"})[1]["error_code"], "authorization_required")
        self.assertEqual(self.desktop.calls, [])
        self.desktop.capabilities.add("ocr")
        self.assertEqual(request("POST", {"action": "start"})[0], 200)
        self.assertTrue(self.desktop.frame_entered.wait(1))
        self.assertTrue(request("POST", {"action": "start"})[1]["running"])
        stopped = request("POST", {"action": "stop"})[1]
        self.assertEqual((stopped["state"], stopped["running"]), ("stopping", False))
        self.desktop.frame_can_finish.set()
        standby = self.wait_for(lambda s: s["state"] == "standby")
        self.assertEqual(standby["checks"], 0)
        self.assertEqual(len(self.desktop.calls), 2)

        self.assertEqual(request("POST", {"action": "start"})[0], 200)
        self.wait_for(lambda s: s["state"] == "running")
        server.shutdown()
        self.assertFalse(self.observer.status()["running"])
        self.assertFalse(self.observer.start()["running"])
