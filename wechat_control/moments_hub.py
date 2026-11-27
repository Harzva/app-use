"""WeChat Moments (朋友圈) hub for the macOS WeChat desktop client.

朋友圈视图不暴露辅助功能树，整个流程都靠原生 Vision OCR 驱动。读取是「发现 → 朋友圈 → 逐帧
小步滚动」，解析见 moments_feed.py，本地档案见 moments_store.py；点赞、评论走独立窗口里的弹层，
校验与点击见 moments_actions.py。

对外动作默认 dry-run，并且依次过三道闸：Studio 授权门禁（朋友圈有独立的能力项）、人工活动守卫
（用户正在用鼠标键盘时不操作）、朋友圈专用频控。流程结束后默认切回聊天页——否则会话列表会被
「发现」页顶掉，巡检就读不到会话了。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .moments_feed import (
    DISCOVER_PANE_LEFT, FeedMerger, normalize_key_text, parse_feed_page, public_post, same_post,
)
from .moments_store import STORED_DRIFT_DAYS, MomentsStore, ordered_posts

MOMENTS_CAP_READ = "read_moments"
MOMENTS_CAP_DRY_RUN = "moments_interact_dry_run"
MOMENTS_CAP_LIVE = "moments_interact_live"
MOMENTS_MODES = ("dry_run", "silent_verify", "live")

# 微信 4.2.0 实测的左侧导航栏图标中心（窗口内坐标）。旧版间距不同，依次尝试并靠 OCR 确认。
RAIL_DISCOVER_POINTS = ((31.0, 264.0), (27.0, 244.0))
RAIL_CHATS_POINT = (30.0, 118.0)
# 每帧滚动不超过可视高度的 30%：这样高度不超过可视区 70% 的帖子必然在某一帧里完整出现
SCROLL_RATIO = 0.30
MAX_READ_PAGES = 90
MAX_LOCATE_PAGES = 60


class MomentsFlowError(RuntimeError):
    """朋友圈流程无法继续（微信没开、界面没认出来等）。`code` 供调用方判断。"""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


_COMMENT_MAX_SUGGEST_CHARS = 40
_STYLE_HINTS: Dict[str, str] = {
    "natural": "熟人朋友日常口语，真诚自然、像平时随手回一句，不要书面腔或客服腔",
    "warm": "温暖关心、带一点熟人惦记感，真诚不肉麻",
    "concise": "简短利落，4-15字以内点到为止",
    "humorous": "轻松带点熟人幽默感，自然不油腻",
    "professional": "得体大方、尊重对方专业分享，依然保持口语感不端着",
}


def _name_matches(target_key: str, candidate: str) -> bool:
    if not target_key:
        return False
    cand_key = normalize_key_text(candidate or "")
    if not cand_key:
        return False
    if target_key == cand_key:
        return True
    if len(target_key) >= 2 and len(cand_key) >= 2:
        return target_key in cand_key or cand_key in target_key
    return False


def _trim_comment(text: str, max_len: int = _COMMENT_MAX_SUGGEST_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = cleaned.strip("\"'“”‘’「」")
    cleaned = re.sub(r"^(?:\d+[.、)]\s*|[-•·]\s*)", "", cleaned).strip()
    if len(cleaned) <= max_len:
        return cleaned
    clipped = cleaned[:max_len]
    for sep in ("。", "！", "？", "~", "～", "，", ","):
        idx = clipped.rfind(sep)
        if idx >= max_len // 2:
            candidate = clipped[: idx + (0 if sep in ("，", ",") else 1)].strip()
            if candidate:
                return candidate
    return clipped.rstrip("，,、 ")


def _parse_suggested_comments_json(raw_text: str) -> Tuple[str, List[str]]:
    body = str(raw_text or "").strip()
    if not body:
        return "", []
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", body, flags=re.IGNORECASE)
    if fenced:
        body = fenced.group(1).strip()
    else:
        start = body.find("{")
        end = body.rfind("}")
        if start != -1 and end > start:
            body = body[start : end + 1]
    try:
        doc = json.loads(body)
    except Exception:
        return "", []
    if not isinstance(doc, dict):
        return "", []
    primary_raw = doc.get("suggestedText") or doc.get("suggested") or doc.get("comment") or doc.get("text") or ""
    primary = _trim_comment(str(primary_raw))
    if not primary:
        return "", []
    alts: List[str] = []
    raw_alts = doc.get("alternatives") or []
    if isinstance(raw_alts, list):
        for item in raw_alts:
            cand = _trim_comment(str(item or ""))
            if cand and cand != primary and cand not in alts:
                alts.append(cand)
                if len(alts) >= 2:
                    break
    return primary, alts


class WeChatMomentsHub:
    """读取朋友圈信息流，并作为点赞、评论流程的对外入口。"""

    def __init__(
        self,
        engine: Any,
        *,
        store_dir: Optional[Path] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        run_native: Optional[Callable[[List[str], float], Dict[str, Any]]] = None,
    ) -> None:
        self.engine = engine
        self._clock = clock_fn or time.time
        self._sleep = sleep_fn or time.sleep
        self._run = run_native or (lambda args, timeout=20.0: engine._run_native(args, timeout))
        root = Path(store_dir) if store_dir else Path(engine.inspector.reports_dir) / "moments"
        self.store = MomentsStore(root, clock_fn=self._clock)
        limiter = self.store.limiter
        limiter.per_contact_hourly = int(os.environ.get("WECHAT_PLUGIN_MOMENTS_CONTACT_HOURLY", "2") or 2)
        limiter.global_hourly = int(os.environ.get("WECHAT_PLUGIN_MOMENTS_HOURLY", "10") or 10)
        limiter.global_daily = int(os.environ.get("WECHAT_PLUGIN_MOMENTS_DAILY", "30") or 30)
        limiter.min_gap_seconds = int(os.environ.get("WECHAT_PLUGIN_MOMENTS_GAP", "45") or 45)
        self._snapshots_dir = Path(engine.inspector.snapshots_dir)
        self._lock = threading.Lock()
        # 最近一次界面点击/滚动的屏幕坐标：用来判断流程中途有没有人来动鼠标
        self._last_point: Optional[Dict[str, float]] = None
        # 可选的评论文案生成器：(帖子) -> 文案。不设则只用策略里的模板。
        self.comment_generator: Optional[Callable[[Dict[str, Any]], str]] = None
        self._actions: Any = None

    # ------------------------------------------------------------------
    # 原生操作与界面识别
    # ------------------------------------------------------------------
    def _now(self) -> float:
        return float(self._clock())

    def _window_bounds(self) -> Dict[str, Any]:
        status = self._run(["status"], 12.0)
        windows = [w for w in (status.get("windows") or []) if w.get("bounds")]
        if not status.get("wechatRunning") or not windows:
            self._run(["activate"], 12.0)
            self._sleep(0.5)
            status = self._run(["status"], 12.0)
            windows = [w for w in (status.get("windows") or []) if w.get("bounds")]
        if not status.get("wechatRunning"):
            raise MomentsFlowError("wechat_not_running", "微信没有在运行")
        if not windows:
            raise MomentsFlowError("no_wechat_window", "没有找到微信主窗口")
        # 赞/评论的弹层和按键都要求微信在最前面
        self._run(["activate"], 12.0)
        self._sleep(0.6)
        return windows[0]["bounds"]

    def _capture(self, name: str) -> Dict[str, Any]:
        shot = self._snapshots_dir / f"moments_{name}.png"
        res = self._run(["capture-ocr", "--out", str(shot)], 30.0)
        if not res.get("ok"):
            raise MomentsFlowError(res.get("error_code") or "capture_failed", str(res.get("error") or ""))
        return res

    def _view(self, owner: str = "", name: str = "view") -> Dict[str, Any]:
        """截一帧并解析。滚动或加载途中会截到乱码帧，这时等一下重截。"""
        last: Dict[str, Any] = {}
        for attempt in range(3):
            last = parse_feed_page(self._capture(name), owner_name=owner, now_ts=self._now())
            if last["isDiscoverList"] or len(last["elements"]) >= 6:
                return last
            self._sleep(1.0)
        return last

    def _click(self, bounds: Dict[str, Any], x: float, y: float) -> None:
        self._click_screen(float(bounds.get("x", 0.0)) + float(x), float(bounds.get("y", 0.0)) + float(y))

    def _click_screen(self, screen_x: float, screen_y: float) -> None:
        sx = float(screen_x)
        sy = float(screen_y)
        res = self._run(["click", "--x", f"{sx:.1f}", "--y", f"{sy:.1f}"], 8.0)
        if not res.get("ok"):
            raise MomentsFlowError(res.get("error_code") or "click_failed", str(res.get("error") or ""))
        self._last_point = {"x": sx, "y": sy}

    def _scroll(self, bounds: Dict[str, Any], x: float, y: float, dy: int) -> None:
        screen_x = float(bounds.get("x", 0.0)) + float(x)
        screen_y = float(bounds.get("y", 0.0)) + float(y)
        res = self._run(
            ["scroll", "--x", f"{screen_x:.1f}", "--y", f"{screen_y:.1f}", "--dy", str(int(dy)),
             "--units", "pixel", "--steps", "6"],
            12.0,
        )
        if not res.get("ok"):
            raise MomentsFlowError(res.get("error_code") or "scroll_failed", str(res.get("error") or ""))
        self._last_point = {"x": screen_x, "y": screen_y}

    def _key(self, combo: str) -> None:
        res = self._run(["press-key", "--combo", combo], 8.0)
        if not res.get("ok"):
            raise MomentsFlowError(res.get("error_code") or "key_failed", str(res.get("error") or ""))

    def _human_interrupted(self) -> bool:
        """流程开始后自己每次点击都会重置系统空闲计时，所以不能再用人工守卫；直接看
        硬件键盘有没有人在敲、光标有没有离开我上次操作的位置。"""
        res = self._run(["hid-idle"], 4.0)
        hid = res.get("hidIdle") if isinstance(res.get("hidIdle"), dict) else res
        if not isinstance(hid, dict):
            return True
        if float(hid.get("hardwareKeyboardIdleSeconds") or 0.0) < 2.0:
            return True
        cursor = hid.get("cursorPosition") or {}
        last = self._last_point
        if last and "x" in cursor and "y" in cursor:
            moved = ((float(cursor["x"]) - last["x"]) ** 2 + (float(cursor["y"]) - last["y"]) ** 2) ** 0.5
            return moved > 22.0
        return False

    # ------------------------------------------------------------------
    # 进入朋友圈、滚动、退出
    # ------------------------------------------------------------------
    @staticmethod
    def _feed_center(view: Dict[str, Any]) -> Dict[str, float]:
        usable = max(200.0, float(view["window"]["height"]) - float(view["feedTop"]))
        return {
            "x": (DISCOVER_PANE_LEFT + float(view["window"]["width"])) / 2.0,
            "y": float(view["feedTop"]) + usable * 0.5,
            "step": max(240.0, usable * SCROLL_RATIO),
            "usable": usable,
        }

    def _ensure_feed(self, bounds: Dict[str, Any]) -> Dict[str, Any]:
        """已经在朋友圈就直接用；否则「发现」→「朋友圈」，每一步都用 OCR 确认走对了。"""
        view = self._view("", "entry")
        if view["isMomentsView"]:
            return view
        if not view["isDiscoverList"]:
            for point in RAIL_DISCOVER_POINTS:
                self._click(bounds, point[0], point[1])
                self._sleep(0.9)
                view = self._view("", "entry")
                if view["isDiscoverList"]:
                    break
            else:
                raise MomentsFlowError("discover_not_opened", "没能打开微信的「发现」页")
            if view["isMomentsView"]:
                return view
        row = next(
            (el for el in view["elements"]
             if "朋友圈" in el["text"] and el["x"] < DISCOVER_PANE_LEFT and el["y"] > 50.0),
            None,
        )
        if row is None:
            raise MomentsFlowError("moments_entry_not_found", "「发现」页里没有找到「朋友圈」入口")
        self._click(bounds, row["x"] + row["w"] / 2.0, row["y"])
        self._sleep(1.6)
        view = self._view("", "entry")
        if not view["isMomentsView"]:
            raise MomentsFlowError("moments_not_opened", "点了「朋友圈」但没有进入朋友圈")
        return view

    def _scroll_to_top(self, bounds: Dict[str, Any], owner: str) -> Dict[str, Any]:
        view = self._view(owner, "top")
        for _ in range(10):
            if view["topPage"]:
                return view
            center = self._feed_center(view)
            self._scroll(bounds, center["x"], center["y"], int(center["usable"] * 1.5))
            self._sleep(0.9)
            view = self._view(owner, "top")
        return view

    def _return_to_chats(self, bounds: Dict[str, Any]) -> bool:
        for _ in range(2):
            self._click(bounds, RAIL_CHATS_POINT[0], RAIL_CHATS_POINT[1])
            self._sleep(0.8)
            if not self._view("", "exit")["isDiscoverList"]:
                return True
        return False

    # ------------------------------------------------------------------
    # 读取信息流
    # ------------------------------------------------------------------
    def read_feed(
        self, *, max_posts: int = 40, max_pages: int = MAX_READ_PAGES, restore_view: bool = True
    ) -> Dict[str, Any]:
        """从最新一条往下读朋友圈。读到够数、到底、或连续两帧全是库里已有的帖子就停。"""
        self.engine._require(MOMENTS_CAP_READ)
        guard = self.engine.human_guard.check_can_operate()
        if not guard.get("canOperate"):
            return {
                "ok": False, "blockedByHumanGuard": True, "error_code": "human_active",
                "error": "检测到人工正在操作鼠标/键盘，暂不读取朋友圈", "humanGuard": guard,
            }
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error_code": "moments_busy", "error": "另一个朋友圈操作正在进行"}
        limit = max(1, int(max_posts))
        bounds: Dict[str, Any] = {}
        entered = False
        try:
            bounds = self._window_bounds()
            view = self._ensure_feed(bounds)
            entered = True
            owner = self.store.owner_name() or view.get("ownerName") or ""
            view = self._scroll_to_top(bounds, owner)
            owner = view.get("ownerName") or owner
            merger = FeedMerger()
            recent = ordered_posts(self.store.load_posts()["posts"])[:160]
            previous_digest = ""
            stale_known = 0
            stopped = "max_pages"
            end_of_feed = False
            for index in range(max(1, int(max_pages))):
                view = self._view(owner, f"read{index % 3}")
                if not view["isMomentsView"]:
                    stopped = "view_lost"
                    break
                merger.add_page(view)
                if sum(1 for p in merger.posts if not p["partial"]) >= limit:
                    stopped = "max_posts"
                    break
                visible = [p for p in view["posts"] if not p["partial"]]
                known_only = bool(recent) and bool(visible) and all(
                    self.store.find_stored(recent, p) is not None for p in visible
                )
                stale_known = stale_known + 1 if known_only else 0
                if stale_known >= 2:
                    stopped = "reached_known"
                    break
                if view["digest"] == previous_digest:
                    stopped, end_of_feed = "end_of_feed", True
                    break
                previous_digest = view["digest"]
                center = self._feed_center(view)
                self._scroll(bounds, center["x"], center["y"], -int(center["step"]))
                self._sleep(1.1)
            counts = self.store.save_read(merger.posts, owner=owner)
            complete = [p for p in merger.posts if not p["partial"]]
            self.store.record_observation({
                "frames": merger.frames, "postsRead": len(complete), "newPosts": counts["newPosts"],
                "partialSkipped": counts["partialSkipped"], "stoppedBecause": stopped,
            })
            self.engine.audit.log("moments_read", "ok", {
                "frames": merger.frames, "postsRead": len(complete), "newPosts": counts["newPosts"],
                "stoppedBecause": stopped,
            })
            store = self.store.load_posts()
            return {
                "ok": True, "ownerName": owner, "framesRead": merger.frames, "postsRead": len(complete),
                "endOfFeed": end_of_feed, "stoppedBecause": stopped,
                "partialSkipped": counts["partialSkipped"],
                "store": {
                    "newPosts": counts["newPosts"], "refreshed": counts["refreshed"],
                    "totalComplete": sum(1 for p in store["posts"].values() if not p.get("partial")),
                    "lastReadAt": store.get("lastReadAt") or "",
                    "path": str(self.store.posts_path),
                },
                "posts": [public_post(p) for p in complete[:limit]],
            }
        except MomentsFlowError as exc:
            self.engine.audit.log("moments_read", "error", {"code": exc.code})
            return {"ok": False, "error_code": exc.code, "error": str(exc)}
        finally:
            if entered and restore_view and bounds:
                try:
                    self._return_to_chats(bounds)
                except Exception:
                    pass
            self._lock.release()

    # ------------------------------------------------------------------
    # 对外接口：档案查询、策略、互动
    # ------------------------------------------------------------------
    def list_posts(self, *, limit: int = 30, author: str = "", include_partial: bool = False) -> Dict[str, Any]:
        store = self.store.load_posts()
        posts = list(ordered_posts(store["posts"]))
        if not include_partial:
            posts = [post for post in posts if not post.get("partial")]
        if author:
            key = normalize_key_text(author)
            posts = [post for post in posts if key in normalize_key_text(post.get("author") or "")]
        return {
            "ok": True, "ownerName": store.get("ownerName") or "", "lastReadAt": store.get("lastReadAt") or "",
            "count": len(posts), "posts": [public_post(post) for post in posts[:max(0, int(limit))]],
        }

    def get_post(self, post_key: str) -> Dict[str, Any]:
        post = self.store.load_posts()["posts"].get(str(post_key or ""))
        if not isinstance(post, dict):
            return {"ok": False, "error_code": "post_not_found", "error": "帖子库里没有这一条"}
        return {"ok": True, "post": public_post(post)}

    def get_posts_for_contact(self, contact_name: str, *, limit: int = 15) -> Dict[str, Any]:
        """按昵称宽松匹配联系人发过的完整帖子，以及其在号主帖子下的赞评互动。"""
        name = str(contact_name or "").strip()
        target_key = normalize_key_text(name)
        max_items = max(0, int(limit))
        store_doc = self.store.load_posts()
        owner_name = str(store_doc.get("ownerName") or "")
        owner_key = normalize_key_text(owner_name)
        complete = self.store.complete_posts()

        authored_all: List[Dict[str, Any]] = []
        interacted_all: List[Dict[str, Any]] = []
        liked_my_posts = 0
        commented_my_posts = 0

        for post in complete:
            author = str(post.get("author") or "")
            if _name_matches(target_key, author):
                authored_all.append(public_post(post))
            is_own = bool(post.get("isOwn")) or (
                bool(owner_key) and normalize_key_text(author) == owner_key
            )
            if is_own:
                liked = any(_name_matches(target_key, liker) for liker in (post.get("likes") or []))
                comments = [
                    dict(c) for c in (post.get("comments") or [])
                    if _name_matches(target_key, str(c.get("author") or ""))
                ]
                if liked or comments:
                    if liked:
                        liked_my_posts += 1
                    commented_my_posts += len(comments)
                    interacted_all.append({
                        "postKey": post.get("key") or "",
                        "postAuthor": author or owner_name,
                        "postText": str(post.get("text") or "").strip(),
                        "postSnippet": str(post.get("text") or "").replace("\n", " ").strip()[:80],
                        "timeText": post.get("timeText") or "",
                        "publishedEstimate": post.get("publishedEstimate"),
                        "liked": liked,
                        "comments": comments,
                    })

        liked_by_me = sum(1 for p in authored_all if p.get("likedByMe"))
        commented_by_me = sum(1 for p in authored_all if p.get("commentedByMe"))
        stats = {
            "posts": len(authored_all),
            "authoredCount": len(authored_all),
            "likedByMe": liked_by_me,
            "commentedByMe": commented_by_me,
            "likedMyPosts": liked_my_posts,
            "commentedMyPosts": commented_my_posts,
            "mutualHits": liked_by_me + commented_by_me + liked_my_posts + commented_my_posts,
            "lastPostAt": authored_all[0].get("publishedEstimate") if authored_all else None,
            "lastPostText": (
                str(authored_all[0].get("text") or "").replace("\n", " ").strip()[:80]
                if authored_all
                else ""
            ),
        }
        return {
            "ok": True,
            "contact": contact_name,
            "ownerName": owner_name,
            "lastReadAt": store_doc.get("lastReadAt") or "",
            "authored": authored_all[:max_items],
            "interactedOnMine": interacted_all[:max_items],
            "stats": stats,
        }

    def _can_use_llm(self) -> bool:
        models = getattr(self.engine, "models", None)
        if models is None:
            return False
        is_enabled = getattr(models, "is_llm_enabled", None)
        if not callable(is_enabled):
            return False
        try:
            if not is_enabled():
                return False
        except Exception:
            return False
        return callable(getattr(models, "generate_chat_reply", None))

    def _read_soul_context(self, author: str) -> Dict[str, Any]:
        profiler = getattr(self.engine, "soul_profiler", None)
        if profiler is None or not author:
            return {}
        ctx: Dict[str, Any] = {}
        try:
            if hasattr(profiler, "get_contact_memory_context"):
                mem = profiler.get_contact_memory_context(author) or {}
                if isinstance(mem, dict):
                    if isinstance(mem.get("contactSoul"), dict):
                        ctx["contactSoul"] = mem["contactSoul"]
                    if isinstance(mem.get("ownerProfile"), dict):
                        owner_tone = ((mem["ownerProfile"].get("speakingStyle") or {}).get("toneTag") or "")
                        if owner_tone:
                            ctx["ownerTone"] = owner_tone
                    if mem.get("memoryPromptSnippet"):
                        ctx["memorySnippet"] = str(mem["memoryPromptSnippet"])[:320]
        except Exception:
            pass
        if not ctx.get("contactSoul"):
            try:
                if hasattr(profiler, "get_profiles"):
                    profs = profiler.get_profiles(target=author) or {}
                    cps = profs.get("contactProfiles") or []
                    if cps and isinstance(cps[0], dict):
                        c0 = cps[0]
                        ctx["contactSoul"] = {
                            "personalityTag": c0.get("personalityTag"),
                            "mbtiEstimate": c0.get("mbtiEstimate"),
                            "communicationPreferences": c0.get("communicationPreferences"),
                            "emotionalBaseline": c0.get("emotionalBaseline"),
                        }
            except Exception:
                pass
        return ctx

    @staticmethod
    def _heuristic_comments(post: Dict[str, Any], *, style: str = "natural") -> List[str]:
        text = str(post.get("text") or "").strip()
        attachments = [str(a) for a in (post.get("attachments") or []) if str(a).strip()]
        combined = f"{text} {' '.join(attachments)}".casefold()

        if any(k in combined for k in ("祝贺", "恭喜", "周年", "生日", "毕业", "结婚", "喜提", "顺利")):
            pool = ["恭喜恭喜，越来越好！", "太替你开心了", "值得好好纪念一下"]
        elif any(k in combined for k in ("吃", "饭", "咖啡", "茶", "火锅", "烧烤", "甜品", "面", "美食")):
            pool = ["看着就香，这家在哪呀", "卖相真不错，改天去尝尝", "好久没吃这口了"]
        elif any(k in combined for k in ("山", "海", "风景", "公园", "露营", "徒步", "散步", "夕阳", "天气", "旅行")):
            pool = ["这风景真舒服", "天气好出去走走真不错", "看着心情都亮了"]
        elif any(k in combined for k in ("项目", "上线", "加班", "读书", "reading", "论文", "学习", "复盘", "打卡", "早起", "模型", "代码")):
            pool = ["最近状态很稳啊", "这段写得挺实在", "辛苦啦，忙完好好歇会儿"]
        elif attachments:
            pool = ["马住，有空细看", "这篇看着挺有意思", "感谢分享，刚好用得上"]
        elif not text:
            pool = ["这张拍得挺有感觉", "最近挺惬意啊", "状态真不错"]
        else:
            pool = ["最近状态不错啊", "看到这条挺有共鸣的", "忙里偷闲挺舒服的"]

        if style == "concise":
            pool = ["太赞了", "确实不错", "厉害啊"] + pool
        elif style == "warm":
            pool = ["看着真替你高兴，多注意休息", "这段时间辛苦了，状态挺好"] + pool

        out: List[str] = []
        for item in pool:
            trimmed = _trim_comment(item)
            if trimmed and trimmed not in out:
                out.append(trimmed)
        return out

    def _fallback_comments(self, post: Dict[str, Any], *, style: str = "natural") -> Tuple[str, List[str], str]:
        author = str(post.get("author") or "").strip()
        author_key = normalize_key_text(author)
        templates = self.store.load_policy()["comment"]["templates"]
        by_contact = templates.get("byContact") or {}
        contact_pool = list(by_contact.get(author) or [])
        if not contact_pool and author_key:
            for k, vals in by_contact.items():
                if _name_matches(author_key, str(k)) and isinstance(vals, list):
                    contact_pool = list(vals)
                    break
        default_pool = list(templates.get("default") or [])
        template_pool = contact_pool or default_pool

        picked = ""
        if contact_pool:
            picked = _trim_comment(contact_pool[int(post.get("key", "0")[-4:], 16) % len(contact_pool)])
        elif template_pool:
            picked = _trim_comment(self.store.pick_comment(post))

        heuristic_pool = self._heuristic_comments(post, style=style)
        if picked:
            primary = picked
            source = "policy_template"
            candidates = template_pool + heuristic_pool
        else:
            primary = heuristic_pool[0] if heuristic_pool else "挺不错的"
            source = "rule_fallback"
            candidates = heuristic_pool[1:]

        alternatives: List[str] = []
        for item in candidates:
            cand = _trim_comment(str(item or ""))
            if cand and cand != primary and cand not in alternatives:
                alternatives.append(cand)
                if len(alternatives) >= 2:
                    break
        return primary, alternatives, source

    def _generate_llm_comments(self, post: Dict[str, Any], *, style: str = "natural") -> Dict[str, Any]:
        author = str(post.get("author") or "").strip()
        soul_ctx = self._read_soul_context(author)
        style_desc = _STYLE_HINTS.get(style, _STYLE_HINTS["natural"])
        payload = {
            "author": author,
            "style": style,
            "styleRequirement": style_desc,
            "postText": str(post.get("text") or "")[:400],
            "attachments": [str(a)[:120] for a in (post.get("attachments") or [])[:3]],
            "timeText": str(post.get("timeText") or ""),
            "source": str(post.get("source") or ""),
            "likesCount": len(post.get("likes") or []),
            "existingComments": [
                f"{c.get('author', '')}: {str(c.get('text') or '')[:60]}"
                for c in (post.get("comments") or [])[:4]
            ],
            "soulContext": soul_ctx,
        }
        system_prompt = (
            "你正在帮微信用户给好友的朋友圈写一条评论。要求：\n"
            "1. 口语化、自然、像真实熟人聊天（禁止AI腔、书面套话、感叹号堆砌、括号备注或复读原文）；\n"
            "2. 每条严格不超过40个汉字（建议8-26字）；\n"
            "3. 结合对方发的内容、附件、已有评论气氛和好友性格画像来写，绝不编造没提到的事实；\n"
            "4. 仅输出纯 JSON，格式为：{\"suggestedText\": \"主推评论\", \"alternatives\": [\"备选1\", \"备选2\"]}。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            res = self.engine.models.generate_chat_reply(
                messages,
                contact_name=author or None,
                temperature=0.6,
                max_tokens=512,
                timeout=15.0,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not isinstance(res, dict) or not res.get("ok") or not res.get("replyText"):
            return {"ok": False, "error": str((res or {}).get("error") if isinstance(res, dict) else "llm_empty")}
        primary, alts = _parse_suggested_comments_json(str(res.get("replyText") or ""))
        if not primary:
            return {"ok": False, "error": "invalid_json"}
        return {
            "ok": True,
            "suggestedText": primary,
            "alternatives": alts,
            "modelId": str(res.get("modelId") or ""),
        }

    def _default_comment_generator(self, post: Dict[str, Any]) -> str:
        if not self._can_use_llm():
            return ""
        llm_res = self._generate_llm_comments(post, style="natural")
        if llm_res.get("ok") and llm_res.get("suggestedText"):
            return str(llm_res["suggestedText"])
        return ""

    def suggest_comment(self, post_key: str, *, style: str = "natural") -> Dict[str, Any]:
        """为一条朋友圈帖子生成自然口语评论文案（优先调用 LLM + Soul 画像，失败平滑降级）。"""
        key = str(post_key or "").strip()
        post = self.store.load_posts()["posts"].get(key)
        if not isinstance(post, dict):
            return {"ok": False, "error_code": "post_not_found", "error": "帖子库里没有这一条"}
        author = str(post.get("author") or "").strip()
        clean_style = str(style or "natural").strip() or "natural"

        if self._can_use_llm():
            llm_res = self._generate_llm_comments(post, style=clean_style)
            if llm_res.get("ok") and llm_res.get("suggestedText"):
                primary = str(llm_res["suggestedText"])
                alts = list(llm_res.get("alternatives") or [])
                if len(alts) < 2:
                    fb_primary, fb_alts, _ = self._fallback_comments(post, style=clean_style)
                    for cand in [fb_primary, *fb_alts]:
                        if cand and cand != primary and cand not in alts:
                            alts.append(cand)
                            if len(alts) >= 2:
                                break
                return {
                    "ok": True,
                    "postKey": key,
                    "author": author,
                    "style": clean_style,
                    "suggestedText": primary,
                    "alternatives": alts[:2],
                    "usedLlm": True,
                    "modelId": str(llm_res.get("modelId") or ""),
                    "source": "llm",
                }

        primary, alts, source = self._fallback_comments(post, style=clean_style)
        return {
            "ok": True,
            "postKey": key,
            "author": author,
            "style": clean_style,
            "suggestedText": primary,
            "alternatives": alts[:2],
            "usedLlm": False,
            "modelId": "",
            "source": source,
        }

    def stats(self, *, limit: int = 40) -> Dict[str, Any]:
        return self.store.stats(limit=limit)

    def get_policy(self) -> Dict[str, Any]:
        return {"ok": True, "policy": self.store.load_policy()}

    def set_policy(self, updates: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            return {"ok": True, "policy": self.store.save_policy(updates)}
        except ValueError as exc:
            return {"ok": False, "error_code": "invalid_policy", "error": str(exc)}

    def plan(self, *, limit: int = 20, max_age_days: Optional[int] = None) -> Dict[str, Any]:
        generator = self.comment_generator
        if generator is None and self._can_use_llm():
            generator = self._default_comment_generator
        return self.store.build_plan(
            comment_generator=generator, max_age_days=max_age_days, limit=limit
        )

    def interaction_log(self, *, limit: int = 50) -> Dict[str, Any]:
        return {"ok": True, "items": self.store.interactions(limit=limit)}

    def crm_interactions(self) -> List[Dict[str, Any]]:
        return self.store.crm_interactions()

    def _require_for(self, mode: str) -> None:
        if mode not in MOMENTS_MODES:
            raise MomentsFlowError("invalid_mode", "mode 只能是 dry_run / silent_verify / live")
        self.engine._require(MOMENTS_CAP_READ)
        self.engine._require(MOMENTS_CAP_LIVE if mode == "live" else MOMENTS_CAP_DRY_RUN)

    def interact(
        self, post_key: str = "", *, author: str = "", action: str = "like", text: str = "",
        mode: str = "dry_run", restore_view: bool = True,
    ) -> Dict[str, Any]:
        """对一条帖子点赞 / 取消点赞 / 评论。

        dry_run（默认）只走到弹出「赞 / 评论」菜单并校验它的位置，不点下去；silent_verify 会把评论
        粘进输入框读回核对再放弃；live 才真正发出。"""
        self._require_for(mode)
        targets, error = self.store.resolve_targets(post_key=post_key, author=author, action=action, text=text)
        if error:
            return error
        return self.actions.execute(targets, mode=mode, restore_view=restore_view)

    def execute_plan(
        self, items: Optional[List[Dict[str, Any]]] = None, *, mode: str = "dry_run", limit: int = 5,
        restore_view: bool = True,
    ) -> Dict[str, Any]:
        """执行 plan() 给出的互动清单。默认 dry_run；真正发出需要显式 mode=live 且已授予 live 能力。"""
        self._require_for(mode)
        if items is None:
            items = self.plan(limit=limit)["items"]
        targets: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for item in list(items)[:max(0, int(limit))]:
            found, error = self.store.resolve_targets(
                post_key=str(item.get("postKey") or ""), action=str(item.get("action") or "like"),
                text=str(item.get("text") or ""),
            )
            if error:
                skipped.append({**item, "errorCode": error["error_code"]})
            else:
                targets.extend(found)
        if not targets:
            return {"ok": False, "error_code": "nothing_to_do", "error": "清单里没有可执行的项目", "skipped": skipped}
        return {**self.actions.execute(targets, mode=mode, restore_view=restore_view), "skipped": skipped}

    @property
    def actions(self) -> Any:
        if self._actions is None:
            # 延迟导入：动作模块要用到本模块的能力项常量
            from .moments_actions import MomentsInteractor

            self._actions = MomentsInteractor(self)
        return self._actions
