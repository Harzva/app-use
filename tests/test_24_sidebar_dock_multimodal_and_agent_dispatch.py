"""End-to-end tests for v2.1.0 Sidebar Dock, 2x OCR + DeepSeek Flash Multimodal Reader, and Friend Agent Dispatch."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control import local_signing  # noqa: E402
from wechat_control.auth_gate import READ_ONLY_CAPABILITIES  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


def _make_minimal_png(path: Path, width: int = 120, height: int = 80) -> Path:
    """Create a deterministic valid RGB PNG file without third-party dependencies."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend((32 if (x + y) % 2 == 0 else 235, 160, 210))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", crc)

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=6)
    png_bytes = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes)
    return path


def _make_mock_requester(*, fail_vision_once: bool = False):
    """Build a deterministic HTTP requester mimicking Magpie Gateway responses."""
    state = {"calls": []}

    def _requester(method, url, headers=None, payload=None, timeout=12.0):
        body = payload or {}
        state["calls"].append({"method": method, "url": url, "payload": body})
        if method == "GET" and url.endswith("/v1/models"):
            return 200, {
                "data": [
                    {
                        "id": "auto/deepseek-v4.1-flash",
                        "owned_by": "deepseek",
                        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                    },
                    {
                        "id": "auto/deepseek-v4-pro",
                        "owned_by": "deepseek",
                        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                    },
                ]
            }
        msgs = body.get("messages") or []
        has_image_part = any(
            isinstance(m.get("content"), list)
            and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m.get("content"))
            for m in msgs
            if isinstance(m, dict)
        )
        if fail_vision_once and has_image_part:
            return 400, {"error": "Simulated vision modality unsupported error"}
        reply_obj = {
            "summary": "Mock DeepSeek V4.1 Flash 多模态分析摘要：已完成页面、图像及指令提取。",
            "keyPoints": ["苹果 Vision 2x OCR 识别完成", "DeepSeek V4.1 Flash 多模态理解通过"],
            "friendIntent": "好友分享项目链接并要求绑定智能体执行画作/调研任务。",
            "actionPlan": "调用 boundAgentId 统筹执行并生成测试回执。",
            "recommendedReply": "收到，已完成链接/图片/视频深读并派发绑定智能体处理。",
        }
        return 200, {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(reply_obj, ensure_ascii=False),
                    }
                }
            ]
        }

    return _requester, state


class SidebarDockMultimodalAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.requester, self.req_state = _make_mock_requester(fail_vision_once=False)
        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=self.requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
        )
        self.engine.auth_grant(authorized_by="test-24-suite")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_24a_sidebar_dock_geometry_and_app_version(self) -> None:
        app_bundle = PROJECT_ROOT / "dist" / "WeChat Bot.app"
        app_exe = app_bundle / "Contents" / "MacOS" / "wechat-studio-app"
        self.assertTrue(app_exe.is_file(), f"Missing binary: {app_exe}")

        plist_ver = subprocess.run(
            ["defaults", "read", str(app_bundle / "Contents" / "Info.plist"), "CFBundleShortVersionString"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        self.assertEqual(plist_ver.returncode, 0, plist_ver.stderr)
        # 版本白名单会腐烂：改为语义判定（≥ 2.4.0），新版本号不再需要改测试
        ver_parts = [int(p) for p in plist_ver.stdout.strip().split(".")]
        self.assertGreaterEqual(tuple(ver_parts[:2]), (2, 4), f"app version too old: {plist_ver.stdout.strip()}")

        proc = subprocess.run([str(app_exe), "--verify-dock"], capture_output=True, text=True, timeout=10.0)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("sidebarDefaultWidth"), 430)
        self.assertIn("CodexDockGeometry", data.get("harvisBarPattern", ""))
        self.assertEqual(
            set(data.get("supportedModes") or []),
            {"dock_right", "dock_left", "overlay_right", "tile_split", "collapsed", "standalone"},
        )

    def test_24b_native_vision_crop_and_extract_video_frames(self) -> None:
        vision_bin = PROJECT_ROOT / "bin" / "wechat-vision-ax"
        self.assertTrue(vision_bin.is_file(), f"Missing binary: {vision_bin}")

        png_src = _make_minimal_png(self.tmp_path / "sample.png", 240, 160)
        crop_out = self.tmp_path / "cropped.png"
        crop_proc = subprocess.run(
            [str(vision_bin), "ocr", "--image", str(png_src), "--crop", "10,10,120,80", "--out", str(crop_out)],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        self.assertEqual(crop_proc.returncode, 0, crop_proc.stderr)
        crop_json = json.loads(crop_proc.stdout)
        self.assertTrue(crop_json.get("ok"))
        self.assertTrue(crop_out.is_file())
        self.assertEqual(crop_json.get("imageWidth"), 120)
        self.assertEqual(crop_json.get("imageHeight"), 80)

        sample_mp4 = PROJECT_ROOT / "logs" / "media_analyses" / "sample_xin_an_demo.mp4"
        if sample_mp4.is_file():
            frames_dir = self.tmp_path / "video_frames"
            vproc = subprocess.run(
                [
                    str(vision_bin),
                    "extract-video-frames",
                    "--video",
                    str(sample_mp4),
                    "--out-dir",
                    str(frames_dir),
                    "--frames",
                    "2",
                ],
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            self.assertEqual(vproc.returncode, 0, vproc.stderr)
            vjson = json.loads(vproc.stdout)
            self.assertTrue(vjson.get("ok"))
            self.assertGreaterEqual(vjson.get("frameCount", 0), 2)
            for fr in vjson.get("frames", []):
                self.assertTrue(Path(fr["path"]).is_file())

    def test_24c_magpie_multimodal_and_fallback(self) -> None:
        img = _make_minimal_png(self.tmp_path / "vision_input.png", 100, 100)
        res = self.engine.models.analyze_multimodal(
            prompt="请识别图片并总结",
            image_paths=[img],
            ocr_context="测试 OCR 文本",
            contact_name="心安",
            model_id="auto/deepseek-v4.1-flash",
        )
        self.assertTrue(res.get("ok"), res)
        self.assertTrue(res.get("usedMultimodalImage"))
        self.assertFalse(res.get("usedTextFallbackOnVisionError"))
        post_call = [c for c in self.req_state["calls"] if c["method"] == "POST"][-1]
        user_msgs = [m for m in post_call["payload"]["messages"] if m.get("role") == "user"]
        user_content = user_msgs[-1]["content"]
        self.assertIsInstance(user_content, list)
        self.assertTrue(any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/jpeg;base64,") for p in user_content))

        # Test automatic fallback when vision call errors
        fb_req, fb_state = _make_mock_requester(fail_vision_once=True)
        fb_engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "fb_audit.jsonl",
            auth_file_path=self.tmp_path / "fb_auth.json",
            bindings_file_path=self.tmp_path / "fb_bindings.json",
            models_config_path=self.tmp_path / "fb_models.json",
            model_http_requester=fb_req,
            knowledge_db_path=self.tmp_path / "fb_kb.sqlite",
            personas_file_path=self.tmp_path / "fb_personas.json",
            snapshots_dir=self.tmp_path / "fb_snaps",
            reports_dir=self.tmp_path / "fb_reports",
        )
        fb_engine.auth_grant(authorized_by="test-fb")
        fb_res = fb_engine.models.analyze_multimodal(
            prompt="回退测试",
            image_paths=[img],
            ocr_context="降级 OCR 保留内容",
            contact_name="心安",
            model_id="auto/deepseek-v4.1-flash",
        )
        self.assertTrue(fb_res.get("ok"), fb_res)
        self.assertTrue(fb_res.get("usedTextFallbackOnVisionError"))
        self.assertEqual(len([c for c in fb_state["calls"] if c["method"] == "POST"]), 2)

    def test_24d_media_link_analyzer_link_image_and_video(self) -> None:
        html_doc = """
        <html><head>
        <title>YoBot 微信私域 AI 助理</title>
        <meta name="description" content="微信AI客服与私域自动化平台" />
        </head><body><main><p>支持知识库、CRM接入与多Agent编排。</p></main></body></html>
        """
        link_res = self.engine.analyze_media_or_link(
            kind="link",
            url="https://yobot.yokoagi.com/",
            contact="心安",
            context_text="心安发送了 yobot 链接",
            html_override=html_doc,
        )
        self.assertTrue(link_res.get("ok"), link_res)
        self.assertEqual(link_res.get("kind"), "link")
        self.assertIn("YoBot", link_res.get("title", ""))
        self.assertTrue(Path(link_res["artifactPath"]).is_file())

        snap = PROJECT_ROOT / "logs" / "snapshots" / "monitor_poll_cur.png"
        if not snap.is_file():
            snap = _make_minimal_png(self.tmp_path / "mock_snap.png", 1000, 700)
        img_res = self.engine.analyze_media_or_link(
            kind="image",
            source_snapshot=str(snap),
            crop_region={"x": 710, "y": 350, "width": 200, "height": 280},
            contact="心安",
            context_text="图文卡片识别测试",
        )
        self.assertTrue(img_res.get("ok"), img_res)
        self.assertEqual(img_res.get("kind"), "image_or_card")
        self.assertTrue(Path(img_res["artifactPath"]).is_file())

        sample_mp4 = PROJECT_ROOT / "logs" / "media_analyses" / "sample_xin_an_demo.mp4"
        if sample_mp4.is_file():
            vid_res = self.engine.analyze_media_or_link(
                kind="video",
                video_path=str(sample_mp4),
                contact="心安",
                frame_count=2,
            )
            self.assertTrue(vid_res.get("ok"), vid_res)
            self.assertEqual(vid_res.get("kind"), "video")
            self.assertGreaterEqual(vid_res.get("frameCount", 0), 2)
            self.assertGreaterEqual(vid_res.get("ocrCount", 0), 1)

    def test_24e_agent_binding_instruction_dispatch_mcp_http_and_ui(self) -> None:
        # First bind with care tier and custom notes
        b1 = self.engine.bind_contact(
            "心安",
            role="friend",
            ai_persona="warm-friend",
            notes="重要好友备注",
            special_care=True,
            care_level="special_care",
            care_tags=["特别关心"],
            bound_agent_id="bot_wechat_ecosystem",
            bound_agent_name="WeChat Bot 全生态智能体",
            bound_agent_type="botstudio",
            vision_model_id="auto/deepseek-v4.1-flash",
            auto_dispatch_instructions=True,
            auto_analyze_links_and_media=True,
        )
        self.assertTrue(b1.get("ok"))
        self.assertEqual(b1["binding"]["boundAgentId"], "bot_wechat_ecosystem")
        self.assertEqual(b1["binding"]["visionModelId"], "auto/deepseek-v4.1-flash")
        self.assertTrue(b1["binding"]["specialCare"])

        # Re-bind only vision model -> existing special care & notes must remain intact
        b2 = self.engine.bind_contact("心安", vision_model_id="auto/deepseek-v4-pro")
        self.assertEqual(b2["binding"]["visionModelId"], "auto/deepseek-v4-pro")
        self.assertEqual(b2["binding"]["boundAgentId"], "bot_wechat_ecosystem")

        # Write contact history using real `records` schema
        contacts_dir = self.engine.inspector.reports_dir / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        (contacts_dir / "xin_an_history.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "target": "心安",
                    "matchedTitle": "心安",
                    "records": [
                        {"kind": "timestamp", "direction": "system", "text": "星期二 15:00"},
                        {"kind": "message", "direction": "peer", "text": "https://yobot.yokoagi.com/"},
                        {"kind": "message", "direction": "peer", "text": "以这个图为母版丰富画面，antigravity 作画，opus 选的油画笔"},
                        {"kind": "message", "direction": "peer", "text": "GitHub地址：github.com/OpenBMB/StaffDeck"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        dispatch_res = self.engine.dispatch_friend_instructions(
            "心安",
            include_live_media=True,
            execute_with_agent=True,
            html_overrides={
                "https://yobot.yokoagi.com/": "<html><title>YoBot</title><body>AI Agent</body></html>",
                "https://github.com/OpenBMB/StaffDeck": "<html><title>StaffDeck</title><body>Digital Employee</body></html>",
            },
        )
        self.assertTrue(dispatch_res.get("ok"), dispatch_res)
        self.assertGreaterEqual(dispatch_res.get("tasksCount", 0), 3)
        cats = {t.get("category") for t in dispatch_res.get("tasks", [])}
        self.assertIn("ai_art_generation", cats)
        self.assertIn("url", cats)
        self.assertIn("github_repo", cats)
        self.assertTrue((dispatch_res.get("agentExecution") or {}).get("ok"))

        # MCP tools check
        mcp = WeChatMCPServer(self.engine)
        tools_resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
        for expected in (
            "wechat_bind_agent",
            "wechat_analyze_media",
            "wechat_agent_dispatch",
            "wechat_vision_stack",
            "wechat_dock_sidebar",
        ):
            self.assertIn(expected, tool_names)

        vstack_call = mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "wechat_vision_stack", "arguments": {}}})
        vstack_json = json.loads(vstack_call["result"]["content"][0]["text"])
        self.assertTrue(vstack_json.get("ok"))
        self.assertEqual(vstack_json["layer1MonitorVision"]["tokenCost"], 0)
        self.assertEqual(vstack_json["layer2MultimodalLLM"]["defaultVisionModelId"], "auto/deepseek-v4.1-flash")

        # HTTP server endpoints check
        srv = create_http_server(self.engine, host="127.0.0.1", port=0)
        port = srv.server_address[1]
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            def _req(path: str, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
                if data is None:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5.0) as r:
                        return json.loads(r.read().decode("utf-8"))
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(data).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8.0) as r:
                    return json.loads(r.read().decode("utf-8"))

            self.assertTrue(_req("/api/vision-stack").get("ok"))
            bind_http = _req("/api/bind-agent", {
                "target": "openbot",
                "boundAgentId": "bot_wechat_ecosystem",
                "boundAgentName": "OpenBot Test Agent",
                "visionModelId": "auto/deepseek-v4.1-flash",
            })
            self.assertTrue(bind_http.get("ok"))
            self.assertGreaterEqual(_req("/api/agent-tasks").get("count", 0), 1)
            self.assertGreaterEqual(_req("/api/media-analyses").get("count", 0), 1)
            dock_http = _req("/api/dock-sidebar", {"mode": "verify"})
            self.assertTrue(dock_http.get("ok"))
        finally:
            srv.shutdown()
            srv.server_close()

        # Web Console responsive sidebar CSS & v2.1.0 UI hooks
        html = render_web_console_html()
        for marker in (
            "@media (max-width: 520px)",
            "triggerDockSidebar('dock')",
            "triggerDockSidebar('tile')",
            "visionAgentDispatchPanel",
            "bindFriendAgent()",
            "runMediaDeepRead(",
            "runAgentDispatchFor(",
        ):
            self.assertIn(marker, html)

    def test_24d_stable_local_signing_zero_popup_and_no_approval_compile(self) -> None:
        for bundle_name, bundle_id in (
            ("WeChat Bot.app", "com.openbot.wechat-bot"),
        ):
            bundle_path = PROJECT_ROOT / "dist" / bundle_name
            sig = local_signing.verify_stable_signature(bundle_path, bundle_id=bundle_id)
            self.assertTrue(sig.get("ok"))
            self.assertFalse(sig.get("usesCdhash"))
            self.assertTrue(sig.get("zeroPopupVerified"))
            self.assertEqual(sig.get("mode"), "local-leaf-certificate")
            self.assertNotIn("cdhash", sig.get("designatedRequirement", ""))

        compiled = self.engine.compile_dsh_plugin_for_botstudio()
        self.assertTrue(compiled.get("ok"))

        preset_doc = json.loads((PROJECT_ROOT / "market" / "wechat-rpa-control.preset.json").read_text(encoding="utf-8"))
        plugin_doc = json.loads((PROJECT_ROOT / "market" / "wechat-rpa-control.plugin.json").read_text(encoding="utf-8"))
        preset_panels = preset_doc.get("panels") or []
        plugin_panels = ((plugin_doc.get("preset") or {}).get("panels")) or []
        self.assertGreaterEqual(len(preset_panels), 1)
        self.assertGreaterEqual(len(plugin_panels), 1)
        for panel in preset_panels + plugin_panels:
            for act in panel.get("actions") or []:
                self.assertIs(act.get("requiresApproval"), False, f"Action still requires approval: {act}")

        page_html = (PROJECT_ROOT / "dist" / "botstudio-pages" / "wechat-ecosystem" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("wbSilentCompileBundle", page_html)
        self.assertIn("wbSilentRebuildApp", page_html)

        mcp = WeChatMCPServer(self.engine)
        tools_list = mcp.handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}})
        tools = {t["name"]: t for t in tools_list["result"]["tools"]}
        bridge_enum = tools["wechat_botstudio_bridge"]["inputSchema"]["properties"]["action"]["enum"]
        self.assertIn("rebuild_app", bridge_enum)
        self.assertIn("compile_all", bridge_enum)

        bridge_status = self.engine.get_botstudio_bridge_status()
        self.assertTrue(bridge_status["standalone"]["signing"].get("zeroPopupVerified"))

        console_html = render_web_console_html()
        self.assertIn("rebuildStandaloneAppSilent()", console_html)
        self.assertNotIn("window.confirm(", console_html)


if __name__ == "__main__":
    unittest.main()
