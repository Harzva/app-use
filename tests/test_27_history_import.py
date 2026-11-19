"""历史聊天导入：扫描/勾选导入/一键全部 + HTTP 端点 + 首页面板标记。"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.auth_gate import ALL_CAPABILITIES  # noqa: E402
from wechat_control.safety import normalize_chat_name  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import create_http_server  # noqa: E402
from wechat_control.web_console import render_web_console_html  # noqa: E402


def _offline_model_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in default unit test setup")


def _write_history(directory: Path, target: str, suffix: str, count: int) -> Path:
    path = directory / f"{target}_{suffix}_history.json"
    path.write_text(json.dumps({
        "ok": True,
        "target": target,
        "matchedTitle": target,
        "recordCount": count,
        "observedAt": "2026-11-15T03:57:34.512272+00:00",
        "records": [{"text": f"消息{i}", "kind": "message", "direction": "peer"} for i in range(count)],
    }, ensure_ascii=False), encoding="utf-8")
    return path


class HistoryImportTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.source_dir = self.tmp_path / "old-contacts"
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="unit-test-history")
        self._h1 = _write_history(self.source_dir, "心安", "1a882b", 12)
        self._h2 = _write_history(self.source_dir, "openbot", "9b386b", 25)
        self._h3 = _write_history(self.source_dir, "测试好友丙", "c33ccd", 7)

    def tearDown(self) -> None:
        try:
            self.engine.stop_hosting()
        except Exception:
            pass
        self.tmpdir.cleanup()

    def test_list_history_sources(self) -> None:
        res = self.engine.list_history_sources(source_dir=str(self.source_dir))
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["sources"]), 3)
        by_target = {s["target"]: s for s in res["sources"]}
        self.assertEqual(by_target["心安"]["recordCount"], 12)
        self.assertFalse(by_target["心安"]["alreadyImported"])

    def test_import_all_copies_files_and_updates_profiles(self) -> None:
        res = self.engine.import_histories(source_dir=str(self.source_dir), import_all=True)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["imported"]), 3)
        dest = self.engine.inspector.reports_dir / "contacts"
        self.assertTrue((dest / self._h1.name).exists())
        self.assertTrue((dest / self._h2.name).exists())
        self.assertTrue((dest / self._h3.name).exists())
        # 画像里出现导入的联系人（含未绑定的历史联系人）
        prof = self.engine.profile_contacts() or {}
        targets = {p.get("target"): p for p in prof.get("profiles", [])}
        for t in ("心安", "openbot", "测试好友丙"):
            self.assertIn(t, targets)
            self.assertGreater(int(targets[t].get("messageCount") or 0), 0)
        # 再次扫描应标记 alreadyImported
        listing = self.engine.list_history_sources(source_dir=str(self.source_dir))
        for s in listing["sources"]:
            self.assertTrue(s["alreadyImported"])

    def test_import_selected_only(self) -> None:
        res = self.engine.import_histories(source_dir=str(self.source_dir), targets=["心安"])
        self.assertTrue(res["ok"])
        self.assertEqual([i["target"] for i in res["imported"]], ["心安"])
        dest = self.engine.inspector.reports_dir / "contacts"
        self.assertTrue((dest / self._h1.name).exists())
        self.assertFalse((dest / self._h2.name).exists())
        # 未知目标 → 报错
        res2 = self.engine.import_histories(source_dir=str(self.source_dir), targets=["不存在的好友"])
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["error"], "HISTORY_TARGETS_NOT_FOUND")

    def test_hosting_merge_still_works_after_import(self) -> None:
        """导入历史后，托管开启依然能 merge 绑定而不破坏画像。"""
        self.engine.import_histories(source_dir=str(self.source_dir), import_all=True)
        res = self.engine.start_hosting(["心安"])
        self.assertTrue(res["ok"])
        binding = self.engine.bindings.get_binding("心安")
        self.assertTrue(binding["autoReplyEnabled"])
        friends = self.engine.hosting_friends()
        by_target = {f["target"]: f for f in friends["friends"]}
        self.assertTrue(by_target["心安"]["autoReplyEnabled"])

    def test_hosting_auto_resume_after_engine_restart(self) -> None:
        """崩溃重启自动恢复托管；正常停止不恢复；授权撤销 fail-closed。"""
        # 模拟"崩溃"：开启托管后直接掐掉线程（不走 stop，磁盘保持 enabled=true）
        engine1 = self.engine
        engine1.start_hosting(["测试好友甲"])
        engine1.hosting_manager._stop.set()
        disk = json.loads((self.tmp_path / "reports" / "hosting_state.json").read_text(encoding="utf-8"))
        self.assertTrue(disk["enabled"])
        self.assertEqual(disk["targets"], ["测试好友甲"])

        # 新引擎实例（同目录）构造期间应自动恢复托管
        engine2 = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb2.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        st2 = engine2.hosting_manager.status()
        self.assertTrue(st2["running"], "重启后托管应自动恢复")
        self.assertEqual(st2["targets"], ["测试好友甲"])

        # 正常 stop 后，再新起的引擎不应恢复
        engine2.stop_hosting()
        engine3 = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb3.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        self.assertFalse(engine3.hosting_manager.status()["enabled"])

        # 授权撤销 fail-closed：把磁盘状态改回 enabled，但撤销授权 → 不恢复
        disk_path = self.tmp_path / "reports" / "hosting_state.json"
        disk = json.loads(disk_path.read_text(encoding="utf-8"))
        disk["enabled"] = True
        disk["targets"] = ["测试好友甲"]
        disk_path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
        engine3.auth_revoke(reason="test fail-closed")
        engine4 = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit4.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb4.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.tmp_path / "reports",
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群", "测试私域运营群"],
        )
        self.assertFalse(engine4.hosting_manager.status()["running"])
        self.assertFalse(engine4.hosting_manager.status()["enabled"])

    def test_import_chatlog_file_to_histories(self) -> None:
        """聊天记录 txt（微信4.x格式）解析后直接写进联系人历史，方向按号主昵称判定。"""
        log_path = self.tmp_path / "与心安的聊天.txt"
        log_path.write_text(
            "·心安\n2026年11月15日 10:30\n在吗？\n"
            "·号主本人\n2026年11月15日 10:31\n在的，有什么事？\n"
            "·心安\n2026年11月15日 10:32\n想咨询下你们的产品\n",
            encoding="utf-8",
        )
        res = self.engine.import_chatlog_to_histories(
            source_path=str(log_path), target="心安", owner_name="号主本人",
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["imported"], 3)
        self.assertIn("心安", res.get("participants") or [])
        dest = self.engine.inspector.reports_dir / "contacts"
        files = list(dest.glob("心安_*_history.json"))
        self.assertEqual(len(files), 1)
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(doc["recordCount"], 3)
        dirs = [(r["direction"], r["text"]) for r in doc["records"]]
        self.assertIn(("peer", "在吗？"), dirs)
        self.assertIn(("self", "在的，有什么事？"), dirs)
        self.assertIn(("peer", "想咨询下你们的产品"), dirs)
        # 画像里出现该联系人且消息数>0
        prof = self.engine.profile_contacts() or {}
        targets = {p.get("target"): p for p in prof.get("profiles", [])}
        self.assertIn("心安", targets)
        self.assertGreater(int(targets["心安"].get("messageCount") or 0), 0)
        # 缺 target → 拒绝
        res2 = self.engine.import_chatlog_to_histories(source_path=str(log_path), target="")
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["error"], "CHATLOG_TARGET_REQUIRED")

    def test_import_chatlog_file_http_endpoint_and_markers(self) -> None:
        log_path = self.tmp_path / "聊天导出.txt"
        log_path.write_text(
            "·测试好友丙\n2026年11月15日 09:00\n你好\n"
            "·号主本人\n2026年11月15日 09:01\n你好呀\n",
            encoding="utf-8",
        )
        srv = create_http_server(self.engine, "127.0.0.1", 0)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def _req(path: str, payload: dict | None = None):
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            req = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as err:
                return err.code, err.read()

        try:
            st, raw = _req("/")
            self.assertEqual(st, 200)
            html = raw.decode("utf-8")
            self.assertIn("从聊天记录文件导入", html)
            self.assertIn("/api/import-chatlog-file", html)
            self.assertIn("importChatlogFile", html)

            st, raw = _req("/api/import-chatlog-file", {
                "source_path": str(log_path),
                "target": "测试好友丙",
                "owner_name": "号主本人",
            })
            self.assertEqual(st, 200)
            doc = json.loads(raw.decode("utf-8"))
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["imported"], 2)
            self.assertEqual(doc["target"], "测试好友丙")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_recent_history_thread_and_reply_context_injection(self) -> None:
        """历史往来应注入自动回复上下文：recent_history_thread + historyThreadSnippet。"""
        self.engine.import_histories(source_dir=str(self.source_dir), import_all=True)
        snippet = self.engine.recent_history_thread("心安", limit=6)
        self.assertIn("对方", snippet)
        self.assertIn("消息", snippet)
        # 无历史的联系人 → 空片段
        self.assertEqual(self.engine.recent_history_thread("从没聊过的陌生人"), "")

        # generate_smart_reply 消费 historyThreadSnippet（LLM prompt 含历史往来）
        captured = {}

        def _fake_llm(messages, model_id=None, contact_name=None):
            captured["system"] = messages[0]["content"] if messages else ""
            captured["user"] = messages[1]["content"] if len(messages) > 1 else ""
            return {"ok": True, "replyText": "好的", "latencyMs": 5, "modelId": "test", "providerId": "test"}

        self.engine.models = type("M", (), {
            "is_llm_enabled": lambda self: True,
            "generate_chat_reply": staticmethod(_fake_llm),
            "get_summary": lambda self, refresh=False: {},
        })()
        self.engine.personas.model_hub = self.engine.models
        res = self.engine.personas.generate_smart_reply(
            "心安", "在吗",
            knowledge_store=self.engine.knowledge,
            binding=self.engine.bindings.get_binding("心安"),
            memory_context={"historyThreadSnippet": snippet},
        )
        self.assertTrue(res.get("replyText"))
        self.assertIn("来自聊天记录", captured.get("user", ""))
        self.assertIn("对方", captured.get("user", ""))

    def test_append_media_note_persists_and_injects(self) -> None:
        """链接/图片深读摘要持久化进历史，并在往来上下文注入时带上。"""
        self.engine.import_histories(source_dir=str(self.source_dir), targets=["心安"])
        ok = self.engine.append_media_note("心安", "[链接深读:WaveBot官网] 官网介绍产品与案例")
        self.assertTrue(ok)
        # 再追加一条应落在同一个文件（最新修改的历史文件）
        self.assertTrue(self.engine.append_media_note("心安", "[图片识别:产品截图] 页面展示价格表"))
        snippet = self.engine.recent_history_thread("心安", limit=10)
        self.assertIn("[链接深读:WaveBot官网]", snippet)
        self.assertIn("[图片识别:产品截图]", snippet)
        # 空参数拒绝
        self.assertFalse(self.engine.append_media_note("心安", ""))
        self.assertFalse(self.engine.append_media_note("", "note"))

    def test_sync_hosting_histories_appends_from_events(self) -> None:
        """托管循环观察到的往来消息应回写进联系人历史（去重）。"""
        self.engine.monitor._append_event("auto_reply_sent", {
            "target": "心安",
            "incomingText": "在吗",
            "replyText": "在的，请问有什么事？",
            "careLevel": "normal",
            "specialCare": False,
            "personaId": "warm-friend",
        })
        res = self.engine.sync_hosting_histories()
        self.assertTrue(res["ok"])
        self.assertEqual(res["appended"], 2)  # peer 来信 + self 回复
        dest = self.engine.inspector.reports_dir / "contacts"
        files = list(dest.glob("心安_*_history.json"))
        self.assertEqual(len(files), 1)
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(doc["recordCount"], 2)
        texts = [(r["direction"], r["text"]) for r in doc["records"]]
        self.assertIn(("peer", "在吗"), texts)
        self.assertIn(("self", "在的，请问有什么事？"), texts)
        # 二次同步：同样的消息不重复入库
        res2 = self.engine.sync_hosting_histories()
        self.assertEqual(res2["appended"], 0)

    def test_history_import_http_endpoints_and_homepage_markers(self) -> None:
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
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as err:
                return err.code, err.read()

        try:
            st, raw = _req("/")
            self.assertEqual(st, 200)
            html = raw.decode("utf-8")
            self.assertIn("导入历史聊天记录", html)
            self.assertIn("/api/history-import", html)
            self.assertIn("importHistorySources", html)
            # 启动权限引导面板（影刀式）
            self.assertIn("系统权限检查", html)
            self.assertIn("permPanel", html)
            self.assertIn("loadPermissions", html)
            self.assertIn("x-apple.systempreferences", html)

            st, raw = _req("/api/permissions")
            self.assertEqual(st, 200)
            perm = json.loads(raw.decode("utf-8"))
            self.assertTrue(perm["ok"])
            ids = {item["id"] for item in perm["items"]}
            self.assertEqual(ids, {"accessibility", "post_event", "screen_capture"})
            self.assertEqual(perm["allGranted"], all(item["granted"] for item in perm["items"]))

            st, raw = _req(f"/api/history-import?source_dir={self.source_dir}")
            self.assertEqual(st, 200)
            doc = json.loads(raw.decode("utf-8"))
            self.assertTrue(doc["ok"])
            self.assertEqual(len(doc["sources"]), 3)

            st, raw = _req("/api/history-import", {
                "source_dir": str(self.source_dir),
                "targets": ["心安", "测试好友丙"],
            })
            self.assertEqual(st, 200)
            doc = json.loads(raw.decode("utf-8"))
            self.assertTrue(doc["ok"])
            self.assertEqual(sorted(i["target"] for i in doc["imported"]), ["心安", "测试好友丙"])

            st, raw = _req("/api/history-import", {"source_dir": str(self.source_dir), "import_all": True})
            self.assertEqual(st, 200)
            self.assertEqual(len(json.loads(raw.decode("utf-8"))["imported"]), 3)

            # 最近会话来信兜底：overview.latestInbound 应含导入历史里每位联系人的最近 peer 来信
            st, raw = _req("/api/overview")
            self.assertEqual(st, 200)
            ov = json.loads(raw.decode("utf-8"))
            self.assertIn("latestInbound", ov)
            inbound_keys = set(ov["latestInbound"].keys())
            self.assertIn(normalize_chat_name("心安").casefold(), inbound_keys)
            # 最近往来上下文：overview.recentThreads 含导入联系人的消息列表（时间正序）
            self.assertIn("recentThreads", ov)
            thread_key = normalize_chat_name("心安").casefold()
            self.assertIn(thread_key, ov["recentThreads"])
            msgs = ov["recentThreads"][thread_key]["messages"]
            self.assertGreater(len(msgs), 0)
            self.assertEqual(msgs[-1]["direction"], "peer")  # 时间正序：最后一条是最新
            # OCR 置信度透传（低置信度由前端标注，防误信误读文本）
            self.assertTrue(any("confidence" in m for m in msgs))
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
