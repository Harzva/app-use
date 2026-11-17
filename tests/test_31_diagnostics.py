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


if __name__ == "__main__":
    unittest.main()
