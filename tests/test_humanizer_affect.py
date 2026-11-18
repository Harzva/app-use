"""Unit tests for v2.4.73 humanizer/affect engine, card classification/click-read, and zero-drop delta tracking."""

from __future__ import annotations

import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from wechat_control import ALL_CAPABILITIES
from wechat_control.engine import WeChatControlEngine
from wechat_control.humanizer_affect import (
    GOD_CORE_PERSONA_PARTITIONS,
    EuphoriaAffectEngine,
    blend_persona_partitions,
    humanize_wechat_reply,
    parse_sibyl_feedback_command,
)
from wechat_control.live_inspector import WeChatLiveInspector
from wechat_control.multi_window_scheduler import UnreadDeltaTracker


def _write_solid_png(path: Path, width: int = 800, height: int = 1100) -> None:
    raw = b"".join(b"\x00" + (b"\xf5\xf5\xf5" * width) for _ in range(height))

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


class TestHumanizerAffectAndCardRead(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wx_v2473_"))
        self.engine = WeChatControlEngine(
            audit_log_path=self.tmp / "audit.jsonl",
            auth_file_path=self.tmp / "auth.json",
            bindings_file_path=self.tmp / "bindings.json",
            models_config_path=self.tmp / "models.json",
            model_http_requester=lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError),
            knowledge_db_path=self.tmp / "kb.sqlite",
            personas_file_path=self.tmp / "personas.json",
            snapshots_dir=self.tmp / "snapshots",
            reports_dir=self.tmp / "reports",
        )
        self.engine.auth_grant(ALL_CAPABILITIES, authorized_by="test-v2473")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_god_core_16_partitions_and_affect_decay(self) -> None:
        self.assertEqual(len(GOD_CORE_PERSONA_PARTITIONS), 16)
        blended = blend_persona_partitions("warm-friend")
        self.assertEqual(blended["partitionCount"], 16)
        self.assertGreater(len(blended["activePartitions"]), 8)
        for part, weights in blended["activePartitions"].items():
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=2, msg=f"Partition {part} not normalized")

        affect = EuphoriaAffectEngine(self.tmp / "affect.json", half_life_minutes=30.0)
        res1 = affect.appraise_and_update("微信ClawBot", "卧槽你还真分一二三点，你是AI吧，哈哈笑死", now_ts=1000.0)
        self.assertEqual(res1["trigger"], "banter_playful")
        self.assertGreater(res1["controls"].valence, 0.25)
        self.assertEqual(res1["controls"].recommended_emote, "[旺柴]")

        # Decay after 90 minutes (3 half-lives -> returns closer to baseline)
        res2 = affect.appraise_and_update("微信ClawBot", "嗯", now_ts=1000.0 + 90 * 60.0)
        self.assertLess(res2["controls"].valence, res1["controls"].valence)

    def test_humanize_wechat_reply_strips_ai_lists_particles_and_period(self) -> None:
        ai_slop = "哈哈收到啦！第一、LoopForge是开源工作流；第二、它支持人工审批；第三、适合本地用。总的来说很不错！"
        clean = humanize_wechat_reply(ai_slop, persona_id="warm-friend", allow_emote=False)
        self.assertNotIn("哈哈收到啦", clean)
        self.assertNotIn("第一", clean)
        self.assertNotIn("第二", clean)
        self.assertNotIn("第三", clean)
        self.assertNotIn("；", clean)
        self.assertFalse(clean.endswith("。"))

        num_slop = "1. 先检查网络\n2. 再看权限\n3. 最后重启一下。"
        clean_num = humanize_wechat_reply(num_slop, persona_id="owner-digital-twin", allow_emote=False)
        self.assertNotRegex(clean_num, r"(?:^|\s)[123]\.")
        self.assertFalse(clean_num.endswith("。"))

        sibyl = parse_sibyl_feedback_command("s3 下次先说核心结论再聊细节")
        self.assertEqual(sibyl, {"code": "s3", "rating": "suggest", "suggestion": "下次先说核心结论再聊细节"})

    def test_wide_popout_card_classification_unread_delta_and_click_read(self) -> None:
        snap = self.tmp / "snapshots" / "xinan_14393.png"
        snap.parent.mkdir(parents=True, exist_ok=True)
        _write_solid_png(snap, 1523, 1160)

        ocr_payload = {
            "ok": True,
            "isMainWindow": False,
            "splitX": 0.0,
            "windowTitle": "联系人A",
            "windowBounds": {"x": 927, "y": 177, "width": 1523, "height": 1160},
            "elements": [
                {"text": "联系人A", "bbox": {"x": 13, "y": 49, "width": 31, "height": 18}, "center": {"x": 29, "y": 58}},
                {"text": "、6…", "bbox": {"x": 1399, "y": 46, "width": 109, "height": 19}, "center": {"x": 1453, "y": 55}},
                {"text": "10:52", "bbox": {"x": 744, "y": 230, "width": 35, "height": 11}, "center": {"x": 761, "y": 236}},
                {"text": "宁德时代董事长曾毓群反思：", "bbox": {"x": 93, "y": 283, "width": 139, "height": 14}, "center": {"x": 163, "y": 290}},
                {"text": "我们为什么这么拼？", "bbox": {"x": 115, "y": 299, "width": 95, "height": 13}, "center": {"x": 163, "y": 305}},
                {"text": "W 券商中国福大众", "bbox": {"x": 77, "y": 485, "width": 117, "height": 22}, "center": {"x": 136, "y": 496}},
                {"text": "ISPRS | CASGM：武大提出显著几何", "bbox": {"x": 80, "y": 540, "width": 224, "height": 16}, "center": {"x": 191, "y": 548}},
                {"text": "差异下依然稳健的光学-SAR影像..", "bbox": {"x": 80, "y": 560, "width": 219, "height": 16}, "center": {"x": 189, "y": 568}},
                {"text": "M 遥感与深度学习", "bbox": {"x": 82, "y": 644, "width": 102, "height": 13}, "center": {"x": 133, "y": 651}},
                {"text": "这个视频是什么意思呢？", "bbox": {"x": 80, "y": 848, "width": 151, "height": 18}, "center": {"x": 155, "y": 857}},
                {"text": "你发的其实是 GitHub 仓库链接", "bbox": {"x": 900, "y": 905, "width": 300, "height": 18}, "center": {"x": 1050, "y": 913}},
                {"text": "最新的我发送的这个微信文章链接，还有视频号你看不到吗", "bbox": {"x": 80, "y": 981, "width": 365, "height": 22}, "center": {"x": 262, "y": 992}},
            ],
        }
        structured = self.engine.inspector.extract_structured_bubbles(ocr_payload, snapshot_path=snap)
        self.assertEqual(structured["headerTitle"], "联系人A")
        bubbles = structured["bubbles"]
        # Window title at y=58 must NOT leak into bubbles[0]
        self.assertNotEqual(bubbles[0]["text"], "联系人A")
        types = [b["mediaType"] for b in bubbles]
        self.assertIn("channels_video", types)
        self.assertIn("wechat_article", types)

        delta = UnreadDeltaTracker.extract_unread_delta(bubbles)
        card_types = [c["mediaType"] for c in delta["activeMediaCards"]]
        self.assertEqual(card_types, ["channels_video", "wechat_article"])

        # Simulate active click-to-open reader window for the wechat_article bubble
        calls = []
        win_state = {"opened": False}

        def fake_native(args, timeout=15.0):
            calls.append(list(args))
            cmd = args[0]
            if cmd == "list-app-windows":
                wins = [{"windowID": 14393, "title": "联系人A", "isMainWindow": False, "bounds": {"x": 927, "y": 177, "width": 1523, "height": 1160}}]
                if win_state["opened"]:
                    wins.append({"windowID": 15001, "title": "ISPRS | CASGM", "isMainWindow": False, "bounds": {"x": 300, "y": 100, "width": 820, "height": 900}})
                return {"ok": True, "windows": wins}
            if cmd == "click":
                win_state["opened"] = True
                return {"ok": True}
            if cmd == "capture-ocr":
                out_flag = args[args.index("--out") + 1] if "--out" in args else ""
                if out_flag:
                    _write_solid_png(Path(out_flag), 820, 900)
                return {"ok": True, "elements": [{"text": "武汉大学团队提出CASGM共视区域引导光学SAR图像匹配方法"}]}
            if cmd == "ocr":
                if "--out" in args:
                    _write_solid_png(Path(args[args.index("--out") + 1]), 320, 200)
                return {"ok": True, "imageWidth": 320, "imageHeight": 200, "elements": [{"text": "ISPRS CASGM 遥感与深度学习"}]}
            return {"ok": True}

        self.engine._run_native = fake_native  # type: ignore[method-assign]
        article_bubble = next(b for b in bubbles if b["mediaType"] == "wechat_article")
        deep = self.engine.media_analyzer.click_and_deep_read_bubble(
            article_bubble,
            window_bounds={"x": 927, "y": 177, "width": 1523, "height": 1160},
            window_id=14393,
            snapshot_path=snap,
            contact="联系人A",
            click_to_open=True,
        )
        self.assertTrue(deep["ok"])
        self.assertTrue(deep["clickedToOpen"])
        self.assertEqual(deep["openedViewerWindowID"], 15001)
        self.assertTrue(deep["note"].startswith("[公众号文章深读:"))
        self.assertIn("CASGM", deep["ocrText"])

    def test_dual_product_coevolution_and_multimodal_sparring(self) -> None:
        from wechat_control import evaluate_turn_human_likeness

        high_q = evaluate_turn_human_likeness(
            "南角离阳台两米多，下午有西晒，我先把快递盒挪走，半黄叶子先留着 [旺柴]",
            incoming_text="你家南边那个角晒不晒得到太阳，半黄叶子剪了没",
        )
        low_q = evaluate_turn_human_likeness(
            "哈哈收到啦！第一、先挪走快递盒；第二、绿萝需要散光。",
            incoming_text="绿萝怎么养",
        )
        self.assertGreaterEqual(high_q["humanLikenessScore"], 90)
        self.assertEqual(high_q["grade"], "S")
        self.assertLess(low_q["humanLikenessScore"], 50)
        self.assertIn("contains_list_enumeration", low_q["issues"])
        self.assertIn("contains_ai_modal_slop", low_q["issues"])

        res = self.engine.coevolution.record_sparring_turn(
            target="微信ClawBot",
            incoming_text="卧槽你刚才还分一二三点，你是AI吧？顺便看看这视频号还有那张图片链接",
            reply_text="被你看出来了，下次不列点直接说人话，那张图和视频号要点我都看清了 [捂脸]",
            persona_id="warm-friend",
            generation_mode="llm_magpie",
            model_used="auto/deepseek-v4-pro",
            media_notes=[
                "[链接深读:GitHub LoopForge] 腾讯开源本地多Agent人工审批工作流",
                "[图片识别:结构对比图] 展示了三阶段防抢鼠标状态机流程图",
                "[视频号深读:九紫离火运客厅布局] 建议保持阳台过道通风采光",
            ],
            dispatched_receipt={"tasks": [{"kind": "card_deep_read", "clickedToOpen": True}]},
            send_receipt={"ok": True, "status": "sent"},
            popout_meta={"popoutWindowID": 14013, "zeroSwitch": True},
        )
        self.assertTrue(res["ok"])
        summary = res["summary"]
        vlse = summary["vlseBotLayer"]
        rpa = summary["wechatRpaLayer"]
        self.assertEqual(vlse["totalTurns"], 1)
        self.assertEqual(vlse["distilledKnowledgeCount"], 3)
        self.assertGreaterEqual(vlse["evolvedRulesCount"], 1)
        self.assertEqual(rpa["zeroSwitchTurns"], 1)
        self.assertEqual(rpa["zeroSwitchRate"], 100.0)
        self.assertEqual(rpa["cardClickOpens"], 1)
        self.assertEqual(rpa["multimodalDeepReadTotal"], 3)
        self.assertEqual(rpa["multimodalByKind"]["link"], 1)
        self.assertEqual(rpa["multimodalByKind"]["image"], 1)
        self.assertEqual(rpa["multimodalByKind"]["channels_video"], 1)

        # Learned partition overrides & style rules flow back into PersonaSwitchEngine
        overrides = self.engine.coevolution.get_contact_partition_overrides("微信ClawBot")
        rules = self.engine.coevolution.get_contact_style_rules("微信ClawBot")
        self.assertIsNotNone(overrides)
        self.assertTrue(rules)
        smart = self.engine.personas.generate_smart_reply(
            "微信ClawBot",
            "这次还不错",
            knowledge_store=self.engine.knowledge,
            memory_context={
                "coevolutionPartitionOverrides": overrides,
                "coevolutionStyleRules": rules,
            },
            use_llm=False,
        )
        self.assertTrue(smart["ok"])
        self.assertTrue(Path(summary["syncPath"]).is_file())

    def test_official_wechat_emojis_normalization_and_sticker_sender(self) -> None:
        from wechat_control import OFFICIAL_WECHAT_EMOJIS, normalize_wechat_emojis

        # Non-WeChat shortcodes like [思考] / [笑哭] / [doge] must normalize to official WeChat graphical emojis
        self.assertEqual(normalize_wechat_emojis("压力确实大 [思考]"), "压力确实大 [机智]")
        self.assertEqual(normalize_wechat_emojis("笑不活了 [笑哭]"), "笑不活了 [破涕为笑]")
        self.assertEqual(normalize_wechat_emojis("太强了 [doge]"), "太强了 [旺柴]")
        # Media tags must NOT be corrupted
        self.assertEqual(normalize_wechat_emojis("[图片] 看看这个 [视频]"), "[图片] 看看这个 [视频]")

        # humanize_wechat_reply always emits official WeChat graphical emojis for real-human contacts
        affect = EuphoriaAffectEngine(self.tmp / "affect_emoji.json")
        ctrl = affect.appraise_and_update("联系人B", "这个视频详细说下核心点", now_ts=2000.0)["controls"]
        self.assertGreaterEqual(ctrl.emote_probability, 0.75)
        self.assertNotEqual(ctrl.recommended_emote, "[思考]")
        self.assertIn(ctrl.recommended_emote.strip("[]"), OFFICIAL_WECHAT_EMOJIS)

        replied = humanize_wechat_reply(
            "宁德时代那段主要讲技术迭代太快了，得抱团应对压力[思考]。",
            persona_id="warm-companion",
            affect_controls=ctrl,
            allow_emote=True,
        )
        self.assertNotIn("[思考]", replied)
        self.assertIn("[机智]", replied)

        # send_wechat_sticker supports both emoji shortcode and native sticker panel dispatch
        native_calls = []

        def fake_sticker_native(args, timeout=15.0):
            native_calls.append(list(args))
            if args[0] == "list-app-windows":
                return {
                    "ok": True,
                    "windows": [{"windowID": 14393, "title": "联系人A", "isMainWindow": False, "bounds": {"x": 927, "y": 177, "width": 1523, "height": 1160}}],
                }
            if args[0] == "send-sticker":
                return {"ok": True, "sent": False, "dryRun": True, "tab": "favorites", "slot": 0}
            return {"ok": True, "sent": False}

        self.engine._run_native = fake_sticker_native  # type: ignore[method-assign]
        res_panel = self.engine.send_wechat_sticker("联系人A", tab="favorites", slot=0, dry_run=True, confirm_send=False)
        self.assertTrue(res_panel["ok"])
        self.assertTrue(any(c[0] == "send-sticker" and "--tab" in c and "favorites" in c for c in native_calls))

        res_code = self.engine.send_wechat_sticker("联系人A", emoji_code="思考", dry_run=True, confirm_send=False)
        self.assertTrue(res_code["ok"])
        self.assertEqual(res_code["status"], "dry_run_ok")

    def test_v2476_memory_interrupt_keyboard_and_image_tools(self) -> None:
        from wechat_control.human_activity_guard import HumanActivityGuard

        # 1) Dynamic User Memory Management (`ingest_live_turn` + `get_contact_memory_context`)
        mem_res = self.engine.soul_profiler.ingest_live_turn(
            "微信ClawBot",
            "我家玄关只有90公分宽，我妈喜欢在南墙窗台养绿萝",
            "90公分宽建议做半高鞋柜留空过道，绿萝别直晒 [旺柴]",
            media_notes=["[公众号文章深读:玄关采光布局] 留白通风减少潮湿"],
        )
        self.assertTrue(mem_res["ok"])
        self.assertGreaterEqual(mem_res["factsCount"], 1)
        mem_ctx = self.engine.soul_profiler.get_contact_memory_context("微信ClawBot")
        self.assertIn("我家玄关只有90公分宽", mem_ctx["memoryPromptSnippet"])
        self.assertIn("90公分宽", mem_ctx["rollingSummary"])

        # 2) Interrupted Paste Rollback & Auto-Resume in `poll_once`
        self.engine.bind_contact("测试好友Z", ai_persona="warm-friend", auto_reply_enabled=True)
        attempt_state = {"n": 0}
        snap_src = self.tmp / "snapshots" / "poll_interrupt.png"
        snap_src.parent.mkdir(parents=True, exist_ok=True)
        _write_solid_png(snap_src, 900, 900)

        def fake_poll_native(args, timeout=15.0):
            cmd = args[0]
            if cmd == "list-app-windows":
                return {
                    "ok": True,
                    "windows": [
                        {"windowID": 20001, "title": "测试好友Z", "isMainWindow": False, "bounds": {"x": 100, "y": 100, "width": 700, "height": 800}},
                    ],
                }
            if cmd == "capture-ocr":
                if "--out" in args:
                    _write_solid_png(Path(args[args.index("--out") + 1]), 700, 800)
                return {
                    "ok": True,
                    "isMainWindow": False,
                    "splitX": 0.0,
                    "windowTitle": "测试好友Z",
                    "windowBounds": {"x": 100, "y": 100, "width": 700, "height": 800},
                    "elements": [
                        {"text": "测试好友Z", "bbox": {"x": 15, "y": 40, "width": 70, "height": 18}, "center": {"x": 50, "y": 49}},
                        {"text": "17:10", "bbox": {"x": 330, "y": 180, "width": 40, "height": 12}, "center": {"x": 350, "y": 186}},
                        {"text": "请问我家玄关90公分够不够放鞋柜？", "bbox": {"x": 60, "y": 240, "width": 260, "height": 22}, "center": {"x": 190, "y": 251}},
                    ],
                }
            if cmd == "paste-and-verify":
                attempt_state["n"] += 1
                if attempt_state["n"] == 1:
                    return {"ok": False, "error_code": "interrupted_during_paste", "retryable": True, "error": "Human interrupted paste"}
                return {"ok": True, "sent": True, "verified": True, "readbackSource": "ax"}
            return {"ok": True}

        self.engine._run_native = fake_poll_native  # type: ignore[method-assign]
        p1 = self.engine.monitor.poll_once(target_filter="测试好友Z", auto_reply=True, confirm_send=True, ignore_human_guard=True)
        self.assertEqual(p1["repliesDispatched"], 0)
        self.assertEqual(p1["actions"][0]["status"], "interrupted_during_paste")
        # Dedup must have rolled back so immediate retry on cycle 2 is NOT blocked_duplicate
        self.engine.antiban.min_reply_gap_seconds = 0
        p2 = self.engine.monitor.poll_once(target_filter="测试好友Z", auto_reply=True, confirm_send=True, ignore_human_guard=True)
        self.assertEqual(p2["repliesDispatched"], 1)
        self.assertEqual(p2["actions"][0]["status"], "replied")
        self.assertTrue(p2["actions"][0].get("resumedFromInterruption"))

        # 3) Hardware keyboard activity stops automation immediately (never exempted by paste-and-verify)
        clock = {"now": 5000.0}
        guard = HumanActivityGuard(
            state_path=self.tmp / "kb_guard.json",
            clock_fn=lambda: clock["now"],
            default_idle_resume_seconds=45.0,
            default_cooldown_seconds=45.0,
        )
        guard.record_rpa_action(action="paste-and-verify", cursor_x=400.0, cursor_y=300.0)
        clock["now"] = 5000.5
        res_kb = guard.check_can_operate({
            "anyInputIdleSeconds": 0.4,
            "mouseIdleSeconds": 60.0,
            "keyboardIdleSeconds": 0.4,
            "hardwareKeyboardIdleSeconds": 0.4,
            "keyboardActive": True,
            "cursorPosition": {"x": 400.0, "y": 300.0},
        })
        self.assertFalse(res_kb["canOperate"])
        self.assertEqual(res_kb["status"], "human_active_cooldown")
        self.assertIn("keyboard", res_kb["triggerReason"])

        # 4) Web image search fallback & image annotation dry-run
        sample_img = self.tmp / "snapshots" / "sample_annot.png"
        _write_solid_png(sample_img, 480, 320)

        def fake_media_native(args, timeout=15.0):
            cmd = args[0]
            if cmd == "render-test-image":
                out_p = Path(args[args.index("--out") + 1])
                _write_solid_png(out_p, 600, 360)
                return {"ok": True, "outPath": str(out_p)}
            if cmd == "annotate-image":
                out_p = Path(args[args.index("--out") + 1])
                _write_solid_png(out_p, 480, 320)
                return {"ok": True, "outPath": str(out_p), "annotatedCount": 2, "matchedBoxes": [{"index": 1}, {"index": 2}]}
            if cmd == "list-app-windows":
                return {"ok": True, "windows": [{"windowID": 20001, "title": "测试好友Z", "isMainWindow": False, "bounds": {"x": 100, "y": 100, "width": 700, "height": 800}}]}
            if cmd == "paste-image":
                return {"ok": True, "sent": False, "dryRun": True}
            return {"ok": True}

        self.engine._run_native = fake_media_native  # type: ignore[method-assign]
        ann_send = self.engine.annotate_and_send_peer_image(
            "测试好友Z",
            image_path=str(sample_img),
            keywords=["90公分"],
            note="红框处尺寸确认",
            boxes=[{"x": 40, "y": 50, "width": 160, "height": 40}],
            dry_run=True,
            confirm_send=False,
        )
        self.assertTrue(ann_send["ok"])
        self.assertEqual(ann_send["annotation"]["annotatedCount"], 2)

        # Avoid outbound live network call inside unit tests by mocking urlopen to use local fallback cleanly
        import urllib.request as _ur
        orig_urlopen = _ur.urlopen
        try:
            _ur.urlopen = lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError("offline test"))  # type: ignore[assignment]
            web_send = self.engine.search_and_send_web_image(
                "测试好友Z",
                "极简玄关矮柜",
                dry_run=True,
                confirm_send=False,
            )
            self.assertTrue(web_send["ok"])
            self.assertEqual(web_send["search"]["sourceMode"], "local_visual_fallback")
        finally:
            _ur.urlopen = orig_urlopen  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
