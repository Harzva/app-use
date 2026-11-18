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
            {"text": "语音助手", "bbox": {"x": 116, "y": 200, "width": 44, "height": 12}, "center": {"x": 138, "y": 206}},
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
        cap = self.engine.avatar_capture("语音助手")
        self.assertTrue(cap["ok"])
        self.assertEqual(cap["url"], "/avatars/语音助手.png")
        self.assertEqual(recorded_crops[-1], "68,196,40,40")

        ov = self.engine.get_web_overview()
        self.assertEqual((ov.get("avatars") or {}).get("语音助手"), "/avatars/语音助手.png")

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
            {"text": "联系人A", "bbox": {"x": 557, "y": 572, "width": 26, "height": 16}, "center": {"x": 570, "y": 580}},
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
        self.engine.bind_contact("联系人A", role="friend", auto_reply_enabled=True)
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
                    stage["active"] = "联系人A"
                return {"ok": True}
            if cmd == "capture-ocr":
                if "--out" in args:
                    p = Path(args[args.index("--out") + 1])
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"")
                if stage["active"] != "联系人A":
                    preview = "第一条测试问题" if stage["msg"] == 1 else "第二条追问消息"
                    return {
                        "ok": True,
                        "elements": [
                            {"text": "其他会话", "center": {"x": 300, "y": 28}, "bbox": {"x": 265, "y": 20, "width": 70, "height": 16}},
                            {"text": "联系人A", "center": {"x": 115, "y": 66}, "bbox": {"x": 96, "y": 58, "width": 36, "height": 16}},
                            {"text": "12:04" if stage["msg"] == 1 else "12:05", "center": {"x": 202, "y": 66}, "bbox": {"x": 182, "y": 58, "width": 38, "height": 16}},
                            {"text": preview, "center": {"x": 140, "y": 86}, "bbox": {"x": 96, "y": 78, "width": 90, "height": 16}},
                        ],
                    }
                msg_txt = "第一条测试问题" if stage["msg"] == 1 else "第二条追问消息"
                return {
                    "ok": True,
                    "elements": [
                        {"text": "联系人A", "center": {"x": 255, "y": 28}, "bbox": {"x": 236, "y": 20, "width": 38, "height": 16}},
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
        st2 = self.engine.monitor.state_summary()["contacts"]["联系人A"]
        self.assertTrue(st2.get("pendingGapRetry"))

        # 冷却结束后（1000 -> 1140 > 90s）即使无未读角标也应自动重检并回复
        clock["t"] = 1140.0
        stage["active"] = "其他会话"
        r3 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r3["repliesDispatched"], 1)
        self.assertEqual(len(sent_texts), 2)
        st3 = self.engine.monitor.state_summary()["contacts"]["联系人A"]
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
            "联系人A",
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
                {"text": "联系人A", "x": 570, "y": 400, "bbox": {"x": 557, "y": 392, "width": 26, "height": 16}},
                {"text": "看到这个Fable 5.2纯代码视频效果很强", "x": 680, "y": 440, "bbox": {"x": 565, "y": 431, "width": 220, "height": 18}},
                {"text": "W 高老师的分享局", "x": 620, "y": 552, "bbox": {"x": 570, "y": 544, "width": 100, "height": 14}},
            ],
            split_x=489.0,
            win_w=853.0,
            image_path=card_png,
        )
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(bubbles[0].get("sender"), "联系人A")
        self.assertTrue(bubbles[0]["text"].startswith("联系人A: "))
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
        self.assertFalse(is_wechat_ai_assistant_name("语音助手"))
        self.assertFalse(is_wechat_ai_assistant_name("联系人A"))
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
                        {"text": "联系人A", "center": {"x": 570, "y": 208}, "bbox": {"x": 557, "y": 200, "width": 26, "height": 16}},
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
                        {"text": "联系人A", "center": {"x": 570, "y": 360}, "bbox": {"x": 557, "y": 352, "width": 26, "height": 16}},
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
                        "contentHint": "联系人A: 看看这条视频号教程",
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
        preview = self.engine.preview_smart_reply("openbot", "联系人A: 这条视频讲了什么？", use_llm=False)
        self.assertIn("Fable 5.2", preview["replyText"])

        self.engine.bind_contact("语音助手", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)
        no_note_preview = self.engine.preview_smart_reply("语音助手", "帮我总结一下刚才发的文章重点", use_llm=False)
        self.assertEqual(no_note_preview["matchedCount"], 0)
        self.assertNotIn("WaveBot 是一款", no_note_preview["replyText"])
        self.assertIn("@元宝 解析 / 转发小微", no_note_preview["replyText"])

        # 3) _agent_dispatch_notes 任务优先级：最新气泡中的 link_deep_read 不被前面多条旧 agent_instruction 饿死
        self.engine.bind_contact("联系人A", role="friend", auto_reply_enabled=True)
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
            self.engine.bindings.get_binding("联系人A") or {},
            "联系人A",
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

        self.engine.bind_contact("语音助手", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)

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
        p1 = self.engine.preview_smart_reply("语音助手", f"语音助手: {novel_q}", use_llm=True)
        self.assertTrue(p1["ok"])
        self.assertEqual(p1["matchedCount"], 0)
        self.assertIn("seeThinkAct", p1)
        sta = p1["seeThinkAct"]
        self.assertIn("see", sta)
        self.assertIn("think", sta)
        self.assertIn("act", sta)
        self.assertEqual(sta["think"]["speedMode"], "deep")
        self.assertEqual(sta["think"]["taskGoal"], "专注技术方案与部署边界解答")
        self.assertEqual(sta["see"]["speaker"], "语音助手")
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
                    "target": "语音助手",
                    "incoming_text": f"语音助手: {novel_q}",
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
                    "target": "语音助手",
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

    def test_wecom_wechat_window_binding_and_pdf_doc_ingest(self):
        import base64
        import threading
        import urllib.error
        import urllib.request
        from wechat_control.doc_ingestor import ALLOWED_TEST_CONTACTS
        from wechat_control.web_console import render_web_console_html

        self.assertEqual(ALLOWED_TEST_CONTACTS, ("语音助手", "联系人A", "openbot"))

        # 使用默认未覆写 allowed_groups 的引擎，验证测试联系人白名单仅严守 ["语音助手", "联系人A", "openbot"]
        work_dir = self.data / "dualapp_engine"
        work_engine = WeChatControlEngine(
            audit_log_path=work_dir / "audit.jsonl",
            auth_file_path=work_dir / "auth.json",
            bindings_file_path=work_dir / "bindings.json",
            models_config_path=work_dir / "models.json",
            model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=work_dir / "kb.sqlite",
            personas_file_path=work_dir / "personas.json",
            snapshots_dir=work_dir / "snap",
            reports_dir=work_dir / "reports",
        )
        work_engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-dualapp-test")
        work_engine.bind_contact("语音助手", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)

        native_calls = []
        mock_windows = [
            {
                "windowID": 3258,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "微信",
                "isMainWindow": True,
                "bounds": {"x": 20, "y": 40, "width": 900, "height": 720},
            },
            {
                "windowID": 11503,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "语音助手",
                "isMainWindow": False,
                "bounds": {"x": 1380, "y": 484, "width": 598, "height": 640},
            },
            {
                "windowID": 4012,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "陌生人弹窗",
                "isMainWindow": False,
                "bounds": {"x": 920, "y": 100, "width": 520, "height": 580},
            },
            {
                "windowID": 3776,
                "appId": "wecom",
                "appLabel": "企业微信",
                "bundleID": "com.tencent.WeWorkMac",
                "pid": 25799,
                "title": "企业微信",
                "isMainWindow": True,
                "bounds": {"x": 100, "y": 80, "width": 1080, "height": 760},
            },
        ]

        def fake_native(args, timeout=15.0):
            native_calls.append(list(args))
            cmd = args[0] if args else ""
            if cmd == "list-app-windows":
                app_arg = args[args.index("--app") + 1] if "--app" in args else "all"
                wins = (
                    mock_windows
                    if app_arg in ("all", "auto")
                    else [w for w in mock_windows if w["appId"] == app_arg]
                )
                return {
                    "ok": True,
                    "requestedApp": app_arg,
                    "apps": [
                        {"appId": "wechat", "appLabel": "微信", "running": True, "windowCount": 3},
                        {"appId": "wecom", "appLabel": "企业微信", "running": True, "windowCount": 1},
                    ],
                    "windowCount": len(wins),
                    "windows": wins,
                }
            if cmd == "extract-pdf-text":
                pdf_path = args[args.index("--pdf") + 1] if "--pdf" in args else ""
                return {
                    "ok": True,
                    "pdfPath": pdf_path,
                    "pageCount": 2,
                    "processedPages": 2,
                    "truncated": False,
                    "text": (
                        "产品名称：星云净水器 Pro\n"
                        "核心卖点：星云净水器 Pro 采用 0.0001 微米 RO 反渗透膜，母婴直饮零陈水。\n"
                        "使用方法：第一步接通电源并冲洗 5 分钟；第二步轻触出水键即可直饮。\n"
                        "注意事项：滤芯每 12 个月更换一次，切勿接入 45 摄氏度以上热水。\n"
                        "Q1：滤芯多久换一次？\nA1：建议每 12 个月更换一次原装复合滤芯。"
                    ),
                    "pages": [
                        {"page": 1, "source": "pdfkit", "text": "星云净水器 Pro 核心卖点与使用步骤"},
                        {"page": 2, "source": "ocr", "text": "注意事项与常见问题"},
                    ],
                }
            return {
                "ok": True,
                "accessibilityTrusted": True,
                "postEventTrusted": True,
                "screenCaptureTrusted": True,
                "wechatRunning": True,
                "wechatPid": 60968,
            }

        work_engine._run_native = fake_native  # type: ignore[method-assign]

        # 1) 验证 web_console.py 必备 DOM ID
        console_html = render_web_console_html()
        for marker in (
            "appWindowPickerBtn",
            "windowPickerPopover",
            "docIngestBtn",
            "docIngestOverlay",
            "docIngestConfirmBtn",
        ):
            self.assertIn(marker, console_html, f"web_console.py 缺少关键标记: {marker}")

        srv = create_http_server(work_engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"

            # 2) GET /api/workos/windows 验证双应用扫描 + 独立小窗白名单隔离标注
            with urllib.request.urlopen(f"{base}/api/workos/windows?app=all", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                win_data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(win_data["ok"])
                self.assertEqual(len(win_data["windows"]), 4)
                by_id = {w["windowID"]: w for w in win_data["windows"]}
                self.assertTrue(by_id[11503]["isPopout"])
                self.assertTrue(by_id[11503]["isAllowlistedTarget"])
                self.assertTrue(by_id[4012]["isPopout"])
                self.assertFalse(by_id[4012]["isAllowlistedTarget"])
                self.assertFalse(by_id[3776]["isPopout"])

            # 3) POST /api/workos/bind-window 支持 wechat 与 wecom 持久化
            for bind_payload in (
                {"appId": "wechat", "windowID": 11503, "windowTitle": "语音助手"},
                {"appId": "wecom", "windowID": 3776, "windowTitle": "企业微信"},
            ):
                req = urllib.request.Request(
                    f"{base}/api/workos/bind-window",
                    data=json.dumps(bind_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    bres = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(bres["ok"])
                    self.assertEqual(bres["appId"], bind_payload["appId"])
                    self.assertEqual(bres["windowID"], bind_payload["windowID"])
                    self.assertTrue(bres["followUpIsolation"])

            # 重新构造同路径引擎实例，验证窗口绑定已持久化
            reloaded_engine = WeChatControlEngine(
                audit_log_path=work_dir / "audit.jsonl",
                auth_file_path=work_dir / "auth.json",
                bindings_file_path=work_dir / "bindings.json",
                models_config_path=work_dir / "models.json",
                model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
                knowledge_db_path=work_dir / "kb.sqlite",
                personas_file_path=work_dir / "personas.json",
                snapshots_dir=work_dir / "snap",
                reports_dir=work_dir / "reports",
            )
            reloaded_engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-dualapp-reload")
            persisted_bind = reloaded_engine.get_bound_app_window()
            self.assertEqual(persisted_bind["appId"], "wecom")
            self.assertEqual(persisted_bind["windowID"], 3776)
            self.assertEqual(persisted_bind["windowTitle"], "企业微信")

            # 4) POST /api/workos/doc-ingest/preview：支持 .md/.txt 与 Mock PDF 提取拆解
            md_content = (
                "# 光年咖啡机 X9\n"
                "## 核心卖点\n"
                "光年咖啡机 X9 支持 15Bar 黄金萃取与 30 秒极速预热。\n"
                "## 使用方法\n"
                "第一步水箱注水；第二步装入咖啡粉并按下萃取键。\n"
                "## 注意事项\n"
                "请勿干烧，每两周清理一次蒸汽喷嘴。\n"
                "## 常见FAQ\n"
                "Q：支持打奶泡吗？\nA：支持独立蒸汽棒绵密奶泡。\n"
            )
            md_req = urllib.request.Request(
                f"{base}/api/workos/doc-ingest/preview",
                data=json.dumps({
                    "file_bytes_b64": base64.b64encode(md_content.encode("utf-8")).decode("ascii"),
                    "filename": "光年咖啡机X9.md",
                    "instruction": "希望你能够替代我去和顾客聊天",
                    "use_llm": False,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(md_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                md_prev = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(md_prev["ok"])
                self.assertEqual(md_prev["sourceType"], "markdown")
                self.assertGreaterEqual(md_prev["itemCount"], 3)
                cats = {it["category"] for it in md_prev["items"]}
                self.assertTrue({"核心卖点", "使用方法与步骤", "注意事项"}.issubset(cats))
                self.assertEqual(md_prev["recommendedStrategy"], "bind_kb")
                opts = {o["id"]: o for o in md_prev["strategyOptions"]}
                self.assertTrue(opts["bind_kb"]["recommended"])
                self.assertFalse(opts["merge_prompt"]["recommended"])
                self.assertEqual(md_prev["confirmCard"]["strategy"], "bind_kb")
                self.assertEqual(md_prev["confirmCard"]["itemCount"], md_prev["itemCount"])

            # Mock PDF 上传（base64）触发原生 extract-pdf-text 提取拆解
            pdf_req = urllib.request.Request(
                f"{base}/api/workos/doc-ingest/preview",
                data=json.dumps({
                    "file_bytes_b64": base64.b64encode(b"%PDF-1.4\n%mock-pdf\n").decode("ascii"),
                    "filename": "星云净水器Pro.pdf",
                    "instruction": "希望你能够替代我去和顾客聊天",
                    "use_llm": False,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(pdf_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                pdf_prev = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(pdf_prev["ok"])
                self.assertEqual(pdf_prev["sourceType"], "pdf")
                self.assertEqual(pdf_prev["pageCount"], 2)
                self.assertGreaterEqual(pdf_prev["itemCount"], 3)
                self.assertTrue(any(c and c[0] == "extract-pdf-text" for c in native_calls))

            # 5) POST /api/workos/doc-ingest/confirm 入库后，preview_smart_reply 立即命中并遵循顾问式回答
            conf_req = urllib.request.Request(
                f"{base}/api/workos/doc-ingest/confirm",
                data=json.dumps({
                    "items": pdf_prev["items"],
                    "strategy": "bind_kb",
                    "doc_name": pdf_prev["docName"],
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(conf_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                conf_res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(conf_res["ok"])
                self.assertEqual(conf_res["strategy"], "bind_kb")
                self.assertEqual(conf_res["savedCount"], len(pdf_prev["items"]))
                self.assertFalse(conf_res["promptUpdated"])

            hit_reply = work_engine.preview_smart_reply(
                "语音助手",
                "语音助手: 星云净水器 Pro 怎么使用？",
                use_llm=False,
            )
            self.assertTrue(hit_reply["ok"])
            self.assertGreaterEqual(hit_reply["matchedCount"], 1)
            self.assertIn("星云净水器", hit_reply["replyText"])
            self.assertIn("接通电源", hit_reply["replyText"])

            # 验证 LLM 路径注入顾问式两段回复提示词
            recorded_msgs = []

            class _MockConsultHub:
                def is_llm_enabled(self):
                    return True

                def generate_chat_reply(self, messages, *, model_id=None, contact_name=None):
                    recorded_msgs.append(messages)
                    return {
                        "ok": True,
                        "replyText": "您好，理解您的需求，星云净水器 Pro 先接通电源冲洗5分钟即可直饮。",
                        "modelId": "mock-consult",
                        "providerId": "mock",
                        "latencyMs": 10,
                    }

            orig_models = work_engine.models
            work_engine.models = _MockConsultHub()  # type: ignore[assignment]
            try:
                llm_prev = work_engine.preview_smart_reply(
                    "语音助手",
                    "星云净水器 Pro 怎么使用？",
                    use_llm=True,
                )
                self.assertTrue(llm_prev["ok"])
                self.assertIn("先共情/给专业判断或安全排查", recorded_msgs[0][0]["content"])
                self.assertIn("绝不编造承诺", recorded_msgs[0][0]["content"])
            finally:
                work_engine.models = orig_models

            # 6) needsHumanReview 在退款/投诉场景为 True
            refund_prev = work_engine.preview_smart_reply(
                "语音助手",
                "语音助手: 这台机器用不了我要申请退款并投诉",
                use_llm=False,
            )
            self.assertTrue(refund_prev["ok"])
            self.assertTrue(refund_prev["needsHumanReview"])
            self.assertTrue(bool(refund_prev["humanReviewReason"]))

            # 7) 联系白名单严守仅 ["语音助手", "联系人A", "openbot"] 及合规助手（拒绝 "陌生人"）
            stranger_req = urllib.request.Request(
                f"{base}/api/wechat-ai-assist",
                data=json.dumps({
                    "target": "陌生人",
                    "content_hint": "https://example.com",
                    "dry_run": True,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(stranger_req, timeout=10)
            self.assertEqual(ctx.exception.code, 400)
            err_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(err_body["ok"])
            self.assertEqual(err_body["error_code"], "target_not_allowed")

            assist_ok_req = urllib.request.Request(
                f"{base}/api/wechat-ai-assist",
                data=json.dumps({
                    "target": "小微",
                    "content_hint": "请总结这篇文章",
                    "bubbles": [{"direction": "peer", "text": "小微: 已整理文章核心要点与产品说明。"}],
                    "dry_run": True,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(assist_ok_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read().decode("utf-8"))["ok"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_popout_window_full_width_ocr_and_zero_switch_direct_inspect(self):
        from wechat_control.live_inspector import WeChatLiveInspector

        popout_dir = self.data / "popout_case"
        inspector = WeChatLiveInspector(
            lambda args, timeout=15.0: {"ok": False},
            snapshots_dir=popout_dir / "snap",
            reports_dir=popout_dir / "reports",
        )
        # 独立小窗无左栏（isMainWindow=False, splitX=0.0），左半侧 x=70 来信气泡绝不能被丢弃
        popout_ocr = {
            "ok": True,
            "windowID": 11503,
            "isMainWindow": False,
            "splitX": 0.0,
            "windowTitle": "语音助手",
            "windowBounds": {"x": 1380, "y": 484, "width": 598, "height": 640},
            "elements": [
                {"text": "语音助手", "bbox": {"x": 28, "y": 20, "width": 52, "height": 16}, "center": {"x": 54, "y": 28}, "confidence": 0.99},
                {"text": "请问企业版支持离线部署吗？", "bbox": {"x": 40, "y": 142, "width": 200, "height": 18}, "center": {"x": 70, "y": 151}, "confidence": 0.98},
                {"text": "支持离线部署与内网私有化", "bbox": {"x": 340, "y": 212, "width": 195, "height": 18}, "center": {"x": 438, "y": 221}, "confidence": 0.97},
            ],
        }
        structured = inspector.extract_structured_bubbles(popout_ocr)
        self.assertEqual(structured["headerTitle"], "语音助手")
        self.assertEqual(len(structured["bubbles"]), 2)
        self.assertEqual(structured["bubbles"][0]["direction"], "peer")
        self.assertIn("离线部署", structured["bubbles"][0]["text"])
        self.assertEqual(structured["bubbles"][1]["direction"], "self")

        # 验证 find_popout_window("语音助手") 与 inspect_messages("语音助手") 走免切换直连（无 click 切换主窗）
        native_cmds = []

        def fake_native_popout(args, timeout=15.0):
            native_cmds.append(list(args))
            cmd = args[0] if args else ""
            if cmd == "list-app-windows":
                return {
                    "ok": True,
                    "windows": [
                        {
                            "windowID": 3258,
                            "appId": "wechat",
                            "appLabel": "微信",
                            "title": "微信",
                            "isMainWindow": True,
                            "bounds": {"x": 20, "y": 40, "width": 900, "height": 720},
                        },
                        {
                            "windowID": 11503,
                            "appId": "wechat",
                            "appLabel": "微信",
                            "title": "语音助手",
                            "isMainWindow": False,
                            "bounds": {"x": 1380, "y": 484, "width": 598, "height": 640},
                        },
                    ],
                }
            if cmd == "capture-ocr":
                return dict(popout_ocr)
            return {"ok": True}

        inspector._run_native = fake_native_popout  # type: ignore[method-assign]
        found = inspector.find_popout_window("语音助手")
        self.assertIsNotNone(found)
        self.assertEqual(found["windowID"], 11503)

        inspected = inspector.inspect_messages("语音助手")
        self.assertTrue(inspected["ok"])
        self.assertTrue(inspected["popoutWindow"])
        self.assertTrue(inspected["zeroSwitch"])
        self.assertEqual(inspected["windowID"], 11503)
        self.assertEqual(inspected["headerTitle"], "语音助手")
        self.assertEqual(len(inspected["bubbles"]), 2)
        self.assertIn("离线部署", inspected["bubbles"][0]["text"])
        self.assertFalse(any(c and c[0] == "click" for c in native_cmds))
        self.assertTrue(any(
            c and c[0] == "capture-ocr" and "--window-id" in c and "11503" in c and "--no-activate" in c
            for c in native_cmds
        ))

    def test_multi_window_dhash_coalesce_priority_heap_and_two_tier_coordinator(self):
        import threading
        import time
        import urllib.error
        import urllib.request
        from wechat_control.multi_window_scheduler import (
            AgingPriorityScheduler,
            PerceptualDHashFilter,
            SlidingWindowCoalescer,
            TwoTierWindowCoordinator,
        )
        from wechat_control.web_console import render_web_console_html

        # 1) LC 461 PerceptualDHashFilter: 静止窗口跳过 OCR，变化窗口放行
        dhash_filter = PerceptualDHashFilter(default_threshold=4)
        self.assertEqual(dhash_filter.hamming_distance("0000000000000000", "000000000000000f"), 4)
        self.assertEqual(dhash_filter.hamming_distance("0000000000000000", "0000000000000003"), 2)

        run1, dist1 = dhash_filter.should_run_ocr(11503, "031af0c060343853")
        self.assertTrue(run1)
        self.assertEqual(dist1, 64)

        run2, dist2 = dhash_filter.should_run_ocr(11503, "031af0c060343850")  # distance=2 < 4
        self.assertFalse(run2)
        self.assertEqual(dist2, 2)

        run3, dist3 = dhash_filter.should_run_ocr(11503, "031af0c06034385c")  # distance from 031af0c060343853 = 4
        self.assertTrue(run3)
        self.assertGreaterEqual(dist3, 4)
        self.assertEqual(dhash_filter.stats()["ocrSkippedByDHash"], 1)
        self.assertEqual(dhash_filter.stats()["ocrTriggered"], 2)

        # 2) LC 56 SlidingWindowCoalescer: 1.8s 内连发短消息合并，跨窗拆段
        coalescer = SlidingWindowCoalescer(window_seconds=1.8)
        self.assertEqual(
            coalescer.merge_intervals([(1.0, 2.8), (1.8, 3.6), (5.0, 6.8)]),
            [(1.0, 3.6), (5.0, 6.8)],
        )
        self.assertIsNone(coalescer.push("语音助手", "在吗", now_ts=100.0))
        self.assertIsNone(coalescer.push("语音助手", "猫乱尿怎么喷", now_ts=100.9))
        # 未过 1.8s 窗暂不 drain
        self.assertEqual(coalescer.drain_ready(now_ts=102.0), [])
        # 超过 1.8s 窗自动合并输出
        ready = coalescer.drain_ready(now_ts=103.0)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["target"], "语音助手")
        self.assertEqual(ready[0]["mergedText"], "在吗 猫乱尿怎么喷")
        self.assertEqual(ready[0]["messageCount"], 2)
        self.assertTrue(ready[0]["coalesced"])
        self.assertEqual(coalescer.stats()["coalescedBursts"], 1)

        # 3) LC 1834 AgingPriorityScheduler: VIP+紧急优先 + 老化防饿死 + 并发思考 + 单写锁串行发消息
        scheduler = AgingPriorityScheduler(min_send_interval_seconds=0.0)
        scheduler.enqueue({"target": "普通新消息", "urgency": 0.3, "careWeight": 0.5, "isPopout": False}, now_ts=200.0)
        scheduler.enqueue({"target": "VIP紧急小窗", "urgency": 1.0, "careWeight": 2.0, "isPopout": True}, now_ts=200.0)
        scheduler.enqueue({"target": "久等防饿死好友", "urgency": 0.2, "careWeight": 0.5, "isPopout": False}, now_ts=100.0)

        ordered = scheduler.peek_ordered(now_ts=200.0)
        # 久等防饿死好友 wait=100s -> +250 老化分 (> VIP紧急小窗 215 分 > 普通新消息 55 分)
        self.assertEqual([o["target"] for o in ordered], ["久等防饿死好友", "VIP紧急小窗", "普通新消息"])

        # 验证并发 think_fn 与单写锁串行 send_fn
        think_barrier = threading.Barrier(3, timeout=3.0)
        concurrent_think_peak = 0
        concurrent_send_peak = 0
        active_thinks = 0
        active_sends = 0
        counter_lock = threading.Lock()
        send_log = []

        def fake_think(task):
            nonlocal active_thinks, concurrent_think_peak
            with counter_lock:
                active_thinks += 1
                concurrent_think_peak = max(concurrent_think_peak, active_thinks)
            think_barrier.wait()
            time.sleep(0.02)
            with counter_lock:
                active_thinks -= 1
            return f"reply:{task['target']}"

        def fake_send(task, draft):
            nonlocal active_sends, concurrent_send_peak
            with counter_lock:
                active_sends += 1
                concurrent_send_peak = max(concurrent_send_peak, active_sends)
            time.sleep(0.01)
            send_log.append((task["target"], draft))
            with counter_lock:
                active_sends -= 1
            return {"sent": True}

        dispatch_res = scheduler.dispatch_concurrent_replies(
            None,
            think_fn=fake_think,
            send_fn=fake_send,
            max_workers=3,
            now_ts=200.0,
        )
        self.assertTrue(dispatch_res["ok"])
        self.assertEqual(dispatch_res["taskCount"], 3)
        self.assertGreaterEqual(concurrent_think_peak, 2)
        self.assertEqual(concurrent_send_peak, 1)
        self.assertEqual(
            dispatch_res["dispatchedOrder"],
            ["久等防饿死好友", "VIP紧急小窗", "普通新消息"],
        )
        self.assertEqual([x[0] for x in send_log], ["久等防饿死好友", "VIP紧急小窗", "普通新消息"])

        # 4) TwoTierWindowCoordinator: 快车道只收白名单独立小窗，主窗兜底严格去重，非白名单独立小窗只读隔离
        sample_windows = [
            {
                "windowID": 3258,
                "appId": "wechat",
                "appLabel": "微信",
                "title": "微信",
                "isMainWindow": True,
                "dHash64": "94a4848c84841481",
                "bounds": {"x": 0, "y": 30, "width": 853, "height": 1320},
            },
            {
                "windowID": 11503,
                "appId": "wechat",
                "appLabel": "微信",
                "title": "语音助手",
                "isMainWindow": False,
                "dHash64": "031af0c060343853",
                "bounds": {"x": 1380, "y": 484, "width": 598, "height": 640},
            },
            {
                "windowID": 11509,
                "appId": "wechat",
                "appLabel": "微信",
                "title": "联系人B",
                "isMainWindow": False,
                "dHash64": "abcdef0123456789",
                "bounds": {"x": 1804, "y": 699, "width": 598, "height": 640},
            },
            {
                "windowID": 3776,
                "appId": "wecom",
                "appLabel": "企业微信",
                "title": "企业微信",
                "isMainWindow": True,
                "dHash64": "000000080c404040",
                "bounds": {"x": 853, "y": 30, "width": 960, "height": 1320},
            },
        ]
        lanes = TwoTierWindowCoordinator.plan_lanes(["语音助手", "联系人A", "openbot"], sample_windows)
        self.assertEqual([p["target"] for p in lanes["fastLanePopouts"]], ["语音助手"])
        self.assertEqual(lanes["fastLanePopouts"][0]["windowID"], 11503)
        self.assertTrue(lanes["fastLanePopouts"][0]["zeroSwitch"])
        self.assertEqual(lanes["mainWindowFallbackTargets"], ["联系人A", "openbot"])
        self.assertEqual([p["title"] for p in lanes["protectedReadOnlyPopouts"]], ["联系人B"])
        self.assertTrue(lanes["protectedReadOnlyPopouts"][0]["readOnly"])

        # 5) web_console.py 新增 v2.4.71 DOM 标记校验
        html = render_web_console_html()
        for marker in (
            "borderOverlayToggle",
            "runMultiWinSchedulerBtn",
            "settingsBorderOverlayToggle",
            "popoverSchedulerSummary",
            "workosSchedulerBox",
        ):
            self.assertIn(marker, html, f"web_console.py 缺少 v2.4.71 标记: {marker}")

        # 6) HTTP 端到端验证 /api/workos/scheduler、/api/workos/scheduler/run、/api/workos/border-overlay
        sched_dir = self.data / "v2471_http_engine"
        sched_engine = WeChatControlEngine(
            audit_log_path=sched_dir / "audit.jsonl",
            auth_file_path=sched_dir / "auth.json",
            bindings_file_path=sched_dir / "bindings.json",
            models_config_path=sched_dir / "models.json",
            model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=sched_dir / "kb.sqlite",
            personas_file_path=sched_dir / "personas.json",
            snapshots_dir=sched_dir / "snap",
            reports_dir=sched_dir / "reports",
        )
        sched_engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-v2471-test")
        sched_engine.bind_contact("语音助手", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True, special_care=True)
        sched_engine.bind_contact("联系人A", role="friend", ai_persona="wecom-kf-pro", auto_reply_enabled=True)
        sched_engine.bind_contact("openbot", role="group", ai_persona="wecom-kf-pro", auto_reply_enabled=True)

        def fake_native_sched(args, timeout=15.0):
            cmd = args[0] if args else ""
            if cmd in ("dhash-windows", "list-app-windows"):
                return {
                    "ok": True,
                    "app": "all",
                    "count": len(sample_windows),
                    "elapsedMs": 12.4,
                    "windows": sample_windows,
                }
            return {"ok": True}

        sched_engine._run_native = fake_native_sched  # type: ignore[method-assign]

        srv = create_http_server(sched_engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/api/workos/scheduler", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                st = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(st["ok"])
                self.assertIn("dhash", st)
                self.assertIn("coalescer", st)
                self.assertIn("priorityQueue", st)
                self.assertIn("borderOverlay", st)

            # Round 1: 首次执行，快车道触发 OCR，主窗兜底去重，非白名单隔离
            r1_req = urllib.request.Request(
                f"{base}/api/workos/scheduler/run",
                data=json.dumps({"auto_think": True, "dry_run": True, "app": "all"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(r1_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                r1 = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(r1["ok"])
                self.assertEqual(r1["scanSource"], "dhash-windows")
                self.assertEqual([p["target"] for p in r1["fastLanePopouts"]], ["语音助手"])
                self.assertTrue(r1["fastLanePopouts"][0]["shouldRunOcr"])
                self.assertEqual(set(r1["mainWindowFallbackTargets"]), {"联系人A", "openbot"})
                self.assertEqual([p["title"] for p in r1["protectedReadOnlyPopouts"]], ["联系人B"])
                self.assertIsNotNone(r1["dispatchReport"])
                self.assertEqual(r1["dispatchReport"]["taskCount"], 3)

            # Round 2: dHash 未变化 -> 直接跳过无效 OCR
            r2_req = urllib.request.Request(
                f"{base}/api/workos/scheduler/run",
                data=json.dumps({"auto_think": False, "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(r2_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                r2 = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(r2["ok"])
                self.assertFalse(r2["fastLanePopouts"][0]["shouldRunOcr"])
                self.assertGreaterEqual(r2["dhash"]["ocrSkippedByDHash"], 1)

            # 透明呼吸边框配置与读取（idle / thinking / human_paused + 非法态 400）
            for state_name, expected_color in (
                ("idle", "#10B981"),
                ("thinking", "#3B82F6"),
                ("human_paused", "#F59E0B"),
            ):
                bo_req = urllib.request.Request(
                    f"{base}/api/workos/border-overlay",
                    data=json.dumps({"enabled": True, "state": state_name}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(bo_req, timeout=10) as resp:
                    self.assertEqual(resp.status, 200)
                    bo = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(bo["ok"])
                    self.assertTrue(bo["enabled"])
                    self.assertEqual(bo["state"], state_name)
                    self.assertEqual(bo["color"], expected_color)
                    self.assertEqual([w["windowID"] for w in bo["activeWindows"]], [11503])

            with urllib.request.urlopen(f"{base}/api/workos/border-overlay", timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                bo_get = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(bo_get["enabled"])
                self.assertEqual(bo_get["color"], "#F59E0B")

            bad_bo_req = urllib.request.Request(
                f"{base}/api/workos/border-overlay",
                data=json.dumps({"state": "invalid_color_state"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(bad_bo_req, timeout=10)
            self.assertEqual(ctx.exception.code, 400)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_v2472_sidebar_watch_contact_and_clawbot_flow(self):
        import threading
        import urllib.error
        import urllib.request
        from wechat_control.web_console import render_web_console_html

        # 1) HTML DOM 标记覆盖左侧「+ 关注」「🪟 弹出小窗」与弹窗快捷添加
        html = render_web_console_html()
        for marker in (
            "sidebarWatchPanel",
            "sidebarAddWatchBtn",
            "sidebarPopoutAllBtn",
            "sidebarWatchDrawer",
            "sidebarWatchInput",
            "threadListPlusBtn",
            "hostingQuickAddInput",
            "popoutWatchedWindowsBtn",
        ):
            self.assertIn(marker, html, f"web_console.py 缺少 v2.4.72 标记: {marker}")

        # 2) 验证微信独立小窗标题匹配（微信 ClawBot AI <-> clawBOT）与防脏气泡污染
        w_dir = self.data / "v2472_watch_engine"
        w_engine = WeChatControlEngine(
            audit_log_path=w_dir / "audit.jsonl",
            auth_file_path=w_dir / "auth.json",
            bindings_file_path=w_dir / "bindings.json",
            models_config_path=w_dir / "models.json",
            model_http_requester=lambda m, u, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=w_dir / "kb.sqlite",
            personas_file_path=w_dir / "personas.json",
            snapshots_dir=w_dir / "snap",
            reports_dir=w_dir / "reports",
        )
        w_engine.auth_grant(ALL_CAPABILITIES, authorized_by="diag-v2472-test")
        w_engine.bind_contact("语音助手", role="friend", auto_reply_enabled=True)
        # 写入一个历史误采气泡，验证 profile_contacts/hosting_friends 自动过滤脏片段
        w_engine.bind_contact("家床头朝哪边啊?", role="friend", auto_reply_enabled=False)

        popout_windows = [
            {
                "windowID": 3258,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "微信",
                "isMainWindow": True,
                "bounds": {"x": 0, "y": 30, "width": 853, "height": 1320},
            },
            {
                "windowID": 14013,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "微信ClawBot",
                "isMainWindow": False,
                "bounds": {"x": 1591, "y": 96, "width": 598, "height": 640},
            },
            {
                "windowID": 11509,
                "appId": "wechat",
                "appLabel": "微信",
                "bundleID": "com.tencent.xinWeChat",
                "pid": 60968,
                "title": "联系人B",
                "isMainWindow": False,
                "bounds": {"x": 1804, "y": 699, "width": 598, "height": 640},
            },
        ]
        native_calls = []

        def fake_native_watch(args, timeout=15.0):
            native_calls.append(list(args))
            cmd = args[0] if args else ""
            if cmd == "list-app-windows":
                return {
                    "ok": True,
                    "app": "all",
                    "count": len(popout_windows),
                    "windows": popout_windows,
                }
            if cmd == "status":
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "accessibilityTrusted": True,
                    "postEventTrusted": True,
                    "screenCaptureTrusted": True,
                    "windows": [popout_windows[1]],  # 测试主窗关闭时只剩独立小窗
                }
            if cmd == "capture-ocr":
                return {
                    "ok": True,
                    "imageWidth": 598,
                    "imageHeight": 640,
                    "elements": [
                        {"text": "微信 ClawBot AI", "center": {"x": 110, "y": 30}, "bbox": {"x": 30, "y": 16, "width": 160, "height": 26}, "confidence": 0.99},
                        {"text": "你家床头朝哪边啊？", "center": {"x": 200, "y": 240}, "bbox": {"x": 40, "y": 225, "width": 260, "height": 28}, "confidence": 0.98},
                    ],
                }
            return {"ok": True}

        w_engine._run_native = fake_native_watch  # type: ignore[method-assign]

        # 仅剩独立小窗时执行 inspect_live：绝不把聊天句子当好友，只收录真实独立小窗标题
        insp = w_engine.inspector.inspect_live()
        self.assertTrue(insp["ok"])
        self.assertTrue(insp.get("popoutOnlyMode"))
        session_titles = [s["listTitleSnippet"] for s in insp["sessions"]]
        self.assertIn("微信ClawBot", session_titles)
        self.assertNotIn("你家床头朝哪边啊？", session_titles)
        self.assertNotIn("家床头朝哪边啊?", session_titles)

        # hosting_friends 自动收录独立小窗 微信ClawBot，并过滤掉脏片段 "家床头朝哪边啊?"
        hf = w_engine.hosting_friends()
        targets_in_friends = [f["target"] for f in hf["friends"]]
        self.assertIn("微信ClawBot", targets_in_friends)
        self.assertNotIn("家床头朝哪边啊?", targets_in_friends)

        srv = create_http_server(w_engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"

            # 空 target -> 400 missing_target
            empty_req = urllib.request.Request(
                f"{base}/api/watch-contacts",
                data=json.dumps({"action": "watch", "target": "   "}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(empty_req, timeout=10)
            self.assertEqual(ctx.exception.code, 400)
            self.assertEqual(json.loads(ctx.exception.read().decode("utf-8"))["error_code"], "missing_target")

            # 添加关注 clawBOT（auto_start_hosting=False），动态进入白名单并匹配「微信ClawBot」独立小窗
            w_req = urllib.request.Request(
                f"{base}/api/watch-contacts",
                data=json.dumps({"action": "watch", "target": "clawBOT", "auto_start_hosting": False}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(w_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                w_res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(w_res["ok"])
                self.assertTrue(w_res["watched"])
                self.assertIn("clawBOT", w_res["watchedTargets"])
                self.assertIn("clawBOT", w_res["hosting"]["targets"])

            with urllib.request.urlopen(f"{base}/api/workos/windows?app=all", timeout=10) as resp:
                wins_doc = json.loads(resp.read().decode("utf-8"))
                by_id = {w["windowID"]: w for w in wins_doc["windows"]}
                self.assertTrue(by_id[14013]["isPopout"])
                self.assertTrue(by_id[14013]["isAllowlistedTarget"])
                self.assertTrue(by_id[11509]["isPopout"])
                self.assertFalse(by_id[11509]["isAllowlistedTarget"])

            # POST /api/workos/popout-windows：对已打开小窗「clawBOT」命中 alreadyPopout，对陌生人拒绝 400
            pop_ok_req = urllib.request.Request(
                f"{base}/api/workos/popout-windows",
                data=json.dumps({"targets": ["clawBOT"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(pop_ok_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                pop_res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(pop_res["ok"])
                self.assertEqual(pop_res["alreadyPopoutCount"], 1)
                self.assertEqual(pop_res["results"][0]["windowID"], 14013)

            pop_bad_req = urllib.request.Request(
                f"{base}/api/workos/popout-windows",
                data=json.dumps({"targets": ["陌生人"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx_bad:
                urllib.request.urlopen(pop_bad_req, timeout=10)
            self.assertEqual(ctx_bad.exception.code, 400)
            self.assertEqual(json.loads(ctx_bad.exception.read().decode("utf-8"))["error_code"], "target_not_allowed")

            # 取消关注 clawBOT：移除出 watchedTargets/hosting，并将 autoReplyEnabled 置 False
            uw_req = urllib.request.Request(
                f"{base}/api/watch-contacts",
                data=json.dumps({"action": "unwatch", "target": "clawBOT"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(uw_req, timeout=10) as resp:
                self.assertEqual(resp.status, 200)
                uw_res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(uw_res["ok"])
                self.assertFalse(uw_res["watched"])
                self.assertNotIn("clawBOT", uw_res["watchedTargets"])
                self.assertNotIn("clawBOT", uw_res["hosting"]["targets"])

            with urllib.request.urlopen(f"{base}/api/watch-contacts", timeout=10) as resp:
                lst = json.loads(resp.read().decode("utf-8"))
                self.assertNotIn("clawBOT", lst["watchedTargets"])
                b_after = w_engine.bindings.get_binding("clawBOT")
                self.assertFalse(b_after["autoReplyEnabled"])
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
