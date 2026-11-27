"""授权自愈（repair_permissions）专项测试。

安全约束：这里的每个用例都必须用桩替代 /usr/bin/tccutil 与原生 request-permissions，
绝不改动开发机真实的系统授权，也不弹出系统授权提示。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PROJECT_ROOT = Path(__file__).resolve().parent.parent

from wechat_control.engine import WeChatControlEngine
from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.mcp_server import create_http_server


def _make_engine(data: Path) -> WeChatControlEngine:
    return WeChatControlEngine(
        audit_log_path=data / "audit.jsonl", auth_file_path=data / "auth.json",
        bindings_file_path=data / "bindings.json", models_config_path=data / "models.json",
        model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
        knowledge_db_path=data / "kb.sqlite", personas_file_path=data / "personas.json",
        snapshots_dir=data / "snap", reports_dir=data / "reports",
        allowed_groups=["VIP客户群"],
    )


class PermissionRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.engine = _make_engine(self.engine_dir())
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="perm-repair-test")

        # 桩 tccutil：把参数记进日志，按 STUB_EXIT 环境变量决定退出码
        self.tcc_log = self.data / "tcc_calls.log"
        stub = self.data / "tccutil-stub.sh"
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{self.tcc_log}"\n'
            'if [ -f "' + str(self.data / "stub_fail") + '" ]; then echo "tccutil: stub refused" >&2; exit 1; fi\n'
            "exit 0\n"
        )
        stub.chmod(0o755)
        self.engine._tccutil_bin = str(stub)

        # 桩原生探测：真实调用会让 macOS 弹系统授权提示。记下 (open_settings, only)；
        # 返回 accessibilityTrusted=True 表示辅助功能未弹窗，两步之间不需要留间隔。
        self.native_calls = []

        def _request_stub(*, open_settings=True, only=None):
            if only and only not in self.engine.PERMISSION_ITEMS:
                raise ValueError(f"Unsupported permission item: {only}")
            self.native_calls.append((open_settings, only))
            return {"ok": True, "promptTriggered": True, "accessibilityTrusted": True}

        self.engine.request_permissions = _request_stub

    def engine_dir(self) -> Path:
        return self.data / "engine"

    def _tcc_calls(self):
        if not self.tcc_log.exists():
            return []
        return [line.split() for line in self.tcc_log.read_text().splitlines() if line.strip()]

    def test_reset_only_touches_this_app_two_services_then_prompts_one_by_one(self):
        res = self.engine.repair_permissions()
        self.assertTrue(res["ok"])
        bid = res["bundleId"]
        self.assertEqual(self._tcc_calls(), [
            ["reset", "Accessibility", bid],
            ["reset", "ScreenCapture", bid],
        ])
        # 清除之后让系统重新登记当前版本，且不额外打开系统设置（向导自己会引导）。
        # 辅助功能与屏幕录制分两次申请：同一瞬间一起申请，后一个系统弹窗可能被丢弃。
        self.assertEqual(self.native_calls, [(False, "accessibility"), (False, "screen_capture")])
        self.assertTrue(res["request"]["promptTriggered"])
        self.assertEqual(len(res["request"]["steps"]), 2)

    def test_gap_is_left_between_ax_and_screen_capture_prompts(self):
        slept = []
        self.engine.request_permissions = lambda *, open_settings=True, only=None: (
            self.native_calls.append((open_settings, only))
            or {"ok": True, "promptTriggered": True, "accessibilityTrusted": only != "accessibility"}
        )
        import time as time_module
        real_sleep = time_module.sleep
        time_module.sleep = lambda seconds: slept.append(seconds)
        try:
            self.engine.repair_permissions()
        finally:
            time_module.sleep = real_sleep
        self.assertEqual(slept, [self.engine._permission_prompt_gap_seconds])
        self.assertEqual(self.native_calls, [(False, "accessibility"), (False, "screen_capture")])

    def test_repair_only_screen_capture_leaves_accessibility_alone(self):
        res = self.engine.repair_permissions(services=["screen_capture"])
        self.assertTrue(res["ok"])
        # 修屏幕录制时不得连已经正常的辅助功能一起清掉
        self.assertEqual(self._tcc_calls(), [["reset", "ScreenCapture", res["bundleId"]]])
        self.assertEqual(self.native_calls, [(False, "screen_capture")])
        self.assertEqual(res["items"], ["screen_capture"])

    def test_repair_only_accessibility_skips_screen_capture(self):
        res = self.engine.repair_permissions(services=["accessibility"])
        self.assertEqual(self._tcc_calls(), [["reset", "Accessibility", res["bundleId"]]])
        self.assertEqual(self.native_calls, [(False, "accessibility")])

    def test_repair_post_event_alone_maps_to_accessibility_service(self):
        res = self.engine.repair_permissions(services=["post_event"])
        self.assertEqual(self._tcc_calls(), [["reset", "Accessibility", res["bundleId"]]])
        self.assertEqual(self.native_calls, [(False, "post_event")])

    def test_post_event_alone_sends_post_event_flag_to_native(self):
        calls = []
        fresh = _make_engine(self.data / "engine-post-event")
        fresh._run_native = lambda args, timeout=20.0: (
            calls.append(list(args)) or {"ok": True, "promptTriggered": True}
        )
        fresh.repair_permissions(services=["post_event"])
        self.assertEqual(calls, [["request-permissions", "--only", "post-event", "--no-settings"]])

    def test_repair_rejects_unknown_service_before_touching_system(self):
        with self.assertRaises(ValueError):
            self.engine.repair_permissions(services=["microphone"])
        self.assertEqual(self._tcc_calls(), [])
        self.assertEqual(self.native_calls, [])

    def test_request_permissions_sends_only_flag_without_resetting(self):
        calls = []
        fresh = _make_engine(self.data / "engine-request")
        fresh._run_native = lambda args, timeout=20.0: (
            calls.append(list(args)) or {"ok": True, "promptTriggered": True, "screenCapturePrompted": True}
        )
        res = fresh.request_permissions(open_settings=False, only="screen_capture")
        self.assertTrue(res["ok"])
        self.assertEqual(calls, [["request-permissions", "--only", "screen-capture", "--no-settings"]])
        self.assertFalse(self.tcc_log.exists(), "申请登记不得清除任何已有授权")
        fresh.request_permissions()
        self.assertEqual(calls[-1], ["request-permissions"])
        with self.assertRaises(ValueError):
            fresh.request_permissions(only="microphone")

    def test_reset_failure_is_surfaced_not_swallowed(self):
        (self.data / "stub_fail").write_text("1")
        res = self.engine.repair_permissions()
        self.assertFalse(res["ok"])
        self.assertEqual([r["returncode"] for r in res["reset"]], [1, 1])
        self.assertIn("stub refused", res["reset"][0]["output"])

    def test_reset_false_only_prompts(self):
        res = self.engine.repair_permissions(reset=False)
        self.assertTrue(res["ok"])
        self.assertEqual(self._tcc_calls(), [])
        self.assertEqual(self.native_calls, [(False, "accessibility"), (False, "screen_capture")])

    def test_bundle_id_env_override_and_default(self):
        import os
        self.assertEqual(self.engine.tcc_bundle_id(), "com.openbot.wechat-bot")
        os.environ["WECHAT_BUNDLE_ID"] = "com.example.other"
        try:
            self.assertEqual(self.engine.tcc_bundle_id(), "com.example.other")
        finally:
            del os.environ["WECHAT_BUNDLE_ID"]

    def _server(self):
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def _post(self, base, payload, path="/api/permissions/repair"):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_http_requires_explicit_confirm(self):
        base = self._server()
        status, body = self._post(base, {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "CONFIRM_REQUIRED")
        self.assertEqual(self._tcc_calls(), [], "未确认的请求不得改动系统授权")
        self.assertEqual(self.native_calls, [])

    def test_http_with_confirm_repairs(self):
        base = self._server()
        status, body = self._post(base, {"confirm": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual([c[1] for c in self._tcc_calls()], ["Accessibility", "ScreenCapture"])
        self.assertEqual(self.native_calls, [(False, "accessibility"), (False, "screen_capture")])

    def test_http_repair_with_services_only_touches_those(self):
        base = self._server()
        status, body = self._post(base, {"confirm": True, "services": ["screen_capture"]})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual([c[1] for c in self._tcc_calls()], ["ScreenCapture"])
        self.assertEqual(self.native_calls, [(False, "screen_capture")])

    def test_http_repair_rejects_unknown_services(self):
        base = self._server()
        status, body = self._post(base, {"confirm": True, "services": ["microphone"]})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "INVALID_SERVICES")
        self.assertEqual(self._tcc_calls(), [])
        self.assertEqual(self.native_calls, [])

    def test_http_request_registers_without_resetting(self):
        """向导「去授权」调用的接口：只向 macOS 申请登记，绝不清除已有授权。"""
        base = self._server()
        status, body = self._post(base, {"service": "screen_capture"}, path="/api/permissions/request")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["promptTriggered"])
        self.assertEqual(self.native_calls, [(False, "screen_capture")])
        self.assertEqual(self._tcc_calls(), [])

        status, body = self._post(base, {"service": "microphone"}, path="/api/permissions/request")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "INVALID_SERVICE")


class PermissionWizardLogicTests(unittest.TestCase):
    """向导前端逻辑：用 node 执行页面里的纯函数，保证步骤划分与文案正确。"""

    @classmethod
    def setUpClass(cls):
        from wechat_control.web_console import render_web_console_html
        cls.html = render_web_console_html()

    def _run_node(self, fn_name, expr):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用，跳过前端逻辑校验")
        match = re.search(rf"    function {fn_name}\(.*?\n    }}\n", self.html, re.S)
        self.assertIsNotNone(match, f"页面里找不到函数 {fn_name}")
        script = match.group(0) + f"\nprocess.stdout.write(JSON.stringify({expr}));"
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True,
                                         timeout=20, check=True).stdout)

    def test_post_event_is_not_a_separate_step_while_accessibility_pending(self):
        items = [
            {"id": "accessibility", "granted": False},
            {"id": "post_event", "granted": False},
            {"id": "screen_capture", "granted": False},
        ]
        self.assertEqual([p["id"] for p in self._run_node("permPendingSteps", f"permPendingSteps({json.dumps(items)})")],
                         ["accessibility", "screen_capture"])
        # 辅助功能已授权而事件模拟仍未通过时，才单独列出来提示
        items[0]["granted"] = True
        self.assertEqual([p["id"] for p in self._run_node("permPendingSteps", f"permPendingSteps({json.dumps(items)})")],
                         ["post_event", "screen_capture"])

    def test_wizard_has_repair_action_and_no_confirm_dialog(self):
        for marker in ("repairPermissions", "/api/permissions/repair", "重新登记", "随辅助功能开通",
                       "点击进入这一步", "退出并重新打开"):
            self.assertIn(marker, self.html, f"授权向导缺少: {marker}")
        self.assertNotIn("window.confirm(", self.html)
        # 旧的错误解释不能残留
        self.assertNotIn("旧授权随之失效", self.html)
        self.assertNotIn("这三项 macOS 权限", self.html)

    def test_wizard_requests_registration_before_opening_settings(self):
        """「去授权」必须先向 macOS 申请登记，再打开系统设置——否则列表里没有 WeChat Bot，只能手动「+」。"""
        for marker in ("requestPermissionThenOpen", "/api/permissions/request", "正在向系统申请登记",
                       "小卡片", "拖进列表", "permissionCard", "services: repairStepId"):
            self.assertIn(marker, self.html, f"授权向导缺少: {marker}")
        # 三个入口都要走「先申请再打开」：向导主按钮、弹窗底部按钮、首页分项按钮（不含函数定义本身）
        call_sites = self.html.replace("function requestPermissionThenOpen(", "")
        self.assertEqual(call_sites.count("requestPermissionThenOpen(event,"), 3)
        self.assertNotIn("把 WeChat Bot 加进去并打开开关", self.html)
        self.assertNotIn("先「−」删除再重新添加", self.html)

    def test_wizard_request_then_open_delegates_to_shell_card_or_opens_pane(self):
        """在 App 外壳里：通知外壳弹出可拖拽的小卡片，不再跳转；在浏览器里：照常打开面板。
        申请成功、申请失败（旧版后端没有该接口）两种情况都要走到，按钮文字都要复原。"""
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用，跳过前端逻辑校验")
        sources = []
        for fn_name in ("permissionCardBridge", "requestPermissionThenOpen"):
            match = re.search(rf"    function {fn_name}\(.*?\n    }}\n", self.html, re.S)
            self.assertIsNotNone(match, f"页面里找不到函数 {fn_name}")
            sources.append(match.group(0))
        for in_shell, api_body in (
            (True, "return { status: 200, data: { ok: true } };"),
            (True, "throw new Error('HTTP 404');"),
            (False, "return { status: 200, data: { ok: true } };"),
            (False, "throw new Error('HTTP 404');"),
        ):
            bridge_setup = (
                "const posted = []; const window = { webkit: { messageHandlers: "
                "{ permissionCard: { postMessage: (value) => { posted.push(value); } } } } };"
                if in_shell else
                "const posted = []; const window = {};"
            )
            script = (
                "const requested = [], clicked = [], prevented = [];\n"
                "const apiJson = async (url, options) => {\n"
                "  requested.push(JSON.parse(options.body).service);\n"
                "  " + api_body + "\n"
                "};\n"
                "const setTimeout = (fn) => { fn(); return 0; };\n"
                + bridge_setup + "\n"
                "const document = {\n"
                "  body: { appendChild() {} },\n"
                "  createElement: () => ({\n"
                "    _href: '', set href(v) { this._href = v; }, get href() { return this._href; },\n"
                "    click() { clicked.push(this._href); }, remove() {},\n"
                "  }),\n"
                "};\n"
                + "\n".join(sources)
                + "\n(async () => {\n"
                "  const el = { textContent: '去授权', dataset: {}, style: {} };\n"
                "  requestPermissionThenOpen({ preventDefault() { prevented.push(1); } }, 'screen_capture',\n"
                "    'x-apple.systempreferences:Privacy_ScreenRecording', el);\n"
                "  for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));\n"
                "  process.stdout.write(JSON.stringify({ requested, clicked, prevented, posted, label: el.textContent }));\n"
                "})();\n"
            )
            proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {
                "requested": ["screen_capture"],
                "clicked": [] if in_shell else ["x-apple.systempreferences:Privacy_ScreenRecording"],
                "prevented": [1],
                "posted": ["screen_capture"] if in_shell else [],
                "label": "去授权",
            })

    def test_native_shell_has_drag_card_and_bridge(self):
        """外壳源码里要有：可拖进系统设置列表的小卡片、网页通道、以及给页面判断环境用的标记。"""
        swift = (PROJECT_ROOT / "native" / "wechat_studio_app.swift").read_text(encoding="utf-8")
        for marker in (
            "final class PermissionDragCardController", "beginDraggingSession", "forType: .fileURL",
            "NSPasteboardItem", ".nonactivatingPanel", "window.WECHATBOT_SHELL = true;",
            'add(self, name: "permissionCard")', "didReceive message", "openPermissionGuide(for:",
            "com.apple.systempreferences", "--permission-card",
        ):
            self.assertIn(marker, swift, f"外壳缺少拖拽卡片相关的实现: {marker}")
        # 旧的手动添加文案不能残留
        self.assertNotIn("把 WeChat Bot 加进去并打开开关", swift)
        self.assertNotIn("先「−」删除再重新添加", swift)


if __name__ == "__main__":
    unittest.main()
