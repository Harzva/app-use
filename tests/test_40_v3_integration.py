"""Integration tests for v3 Zero-FDE onboarding, self-training, supervisor sandbox, and HTTP APIs."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from wechat_control import (
    CorpusDiscoveryEngine,
    SelfTrainingPlaybookEngine,
    SupervisorEvalEngine,
    TenantProfileStore,
    WeChatControlEngine,
    create_http_server,
)
from wechat_control.auth_gate import ALL_CAPABILITIES
from wechat_control.cli import build_parser
from wechat_control.engine import _migrate_legacy_runtime_data
from wechat_control.tenant_profile import CUSTOMER_BUILD_MARKER

REPO_ROOT = Path(__file__).resolve().parent.parent


def _http_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=5.0) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


class V3ZeroFDEIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_customer_bundle(self) -> Path:
        bundle = self.root / "bundle_res"
        (bundle / "config_templates" / "sales_packs").mkdir(parents=True, exist_ok=True)
        (bundle / "docs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            REPO_ROOT / "config_templates" / "sales_packs" / "general_sales.json",
            bundle / "config_templates" / "sales_packs" / "general_sales.json",
        )
        shutil.copy2(
            REPO_ROOT / "docs" / "USER_GUIDE.md",
            bundle / "docs" / "USER_GUIDE.md",
        )
        if (REPO_ROOT / "docs" / "user-guide.html").is_file():
            shutil.copy2(
                REPO_ROOT / "docs" / "user-guide.html",
                bundle / "docs" / "user-guide.html",
            )
        (bundle / CUSTOMER_BUILD_MARKER).write_text("clean\n", encoding="utf-8")
        return bundle

    def _make_engine(self, *, customer_bundle: bool = False, name: str = "app") -> WeChatControlEngine:
        base = self.root / name
        cfg = base / "config"
        logs = base / "logs"
        cfg.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        bundle = self._make_customer_bundle() if customer_bundle else REPO_ROOT
        return WeChatControlEngine(
            audit_log_path=logs / "audit.jsonl",
            auth_file_path=cfg / "studio_auth.json",
            bindings_file_path=cfg / "bound_contacts.json",
            models_config_path=cfg / "model_providers.json",
            knowledge_db_path=cfg / "wechat_knowledge.sqlite",
            personas_file_path=cfg / "personas.json",
            monitor_state_path=logs / "monitor_state.json",
            monitor_events_path=logs / "monitor_events.jsonl",
            snapshots_dir=logs / "snapshots",
            reports_dir=logs,
            bundle_root=bundle,
        )

    def test_01_customer_mode_isolation_and_migration_skip(self) -> None:
        bundle = self._make_customer_bundle()
        # Even if repo_root.txt or bundle config exists, customer_build.marker skips legacy migration
        (bundle / "config").mkdir(parents=True, exist_ok=True)
        (bundle / "config" / "bound_contacts.json").write_text('{"bindings":[{"target":"心安"}]}', encoding="utf-8")
        target_root = self.root / "app_support"
        mig = _migrate_legacy_runtime_data(bundle, target_root)
        self.assertFalse(mig["migrated"])
        self.assertEqual(mig["reason"], "customer_build_marker")
        self.assertFalse((target_root / "config" / "bound_contacts.json").exists())

        engine = self._make_engine(customer_bundle=True, name="cust_iso")
        self.assertIsInstance(engine.tenant, TenantProfileStore)
        self.assertIsInstance(engine.corpus_discovery, CorpusDiscoveryEngine)
        self.assertIsInstance(engine.playbook_trainer, SelfTrainingPlaybookEngine)
        self.assertIsInstance(engine.supervisor_eval, SupervisorEvalEngine)
        self.assertTrue(engine.tenant.is_customer_mode())

        kb = engine.knowledge.list_entries(include_drafts=False, limit=500)
        ids = [e["id"] for e in kb["entries"]]
        self.assertFalse(any(eid.startswith("seed-") for eid in ids))
        self.assertGreaterEqual(len(ids), 14)
        kb_blob = json.dumps(kb, ensure_ascii=False)
        for leaked in ("zhhao_1995", "郝泽华", "安心的AI工作室", "WaveBot"):
            self.assertNotIn(leaked, kb_blob)

        # Soul profiler in customer mode skips personal contact branches & personal fallbacks
        engine.soul_profiler.ingest_bridge_archive(
            type(
                "B",
                (),
                {
                    "title": "心安",
                    "source_path": "x.txt",
                    "records": [
                        type("R", (), {"sender": "心安", "content": "您好，想了解一下你们的产品方案", "timestamp": "09:00"})(),
                        type("R", (), {"sender": "我", "content": "您好，请问您目前团队大概多少人？", "timestamp": "09:02"})(),
                    ],
                },
            )(),
            contact_name="心安",
            owner_sender="我",
        )
        soul = engine.soul_profiler.get_profiles()
        soul_blob = json.dumps(soul, ensure_ascii=False)
        for leaked in ("zhhao_1995", "郝泽华", "安心的AI工作室", "WaveBot", "OpenBot", "StaffDeck", "YoBot"):
            self.assertNotIn(leaked, soul_blob)

    def test_02_onboarding_discover_train_approve_and_search_flow(self) -> None:
        engine = self._make_engine(customer_bundle=True, name="cust_train")
        engine.auth_grant(ALL_CAPABILITIES, authorized_by="test")

        onb = engine.setup_tenant_onboarding(
            owner_name="陈经理",
            business_name="星河定制家居",
            product_summary="专注全屋环保实木定制与免费上门量尺设计",
            industry_pack="general_sales",
            owner_aliases=["Kevin-华东"],
            test_contacts=["内部测试号"],
        )
        self.assertTrue(onb["ok"])
        self.assertEqual(onb["profile"]["ownerName"], "陈经理")
        self.assertTrue(onb["profile"]["onboardingCompleted"])
        self.assertEqual(onb["salesPackApplied"]["packId"], "general_sales")

        # Create exported archive with safe Q&A + risk-gated price Q&A + PII
        arch_dir = self.root / "exports"
        arch_dir.mkdir(parents=True, exist_ok=True)
        chat_txt = arch_dir / "客户王总_聊天记录.txt"
        chat_txt.write_text(
            "·客户王总\n"
            "2026年11月20日 10:00\n"
            "请问环保实木定制包含上门量尺吗？我手机号 13800138000\n"
            "·陈经理\n"
            "2026年11月20日 10:01\n"
            "您好，我们标准服务都包含免费预约量尺和三维出图，先按您的户型出方案再沟通。\n"
            "·客户王总\n"
            "2026年11月20日 10:03\n"
            "太好了，大概怎么预约？\n"
            "·客户王总\n"
            "2026年11月20日 11:30\n"
            "环保实木定制全屋套餐多少钱，能打8折吗？\n"
            "·陈经理\n"
            "2026年11月20日 11:32\n"
            "标准基础套餐 ¥29800 元起，老客户推荐可申请 8 折优惠。\n"
            "·客户王总\n"
            "2026年11月20日 11:33\n"
            "好的发资料看看\n",
            encoding="utf-8",
        )

        disc = engine.discover_training_corpus(search_dirs=[arch_dir], include_live_sessions=False)
        self.assertTrue(disc["ok"])
        self.assertEqual(disc["archiveCount"], 1)

        train = engine.run_self_training(
            archive_paths=[chat_txt],
            use_llm=False,
            auto_publish_safe=True,
        )
        self.assertTrue(train["ok"])
        self.assertGreaterEqual(len(train["draftIds"]), 1)
        # PII must be redacted
        entries_json = json.dumps(train["entries"], ensure_ascii=False)
        self.assertNotIn("13800138000", entries_json)

        # Drafts are not yet searchable until approved
        pre_search = engine.kb_search("环保实木定制全屋套餐", limit=10)
        pre_ids = {e["id"] for e in pre_search["entries"]}
        for did in train["draftIds"]:
            self.assertNotIn(did, pre_ids)

        app_res = engine.approve_training_drafts(train["draftIds"])
        self.assertTrue(app_res["ok"])
        self.assertEqual(len(app_res["publishedIds"]), len(train["draftIds"]))

        post_search = engine.kb_search("环保实木定制全屋套餐", limit=10)
        post_ids = {e["id"] for e in post_search["entries"]}
        self.assertTrue(any(did in post_ids for did in train["draftIds"]))

    def test_03_test_contact_crm_exclusion_and_monitor_hashtag_guards(self) -> None:
        engine = self._make_engine(customer_bundle=True, name="cust_mon")
        engine.auth_grant(ALL_CAPABILITIES, authorized_by="test")
        engine.setup_tenant_onboarding(owner_name="林顾问", business_name="云帆科技", product_summary="企业协同方案")

        # Mark test contact and bind both test contact and real customer
        tc_res = engine.set_test_contact("测试小号", enabled=True, note="内部质检")
        self.assertTrue(tc_res["ok"])
        engine.bind_contact("测试小号", role="test", ai_persona="wecom-kf-pro", auto_reply_enabled=True)
        engine.bind_contact("张总", role="customer", ai_persona="wecom-kf-pro", auto_reply_enabled=True)

        # Verify SalesCRM excludes test contact and reports excludedTestContactsCount
        crm = engine.sales_crm.get_overview(auto_sync=True)
        ranked_names = [p["displayName"] for p in crm["rankings"]]
        self.assertIn("张总", ranked_names)
        self.assertNotIn("测试小号", ranked_names)
        self.assertGreaterEqual(crm["summary"]["excludedTestContactsCount"], 1)

        # Hard outbound guard: normal customer CANNOT receive `#` directive
        blocked = engine.send_text("张总", "#评分 1 语气太硬", dry_run=True)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error_code"], "blocked_internal_hashtag_directive")

        # Test contact IS allowed dry_run `#` directive
        allowed = engine.send_text("测试小号", "#评分 1 语气太硬", dry_run=True)
        self.assertTrue(allowed["ok"])

        # Simulate realtime_monitor handling:
        # 1) Normal customer 张总 sending `#...` is NOT treated as supervisor directive
        # 2) Test contact 测试小号 sending normal message records turn + bypasses antiban gap
        # 3) Test contact 测试小号 sending `#别直接报底价，先问需求` triggers directive rewrite & ackMessage
        sent_messages: list[tuple[str, str]] = []

        def _fake_capture() -> dict:
            return {
                "ok": True,
                "bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
                "ocrPayload": {"elements": []},
                "snapshotPath": str(self.root / "snap.png"),
            }

        turn_plan = {
            "张总": [{"direction": "peer", "text": "#请问你们方案多少钱", "timeMarker": "10:00"}],
            "测试小号": [{"direction": "peer", "text": "你们报价是多少？", "timeMarker": "10:01"}],
        }

        def _fake_inspect(target, **kwargs):
            bubbles = turn_plan.get(target, [])
            return {
                "checked": True,
                "matchedTitle": target,
                "structured": {
                    "headerTitle": target,
                    "bubbles": bubbles,
                    "lastBubble": bubbles[-1] if bubbles else None,
                },
            }

        def _fake_send(target, text, **kwargs):
            sent_messages.append((target, text))
            return {"ok": True, "status": "sent", "target": target, "text": text}

        with patch.object(engine.monitor, "_capture_live_window", side_effect=_fake_capture), \
             patch.object(engine.monitor, "_inspect_target_bubbles", side_effect=_fake_inspect), \
             patch.object(engine, "send_text", side_effect=_fake_send):
            res1 = engine.monitor.poll_once(auto_reply=True, confirm_send=True, ignore_human_guard=True)

        self.assertTrue(res1["ok"])
        by_target = {a["target"]: a for a in res1["actions"]}
        self.assertEqual(by_target["张总"]["status"], "replied")
        self.assertIn("autoScore", by_target["张总"])
        self.assertEqual(by_target["测试小号"]["status"], "replied")
        self.assertIn("turnId", by_target["测试小号"])

        # Immediately send a `#` directive from 测试小号 (within antiban min_reply_gap_seconds!)
        turn_plan["张总"] = [{"direction": "peer", "text": "#请问你们方案多少钱", "timeMarker": "10:00"}]
        turn_plan["测试小号"] = [
            {"direction": "peer", "text": "你们报价是多少？", "timeMarker": "10:01"},
            {"direction": "self", "text": by_target["测试小号"]["replyText"], "timeMarker": "10:01"},
            {"direction": "peer", "text": "#别一上来报底价，先问客户需求数量", "timeMarker": "10:02"},
        ]
        with patch.object(engine.monitor, "_capture_live_window", side_effect=_fake_capture), \
             patch.object(engine.monitor, "_inspect_target_bubbles", side_effect=_fake_inspect), \
             patch.object(engine, "send_text", side_effect=_fake_send):
            res2 = engine.monitor.poll_once(target_filter="测试小号", auto_reply=True, confirm_send=True, ignore_human_guard=True)

        self.assertTrue(res2["ok"])
        act = res2["actions"][0]
        self.assertEqual(act["status"], "supervisor_directive_handled")
        self.assertIn("已记住你的纠偏要求", act["replyText"])
        self.assertTrue(act["directiveResult"]["revisedReply"])

        # Now test-contact sends another normal message immediately -> still not rate-limited by cold-start antiban
        turn_plan["测试小号"].extend([
            {"direction": "self", "text": act["replyText"], "timeMarker": "10:02"},
            {"direction": "peer", "text": "能介绍一下交付周期吗？", "timeMarker": "10:03"},
        ])
        with patch.object(engine.monitor, "_capture_live_window", side_effect=_fake_capture), \
             patch.object(engine.monitor, "_inspect_target_bubbles", side_effect=_fake_inspect), \
             patch.object(engine, "send_text", side_effect=_fake_send):
            res3 = engine.monitor.poll_once(target_filter="测试小号", auto_reply=True, confirm_send=True, ignore_human_guard=True)

        self.assertEqual(res3["actions"][0]["status"], "replied")

        # Verify low-score autoScore (< 70) sets needsHumanReview = True inside realtime_monitor
        turn_plan["张总"].append({"direction": "peer", "text": "这个靠谱吗", "timeMarker": "10:04"})
        with patch.object(engine.monitor, "_capture_live_window", side_effect=_fake_capture), \
             patch.object(engine.monitor, "_inspect_target_bubbles", side_effect=_fake_inspect), \
             patch.object(engine, "send_text", side_effect=_fake_send), \
             patch.object(
                 engine.personas,
                 "generate_smart_reply",
                 return_value={
                     "ok": True,
                     "target": "张总",
                     "replyText": "不知道 FTS5 100%保证",
                     "persona": {"id": "wecom-kf-pro", "name": "企微客服"},
                     "basis": {"documentRefs": []},
                     "matchedEntries": [],
                     "needsHumanReview": False,
                 },
             ):
            res_low = engine.monitor.poll_once(target_filter="张总", auto_reply=True, confirm_send=False, ignore_human_guard=True)
        low_act = res_low["actions"][0]
        self.assertLess(low_act["autoScore"]["overallScore"], 70)
        self.assertTrue(low_act["needsHumanReview"])

    def test_04_rating_affects_kb_search_rank(self) -> None:
        engine = self._make_engine(customer_bundle=True, name="cust_rank")
        engine.auth_grant(ALL_CAPABILITIES, authorized_by="test")

        e_a = engine.kb_save(
            title="星河全屋定制方案甲",
            body="星河全屋定制方案甲介绍：环保板材与标准设计服务。",
            kind="script",
            keywords=["全屋定制方案", "星河定制"],
        )["entry"]
        e_b = engine.kb_save(
            title="星河全屋定制方案乙",
            body="星河全屋定制方案乙介绍：环保板材与标准设计服务。",
            kind="script",
            keywords=["全屋定制方案", "星河定制"],
        )["entry"]

        t_a = engine.supervisor_eval.record_turn(
            "测试小号", "了解全屋定制方案", "方案甲回复", matched_entry_ids=[e_a["id"]]
        )["turnId"]
        t_b = engine.supervisor_eval.record_turn(
            "测试小号", "了解全屋定制方案", "方案乙回复", matched_entry_ids=[e_b["id"]]
        )["turnId"]

        # Rate A down twice and B up twice
        for _ in range(2):
            engine.submit_reply_rating(t_a, stars=1, tags=["语气太硬"], comment="不够专业")
            engine.submit_reply_rating(t_b, stars=5)

        search_res = engine.kb_search("全屋定制方案", kind="script", limit=10)
        ranked_ids = [e["id"] for e in search_res["entries"]]
        self.assertIn(e_a["id"], ranked_ids)
        self.assertIn(e_b["id"], ranked_ids)
        self.assertLess(ranked_ids.index(e_b["id"]), ranked_ids.index(e_a["id"]))

    def test_05_http_routes_user_guide_and_cli_parsers(self) -> None:
        engine = self._make_engine(customer_bundle=True, name="cust_http")
        engine.auth_grant(ALL_CAPABILITIES, authorized_by="test")
        server = create_http_server(engine, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            # Verify Web Console HTML contains key v3 UI markers
            with urlopen(f"{base}/", timeout=5.0) as resp:
                html = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            for label in (
                "📖 使用手册",
                "✨ 快速训练向导",
                "🧪 测试与评分",
                "🧪 设为测试好友",
                "管理员指令模式：仅指导 AI 改写，不直接发给客户",
                'href="/user-guide"',
                "🌐 在浏览器打开网页版手册",
                'href="https://harzva.github.io/app-use/user-guide.html"',
                "🔗 在线网页版",
            ):
                self.assertIn(label, html)

            # Offline/local web user guide route
            with urlopen(f"{base}/user-guide", timeout=5.0) as guide_resp:
                self.assertEqual(guide_resp.status, 200)
                ctype = str(guide_resp.headers.get("Content-Type") or "")
                self.assertTrue(ctype.lower().startswith("text/html"), f"Unexpected Content-Type: {ctype}")
                guide_html = guide_resp.read().decode("utf-8")
            self.assertIn("WeChat Bot", guide_html)
            if (REPO_ROOT / "docs" / "user-guide.html").is_file():
                expected_html = (REPO_ROOT / "docs" / "user-guide.html").read_text(encoding="utf-8")
                self.assertEqual(guide_html, expected_html)
                visible_text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", guide_html, flags=re.IGNORECASE | re.DOTALL)
                visible_text = re.sub(r"<[^>]+>", " ", visible_text)
                banned_terms = (
                    "FTS5", "SQLite", "AXUIElement", "CGEvent", "Vision OCR", "Magpie",
                    "repo_root", "JSONL", "MCP", "Python", "unittest", "API",
                    "endpoint", "schema", "git", "dhash", "stdout", "WorkOS",
                )
                for term in banned_terms:
                    self.assertIsNone(
                        re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", visible_text, re.IGNORECASE),
                        f"Banned engineering term found in /user-guide visible text: {term}",
                    )

            # User guide markdown route
            st, guide = _http_json(f"{base}/api/docs/user-guide")
            self.assertEqual(st, 200)
            self.assertTrue(guide["ok"])
            self.assertIn("WeChat Bot 使用者操作手册", guide["markdown"])

            # Onboarding + sales packs
            st, packs = _http_json(f"{base}/api/sales-packs")
            self.assertEqual(st, 200)
            self.assertTrue(any(p["packId"] == "general_sales" for p in packs["packs"]))

            st, onb_res = _http_json(
                f"{base}/api/onboarding/setup",
                method="POST",
                payload={"ownerName": "赵老板", "businessName": "青松教育", "productSummary": "职业技能培训"},
            )
            self.assertEqual(st, 200)
            self.assertTrue(onb_res["ok"])

            st, onb_stat = _http_json(f"{base}/api/onboarding/status")
            self.assertEqual(st, 200)
            self.assertTrue(onb_stat["onboardingCompleted"])

            # Training discover/run/approve
            st, disc = _http_json(f"{base}/api/training/discover", method="POST", payload={"searchDirs": [], "includeLiveSessions": False})
            self.assertEqual(st, 200)
            self.assertTrue(disc["ok"])

            st, tr = _http_json(
                f"{base}/api/training/run",
                method="POST",
                payload={
                    "rawConversations": [{
                        "contact": "学员小周",
                        "records": [
                            {"direction": "peer", "text": "课程怎么收费，多少钱？", "timestamp": "2026-11-20 10:00"},
                            {"direction": "self", "text": "基础班 ¥1980 元，支持试听。", "timestamp": "2026-11-20 10:01"},
                            {"direction": "peer", "text": "好的发来看看", "timestamp": "2026-11-20 10:02"},
                        ],
                    }],
                    "useLlm": False,
                },
            )
            self.assertEqual(st, 200)
            self.assertTrue(tr["ok"])
            if tr["draftIds"]:
                st, app = _http_json(
                    f"{base}/api/training/approve",
                    method="POST",
                    payload={"entryIds": tr["draftIds"]},
                )
                self.assertEqual(st, 200)
                self.assertTrue(app["ok"])

            # Test contacts + sparring chat + hashtag + rate + dashboard + regression
            st, tc = _http_json(f"{base}/api/test-contacts", method="POST", payload={"name": "沙盒测试员", "enabled": True})
            self.assertEqual(st, 200)
            self.assertTrue(any(c["displayName"] == "沙盒测试员" for c in tc["testContacts"]))

            st, tc_list = _http_json(f"{base}/api/test-contacts")
            self.assertEqual(st, 200)
            self.assertGreaterEqual(tc_list["count"], 1)

            st, sim = _http_json(
                f"{base}/api/sparring/chat",
                method="POST",
                payload={"contactName": "沙盒测试员", "message": "请问你们课程多少钱？"},
            )
            self.assertEqual(st, 200)
            self.assertTrue(sim["ok"])
            self.assertIn("autoScore", sim)
            tid = sim["turnId"]

            st, dir_res = _http_json(
                f"{base}/api/supervisor/directive",
                method="POST",
                payload={"contact": "沙盒测试员", "text": "#别直接报价，先了解学习目标", "channel": "sparring_sim"},
            )
            self.assertEqual(st, 200)
            self.assertTrue(dir_res["ok"])

            st, rate_res = _http_json(
                f"{base}/api/supervisor/rate",
                method="POST",
                payload={"turnId": tid, "stars": 2, "tags": ["缺少推进"], "comment": "先了解目标"},
            )
            self.assertEqual(st, 200)
            self.assertTrue(rate_res["ok"])

            st, turns_res = _http_json(f"{base}/api/sparring/turns?limit=10")
            self.assertEqual(st, 200)
            self.assertGreaterEqual(turns_res["count"], 1)

            st, dash = _http_json(f"{base}/api/supervisor/dashboard?days=7")
            self.assertEqual(st, 200)
            self.assertGreaterEqual(dash["summary"]["totalTurns"], 1)

            st, reg = _http_json(f"{base}/api/sparring/regression", method="POST", payload={"limit": 10})
            self.assertEqual(st, 200)
            self.assertTrue(reg["ok"])
            self.assertGreaterEqual(reg["totalCases"], 1)
        finally:
            server.shutdown()
            server.server_close()

        # Verify CLI parser registers required v3 subcommands
        parser = build_parser()
        self.assertEqual(parser.parse_args(["train-playbook", "--discover"]).command, "train-playbook")
        self.assertEqual(parser.parse_args(["test-contact", "add", "测试员"]).command, "test-contact")
        self.assertEqual(parser.parse_args(["quality-dashboard", "--regression"]).command, "quality-dashboard")

    def test_06_v3_version_declarations_consistent(self) -> None:
        pyproject_text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "3.0.0"', pyproject_text)

        for rel in (
            "plugin.manifest.json",
            "dsh.plugin.json",
            "market/wechat-rpa-control.plugin.json",
        ):
            data = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
            self.assertEqual(data.get("version"), "3.0.0", f"{rel} version mismatch")

        build_script = (REPO_ROOT / "bin" / "build-standalone-app").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION="3.0.0"', build_script)
        self.assertIn('APP_BUILD="3000"', build_script)


if __name__ == "__main__":
    unittest.main()
