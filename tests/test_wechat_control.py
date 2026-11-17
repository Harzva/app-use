"""End-to-end unit and integration tests for OpenBot macOS WeChat RPA + OCR + Bridge Plugin."""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.auth_gate import ALL_CAPABILITIES, READ_ONLY_CAPABILITIES, StudioPluginUnauthorizedError  # noqa: E402
from wechat_control.bridge_importer import UnsafeArchiveError, WeChatBridgeImporter  # noqa: E402
from wechat_control.contact_profiler import classify_time_slot  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.live_inspector import WeChatLiveInspector, _matches_target, _slugify_target  # noqa: E402
from wechat_control.magpie_provider_hub import MagpieProviderHub, map_magpie_model  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402
from wechat_control.safety import AntiBanGuard  # noqa: E402
from wechat_control.safety import (  # noqa: E402
    DirtyInputCircuitBreakerError,
    ReadbackMismatchError,
    ReadbackVerifier,
    normalize_chat_name,
)


def _offline_model_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in default unit test setup")


class WeChatControlTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.audit_log = self.tmp_path / "audit.jsonl"
        self.auth_file = self.tmp_path / "studio_auth.json"
        self.bindings_file = self.tmp_path / "bound_contacts.json"
        self.engine = WeChatControlEngine(
            audit_log_path=self.audit_log,
            auth_file_path=self.auth_file,
            bindings_file_path=self.bindings_file,
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        # Grant default safe capabilities for isolated functional tests
        self.engine.auth_grant(authorized_by="unit-test-studio")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    # 1. Fail-closed Bot Studio authorization gate & standalone plugin manifests
    def test_studio_authorization_gate_and_plugin_manifest(self) -> None:
        gated = WeChatControlEngine(
            audit_log_path=self.tmp_path / "gated_audit.jsonl",
            auth_file_path=self.tmp_path / "fresh_studio_auth.json",
        )
        # Fail-closed before grant
        self.assertFalse(gated.auth_status()["authorization"]["authorized"])
        with self.assertRaises(StudioPluginUnauthorizedError) as ctx:
            gated.get_status()
        self.assertEqual(ctx.exception.code, "STUDIO_PLUGIN_UNAUTHORIZED")

        # Grant read-only capabilities only -> status works, send_text_dry_run & send_text_live denied
        grant_res = gated.auth_grant(READ_ONLY_CAPABILITIES, authorized_by="studio-admin", note="Read-only inspection")
        self.assertTrue(grant_res["authorization"]["authorized"])
        self.assertTrue(gated.get_status().get("ok"))

        with self.assertRaises(StudioPluginUnauthorizedError):
            gated.send_text(target="测试群", text="hi", dry_run=True)

        # Grant default (includes send_text_dry_run) -> dry_run passes, live send still denied
        gated.auth_grant(authorized_by="studio-admin")
        dry_res = gated.send_text(target="测试群", text="hi", dry_run=True)
        self.assertTrue(dry_res["ok"])
        with self.assertRaises(StudioPluginUnauthorizedError):
            gated.send_text(target="测试群", text="hi", dry_run=False, silent_mode=False, confirm_send=True)

        # Revoke immediately blocks all capabilities again
        rev_res = gated.auth_revoke(reason="User toggled plugin off in Studio")
        self.assertFalse(rev_res["authorization"]["authorized"])
        with self.assertRaises(StudioPluginUnauthorizedError):
            gated.get_status()

        # Verify standalone plugin manifests & preset schema
        manifest = json.loads((PROJECT_ROOT / "plugin.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "openbot.plugin.wechat-rpa-control")
        self.assertTrue(manifest["authorization"]["failClosed"])
        pkg = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["name"], "@openbot/wechat-rpa-plugin")
        preset = json.loads((PROJECT_ROOT / "market" / "wechat-rpa-control.preset.json").read_text(encoding="utf-8"))
        self.assertEqual(preset["schema"], "openbot.codex-workbench-preset/1")
        self.assertEqual([p["id"] for p in preset.get("pages", [])], ["overview", "console", "workflows", "page_spec"])

    # 2. Native Swift binary status & permission prompt schema check
    def test_native_status_schema(self) -> None:
        status = self.engine.get_status()
        self.assertTrue(status.get("ok"), f"Unexpected status failure: {status}")
        for key in ("accessibilityTrusted", "postEventTrusted", "screenCaptureTrusted", "wechatRunning", "wechatFrontmost"):
            self.assertIn(key, status)

        perm = self.engine.request_permissions(open_settings=False)
        self.assertTrue(perm.get("ok"), f"Unexpected request_permissions failure: {perm}")
        self.assertTrue(perm.get("promptTriggered"))
        self.assertFalse(perm.get("openedSystemSettings"))
        for key in ("accessibilityTrusted", "postEventTrusted", "screenCaptureTrusted", "settingsURL"):
            self.assertIn(key, perm)
        self.assertTrue(self.audit_log.exists())

    # 3. Native macOS Vision Chinese OCR end-to-end test
    def test_native_vision_chinese_ocr_roundtrip(self) -> None:
        png_path = self.tmp_path / "wechat_mock_chat.png"
        sample_text = "客户A-私域运营群 (128)\n你好，请问今年的新品报价单发我一下\n收到，马上为您发送产品资料"
        rendered = self.engine.render_test_image(png_path, text=sample_text)
        self.assertTrue(rendered.get("ok"), f"render_test_image failed: {rendered}")
        self.assertTrue(png_path.exists())

        ocr_res = self.engine.ocr_image(png_path)
        self.assertTrue(ocr_res.get("ok"), f"OCR failed: {ocr_res}")
        self.assertGreaterEqual(ocr_res.get("count", 0), 3)

        all_texts = " ".join(el["text"] for el in ocr_res["elements"])
        self.assertIn("私域运营群", all_texts)
        self.assertIn("新品报价单", all_texts)
        self.assertIn("产品资料", all_texts)

        first = ocr_res["elements"][0]
        for box_key in ("x", "y", "width", "height"):
            self.assertIn(box_key, first["bbox"])
        self.assertIn("x", first["center"])
        self.assertIn("y", first["center"])

    # 4. Safety pipeline: dry_run, dedup lock, group allowlist & normalization, 3x circuit breaker
    def test_safety_send_pipeline_and_circuit_breaker(self) -> None:
        res1 = self.engine.send_text(
            target="VIP客户群 (45)",
            text="您好，本周活动方案已更新，请查收。",
            dry_run=True,
        )
        self.assertTrue(res1.get("ok"), res1)
        self.assertEqual(res1["status"], "dry_run_ok")
        self.assertFalse(res1["sent"])
        self.assertEqual(normalize_chat_name("VIP客户群 (45)"), "VIP客户群")

        res_dup = self.engine.send_text(
            target="VIP客户群",
            text="您好，本周活动方案已更新，请查收。",
            dry_run=True,
        )
        self.assertFalse(res_dup.get("ok"))
        self.assertEqual(res_dup["status"], "blocked_duplicate")

        res_wl = self.engine.send_text(
            target="外部陌生群 (12)",
            text="测试消息",
            dry_run=True,
        )
        self.assertFalse(res_wl.get("ok"))
        self.assertEqual(res_wl["status"], "blocked_whitelist")

        ReadbackVerifier.verify("短消息", "短消息")
        with self.assertRaises(DirtyInputCircuitBreakerError):
            ReadbackVerifier.verify("短消息", "历史草稿垃圾内容" * 10 + "短消息")
        with self.assertRaises(ReadbackMismatchError):
            ReadbackVerifier.verify("预期内容A", "完全不相干的内容B")

        res_cb = self.engine.send_text(
            target="测试私域运营群",
            text="报价单已发",
            dry_run=True,
            simulate_readback="残留草稿内容非常非常长" * 6 + "报价单已发",
        )
        self.assertFalse(res_cb.get("ok"))
        self.assertEqual(res_cb["status"], "circuit_breaker")

        audit_lines = self.audit_log.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(audit_lines), 4)

    # 5. WeChatBridge native archive import & Zip Slip security test
    def test_wechat_bridge_zip_import_and_security(self) -> None:
        zip_path = self.tmp_path / "forwarded_bundle.zip"
        transcript_body = (
            "·张经理\n"
            "2026年11月15日 09:30\n"
            "请把最新私有化部署方案发我一下，谢谢！\n"
            "·OpenBot顾问\n"
            "2026年11月15日 09:32\n"
            "[文件: OpenBot方案.pdf] 已发送，另有效果图 [图片: arch.png]\n"
        )
        fake_png = b"\x89PNG\r\n\x1a\nfake-image-payload"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("聊天记录.txt", transcript_body.encode("utf-8"))
            zf.writestr("attachments/arch.png", fake_png)

        out_dir = self.tmp_path / "exported"
        imported = self.engine.import_chatlog(zip_path, output_dir=out_dir)
        self.assertTrue(imported.get("ok"))
        bundle = imported["bundle"]
        self.assertEqual(bundle["record_count"], 2)
        self.assertEqual(bundle["attachment_count"], 1)
        self.assertEqual(bundle["participants"], ["OpenBot顾问", "张经理"])
        self.assertEqual(bundle["records"][0]["sender"], "张经理")
        self.assertEqual(bundle["records"][1]["msg_type"], "mixed")

        md_file = Path(imported["exportedFiles"]["markdown"])
        jsonl_file = Path(imported["exportedFiles"]["jsonl"])
        self.assertTrue(md_file.exists())
        self.assertTrue(jsonl_file.exists())
        md_text = md_file.read_text(encoding="utf-8")
        self.assertIn("张经理", md_text)
        self.assertIn("attachments/arch.png", md_text)

        jsonl_lines = [json.loads(line) for line in jsonl_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(jsonl_lines), 2)

        evil_zip = self.tmp_path / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../escape.txt", b"pwn")
        importer = WeChatBridgeImporter()
        with self.assertRaises(UnsafeArchiveError):
            importer.load(evil_zip)

    # 6. MCP JSON-RPC 2.0 stdio server round-trip (with isolated Studio auth file)
    def test_mcp_stdio_roundtrip(self) -> None:
        txt_path = self.tmp_path / "classic_chat.txt"
        txt_path.write_text(
            "王总 2026-11-15 10:15:00\n今天下午三点同步私域自动化方案。\n",
            encoding="utf-8",
        )
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "wechat_doctor", "arguments": {}}},
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "wechat_import_chatlog",
                    "arguments": {"source_path": str(txt_path)},
                },
            },
        ]
        stdin_payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["WECHAT_PLUGIN_AUTH_FILE"] = str(self.auth_file)
        env["WECHAT_PLUGIN_AUDIT_LOG"] = str(self.audit_log)
        env["WECHAT_PLUGIN_BINDINGS_FILE"] = str(self.bindings_file)
        proc = subprocess.run(
            [sys.executable, "-m", "wechat_control.cli", "serve-mcp"],
            input=stdin_payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4])

        tools = responses[1]["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        self.assertIn("wechat_auth_status", tool_names)
        self.assertIn("wechat_inspect_live", tool_names)
        self.assertIn("wechat_send_text", tool_names)
        self.assertIn("wechat_import_chatlog", tool_names)
        self.assertIn("wechat_bind_contact", tool_names)
        self.assertIn("wechat_observe_contact", tool_names)
        self.assertIn("wechat_profile_contact", tool_names)
        self.assertIn("wechat_chat_test", tool_names)
        self.assertIn("wechat_kb_search", tool_names)
        self.assertIn("wechat_kb_save", tool_names)
        self.assertIn("wechat_persona_switch", tool_names)
        self.assertIn("wechat_reply_preview", tool_names)
        self.assertIn("wechat_watch_once", tool_names)
        self.assertIn("wechat_monitor_status", tool_names)
        self.assertIn("wechat_takeover_contact", tool_names)

        doctor_payload = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertTrue(doctor_payload["binaryReady"])
        self.assertTrue(doctor_payload["studioAuthorization"]["authorized"])

        import_payload = json.loads(responses[3]["result"]["content"][0]["text"])
        self.assertEqual(import_payload["bundle"]["record_count"], 1)
        self.assertEqual(import_payload["bundle"]["records"][0]["sender"], "王总")

    # 7. Bound contacts, session target matching, and style/frequency analytics
    def test_contact_binding_and_style_profiler(self) -> None:
        self.assertTrue(_matches_target("openbot", "Op... 昨天 23:39"))
        self.assertTrue(_matches_target("openbot", "openbot 11:37"))
        self.assertTrue(_matches_target("openbot", "openbot （2）"))
        self.assertTrue(_matches_target("心安", "心安 星期二"))
        self.assertFalse(_matches_target("心安", "心安、小苏的第二个号（3）"))
        self.assertFalse(_matches_target("心安", "心安: [链接] ResWorld"))
        self.assertFalse(_matches_target("心安", "苏文璐"))

        clustered = WeChatLiveInspector._cluster_session_rows(
            [
                {"text": "1", "center": {"x": 110, "y": 58}},
                {"text": "openbot 11:37", "center": {"x": 160, "y": 72}},
                {"text": "心安: [链接] R...", "center": {"x": 155, "y": 90}},
                {"text": "星期二", "center": {"x": 200, "y": 379}},
                {"text": "心安", "center": {"x": 135, "y": 381}},
                {"text": "https://yobot...", "center": {"x": 155, "y": 401}},
            ],
            split_x=222.0,
            win_h=640.0,
        )
        self.assertEqual([r["titleSnippet"] for r in clustered], ["openbot 11:37", "心安"])

        self.assertEqual(classify_time_slot("星期二 08:42"), "清晨 05:00-08:59")
        self.assertEqual(classify_time_slot("星期二 15:00"), "下午 12:00-17:59")
        self.assertEqual(classify_time_slot("昨天 23:39"), "深夜 22:00-04:59")

        bind_res = self.engine.bind_contact(
            "心安",
            role="friend",
            ai_persona="轻松幽默的 AI 伙伴",
            scheduled_enabled=True,
            cron_hint="0 9,21 * * *",
            auto_reply_enabled=True,
            notes="单元测试绑定",
        )
        self.assertTrue(bind_res["ok"])
        self.assertEqual(self.engine.list_bindings()["count"], 1)

        # Bound contact bypasses static test allowlist, while unbound contact remains blocked
        dry_bound = self.engine.send_text(target="心安", text="定时问候测试", dry_run=True)
        self.assertTrue(dry_bound["ok"], dry_bound)
        self.assertEqual(dry_bound["status"], "dry_run_ok")

        dry_chat = self.engine.chat_test(target="心安", mode="scheduled", confirm_send=False)
        self.assertTrue(dry_chat["ok"])
        self.assertEqual(dry_chat["status"], "dry_run_ok")
        self.assertIn("定时测试", dry_chat["generatedText"])

        blocked_unbound = self.engine.send_text(target="未绑定陌生群", text="hi", dry_run=True)
        self.assertFalse(blocked_unbound["ok"])
        self.assertEqual(blocked_unbound["status"], "blocked_whitelist")

        # Persist mock observed history & verify analytics report generation
        contacts_dir = self.tmp_path / "reports" / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify_target("心安")
        (contacts_dir / f"{slug}_history.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "target": "心安",
                    "matchedTitle": "心安",
                    "slug": slug,
                    "records": [
                        {"kind": "timestamp", "direction": "system", "text": "星期二 08:42", "timeMarker": "星期二 08:42"},
                        {"kind": "message", "direction": "self", "text": "一本名为“久病成医”的书", "timeMarker": "星期二 08:42"},
                        {"kind": "timestamp", "direction": "system", "text": "星期二 15:00", "timeMarker": "星期二 15:00"},
                        {"kind": "message", "direction": "self", "text": "https://yobot.yokoagi.com/", "timeMarker": "星期二 15:00"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        analytics = self.engine.profile_contacts()
        self.assertTrue(analytics["ok"])
        self.assertGreaterEqual(analytics["profileCount"], 1)
        xinan_prof = next(p for p in analytics["profiles"] if p["matchedTitle"] == "心安")
        self.assertTrue(xinan_prof["bound"])
        self.assertEqual(xinan_prof["messageCount"], 2)
        self.assertIn("清晨 05:00-08:59", xinan_prof["timeSlotDistribution"])
        self.assertIn("下午 12:00-17:59", xinan_prof["timeSlotDistribution"])
        self.assertTrue(Path(analytics["reportMarkdownPath"]).exists())
        self.assertTrue(Path(analytics["reportJsonPath"]).exists())

        unbind_res = self.engine.unbind_contact("心安")
        self.assertTrue(unbind_res["ok"])
        self.assertEqual(self.engine.list_bindings()["count"], 0)

    # 8. Customer service FTS5 knowledge base, terminology, withdraw, & OpenBot SQLite sync
    def test_knowledge_store_fts_terminology_withdraw_and_openbot_sync(self) -> None:
        listed = self.engine.kb_list()
        self.assertTrue(listed["ok"])
        self.assertGreaterEqual(listed["count"], 9)

        # Chinese 2-char bigram & FTS5 trigram search
        for query in ("你能回复我消息吗", "脏输入熔断", "RPA与按键精灵有什么区别"):
            found = self.engine.kb_search(query)
            self.assertTrue(found["ok"], query)
            self.assertGreaterEqual(found["matchedCount"], 1, f"Expected KB hit for {query!r}: {found}")

        # Secret material blocked
        with self.assertRaises(ValueError):
            self.engine.kb_save(
                title="非法密钥",
                body="Authorization token sk-abcdefghijklmnopqrstuvwxyz123456",
                kind="knowledge",
            )

        # Save, revision conflict check, and withdraw
        saved = self.engine.kb_save(
            title="微信企业客服术语：会话锚点",
            body="会话锚点用于绑定客户与接管记录，防止跨会话误回。",
            kind="terminology",
            keywords=["会话锚点", "微信客服"],
            synonyms=["anchor", "人工接管"],
        )
        entry = saved["entry"]
        entry_id = entry["id"]
        self.assertEqual(entry["revision"], 1)

        with self.assertRaises(ValueError):
            self.engine.kb_withdraw(entry_id, expected_revision=99)

        withdrawn = self.engine.kb_withdraw(entry_id, expected_revision=1)
        self.assertTrue(withdrawn["ok"])
        self.assertTrue(withdrawn["entry"]["withdrawn"])
        active_ids = {e["id"] for e in self.engine.kb_list()["entries"]}
        self.assertNotIn(entry_id, active_ids)

        # Sync from OpenBot-compatible knowledge.sqlite schema
        src_db = self.tmp_path / "openbot_knowledge.sqlite"
        with sqlite3.connect(str(src_db)) as conn:
            conn.executescript(
                """
                CREATE TABLE knowledge_entries (
                  space_id TEXT NOT NULL,
                  owner_bot_id TEXT NOT NULL,
                  id TEXT NOT NULL,
                  library TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  source TEXT NOT NULL DEFAULT '',
                  external INTEGER NOT NULL DEFAULT 1,
                  status TEXT NOT NULL DEFAULT 'published',
                  withdrawn INTEGER NOT NULL DEFAULT 0,
                  revision INTEGER NOT NULL DEFAULT 1,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  PRIMARY KEY (space_id, owner_bot_id, id)
                );
                CREATE TABLE knowledge_styles (
                  space_id TEXT NOT NULL,
                  bot_id TEXT NOT NULL,
                  value TEXT NOT NULL,
                  revision INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  PRIMARY KEY (space_id, bot_id)
                );
                """
            )
            conn.execute(
                """
                INSERT INTO knowledge_entries
                VALUES('personal', '', 'ob-1', 'shared', 'knowledge', '微信客服专属退换货政策',
                       '支持 7 天无理由退换，VIP 专属通道 15 分钟内响应。', 'wecom-kf', 1, 'published', 0, 2, 1000, 1000)
                """
            )
            conn.execute(
                """
                INSERT INTO knowledge_entries
                VALUES('personal', '', 'ob-draft', 'shared', 'knowledge', '内部草稿',
                       '不应在 external_only 检索返回。', 'wecom-kf', 0, 'published', 0, 1, 1000, 1000)
                """
            )
            conn.execute(
                """
                INSERT INTO knowledge_styles VALUES('personal', 'default', '专业清晰且有依据', 1, 1000)
                """
            )

        sync_res = self.engine.kb_sync_openbot(src_db)
        self.assertTrue(sync_res["ok"])
        self.assertEqual(sync_res["importedEntries"], 2)
        self.assertEqual(sync_res["importedStyles"], 1)
        hit = self.engine.kb_search("退换货政策")
        self.assertGreaterEqual(hit["matchedCount"], 1)
        self.assertTrue(any(e["title"] == "微信客服专属退换货政策" for e in hit["entries"]))

    # 9. Switchable persona engine + MBTI + interaction style smart reply preview
    def test_persona_switching_and_smart_reply(self) -> None:
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)
        plist = self.engine.persona_list()
        self.assertTrue(plist["ok"])
        self.assertGreaterEqual(len(plist["personas"]), 4)
        self.assertIn("INTJ", plist["mbtiTypes"])
        self.assertIn("challenger", plist["interactionStyles"])

        replies = {}
        configs = [
            ("warm-friend", None, None),
            ("wecom-kf-pro", None, None),
            ("rpa-tech-expert", "INTJ", "challenger"),
            ("concise-assistant", None, None),
        ]
        for pid, mbti, style in configs:
            sw = self.engine.persona_switch("心安", pid, mbti=mbti, interaction_style=style)
            self.assertTrue(sw["ok"])
            self.assertEqual(sw["persona"]["id"], pid)
            if mbti:
                self.assertEqual(sw["persona"]["mbti"], mbti)
            if style:
                self.assertEqual(sw["persona"]["interactionStyle"], style)
            prev = self.engine.preview_smart_reply("心安", "你好你好，你能回复我消息吗？")
            self.assertTrue(prev["ok"])
            self.assertEqual(prev["basis"]["personaId"], pid)
            self.assertTrue(prev["replyText"])
            replies[pid] = prev["replyText"]

        self.assertEqual(len(set(replies.values())), 4)
        self.assertIn("微信客服", replies["wecom-kf-pro"])

        tech_prev = self.engine.preview_smart_reply("心安", "RPA与按键精灵有什么区别", persona_override="rpa-tech-expert")
        self.assertGreaterEqual(tech_prev["matchedCount"], 1)

    # 10. Unread badge detection + multi-line bubble clustering & pixel green-vs-grey test
    def test_live_inspector_unread_badge_and_bubble_clustering(self) -> None:
        clustered = WeChatLiveInspector._cluster_session_rows(
            [
                {"text": "2", "center": {"x": 68, "y": 64}},
                {"text": "心安", "center": {"x": 120, "y": 68}},
                {"text": "12:04", "center": {"x": 205, "y": 68}},
                {"text": "你好你好，你…", "center": {"x": 145, "y": 88}},
                {"text": "openbot", "center": {"x": 125, "y": 132}},
                {"text": "昨天", "center": {"x": 205, "y": 132}},
                {"text": "收到", "center": {"x": 145, "y": 152}},
            ],
            split_x=222.0,
            win_h=640.0,
        )
        self.assertEqual(len(clustered), 2)
        self.assertEqual(clustered[0]["titleSnippet"], "心安")
        self.assertEqual(clustered[0]["unreadBadge"], "2")
        self.assertEqual(clustered[1]["titleSnippet"], "openbot")
        self.assertEqual(clustered[1]["unreadBadge"], "")

        # Synthesize a real RGB PNG (480x140) where BOTH bubbles overlap horizontally
        # around x=180..280, distinguished purely by peer grey vs self green pixels!
        def _write_test_png(path: Path, width: int, height: int) -> None:
            rows_raw = bytearray()
            for y in range(height):
                rows_raw.append(0)  # filter type 0
                for x in range(width):
                    if 160 <= x <= 320 and 55 <= y <= 85:
                        rows_raw.extend((237, 238, 240))  # peer grey bubble
                    elif 160 <= x <= 320 and 92 <= y <= 130:
                        rows_raw.extend((158, 242, 159))  # self green bubble
                    else:
                        rows_raw.extend((245, 245, 245))

            def _chunk(tag: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
            png_bytes = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows_raw))) + _chunk(b"IEND", b"")
            path.write_bytes(png_bytes)

        synth_png = self.tmp_path / "synth_bubbles.png"
        _write_test_png(synth_png, 480, 140)

        bubbles = WeChatLiveInspector.cluster_message_bubbles(
            [
                {"text": "12:04", "x": 300, "y": 40, "bbox": {"x": 280, "y": 32, "width": 40, "height": 14}},
                {"text": "你好你好，你能回复我消息", "x": 220, "y": 60, "bbox": {"x": 170, "y": 53, "width": 130, "height": 14}},
                {"text": "吗？", "x": 182, "y": 78, "bbox": {"x": 170, "y": 71, "width": 24, "height": 14}},
                {"text": "收到啦", "x": 210, "y": 110, "bbox": {"x": 175, "y": 103, "width": 48, "height": 14}},
            ],
            split_x=150.0,
            win_w=480.0,
            image_path=synth_png,
        )
        self.assertEqual(len(bubbles), 2)
        self.assertEqual(bubbles[0]["direction"], "peer")
        self.assertEqual(bubbles[0]["text"], "你好你好，你能回复我消息吗？")
        self.assertEqual(bubbles[0]["timeMarker"], "12:04")
        self.assertEqual(bubbles[1]["direction"], "self")
        self.assertEqual(bubbles[1]["text"], "收到啦")

    # 11. Real-time monitor: peer trigger, idempotent dedup lock, self-last skip, & human takeover
    def test_realtime_monitor_poll_dedup_self_and_takeover(self) -> None:
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test-studio")
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)
        self.engine.persona_switch("心安", "warm-friend")
        # 本用例连续模拟同一联系人多轮回复：放宽防封频控（闸门本身在 test_28 专项覆盖）
        self.engine.antiban = AntiBanGuard(
            state_path=self.tmp_path / "antiban_relaxed.json",
            per_contact_hourly=999, global_hourly=999, global_daily=999, min_reply_gap_seconds=0,
        )

        sent_texts = []
        screen_mode = {"state": "svc_with_xinan_row", "peer_msg_stage": 1}

        def _fake_native(args, timeout):
            cmd = args[0]
            if cmd == "status":
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "accessibilityTrusted": True,
                    "postEventTrusted": True,
                    "screenCaptureTrusted": True,
                    "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
                }
            if cmd == "activate":
                return {"ok": True}
            if cmd == "hid-idle":
                return {
                    "ok": True,
                    "anyInputIdleSeconds": 90.0,
                    "mouseIdleSeconds": 90.0,
                    "keyboardIdleSeconds": 90.0,
                    "cursorPosition": {"x": 100.0, "y": 100.0},
                }
            if cmd == "click":
                click_x = float(args[args.index("--x") + 1]) if "--x" in args else 0.0
                if click_x > 60.0:
                    screen_mode["state"] = "xinan_open"
                return {"ok": True}
            if cmd == "capture-ocr":
                if "--out" in args:
                    out_p = Path(args[args.index("--out") + 1])
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(b"")
                if screen_mode["state"] == "svc_with_xinan_row":
                    return {
                        "ok": True,
                        "elements": [
                            {"text": "服务通知", "center": {"x": 300, "y": 28}, "bbox": {"x": 265, "y": 20, "width": 70, "height": 16}, "confidence": 0.99},
                            {"text": "1", "center": {"x": 66, "y": 64}, "bbox": {"x": 60, "y": 58, "width": 12, "height": 12}, "confidence": 0.99},
                            {"text": "心安", "center": {"x": 115, "y": 66}, "bbox": {"x": 96, "y": 58, "width": 36, "height": 16}, "confidence": 0.99},
                            {"text": "12:04", "center": {"x": 202, "y": 66}, "bbox": {"x": 182, "y": 58, "width": 38, "height": 16}, "confidence": 0.99},
                            {"text": "你好你好，你…", "center": {"x": 140, "y": 86}, "bbox": {"x": 96, "y": 78, "width": 90, "height": 16}, "confidence": 0.99},
                        ],
                    }
                if screen_mode["state"] == "xinan_self_last":
                    return {
                        "ok": True,
                        "elements": [
                            {"text": "心安", "center": {"x": 255, "y": 28}, "bbox": {"x": 236, "y": 20, "width": 38, "height": 16}, "confidence": 0.99},
                            {"text": "12:04", "center": {"x": 400, "y": 200}, "bbox": {"x": 380, "y": 192, "width": 40, "height": 14}, "confidence": 0.99},
                            {"text": "收到啦", "center": {"x": 520, "y": 260}, "bbox": {"x": 485, "y": 252, "width": 65, "height": 16}, "confidence": 0.99},
                        ],
                    }
                # xinan_open with peer message stage
                peer_lines = (
                    [
                        {"text": "你好你好，你能回复我消息", "center": {"x": 360, "y": 260}, "bbox": {"x": 295, "y": 252, "width": 135, "height": 16}, "confidence": 0.99},
                        {"text": "吗？", "center": {"x": 310, "y": 280}, "bbox": {"x": 295, "y": 272, "width": 28, "height": 16}, "confidence": 0.99},
                    ]
                    if screen_mode["peer_msg_stage"] == 1
                    else [
                        {"text": "客服在吗？转人工可以吗", "center": {"x": 355, "y": 320}, "bbox": {"x": 295, "y": 312, "width": 120, "height": 16}, "confidence": 0.99},
                    ]
                )
                return {
                    "ok": True,
                    "elements": [
                        {"text": "心安", "center": {"x": 255, "y": 28}, "bbox": {"x": 236, "y": 20, "width": 38, "height": 16}, "confidence": 0.99},
                        {"text": "12:04", "center": {"x": 400, "y": 220}, "bbox": {"x": 380, "y": 212, "width": 40, "height": 14}, "confidence": 0.99},
                        *peer_lines,
                    ],
                }
            if cmd == "paste-and-verify":
                txt = args[args.index("--text") + 1]
                sent_texts.append(txt)
                return {"ok": True, "sent": ("--send" in args), "readback": txt}
            return {"ok": True}

        self.engine._run_native = _fake_native  # type: ignore[method-assign]
        self.engine.inspector._sleep = lambda _s: None  # type: ignore[method-assign]

        # 1) Finds 心安 via unread row, navigates from 服务通知, clusters 2 lines, replies once
        r1 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["repliesDispatched"], 1)
        self.assertEqual(len(sent_texts), 1)
        self.assertEqual(r1["actions"][0]["status"], "replied")
        self.assertEqual(r1["actions"][0]["incomingText"], "你好你好，你能回复我消息吗？")

        # 2) Same peer bubble still on screen -> dedup lock refuses duplicate send
        r2 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r2["repliesDispatched"], 0)
        self.assertEqual(r2["actions"][0]["status"], "skipped_already_replied")
        self.assertEqual(len(sent_texts), 1)

        # 3) Last bubble is self -> never auto-replies to self
        screen_mode["state"] = "xinan_self_last"
        r3 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r3["repliesDispatched"], 0)
        self.assertEqual(r3["actions"][0]["status"], "skipped_last_is_self")

        # 4) Takeover pauses auto-send while still saving pendingDraft; resume dispatches
        to_res = self.engine.takeover_contact("心安", reason="VIP 人工接管")
        self.assertTrue(to_res["contactState"]["takenOver"])
        screen_mode["state"] = "xinan_open"
        screen_mode["peer_msg_stage"] = 2
        r4 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r4["repliesDispatched"], 0)
        # 新语义：该消息文本含「转人工」→ 客户意图触发自动接管（手动 takeover 已在，幂等）
        self.assertEqual(r4["actions"][0]["status"], "handoff_taken_over")
        self.assertTrue(self.engine.monitor.get_status(event_limit=0)["contacts"]
                        [normalize_chat_name("心安").casefold()]["takenOver"])
        self.assertEqual(r4["actions"][0]["incomingText"], "客服在吗？转人工可以吗")
        # 新语义：转人工提示语已真实发送（sent_texts: r1 智能回复 + r4 转接提示）
        self.assertEqual(len(sent_texts), 2)
        self.assertIn("人工", sent_texts[-1])

        self.engine.resume_contact("心安")
        # 新语义：转人工提示语已消费该消息签名——resume 后旧消息不重复自动回复
        # （人工恢复后直接在微信里接话，机器人无需重答「转人工」那条）
        r5 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r5["repliesDispatched"], 0)
        self.assertEqual(r5["actions"][0]["status"], "skipped_already_replied")
        self.assertEqual(len(sent_texts), 2)

    # 11b. Handoff intent: customer requests human -> auto takeover, drafts land in workbench
    def test_realtime_monitor_handoff_auto_takeover_and_workbench_sync(self) -> None:
        """转人工意图 → 自动接管 + 提示语发送；接管期间草稿同步进待办审阅台。"""
        from wechat_control.realtime_monitor import _is_human_handoff_request

        self.assertTrue(_is_human_handoff_request("转人工"))
        self.assertTrue(_is_human_handoff_request("请帮我转接人工客服"))
        self.assertTrue(_is_human_handoff_request("找真人"))
        self.assertFalse(_is_human_handoff_request("人工成本多少"))  # 误伤保护：普通话题不触发

        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test-studio")
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)
        self.engine.persona_switch("心安", "warm-friend")
        self.engine.antiban = AntiBanGuard(
            state_path=self.tmp_path / "antiban_relaxed2.json",
            per_contact_hourly=999, global_hourly=999, global_daily=999, min_reply_gap_seconds=0,
        )

        sent_texts = []
        screen_mode = {"state": "svc_with_xinan_row"}

        def _fake_native(args, timeout):
            cmd = args[0]
            if cmd == "status":
                return {
                    "ok": True, "wechatRunning": True, "accessibilityTrusted": True,
                    "postEventTrusted": True, "screenCaptureTrusted": True,
                    "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
                }
            if cmd == "activate":
                return {"ok": True}
            if cmd == "hid-idle":
                return {
                    "ok": True, "anyInputIdleSeconds": 90.0,
                    "mouseIdleSeconds": 90.0, "keyboardIdleSeconds": 90.0,
                    "cursorPosition": {"x": 100.0, "y": 100.0},
                }
            if cmd == "click":
                click_x = float(args[args.index("--x") + 1]) if "--x" in args else 0.0
                if click_x > 60.0:
                    screen_mode["state"] = "xinan_open"
                return {"ok": True}
            if cmd == "capture-ocr":
                if "--out" in args:
                    out_p = Path(args[args.index("--out") + 1])
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(b"")
                if screen_mode["state"] == "svc_with_xinan_row":
                    return {
                        "ok": True,
                        "elements": [
                            {"text": "服务通知", "center": {"x": 300, "y": 28}, "bbox": {"x": 265, "y": 20, "width": 70, "height": 16}, "confidence": 0.99},
                            {"text": "1", "center": {"x": 66, "y": 64}, "bbox": {"x": 60, "y": 58, "width": 12, "height": 12}, "confidence": 0.99},
                            {"text": "心安", "center": {"x": 115, "y": 66}, "bbox": {"x": 96, "y": 58, "width": 36, "height": 16}, "confidence": 0.99},
                            {"text": "12:04", "center": {"x": 202, "y": 66}, "bbox": {"x": 182, "y": 58, "width": 38, "height": 16}, "confidence": 0.99},
                            {"text": "转人工", "center": {"x": 140, "y": 86}, "bbox": {"x": 96, "y": 78, "width": 90, "height": 16}, "confidence": 0.99},
                        ],
                    }
                # xinan_open：会话页含「转人工」peer 气泡
                return {
                    "ok": True,
                    "elements": [
                        {"text": "心安", "center": {"x": 255, "y": 28}, "bbox": {"x": 236, "y": 20, "width": 38, "height": 16}, "confidence": 0.99},
                        {"text": "12:04", "center": {"x": 400, "y": 220}, "bbox": {"x": 380, "y": 212, "width": 40, "height": 14}, "confidence": 0.99},
                        {"text": "转人工", "center": {"x": 355, "y": 320}, "bbox": {"x": 295, "y": 312, "width": 120, "height": 16}, "confidence": 0.99},
                    ],
                }
            if cmd == "paste-and-verify":
                txt = args[args.index("--text") + 1]
                sent_texts.append(txt)
                return {"ok": True, "sent": ("--send" in args), "readback": txt}
            return {"ok": True}

        self.engine._run_native = _fake_native  # type: ignore[method-assign]
        self.engine.inspector._sleep = lambda _s: None  # type: ignore[method-assign]

        # 1) 列表页找到心安（预览「转人工」）→ 进入会话 → handoff 自动接管 + 发提示语
        r1 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertTrue(r1.get("ok"))
        acts = r1.get("actions") or []
        self.assertTrue(acts and acts[0].get("status") == "handoff_taken_over",
                        f"转人工应触发自动接管: {acts}")
        self.assertTrue(sent_texts, "应已发送转人工提示语")
        mon = self.engine.monitor.get_status(event_limit=0)
        key = normalize_chat_name("心安").casefold()
        self.assertTrue((mon.get("contacts") or {}).get(key, {}).get("takenOver"),
                        "转人工后应自动置 takenOver")

        # 2) 接管期间草稿同步进待办审阅台（人工真的看得到、能一键发送）
        import sqlite3
        from contextlib import closing
        wb_db = self.engine.auth_gate.auth_file.parent / "workbench" / "saved-drafts.sqlite"
        res_push = self.engine.push_pending_draft_to_workbench(
            "心安", msgid="unit-msg-1", incoming="转人工",
            draft="好的，已为您转接人工客服，请稍候；人工不在时您可以留言，看到会第一时间回复您。",
        )
        self.assertTrue(res_push["ok"], res_push)
        with closing(sqlite3.connect(wb_db)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT id, target, incoming, draft FROM saved_draft").fetchall()
        self.assertTrue(any(r["incoming"] == "转人工" for r in rows),
                        f"待办里应有人工接管期间的消息: {[dict(r) for r in rows]}")

        # 3) 接管期间再巡检：同消息不重复处理、绝不真发送（机器人真的停手了）
        r2 = self.engine.monitor_once(auto_reply=True, confirm_send=True)
        self.assertEqual(r2["repliesDispatched"], 0)
        self.assertEqual(len(sent_texts), 1)  # 仅转人工提示语；接管期间无新增发送
        self.assertIn("人工", sent_texts[-1])

    def test_12_special_care_priority_and_enriched_analytics(self) -> None:
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="tester")
        # Bind three contacts at different tiers
        self.engine.bind_contact("普通同事", role="friend", ai_persona="concise-assistant")
        self.engine.bind_contact("openbot", role="group", ai_persona="rpa-tech-expert")
        self.engine.bind_contact("心安", role="friend", ai_persona="warm-friend")

        # Promote openbot -> vip and 心安 -> special_care
        r_vip = self.engine.set_special_care("openbot", enabled=True, care_level="vip", care_tags=["重点关照", "研发群"])
        self.assertEqual(r_vip["binding"]["careLevel"], "vip")
        self.assertTrue(r_vip["binding"]["specialCare"])

        r_sc = self.engine.set_special_care("心安", enabled=True, care_level="special_care", care_tags=["特别关心", "核心好友"], follow_up_days=2)
        self.assertEqual(r_sc["binding"]["careLevel"], "special_care")
        self.assertEqual(r_sc["binding"]["followUpDays"], 2)

        # Persona switch should preserve specialCare / careLevel on 心安
        self.engine.persona_switch("心安", "wecom-kf-pro", mbti="INFJ")
        kept = self.engine.bindings.get_binding("心安")
        assert kept is not None
        self.assertEqual(kept["careLevel"], "special_care")
        self.assertTrue(kept["specialCare"])

        # Write sample history to exercise bidirectional stats & warmth score
        contacts_dir = self.tmp_path / "reports" / "contacts"
        contacts_dir.mkdir(parents=True, exist_ok=True)
        (contacts_dir / "xinan_history.json").write_text(
            json.dumps(
                {
                    "target": "心安",
                    "matchedTitle": "心安",
                    "records": [
                        {"kind": "timestamp", "text": "20:15"},
                        {"kind": "message", "direction": "peer", "text": "你好你好，视频好有趣"},
                        {"kind": "message", "direction": "self", "text": "哈哈收到，我也觉得超好玩"},
                        {"kind": "message", "direction": "peer", "text": "晚上继续测试 OpenBot"},
                        {"kind": "message", "direction": "self", "text": "没问题，晚间黄金时段上线！"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        analytics = self.engine.profile_contacts()
        self.assertTrue(analytics["ok"])
        summary = analytics["specialCareSummary"]
        self.assertEqual(summary["specialCareCount"], 1)
        self.assertEqual(summary["vipCount"], 1)
        self.assertGreater(summary["averageWarmthScore"], 0)
        # First profile must be special_care (心安), second vip (openbot)
        self.assertEqual(analytics["profiles"][0]["target"], "心安")
        self.assertEqual(analytics["profiles"][0]["careLevel"], "special_care")
        self.assertEqual(analytics["profiles"][0]["monitorPriority"], "P0-最高优")
        self.assertEqual(analytics["profiles"][0]["selfCount"], 2)
        self.assertEqual(analytics["profiles"][0]["peerCount"], 2)
        self.assertIn("晚间", analytics["profiles"][0]["bestContactWindow"])
        self.assertEqual(analytics["profiles"][1]["target"], "openbot")
        self.assertEqual(analytics["profiles"][1]["careLevel"], "vip")

        # Demote test
        demote = self.engine.set_special_care("openbot", enabled=False)
        self.assertEqual(demote["binding"]["careLevel"], "normal")
        self.assertFalse(demote["binding"]["specialCare"])

    def test_13_web_console_http_endpoints(self) -> None:
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="tester")
        self.engine._run_native = lambda args, timeout=15.0: {  # type: ignore[method-assign]
            "ok": True,
            "accessibilityTrusted": True,
            "postEventTrusted": True,
            "screenCaptureTrusted": True,
            "wechatRunning": True,
            "wechatPid": 12345,
            "windowCount": 1,
            "windows": [{"windowID": 1, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
            "activeChat": {"title": "心安"},
        }
        self.engine.bind_contact("心安", role="friend", ai_persona="warm-friend", special_care=True, care_level="special_care")
        snap = self.tmp_path / "snapshots" / "unit_test_snap.png"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"

        def _req(path: str, payload: dict | None = None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            req = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.headers.get("Content-Type", ""), resp.read()
            except urllib.error.HTTPError as err:
                return err.code, err.headers.get("Content-Type", ""), err.read()

        try:
            # 1) HTML Web Console
            st, ct, raw = _req("/")
            self.assertEqual(st, 200)
            self.assertIn("text/html", ct)
            html = raw.decode("utf-8")
            self.assertIn('<title>WeChat Bot · 微信工作台</title>', html)
            self.assertIn('href="/workbench"', html)
            self.assertIn("/api/special-care", html)

            # 2) Aggregated overview API
            st, _, raw = _req("/api/overview")
            self.assertEqual(st, 200)
            ov = json.loads(raw.decode("utf-8"))
            self.assertTrue(ov["ok"])
            self.assertEqual(ov["analytics"]["specialCareSummary"]["specialCareCount"], 1)
            self.assertEqual(ov["wechatStatus"]["activeChat"]["title"], "心安")

            # 3) Snapshot route & path traversal guard
            st, ct, raw = _req("/snapshots/unit_test_snap.png")
            self.assertEqual(st, 200)
            self.assertIn("image/png", ct)
            self.assertGreater(len(raw), 20)

            st_bad, _, _ = _req("/snapshots/..%2F..%2Fetc%2Fpasswd")
            self.assertEqual(st_bad, 404)

            # 4) Toggle Special Care, Persona, Takeover, KB & Preview via HTTP POST
            st, _, raw = _req("/api/special-care", {"target": "openbot", "care_level": "vip", "enabled": True})
            self.assertEqual(st, 200)
            self.assertEqual(json.loads(raw.decode("utf-8"))["binding"]["careLevel"], "vip")

            st, _, raw = _req("/api/persona-switch", {"target": "心安", "persona_id": "rpa-tech-expert"})
            self.assertEqual(st, 200)
            self.assertEqual(json.loads(raw.decode("utf-8"))["persona"]["id"], "rpa-tech-expert")

            st, _, raw = _req("/api/takeover", {"target": "心安", "action": "takeover", "reason": "testing"})
            self.assertEqual(st, 200)
            self.assertTrue(json.loads(raw.decode("utf-8"))["contactState"]["takenOver"])

            st, _, raw = _req("/api/takeover", {"target": "心安", "action": "resume"})
            self.assertEqual(st, 200)
            self.assertFalse(json.loads(raw.decode("utf-8"))["contactState"]["takenOver"])

            st, _, raw = _req("/api/kb-save", {"title": "Web测试术语", "body": "3x 读回校验防止输入错位", "kind": "terminology", "keywords": ["读回"]})
            self.assertEqual(st, 200)
            st, _, raw = _req("/api/kb-search", {"query": "读回"})
            self.assertEqual(st, 200)
            self.assertGreaterEqual(len(json.loads(raw.decode("utf-8"))["entries"]), 1)

            st, _, raw = _req("/api/reply-preview", {"target": "心安", "incoming_text": "你好，请问支持防封吗？"})
            self.assertEqual(st, 200)
            self.assertIn("replyText", json.loads(raw.decode("utf-8")))

            # 5) Auth toggle revoke -> /api/overview fail-closed 403 -> grant restores 200
            st, _, _ = _req("/api/auth-toggle", {"action": "revoke"})
            self.assertEqual(st, 200)
            st_locked, _, raw_locked = _req("/api/overview")
            self.assertEqual(st_locked, 403)
            self.assertEqual(json.loads(raw_locked.decode("utf-8"))["error_code"], "STUDIO_PLUGIN_UNAUTHORIZED")

            st, _, _ = _req("/api/auth-toggle", {"action": "grant"})
            self.assertEqual(st, 200)
            st_ok, _, _ = _req("/api/overview")
            self.assertEqual(st_ok, 200)
        finally:
            srv.shutdown()
            srv.server_close()

        # 6) Verify ergonomic ./bin/wechat-bot CLI wrapper executes cleanly from outside repo cwd
        wrapper = PROJECT_ROOT / "bin" / "wechat-bot"
        env = dict(os.environ)
        env["WECHAT_PLUGIN_AUTH_FILE"] = str(self.auth_file)
        env["WECHAT_PLUGIN_BINDINGS_FILE"] = str(self.bindings_file)
        env["WECHAT_PLUGIN_AUDIT_LOG"] = str(self.audit_log)
        proc = subprocess.run(
            [str(wrapper), "care", "心安", "--level", "special_care", "--tag", "VIP测试"],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cli_out = json.loads(proc.stdout)
        self.assertTrue(cli_out["ok"])
        self.assertEqual(cli_out["binding"]["careLevel"], "special_care")

    # 14. Magpie Multi-Provider Hub: model mapping, gateway sync, SHA-256 profile IDs & secret masking
    def test_14_magpie_provider_hub_and_profiles(self) -> None:
        fake_gateway_models = {
            "data": [
                {
                    "id": "auto/deepseek-v4-pro",
                    "display_name": "DeepSeek V4 Pro",
                    "magpie_label": "DeepSeek V4 Pro · routing group",
                    "owned_by": "deepseek",
                    "context_window": 1048576,
                    "max_output_tokens": 393216,
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text"], "output": ["text"]},
                    "supported_reasoning_levels": [{"effort": "high"}, {"effort": "max"}],
                },
                {
                    "id": "mistral/mistral-large-4",
                    "display_name": "Mistral Large 4",
                    "owned_by": "mistral",
                    "context_window": 262144,
                    "max_output_tokens": 65536,
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                },
            ]
        }

        def _fake_http(method, url, headers=None, payload=None, timeout=12.0):
            if url.endswith("/v1/models"):
                return 200, fake_gateway_models
            return 404, {"error": "not mocked"}

        hub = MagpieProviderHub(
            plugin_root=PROJECT_ROOT,
            config_path=self.tmp_path / "hub_models.json",
            http_requester=_fake_http,
        )
        summary = hub.get_summary(refresh=True)
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["gatewayOnline"])
        self.assertEqual(summary["totalModelCount"], 2)
        self.assertTrue(any(g["name"] == "mistral" for g in summary["providerGroups"]))

        # Verify exact port of mapModel & input/effort extraction
        mistral_row = next(m for m in summary["models"] if m["id"] == "mistral/mistral-large-4")
        self.assertTrue(mistral_row["vision"])
        self.assertTrue(mistral_row["toolCall"])

        # Add custom OpenAI-compatible provider with a secret key -> verify strict masking
        secret_token = "sk-test-secret-do-not-leak-123456"
        saved = hub.upsert_provider(
            provider_id="custom-deepseek",
            name="自定义 DeepSeek 节点",
            base_url="https://api.deepseek.com/v1",
            api_key=secret_token,
            default_model="deepseek-chat",
            vendor="DeepSeek",
            enabled=True,
        )
        self.assertTrue(saved["ok"])
        self.assertTrue(saved["provider"]["hasKey"])
        self.assertEqual(saved["provider"]["maskedKey"], "••••••••")
        self.assertNotIn(secret_token, json.dumps(saved, ensure_ascii=False))

        # Verify SHA-256 profile ID generation (magpie_<16hex>) and per-contact binding
        selected = hub.use_model(model_id="mistral/mistral-large-4", contact="心安")
        self.assertTrue(selected["ok"])
        self.assertTrue(selected["profileId"].startswith("magpie_"))
        self.assertEqual(len(selected["profileId"]), len("magpie_") + 16)
        self.assertEqual(hub.resolve_model_for_contact("心安"), "mistral/mistral-large-4")

        # After syncing again, custom-deepseek/deepseek-chat should also appear in unified catalog
        refreshed = hub.get_summary(refresh=True)
        model_ids = {m["id"] for m in refreshed["models"]}
        self.assertIn("custom-deepseek/deepseek-chat", model_ids)
        self.assertNotIn(secret_token, json.dumps(refreshed, ensure_ascii=False))

    # 15. LLM-backed smart reply grounded in FTS5 KB + thinking-tag strip + fallback
    def test_15_llm_smart_reply_with_kb_and_fallback(self) -> None:
        recorded_requests = []

        def _smart_http(method, url, headers=None, payload=None, timeout=12.0):
            if url.endswith("/v1/models"):
                return 200, {"data": [{"id": "auto/deepseek-v4-pro", "owned_by": "deepseek"}]}
            if url.endswith("/v1/chat/completions"):
                recorded_requests.append(payload)
                req_model = payload["model"]
                if req_model == "broken/model":
                    return 502, {"error": "upstream unavailable"}
                return 200, {
                    "choices": [
                        {
                            "message": {
                                "content": "<think>检查3x读回术语后再回答</think>收到测试啦！后台监控与 3x 读回校验均正常在线 ✨"
                            }
                        }
                    ],
                    "usage": {"total_tokens": 88},
                }
            return 404, {}

        llm_engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "llm_audit.jsonl",
            auth_file_path=self.tmp_path / "llm_auth.json",
            bindings_file_path=self.tmp_path / "llm_bindings.json",
            models_config_path=self.tmp_path / "llm_models.json",
            model_http_requester=_smart_http,
            knowledge_db_path=self.tmp_path / "llm_kb.sqlite",
            personas_file_path=self.tmp_path / "llm_personas.json",
        )
        llm_engine.auth_grant(authorized_by="unit-test-llm")
        llm_engine.bind_contact("心安", role="friend", auto_reply_enabled=True)

        # Primary LLM reply with KB context injection & <think> stripping
        reply = llm_engine.preview_smart_reply("心安", "你们3x读回校验和防封控怎么做？", use_llm=True)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["generationMode"], "llm_magpie")
        self.assertEqual(reply["modelUsed"], "auto/deepseek-v4-pro")
        self.assertNotIn("<think>", reply["replyText"])
        self.assertIn("3x 读回", reply["replyText"])
        self.assertEqual(len(recorded_requests), 1)
        sys_msg = recorded_requests[0]["messages"][0]["content"]
        self.assertIn("心安", sys_msg)
        self.assertIn("企业知识库与术语参考", sys_msg)

        # Explicit broken model should fall back cleanly to KB template without raising
        llm_engine.models.state["fallbackModelId"] = ""
        fallback_reply = llm_engine.preview_smart_reply(
            "心安",
            "你好你好，你能回复我消息吗？",
            model_id="broken/model",
            use_llm=True,
        )
        self.assertTrue(fallback_reply["ok"])
        self.assertEqual(fallback_reply["generationMode"], "kb_template_fallback")
        self.assertTrue(fallback_reply["replyText"])

    # 16. HTTP /api/models, /api/model-select, /api/model-probe, /api/provider-save & CLI commands
    def test_16_web_console_and_cli_model_endpoints(self) -> None:
        def _probe_http(method, url, headers=None, payload=None, timeout=12.0):
            if url.endswith("/v1/models"):
                return 200, {
                    "data": [
                        {"id": "auto/deepseek-v4-pro", "display_name": "DeepSeek V4 Pro", "owned_by": "deepseek"},
                        {"id": "auto/glm-5.3-flash", "display_name": "GLM-5.3 Flash", "owned_by": "zhitro"},
                    ]
                }
            if url.endswith("/v1/chat/completions"):
                return 200, {"choices": [{"message": {"content": "探针响应正常 · Magpie OK"}}]}
            return 404, {}

        http_engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "http_m_audit.jsonl",
            auth_file_path=self.tmp_path / "http_m_auth.json",
            bindings_file_path=self.tmp_path / "http_m_bindings.json",
            models_config_path=self.tmp_path / "http_m_models.json",
            model_http_requester=_probe_http,
            knowledge_db_path=self.tmp_path / "http_m_kb.sqlite",
            personas_file_path=self.tmp_path / "http_m_personas.json",
        )
        http_engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-http-models")

        srv = create_http_server(http_engine, host="127.0.0.1", port=0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def _req(path, body=None):
                data = json.dumps(body).encode("utf-8") if body is not None else None
                headers = {"Content-Type": "application/json"} if body is not None else {}
                req = urllib.request.Request(base + path, data=data, headers=headers)
                with opener.open(req, timeout=5.0) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))

            st, models_payload = _req("/api/models?refresh=1")
            self.assertEqual(st, 200)
            self.assertTrue(models_payload["gatewayOnline"])
            self.assertEqual(models_payload["totalModelCount"], 2)

            st, sel_payload = _req("/api/model-select", {"model_id": "auto/glm-5.3-flash", "contact": "openbot"})
            self.assertEqual(st, 200)
            self.assertEqual(sel_payload["contactModelBindings"]["openbot"], "auto/glm-5.3-flash")

            st, probe_payload = _req("/api/model-probe", {"model_id": "auto/deepseek-v4-pro"})
            self.assertEqual(st, 200)
            self.assertTrue(probe_payload["ok"])
            self.assertIn("Magpie OK", probe_payload["replyText"])

            st, save_payload = _req(
                "/api/provider-save",
                {
                    "provider_id": "qwen-custom",
                    "name": "Qwen Test Node",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "api_key": "sk-secret-abc",
                    "default_model": "qwen-plus",
                },
            )
            self.assertEqual(st, 200)
            self.assertEqual(save_payload["provider"]["maskedKey"], "••••••••")
            self.assertNotIn("sk-secret-abc", json.dumps(save_payload))
        finally:
            srv.shutdown()
            srv.server_close()

        # Verify CLI wrapper subcommands `models` and `model-set`
        wrapper = PROJECT_ROOT / "bin" / "wechat-bot"
        env = dict(os.environ)
        env["WECHAT_PLUGIN_AUTH_FILE"] = str(self.auth_file)
        env["WECHAT_PLUGIN_BINDINGS_FILE"] = str(self.bindings_file)
        env["WECHAT_PLUGIN_AUDIT_LOG"] = str(self.audit_log)
        env["WECHAT_PLUGIN_MODELS_CONFIG"] = str(self.tmp_path / "cli_models.json")
        proc = subprocess.run(
            [str(wrapper), "model-set", "auto/glm-5.3", "--contact", "心安"],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["contactModelBindings"]["心安"], "auto/glm-5.3")

    # 17. Auto-wake WeChat window from closed/minimized state & poll_error deduplication
    def test_17_auto_wake_wechat_window_and_poll_error_dedup(self) -> None:
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-auto-wake")
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)

        state_tracker = {"activated": False}

        def _wake_native(args, timeout):
            cmd = args[0]
            if cmd == "hid-idle":
                return {
                    "ok": True,
                    "anyInputIdleSeconds": 90.0,
                    "mouseIdleSeconds": 90.0,
                    "keyboardIdleSeconds": 90.0,
                    "cursorPosition": {"x": 100.0, "y": 100.0},
                }
            if cmd == "status":
                if not state_tracker["activated"]:
                    return {"ok": True, "wechatRunning": False, "windowCount": 0, "windows": []}
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "wechatPID": 718,
                    "windowCount": 1,
                    "windows": [{"windowID": 447, "bounds": {"x": 0, "y": 0, "width": 585, "height": 640}}],
                }
            if cmd == "activate":
                state_tracker["activated"] = True
                return {
                    "ok": True,
                    "recoveryMethod": "dock_ax_press",
                    "wechatFrontmost": True,
                    "windowCount": 1,
                }
            if cmd == "capture-ocr":
                if "--out" in args:
                    out_p = Path(args[args.index("--out") + 1])
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(b"")
                return {
                    "ok": True,
                    "imageWidth": 1170,
                    "imageHeight": 1280,
                    "elements": [
                        {"text": "心安", "x": 120, "y": 68, "center": {"x": 120, "y": 68}},
                        {"text": "心安", "x": 380, "y": 24, "center": {"x": 380, "y": 24}},
                    ],
                }
            return {"ok": True}

        self.engine._run_native = _wake_native
        self.engine.inspector._run_native = _wake_native

        res = self.engine.monitor_once(auto_reply=False)
        self.assertTrue(res["ok"])
        self.assertTrue(state_tracker["activated"])

        # Confirm `window_auto_restored` event was logged
        events = self.engine.monitor.recent_events(limit=10)
        restored_evs = [e for e in events if e.get("event") == "window_auto_restored"]
        self.assertEqual(len(restored_evs), 1)
        self.assertEqual(restored_evs[0]["recoveryMethod"], "dock_ax_press")

        # Confirm consecutive identical poll_error events collapse cleanly with repeatCount
        self.engine.monitor._append_event("poll_error", {"error": "No visible WeChat main window."})
        self.engine.monitor._append_event("poll_error", {"error": "No visible WeChat main window."})
        self.engine.monitor._append_event("poll_error", {"error": "No visible WeChat main window."})
        latest_events = self.engine.monitor.recent_events(limit=10)
        poll_errs = [e for e in latest_events if e.get("event") == "poll_error"]
        self.assertEqual(len(poll_errs), 1)
        self.assertEqual(poll_errs[0]["repeatCount"], 3)

    # 18. WeChat article export to Markdown (.md) + local image download & OCR crop fallback
    def test_18_wechat_article_exporter_markdown_and_images(self) -> None:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-article-export")

        def _make_png(width: int, height: int) -> bytes:
            raw_row = b"\x00" + (b"\xee\xf2\xf7" * width)
            compressed = zlib.compress(raw_row * height, level=1)

            def _chunk(tag: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
            return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")

        sample_img_png = _make_png(120, 80)
        captured_referers = []

        class _ArticleMockHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                port = self.server.server_address[1]
                if self.path.startswith("/s/demo"):
                    body = f"""<!doctype html><html><head>
                    <meta property="og:title" content="谷歌 Ultra AI 隐藏福利实测" />
                    </head><body>
                    <h1 id="activity-name">谷歌 Ultra AI 隐藏福利实测</h1>
                    <a id="js_name">KK的AI笔记</a>
                    <em id="publish_time">2026-11-10 18:34</em>
                    <div id="js_content">
                      <h2>一、核心功能拆解</h2>
                      <p>这是一段包含<strong>高能加粗</strong>的实测段落。</p>
                      <blockquote><p>重要提示：微信图片默认使用 data-src 懒加载。</p></blockquote>
                      <p><img data-src="http://127.0.0.1:{port}/mmbiz_png/demo/0?wx_fmt=png" alt="福利结构图" /></p>
                      <ul><li>支持 20TB 云空间</li><li>支持 Veo 视频生成</li></ul>
                    </div>
                    </body></html>""".encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/mmbiz_png/"):
                    captured_referers.append(self.headers.get("Referer", ""))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(sample_img_png)))
                    self.end_headers()
                    self.wfile.write(sample_img_png)
                else:
                    self.send_response(404)
                    self.end_headers()

        srv = HTTPServer(("127.0.0.1", 0), _ArticleMockHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        prev_loopback = self.engine.article_exporter.allow_loopback_urls
        self.engine.article_exporter.allow_loopback_urls = True
        try:
            port = srv.server_address[1]
            res1 = self.engine.export_article(
                url=f"http://127.0.0.1:{port}/s/demo",
                from_window=False,
                download_images=True,
            )
            self.assertTrue(res1["ok"])
            self.assertEqual(res1["mode"], "html_url")
            self.assertEqual(res1["title"], "谷歌 Ultra AI 隐藏福利实测")
            self.assertEqual(res1["author"], "KK的AI笔记")
            self.assertEqual(res1["downloaded_image_count"], 1)
            self.assertTrue(any("s/demo" in r or "mp.weixin.qq.com" in r for r in captured_referers))

            md_file = Path(res1["markdown_path"])
            img_file = Path(res1["assets_dir"]) / "img_001.png"
            self.assertTrue(md_file.is_file())
            self.assertTrue(img_file.is_file())
            md_text = md_file.read_text(encoding="utf-8")
            self.assertIn("## 一、核心功能拆解", md_text)
            self.assertIn("**高能加粗**", md_text)
            self.assertIn("![福利结构图](assets/img_001.png)", md_text)
            self.assertNotIn("mmbiz_png", md_text.split("---", 2)[-1])
        finally:
            self.engine.article_exporter.allow_loopback_urls = prev_loopback
            srv.shutdown()
            srv.server_close()

        # Also test live WeChat window scroll OCR + figure gap crop fallback
        window_png = _make_png(1029, 640)
        page_counter = {"n": 0}

        def _mock_article_native(args, timeout=15.0):
            cmd = args[0]
            if cmd in ("status", "activate"):
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "wechatFrontmost": True,
                    "windowCount": 1,
                    "windows": [
                        {"windowID": 447, "title": "微信", "bounds": {"x": 1409, "y": 378, "width": 1029, "height": 640}}
                    ],
                }
            if cmd == "scroll":
                return {"ok": True, "units": "pixel", "dy": -360}
            if cmd == "capture-ocr":
                out_idx = args.index("--out") + 1 if "--out" in args else -1
                if out_idx > 0:
                    out_p = Path(args[out_idx])
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_bytes(window_png)
                page_counter["n"] += 1
                if page_counter["n"] == 1:
                    elements = [
                        {"text": "谷歌 Ultra 隐藏功能测试", "bbox": {"x": 605, "y": 78, "width": 320, "height": 24}, "center": {"x": 765, "y": 90}},
                        {"text": "原创 潇然 2026年11月10日", "bbox": {"x": 605, "y": 148, "width": 260, "height": 18}, "center": {"x": 735, "y": 157}},
                        {"text": "第一段正文，介绍入口功能。", "bbox": {"x": 620, "y": 210, "width": 320, "height": 20}, "center": {"x": 780, "y": 220}},
                        # Vertical gap of 130px (y=230 -> y=360) triggers embedded figure crop!
                        {"text": "第二段紧跟在插图下方。", "bbox": {"x": 620, "y": 360, "width": 320, "height": 20}, "center": {"x": 780, "y": 370}},
                    ]
                else:
                    elements = [
                        {"text": "第三段：第二页滚动追加内容。", "bbox": {"x": 620, "y": 140, "width": 320, "height": 20}, "center": {"x": 780, "y": 150}},
                    ]
                return {"ok": True, "imageWidth": 1029, "imageHeight": 640, "elements": elements}
            return {"ok": True}

        self.engine._run_native = _mock_article_native
        self.engine.inspector._run_native = _mock_article_native

        res2 = self.engine.export_article(
            from_window=True,
            max_scroll_pages=2,
            try_copy_link=False,
            download_images=True,
        )
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["mode"], "window_ocr_scroll")
        self.assertEqual(res2["pages_captured"], 2)
        md2 = Path(res2["markdown_path"]).read_text(encoding="utf-8")
        self.assertIn("谷歌 Ultra 隐藏功能测试", md2)
        self.assertIn("第二段紧跟在插图下方。", md2)
        self.assertIn("第三段：第二页滚动追加内容。", md2)
        self.assertIn("![文章插图 p1-1](assets/fig_p01_01.png)", md2)
        self.assertTrue((Path(res2["assets_dir"]) / "fig_p01_01.png").is_file())
        self.assertTrue((Path(res2["assets_dir"]) / "page_01.png").is_file())

        listed = self.engine.list_exported_articles(limit=10)
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["count"], 2)

    # 19. Standardized WeChat UI Schema & Human Mouse/Keyboard Idle Cooldown Guard
    def test_19_wechat_ui_schema_and_human_activity_guard(self) -> None:
        from wechat_control.human_activity_guard import HumanActivityGuard

        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-ui-human-guard")
        self.engine.bind_contact("心安", role="friend", auto_reply_enabled=True)

        # 1) Standardized UI Schema & JSON Schema contract
        schema = self.engine.get_ui_schema()
        self.assertTrue(schema["ok"])
        self.assertGreaterEqual(schema["viewsCount"], 8)
        self.assertGreaterEqual(schema["regionsCount"], 10)
        self.assertGreaterEqual(schema["targetsCount"], 20)

        schema_file = PROJECT_ROOT / "schemas" / "wechat-ui-protocol.schema.json"
        self.assertTrue(schema_file.is_file())
        parsed_schema = json.loads(schema_file.read_text(encoding="utf-8"))
        self.assertEqual(parsed_schema["properties"]["protocolName"]["const"], "openbot-wechat-ui-protocol")

        clock = {"now": 1000.0}
        hid = {
            "anyInputIdleSeconds": 120.0,
            "mouseIdleSeconds": 120.0,
            "keyboardIdleSeconds": 120.0,
            "cursorPosition": {"x": 500.0, "y": 500.0},
        }

        def _fake_native(args, timeout=15.0):
            cmd = args[0]
            if cmd == "hid-idle":
                return {"ok": True, "hidIdle": dict(hid)}
            if cmd in ("status", "activate"):
                return {
                    "ok": True,
                    "wechatRunning": True,
                    "wechatFrontmost": True,
                    "currentChatTitle": "心安",
                    "hidIdle": dict(hid),
                    "windowCount": 1,
                    "windows": [
                        {"windowID": 447, "title": "微信", "bounds": {"x": 964, "y": 30, "width": 1439, "height": 1321}}
                    ],
                }
            if cmd == "capture-ocr":
                return {
                    "ok": True,
                    "imageWidth": 1439,
                    "imageHeight": 1321,
                    "elements": [
                        {"text": "搜索", "bbox": {"x": 90, "y": 20, "width": 40, "height": 18}, "center": {"x": 110, "y": 29}},
                        {"text": "心安", "bbox": {"x": 90, "y": 90, "width": 60, "height": 18}, "center": {"x": 120, "y": 99}},
                    ],
                }
            return {"ok": True}

        self.engine._run_native = _fake_native
        self.engine.inspector._run_native = _fake_native

        guard = HumanActivityGuard(
            state_path=self.tmp_path / "guard_test_state.json",
            hid_query_fn=lambda: {"hidIdle": dict(hid)},
            clock_fn=lambda: clock["now"],
            default_idle_resume_seconds=45.0,
            default_cooldown_seconds=45.0,
        )
        self.engine.human_guard = guard

        # Verify live UI state resolution & dry-run navigation
        ui_state = self.engine.inspect_ui_state(refresh_ocr=True)
        self.assertTrue(ui_state["ok"])
        self.assertEqual(ui_state["activeView"], "main_chat_split")
        nav_dry = self.engine.navigate_ui("menu.settings", dry_run=True)
        self.assertTrue(nav_dry["ok"])
        self.assertTrue(nav_dry["dryRun"])
        self.assertIsNotNone(nav_dry["resolved"]["screenPoint"])

        # 2) Stage 1: Detect human mouse/keyboard intervention -> immediate stop + cooldown
        hid.update({"anyInputIdleSeconds": 1.5, "mouseIdleSeconds": 1.5, "keyboardIdleSeconds": 10.0})
        g1 = self.engine.get_human_guard_status()
        self.assertFalse(g1["canOperate"])
        self.assertEqual(g1["status"], "human_active_cooldown")
        self.assertEqual(g1["interventionsDetected"], 1)

        # Monitor yields & deduplicates human_active_paused events without touching WeChat
        p1 = self.engine.monitor_once(auto_reply=False)
        p2 = self.engine.monitor_once(auto_reply=False)
        self.assertTrue(p1["pausedByHumanGuard"])
        self.assertTrue(p2["pausedByHumanGuard"])
        events = self.engine.monitor.recent_events(limit=10)
        paused_evs = [e for e in events if e.get("event") == "human_active_paused"]
        self.assertEqual(len(paused_evs), 1)
        self.assertEqual(paused_evs[0]["repeatCount"], 2)

        # Live UI click blocked while human is active
        nav_blocked = self.engine.navigate_ui("nav.contacts", dry_run=False)
        self.assertFalse(nav_blocked["ok"])
        self.assertTrue(nav_blocked["blockedByHumanGuard"])

        # 3) Stage 2: Cooldown window held at t + 20s even without further input
        clock["now"] = 1020.0
        hid.update({"anyInputIdleSeconds": 21.5, "mouseIdleSeconds": 21.5, "keyboardIdleSeconds": 30.0})
        g2 = self.engine.get_human_guard_status()
        self.assertFalse(g2["canOperate"])
        self.assertGreater(g2["remainingCooldownSeconds"], 20.0)

        # 4) Stage 3: Resume cleanly after idle >= 45s and cooldown expired
        clock["now"] = 1046.0
        hid.update({"anyInputIdleSeconds": 47.5, "mouseIdleSeconds": 47.5, "keyboardIdleSeconds": 56.0})
        g3 = self.engine.get_human_guard_status()
        self.assertTrue(g3["canOperate"])
        self.assertEqual(g3["status"], "idle_ready")

        p3 = self.engine.monitor_once(auto_reply=False)
        self.assertFalse(p3.get("pausedByHumanGuard", False))
        events_after = self.engine.monitor.recent_events(limit=10)
        self.assertTrue(any(e.get("event") == "human_idle_resumed" for e in events_after))

        # 5) Self-RPA cursor exemption vs human cursor drift (>18px)
        clock["now"] = 1100.0
        guard.record_rpa_action(action="click", cursor_x=400.0, cursor_y=300.0)
        clock["now"] = 1100.2
        hid.update({
            "anyInputIdleSeconds": 0.2,
            "mouseIdleSeconds": 0.2,
            "keyboardIdleSeconds": 80.0,
            "cursorPosition": {"x": 402.0, "y": 301.0},
        })
        self.assertTrue(guard.check_can_operate()["canOperate"])

        # Human drags cursor far away from RPA target -> trips guard immediately
        hid["cursorPosition"] = {"x": 460.0, "y": 350.0}
        drifted = guard.check_can_operate()
        self.assertFalse(drifted["canOperate"])
        self.assertIn("mouse_moved_delta", drifted["triggerReason"])

    def test_20_owner_and_friend_soul_memory_profiler_and_bridge(self):
        self.engine.auth_grant(["*"])
        self.engine.bind_contact(
            "心安",
            role="friend",
            ai_persona="warm-friend",
            special_care=True,
            care_level="special_care",
        )

        # Create a WeChatBridge transcript with explicit self (我) and peer (心安) utterances
        bridge_txt = self.tmp_path / "心安_聊天记录.txt"
        bridge_txt.write_text(
            "·心安\n"
            "2026年11月15日 08:40\n"
            "微信号：zhhao_1995 你好呀，咱们周二早上一起测 OpenBot 和 StaffDeck 吗？\n"
            "·我\n"
            "2026年11月15日 08:42\n"
            "哈哈没问题！我刚把 安心的AI工作室 的记忆库和防抢鼠标守卫都接上啦～\n"
            "·我\n"
            "2026年11月15日 08:43\n"
            "收到，等下顺便看看 YoBot 控制端。\n",
            encoding="utf-8",
        )
        ingested = self.engine.import_bridge_to_soul(bridge_txt, contact_name="心安", owner_sender="我")
        self.assertTrue(ingested["ok"])
        self.assertEqual(ingested["selfCount"], 2)
        self.assertEqual(ingested["peerCount"], 1)

        # Add an explicit episodic memory note
        added = self.engine.add_soul_memory(
            "心安",
            "约定每周二早晨 08:40 运行定时 AI 测试问候",
            category="event",
            time_marker="每周二 08:40",
        )
        self.assertTrue(added["ok"])

        soul = self.engine.get_soul_profiles(target="心安")
        self.assertTrue(soul["ok"])
        owner = soul["ownerProfile"]
        self.assertEqual(owner["wechatIdHint"], "zhhao_1995")
        self.assertEqual(owner["organizationHint"], "安心的AI工作室")
        self.assertTrue(len(owner["personalityTraits"]) >= 3)
        self.assertTrue(len(owner["roleSwitchingMatrix"]) >= 1)

        cp = soul["contactProfiles"][0]
        mems = cp["memories"]
        self.assertGreaterEqual(mems["totalMemories"], 3)
        all_mem_text = " ".join(
            m["content"] for m in (mems["facts"] + mems["episodicEvents"] + mems["sharedContext"])
        )
        self.assertIn("定时 AI 测试问候", all_mem_text)

        # Verify owner-digital-twin persona is registered & generates memory-backed reply
        twin_reply = self.engine.preview_smart_reply(
            "心安",
            "在吗，能回复我吗？",
            persona_override="owner-digital-twin",
            use_llm=False,
        )
        self.assertTrue(twin_reply["ok"])
        self.assertEqual(twin_reply["persona"]["id"], "owner-digital-twin")
        self.assertTrue(twin_reply["basis"]["ownerTwinActive"])
        self.assertGreaterEqual(len(twin_reply["memoryRefs"]), 1)

    def test_21_benchmark_suite_and_mcp_soul_tools(self):
        self.engine.auth_grant(["*"])
        # Mock native hid-idle cleanly so benchmark doesn't touch live GUI
        self.engine._run_native = lambda args, timeout=15.0: (
            {
                "ok": True,
                "hidIdle": {
                    "anyInputIdleSeconds": 65.0,
                    "mouseIdleSeconds": 65.0,
                    "keyboardIdleSeconds": 70.0,
                    "cursorPosition": {"x": 320.0, "y": 240.0},
                },
            }
            if args and args[0] == "hid-idle"
            else {"ok": True}
        )
        # Put a stub binary if missing in temp environment check
        bench = self.engine.run_benchmark(include_tests=False)
        self.assertEqual(bench["totalModules"], 8)
        self.assertTrue(Path(bench["reportJsonPath"]).exists())
        self.assertTrue(Path(bench["reportMarkdownPath"]).exists())
        module_ids = {m["id"] for m in bench["benchmarks"]}
        self.assertIn("wechat_bridge_soul_and_memory", module_ids)
        self.assertIn("human_activity_guard", module_ids)
        self.assertIn("kimi_acceptance_status", module_ids)

        # Check MCP tools & HTTP endpoints
        mcp = WeChatMCPServer(self.engine)
        tools_resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
        self.assertIn("wechat_soul_profile", tool_names)
        self.assertIn("wechat_memory_add", tool_names)
        self.assertIn("wechat_run_benchmark", tool_names)

        # Verify web console HTML contains the new Soul & Kimi Acceptance tab
        overview = self.engine.get_web_overview()
        self.assertIn("soulSummary", overview)
        self.assertIn("benchmarkSummary", overview)
        html = render_web_console_html()
        self.assertIn("tab-soul", html)
        self.assertIn("本我性格", html)
        self.assertIn("kimiAcceptanceBox", html)

    # 22. Official/Service Account Batch Articles, Channels Video Exporter, & Kimi/codexma Security Fixes
    def test_22_official_account_batch_channels_video_and_security_hardening(self) -> None:
        import struct
        import zlib
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from wechat_control.human_activity_guard import HumanActivityGuard
        from wechat_control.ui_schema import compute_layout_geometry

        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-batch-security")

        # Tiny 4x4 PNG helper
        def _png4() -> bytes:
            raw = b"".join(b"\x00" + (b"\x40\x80\xc0\xff" * 4) for _ in range(4))
            ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)

            def _ck(tag: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            return b"\x89PNG\r\n\x1a\n" + _ck(b"IHDR", ihdr) + _ck(b"IDAT", zlib.compress(raw)) + _ck(b"IEND", b"")

        png_bytes = _png4()
        raw_mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + (b"\xaa" * 64)
        xor_key = 0x0101010101010101
        xor_mp4 = bytes(b ^ 0x01 for b in raw_mp4)

        class _BatchMockHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_GET(self):  # noqa: N802
                host = self.headers.get("Host", "127.0.0.1")
                if self.path == "/album":
                    body = (
                        f'<html><head><title>OpenBot 服务号</title></head><body>'
                        f'<a href="http://{host}/s/art1">服务号深度文章一</a>'
                        f'<a href="http://{host}/s/art2">服务号深度文章二</a>'
                        f"</body></html>"
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path in ("/s/art1", "/s/art2"):
                    idx = "1" if self.path.endswith("1") else "2"
                    body = (
                        f'<html><body><h1 id="activity-name">服务号文章 {idx}</h1>'
                        f'<a id="js_name">OpenBot 服务号</a>'
                        f'<div id="js_content"><p>批量导出的正文第 {idx} 篇。</p>'
                        f'<img data-src="http://{host}/img/{idx}.png" alt="配图{idx}"/></div>'
                        f"</body></html>"
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith("/img/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(png_bytes)))
                    self.end_headers()
                    self.wfile.write(png_bytes)
                elif self.path == "/channels/v1.bin":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(xor_mp4)))
                    self.end_headers()
                    self.wfile.write(xor_mp4)
                else:
                    self.send_response(404)
                    self.end_headers()

        # (c) SSRF / unsafe URL rejection when default allow_loopback_urls=False
        self.assertFalse(self.engine.article_exporter.allow_loopback_urls)
        for blocked_url in (
            "http://127.0.0.1:80/s/ssrf",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
            "file:///etc/passwd",
        ):
            r_block = self.engine.export_article(url=blocked_url, from_window=False)
            self.assertFalse(r_block["ok"], msg=f"Should reject SSRF/unsafe URL: {blocked_url}")

        srv = HTTPServer(("127.0.0.1", 0), _BatchMockHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        prev_loopback = self.engine.article_exporter.allow_loopback_urls
        self.engine.article_exporter.allow_loopback_urls = True
        try:
            port = srv.server_address[1]
            # (a) Official/Service Account Batch Articles
            acc_res = self.engine.export_account_articles(
                account_name="OpenBot 服务号",
                album_url=f"http://127.0.0.1:{port}/album",
                download_images=True,
                max_articles=10,
            )
            self.assertTrue(acc_res["ok"])
            self.assertEqual(acc_res["exportedCount"], 2)
            self.assertTrue(Path(acc_res["indexMarkdownPath"]).is_file())
            self.assertTrue(Path(acc_res["catalogJsonPath"]).is_file())
            self.assertIn("服务号文章 1", Path(acc_res["indexMarkdownPath"]).read_text(encoding="utf-8"))
            acc_listed = self.engine.list_exported_accounts(limit=10)
            self.assertGreaterEqual(acc_listed["count"], 1)

            # (b) WeChat Channels Author All Videos (URL + XOR decode + cache scan)
            ch_cache = self.tmp_path / "channels_cache_mock"
            ch_cache.mkdir(parents=True, exist_ok=True)
            (ch_cache / "cached_clip_01.dat").write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"\xbb" * 32)
            ch_res = self.engine.export_channels_videos(
                author_name="极客频道",
                video_items=[
                    {
                        "title": "测试视频一号",
                        "url": f"http://127.0.0.1:{port}/channels/v1.bin",
                        "decode_key": hex(xor_key),
                    }
                ],
                cache_dir=str(ch_cache),
                download_media=True,
                max_videos=10,
            )
            self.assertTrue(ch_res["ok"])
            self.assertEqual(ch_res["exportedCount"], 2)
            self.assertTrue(Path(ch_res["indexMarkdownPath"]).is_file())
            self.assertTrue(Path(ch_res["catalogJsonPath"]).is_file())
            v_item = ch_res["videos"][0]
            saved_mp4 = Path(ch_res["bundleDir"]) / v_item["video_rel_path"]
            self.assertTrue(saved_mp4.is_file())
            self.assertEqual(saved_mp4.read_bytes()[4:8], b"ftyp")
            ch_listed = self.engine.list_exported_channels(limit=10)
            self.assertGreaterEqual(ch_listed["count"], 1)
        finally:
            self.engine.article_exporter.allow_loopback_urls = prev_loopback
            srv.shutdown()
            srv.server_close()

        # Verify list_exported_articles skips accounts/ and channels/ directories
        single_arts = self.engine.list_exported_articles(limit=50)["articles"]
        self.assertFalse(any(str(a.get("slug", "")) in ("accounts", "channels") for a in single_arts))

        # Check MCP tools & HTTP console expose new batch endpoints
        mcp = WeChatMCPServer(self.engine)
        tools_resp = mcp.handle_request({"jsonrpc": "2.0", "id": 99, "method": "tools/list"})
        tool_names = {tool["name"] for tool in tools_resp["result"]["tools"]}
        self.assertIn("wechat_export_account_articles", tool_names)
        self.assertIn("wechat_export_channels_videos", tool_names)
        html = render_web_console_html()
        self.assertIn("exportAccountBatch", html)
        self.assertIn("exportChannelsVideos", html)

        # (d) HumanActivityGuard fail-closed on missing HID & SecurityAgent frontmost popup
        guard = HumanActivityGuard(state_path=self.tmp_path / "guard_hardening.json")
        g_missing = guard.check_can_operate({"ok": False, "error": "hid_err"})
        self.assertFalse(g_missing["canOperate"])
        self.assertEqual(g_missing["status"], "hid_unavailable")
        g_sec = guard.check_can_operate(
            {
                "ok": True,
                "anyInputIdleSeconds": 999.0,
                "mouseIdleSeconds": 999.0,
                "keyboardIdleSeconds": 999.0,
                "cursorPosition": {"x": 100.0, "y": 100.0},
                "frontmostApp": "SecurityAgent (com.apple.SecurityAgent)",
            }
        )
        self.assertFalse(g_sec["canOperate"])
        self.assertEqual(g_sec["status"], "security_agent_paused")

        # (e) ui_schema no false-positive on "AI" chat message + soul_memory category & report file
        geo = compute_layout_geometry(
            {"x": 0, "y": 0, "width": 1000, "height": 700},
            [{"text": "AI", "x": 400, "y": 300}, {"text": "Gemini", "x": 420, "y": 330}],
        )
        self.assertFalse(geo["hasArticlePane"])
        mem_add = self.engine.add_soul_memory("心安", "喜欢早起喝黑咖啡", category="preference")
        self.assertTrue(mem_add["ok"])
        store_mems = self.engine.soul_profiler._load_store()["manualMemories"].get("心安") or []
        self.assertTrue(any(m.get("content") == "喜欢早起喝黑咖啡" and m.get("category") == "preference" for m in store_mems))
        rebuilt = self.engine.get_soul_profiles(rebuild=True)
        self.assertTrue(Path(rebuilt["reportJsonPath"]).is_file())

    def test_23_standalone_app_dsh_plugin_and_botstudio_bridge(self) -> None:
        # (a) Standalone native macOS .app bundle verification (--verify-headless)
        app_exe = PROJECT_ROOT / "dist" / "WeChat Bot.app" / "Contents" / "MacOS" / "wechat-studio-app"
        self.assertTrue(app_exe.is_file(), f"Missing standalone .app executable: {app_exe}")
        proc = subprocess.run(
            [str(app_exe), "--verify-headless"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15.0,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        app_info = json.loads(proc.stdout)
        self.assertTrue(app_info.get("ok"))
        self.assertEqual(app_info.get("appTitle"), "WeChat Bot")
        self.assertEqual(app_info.get("bundleId"), "com.openbot.wechat-bot")
        self.assertTrue(app_info.get("backendScriptExists"))

        # (b) Native DSH plugin manifest & catalog entry exist + compile via dsh2codex-node -> 4-Tab bundle
        dsh_doc = json.loads((PROJECT_ROOT / "dsh.plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(dsh_doc.get("schema"), "openbot.dsh-plugin/1")
        self.assertEqual(dsh_doc.get("id"), "dsh-plugin-wechat-ecosystem")
        self.assertEqual(dsh_doc.get("packageName"), "@dsh-market/wechat-ecosystem")
        self.assertGreaterEqual(len(dsh_doc.get("tools") or []), 8)
        self.assertGreaterEqual(len((dsh_doc.get("workbench") or {}).get("panels") or []), 3)

        self.engine.auth_grant(capabilities=READ_ONLY_CAPABILITIES)
        bundle_out = self.tmp_path / "botstudio_integration_bundle.json"
        exported = self.engine.export_botstudio_integration_bundle(out_path=str(bundle_out))
        self.assertTrue(exported.get("ok"))
        self.assertEqual(exported.get("engine"), "dsh2codex-node")
        self.assertTrue(exported.get("dsh2codexVerified"))
        self.assertTrue(exported.get("catalogAdaptedOk"))
        self.assertEqual(exported.get("fourTabPages"), ["overview", "console", "workflows", "page_spec"])
        self.assertTrue(bundle_out.is_file())
        bundle_json = json.loads(bundle_out.read_text(encoding="utf-8"))
        self.assertEqual(bundle_json.get("schema"), "openbot.botstudio-integration-bundle/1")
        self.assertEqual(
            (bundle_json.get("workbenchPlugin") or {}).get("schema"),
            "openbot.codex-workbench-plugin/1",
        )
        self.assertEqual(
            (bundle_json.get("workbenchPreset") or {}).get("schema"),
            "openbot.codex-workbench-preset/1",
        )

        # (c) Standalone dsh2codex page files + MCP tool + Web UI Tab 5 + Fail-Closed API check
        page_html = PROJECT_ROOT / "dist" / "botstudio-pages" / "wechat-ecosystem" / "index.html"
        self.assertTrue(page_html.is_file())
        mcp = WeChatMCPServer(self.engine)
        list_resp = mcp.handle_request({"jsonrpc": "2.0", "id": 230, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in list_resp["result"]["tools"]}
        self.assertIn("wechat_botstudio_bridge", tool_names)

        bridge_call = mcp.handle_request({
            "jsonrpc": "2.0",
            "id": 231,
            "method": "tools/call",
            "params": {"name": "wechat_botstudio_bridge", "arguments": {"action": "status"}},
        })
        bridge_payload = json.loads(bridge_call["result"]["content"][0]["text"])
        self.assertTrue(bridge_payload["standalone"]["appReady"])
        self.assertTrue(bridge_payload["dshPlugin"]["dsh2codexVerified"])
        self.assertEqual(bridge_payload["botStudio"]["fourTabPages"], ["overview", "console", "workflows", "page_spec"])

        ui_html = render_web_console_html()
        self.assertIn("standaloneSoftwareBody", ui_html)
        self.assertIn("dshBridgeMetrics", ui_html)
        self.assertIn("compileAndExportBotStudioBundle", ui_html)

        # Fail-Closed check when authorization is revoked
        self.engine.auth_revoke(reason="test_23")
        with self.assertRaises(StudioPluginUnauthorizedError):
            self.engine.get_botstudio_bridge_status()


if __name__ == "__main__":
    unittest.main()
