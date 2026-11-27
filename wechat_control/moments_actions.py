"""朋友圈点赞与评论的界面流程。

实测（微信 4.2.0）：帖子页脚右侧的「··」会弹出一个深色胶囊，里面是「赞」和「评论」。这个胶囊是
独立窗口——`capture-ocr` 只截主窗口，看不到它；原生助手的窗口列表也只收正常层级的窗口。所以校验
它必须用 `capture-region` 截屏幕区域。点赞之后弹层立即关闭；点「评论」会关闭弹层并在帖子下方
打开输入框（在主窗口里，Esc 可放弃）。

安全设计：
- dry_run 是默认值：只点「··」并校验弹层，不点「赞」「评论」。
- 每一次对外点击之前，都确认弹层或输入框确实出现在预期位置；位置不对就放弃，绝不盲点。
- 流程中途检测到有人在敲键盘或动了鼠标就停。
- 点赞不自动重试：验证失败时再点一次可能把赞取消掉。
"""

from __future__ import annotations

import subprocess
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from .moments_feed import normalize_key_text, same_post
from .moments_hub import MAX_LOCATE_PAGES
from .moments_store import STORED_DRIFT_DAYS

LIKE_LABELS = "赞贊讚"
CANCEL_LABEL = "取消"
COMMENT_LABELS = ("评论", "評論")
# 胶囊出现在「··」按钮左侧、与它同一行
POPOVER_WIDTH = 256.0
POPOVER_HEIGHT = 68.0
COMMENT_INPUT_PLACEHOLDER = "评论"
SEND_LABEL = "发送"


class MomentsInteractor:
    """在已经打开的朋友圈信息流里，定位帖子并执行点赞 / 取消点赞 / 评论。"""

    def __init__(self, hub: Any) -> None:
        self.hub = hub

    # ------------------------------------------------------------------
    # 一次执行：可以带多个目标，从最新一条往下找，找到就处理
    # ------------------------------------------------------------------
    def execute(
        self, targets: List[Dict[str, Any]], *, mode: str = "dry_run", restore_view: bool = True
    ) -> Dict[str, Any]:
        hub = self.hub
        guard = hub.engine.human_guard.check_can_operate()
        if not guard.get("canOperate"):
            return {
                "ok": False, "blockedByHumanGuard": True, "error_code": "human_active",
                "error": "检测到人工正在操作鼠标/键盘，暂不操作朋友圈", "humanGuard": guard,
            }
        if not hub._lock.acquire(blocking=False):
            return {"ok": False, "error_code": "moments_busy", "error": "另一个朋友圈操作正在进行"}
        pending = list(targets)
        results: List[Dict[str, Any]] = []
        bounds: Dict[str, Any] = {}
        entered = False
        try:
            bounds = hub._window_bounds()
            hub._ensure_feed(bounds)
            entered = True
            owner = hub.store.owner_name()
            hub._scroll_to_top(bounds, owner)
            pages = 0
            previous_digest = ""
            while pending and pages < MAX_LOCATE_PAGES:
                view = hub._view(owner, f"act{pages % 3}")
                if not view["isMomentsView"]:
                    for target in pending:
                        results.append(self._fail(target, "view_lost", "滚动途中没有再认出朋友圈视图"))
                    pending = []
                    break
                # 处理完一条，下面的帖子都会下移，所以要重新截一帧再找下一条
                while pending:
                    pick = self._pick(view, pending)
                    if pick is None:
                        break
                    post, target = pick
                    if mode == "live":
                        allowed, reason = hub.store.limiter.check(target["author"])
                        if not allowed:
                            results.append(self._fail(target, "rate_limited", f"触发朋友圈频控：{reason}"))
                            pending.remove(target)
                            continue
                    result = self._act(bounds, view, post, target, mode, owner)
                    results.append(result)
                    pending.remove(target)
                    if result.get("status") in ("failed", "blocked"):
                        # 出错或人工接管就整批停下，不在没弄清的状态下继续点
                        pending = []
                        break
                    view = hub._view(owner, "act")
                    if not view["isMomentsView"]:
                        break
                if not pending:
                    break
                if view["digest"] == previous_digest:
                    break
                previous_digest = view["digest"]
                center = hub._feed_center(view)
                hub._scroll(bounds, center["x"], center["y"], -int(center["step"]))
                hub._sleep(1.1)
                pages += 1
            for target in pending:
                results.append(self._fail(target, "post_not_found", "在信息流里没有找到这条帖子"))
            ok = bool(results) and all(r.get("status") not in ("failed", "blocked") for r in results)
            hub.engine.audit.log("moments_interact", "ok" if ok else "error", {
                "mode": mode, "count": len(results),
                "statuses": sorted({str(r.get("status")) for r in results}),
            })
            return {"ok": ok, "mode": mode, "results": results, "pagesScanned": pages}
        except Exception as exc:  # MomentsFlowError 或原生调用异常：带着已完成的记录返回
            code = getattr(exc, "code", None) or "interaction_failed"
            hub.engine.audit.log("moments_interact", "error", {"mode": mode, "code": code})
            return {"ok": False, "error_code": code, "error": str(exc), "results": results}
        finally:
            if entered:
                # 收尾：关掉可能还开着的弹层或输入框，再切回聊天页
                try:
                    self._dismiss()
                except Exception:
                    pass
                if restore_view and bounds:
                    try:
                        restored = hub._return_to_chats(bounds)
                    except Exception:
                        pass
            hub._lock.release()

    @staticmethod
    def _fail(target: Dict[str, Any], code: str, message: str) -> Dict[str, Any]:
        return {
            "postKey": target.get("postKey", ""), "author": target.get("author", ""),
            "action": target.get("action", ""), "text": target.get("text", ""),
            "status": "failed", "errorCode": code, "error": message,
        }

    def _pick(
        self, view: Dict[str, Any], pending: List[Dict[str, Any]]
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """在这一帧里从上往下找第一条能操作的目标帖子：作者和页脚都在画面里，页脚离边缘足够远。"""
        height = float(view["window"]["height"])
        bottom = height - 60.0
        for post in sorted(
            (p for p in view["posts"] if p.get("footer") and not p.get("topCut")),
            key=lambda p: float(p["footer"]["y"]),
        ):
            footer_y = float(post["footer"]["y"])
            if not (float(view["feedTop"]) + 30.0 <= footer_y <= bottom):
                continue
            for target in pending:
                if post["key"] != target["postKey"] and not same_post(
                    target["snapshot"], post, max_drift_days=STORED_DRIFT_DAYS
                ):
                    continue
                # 评论输入框开在页脚下方，页脚太靠下时输入框会被挤出画面
                if target["action"] == "comment" and footer_y > height - 260.0:
                    continue
                return post, target
        return None

    def _dismiss(self) -> None:
        self.hub._key("esc")
        self.hub._sleep(0.4)

    def _click_screen(self, point: Dict[str, Any]) -> None:
        self.hub._click_screen(float(point["x"]), float(point["y"]))

    def _verify_popover(
        self, bounds: Dict[str, Any], footer: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """确认「赞 / 评论」胶囊真的开在「··」左边，并返回两个按钮的屏幕坐标。"""
        button_x = float(bounds.get("x", 0.0)) + float(footer["x"])
        button_y = float(bounds.get("y", 0.0)) + float(footer["y"])
        res = self.hub._run(
            ["capture-region", "--x", f"{button_x - 215.0:.0f}", "--y", f"{button_y - 34.0:.0f}",
             "--width", f"{POPOVER_WIDTH:.0f}", "--height", f"{POPOVER_HEIGHT:.0f}"],
            15.0,
        )
        if not res.get("ok"):
            return None
        like: Optional[Dict[str, Any]] = None
        comment: Optional[Dict[str, Any]] = None
        label = ""
        for element in res.get("elements") or []:
            text = str(element.get("text") or "").strip()
            point = element.get("screenCenter") or {}
            if "x" not in point or "y" not in point:
                continue
            # 只认胶囊所在的位置：按钮左侧、与它同一行。帖子正文里的「赞」「评论」不在那里。
            if abs(float(point["y"]) - button_y) > 14.0 or not (button_x - 210.0 <= float(point["x"]) <= button_x - 12.0):
                continue
            if any(word in text for word in COMMENT_LABELS):
                comment = point
            elif CANCEL_LABEL in text:
                like, label = point, CANCEL_LABEL
            elif any(ch in text for ch in LIKE_LABELS):
                like, label = point, "赞"
        if like is None or comment is None:
            # 胶囊里总是同时有「赞」和「评论」，只读到一项说明没看清，不点
            return None
        return {"like": like, "comment": comment, "likeLabel": label}

    # ------------------------------------------------------------------
    # 剪贴板：评论只能粘贴输入，事后把用户原来的剪贴板内容放回去
    # ------------------------------------------------------------------
    @staticmethod
    def _read_clipboard() -> str:
        try:
            proc = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3.0)
            return proc.stdout if proc.returncode == 0 else ""
        except Exception:
            return ""

    @staticmethod
    def _write_clipboard(text: str) -> None:
        try:
            subprocess.run(["pbcopy"], input=text, text=True, capture_output=True, timeout=3.0)
        except Exception:
            pass

    @staticmethod
    def _alike(expected: str, actual: str) -> float:
        want = normalize_key_text(expected)
        got = normalize_key_text(actual)
        if want and want in got:
            return 1.0
        return SequenceMatcher(None, want, got, autojunk=False).ratio() if want else 0.0

    # ------------------------------------------------------------------
    # 对一条帖子的单个动作
    # ------------------------------------------------------------------
    def _act(
        self, bounds: Dict[str, Any], view: Dict[str, Any], post: Dict[str, Any], target: Dict[str, Any],
        mode: str, owner: str,
    ) -> Dict[str, Any]:
        hub = self.hub
        action = target["action"]
        result: Dict[str, Any] = {
            "postKey": target["postKey"], "author": post.get("author") or target["author"],
            "action": action, "text": target["text"], "timeText": post.get("timeText") or "", "mode": mode,
        }
        if hub._human_interrupted():
            return self._finish(result, "blocked", "human_active", "检测到有人正在操作鼠标或键盘，已停下")
        footer = post["footer"]
        hub._click(bounds, footer["x"], footer["y"])  # 「··」只是弹出菜单，本身不对外
        hub._sleep(0.7)
        popover = self._verify_popover(bounds, footer)
        if popover is None:
            self._dismiss()
            return self._finish(
                result, "failed", "popover_not_verified", "点了「··」但没在预期位置看到「赞 / 评论」菜单，已放弃"
            )
        result["popover"] = {"like": popover["like"], "comment": popover["comment"], "likeLabel": popover["likeLabel"]}

        if action in ("like", "unlike"):
            if popover["like"] is None:
                self._dismiss()
                return self._finish(result, "failed", "popover_incomplete", "菜单里没有看清「赞」按钮，已放弃")
            # 菜单上写的是「取消」说明这条帖子实际上已经赞过；以界面为准，和档案对账
            already = popover["likeLabel"] == CANCEL_LABEL
            if action == "like" and already:
                hub.store.apply_interaction(target["postKey"], action="like", owner=owner)
                self._dismiss()
                return self._finish(result, "skipped", "already_liked", "这条帖子实际上已经赞过，不重复点")
            if action == "unlike" and not already:
                self._dismiss()
                return self._finish(result, "skipped", "not_liked", "这条帖子实际上没有赞过，无需取消")
            if mode == "dry_run":
                self._dismiss()
                return self._finish(
                    {**result, "wouldClick": popover["like"]}, "dry_run", "", "dry-run：菜单已校验，没有点击"
                )
            if hub._human_interrupted():
                self._dismiss()
                return self._finish(result, "blocked", "human_active", "检测到有人正在操作鼠标或键盘，已停下")
            self._click_screen(popover["like"])
            hub._sleep(1.2)
            # 不重试：验证没通过时再点一次，可能把刚点的赞取消掉
            verified = self._verify_like(owner, post, want=(action == "like"))
            if verified:
                hub.store.apply_interaction(target["postKey"], action=action, owner=owner)
            hub.store.limiter.record(target["author"])
            return self._finish(
                {**result, "clicked": popover["like"]},
                "verified" if verified else "sent_unverified", "",
                "" if verified else "已点击，但没能在点赞名单里核对到本人，请到微信里确认",
            )

        if popover["comment"] is None:
            self._dismiss()
            return self._finish(result, "failed", "popover_incomplete", "菜单里没有看清「评论」按钮，已放弃")
        if mode == "dry_run":
            self._dismiss()
            return self._finish(
                {**result, "wouldClick": popover["comment"]}, "dry_run", "", "dry-run：菜单已校验，没有点击"
            )
        if hub._human_interrupted():
            self._dismiss()
            return self._finish(result, "blocked", "human_active", "检测到有人正在操作鼠标或键盘，已停下")
        self._click_screen(popover["comment"])
        hub._sleep(0.8)
        return self._comment(bounds, post, target, mode, owner, result)

    def _finish(self, result: Dict[str, Any], status: str, code: str, message: str) -> Dict[str, Any]:
        """落互动台账与审计日志（不记录评论正文，只记长度），并补上状态字段。"""
        hub = self.hub
        hub.store.record_interaction({
            "postKey": result.get("postKey"), "author": result.get("author"), "action": result.get("action"),
            "mode": result.get("mode"), "status": status, "errorCode": code or "",
            "textLength": len(result.get("text") or ""),
        })
        hub.engine.audit.log(
            f"moments_{result.get('action')}",
            status if status in ("verified", "sent_unverified", "dry_run", "silent_verified", "skipped") else "stopped",
            {"postKey": result.get("postKey"), "author": result.get("author"), "mode": result.get("mode"), "errorCode": code or ""},
        )
        return {**result, "status": status, "errorCode": code or "", "error": message}

    def _find_post(self, owner: str, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        view = self.hub._view(owner, "verify")
        if not view["isMomentsView"]:
            return None
        for candidate in view["posts"]:
            if candidate.get("key") == post.get("key") or same_post(post, candidate):
                return candidate
        return None

    def _verify_like(self, owner: str, post: Dict[str, Any], *, want: bool) -> bool:
        current = self._find_post(owner, post)
        if current is None:
            return False
        me = normalize_key_text(owner)
        liked = any(normalize_key_text(name) == me for name in current.get("likes") or [])
        return liked == want

    def _verify_comment(self, owner: str, post: Dict[str, Any], text: str) -> bool:
        current = self._find_post(owner, post)
        if current is None:
            return False
        me = normalize_key_text(owner)
        return any(
            normalize_key_text(comment.get("author") or "") == me
            and self._alike(text, comment.get("text") or "") >= 0.85
            for comment in current.get("comments") or []
        )

    # ------------------------------------------------------------------
    # 评论：打开输入框 → 粘贴 → 读回核对 → （live）发送 → 核对
    # ------------------------------------------------------------------
    def _comment(
        self, bounds: Dict[str, Any], post: Dict[str, Any], target: Dict[str, Any], mode: str,
        owner: str, result: Dict[str, Any],
    ) -> Dict[str, Any]:
        hub = self.hub
        text = target["text"]
        box = self._find_input(owner, post)
        if box is None:
            self._discard_input(typed=False)
            return self._finish(
                result, "failed", "comment_input_not_found", "点了「评论」但没有在帖子下方看到输入框，已放弃"
            )
        pasted = False
        backup = self._read_clipboard()
        self._write_clipboard(text)
        try:
            hub._click(bounds, box["x"] + 40.0, box["y"] + 12.0)
            hub._sleep(0.3)
            hub._key("cmd+v")
            pasted = True
            hub._sleep(0.6)
            readback = self._read_input(owner, box)
            for _ in range(2):
                if self._alike(text, readback) >= 0.9:
                    break
                hub._sleep(0.6)
                readback = self._read_input(owner, box)
            ratio = self._alike(text, readback)
            if ratio < 0.9:
                self._discard_input(typed=pasted)
                return self._finish(
                    result, "failed", "readback_mismatch",
                    f"输入框里读回的文字与要发的评论不一致（相似度 {ratio:.2f}），已清空放弃",
                )
            if mode == "silent_verify":
                self._discard_input(typed=pasted)
                return self._finish(
                    {**result, "readback": readback[:60]}, "silent_verified", "",
                    "评论已粘贴进输入框并读回核对一致，没有发送，已清空",
                )
            send = self._find_send_button(owner, box)
            if send is None:
                self._discard_input(typed=pasted)
                return self._finish(
                    result, "failed", "send_button_not_found", "没有在输入框右下角找到「发送」按钮，已清空放弃"
                )
            if hub._human_interrupted():
                self._discard_input(typed=pasted)
                return self._finish(result, "blocked", "human_active", "检测到有人正在操作鼠标或键盘，已停下并清空")
            hub._click(bounds, send["x"], send["y"])
            hub._sleep(1.4)
            verified = self._verify_comment(owner, post, text)
            if verified:
                hub.store.apply_interaction(target["postKey"], action="comment", owner=owner, comment_text=text)
            hub.store.limiter.record(target["author"])
            return self._finish(
                {**result, "clicked": send},
                "verified" if verified else "sent_unverified", "",
                "" if verified else "已发送，但没能在评论列表里核对到这条评论，请到微信里确认",
            )
        finally:
            self._write_clipboard(backup)

    def _find_input(self, owner: str, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """评论输入框打开后，占位符「评论」落在页脚下方、正文列里。"""
        view = self.hub._view(owner, "input")
        if not view["isMomentsView"]:
            return None
        footer_y = float(post["footer"]["y"]) if post.get("footer") else 0.0
        col = float(view["colLeft"])
        box = {"colLeft": col, "colRight": float(view["colRight"])}
        for element in view["elements"]:
            if (
                element["text"].strip() == COMMENT_INPUT_PLACEHOLDER
                and col + 15.0 <= element["x"] <= col + 90.0
                and footer_y + 40.0 <= element["y"] <= footer_y + 240.0
            ):
                return {**box, "x": element["x"], "y": element["y"]}
        for parsed in view["posts"]:
            if parsed.get("commentInputOpen") and (parsed.get("key") == post.get("key") or same_post(post, parsed)):
                # 占位符没读出来，但解析时看到了输入框的「发送」按钮：按实测位置点页脚下方约 86px
                return {**box, "x": col + 32.0, "y": footer_y + 86.0}
        return None

    def _read_input(self, owner: str, box: Dict[str, Any]) -> str:
        view = self.hub._view(owner, "typed")
        if not view["isMomentsView"]:
            return ""
        return "".join(
            element["text"] for element in view["elements"]
            if box["colLeft"] + 8.0 <= element["x"] <= box["colRight"]
            and box["y"] - 24.0 <= element["y"] <= box["y"] + 34.0
        )

    def _find_send_button(self, owner: str, box: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        view = self.hub._view(owner, "send")
        if not view["isMomentsView"]:
            return None
        for element in view["elements"]:
            if (
                element["text"].strip().endswith(SEND_LABEL)
                and element["x"] > box["colLeft"] + 250.0
                and abs(element["y"] - box["y"]) <= 75.0
            ):
                # 「发送」前面可能粘着表情、图片图标，点文字的右端
                return {"x": element["x"] + element["w"] - 10.0, "y": element["y"]}
        return None

    def _discard_input(self, *, typed: bool) -> None:
        """放弃输入框里已有的文字并关掉它。只清空、不发送。"""
        if typed:
            self.hub._key("cmd+a")
            self.hub._sleep(0.15)
            self.hub._key("delete")
            self.hub._sleep(0.2)
        self._dismiss()
