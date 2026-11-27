"""Tests for SupervisorEvalEngine: test-contact sandbox, `#` directives, and dual-track scoring."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from wechat_control.knowledge_kf_engine import WeChatKnowledgeStore
from wechat_control.supervisor_eval import (
    MAX_ENTRY_WEIGHT,
    MIN_ENTRY_WEIGHT,
    SupervisorEvalEngine,
    is_blocked_outbound_directive,
    is_hashtag_directive,
    parse_hashtag_directive,
)


class SupervisorEvalEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "config" / "supervisor_eval.sqlite"
        self.kb_path = self.root / "config" / "knowledge.sqlite"
        self.engine = SupervisorEvalEngine(self.db_path)
        self.kb = WeChatKnowledgeStore(self.kb_path, openbot_db_path=None, auto_seed=False)

    def test_sqlite_schema_tables_and_columns(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            expected_tables = {
                "test_contacts",
                "sparring_turns",
                "negative_constraints",
                "entry_quality_stats",
                "golden_exemplars",
            }
            self.assertTrue(expected_tables.issubset(tables))

            def cols(table: str) -> set[str]:
                return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

            self.assertEqual(
                cols("test_contacts"),
                {"contact_key", "display_name", "note", "created_at"},
            )
            self.assertEqual(
                cols("sparring_turns"),
                {
                    "id",
                    "contact_name",
                    "channel",
                    "incoming_text",
                    "ai_reply",
                    "matched_entry_ids_json",
                    "auto_score_json",
                    "supervisor_rating",
                    "supervisor_tags_json",
                    "supervisor_comment",
                    "hashtag_directive",
                    "revised_reply",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertEqual(
                cols("negative_constraints"),
                {
                    "id",
                    "trigger_text",
                    "bad_reply",
                    "rule_text",
                    "corrected_reply",
                    "keywords_json",
                    "source_contact",
                    "active",
                    "created_at",
                },
            )
            self.assertEqual(
                cols("entry_quality_stats"),
                {
                    "entry_id",
                    "rating_sum",
                    "rating_count",
                    "low_count",
                    "high_count",
                    "weight",
                    "updated_at",
                },
            )
            self.assertEqual(
                cols("golden_exemplars"),
                {
                    "id",
                    "trigger_text",
                    "reply_text",
                    "stage",
                    "rating",
                    "keywords_json",
                    "source_contact",
                    "created_at",
                },
            )

    def test_test_contact_sandbox_and_permission_gate(self) -> None:
        res = self.engine.mark_test_contact("测试小号A (2)", note="老板测试微信")
        self.assertTrue(res["ok"])
        self.assertEqual(res["displayName"], "测试小号A")
        self.assertTrue(self.engine.is_test_contact("测试小号A"))
        self.assertTrue(self.engine.is_test_contact(" 测试小号A (5) "))

        listed = self.engine.list_test_contacts()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["note"], "老板测试微信")

        # Permission matrix
        self.assertTrue(self.engine.is_authorized_supervisor("测试小号A", channel="wechat"))
        self.assertTrue(self.engine.is_authorized_supervisor("文件传输助手", channel="wechat"))
        self.assertTrue(
            self.engine.is_authorized_supervisor(
                "销售总监",
                channel="wechat",
                admin_contacts=["销售总监"],
            )
        )
        for ch in ("workbench", "mobile", "sparring_sim"):
            self.assertTrue(self.engine.is_authorized_supervisor("普通客户李四", channel=ch))

        # External WeChat customers MUST be rejected
        self.assertFalse(self.engine.is_authorized_supervisor("普通客户李四", channel="wechat"))
        self.assertFalse(self.engine.is_authorized_supervisor("", channel="wechat"))

        with self.assertRaises(ValueError):
            self.engine.mark_test_contact("   ")

        removed = self.engine.unmark_test_contact("测试小号A")
        self.assertTrue(removed["removed"])
        self.assertFalse(self.engine.is_test_contact("测试小号A"))
        self.assertFalse(self.engine.is_authorized_supervisor("测试小号A", channel="wechat"))

    def test_unauthorized_customer_hashtag_is_rejected(self) -> None:
        self.engine.record_turn("普通客户王五", "这个怎么卖", "199元一套")
        out = self.engine.handle_hashtag_directive(
            "普通客户王五",
            "# 不能这样说，先问数量",
            channel="wechat",
            knowledge_store=self.kb,
            reply_generator=lambda *a, **kw: "不应该触发",
        )
        self.assertFalse(out["ok"])
        self.assertFalse(out["handled"])
        self.assertEqual(out["reason"], "unauthorized_sender")
        self.assertEqual(self.engine.match_negative_constraints("怎么卖"), [])
        self.assertEqual(self.kb.list_entries()["count"], 0)

    def test_outbound_directive_guard_and_hashtag_detection(self) -> None:
        self.assertTrue(is_hashtag_directive("# 别报底价"))
        self.assertTrue(is_hashtag_directive("＃评分 4 不错"))
        self.assertFalse(is_hashtag_directive("#   "))
        self.assertFalse(is_hashtag_directive("订单号#12345 已发货"))

        self.assertTrue(is_blocked_outbound_directive("#话术 问价格 => 先问数量"))
        self.assertTrue(is_blocked_outbound_directive("好的\n# 别这样回"))
        self.assertFalse(is_blocked_outbound_directive("您的订单#88912明天发货，请查收"))

    def test_parse_all_five_hashtag_intents(self) -> None:
        p1 = parse_hashtag_directive("#评分 2 语气太硬")
        self.assertEqual(p1["intent"], "rate")
        self.assertEqual(p1["stars"], 2)
        self.assertEqual(p1["comment"], "语气太硬")

        p1b = parse_hashtag_directive("＃2分 没说交付周期")
        self.assertEqual(p1b["intent"], "rate")
        self.assertEqual(p1b["stars"], 2)
        self.assertEqual(p1b["comment"], "没说交付周期")

        p1c = parse_hashtag_directive("#5星 很好")
        self.assertEqual(p1c["intent"], "rate")
        self.assertEqual(p1c["stars"], 5)
        self.assertEqual(p1c["comment"], "很好")

        p2 = parse_hashtag_directive("#话术 问价格 => 先了解需求数量再给区间")
        self.assertEqual(p2["intent"], "save_script")
        self.assertEqual(p2["trigger"], "问价格")
        self.assertEqual(p2["body"], "先了解需求数量再给区间")

        p2b = parse_hashtag_directive("#记住 老客户统一9折")
        self.assertEqual(p2b["intent"], "save_script")
        self.assertEqual(p2b["body"], "老客户统一9折")

        p3 = parse_hashtag_directive("#词汇 定制版 => 指支持按logo和尺寸定制的方案")
        self.assertEqual(p3["intent"], "save_term")
        self.assertEqual(p3["term"], "定制版")
        self.assertEqual(p3["definition"], "指支持按logo和尺寸定制的方案")

        for raw, exp_action, exp_paused in (
            ("#接管", "takeover", True),
            ("#停", "pause", True),
            ("#恢复", "resume", False),
        ):
            p4 = parse_hashtag_directive(raw)
            self.assertEqual(p4["intent"], "takeover_control")
            self.assertEqual(p4["action"], exp_action)
            self.assertEqual(p4["paused"], exp_paused)

        p5 = parse_hashtag_directive("# 不能这样说，别一上来报底价，先问对方要几套")
        self.assertEqual(p5["intent"], "critique_rewrite")
        self.assertIn("别一上来报底价", p5["ruleText"])

        p5b = parse_hashtag_directive("# 告诉他周五前下单送安装")
        self.assertEqual(p5b["intent"], "critique_rewrite")
        self.assertEqual(p5b["ruleText"], "告诉他周五前下单送安装")

    def test_critique_rewrite_closed_loop_with_test_contact(self) -> None:
        self.engine.mark_test_contact("测试小号", note="内部质检号")
        saved_kb = self.kb.save_entry(
            title="标准报价话术",
            body="直接报底价199元一套",
            kind="script",
            keywords=["报价", "多少钱"],
        )
        entry_id = saved_kb["entry"]["id"]

        turn = self.engine.record_turn(
            "测试小号 (1)",
            "你们产品多少钱一套？",
            "底价199元一套，直接下单就行。",
            channel="wechat",
            matched_entry_ids=[entry_id],
        )
        self.assertGreater(turn["turnId"], 0)

        captured = {}

        def fake_generator(contact, trigger_text, *, directive="", negative_constraints=()):
            captured["contact"] = contact
            captured["trigger"] = trigger_text
            captured["directive"] = directive
            captured["negatives"] = list(negative_constraints)
            return "方便问下您大概需要几套、用在什么场景吗？不同数量这边给您匹配对应方案和区间价格"

        res = self.engine.handle_hashtag_directive(
            "测试小号",
            "# 不能这样说，别一上来报底价，先问对方要几套",
            channel="wechat",
            knowledge_store=self.kb,
            reply_generator=fake_generator,
        )
        self.assertTrue(res["ok"])
        self.assertTrue(res["handled"])
        self.assertEqual(res["intent"], "critique_rewrite")
        self.assertEqual(res["turnId"], turn["turnId"])
        self.assertIn("几套", res["revisedReply"])
        self.assertIn("已记住", res["ackMessage"])
        self.assertEqual(captured["contact"], "测试小号")
        self.assertEqual(captured["trigger"], "你们产品多少钱一套？")
        self.assertTrue(len(captured["negatives"]) >= 1)

        # Weight decayed for matched entry
        weights = self.engine.get_entry_weights()
        self.assertIn(entry_id, weights)
        self.assertLess(weights[entry_id], 1.0)

        # Negative constraint stored and matchable
        matched_nc = self.engine.match_negative_constraints("产品多少钱一套")
        self.assertGreaterEqual(len(matched_nc), 1)
        self.assertIn("别一上来报底价", matched_nc[0]["ruleText"])
        self.assertEqual(matched_nc[0]["badReply"], "底价199元一套，直接下单就行。")

        # SOP persisted in knowledge_store
        entries = self.kb.list_entries(kind="script")["entries"]
        hashtag_entries = [e for e in entries if e["source"] == "supervisor-hashtag"]
        self.assertEqual(len(hashtag_entries), 1)
        search_hit = self.kb.search_context("要几套 报价")
        self.assertGreaterEqual(search_hit["count"], 1)

    def test_other_four_hashtag_intents_closed_loop(self) -> None:
        self.engine.mark_test_contact("测试主管")
        t = self.engine.record_turn("测试主管", "定制版怎么算？", "需要看具体要求。")

        # 1. rate
        r_rate = self.engine.handle_hashtag_directive(
            "测试主管",
            "#评分 4 还可以，下次再补充周期",
            knowledge_store=self.kb,
        )
        self.assertTrue(r_rate["ok"])
        self.assertEqual(r_rate["stars"], 4)
        self.assertEqual(len(self.engine.match_golden_exemplars("定制版")), 1)

        # 2. save_script
        r_script = self.engine.handle_hashtag_directive(
            "测试主管",
            "#话术 问价格 => 先了解需求数量再给区间",
            knowledge_store=self.kb,
        )
        self.assertTrue(r_script["ok"])
        self.assertIsNotNone(r_script["savedEntryId"])
        scripts = self.kb.list_entries(kind="script")["entries"]
        self.assertTrue(any("先了解需求数量再给区间" in e["body"] for e in scripts))

        # 3. save_term
        r_term = self.engine.handle_hashtag_directive(
            "测试主管",
            "#词汇 定制版 => 指支持按logo和尺寸定制的方案",
            knowledge_store=self.kb,
        )
        self.assertTrue(r_term["ok"])
        self.assertIsNotNone(r_term["savedEntryId"])
        terms = self.kb.list_entries(kind="terminology")["entries"]
        self.assertTrue(any(e["title"] == "定制版" for e in terms))

        # 4. takeover_control
        takeover_events = []
        r_pause = self.engine.handle_hashtag_directive(
            "测试主管",
            "#接管",
            takeover_cb=lambda contact, action: takeover_events.append((contact, action)) or True,
        )
        r_resume = self.engine.handle_hashtag_directive(
            "测试主管",
            "#恢复",
            takeover_cb=lambda contact, action: takeover_events.append((contact, action)) or True,
        )
        self.assertTrue(r_pause["paused"])
        self.assertFalse(r_resume["paused"])
        self.assertEqual(takeover_events, [("测试主管", "takeover"), ("测试主管", "resume")])
        self.assertEqual(t["turnId"], r_rate["turnId"])

    def test_auto_score_five_dimensions(self) -> None:
        good_entry = {
            "id": "kb_1",
            "kind": "terminology",
            "title": "企业定制版",
            "body": "支持按logo和尺寸定制，7天交付",
            "keywords": ["企业定制版", "交付"],
            "synonyms": ["定制版"],
        }
        good = self.engine.auto_score_reply(
            "你们定制版几天能交付？",
            "企业定制版一般7天左右可以交付，方便问下您这边大概需要几套、有logo印制需求吗",
            matched_entries=[good_entry],
            terminology_terms=[{"term": "企业定制版", "aliases": ["定制版"], "dontSay": ["贴牌货"]}],
            negative_constraints=[],
        )
        self.assertGreaterEqual(good["overallScore"], 80)
        self.assertGreaterEqual(good["stars"], 4)
        self.assertFalse(good["needsReview"])
        self.assertEqual(
            set(good["dimensions"].keys()),
            {
                "kbGrounding",
                "terminologyAlignment",
                "salesProgression",
                "complianceSafety",
                "humanLikeness",
            },
        )

        bad = self.engine.auto_score_reply(
            "你们定制版多少钱？",
            "#话术 第一，贴牌货100%保证稳赚；第二，底价199元一套。",
            matched_entries=[good_entry],
            terminology_terms=[{"term": "企业定制版", "aliases": ["定制版"], "dontSay": ["贴牌货"]}],
            negative_constraints=[
                {
                    "badReply": "底价199元一套",
                    "ruleText": "别一上来报底价",
                }
            ],
        )
        self.assertLess(bad["overallScore"], 70)
        self.assertTrue(bad["needsReview"])
        self.assertIn("leaked_hashtag_directive", bad["issues"])
        self.assertIn("violates_negative_constraint", bad["issues"])
        self.assertIn("terminology_dont_say_used", bad["issues"])
        self.assertIn("contains_list_enumeration", bad["issues"])

    def test_submit_rating_weights_clamping_exemplars_and_dashboard(self) -> None:
        with self.assertRaises(ValueError):
            self.engine.submit_rating(1, stars=6)
        with self.assertRaises(ValueError):
            self.engine.submit_rating(1, stars=True)  # type: ignore[arg-type]

        e1 = "kb_good"
        e2 = "kb_bad"
        t_good = self.engine.record_turn(
            "客户A",
            "交期要多久",
            "常规款3天发货，定制款看数量一般7天，您这批大概什么时候要用",
            channel="workbench",
            matched_entry_ids=[e1],
        )
        t_bad = self.engine.record_turn(
            "客户B",
            "能便宜点吗",
            "最低100元不能再少了。",
            channel="wechat",
            matched_entry_ids=[e2],
        )

        # Repeated 5-star boosts clamp at MAX_ENTRY_WEIGHT
        for _ in range(6):
            self.engine.submit_rating(t_good["turnId"], stars=5, tags=["自然专业"])
        # Repeated 1-star decays clamp at MIN_ENTRY_WEIGHT
        for idx in range(6):
            self.engine.submit_rating(
                t_bad["turnId"],
                stars=1,
                tags=["报底价太直接", "缺少推进"],
                comment="别直接说最低价，先确认数量和长期合作计划",
                rewritten_reply="这边价格和采购数量挂钩，您大概打算订多少套？我给您核算阶梯方案",
                knowledge_store=self.kb if idx == 0 else None,
            )

        weights = self.engine.get_entry_weights()
        self.assertEqual(weights[e1], MAX_ENTRY_WEIGHT)
        self.assertEqual(weights[e2], MIN_ENTRY_WEIGHT)

        exemplars = self.engine.match_golden_exemplars("交期 多久")
        self.assertEqual(len(exemplars), 1)
        self.assertEqual(exemplars[0]["rating"], 5)

        dash = self.engine.get_quality_dashboard(days=7)
        self.assertTrue(dash["ok"])
        self.assertEqual(dash["summary"]["totalTurns"], 2)
        self.assertEqual(dash["summary"]["ratedTurns"], 2)
        self.assertEqual(dash["ratingDistribution"][5], 1)
        self.assertEqual(dash["ratingDistribution"][1], 1)
        self.assertGreaterEqual(dash["summary"]["activeNegativeConstraints"], 1)
        self.assertEqual(dash["entryQualityRanking"][0]["entryId"], e1)
        self.assertTrue(any(item["tag"] == "报底价太直接" for item in dash["topIssueTags"]))

    def test_regression_suite_detects_violation_and_verifies_fix(self) -> None:
        self.engine.mark_test_contact("测试小号")
        self.engine.record_turn("测试小号", "多少钱一套", "底价199元一套，直接下单")
        self.engine.handle_hashtag_directive(
            "测试小号",
            "# 不能这样说，别一上来报底价，先问对方要几套",
            reply_generator=lambda c, t, **kw: "方便问下您大概需要几套吗？我按需求给您报区间方案",
        )

        # Bad generator repeats the old bad reply -> 0% pass rate
        bad_report = self.engine.run_regression_suite(
            lambda contact, incoming: "底价199元一套，直接下单",
            limit=10,
        )
        self.assertEqual(bad_report["totalCases"], 1)
        self.assertEqual(bad_report["passedCases"], 0)
        self.assertEqual(bad_report["passRate"], 0.0)

        # Fixed generator avoids negative constraint and progresses the sale -> 100% pass rate
        good_report = self.engine.run_regression_suite(
            lambda contact, incoming, **kw: "方便问下您预计采购几套、什么时间使用呢？我给您出个对应区间方案",
            limit=10,
        )
        self.assertEqual(good_report["totalCases"], 1)
        self.assertEqual(good_report["passedCases"], 1)
        self.assertEqual(good_report["passRate"], 100.0)


if __name__ == "__main__":
    unittest.main()
