import io
import json
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wechat_control.engine import WeChatControlEngine
from wechat_control.mcp_server import create_http_server


class ImageSendManualTriggerTests(unittest.TestCase):
    routes = ("/api/search-send-image", "/api/annotate-send-image")

    def setUp(self):
        engine = self.engine = WeChatControlEngine.__new__(WeChatControlEngine)
        engine._require = Mock()
        engine.allowlist = SimpleNamespace(enabled=False)
        engine.audit = Mock()
        engine.inspector = Mock()
        engine.is_human_guard_bypassed = Mock(return_value=False)
        engine.human_guard = Mock()
        engine.human_guard.check_can_operate.return_value = {
            "canOperate": False, "status": "human_input_active",
        }
        engine._run_native = Mock(return_value={"ok": True})
        engine.media_analyzer = Mock()
        prepared = {"ok": True, "imagePath": "/synthetic/image.png"}
        engine.media_analyzer.search_web_image.return_value = prepared
        engine.media_analyzer.annotate_image_with_highlights.return_value = prepared
        engine.send_image = Mock(wraps=engine.send_image)
        # Capture the real HTTP handler without binding a socket.
        with patch("http.server.ThreadingHTTPServer.__init__", return_value=None) as init:
            create_http_server(engine, "127.0.0.1", 19001)
        self.handler_type = init.call_args.args[1]

    def post(self, route, fields, *, host="localhost:19001",
             origin="http://localhost:19001", content_type="application/json"):
        body = json.dumps({
            "target": "synthetic", "query": "synthetic", "target_window_id": 17, **fields,
        }).encode()
        handler = self.handler_type.__new__(self.handler_type)
        handler.path = route
        handler.server = SimpleNamespace(server_port=19001)
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = Message()
        for name, value in {
            "Host": host, "Origin": origin, "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }.items():
            handler.headers[name] = value
        handler.rfile = io.BytesIO(body)
        handler._send_json = Mock()
        handler.do_POST()
        return handler._send_json.call_args.args

    def test_manual_flag_and_camel_precedence(self):
        self.engine.send_image.return_value = {"ok": True}
        cases = (
            ({"manualTrigger": True, "manual_trigger": False}, True),
            ({"manual_trigger": True}, True),
            ({"manualTrigger": False, "manual_trigger": True}, False),
            ({"manual_trigger": False}, False),
            ({}, False),
            ({"manualTrigger": "false", "manual_trigger": True}, False),
            ({"manual_trigger": "true"}, False),
            ({"manualTrigger": 1}, False),
        )
        for route in self.routes:
            for fields, expected in cases:
                with self.subTest(route=route, fields=fields):
                    headers = {} if expected else {
                        "origin": "https://other.invalid", "content_type": "text/plain",
                    }
                    self.assertEqual(self.post(route, fields, **headers)[0], 200)
                    self.assertIs(self.engine.send_image.call_args.kwargs["manual_trigger"], expected)

    def test_reject_untrusted_manual_requests_before_processing(self):
        cases = (
            ({"origin": "https://other.invalid"}, 403, "local_origin_required"),
            ({"host": "other.invalid:19001", "origin": "http://other.invalid:19001"},
             403, "local_origin_required"),
            ({"content_type": "text/plain"}, 415, "json_required"),
        )
        for route in self.routes:
            for headers, status, code in cases:
                with self.subTest(route=route, headers=headers):
                    self.assertEqual(self.post(route, {"manualTrigger": True}, **headers),
                                     (status, {"ok": False, "error_code": code}))
        self.assertEqual(self.engine.media_analyzer.mock_calls, [])
        self.engine._require.assert_not_called()
        self.engine.send_image.assert_not_called()

    @patch("wechat_control.engine.Path.is_file", return_value=True)
    def test_manual_dry_run_keeps_preview_behavior(self, _is_file):
        for route in self.routes:
            with self.subTest(route=route):
                status, result = self.post(route, {"manualTrigger": True, "dryRun": True})
                self.assertEqual((status, result["status"]), (200, "dry_run_ok"))
                self.assertTrue(self.engine.send_image.call_args.kwargs["manual_trigger"])
                self.assertIn("--dry-run", self.engine._run_native.call_args.args[0])
                self.assertNotIn("--send", self.engine._run_native.call_args.args[0])
                self.engine._require.assert_called_with("send_text_dry_run")
        self.engine.human_guard.check_can_operate.assert_not_called()
        self.engine.inspector.select_session.assert_not_called()

    @patch("wechat_control.engine.Path.is_file", return_value=True)
    def test_automatic_send_yields_to_active_human(self, _is_file):
        for route in self.routes:
            for fields in ({}, {"manualTrigger": False}, {"manualTrigger": "false"}):
                with self.subTest(route=route, fields=fields):
                    status, result = self.post(route, fields)
                    self.assertEqual((status, result["status"]), (400, "paused_human_active"))
                    self.assertTrue(result["blockedByHumanGuard"])
                    self.assertFalse(self.engine.send_image.call_args.kwargs["manual_trigger"])
                    self.engine._require.assert_called_with("send_text_live")
        self.assertEqual(self.engine.human_guard.check_can_operate.call_count, 6)
        self.assertEqual(self.engine.inspector.mock_calls, [])
        self.engine._run_native.assert_not_called()
