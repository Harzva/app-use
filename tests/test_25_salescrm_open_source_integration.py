"""Tests for Aurora-73/SalesCRM open-source CRM integration across WeChatBot."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vendor.salescrm.engine.formulas import (  # noqa: E402
    sales_action,
    sales_bq,
    sales_bsp,
    sales_bws,
    sales_pv,
)
from wechat_control.cli import build_parser  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.mcp_server import WeChatMCPServer, create_http_server  # noqa: E402
from wechat_control.sales_crm_hub import (  # noqa: E402
    SalesCRMValidationError,
    WeChatSalesCRMHub,
    parse_follow_up_beijing,
)
from wechat_control.web_console import render_web_console_html  # noqa: E402


def _offline_model_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in SalesCRM unit test")


def _http_json(url: str, *, method: str = "GET", body: dict | None = None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class SalesCRMIntegrationTestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)
        self.reports_dir = self.tmp_path / "reports"
        self.contacts_dir = self.reports_dir / "contacts"
        self.contacts_dir.mkdir(parents=True, exist_ok=True)

        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp_path / "audit.jsonl",
            auth_file_path=self.tmp_path / "studio_auth.json",
            bindings_file_path=self.tmp_path / "bound_contacts.json",
            models_config_path=self.tmp_path / "model_providers.json",
            model_http_requester=_offline_model_requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            monitor_state_path=self.tmp_path / "monitor_state.json",
            monitor_events_path=self.tmp_path / "monitor_events.jsonl",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.reports_dir,
            dedup_window_seconds=120.0,
            allowed_groups=["VIP客户群"],
        )
        self.engine.soul_profiler.store_path = self.tmp_path / "soul_memories.json"
        self.engine.auth_grant(authorized_by="salescrm-test")
        self.engine.bind_contact(
            "心安",
            alias="心安伙伴",
            role="vip-customer",
            ai_persona="owner-digital-twin",
            notes="重点AI合作客户",
            special_care=True,
        )
        self.engine.bind_contact(
            "张总",
            role="client",
            ai_persona="professional-consultant",
            notes="企业版预算评估中",
            special_care=False,
        )

        # Seed realistic WeChat contact histories for quantitative scoring & event detection
        now_ts = 1763265600  # fixed epoch for repeatable metrics
        (self.contacts_dir / "心安_test_history.json").write_text(
            json.dumps(
                {
                    "contact": "心安",
                    "messages": [
                        {"direction": "other", "text": "这个方案大概多少钱，下周能定预算吗？", "timestamp": now_ts - 7200},
                        {"direction": "self", "text": "我们帮您准备了分档报价方案和交付排期，发您参考。", "timestamp": now_ts - 7000},
                        {"direction": "other", "text": "价格方面能再给一点优惠吗？我们老板下周二要看演示。", "timestamp": now_ts - 3600},
                        {"direction": "self", "text": "没问题，周二上午十点我带演示材料和报价合同过去对齐。", "timestamp": now_ts - 3400},
                        {"direction": "other", "text": "好呀，周二见！如果顺利这月底前就签约上线。", "timestamp": now_ts - 1800},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.contacts_dir / "张总_test_history.json").write_text(
            json.dumps(
                {
                    "contact": "张总",
                    "messages": [
                        {"direction": "other", "text": "有空发份产品介绍看看。", "timestamp": now_ts - 86400},
                        {"direction": "self", "text": "好的张总，资料已发您，有需要随时联系。", "timestamp": now_ts - 86000},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_25a_vendored_salescrm_15d_metrics_and_formulas(self) -> None:
        bq = sales_bq(0.7, 0.8, 0.4, 0.2)
        bsp = sales_bsp(0.8, 0.7, 1.0, 1.0)
        bws = sales_bws(0.7, 0.8, 0.6, 0.2)
        pv = sales_pv(0.75, 1.0, 0.25, 0.3)
        act = sales_action(bq["bq"], bsp["bsp"], bws["bws"], 0.2, pv["pv"])
        self.assertGreater(bq["bq"], 0.5)
        self.assertIn(act["action"], {"bargain", "push", "maintain", "reset", "nurture"})

        sync_res = self.engine.crm_sync_from_wechat()
        self.assertTrue(sync_res["ok"])
        self.assertGreaterEqual(sync_res["syncedContacts"], 2)

        enr = self.engine.crm_enroll_contact(
            "心安",
            stage="已报价",
            note="老板周二评审演示与合同金额",
            follow_up="2026-11-16T10:30",
            deal_value=88000.0,
        )
        self.assertTrue(enr["ok"])
        dims = enr["metrics"]["dimensions15"]
        self.assertEqual(len(dims), 15)
        for d in dims:
            self.assertIn("key", d)
            self.assertIn("normalized", d)
            self.assertIn("confidence", d)

        ov_formulas = self.engine.crm_evaluate_formulas(
            "心安",
            overrides={"p_succ": 0.9, "escalation_bonus": 1.2, "p_fail": 0.1, "bs": 0.1},
        )
        self.assertEqual(round(ov_formulas["expectedDealValue"], 2), round(88000.0 * 0.9, 2))
        self.assertGreater(ov_formulas["pv"]["pv"], 0.5)

    def test_25b_beijing_followup_validation_and_due_reminders_c01_c04(self) -> None:
        utc_ts, bj_str = parse_follow_up_beijing("2026-11-16T10:30")
        expected_utc = int(datetime(2026, 11, 16, 10, 30, tzinfo=timezone(timedelta(hours=8))).timestamp())
        self.assertEqual(utc_ts, expected_utc)
        self.assertEqual(bj_str, "2026-11-16T10:30")

        db_path = self.tmp_path / "custom_crm.sqlite"
        fixed_clock = [expected_utc - 1800]  # 10:00 CST (before 10:30 follow-up)
        hub = WeChatSalesCRMHub(self.engine, db_path=db_path, clock=lambda: fixed_clock[0])
        hub.sync_from_wechat()
        hub.enroll_contact("心安", stage="已报价", note="初始有效备注", follow_up="2026-11-16T10:30", deal_value=50000.0)

        # C01: invalid follow_up / stage / >2000 note must raise and NEVER overwrite saved valid record
        with self.assertRaises(SalesCRMValidationError):
            hub.update_record("心安", stage="方案推进", note="无效时间不应覆盖", follow_up="tomorrow-morning")
        with self.assertRaises(SalesCRMValidationError):
            hub.update_record("心安", stage="不存在阶段", note="无效阶段不应覆盖", follow_up="2026-11-16T11:00")
        with self.assertRaises(SalesCRMValidationError):
            hub.update_record("心安", stage="跟进中", note="x" * 2001, follow_up="2026-11-16T11:00")

        after_fail = hub.analyze_contact("心安")
        self.assertEqual(after_fail["person"]["stage"], "已报价")
        self.assertEqual(after_fail["person"]["note"], "初始有效备注")
        self.assertEqual(after_fail["person"]["followUpBeijing"], "2026-11-16T10:30")

        # Reopen persistence check + UTC boundary transitions
        hub_reopened = WeChatSalesCRMHub(self.engine, db_path=db_path, clock=lambda: fixed_clock[0])
        before_due = hub_reopened.list_reminders(now_ts=expected_utc - 60)
        self.assertEqual(before_due["dueCount"], 0)
        self.assertEqual(before_due["upcomingCount"], 1)

        at_due = hub_reopened.list_reminders(now_ts=expected_utc)
        self.assertEqual(at_due["dueCount"], 1)
        self.assertEqual(at_due["due"][0]["displayName"], "心安")

        resched = hub_reopened.reschedule_reminder("心安", "2026-11-16T14:00")
        self.assertEqual(resched["followUpBeijing"], "2026-11-16T14:00")
        done = hub_reopened.complete_reminder("心安")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["reminders"]["dueCount"], 0)
        self.assertEqual(done["reminders"]["upcomingCount"], 0)

        # Person -> Account -> Alias merge check
        merge_res = hub_reopened.merge_accounts("心安", "心安小号", alias="XinanVIP")
        self.assertTrue(merge_res["merged"])
        resolved = hub_reopened.resolve_person("XinanVIP")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["displayName"], "心安")

    def test_25c_wechat_sync_timeline_and_top3_drafts_adoption(self) -> None:
        (self.reports_dir / "wechat_management_report.json").write_text(
            json.dumps(
                {
                    "generatedAt": "2026-11-16T01:00:00Z",
                    "contacts": [{"name": "李经理", "unreadCount": 2, "latestSnippet": "发一下商务报价"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        sync_res = self.engine.crm_sync_from_wechat()
        self.assertGreaterEqual(sync_res["syncedContacts"], 3)

        analysis = self.engine.crm_analyze_contact("心安", incoming_text="下周二把最终合同发我看看")
        self.assertTrue(analysis["ok"])
        self.assertGreaterEqual(len(analysis["timeline"]), 1)
        self.assertEqual(len(analysis["topDrafts"]), 3)

        adopted = self.engine.crm_adopt_draft("心安", rank_index=2, send_mode="dry_run")
        self.assertTrue(adopted["ok"])
        self.assertEqual(adopted["rank"], 2)
        self.assertIsNotNone(adopted["sendReceipt"])
        self.assertEqual(adopted["sendReceipt"]["mode"], "dry_run")
        self.assertFalse(adopted["sendReceipt"]["sent"])

    def test_25d_http_api_mcp_dsh_and_web_console_salescrm_tab(self) -> None:
        # 1. CLI parser check
        args = build_parser().parse_args(["crm", "--target", "心安", "--formulas"])
        self.assertEqual(args.command, "crm")
        self.assertEqual(args.target, "心安")
        self.assertTrue(args.formulas)

        # 2. MCP server tools & dispatch check
        mcp = WeChatMCPServer(self.engine)
        tools_list = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in tools_list["result"]["tools"]}
        self.assertTrue({"wechat_salescrm_pipeline", "wechat_salescrm_analyze", "wechat_salescrm_formulas"} <= tool_names)

        call_res = mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "wechat_salescrm_analyze", "arguments": {"target": "心安"}},
            }
        )
        payload = json.loads(call_res["result"]["content"][0]["text"])
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["metrics"]["dimensions15"]), 15)

        # 3. HTTP REST endpoints check
        server = create_http_server(self.engine, host="127.0.0.1", port=0)
        port = server.server_address[1]
        th = threading.Thread(target=server.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{port}"
            st_ov, crm_ov = _http_json(f"{base}/api/crm/overview")
            self.assertEqual(st_ov, 200)
            self.assertTrue(crm_ov["ok"])

            st_enr, enr_res = _http_json(
                f"{base}/api/crm/enroll",
                method="POST",
                body={"target": "心安", "stage": "已报价", "note": "HTTP 接口写入", "follow_up": "2026-11-16T15:30", "deal_value": 66000},
            )
            self.assertEqual(st_enr, 200)
            self.assertEqual(enr_res["person"]["stage"], "已报价")

            st_bad, bad_res = _http_json(
                f"{base}/api/crm/update",
                method="POST",
                body={"target": "心安", "stage": "已成交", "note": "bad time", "follow_up": "not-a-time"},
            )
            self.assertEqual(st_bad, 400)
            self.assertFalse(bad_res["ok"])

            st_rem, rem_res = _http_json(f"{base}/api/crm/reminders")
            self.assertEqual(st_rem, 200)
            self.assertEqual(rem_res["dueCount"] + rem_res["upcomingCount"], 1)

            st_fm, fm_res = _http_json(
                f"{base}/api/crm/formulas",
                method="POST",
                body={"target": "心安", "overrides": {"p_succ": 0.85}},
            )
            self.assertEqual(st_fm, 200)
            self.assertEqual(round(fm_res["expectedDealValue"], 2), round(66000 * 0.85, 2))
        finally:
            server.shutdown()
            server.server_close()
            th.join(timeout=2)

        # 4. Web Console HTML & DSH manifests check (zero confirm dialogs)
        html = render_web_console_html()
        self.assertIn('id="tab-salescrm"', html)
        self.assertIn("renderSalesCrmTab", html)
        self.assertIn("crmRankingsTableBody", html)
        self.assertNotIn("window.confirm(", html)
        self.assertNotIn("window.prompt(", html)

        dsh_doc = json.loads((PROJECT_ROOT / "dsh.plugin.json").read_text(encoding="utf-8"))
        panel_ids = [p["id"] for p in dsh_doc["workbench"]["panels"]]
        self.assertIn("wechat_salescrm_panel", panel_ids)
        for panel in dsh_doc["workbench"]["panels"]:
            for act in panel.get("actions", []):
                self.assertIs(act.get("requiresApproval"), False)

        cat_doc = json.loads((PROJECT_ROOT / "market" / "dsh-agent-plugin-catalog-entry.json").read_text(encoding="utf-8"))
        cap_ids = {c["id"] for c in cat_doc["capabilities"]}
        self.assertIn("sales_crm", cap_ids)


if __name__ == "__main__":
    unittest.main()
