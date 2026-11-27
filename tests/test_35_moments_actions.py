"""朋友圈互动（_click_screen / like / unlike / comment）、联系人动态聚合与 AI 拟评全 Mock 测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wechat_control import moments_feed as mf
from wechat_control.auth_gate import StudioPluginUnauthorizedError
from wechat_control.moments_actions import MomentsInteractor
from wechat_control.moments_hub import (
    MOMENTS_CAP_DRY_RUN,
    MOMENTS_CAP_LIVE,
    MOMENTS_CAP_READ,
    MomentsFlowError,
    WeChatMomentsHub,
)
from tests.test_34_moments_feed import COL, WIN, el, frame, post_rows


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    def log(self, action: str, status: str, detail=None) -> None:
        self.events.append({"action": action, "status": status, "detail": detail or {}})


class FakeHumanGuard:
    def __init__(self, can_operate: bool = True) -> None:
        self.can_operate = can_operate

    def check_can_operate(self):
        return {"canOperate": self.can_operate, "reason": "ok" if self.can_operate else "mouse_active"}


class FakeModels:
    def __init__(self, *, enabled: bool = True, reply=None, exc: Exception | None = None) -> None:
        self._enabled = enabled
        self._reply = reply
        self._exc = exc
        self.calls = []

    def is_llm_enabled(self) -> bool:
        return self._enabled

    def generate_chat_reply(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._exc is not None:
            raise self._exc
        if callable(self._reply):
            return self._reply(messages, **kwargs)
        return self._reply


class FakeSoulProfiler:
    def __init__(self, ctx=None, *, exc: Exception | None = None) -> None:
        self._ctx = ctx or {}
        self._exc = exc

    def get_contact_memory_context(self, target: str):
        if self._exc is not None:
            raise self._exc
        return self._ctx


class FakeEngine:
    def __init__(
        self,
        root: Path,
        *,
        grants=None,
        can_operate: bool = True,
        models=None,
        soul_profiler=None,
    ) -> None:
        self.inspector = SimpleNamespace(
            reports_dir=root / "reports",
            snapshots_dir=root / "snapshots",
        )
        self.inspector.reports_dir.mkdir(parents=True, exist_ok=True)
        self.inspector.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.human_guard = FakeHumanGuard(can_operate=can_operate)
        self.audit = FakeAudit()
        self.models = models
        self.soul_profiler = soul_profiler
        self.grants = set(grants if grants is not None else {MOMENTS_CAP_READ, MOMENTS_CAP_DRY_RUN, MOMENTS_CAP_LIVE})

    def _require(self, cap: str) -> None:
        if cap not in self.grants:
            raise StudioPluginUnauthorizedError(f"missing {cap}", capability=cap)


class FakeWeChatDriver:
    """全 Mock 原生微信驱动，按真实 4.2.0 坐标仿真 发现/朋友圈/胶囊/输入框/退出。"""

    def __init__(
        self,
        *,
        bounds=None,
        owner: str = "号主小号",
        author: str = "张三",
        text_lines=("今天天气真不错",),
        time_text: str = "3小时前",
        initial_liked: bool = False,
        verify_like_succeeds: bool = True,
        verify_comment_succeeds: bool = True,
        readback_override: str | None = None,
        interrupt_on_hid_call: int | None = None,
        interrupt_reason: str = "keyboard",
    ) -> None:
        self.bounds = dict(bounds or {"x": 100.0, "y": 50.0, "width": WIN["width"], "height": WIN["height"]})
        self.owner = owner
        self.author = author
        self.text_lines = list(text_lines)
        self.time_text = time_text
        self.liked = initial_liked
        self.comments = []
        self.verify_like_succeeds = verify_like_succeeds
        self.verify_comment_succeeds = verify_comment_succeeds
        self.readback_override = readback_override
        self.interrupt_on_hid_call = interrupt_on_hid_call
        self.interrupt_reason = interrupt_reason

        self.in_moments = True
        self.popover_open = False
        self.input_open = False
        self.typed_text = ""
        self.clipboard = "orig-clip"
        self.hid_calls = 0
        self.native_calls = []
        self.clicks = []
        self.keys = []
        self.last_click = {"x": 0.0, "y": 0.0}

        # Footer y matches post_rows(y=360) with len(text_lines): 360 + 24 * (1 + len(text_lines))
        self.footer_x = 1271.0
        self.footer_y = 360.0 + 24.0 * (1 + len(self.text_lines))
        self.like_screen_pt = {"x": self.bounds["x"] + self.footer_x - 150.0, "y": self.bounds["y"] + self.footer_y}
        self.comment_screen_pt = {"x": self.bounds["x"] + self.footer_x - 60.0, "y": self.bounds["y"] + self.footer_y}
        self.input_local_y = self.footer_y + 68.0
        self.send_local_x = 1150.0
        self.send_local_w = 60.0

    def _current_feed_cap(self):
        if not self.in_moments:
            # 聊天主界面（非发现页）
            return {
                "ok": True,
                "imageWidth": WIN["width"],
                "imageHeight": WIN["height"],
                "windowBounds": dict(self.bounds),
                "elements": [el("文件传输助手", 140, 120), el("张三", 140, 200)],
            }
        likes_str = f"V {self.owner}" if self.liked else ""
        comment_strs = [f"{c['author']}：{c['text']}" for c in self.comments]
        extra = []
        if self.input_open:
            if self.typed_text:
                extra.append(el(self.typed_text, 845, self.input_local_y, width=240))
            else:
                extra.append(el("评论", 845, self.input_local_y, width=30))
            extra.append(el("发送", self.send_local_x, self.input_local_y + 58.0, width=self.send_local_w))
        rows, _ = post_rows(
            author=self.author,
            lines=self.text_lines,
            time_text=self.time_text,
            likes=likes_str,
            comments=comment_strs,
            extra=extra,
        )
        cap = frame((rows, 360), owner=self.owner)
        cap["windowBounds"] = dict(self.bounds)
        return cap

    def run_native(self, args, timeout=20.0):
        self.native_calls.append((list(args), timeout))
        cmd = args[0]
        if cmd == "status":
            return {"ok": True, "wechatRunning": True, "windows": [{"bounds": dict(self.bounds)}]}
        if cmd == "activate":
            return {"ok": True}
        if cmd == "capture-ocr":
            return self._current_feed_cap()
        if cmd == "capture-region":
            label = "取消" if self.liked else "赞"
            return {
                "ok": True,
                "elements": [
                    {"text": label, "screenCenter": dict(self.like_screen_pt)},
                    {"text": "评论", "screenCenter": dict(self.comment_screen_pt)},
                ],
            }
        if cmd == "click":
            sx = float(args[args.index("--x") + 1])
            sy = float(args[args.index("--y") + 1])
            self.clicks.append((sx, sy))
            self.last_click = {"x": sx, "y": sy}
            lx = sx - self.bounds["x"]
            ly = sy - self.bounds["y"]
            # 点到左栏聊天图标 -> 切回聊天
            if abs(lx - 30.0) < 10.0 and abs(ly - 118.0) < 10.0:
                self.in_moments = False
                self.popover_open = False
                self.input_open = False
            # 点到「··」打开弹层
            elif abs(lx - self.footer_x) < 12.0 and abs(ly - self.footer_y) < 12.0:
                self.popover_open = True
            # 点到屏幕绝对坐标「赞 / 取消」
            elif abs(sx - self.like_screen_pt["x"]) < 8.0 and abs(sy - self.like_screen_pt["y"]) < 8.0:
                self.popover_open = False
                if self.verify_like_succeeds:
                    self.liked = not self.liked
            # 点到屏幕绝对坐标「评论」
            elif abs(sx - self.comment_screen_pt["x"]) < 8.0 and abs(sy - self.comment_screen_pt["y"]) < 8.0:
                self.popover_open = False
                self.input_open = True
                self.typed_text = ""
            # 点到「发送」按钮
            elif self.input_open and abs(lx - (self.send_local_x + self.send_local_w - 10.0)) < 18.0:
                if self.verify_comment_succeeds and self.typed_text:
                    self.comments.append({"author": self.owner, "replyTo": "", "text": self.typed_text})
                self.input_open = False
                self.typed_text = ""
            return {"ok": True}
        if cmd == "press-key":
            combo = args[args.index("--combo") + 1]
            self.keys.append(combo)
            if combo == "esc":
                self.popover_open = False
                self.input_open = False
                self.typed_text = ""
            elif combo == "cmd+v" and self.input_open:
                self.typed_text = self.readback_override if self.readback_override is not None else self.clipboard
            elif combo == "delete" and self.input_open:
                self.typed_text = ""
            return {"ok": True}
        if cmd == "hid-idle":
            self.hid_calls += 1
            if self.interrupt_on_hid_call is not None and self.hid_calls >= self.interrupt_on_hid_call:
                if self.interrupt_reason == "cursor":
                    return {
                        "ok": True,
                        "hidIdle": {
                            "hardwareKeyboardIdleSeconds": 12.0,
                            "cursorPosition": {"x": self.last_click["x"] + 90.0, "y": self.last_click["y"]},
                        },
                    }
                return {
                    "ok": True,
                    "hidIdle": {
                        "hardwareKeyboardIdleSeconds": 0.4,
                        "cursorPosition": dict(self.last_click),
                    },
                }
            return {
                "ok": True,
                "hidIdle": {
                    "hardwareKeyboardIdleSeconds": 15.0,
                    "cursorPosition": dict(self.last_click),
                },
            }
        return {"ok": True}


class MomentsActionsAndHubTests(unittest.TestCase):
    NOW = 1_800_000_000.0

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_post(
        self,
        hub: WeChatMomentsHub,
        *,
        author: str = "张三",
        text: str = "今天天气真不错",
        time_text: str = "3小时前",
        liked_by_me: bool = False,
        commented_by_me: bool = False,
        is_own: bool = False,
        likes=None,
        comments=None,
        owner: str = "号主小号",
    ) -> str:
        ts = self.NOW - 3 * 3600
        key = mf.post_key(author, text, time_text, ts)
        post = {
            "key": key,
            "author": author,
            "authorConfident": True,
            "text": text,
            "collapsed": False,
            "attachments": [],
            "timeText": time_text,
            "source": "",
            "publishedEstimate": mf._iso(ts),
            "likes": list(likes or ([owner] if liked_by_me else [])),
            "comments": list(comments or []),
            "isAd": False,
            "isOwn": is_own,
            "likedByMe": liked_by_me,
            "commentedByMe": commented_by_me,
            "partial": False,
        }
        hub.store.save_read([post], owner=owner)
        return key

    # ------------------------------------------------------------------
    # 1. _click_screen
    # ------------------------------------------------------------------
    def test_click_screen_success_and_error(self):
        calls = []

        def fake_native(args, timeout=20.0):
            calls.append((args, timeout))
            if args[2] == "999.0":
                return {"ok": False, "error_code": "cg_denied", "error": "no permission"}
            return {"ok": True}

        engine = FakeEngine(self.root)
        hub = WeChatMomentsHub(engine, run_native=fake_native, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)

        hub._click_screen(1234.56, 567.84)
        self.assertEqual(calls[0], (["click", "--x", "1234.6", "--y", "567.8"], 8.0))
        self.assertEqual(hub._last_point, {"x": 1234.56, "y": 567.84})

        with self.assertRaises(MomentsFlowError) as ctx:
            hub._click_screen(999.0, 200.0)
        self.assertEqual(ctx.exception.code, "cg_denied")
        self.assertIn("no permission", str(ctx.exception))

        # Missing error_code defaults to click_failed
        hub_default = WeChatMomentsHub(
            engine,
            run_native=lambda args, timeout=20.0: {"ok": False},
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        with self.assertRaises(MomentsFlowError) as ctx2:
            hub_default._click_screen(10.0, 20.0)
        self.assertEqual(ctx2.exception.code, "click_failed")

    # ------------------------------------------------------------------
    # 2. like / unlike: dry_run, live, already_liked, not_liked, unverified
    # ------------------------------------------------------------------
    def test_like_dry_run_and_live_and_unlike_flows(self):
        drv = FakeWeChatDriver()
        engine = FakeEngine(self.root)
        hub = WeChatMomentsHub(engine, run_native=drv.run_native, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        key = self._seed_post(hub)

        # dry_run: verifies popover and returns wouldClick without clicking like
        dry = hub.interact(post_key=key, action="like", mode="dry_run")
        self.assertTrue(dry["ok"])
        self.assertEqual(dry["results"][0]["status"], "dry_run")
        self.assertEqual(dry["results"][0]["wouldClick"], drv.like_screen_pt)
        self.assertFalse(drv.liked)
        self.assertFalse(drv.in_moments)  # restored to chats

        # live like: clicks absolute screen coords of 赞, verifies in feed, updates store
        drv.in_moments = True
        live = hub.interact(post_key=key, action="like", mode="live")
        self.assertTrue(live["ok"])
        self.assertEqual(live["results"][0]["status"], "verified")
        self.assertEqual(live["results"][0]["clicked"], drv.like_screen_pt)
        self.assertIn((drv.like_screen_pt["x"], drv.like_screen_pt["y"]), drv.clicks)
        self.assertTrue(hub.get_post(key)["post"]["likedByMe"])

        # dry_run unlike: popover shows 取消
        drv.in_moments = True
        unlike_dry = hub.interact(post_key=key, action="unlike", mode="dry_run")
        self.assertTrue(unlike_dry["ok"])
        self.assertEqual(unlike_dry["results"][0]["status"], "dry_run")
        self.assertEqual(unlike_dry["results"][0]["popover"]["likeLabel"], "取消")
        self.assertTrue(drv.liked)

        # live unlike: clicks 取消, verifies removal, updates store
        drv.in_moments = True
        # Advance clock past min_gap_seconds
        hub._clock = lambda: self.NOW + 120.0
        hub.store._now = hub._clock
        hub.store.limiter._now = hub._clock
        unlike_live = hub.interact(post_key=key, action="unlike", mode="live")
        self.assertTrue(unlike_live["ok"])
        self.assertEqual(unlike_live["results"][0]["status"], "verified")
        self.assertFalse(hub.get_post(key)["post"]["likedByMe"])

    def test_already_liked_and_not_liked_reconciliation_and_unverified(self):
        # Local store thinks unliked, live UI already shows 取消
        drv = FakeWeChatDriver(initial_liked=True)
        engine = FakeEngine(self.root)
        hub = WeChatMomentsHub(engine, run_native=drv.run_native, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        key = self._seed_post(hub, liked_by_me=False)

        res = hub.interact(post_key=key, action="like", mode="live")
        self.assertTrue(res["ok"])
        self.assertEqual(res["results"][0]["status"], "skipped")
        self.assertEqual(res["results"][0]["errorCode"], "already_liked")
        self.assertNotIn((drv.like_screen_pt["x"], drv.like_screen_pt["y"]), drv.clicks)
        self.assertTrue(hub.get_post(key)["post"]["likedByMe"])

        # Local store thinks liked, live UI shows 赞 -> not_liked skipped
        drv2 = FakeWeChatDriver(initial_liked=False)
        hub2 = WeChatMomentsHub(
            engine,
            store_dir=self.root / "moments2",
            run_native=drv2.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        key2 = self._seed_post(hub2, liked_by_me=True)
        res2 = hub2.interact(post_key=key2, action="unlike", mode="live")
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["results"][0]["status"], "skipped")
        self.assertEqual(res2["results"][0]["errorCode"], "not_liked")

        # Click happened, verification did not see own name -> sent_unverified, no retry
        drv3 = FakeWeChatDriver(initial_liked=False, verify_like_succeeds=False)
        hub3 = WeChatMomentsHub(
            engine,
            store_dir=self.root / "moments3",
            run_native=drv3.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        key3 = self._seed_post(hub3, liked_by_me=False)
        res3 = hub3.interact(post_key=key3, action="like", mode="live")
        self.assertTrue(res3["ok"])
        self.assertEqual(res3["results"][0]["status"], "sent_unverified")
        like_clicks = [c for c in drv3.clicks if abs(c[0] - drv3.like_screen_pt["x"]) < 2.0]
        self.assertEqual(len(like_clicks), 1)

    # ------------------------------------------------------------------
    # 3. comment: dry_run, silent_verify, live, readback_mismatch
    # ------------------------------------------------------------------
    def test_comment_three_modes_and_readback_mismatch(self):
        drv = FakeWeChatDriver()
        engine = FakeEngine(self.root)
        hub = WeChatMomentsHub(engine, run_native=drv.run_native, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        key = self._seed_post(hub)

        def fake_read_clip():
            return drv.clipboard

        def fake_write_clip(val: str):
            drv.clipboard = val

        with patch.object(MomentsInteractor, "_read_clipboard", staticmethod(fake_read_clip)), \
             patch.object(MomentsInteractor, "_write_clipboard", staticmethod(fake_write_clip)):

            # dry_run
            dry = hub.interact(post_key=key, action="comment", text="天气真好", mode="dry_run")
            self.assertTrue(dry["ok"])
            self.assertEqual(dry["results"][0]["status"], "dry_run")
            self.assertEqual(dry["results"][0]["wouldClick"], drv.comment_screen_pt)
            self.assertEqual(drv.clipboard, "orig-clip")

            # silent_verify
            drv.in_moments = True
            sv = hub.interact(post_key=key, action="comment", text="天气真好", mode="silent_verify")
            self.assertTrue(sv["ok"])
            self.assertEqual(sv["results"][0]["status"], "silent_verified")
            self.assertEqual(sv["results"][0]["readback"], "天气真好")
            self.assertIn("cmd+a", drv.keys)
            self.assertIn("delete", drv.keys)
            self.assertEqual(drv.comments, [])
            self.assertEqual(drv.clipboard, "orig-clip")

            # readback_mismatch
            drv.in_moments = True
            drv.readback_override = "完全不相干的乱码"
            mismatch = hub.interact(post_key=key, action="comment", text="天气真好", mode="live")
            self.assertFalse(mismatch["ok"])
            self.assertEqual(mismatch["results"][0]["status"], "failed")
            self.assertEqual(mismatch["results"][0]["errorCode"], "readback_mismatch")
            self.assertEqual(drv.clipboard, "orig-clip")

            # live
            drv.in_moments = True
            drv.readback_override = None
            live = hub.interact(post_key=key, action="comment", text="天气真好", mode="live")
            self.assertTrue(live["ok"])
            self.assertEqual(live["results"][0]["status"], "verified")
            self.assertEqual(len(drv.comments), 1)
            self.assertEqual(drv.comments[0]["text"], "天气真好")
            self.assertTrue(hub.get_post(key)["post"]["commentedByMe"])
            self.assertEqual(drv.clipboard, "orig-clip")

    # ------------------------------------------------------------------
    # 4. Human guard, mid-flow interruption, rate limit, capability check
    # ------------------------------------------------------------------
    def test_human_guard_and_mid_flow_interruption_and_rate_limit(self):
        # Pre-entry human guard
        drv = FakeWeChatDriver()
        engine_busy = FakeEngine(self.root, can_operate=False)
        hub_busy = WeChatMomentsHub(engine_busy, run_native=drv.run_native, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        key_b = self._seed_post(hub_busy)
        res_guard = hub_busy.interact(post_key=key_b, action="like", mode="dry_run")
        self.assertFalse(res_guard["ok"])
        self.assertTrue(res_guard["blockedByHumanGuard"])
        self.assertEqual(res_guard["error_code"], "human_active")
        self.assertEqual(drv.native_calls, [])

        # Mid-flow keyboard interruption before clicking like
        drv_kb = FakeWeChatDriver(interrupt_on_hid_call=2, interrupt_reason="keyboard")
        engine = FakeEngine(self.root)
        hub_kb = WeChatMomentsHub(
            engine,
            store_dir=self.root / "kb",
            run_native=drv_kb.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        key_k = self._seed_post(hub_kb)
        res_kb = hub_kb.interact(post_key=key_k, action="like", mode="live")
        self.assertFalse(res_kb["ok"])
        self.assertEqual(res_kb["results"][0]["status"], "blocked")
        self.assertEqual(res_kb["results"][0]["errorCode"], "human_active")
        self.assertNotIn((drv_kb.like_screen_pt["x"], drv_kb.like_screen_pt["y"]), drv_kb.clicks)

        # Mid-flow cursor movement interruption after clicking 「··」 (when _last_point is recorded)
        drv_cur = FakeWeChatDriver(interrupt_on_hid_call=2, interrupt_reason="cursor")
        hub_cur = WeChatMomentsHub(
            engine,
            store_dir=self.root / "cur",
            run_native=drv_cur.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        key_c = self._seed_post(hub_cur)
        res_cur = hub_cur.interact(post_key=key_c, action="like", mode="live")
        self.assertFalse(res_cur["ok"])
        self.assertEqual(res_cur["results"][0]["status"], "blocked")
        self.assertEqual(res_cur["results"][0]["errorCode"], "human_active")
        self.assertNotIn((drv_cur.like_screen_pt["x"], drv_cur.like_screen_pt["y"]), drv_cur.clicks)

        # Rate limiter blocking live mode
        drv_rl = FakeWeChatDriver(text_lines=("第一条日常记录内容",))
        hub_rl = WeChatMomentsHub(
            engine,
            store_dir=self.root / "rl",
            run_native=drv_rl.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        hub_rl.store.limiter.per_contact_hourly = 1
        hub_rl.store.limiter.min_gap_seconds = 0
        key_r1 = self._seed_post(hub_rl, text="第一条日常记录内容")
        key_r2 = self._seed_post(hub_rl, text="第二条日常记录内容")
        hub_rl.store.limiter.record("张三")
        res_rl = hub_rl.interact(post_key=key_r1, action="like", mode="live")
        self.assertFalse(res_rl["ok"])
        self.assertEqual(res_rl["results"][0]["status"], "failed")
        self.assertEqual(res_rl["results"][0]["errorCode"], "rate_limited")

        # Missing live capability gate
        engine_no_live = FakeEngine(self.root, grants={MOMENTS_CAP_READ, MOMENTS_CAP_DRY_RUN})
        hub_no_live = WeChatMomentsHub(
            engine_no_live,
            store_dir=self.root / "nolive",
            run_native=drv.run_native,
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        with self.assertRaises(StudioPluginUnauthorizedError):
            hub_no_live.interact(post_key=key_r2, action="like", mode="live")

    # ------------------------------------------------------------------
    # 5. get_posts_for_contact
    # ------------------------------------------------------------------
    def test_get_posts_for_contact_loose_match_and_stats(self):
        engine = FakeEngine(self.root)
        hub = WeChatMomentsHub(engine, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)

        # Contact's own posts (with nickname punctuation/suffix variation)
        self._seed_post(
            hub,
            author="苏文璐 · 产品",
            text="分享一个控制系统零极点笔记",
            time_text="2小时前",
            liked_by_me=True,
            commented_by_me=False,
        )
        self._seed_post(
            hub,
            author="苏文璐",
            text="周末去爬山晒太阳",
            time_text="2天前",
            liked_by_me=False,
            commented_by_me=True,
            comments=[{"author": "号主小号", "replyTo": "", "text": "风景真好"}],
        )
        # Unrelated contact
        self._seed_post(hub, author="李四", text="日常打卡", time_text="1天前")
        # Owner's post with interaction from 苏文璐
        self._seed_post(
            hub,
            author="号主小号",
            text="今天新版本上线了，欢迎体验",
            time_text="1小时前",
            is_own=True,
            likes=["苏文璐", "王五"],
            comments=[
                {"author": "苏文璐", "replyTo": "", "text": "太稳了！"},
                {"author": "王五", "replyTo": "", "text": "赞"},
            ],
        )
        # Partial post should be ignored by complete_posts
        hub.store.load_posts()
        doc = hub.store.load_posts()
        doc["posts"]["mom_partial_ignored"] = {
            "key": "mom_partial_ignored",
            "author": "苏文璐",
            "text": "半截",
            "partial": True,
        }
        hub.store.posts_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        res = hub.get_posts_for_contact("  苏文璐 ", limit=10)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["authored"]), 2)
        self.assertEqual(len(res["interactedOnMine"]), 1)
        self.assertTrue(res["interactedOnMine"][0]["liked"])
        self.assertEqual(res["interactedOnMine"][0]["comments"][0]["text"], "太稳了！")
        self.assertEqual(res["stats"]["posts"], 2)
        self.assertEqual(res["stats"]["authoredCount"], 2)
        self.assertEqual(res["stats"]["likedByMe"], 1)
        self.assertEqual(res["stats"]["commentedByMe"], 1)
        self.assertEqual(res["stats"]["likedMyPosts"], 1)
        self.assertEqual(res["stats"]["commentedMyPosts"], 1)
        self.assertEqual(res["stats"]["mutualHits"], 4)

        # Empty contact query must not match all posts
        empty_res = hub.get_posts_for_contact("")
        self.assertTrue(empty_res["ok"])
        self.assertEqual(empty_res["authored"], [])
        self.assertEqual(empty_res["interactedOnMine"], [])

    # ------------------------------------------------------------------
    # 6. suggest_comment (LLM + Soul + fallbacks) & plan() hook
    # ------------------------------------------------------------------
    def test_suggest_comment_llm_success_and_missing_post(self):
        models = FakeModels(
            enabled=True,
            reply={
                "ok": True,
                "modelId": "zai/glm-4.6",
                "replyText": '```json\n{"suggestedText": "这景色看着真舒坦，我也想去逛逛", "alternatives": ["周末这样放空太棒了", "风应该挺凉快的吧"]}\n```',
            },
        )
        profiler = FakeSoulProfiler(
            {
                "contactSoul": {
                    "personalityTag": "温和务实",
                    "communicationPreferences": "短句轻松口语",
                    "emotionalBaseline": "积极",
                },
                "ownerProfile": {"speakingStyle": {"toneTag": "自然直接"}},
                "memoryPromptSnippet": "- [事实] 上周聊过想找时间去爬山",
            }
        )
        engine = FakeEngine(self.root, models=models, soul_profiler=profiler)
        hub = WeChatMomentsHub(engine, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)

        missing = hub.suggest_comment("mom_nonexistent")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_code"], "post_not_found")

        key = self._seed_post(hub, author="林小雅", text="周末爬山看到云海，心情瞬间变好")
        res = hub.suggest_comment(key, style="natural")
        self.assertTrue(res["ok"])
        self.assertTrue(res["usedLlm"])
        self.assertEqual(res["modelId"], "zai/glm-4.6")
        self.assertEqual(res["author"], "林小雅")
        self.assertEqual(res["suggestedText"], "这景色看着真舒坦，我也想去逛逛")
        self.assertLessEqual(len(res["suggestedText"]), 40)
        self.assertEqual(len(res["alternatives"]), 2)
        self.assertEqual(len(models.calls), 1)
        user_msg = models.calls[0]["messages"][1]["content"]
        self.assertIn("温和务实", user_msg)
        self.assertIn("爬山", user_msg)

    def test_suggest_comment_fallbacks_and_length_cap(self):
        # 1) LLM disabled -> falls back to policy template first, then rule fallback
        models_off = FakeModels(enabled=False)
        engine_off = FakeEngine(self.root, models=models_off)
        hub_off = WeChatMomentsHub(engine_off, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        key = self._seed_post(hub_off, author="李四", text="刚吃了顿热腾腾的火锅")
        hub_off.set_policy({"comment": {"enabled": True, "templates": {"default": ["看着就香", "改天约一顿"]}}})

        res_tpl = hub_off.suggest_comment(key)
        self.assertTrue(res_tpl["ok"])
        self.assertFalse(res_tpl["usedLlm"])
        self.assertEqual(res_tpl["source"], "policy_template")
        self.assertIn(res_tpl["suggestedText"], ("看着就香", "改天约一顿"))
        self.assertEqual(len(res_tpl["alternatives"]), 2)
        self.assertEqual(len(models_off.calls), 0)

        # 2) LLM raises exception & no templates + Soul profiler fails -> smooth rule fallback
        models_err = FakeModels(enabled=True, exc=RuntimeError("gateway timeout"))
        profiler_err = FakeSoulProfiler(exc=RuntimeError("db corrupt"))
        engine_err = FakeEngine(self.root, models=models_err, soul_profiler=profiler_err)
        hub_err = WeChatMomentsHub(
            engine_err,
            store_dir=self.root / "err",
            clock_fn=lambda: self.NOW,
            sleep_fn=lambda _: None,
        )
        key_err = self._seed_post(hub_err, author="王五", text="新项目终于顺利上线啦，祝贺团队！")
        res_err = hub_err.suggest_comment(key_err)
        self.assertTrue(res_err["ok"])
        self.assertFalse(res_err["usedLlm"])
        self.assertEqual(res_err["source"], "rule_fallback")
        self.assertTrue(res_err["suggestedText"])
        self.assertLessEqual(len(res_err["suggestedText"]), 40)
        self.assertEqual(len(res_err["alternatives"]), 2)

        # 3) LLM returns invalid JSON -> degrades gracefully; overlong LLM text gets capped <= 40
        models_bad_json = FakeModels(enabled=True, reply={"ok": True, "modelId": "m1", "replyText": "not json"})
        hub_err.engine.models = models_bad_json
        res_bad = hub_err.suggest_comment(key_err)
        self.assertTrue(res_bad["ok"])
        self.assertFalse(res_bad["usedLlm"])

        long_reply = "这真的太棒太厉害了我觉得你最近的状态简直无敌了而且这个项目一定能做得越来越大越来越好"
        models_long = FakeModels(
            enabled=True,
            reply={"ok": True, "modelId": "m2", "replyText": json.dumps({"suggestedText": long_reply, "alternatives": []})},
        )
        hub_err.engine.models = models_long
        res_long = hub_err.suggest_comment(key_err)
        self.assertTrue(res_long["ok"])
        self.assertTrue(res_long["usedLlm"])
        self.assertLessEqual(len(res_long["suggestedText"]), 40)
        self.assertEqual(len(res_long["alternatives"]), 2)

    def test_plan_uses_llm_by_default_falls_back_to_template_and_respects_override(self):
        models = FakeModels(
            enabled=True,
            reply={"ok": True, "modelId": "zai/glm-4.6", "replyText": '{"suggestedText": "真挺稳的", "alternatives": ["不错", "加油"]}'},
        )
        engine = FakeEngine(self.root, models=models)
        hub = WeChatMomentsHub(engine, clock_fn=lambda: self.NOW, sleep_fn=lambda _: None)
        hub.set_policy({"comment": {"enabled": True, "templates": {"default": ["默认模板赞"]}}})
        self._seed_post(hub, author="陈六", text="连续早起第十天打卡")

        # Default: hub.comment_generator is None -> uses LLM hook
        plan_llm = hub.plan()
        self.assertEqual(plan_llm["items"][0]["action"], "comment")
        self.assertEqual(plan_llm["items"][0]["text"], "真挺稳的")

        # LLM failure in plan() -> degrades to policy template
        hub.engine.models = FakeModels(enabled=True, exc=RuntimeError("boom"))
        plan_tpl = hub.plan()
        self.assertEqual(plan_tpl["items"][0]["text"], "默认模板赞")

        # Explicit hub.comment_generator override takes priority over LLM
        hub.engine.models = models
        models.calls.clear()
        hub.comment_generator = lambda post: f"定制：{post['author']}"
        plan_custom = hub.plan()
        self.assertEqual(plan_custom["items"][0]["text"], "定制：陈六")
        self.assertEqual(len(models.calls), 0)


if __name__ == "__main__":
    unittest.main()
