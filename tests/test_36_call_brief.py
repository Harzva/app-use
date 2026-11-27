"""Unit tests for PreCallBriefEngine (`wechat_control/call_brief.py`) and
SoulMemoryProfiler Moments enhancement (`wechat_control/soul_memory_profiler.py`).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wechat_control.call_brief import PreCallBriefEngine  # noqa: E402
from wechat_control.engine import WeChatControlEngine  # noqa: E402
from wechat_control.soul_memory_profiler import SoulMemoryProfiler  # noqa: E402


def _offline_requester(method, url, **kwargs):
    raise ConnectionRefusedError("offline in unit test")


class PreCallBriefTestSuite(unittest.TestCase):
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
            model_http_requester=_offline_requester,
            knowledge_db_path=self.tmp_path / "kb.sqlite",
            personas_file_path=self.tmp_path / "personas.json",
            monitor_state_path=self.tmp_path / "monitor_state.json",
            monitor_events_path=self.tmp_path / "monitor_events.jsonl",
            snapshots_dir=self.tmp_path / "snapshots",
            reports_dir=self.reports_dir,
            dedup_window_seconds=120.0,
        )
        self.engine.soul_profiler.store_path = self.tmp_path / "soul_memories.json"
        self.engine.auth_grant(authorized_by="test-36")
        self.brief_engine = PreCallBriefEngine(self.engine)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _seed_full_five_sources(self) -> None:
        # 1) Binding + 2) Contact profile
        self.engine.bind_contact(
            "Alice Chen",
            alias="Alice",
            role="vip-customer",
            ai_persona="warm-companion",
            notes="负责华东区智能客服采购，老板下周二要看演示",
            special_care=True,
            care_tags=["企业采购", "决策人"],
        )

        # 1) Chat history across two differently cased / suffixed files + monitor event (with duplicate)
        now_ts = 1763265600
        (self.contacts_dir / "alice_chen_a1_history.json").write_text(
            json.dumps(
                {
                    "target": "alice chen",
                    "matchedTitle": "Alice Chen",
                    "records": [
                        {
                            "kind": "message",
                            "direction": "peer",
                            "text": "这个企业版方案大概多少钱，能按季度付吗？",
                            "timeMarker": "昨天 14:20",
                        },
                        {
                            "kind": "message",
                            "direction": "self",
                            "text": "我们整理了两档报价和交付排期，发您参考。",
                            "timeMarker": "昨天 14:25",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.contacts_dir / "ALICE_group_history.json").write_text(
            json.dumps(
                {
                    "contact": "Alice Chen (2)",
                    "messages": [
                        # Duplicate of message above to test dedup
                        {
                            "direction": "self",
                            "text": "我们整理了两档报价和交付排期，发您参考。",
                            "timestamp": now_ts - 3600,
                        },
                        {
                            "direction": "other",
                            "text": "价格方面能再给一点优惠吗？下周二上午还要带团队看演示。",
                            "timestamp": now_ts - 1800,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Monitor event with one duplicate and one brand-new incoming message
        self.engine.monitor._append_event(
            "preview_reply",
            {
                "target": "alice chen",
                "incomingText": "价格方面能再给一点优惠吗？下周二上午还要带团队看演示。",
                "replyText": "收到，我这就确认优惠空间。",
            },
        )
        self.engine.monitor._append_event(
            "handoff_requested",
            {
                "target": "Alice Chen",
                "incomingText": "顺便问下私有部署支持 macOS 和 Linux 吗？临时密钥 sk-secret1234567890abcdef",
                "replyText": "我请负责人直接电话跟您确认私有部署与优惠细节。",
            },
        )

        # 3) Soul profile + live memory
        self.engine.soul_profiler.add_memory_note(
            "Alice Chen",
            "偏好电话直给结论，忌讳绕弯子或过度推销",
            category="preference",
            time_marker="2026-11-24",
        )
        self.engine.soul_profiler.ingest_live_turn(
            "Alice Chen",
            "我平时上午开会多，一般下午三点后比较有空接电话",
            "好的，后续我优先下午三点后联系您",
        )

        # 4) Moments posts & mutual interactions (mocked `get_posts_for_contact`)
        self.engine.moments.get_posts_for_contact = lambda name, limit=12: {  # type: ignore[attr-defined]
            "ok": True,
            "contact": name,
            "authored": [
                {
                    "key": "mom_alice_1",
                    "author": "Alice Chen",
                    "text": "周末去莫干山徒步爬山，顺便看完了《创新者的窘境》",
                    "attachments": [],
                    "timeText": "2天前",
                    "source": "",
                    "likes": ["号主", "王总"],
                    "comments": [{"author": "号主", "replyTo": "", "text": "风景真棒！"}],
                    "isAd": False,
                    "isOwn": False,
                    "likedByMe": True,
                    "commentedByMe": True,
                }
            ],
            "interactedOnMine": [
                {"postKey": "mom_owner_1", "kind": "like", "timeText": "昨天"}
            ],
            "stats": {"authoredCount": 1, "likedByMe": 1, "commentedByMe": 1, "likedMyPosts": 1},
        }

        # 5) SalesCRM record
        self.engine.sales_crm.enroll_contact(
            "Alice Chen",
            stage="已报价",
            deal_value=48000.0,
            follow_up="2026-11-26T15:30",
            note="下周二向老板演示后敲定年度采购",
        )

    def test_01_empty_target_validation(self) -> None:
        for bad in ("", "   ", "(12)"):
            res = self.brief_engine.generate_brief(bad)
            self.assertFalse(res["ok"])
            self.assertEqual(res["error_code"], "target_required")
            self.assertTrue(res["error"])

    def test_02_cold_start_empty_contact_no_hallucination(self) -> None:
        res = self.brief_engine.generate_brief("完全陌生的新联系人", use_llm=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["target"], "完全陌生的新联系人")
        self.assertEqual(res["matchedTitle"], "完全陌生的新联系人")
        self.assertEqual(res["goal"], "general")
        self.assertEqual(res["goalLabel"], "综合沟通")
        self.assertFalse(res["usedLlm"])
        self.assertEqual(res["llmFallbackReason"], "use_llm=false")

        cov = res["dataCoverage"]
        self.assertEqual(cov["chatMessages"], 0)
        self.assertEqual(cov["momentsPosts"], 0)
        self.assertEqual(cov["momentsMutualHits"], 0)
        self.assertEqual(cov["soulMemories"], 0)
        self.assertFalse(cov["hasCrmRecord"])
        self.assertEqual(cov["crmStage"], "")

        self.assertEqual(res["momentsInsights"]["recentPosts"], [])
        self.assertEqual(res["momentsInsights"]["icebreakers"], [])
        self.assertEqual(res["historyHighlights"], [])
        self.assertIn("暂无", res["summaryCard"]["oneLiner"])
        self.assertTrue(len(res["summaryCard"]["dos"]) >= 2)
        self.assertTrue(len(res["summaryCard"]["donts"]) >= 2)
        self.assertTrue(res["phoneScripts"]["opening"])
        self.assertTrue(len(res["phoneScripts"]["discoveryQuestions"]) >= 2)
        self.assertTrue(len(res["phoneScripts"]["objectionHandlers"]) >= 2)
        self.assertTrue(res["phoneScripts"]["closing"])

    def test_03_full_five_source_aggregation_and_dedup(self) -> None:
        self._seed_full_five_sources()
        # Query with lowercase to verify case-insensitive matching
        res = self.brief_engine.generate_brief("alice chen", goal="quote", use_llm=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["matchedTitle"], "Alice Chen")
        self.assertEqual(res["goal"], "quote")
        self.assertEqual(res["goalLabel"], "推进方案与报价")

        cov = res["dataCoverage"]
        # 2 from file1 + 1 unique from file2 + 1 unique incoming + 1 reply from handoff = 5 unique messages
        self.assertEqual(cov["chatMessages"], 5)
        self.assertEqual(cov["momentsPosts"], 1)
        self.assertEqual(cov["momentsMutualHits"], 3)
        self.assertGreaterEqual(cov["soulMemories"], 2)
        self.assertTrue(cov["hasCrmRecord"])
        self.assertEqual(cov["crmStage"], "已报价")

        # Strict schema presence
        for k in (
            "ok", "target", "matchedTitle", "generatedAt", "goal", "goalLabel",
            "usedLlm", "modelId", "llmFallbackReason", "dataCoverage",
            "summaryCard", "momentsInsights", "needsAndFocus", "historyHighlights", "phoneScripts",
        ):
            self.assertIn(k, res)

        # Grounded Moments insights
        mi = res["momentsInsights"]
        self.assertEqual(len(mi["recentPosts"]), 1)
        self.assertIn("莫干山", mi["recentPosts"][0]["text"])
        self.assertTrue(any("莫干山" in ib or "创新者" in ib for ib in mi["icebreakers"]))

        # Needs & CRM hint
        nf = res["needsAndFocus"]
        self.assertTrue(any("价格" in item or "预算" in item for item in nf["coreNeeds"]))
        self.assertIn("已报价", nf["crmHint"])
        self.assertTrue(len(nf["openLoops"]) >= 1)

        # Highlights capped at <= 8 and deduplicated
        hh = res["historyHighlights"]
        self.assertGreaterEqual(len(hh), 3)
        self.assertLessEqual(len(hh), 8)
        self.assertEqual(len([x for x in hh if "整理了两档报价和交付排期" in x]), 1)

        # Spoken script checks
        ps = res["phoneScripts"]
        self.assertIn("Alice Chen", ps["opening"])
        self.assertTrue(all("concern" in h and "response" in h for h in ps["objectionHandlers"]))

    def test_04_moments_fallback_to_list_posts_and_fault_tolerance(self) -> None:
        # Engine stub where get_posts_for_contact does NOT exist, bindings/crm/soul fail
        fake_engine = SimpleNamespace(
            inspector=SimpleNamespace(reports_dir=self.tmp_path / "nonexistent_reports"),
            monitor=SimpleNamespace(recent_events=lambda limit=50: (_ for _ in ()).throw(RuntimeError("monitor down"))),
            bindings=SimpleNamespace(get_binding=lambda t: (_ for _ in ()).throw(RuntimeError("bindings down"))),
            profile_contacts=lambda: (_ for _ in ()).throw(PermissionError("no status")),
            soul_profiler=SimpleNamespace(
                get_profiles=lambda target="": (_ for _ in ()).throw(RuntimeError("soul down")),
                get_contact_memory_context=lambda target: (_ for _ in ()).throw(RuntimeError("ctx down")),
            ),
            moments=SimpleNamespace(
                list_posts=lambda author="", limit=12: {
                    "ok": True,
                    "posts": [
                        {
                            "key": "mom_fb_1",
                            "author": author,
                            "text": "刚发布了一个 AI Agent 自动化新工具",
                            "attachments": [],
                            "timeText": "3小时前",
                            "likes": ["号主"],
                            "comments": [],
                            "isAd": False,
                            "likedByMe": True,
                            "commentedByMe": False,
                        }
                    ],
                },
                stats=lambda limit=60: {"ok": True, "contacts": []},
            ),
            sales_crm=SimpleNamespace(
                analyze_contact=lambda t: (_ for _ in ()).throw(ValueError("not found in crm"))
            ),
            models=None,
        )
        brief = PreCallBriefEngine(fake_engine).generate_brief("Bob", use_llm=True)
        self.assertTrue(brief["ok"])
        self.assertEqual(brief["dataCoverage"]["momentsPosts"], 1)
        self.assertEqual(brief["dataCoverage"]["momentsMutualHits"], 1)
        self.assertEqual(brief["momentsInsights"]["recentPosts"][0]["key"], "mom_fb_1")
        self.assertFalse(brief["usedLlm"])
        self.assertEqual(brief["llmFallbackReason"], "models_unavailable")

    def test_05_llm_valid_json_and_code_fence_and_redaction(self) -> None:
        self._seed_full_five_sources()
        captured_calls = []

        def fake_generate_chat_reply(messages, **kwargs):
            captured_calls.append({"messages": messages, "kwargs": kwargs})
            payload = {
                "summaryCard": {
                    "oneLiner": "Alice Chen 关注华东企业采购报价与下周二演示。",
                    "temperamentAndStyle": "干脆务实，看重结果与时间节点。",
                    "emotionalTone": "积极偏审慎",
                    "dos": ["下午三点后联系，直给分档方案", "提前对齐私有部署支持列表"],
                    "donts": ["不要绕弯子寒暄太久"],
                },
                "momentsInsights": {
                    "summary": "近期去莫干山徒步并读《创新者的窘境》，对实用主义效率很有共鸣。",
                    "icebreakers": ["看到你周末去莫干山徒步了，那边空气特别好吧？"],
                },
                "needsAndFocus": {
                    "coreNeeds": ["明确分档报价与优惠边界", "确认 macOS/Linux 私有部署兼容性"],
                    "focusTopics": ["企业版报价", "下周二团队演示", "私有部署"],
                    "openLoops": ["确认下周二上午团队演示议程"],
                    "crmHint": "已报价阶段，建议本次电话敲定演示时间并发送分档预算表。",
                },
                "historyHighlights": ["[对方] 询问报价优惠及下周二团队演示安排"],
                "phoneScripts": {
                    "opening": "喂 Alice，方便聊两分钟吗？关于下周二团队演示和私有部署的事，电话里快速跟您对一下。",
                    "discoveryQuestions": ["下周二参加演示的同事主要关注功能演示还是部署架构？"],
                    "objectionHandlers": [
                        {"concern": "希望再压缩一期采购预算", "response": "我们可以先按核心席位分阶段开通，把首期门槛降下来。"}
                    ],
                    "closing": "那我挂了电话就把分档报价和演示清单发您微信，周二上午准时见！",
                },
            }
            return {
                "ok": True,
                "modelId": "auto/deepseek-v4-pro",
                "replyText": f"<think>分析中</think>\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```",
            }

        self.engine.models.is_llm_enabled = lambda: True  # type: ignore[method-assign]
        self.engine.models.generate_chat_reply = fake_generate_chat_reply  # type: ignore[method-assign]

        res = self.brief_engine.generate_brief("Alice Chen", goal="quote", use_llm=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["usedLlm"])
        self.assertEqual(res["modelId"], "auto/deepseek-v4-pro")
        self.assertEqual(res["llmFallbackReason"], "")
        self.assertEqual(res["summaryCard"]["oneLiner"], "Alice Chen 关注华东企业采购报价与下周二演示。")
        self.assertEqual(res["momentsInsights"]["icebreakers"], ["看到你周末去莫干山徒步了，那边空气特别好吧？"])
        # Real local recentPosts preserved intact (LLM cannot fabricate or delete them)
        self.assertEqual(len(res["momentsInsights"]["recentPosts"]), 1)
        self.assertEqual(res["momentsInsights"]["recentPosts"][0]["key"], "mom_alice_1")

        # Verify exact LLM call kwargs & secret redaction
        self.assertEqual(len(captured_calls), 1)
        kw = captured_calls[0]["kwargs"]
        self.assertEqual(kw["contact_name"], "Alice Chen")
        self.assertAlmostEqual(kw["temperature"], 0.35)
        self.assertEqual(kw["max_tokens"], 4096)
        self.assertAlmostEqual(kw["timeout"], 35.0)
        prompt_blob = json.dumps(captured_calls[0]["messages"], ensure_ascii=False)
        self.assertNotIn("sk-secret1234567890abcdef", prompt_blob)
        self.assertIn("[已脱敏凭据]", prompt_blob)

    def test_06_llm_cold_start_cannot_invent_moments_or_history(self) -> None:
        self.engine.models.is_llm_enabled = lambda: True  # type: ignore[method-assign]
        self.engine.models.generate_chat_reply = lambda msgs, **kw: {  # type: ignore[method-assign]
            "ok": True,
            "modelId": "mock-llm",
            "replyText": json.dumps(
                {
                    "summaryCard": {"oneLiner": "初次接触陌生客户，先温和建立信任。"},
                    "momentsInsights": {"summary": "编造动态", "icebreakers": ["看到你发了旅游照"]},
                    "historyHighlights": ["编造昨天聊过价格"],
                    "phoneScripts": {"opening": "喂你好，第一次电话联系，方便聊两分钟吗？"},
                },
                ensure_ascii=False,
            ),
        }
        res = self.brief_engine.generate_brief("新客户甲", use_llm=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["usedLlm"])
        # Anti-hallucination guard keeps momentsInsights.icebreakers and historyHighlights empty!
        self.assertEqual(res["momentsInsights"]["icebreakers"], [])
        self.assertEqual(res["momentsInsights"]["recentPosts"], [])
        self.assertEqual(res["historyHighlights"], [])

    def test_07_llm_timeout_error_and_invalid_json_fallbacks(self) -> None:
        self._seed_full_five_sources()
        self.engine.models.is_llm_enabled = lambda: True  # type: ignore[method-assign]

        # 1) Timeout exception
        def raise_timeout(*args, **kwargs):
            raise TimeoutError("request timed out after 22s")

        self.engine.models.generate_chat_reply = raise_timeout  # type: ignore[method-assign]
        r1 = self.brief_engine.generate_brief("Alice Chen", use_llm=True)
        self.assertTrue(r1["ok"])
        self.assertFalse(r1["usedLlm"])
        self.assertIn("timed out", r1["llmFallbackReason"])
        self.assertTrue(r1["phoneScripts"]["opening"])

        # 2) Garbled non-JSON output
        self.engine.models.generate_chat_reply = lambda *a, **kw: {  # type: ignore[method-assign]
            "ok": True,
            "modelId": "auto/broken",
            "replyText": "抱歉，我现在无法以 JSON 格式输出：乱码###",
        }
        r2 = self.brief_engine.generate_brief("Alice Chen", use_llm=True)
        self.assertTrue(r2["ok"])
        self.assertFalse(r2["usedLlm"])
        self.assertEqual(r2["modelId"], "auto/broken")
        self.assertEqual(r2["llmFallbackReason"], "invalid_llm_json")

        # 3) Empty JSON dict `{}`
        self.engine.models.generate_chat_reply = lambda *a, **kw: {  # type: ignore[method-assign]
            "ok": True,
            "modelId": "auto/empty",
            "replyText": "{}",
        }
        r3 = self.brief_engine.generate_brief("Alice Chen", use_llm=True)
        self.assertTrue(r3["ok"])
        self.assertFalse(r3["usedLlm"])
        self.assertEqual(r3["llmFallbackReason"], "empty_llm_payload")

        # 4) LLM disabled flag
        self.engine.models.is_llm_enabled = lambda: False  # type: ignore[method-assign]
        r4 = self.brief_engine.generate_brief("Alice Chen", use_llm=True)
        self.assertTrue(r4["ok"])
        self.assertFalse(r4["usedLlm"])
        self.assertEqual(r4["llmFallbackReason"], "llm_disabled")

    def test_08_goal_switching_including_custom_goal(self) -> None:
        self._seed_full_five_sources()
        expected_labels = {
            "general": "综合沟通",
            "followup": "日常破冰与跟进",
            "quote": "推进方案与报价",
            "care": "客情维系关怀",
            "recovery": "异议拆解与情绪安抚",
        }
        openings = {}
        for g, label in expected_labels.items():
            res = self.brief_engine.generate_brief("Alice Chen", goal=g, use_llm=False)
            self.assertTrue(res["ok"])
            self.assertEqual(res["goal"], g)
            self.assertEqual(res["goalLabel"], label)
            openings[g] = res["phoneScripts"]["opening"]

        self.assertEqual(len(set(openings.values())), len(expected_labels))

        custom_res = self.brief_engine.generate_brief(
            "Alice Chen",
            goal="custom",
            custom_goal="续签年度维保并升级私有部署",
            use_llm=False,
        )
        self.assertEqual(custom_res["goal"], "custom")
        self.assertEqual(custom_res["goalLabel"], "续签年度维保并升级私有部署")
        self.assertIn("续签年度维保并升级私有部署", custom_res["phoneScripts"]["opening"])
        self.assertIn("续签年度维保并升级私有部署", custom_res["phoneScripts"]["closing"])

    def test_09_soul_memory_profiler_moments_provider_compat_and_enhancement(self) -> None:
        # (a) Legacy call without `moments_provider` remains 100% compatible
        hist_dir = self.tmp_path / "soul_test" / "contacts"
        hist_dir.mkdir(parents=True, exist_ok=True)
        (hist_dir / "王明_history.json").write_text(
            json.dumps(
                {
                    "target": "王明",
                    "matchedTitle": "王明",
                    "records": [
                        {"kind": "message", "direction": "peer", "text": "明天周三我们对齐下方案吧", "timeMarker": "10:00"},
                        {"kind": "message", "direction": "self", "text": "好呀，没问题", "timeMarker": "10:02"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        legacy_profiler = SoulMemoryProfiler(
            histories_dir=hist_dir,
            reports_dir=self.tmp_path / "soul_test" / "reports_legacy",
            store_path=self.tmp_path / "soul_test" / "legacy.json",
        )
        legacy_res = legacy_profiler.build_profiles(target="王明")
        self.assertTrue(legacy_res["ok"])
        self.assertEqual(legacy_res["contactCount"], 1)
        legacy_cp = legacy_res["contactProfiles"][0]
        self.assertEqual(legacy_cp["recentMomentsCount"], 0)

        # (b) With `moments_provider`, enriches `facts`, `coreTopics`, and `recentMomentsCount`
        def fake_moments_provider(contact_name: str):
            if contact_name == "王明":
                return {
                    "ok": True,
                    "contact": "王明",
                    "authored": [
                        {
                            "key": "m1",
                            "author": "王明",
                            "text": "周末带娃去香山爬山，顺便买了杯手冲咖啡 #户外生活#",
                            "attachments": [],
                            "timeText": "昨天",
                            "isAd": False,
                        },
                        {
                            "key": "m2",
                            "author": "王明",
                            "text": "在看《架构整洁之道》，思考团队 AI Agent 落地",
                            "attachments": [],
                            "timeText": "3天前",
                            "isAd": False,
                        },
                    ],
                    "interactedOnMine": [{"postKey": "mine1", "kind": "like"}],
                    "stats": {"authoredCount": 2},
                }
            raise RuntimeError("transient provider error")

        enhanced_profiler = SoulMemoryProfiler(
            histories_dir=hist_dir,
            reports_dir=self.tmp_path / "soul_test" / "reports_enh",
            store_path=self.tmp_path / "soul_test" / "enh.json",
            moments_provider=fake_moments_provider,
        )
        enh_res = enhanced_profiler.build_profiles(target="王明")
        self.assertTrue(enh_res["ok"])
        cp = enh_res["contactProfiles"][0]
        self.assertEqual(cp["recentMomentsCount"], 2)
        fact_blob = "\n".join(f["content"] for f in cp["memories"]["facts"])
        self.assertIn("香山爬山", fact_blob)
        self.assertIn("架构整洁之道", fact_blob)
        self.assertIn("朋友圈互动", fact_blob)
        topics_blob = " ".join(cp["coreTopics"])
        self.assertTrue("户外" in topics_blob or "AI/技术产品" in topics_blob)

        # (c) Moments-only contact when target isn't in chat histories + error resilience
        only_moments_profiler = SoulMemoryProfiler(
            histories_dir=self.tmp_path / "empty_hist",
            reports_dir=self.tmp_path / "soul_test" / "reports_only",
            store_path=self.tmp_path / "soul_test" / "only.json",
            moments_provider=lambda name: (
                {
                    "ok": True,
                    "authored": [
                        {"key": "m9", "author": name, "text": "下周出差深圳拜访客户", "timeText": "刚刚"}
                    ],
                }
                if name == "赵敏"
                else (_ for _ in ()).throw(RuntimeError("boom"))
            ),
        )
        res_zm = only_moments_profiler.build_profiles(target="赵敏")
        self.assertEqual(res_zm["contactCount"], 1)
        self.assertEqual(res_zm["contactProfiles"][0]["recentMomentsCount"], 1)
        self.assertIn("深圳拜访客户", res_zm["contactProfiles"][0]["memories"]["facts"][0]["content"])

        # Faulty moments provider does not crash build_profiles
        res_err = only_moments_profiler.build_profiles(target="不存在的人")
        self.assertTrue(res_err["ok"])
        self.assertEqual(res_err["contactCount"], 0)

    def test_10_real_moments_store_integration_with_get_posts_for_contact(self) -> None:
        if not callable(getattr(self.engine.moments, "get_posts_for_contact", None)):
            self.skipTest("moments_hub.get_posts_for_contact not present yet")
        self.engine.moments.store.save_read(
            [
                {
                    "key": "mom_real_1",
                    "author": "林雪",
                    "text": "今天完成了新产品的灰度上线，周末准备休息一下",
                    "attachments": [],
                    "timeText": "2小时前",
                    "source": "",
                    "publishedEstimate": "2026-11-25T06:00:00+00:00",
                    "likes": ["号主本人"],
                    "comments": [{"author": "号主本人", "replyTo": "", "text": "恭喜上线！"}],
                    "isAd": False,
                    "isOwn": False,
                    "likedByMe": True,
                    "commentedByMe": True,
                    "partial": False,
                },
                {
                    "key": "mom_real_own",
                    "author": "号主本人",
                    "text": "分享一篇自动化架构复盘",
                    "attachments": [],
                    "timeText": "昨天",
                    "source": "",
                    "publishedEstimate": "2026-11-24T06:00:00+00:00",
                    "likes": ["林雪"],
                    "comments": [{"author": "林雪", "replyTo": "", "text": "写得很透彻！"}],
                    "isAd": False,
                    "isOwn": True,
                    "likedByMe": False,
                    "commentedByMe": False,
                    "partial": False,
                },
            ],
            owner="号主本人",
        )
        res = self.brief_engine.generate_brief("林雪", goal="care", use_llm=False)
        self.assertTrue(res["ok"])
        self.assertEqual(res["dataCoverage"]["momentsPosts"], 1)
        # likedByMe(1) + commentedByMe(1) + likedMyPosts(1) + commentedMyPosts(1) = 4
        self.assertEqual(res["dataCoverage"]["momentsMutualHits"], 4)
        self.assertEqual(res["momentsInsights"]["recentPosts"][0]["key"], "mom_real_1")
        self.assertTrue(any("灰度上线" in ib for ib in res["momentsInsights"]["icebreakers"]))

    def test_11_baseline_opening_strips_or_replaces_urls(self) -> None:
        # Case A: pure URL message -> replaced with natural spoken phrase, zero raw http/https
        (self.contacts_dir / "url_only_history.json").write_text(
            json.dumps(
                {
                    "target": "测试链接好友",
                    "matchedTitle": "测试链接好友",
                    "records": [
                        {
                            "kind": "message",
                            "direction": "peer",
                            "text": "https://yobot.yokoagi.com/",
                            "timeMarker": "10:15",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        res_only = self.brief_engine.generate_brief("测试链接好友", goal="general", use_llm=False)
        self.assertTrue(res_only["ok"])
        opening_only = res_only["phoneScripts"]["opening"]
        self.assertNotIn("http://", opening_only)
        self.assertNotIn("https://", opening_only)
        self.assertIn("之前发过来的链接", opening_only)

        # Case B: mixed text + URL -> URL removed, surrounding context kept naturally
        (self.contacts_dir / "url_mixed_history.json").write_text(
            json.dumps(
                {
                    "target": "测试混合链接好友",
                    "matchedTitle": "测试混合链接好友",
                    "records": [
                        {
                            "kind": "message",
                            "direction": "peer",
                            "text": "帮我看下 https://yobot.yokoagi.com/ 这个怎么部署",
                            "timeMarker": "11:00",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        res_mixed = self.brief_engine.generate_brief("测试混合链接好友", goal="followup", use_llm=False)
        self.assertTrue(res_mixed["ok"])
        opening_mixed = res_mixed["phoneScripts"]["opening"]
        self.assertNotIn("http://", opening_mixed)
        self.assertNotIn("https://", opening_mixed)
        self.assertIn("帮我看下", opening_mixed)


if __name__ == "__main__":
    unittest.main()
