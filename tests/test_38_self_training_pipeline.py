"""Comprehensive unittest suite for zero-FDE corpus discovery and self-training playbook pipeline."""

import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wechat_control.corpus_discovery import CorpusDiscoveryEngine
from wechat_control.knowledge_kf_engine import WeChatKnowledgeStore
from wechat_control.playbook_trainer import SelfTrainingPlaybookEngine
from wechat_control.tenant_profile import load_sales_pack


def _make_history_file(
    directory: Path,
    filename: str,
    target: str,
    records: list,
    *,
    observed_at: str,
) -> Path:
    path = directory / filename
    payload = {
        "ok": True,
        "target": target,
        "matchedTitle": target,
        "observedAt": observed_at,
        "recordCount": len(records),
        "records": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class CorpusDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.engine = CorpusDiscoveryEngine()

    def test_discover_wechat_sessions_filters_system_and_test_contacts_and_ranks(self) -> None:
        histories_dir = self.root / "contacts"
        histories_dir.mkdir(parents=True)
        now = datetime.now(timezone.utc)

        _make_history_file(
            histories_dir,
            "zhangsan_history.json",
            "张三·采购总监",
            [
                {"direction": "peer", "text": "您好，想询价一下你们的企业方案，大概多少钱？", "ts": (now - timedelta(hours=2)).isoformat()},
                {"direction": "self", "text": "您好，我们方案按团队规模配置，支持先试用再签约合同。", "ts": (now - timedelta(hours=1)).isoformat()},
                {"direction": "peer", "text": "可以，发个方案对比和交付周期我看看，预算合适下周下单。", "ts": (now - timedelta(minutes=30)).isoformat()},
            ] * 4,
            observed_at=(now - timedelta(minutes=20)).isoformat(),
        )
        _make_history_file(
            histories_dir,
            "lisi_history.json",
            "李四",
            [
                {"direction": "peer", "text": "周末去爬山吗？", "ts": (now - timedelta(days=10)).isoformat()},
                {"direction": "self", "text": "改天吧", "ts": (now - timedelta(days=10)).isoformat()},
            ],
            observed_at=(now - timedelta(days=10)).isoformat(),
        )
        _make_history_file(
            histories_dir,
            "test_friend_history.json",
            "测试小号",
            [
                {"direction": "peer", "text": "报价多少钱，我要下单", "ts": now.isoformat()},
            ],
            observed_at=now.isoformat(),
        )

        inspector_sessions = [
            {"fullTitle": "订阅号", "listTitleSnippet": "订阅号", "enteredFolder": True, "visibleMessageCount": 10},
            {"fullTitle": "微信团队", "listTitleSnippet": "微信团队", "visibleMessageCount": 5},
            {"fullTitle": "腾讯新闻", "listTitleSnippet": "腾讯新闻", "visibleMessageCount": 8},
            {"fullTitle": "服务号", "listTitleSnippet": "服务号", "visibleMessageCount": 12},
            {"fullTitle": "折叠的群聊", "listTitleSnippet": "折叠的群聊", "visibleMessageCount": 20},
            {"fullTitle": "测试小号 (3)", "listTitleSnippet": "测试小号 (3)", "visibleMessageCount": 6},
            {"fullTitle": "张三·采购总监", "listTitleSnippet": "张三·采购总监", "listPreviewSnippet": "发个方案和报价看看", "visibleMessageCount": 12},
            {"fullTitle": "王五·电商老板", "listTitleSnippet": "王五·电商老板", "listPreviewSnippet": "想预约演示看下效果，有优惠吗", "visibleMessageCount": 4},
            {"fullTitle": "李四", "listTitleSnippet": "李四", "listPreviewSnippet": "改天吧", "visibleMessageCount": 2},
        ]

        ranked = self.engine.discover_wechat_sessions(
            inspector_sessions,
            histories_dir,
            test_contacts=("测试小号",),
            limit=5,
        )
        targets = [r["target"] for r in ranked]
        self.assertEqual(targets[0], "张三·采购总监")
        self.assertIn("王五·电商老板", targets)
        self.assertIn("李四", targets)
        for forbidden in ("订阅号", "微信团队", "腾讯新闻", "服务号", "折叠的群聊", "测试小号"):
            self.assertNotIn(forbidden, targets)

        top = ranked[0]
        self.assertTrue(top["hasLocalHistory"])
        self.assertEqual(top["messageCount"], 12)
        self.assertGreater(top["score"], ranked[-1]["score"])
        self.assertTrue(any("商机关键词" in tag for tag in top["reasonTags"]))
        self.assertIn("本地历史已就绪", top["reasonTags"])

    def test_scan_archive_directories_deduplicates_and_preserves_originals(self) -> None:
        dir_a = self.root / "Downloads"
        dir_b = self.root / "Desktop"
        dir_a.mkdir()
        dir_b.mkdir()

        chat_txt = "·张三\n2026年11月15日 09:30\n请问你们方案怎么收费？\n·陈顾问\n2026年11月15日 09:31\n您好，支持先看演示。\n"
        txt_a = dir_a / "客户张三_聊天记录.txt"
        txt_b = dir_b / "客户张三_聊天记录_副本.txt"
        txt_a.write_text(chat_txt, encoding="utf-8")
        txt_b.write_text(chat_txt, encoding="utf-8")
        orig_bytes = txt_a.read_bytes()

        zip_path = dir_a / "王总转发记录.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("聊天记录.txt", "·王总\n2026年11月16日 10:00\n能试用吗？\n")

        # Non-WeChat zip without txt should be ignored
        other_zip = dir_a / "binary_installer.zip"
        with zipfile.ZipFile(other_zip, "w") as zf:
            zf.writestr("payload.bin", b"\x00\x01\x02")

        found = self.engine.scan_archive_directories([dir_a, dir_b])
        names = [item["name"] for item in found]
        self.assertEqual(len(found), 2)
        self.assertIn("王总转发记录.zip", names)
        self.assertEqual(sum(1 for item in found if item["kind"] == "txt"), 1)
        self.assertEqual(txt_a.read_bytes(), orig_bytes)

    def test_infer_owner_multi_bundle_and_single_bundle_fallbacks(self) -> None:
        b1 = {
            "participants": ["陈顾问", "客户甲"],
            "records": [
                {"sender": "客户甲", "content": "您好，想了解方案", "timestamp": "2026-11-15 09:00"},
                {"sender": "陈顾问", "content": "您好，我这边给您发一下资料", "timestamp": "2026-11-15 09:02"},
            ],
        }
        b2 = {
            "participants": ["陈顾问", "客户乙"],
            "records": [
                {"sender": "客户乙", "content": "支持定制吗？", "timestamp": "2026-11-16 10:00"},
                {"sender": "陈顾问", "content": "支持的，我这边安排演示", "timestamp": "2026-11-16 10:01"},
            ],
        }
        res_multi = self.engine.infer_owner_from_bundles([b1, b2])
        self.assertEqual(res_multi["ownerName"], "陈顾问")
        self.assertIn("cross_session_intersection", res_multi["method"])
        self.assertGreaterEqual(res_multi["confidence"], 0.85)

        res_alias = self.engine.infer_owner_from_bundles([b1], known_aliases=["陈顾问"])
        self.assertEqual(res_alias["ownerName"], "陈顾问")
        self.assertEqual(res_alias["method"], "known_alias")

        single_heuristic = {
            "participants": ["买家小李", "销售阿强"],
            "records": [
                {"sender": "买家小李", "content": "在吗", "timestamp": "2026-11-15 09:00"},
                {"sender": "销售阿强", "content": "您好，请问有什么需要安排", "timestamp": "2026-11-15 09:01"},
                {"sender": "买家小李", "content": "想看看", "timestamp": "2026-11-15 09:02"},
                {"sender": "销售阿强", "content": "这边发您报价和方案", "timestamp": "2026-11-15 09:03"},
            ],
        }
        res_heur = self.engine.infer_owner_from_bundles([single_heuristic])
        self.assertEqual(res_heur["ownerName"], "销售阿强")
        self.assertEqual(res_heur["method"], "reply_frequency_heuristic")

    def test_batch_import_archives_parses_zip_and_txt(self) -> None:
        txt_path = self.root / "客户甲_聊天记录.txt"
        txt_path.write_text(
            "·客户甲\n2026年11月15日 09:30\n你好，请问有标准版方案吗？\n"
            "·林顾问\n2026年11月15日 09:31\n您好，标准版适合中小团队快速上手。\n",
            encoding="utf-8",
        )
        zip_path = self.root / "客户乙.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "聊天记录.txt",
                "·客户乙\n2026年11月16日 11:00\n能安排产品演示吗？\n"
                "·林顾问\n2026年11月16日 11:02\n没问题，今天下午可以帮您约。\n",
            )

        convs = self.engine.batch_import_archives([txt_path, zip_path])
        self.assertEqual(len(convs), 2)
        contacts = {c["contact"]: c for c in convs}
        self.assertIn("客户甲", contacts)
        self.assertIn("客户乙", contacts)
        self.assertEqual(contacts["客户甲"]["owner"], "林顾问")
        dirs_a = [r["direction"] for r in contacts["客户甲"]["records"]]
        self.assertEqual(dirs_a, ["peer", "self"])


class SelfTrainingPlaybookPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.trainer = SelfTrainingPlaybookEngine()
        self.sales_pack = load_sales_pack(
            "general_sales",
            Path("/Volumes/SanDisk/WeChatBot/config_templates/sales_packs"),
        )
        self.kb_store = WeChatKnowledgeStore(self.root / "knowledge.sqlite", auto_seed=False)

    def test_redact_pii_masks_all_sensitive_fields_and_secrets(self) -> None:
        raw = (
            "我是张建国，手机13812345678，备用139-8765-4321，邮箱zhang@example.com，"
            "微信号：alice_wx99，老号wxid_abc12345，身份证110105199001011234，"
            "银行卡6222021234567890123，地址上海市浦东新区张江路88号3栋502室，"
            "密钥sk-1234567890abcdef1234567890。"
        )
        redacted = self.trainer.redact_pii(raw, customer_names=["张建国"])
        self.assertIn("{客户}", redacted)
        self.assertIn("{手机号}", redacted)
        self.assertIn("{邮箱}", redacted)
        self.assertIn("{微信号}", redacted)
        self.assertIn("{身份证号}", redacted)
        self.assertIn("{银行卡号}", redacted)
        self.assertIn("{地址}", redacted)
        self.assertIn("{密钥}", redacted)
        for leaked in ("张建国", "13812345678", "139-8765-4321", "zhang@example.com", "alice_wx99", "wxid_abc12345", "110105199001011234", "6222021234567890123", "张江路88号", "sk-1234567890"):
            self.assertNotIn(leaked, redacted)

    def test_segment_qa_turns_merges_bubbles_and_splits_on_gap(self) -> None:
        records = [
            {"direction": "peer", "sender": "客户A", "text": "您好", "timestamp": "2026-11-15 10:00:00"},
            {"direction": "peer", "sender": "客户A", "text": "想咨询下企业茶礼定制方案", "timestamp": "2026-11-15 10:01:00"},
            {"direction": "self", "sender": "我", "text": "您好，企业茶礼支持LOGO定制。", "timestamp": "2026-11-15 10:02:00"},
            {"direction": "self", "sender": "我", "text": "目前标准礼盒有乌龙茶礼盒和红茶礼盒两款。", "timestamp": "2026-11-15 10:03:00"},
            {"direction": "peer", "sender": "客户A", "text": "好的，发个案例图我看看", "timestamp": "2026-11-15 10:05:00"},
            # Gap > 30 minutes
            {"direction": "peer", "sender": "客户A", "text": "另外问下交付周期多久", "timestamp": "2026-11-15 11:00:00"},
            {"direction": "self", "sender": "我", "text": "常规按订单排期确认后安排发货。", "timestamp": "2026-11-15 11:02:00"},
        ]
        turns = self.trainer.segment_qa_turns(records, gap_minutes=30, contact="客户A")
        self.assertEqual(len(turns), 2)
        self.assertIn("想咨询下企业茶礼定制方案", turns[0]["askText"])
        self.assertEqual(turns[0]["askBubbleCount"], 2)
        self.assertEqual(turns[0]["replyBubbleCount"], 2)
        self.assertEqual(turns[0]["next_peer_reply"], "好的，发个案例图我看看")
        self.assertEqual(turns[1]["askText"], "另外问下交付周期多久")
        self.assertEqual(turns[1]["next_peer_reply"], "")

    def test_select_high_value_turns_filters_noise_rejections_and_clusters(self) -> None:
        turns = [
            {"contact": "A", "askText": "在吗", "replyText": "在的", "next_peer_reply": "好的"},
            {"contact": "A", "askText": "收到", "replyText": "[旺柴]", "next_peer_reply": ""},
            {"contact": "B", "askText": "这个方案怎么合作？", "replyText": "我们先了解您的团队规模，再匹配标准版方案并安排演示。", "next_peer_reply": "不需要，不用了，别发了"},
            {"contact": "C", "askText": "你们怎么帮我们提升客户跟进效率？", "replyText": "我们先梳理高频咨询场景，再配合行业话术库和跟进提醒帮团队提升首响速度。", "next_peer_reply": "不错，可以约个时间演示看看"},
            {"contact": "D", "askText": "你们系统怎么提升客户跟进效率呀？", "replyText": "我们先梳理高频咨询场景，再配合行业话术库和跟进提醒帮团队提升首响速度。", "next_peer_reply": "行，发资料我看看"},
            {"contact": "E", "askText": "支持先看演示案例再决定吗？", "replyText": "完全支持，我先结合您的业务场景准备对应演示和同行案例拆解，方便您内部评估。", "next_peer_reply": "好的发来看看"},
        ]
        selected = self.trainer.select_high_value_turns(turns)
        asks = [t["askText"] for t in selected]
        self.assertNotIn("在吗", asks)
        self.assertNotIn("收到", asks)
        self.assertNotIn("这个方案怎么合作？", asks)
        # C and D have near-identical intent/reply and should cluster into 1 representative
        self.assertEqual(len(selected), 2)
        clustered = next(t for t in selected if "跟进效率" in t["askText"])
        self.assertEqual(clustered["clusterSize"], 2)
        self.assertGreater(clustered["scoreBreakdown"]["crossCustomerPhrase"], 0)

    def test_mine_vocabulary_offline_extracts_chinese_terms_and_skus(self) -> None:
        conversations = [
            {
                "contact": "客户1",
                "records": [
                    {"direction": "peer", "text": "我们想采购乌龙茶礼盒，预算看Pro-200款，支持企业定制吗？"},
                    {"direction": "self", "text": "您好，乌龙茶礼盒Pro-200款支持企业定制，也配专属茶礼方案。"},
                ],
            },
            {
                "contact": "客户2",
                "records": [
                    {"direction": "peer", "text": "乌龙茶礼盒和X80便携装对比怎么样？"},
                    {"direction": "self", "text": "乌龙茶礼盒适合商务赠礼，Pro-200款礼盒质感更好，X80便携装适合日常办公。"},
                ],
            },
        ]
        vocab = self.trainer.mine_vocabulary(conversations, model_hub=None, use_llm=False)
        terms = [v["term"] for v in vocab]
        self.assertTrue(any("Pro-200" == t for t in terms), f"Expected Pro-200 in {terms}")
        self.assertTrue(any("X80" == t for t in terms), f"Expected X80 in {terms}")
        self.assertTrue(any("乌龙茶礼盒" in t for t in terms), f"Expected 乌龙茶礼盒 in {terms}")
        for item in vocab:
            self.assertIn("definition", item)
            self.assertIn("doSay", item)
            self.assertIn("dontSay", item)
            self.assertIn("evidence", item)
            self.assertIsInstance(item["aliases"], list)

    def test_synthesize_risk_gating_train_and_approve_drafts_fts5(self) -> None:
        conversations = [
            {
                "contact": "李总",
                "records": [
                    {"direction": "peer", "text": "怎么结合我们的团队情况出方案？", "timestamp": "2026-11-15 10:00:00"},
                    {"direction": "self", "text": "李总您好，我们一般先核对团队规模和业务场景，再匹配乌龙茶礼盒方案给您做演示。", "timestamp": "2026-11-15 10:01:00"},
                    {"direction": "peer", "text": "好的，那约时间演示一下", "timestamp": "2026-11-15 10:03:00"},
                ],
            },
            {
                "contact": "王经理",
                "records": [
                    {"direction": "peer", "text": "乌龙茶礼盒具体多少钱，能打折吗？多久发货？", "timestamp": "2026-11-16 14:00:00"},
                    {"direction": "self", "text": "王经理您好，乌龙茶礼盒标准报价1980元，老客户可以打8折并赠送体验装，保证3天内发货，不满意支持全额退款。", "timestamp": "2026-11-16 14:01:00"},
                    {"direction": "peer", "text": "行，合同发我看看", "timestamp": "2026-11-16 14:02:00"},
                ],
            },
        ]

        report_path = self.root / "training_report.json"
        result = self.trainer.train_from_corpora(
            conversations,
            sales_pack=self.sales_pack,
            knowledge_store=self.kb_store,
            model_hub=None,
            use_llm=False,
            auto_publish_safe=True,
            report_path=report_path,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(report_path.is_file())
        persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted_report["packId"], "general_sales")

        entries_by_id = {e["id"]: e for e in result["entries"]}
        self.assertGreaterEqual(len(result["publishedIds"]), 1)
        self.assertGreaterEqual(len(result["draftIds"]), 1)

        # Risk-flagged entries must be draft and carry descriptive riskFlags
        for did in result["draftIds"]:
            entry = entries_by_id[did]
            self.assertEqual(entry["status"], "draft")
            self.assertTrue(entry["needsApproval"])
            self.assertTrue(len(entry["riskFlags"]) > 0)

        risk_entry = next(entries_by_id[did] for did in result["draftIds"] if "1980元" in entries_by_id[did]["body"])
        self.assertIn("specific_price", risk_entry["riskFlags"])
        self.assertIn("discount", risk_entry["riskFlags"])
        self.assertIn("refund_return", risk_entry["riskFlags"])
        self.assertIn("delivery_deadline", risk_entry["riskFlags"])
        self.assertIn("freebie", risk_entry["riskFlags"])
        # Customer name PII should be masked inside saved body
        self.assertNotIn("王经理", risk_entry["body"])

        # Draft entry should NOT appear in published FTS5 search before approval
        pre_search = self.kb_store.search_context("1980元 乌龙茶礼盒 报价", external_only=True)
        pre_ids = {e["id"] for e in pre_search["entries"]}
        self.assertNotIn(risk_entry["id"], pre_ids)

        # Published safe entry SHOULD appear in FTS5 search
        safe_search = self.kb_store.search_context("团队规模 乌龙茶礼盒 演示", external_only=True)
        safe_ids = {e["id"] for e in safe_search["entries"]}
        self.assertTrue(bool(safe_ids & set(result["publishedIds"])))

        # Approve draft with edited body and verify FTS5 searchability
        approved = self.trainer.approve_drafts(
            self.kb_store,
            [risk_entry["id"]],
            edits={
                risk_entry["id"]: {
                    "title": "已报价·核定标准茶礼报价",
                    "body": "核定口径：企业茶礼标准套餐按配置梯度报价，具体排期与优惠由负责人确认后书面报价单为准。",
                }
            },
        )
        self.assertEqual(approved["publishedIds"], [risk_entry["id"]])
        self.assertEqual(approved["approved"][0]["status"], "published")
        self.assertEqual(approved["approved"][0]["revision"], 2)

        post_search = self.kb_store.search_context("书面报价单 企业茶礼", external_only=True)
        post_ids = {e["id"] for e in post_search["entries"]}
        self.assertIn(risk_entry["id"], post_ids)

    def test_exaggerated_claim_gating_and_llm_enrichment_with_fallback(self) -> None:
        class _DummyModelHub:
            state = {"enabled": True}

            def generate_chat_reply(self, messages, **kwargs):
                content = messages[0]["content"]
                if "业务术语" in content:
                    return {
                        "ok": True,
                        "replyText": json.dumps([
                            {
                                "term": "企业茶礼",
                                "aliases": ["商务茶礼"],
                                "definition": "面向企业客户的定制礼盒方案。",
                                "doSay": "可按需定制礼盒规格",
                                "dontSay": "不要随意承诺最低价",
                            }
                        ], ensure_ascii=False),
                    }
                return {"ok": False, "error": "simulated offline"}

        convs = [
            {
                "contact": "赵总",
                "records": [
                    {"direction": "peer", "text": "你们企业茶礼效果怎么样？", "timestamp": "2026-11-17 09:00:00"},
                    {"direction": "self", "text": "企业茶礼100%保证效果，客户收到肯定满意，企业茶礼支持定制。", "timestamp": "2026-11-17 09:01:00"},
                    {"direction": "peer", "text": "好的，发方案看看", "timestamp": "2026-11-17 09:02:00"},
                ],
            }
        ]
        res = self.trainer.train_from_corpora(
            convs,
            sales_pack=self.sales_pack,
            knowledge_store=self.kb_store,
            model_hub=_DummyModelHub(),
            use_llm=True,
            auto_publish_safe=True,
        )
        exaggerated = [e for e in res["entries"] if "exaggerated_claim" in e["riskFlags"]]
        self.assertGreaterEqual(len(exaggerated), 1)
        for item in exaggerated:
            self.assertEqual(item["status"], "draft")
            self.assertTrue(item["needsApproval"])


if __name__ == "__main__":
    unittest.main()
