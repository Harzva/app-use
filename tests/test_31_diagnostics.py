"""diagnostics 聚合诊断端点专项测试。"""
import json
import sys
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_control.engine import WeChatControlEngine
from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.mcp_server import create_http_server


def _make_engine(data: Path) -> WeChatControlEngine:
    engine = WeChatControlEngine(
        audit_log_path=data / "audit.jsonl", auth_file_path=data / "auth.json",
        bindings_file_path=data / "bindings.json", models_config_path=data / "models.json",
        model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
        knowledge_db_path=data / "kb.sqlite", personas_file_path=data / "personas.json",
        snapshots_dir=data / "snap", reports_dir=data / "reports",
        allowed_groups=["VIP客户群"],
    )
    engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-test")
    return engine


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.engine = _make_engine(self.data)

    def test_shallow_diagnostics_aggregates_subsystems(self):
        rep = self.engine.diagnostics()
        self.assertTrue(rep["ok"])
        self.assertIn("generatedAt", rep)
        # 版本应与 plugin.manifest.json 动态一致（而非硬编码，避免每次 bump 挂测试）
        manifest_ver = json.loads(
            (Path(__file__).resolve().parent.parent / "plugin.manifest.json").read_text()
        ).get("version")
        self.assertEqual(rep["version"], manifest_ver)
        for key in ("auth", "hosting", "antiban", "knowledgeEntries", "monitorState", "recentEvents"):
            self.assertIn(key, rep, f"缺少 {key}")
            self.assertNotIn("error", rep[key] if isinstance(rep[key], dict) else {}, f"{key} 报错")
        self.assertIsInstance(rep["recentEvents"], list)
        # shallow 模式不包含慢探测项
        self.assertNotIn("permissions", rep)
        self.assertNotIn("llmGateway", rep)

    def test_deep_diagnostics_includes_probes(self):
        rep = self.engine.diagnostics(deep=True)
        self.assertIn("permissions", rep)
        self.assertIn("llmGateway", rep)

    def test_hosting_state_reflects_in_diagnostics(self):
        self.engine.bind_contact("诊断好友", role="friend", auto_reply_enabled=True)
        res = self.engine.start_hosting(["诊断好友"])
        self.assertTrue(res["ok"])
        rep = self.engine.diagnostics()
        self.assertTrue(rep["hosting"].get("enabled"))
        self.assertIn("诊断好友", rep["hosting"].get("targets") or [])

    def test_web_console_perm_wizard(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("renderPermWizard", "startWizardPolling", "stopWizardPolling", "去授权", "自动检测并进入下一步", "permWizard"):
            self.assertIn(marker, html, f"分步授权向导缺少标记: {marker}")

    def test_web_console_perm_modal_dismissable(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("PERM_MODAL_DISMISSED", "为什么之前授权过", "旧 WeChat Bot 条目"):
            self.assertIn(marker, html, f"权限弹窗缺少 dismissable/文案标记: {marker}")

    def test_web_console_has_diagnostics_ui(self):
        from wechat_control.web_console import render_web_console_html
        html = render_web_console_html()
        for marker in ("diagBtn", "diagOverlay", "loadDiagnostics", "健康诊断"):
            self.assertIn(marker, html, f"首页缺少诊断 UI 标记: {marker}")

    def test_diagnostics_http_endpoint(self):
        import threading
        import urllib.request
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/diagnostics", timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 200)
                self.assertTrue(body.get("ok"))
                self.assertIn("hosting", body)
            with urllib.request.urlopen(f"{base}/api/diagnostics?deep=1", timeout=10) as resp:
                body2 = json.loads(resp.read().decode("utf-8"))
                self.assertIn("permissions", body2)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_permissions_status_works_without_studio_auth(self):
        import threading
        import urllib.request

        fresh_dir = self.data / "fresh_unauth"
        fresh = WeChatControlEngine(
            audit_log_path=fresh_dir / "audit.jsonl",
            auth_file_path=fresh_dir / "auth.json",
            bindings_file_path=fresh_dir / "bindings.json",
            models_config_path=fresh_dir / "models.json",
            model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=fresh_dir / "kb.sqlite",
            personas_file_path=fresh_dir / "personas.json",
            snapshots_dir=fresh_dir / "snap",
            reports_dir=fresh_dir / "reports",
        )
        fresh._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "accessibilityTrusted": True,
            "postEventTrusted": True,
            "screenCaptureTrusted": True,
            "wechatRunning": True,
            "wechatPid": 999,
        }
        perms = fresh.permissions_status()
        self.assertTrue(perms["ok"])
        self.assertTrue(perms["allGranted"])
        self.assertEqual(len(perms["items"]), 3)

        rep = fresh.diagnostics(deep=True)
        self.assertTrue(rep["ok"])
        self.assertFalse((rep["auth"].get("authorization") or {}).get("authorized"))
        self.assertTrue(rep["permissions"]["allGranted"])

        srv = create_http_server(fresh, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/permissions", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["allGranted"])
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diagnostics?deep=1", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["permissions"]["allGranted"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_diagnostics_knowledge_count_not_capped_at_one(self):
        rep = self.engine.diagnostics()
        self.assertIsInstance(rep["knowledgeEntries"], int)
        self.assertGreater(rep["knowledgeEntries"], 1)

    def test_legacy_runtime_migration_and_bundle_binary_resolution(self):
        from wechat_control.engine import _migrate_legacy_runtime_data, _resolve_default_binary_path

        bundle = self.data / "WeChat Bot.app" / "Contents" / "Resources"
        macos = bundle.parent / "MacOS"
        bundle.mkdir(parents=True)
        macos.mkdir(parents=True)
        bin_path = macos / "wechat-vision-ax"
        bin_path.write_text("#!/bin/sh\n", encoding="utf-8")
        self.assertEqual(_resolve_default_binary_path(bundle), bin_path)

        legacy = self.data / "legacy_repo"
        (legacy / "config").mkdir(parents=True)
        (legacy / "logs" / "contacts").mkdir(parents=True)
        (bundle / "repo_root.txt").write_text(str(legacy) + "\n", encoding="utf-8")

        (legacy / "config" / "studio_auth.json").write_text('{"authorized": true}\n', encoding="utf-8")
        (legacy / "config" / "bound_contacts.json").write_text('{"bindings": {"测试好友": {}}}\n', encoding="utf-8")
        (legacy / "config" / "personas.json").write_text('{"custom": true}\n', encoding="utf-8")
        (legacy / "logs" / "hosting_state.json").write_text('{"enabled": true}\n', encoding="utf-8")
        (legacy / "logs" / "contacts" / "测试_history.json").write_text('{"messages": []}\n', encoding="utf-8")

        target_root = self.data / "app_support"
        (target_root / "config").mkdir(parents=True)
        (target_root / "config" / "personas.json").write_text('{"custom": false}\n', encoding="utf-8")

        res = _migrate_legacy_runtime_data(bundle, target_root)
        self.assertTrue(res["migrated"])
        self.assertTrue((target_root / ".runtime_migrated_v1").is_file())
        self.assertTrue((target_root / "config" / "studio_auth.json").is_file())
        self.assertTrue((target_root / "config" / "bound_contacts.json").is_file())
        self.assertTrue((target_root / "logs" / "hosting_state.json").is_file())
        self.assertTrue((target_root / "logs" / "contacts" / "测试_history.json").is_file())
        self.assertEqual(json.loads((target_root / "config" / "personas.json").read_text()), {"custom": True})

        res2 = _migrate_legacy_runtime_data(bundle, target_root)
        self.assertFalse(res2["migrated"])
        self.assertEqual(res2["reason"], "already_migrated")

    def test_avatar_rel_coordinates_and_capture_auto_crop(self):
        import threading
        import urllib.request
        from wechat_control.live_inspector import WeChatLiveInspector

        elements = [
            {"text": "openbot", "bbox": {"x": 118, "y": 70, "width": 58, "height": 12}, "center": {"x": 147, "y": 76}},
            {"text": "测试预览", "bbox": {"x": 118, "y": 91, "width": 80, "height": 12}, "center": {"x": 158, "y": 97}},
            {"text": "安晓心", "bbox": {"x": 116, "y": 200, "width": 44, "height": 12}, "center": {"x": 138, "y": 206}},
            {"text": "请回复一句话", "bbox": {"x": 116, "y": 220, "width": 90, "height": 12}, "center": {"x": 161, "y": 226}},
        ]
        rows = WeChatLiveInspector._cluster_session_rows(elements, 310.0, 1320.0)
        self.assertEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0]["avatarRel"]["x"], 64.0)
        self.assertEqual(rows[0]["avatarRel"]["x"], 70.0)
        self.assertEqual(rows[1]["avatarRel"]["x"], 68.0)

        snap = self.engine.inspector.snapshots_dir / "monitor_poll_cur.png"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 300)

        recorded_crops = []

        def fake_native(args, timeout=15.0):
            if args and args[0] == "ocr" and "--crop" in args:
                crop_str = args[args.index("--crop") + 1]
                recorded_crops.append(crop_str)
                out_p = Path(args[args.index("--out") + 1])
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 300)
                return {"ok": True, "savedPath": str(out_p), "elements": []}
            if args and args[0] == "ocr":
                return {"ok": True, "imageWidth": 853, "imageHeight": 1320, "elements": elements}
            return {
                "ok": True,
                "accessibilityTrusted": True,
                "postEventTrusted": True,
                "screenCaptureTrusted": True,
                "wechatRunning": True,
                "wechatPid": 123,
                "windows": [],
            }

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        cap = self.engine.avatar_capture("安晓心")
        self.assertTrue(cap["ok"])
        self.assertEqual(cap["url"], "/avatars/安晓心.png")
        self.assertEqual(recorded_crops[-1], "68,196,40,40")

        ov = self.engine.get_web_overview()
        self.assertEqual((ov.get("avatars") or {}).get("安晓心"), "/avatars/安晓心.png")

        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/avatar",
                data=json.dumps({"target": "openbot"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                body = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(body["ok"])
                self.assertEqual(body["crop"]["x"], 70)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/avatars/openbot.png", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertGreater(len(resp.read()), 200)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_wide_window_split_x_and_card_bubble_clustering(self):
        import struct
        import zlib
        from wechat_control.live_inspector import WeChatLiveInspector

        # 生成与真实 853x1320 微信窗口同比例（含白/灰卡片底色）的 PNG，确保像素方向采样走真实分支
        card_png = self.data / "wide_card.png"
        w, h = 853, 800
        rows_raw = bytearray()
        for y in range(h):
            rows_raw.append(0)
            if 560 <= y <= 730:
                rows_raw.extend((245, 245, 245) * 550 + (237, 238, 240) * 260 + (245, 245, 245) * (w - 810))
            else:
                rows_raw.extend((245, 245, 245) * w)

        def _chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        card_png.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows_raw))) + _chunk(b"IEND", b""))

        elements = [
            {"text": "Q 搜索", "bbox": {"x": 80, "y": 22, "width": 42, "height": 12}, "center": {"x": 101, "y": 28}},
            {"text": "openbot (2)", "bbox": {"x": 505, "y": 22, "width": 80, "height": 14}, "center": {"x": 545, "y": 29}},
            # 左栏右缘时间戳（x=464 < 489）：不得漏进右栏成为 timeMarker
            {"text": "星期一", "bbox": {"x": 447, "y": 460, "width": 30, "height": 10}, "center": {"x": 462, "y": 465}},
            {"text": "10/24", "bbox": {"x": 449, "y": 720, "width": 32, "height": 10}, "center": {"x": 465, "y": 725}},
            # 右栏真实群聊卡片消息
            {"text": "05:02", "bbox": {"x": 651, "y": 536, "width": 36, "height": 10}, "center": {"x": 669, "y": 541}},
            {"text": "心安", "bbox": {"x": 557, "y": 572, "width": 26, "height": 16}, "center": {"x": 570, "y": 580}},
            {"text": "又一个神级开源神器！爆火7.1K star", "bbox": {"x": 567, "y": 604, "width": 228, "height": 18}, "center": {"x": 681, "y": 613}},
            {"text": "，让 AI 轻松搞定 36 种画风，口播⋯", "bbox": {"x": 565, "y": 626, "width": 222, "height": 18}, "center": {"x": 676, "y": 635}},
            {"text": "C 菜鸟学Python", "bbox": {"x": 571, "y": 704, "width": 96, "height": 14}, "center": {"x": 619, "y": 711}},
        ]
        inferred = WeChatLiveInspector._infer_split_x(elements, 853.0)
        self.assertEqual(inferred, 489.0)

        structured = self.engine.inspector.extract_structured_bubbles(
            {"elements": elements},
            snapshot_path=card_png,
            bounds={"width": 853.0, "height": 1320.0},
        )
        self.assertEqual(structured["headerTitle"], "openbot (2)")
        bubbles = structured["bubbles"]
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(bubbles[0]["direction"], "peer")
        self.assertEqual(bubbles[0]["timeMarker"], "05:02")
        self.assertIn("又一个神级开源神器", bubbles[0]["text"])
        self.assertIn("菜鸟学Python", bubbles[0]["text"])

    def test_contact_gap_defers_and_replies_after_cooldown(self):
        from wechat_control.safety import AntiBanGuard

        clock = {"t": 1000.0}
        self.engine.antiban = AntiBanGuard(
            state_path=self.data / "antiban_gap.json",
            per_contact_hourly=10,
            global_hourly=20,
            global_daily=50,
            min_reply_gap_seconds=90,
            now_fn=lambda: clock["t"],
        )
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)
        stage = {"msg": 1, "active": "其他会话"}
        sent_texts = []

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "status":
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "accessibilityTrusted": True,
                    "postEventTrusted": True,
                    "screenCaptureTrusted": True,
                    "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
                }
            if cmd == "hid-idle":
                return {"ok": True, "anyInputIdleSeconds": 90.0, "mouseIdleSeconds": 90.0, "keyboardIdleSeconds": 90.0}
            if cmd == "click":
                if "--x" in args and float(args[args.index("--x") + 1]) > 60:
                    stage["active"] = "心安"
                return {"ok": True}
            if cmd == "capture-ocr":
                if "--out" in args:
                    p = Path(args[args.index("--out") + 1])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"")
                if stage["active"] != "心安":
                    preview = "第一条测试问题" if stage["msg"] == 1 else "第二条追问消息"
                    return {
                        "ok": True,
                        "elements": [
                            {"text": "其他会话", "center": {"x": 300, "y": 28}, "bbox": {"x": 265, "y": 20, "width": 70, "height": 16}},
                            {"text": "心安", "center": {"x": 115, "y": 66}, "bbox": {"x": 96, "y": 58, "width": 36, "height": 16}},
                            {"text": "12:04" if stage["msg"] == 1 else "12:05", "center": {"x": 202, "y": 66}, "bbox": {"x": 182, "y": 58, "width": 38, "height": 16}},
                            {"text": preview, "center": {"x": 140, "y": 86}, "bbox": {"x": 96, "y": 78, "width": 90, "height": 16}},
                        ],
                    }
                msg_txt = "第一条测试问题" if stage["msg"] == 1 else "第二条追问消息"
                return {
                    "ok": True,
                    "elements": [
                        {"text": "心安", "center": {"x": 255, "y": 28}, "bbox": {"x": 236, "y": 20, "width": 38, "height": 16}},
                        {"text": "12:04" if stage["msg"] == 1 else "12:05", "center": {"x": 400, "y": 200}, "bbox": {"x": 380, "y": 192, "width": 40, "height": 14}},
                        {"text": msg_txt, "center": {"x": 340, "y": 250}, "bbox": {"x": 295, "y": 242, "width": 100, "height": 16}},
                    ],
                }
            if cmd == "paste-and-verify":
                txt = args[args.index("--text") + 1]
                sent_texts.append(txt)
                return {"ok": True, "sent": ("--send" in args), "readback": txt}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        self.engine.inspector._sleep = lambda _s: None  # type: ignore[method-assign]

        r1 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r1["repliesDispatched"], 1)

        # 40s 后（< 90s 冷却）新追问触发 contact_gap，不能吞掉消息签名
        clock["t"] = 1040.0
        stage["msg"] = 2
        stage["active"] = "其他会话"
        r2 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r2["repliesDispatched"], 0)
        self.assertEqual(r2["actions"][0]["status"], "rate_limited")
        st2 = self.engine.monitor.state_summary()["contacts"]["心安"]
        self.assertTrue(st2.get("pendingGapRetry"))

        # 冷却结束后（1000 -> 1140 > 90s）即使无未读角标也应自动重检并回复
        clock["t"] = 1140.0
        stage["active"] = "其他会话"
        r3 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r3["repliesDispatched"], 1)
        self.assertEqual(len(sent_texts), 2)
        st3 = self.engine.monitor.state_summary()["contacts"]["心安"]
        self.assertFalse(st3.get("pendingGapRetry", False))
        self.assertNotIn("lastRateLimitReason", st3)

    def test_unread_badge_red_pixel_fallback(self):
        import struct
        import zlib
        from wechat_control.live_inspector import WeChatLiveInspector

        badge_png = self.data / "unread_badge.png"
        w, h = 320, 160
        rows_raw = bytearray()
        # avatar_x = 118 - 48 = 70, avatar_y = 86 - 20 = 66; 红点区 x in [100..110], y in [67..77]
        for y in range(h):
            rows_raw.append(0)
            for x in range(w):
                if 100 <= x <= 110 and 67 <= y <= 77:
                    rows_raw.extend((250, 81, 81))
                else:
                    rows_raw.extend((245, 245, 245))

        def _chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        badge_png.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows_raw))) + _chunk(b"IEND", b""))

        elements = [
            {"text": "openbot", "bbox": {"x": 118, "y": 70, "width": 58, "height": 12}, "center": {"x": 147, "y": 76}},
            {"text": "最新一条测试消息", "bbox": {"x": 118, "y": 90, "width": 90, "height": 12}, "center": {"x": 163, "y": 96}},
        ]
        rows = WeChatLiveInspector._cluster_session_rows(elements, 310.0, 640.0, image_path=badge_png)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unreadBadge"], "dot")

    def test_web_console_left_chat_list_and_top_ribbon_layout(self):
        from wechat_control.web_console import render_web_console_html

        html = render_web_console_html()
        # 顶部彩带栏采用横向布局（不再占用左侧 216px 整列）
        self.assertIn("flex-direction: row !important;", html)
        self.assertIn(".hosting-panel[hidden] { display: none !important; }", html)

        monitor_idx = html.index('id="tab-monitor"')
        aside_idx = html.index('<aside class="home-conversations"', monitor_idx)
        main_idx = html.index('<main class="chat-main-pane"', monitor_idx)
        hosting_idx = html.index('id="hostingPanel"', monitor_idx)
        perm_idx = html.index('id="permPanel"', monitor_idx)

        # 聊天列表位于最左侧列，#permPanel 与 #hostingPanel 位于右侧主工作区内，不压在聊天列表上方
        self.assertLess(aside_idx, main_idx)
        self.assertLess(main_idx, perm_idx)
        self.assertLess(main_idx, hosting_idx)

    def test_professional_reply_no_jargon_nuke_on_agent_sandbox_and_external_links(self):
        from wechat_control.live_inspector import WeChatLiveInspector

        # 1) 通用停用词（为什么/需要/可以/那里）不得误命中本机产品 FAQ
        kb_sandbox = self.engine.knowledge.search_context("为什么Agent 需要沙箱？")
        self.assertEqual(kb_sandbox["matchedCount"], 0)

        # 2) 包含 Prompt / 熔断 的高质量 LLM 技术答复应平滑替换为自然中文，严禁整段吞没成“还在学习中”
        recorded = []

        class _FakeHub:
            def is_llm_enabled(self):
                return True

            def generate_chat_reply(self, messages, *, model_id=None, contact_name=None):
                recorded.append(messages)
                return {
                    "ok": True,
                    "replyText": "Agent 需要沙箱是为了隔离权限，防止 Prompt 注入触发越权命令执行或资源安全熔断。",
                    "modelId": "mock-pro",
                    "providerId": "mock",
                    "latencyMs": 10,
                }

        # legacy aiPersona="warm-companion" 在群聊里不得跌入 rpa-tech-expert；无明确技术指定时走 wecom-kf-pro
        self.engine.bind_contact("openbot", role="group", ai_persona="warm-companion", auto_reply_enabled=True)
        res = self.engine.personas.generate_smart_reply(
            "openbot",
            "为什么Agent 需要沙箱？",
            knowledge_store=self.engine.knowledge,
            binding=self.engine.bindings.get_binding("openbot"),
            model_hub=_FakeHub(),
            use_llm=True,
        )
        self.assertEqual(res["persona"]["id"], "wecom-kf-pro")
        self.assertIn("沙箱", res["replyText"])
        self.assertIn("提示词", res["replyText"])
        self.assertNotIn("还在学习中", res["replyText"])
        self.assertNotIn("Prompt", res["replyText"])

        # 3) 第三方开源链接不应把自家 github.com/Harzva/wechat-bot 定价/FAQ 硬塞进 sys_prompt
        recorded.clear()
        self.engine.personas.generate_smart_reply(
            "心安",
            "LoopForge 的开源地址是：https://github.com/Tencent/LoopForge，可以去那里看完整文档和源码。",
            knowledge_store=self.engine.knowledge,
            binding={"role": "friend", "aiPersona": "wecom-kf-pro"},
            model_hub=_FakeHub(),
            use_llm=True,
        )
        self.assertEqual(len(recorded), 1)
        self.assertNotIn("Harzva/wechat-bot", recorded[0][0]["content"])

        # 4) 112px 跨度的视频号卡片尾行 + 群聊发言人分离
        import struct
        import zlib
        card_png = self.data / "video_card_112.png"
        cw, ch = 853, 600
        raw_rows = b"".join(b"\x00" + (b"\xf5\xf5\xf5" * cw) for _ in range(ch))
        def _ck(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", cw, ch, 8, 2, 0, 0, 0)
        card_png.write_bytes(b"\x89PNG\r\n\x1a\n" + _ck(b"IHDR", ihdr) + _ck(b"IDAT", zlib.compress(raw_rows)) + _ck(b"IEND", b""))

        bubbles = WeChatLiveInspector.cluster_message_bubbles(
            [
                {"text": "心安", "x": 570, "y": 400, "bbox": {"x": 557, "y": 392, "width": 26, "height": 16}},
                {"text": "看到这个Fable 5.2纯代码视频效果很强", "x": 680, "y": 440, "bbox": {"x": 565, "y": 431, "width": 220, "height": 18}},
                {"text": "W 高老师的分享局", "x": 620, "y": 552, "bbox": {"x": 570, "y": 544, "width": 100, "height": 14}},
            ],
            split_x=489.0,
            win_w=853.0,
            image_path=card_png,
        )
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(bubbles[0].get("sender"), "心安")
        self.assertTrue(bubbles[0]["text"].startswith("心安: "))
        self.assertIn("高老师的分享局", bubbles[0]["text"])

    def test_wechat_ai_assistant_yuanbao_and_xiaowei_integration(self):
        import threading
        import urllib.error
        import urllib.request
        from wechat_control.media_link_analyzer import (
            extract_assistant_insights_from_bubbles,
            is_explicit_wechat_ai_mention,
            is_wechat_ai_assistant_name,
        )

        # 1) 原生微信 AI 助手名识别与 @元宝 显式提及判定
        self.assertTrue(is_wechat_ai_assistant_name("元宝"))
        self.assertTrue(is_wechat_ai_assistant_name("腾讯元宝"))
        self.assertTrue(is_wechat_ai_assistant_name("小微"))
        self.assertFalse(is_wechat_ai_assistant_name("安晓心"))
        self.assertFalse(is_wechat_ai_assistant_name("心安"))
        self.assertFalse(is_wechat_ai_assistant_name("https"))
        self.assertTrue(is_explicit_wechat_ai_mention("@元宝 请总结这篇文章"))
        self.assertTrue(is_explicit_wechat_ai_mention("@小微 看看这段视频"))
        self.assertFalse(is_explicit_wechat_ai_mention("你觉得 @元宝 怎么样？"))

        # 2) 从聊天记录气泡收割 元宝 / 小微 解析结论，并注入 LLM 深读上下文
        sample_bubbles = [
            {"direction": "peer", "sender": "元宝", "text": "元宝: 视频核心要点：Fable 5.2 用代码直接驱动分镜与三维运镜。"},
            {"direction": "peer", "sender": "小微", "text": "小微: 文章核心结论：智能体落地需要先做权限沙箱隔离。"},
        ]
        insights = extract_assistant_insights_from_bubbles(sample_bubbles)
        self.assertEqual(len(insights), 2)
        self.assertTrue(any(it.startswith("[元宝深读:元宝]") for it in insights))
        self.assertTrue(any(it.startswith("[小微深读:小微]") for it in insights))

        recorded_prompts = []

        class _FakeHub:
            def is_llm_enabled(self):
                return True

            def generate_chat_reply(self, messages, *, model_id=None, contact_name=None):
                recorded_prompts.append(messages)
                return {
                    "ok": True,
                    "replyText": "结合元宝解析，Fable 5.2 主打纯代码驱动分镜与运镜。",
                    "modelId": "mock-pro",
                    "providerId": "mock",
                    "latencyMs": 8,
                }

        self.engine.bind_contact("openbot", role="group", auto_reply_enabled=True)
        smart = self.engine.personas.generate_smart_reply(
            "openbot",
            "这个视频主要讲了什么？",
            knowledge_store=self.engine.knowledge,
            binding=self.engine.bindings.get_binding("openbot"),
            recent_messages=insights,
            model_hub=_FakeHub(),
            use_llm=True,
        )
        self.assertIn("Fable 5.2", smart["replyText"])
        self.assertIn("深读解析上下文", recorded_prompts[0][0]["content"])
        self.assertIn("[元宝深读:元宝]", recorded_prompts[0][0]["content"])

        # 3) realtime_monitor：人类 @元宝 礼让等待；元宝回复自动收割且防机器人互回死循环；随后追问自动注入历史媒体备注
        import struct
        import zlib
        cw, ch = 853, 600
        raw_rows = b"".join(b"\x00" + (b"\xf5\xf5\xf5" * cw) for _ in range(ch))
        def _ck2(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        ihdr2 = struct.pack(">IIBBBBB", cw, ch, 8, 2, 0, 0, 0)
        grey_png_bytes = b"\x89PNG\r\n\x1a\n" + _ck2(b"IHDR", ihdr2) + _ck2(b"IDAT", zlib.compress(raw_rows)) + _ck2(b"IEND", b"")

        stage = {"step": 1}

        def fake_native(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd == "status":
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "accessibilityTrusted": True,
                    "postEventTrusted": True,
                    "screenCaptureTrusted": True,
                    "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 853, "height": 600}}],
                }
            if cmd == "hid-idle":
                return {"ok": True, "anyInputIdleSeconds": 90.0, "mouseIdleSeconds": 90.0, "keyboardIdleSeconds": 90.0}
            if cmd == "capture-ocr":
                if "--out" in args:
                    p = Path(args[args.index("--out") + 1])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(grey_png_bytes)
                base_els = [
                    {"text": "Q 搜索", "center": {"x": 101, "y": 28}, "bbox": {"x": 80, "y": 22, "width": 42, "height": 12}},
                    {"text": "openbot", "center": {"x": 545, "y": 29}, "bbox": {"x": 505, "y": 22, "width": 80, "height": 14}},
                ]
                if stage["step"] == 1:
                    els = base_els + [
                        {"text": "12:01", "center": {"x": 669, "y": 175}, "bbox": {"x": 651, "y": 170, "width": 36, "height": 10}},
                        {"text": "心安", "center": {"x": 570, "y": 208}, "bbox": {"x": 557, "y": 200, "width": 26, "height": 16}},
                        {"text": "@元宝 请总结这条视频", "center": {"x": 650, "y": 240}, "bbox": {"x": 565, "y": 232, "width": 170, "height": 18}},
                    ]
                elif stage["step"] == 2:
                    els = base_els + [
                        {"text": "12:02", "center": {"x": 669, "y": 175}, "bbox": {"x": 651, "y": 170, "width": 36, "height": 10}},
                        {"text": "元宝", "center": {"x": 570, "y": 280}, "bbox": {"x": 557, "y": 272, "width": 26, "height": 16}},
                        {"text": "视频核心要点：纯代码生成三维动态分镜与自动化运镜。", "center": {"x": 680, "y": 312}, "bbox": {"x": 565, "y": 304, "width": 230, "height": 18}},
                    ]
                else:
                    els = base_els + [
                        {"text": "12:03", "center": {"x": 669, "y": 175}, "bbox": {"x": 651, "y": 170, "width": 36, "height": 10}},
                        {"text": "心安", "center": {"x": 570, "y": 360}, "bbox": {"x": 557, "y": 352, "width": 26, "height": 16}},
                        {"text": "这条视频核心讲了什么？", "center": {"x": 655, "y": 392}, "bbox": {"x": 565, "y": 384, "width": 180, "height": 18}},
                    ]
                return {"ok": True, "elements": els}
            if cmd == "paste-and-verify":
                txt = args[args.index("--text") + 1]
                return {"ok": True, "sent": ("--send" in args), "readback": txt}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]

        r_a = self.engine.monitor_once(target="openbot", auto_reply=True, confirm_send=True)
        self.assertEqual(r_a["repliesDispatched"], 0)
        self.assertEqual(r_a["actions"][0]["status"], "deferred_for_wechat_ai_assistant")

        stage["step"] = 2
        r_b = self.engine.monitor_once(target="openbot", auto_reply=True, confirm_send=True)
        self.assertEqual(r_b["repliesDispatched"], 0)
        self.assertEqual(r_b["actions"][0]["status"], "skipped_ai_assistant_bubble")
        persisted_notes = self.engine.recent_media_notes("openbot")
        self.assertTrue(any("纯代码生成三维动态分镜" in n for n in persisted_notes))

        stage["step"] = 3
        r_c = self.engine.monitor_once(target="openbot", auto_reply=True, confirm_send=True)
        self.assertEqual(r_c["repliesDispatched"], 1)
        self.assertIn("纯代码生成三维动态分镜", r_c["actions"][0]["replyText"])

        # 4) HTTP POST /api/wechat-ai-assist 双模式（@元宝 / 转发小微）
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            for mode in ("at_yuanbao", "relay_xiaowei"):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/wechat-ai-assist",
                    data=json.dumps({
                        "target": "openbot",
                        "contentHint": "心安: 看看这条视频号教程",
                        "mode": mode,
                        "bubbles": sample_bubbles,
                        "dryRun": True,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body["ok"])
                    self.assertEqual(body["mode"], mode)
                    self.assertTrue(body["persistedToHistory"])
                    self.assertTrue(body["note"].startswith("["))

            # 未授权人类联系人调用 /api/wechat-ai-assist 应立即被白名单/绑定守卫拦截返回 400
            bad_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/wechat-ai-assist",
                data=json.dumps({
                    "target": "陌生路人",
                    "contentHint": "看看这条链接",
                    "mode": "at_yuanbao",
                    "dryRun": False,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad_req, timeout=10)
            self.assertEqual(ctx.exception.code, 400)
            bad_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(bad_body["ok"])
            self.assertEqual(bad_body.get("error_code"), "target_not_allowed")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_botstudio_ui_settings_and_deep_read_reply_preview(self):
        from wechat_control.web_console import render_web_console_html

        # 1) Web Console BotStudio 布局、设置中心弹窗、@元宝/小微快捷入口
        html = render_web_console_html()
        for marker in (
            "topSettingsBtn",
            "sidebarSettingsBtn",
            "composerSettingsBtn",
            "settingsOverlay",
            "openSettingsModal",
            "quickYuanbaoBtn",
            "quickXiaoweiBtn",
            "runQuickWeChatAiAssist",
            "bs-view-switcher",
            "hosting-picker-popover",
        ):
            self.assertIn(marker, html, f"控制台缺少 BotStudio/设置/快捷助手标记: {marker}")

        # 2) openbot (2) 历史文件名归一化 + 手动「生成草稿」preview_smart_reply 自动注入 media_note
        self.engine.bind_contact("openbot", role="group", auto_reply_enabled=True)
        self.assertTrue(
            self.engine.append_media_note("openbot (2)", "[元宝深读:元宝] 视频要点：Fable 5.2 代码生成分镜。")
        )
        notes = self.engine.recent_media_notes("openbot")
        self.assertTrue(any("Fable 5.2" in n for n in notes))
        preview = self.engine.preview_smart_reply("openbot", "心安: 这条视频讲了什么？", use_llm=False)
        self.assertIn("Fable 5.2", preview["replyText"])

        self.engine.bind_contact("安晓心", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)
        no_note_preview = self.engine.preview_smart_reply("安晓心", "帮我总结一下刚才发的文章重点", use_llm=False)
        self.assertEqual(no_note_preview["matchedCount"], 0)
        self.assertNotIn("WaveBot 是一款", no_note_preview["replyText"])
        self.assertIn("@元宝 解析 / 转发小微", no_note_preview["replyText"])

        # 3) _agent_dispatch_notes 任务优先级：最新气泡中的 link_deep_read 不被前面多条旧 agent_instruction 饿死
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)
        called_urls = []

        def fake_analyze_link(url, *, contact="", context_text="", model_id="", **kwargs):
            called_urls.append(url)
            return {"ok": True, "title": "示例文章", "summary": "优先深读最新链接而非被旧指令饿死。"}

        self.engine.media_analyzer.analyze_link = fake_analyze_link  # type: ignore[method-assign]
        bubbles = [
            {"direction": "peer", "text": "帮我分析一下架构"},
            {"direction": "peer", "text": "帮我总结一下SOP"},
            {"direction": "peer", "text": "帮忙看看这个仓库"},
            {"direction": "peer", "text": "最新链接：https://example.com/article W 高老师的分享局"},
        ]
        notes_out, receipt = self.engine.monitor._agent_dispatch_notes(
            self.engine.bindings.get_binding("心安") or {},
            "心安",
            bubbles,
            "最新链接：https://example.com/article",
            {"snapshotPath": ""},
        )
        self.assertEqual(called_urls, ["https://example.com/article"])
        self.assertTrue(any("优先深读最新链接" in n for n in notes_out))
        self.assertIsNotNone(receipt)

        # 4) forward_bubble_via_menu 安全隔离（拒绝未授权人类联系人，允许小微/元宝）
        blocked = self.engine.forward_bubble_via_menu(600.0, 300.0, "陌生路人", dry_run=True)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error_code"], "recipient_not_allowed")
        allowed = self.engine.forward_bubble_via_menu(600.0, 300.0, "小微", dry_run=True)
        self.assertTrue(allowed["ok"])
        self.assertTrue(allowed["isWeChatAiAssistant"])

        # 5) diagnostics recentEvents 按最新倒序返回
        self.engine.monitor._append_event("older_evt", {"n": 1})
        self.engine.monitor._append_event("newer_evt", {"n": 2})
        diag = self.engine.diagnostics()
        self.assertEqual(diag["recentEvents"][0]["event"], "newer_evt")

    def test_thiflow_see_think_act_and_yingdao_workos_harness(self):
        import threading
        import urllib.request

        self.engine.bind_contact("安晓心", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)

        # 1) AI 员工岗位与极速/深思档位设置 + seeThinkAct 三步推理注入
        recorded = []

        class _MockDeepHub:
            def is_llm_enabled(self):
                return True

            def generate_chat_reply(self, messages, *, model_id=None, contact_name=None):
                recorded.append(messages)
                return {
                    "ok": True,
                    "replyText": "结合售前技术目标，支持离线私有部署与标准 SLA 保障。",
                    "modelId": "mock-deep",
                    "providerId": "mock",
                    "latencyMs": 12,
                }

        self.engine.models = _MockDeepHub()  # type: ignore[assignment]
        g_res = self.engine.configure_workos_post(
            speed_mode="deep",
            post_preset="tech_consultant",
            task_goal="专注技术方案与部署边界解答",
        )
        self.assertTrue(g_res["ok"])
        self.assertEqual(g_res["speedMode"], "deep")

        novel_q = "请问下周三杭州西湖畔科技沙龙几点签到？"
        p1 = self.engine.preview_smart_reply("安晓心", f"安晓心: {novel_q}", use_llm=True)
        self.assertTrue(p1["ok"])
        self.assertEqual(p1["matchedCount"], 0)
        self.assertIn("seeThinkAct", p1)
        sta = p1["seeThinkAct"]
        self.assertIn("see", sta)
        self.assertIn("think", sta)
        self.assertIn("act", sta)
        self.assertEqual(sta["think"]["speedMode"], "deep")
        self.assertEqual(sta["think"]["taskGoal"], "专注技术方案与部署边界解答")
        self.assertEqual(sta["see"]["speaker"], "安晓心")
        self.assertIn("专注技术方案与部署边界解答", recorded[0][0]["content"])
        self.assertIn("深思模式", recorded[0][0]["content"])

        # 未命中固定条款的来信已进入 WorkOS 反思队列
        h0 = self.engine.get_workos_harness_summary()
        self.assertTrue(any(novel_q in item["incomingText"] for item in h0["reflection"]["items"]))

        # 2) HTTP 接口闭环：/api/reply-preview、/api/workos/learn-correction、/api/workos/harness、/mobile
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            # 人工纠偏沉淀为 SOP
            learn_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/workos/learn-correction",
                data=json.dumps({
                    "target": "安晓心",
                    "incoming_text": f"安晓心: {novel_q}",
                    "corrected_reply": "下周三杭州西湖畔科技沙龙 14:00 开始签到，14:30 准时开场，凭报名码入场。",
                    "original_draft": p1["replyText"],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(learn_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                learned = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(learned["ok"])
                self.assertGreaterEqual(learned["evolutionCount"], 1)

            # 同一问题再次预览，直接命中新沉淀的 SOP
            prev_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/reply-preview",
                data=json.dumps({
                    "target": "安晓心",
                    "incoming_text": novel_q,
                    "use_llm": False,
                    "speed_mode": "deep",
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(prev_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                p2 = json.loads(resp.read().decode("utf-8"))
                self.assertGreaterEqual(p2["matchedCount"], 1)
                self.assertIn("14:00 开始签到", p2["replyText"])
                self.assertEqual(p2["seeThinkAct"]["think"]["speedMode"], "deep")

            # GET /api/workos/harness 验证四维结构（治理/评估/反思/进化）
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/workos/harness", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                harness = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(harness["ok"])
                for pillar in ("governance", "evaluation", "reflection", "evolution"):
                    self.assertIn(pillar, harness)
                self.assertGreaterEqual(harness["evaluation"]["selfLearnedCount"], 1)
                self.assertGreaterEqual(harness["evolution"]["totalCount"], 1)

            # GET /mobile 手机伴侣遥控页
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/mobile", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                mobile_html = resp.read().decode("utf-8")
                self.assertIn("WeChat Bot 遥控台", mobile_html)
                self.assertIn("/api/hosting", mobile_html)
                self.assertIn("/api/workos/harness", mobile_html)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
