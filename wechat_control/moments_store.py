"""朋友圈本地档案：帖子库、互动台账、策略与频控。不碰任何界面，便于单测。"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .io_utils import atomic_write_json, atomic_write_text
from .moments_feed import POSTS_SCHEMA, normalize_key_text, public_post, same_post

MAX_STORED_POSTS = 2000
OBSERVATIONS_MAX_BYTES = 4 * 1024 * 1024
INTERACTIONS_MAX_ITEMS = 5000
MAX_COMMENT_CHARS = 600
POLICY_SCHEMA = "openbot.wechat-moments-policy/1"
# 隔了几天再读，同一条帖子的相对时间会变（「17天前」隔天成「18天前」），归并时允许的漂移
STORED_DRIFT_DAYS = 3.0

DEFAULT_POLICY: Dict[str, Any] = {
    "autoLike": {"enabled": False, "scope": "all", "contacts": [], "exclude": [], "maxAgeDays": 30},
    "comment": {"enabled": False, "templates": {"default": [], "byContact": {}}},
    "skipOwn": True,
    "skipAds": True,
}


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _est_ts(post: Dict[str, Any]) -> Optional[float]:
    raw = post.get("publishedEstimate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).timestamp()
    except ValueError:
        return None


def ordered_posts(posts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """新 → 旧；没有发布时间估计的排在最后。"""
    items = list(posts.values())
    items.sort(key=lambda p: (_est_ts(p) is not None, _est_ts(p) or 0.0), reverse=True)
    return items


class MomentsRateLimiter:
    """朋友圈互动频控：约束自动点赞、评论的节奏。按小时与自然日计数，进程重启后延续。"""

    def __init__(
        self,
        state_path: Path,
        *,
        per_contact_hourly: int = 2,
        global_hourly: int = 10,
        global_daily: int = 30,
        min_gap_seconds: int = 45,
        now_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.per_contact_hourly = int(per_contact_hourly)
        self.global_hourly = int(global_hourly)
        self.global_daily = int(global_daily)
        self.min_gap_seconds = int(min_gap_seconds)
        self._now = now_fn or time.time
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, Any]:
        try:
            doc = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
        return {}

    @staticmethod
    def _hour_key(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H")

    @staticmethod
    def _day_key(ts: float) -> str:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")

    def check(self, author: str) -> Tuple[bool, str]:
        ts = self._now()
        with self._lock:
            doc = self._load()
            if doc.get("dayKey") != self._day_key(ts):
                return True, "ok"
            hour = self._hour_key(ts)
            if int(doc.get("day", 0)) >= self.global_daily:
                return False, f"daily_limit:{doc.get('day', 0)}/{self.global_daily}"
            if int((doc.get("hours") or {}).get(hour, 0)) >= self.global_hourly:
                return False, f"hourly_limit:{(doc.get('hours') or {}).get(hour, 0)}/{self.global_hourly}"
            contact = (doc.get("contacts") or {}).get(normalize_key_text(author).casefold()) or {}
            if contact.get("hourKey") == hour and int(contact.get("hour", 0)) >= self.per_contact_hourly:
                return False, f"contact_hourly_limit:{contact.get('hour', 0)}/{self.per_contact_hourly}"
            last = float(doc.get("lastTs") or 0.0)
            if last and ts - last < self.min_gap_seconds:
                return False, f"gap:{int(ts - last)}s<{self.min_gap_seconds}s"
            return True, "ok"

    def record(self, author: str) -> None:
        ts = self._now()
        with self._lock:
            doc = self._load()
            day = self._day_key(ts)
            if doc.get("dayKey") != day:
                doc = {"dayKey": day, "day": 0, "hours": {}}
            hour = self._hour_key(ts)
            hours = doc.setdefault("hours", {})
            hours[hour] = int(hours.get(hour, 0)) + 1
            for key in sorted(hours)[:-48]:
                hours.pop(key, None)
            doc["day"] = int(doc.get("day", 0)) + 1
            ckey = normalize_key_text(author).casefold()
            contacts = doc.setdefault("contacts", {})
            contact = contacts.setdefault(ckey, {})
            if contact.get("hourKey") != hour:
                contact["hourKey"] = hour
                contact["hour"] = 0
            contact["hour"] = int(contact.get("hour", 0)) + 1
            doc["lastTs"] = ts
            atomic_write_json(self.state_path, doc)

    def status(self) -> Dict[str, Any]:
        ts = self._now()
        with self._lock:
            doc = self._load()
            same_day = doc.get("dayKey") == self._day_key(ts)
            return {
                "dailyUsed": int(doc.get("day", 0)) if same_day else 0,
                "dailyLimit": self.global_daily,
                "hourlyUsed": int((doc.get("hours") or {}).get(self._hour_key(ts), 0)) if same_day else 0,
                "hourlyLimit": self.global_hourly,
                "perContactHourlyLimit": self.per_contact_hourly,
                "minGapSeconds": self.min_gap_seconds,
            }


def normalize_policy(updates: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """把用户的局部修改并入默认策略，并校验类型。返回新策略，不修改入参。"""
    policy = copy.deepcopy(DEFAULT_POLICY)
    if not isinstance(updates, dict):
        return policy

    def merge(target: Dict[str, Any], patch: Dict[str, Any]) -> None:
        for key, value in patch.items():
            if key not in target:
                raise ValueError(f"未知的策略项: {key}")
            if isinstance(target[key], dict):
                if not isinstance(value, dict):
                    raise ValueError(f"策略项 {key} 应为对象")
                merge(target[key], value)
            elif isinstance(target[key], bool):
                if not isinstance(value, bool):
                    raise ValueError(f"策略项 {key} 应为布尔值")
                target[key] = value
            elif isinstance(target[key], int):
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"策略项 {key} 应为非负整数")
                target[key] = value
            elif isinstance(target[key], list):
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError(f"策略项 {key} 应为字符串数组")
                target[key] = [v.strip() for v in value if v.strip()]
            else:
                if not isinstance(value, str):
                    raise ValueError(f"策略项 {key} 应为字符串")
                target[key] = value.strip()

    merge(policy, updates)
    if policy["autoLike"]["scope"] not in ("all", "contacts"):
        raise ValueError("autoLike.scope 只能是 all 或 contacts")
    for author, templates in policy["comment"]["templates"]["byContact"].items():
        if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
            raise ValueError(f"联系人 {author} 的评论模板应为字符串数组")
    return policy


class MomentsStore:
    """朋友圈本地档案，全部原子落盘：posts.json 帖子库、observations.jsonl 读取记录、
    interactions.json 互动台账、policy.json 自动互动策略、rate_limit.json 频控计数。"""

    def __init__(self, store_dir: Path, *, clock_fn: Optional[Callable[[], float]] = None) -> None:
        self.dir = Path(store_dir)
        self._now = clock_fn or time.time
        self.limiter = MomentsRateLimiter(self.dir / "rate_limit.json", now_fn=self._now)

    @property
    def posts_path(self) -> Path:
        return self.dir / "posts.json"

    @property
    def policy_path(self) -> Path:
        return self.dir / "policy.json"

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None

    # ---------- 帖子库 ----------
    def load_posts(self) -> Dict[str, Any]:
        doc = self._read_json(self.posts_path)
        if isinstance(doc, dict) and isinstance(doc.get("posts"), dict):
            return doc
        return {"schema": POSTS_SCHEMA, "updatedAt": "", "ownerName": "", "lastReadAt": "", "posts": {}}

    def owner_name(self) -> str:
        return str(self.load_posts().get("ownerName") or "")

    def complete_posts(self) -> List[Dict[str, Any]]:
        return [post for post in ordered_posts(self.load_posts()["posts"]) if not post.get("partial")]

    @staticmethod
    def find_stored(recent: List[Dict[str, Any]], post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for stored in reversed(recent):
            if same_post(stored, post, max_drift_days=STORED_DRIFT_DAYS):
                return stored
        return None

    def save_read(self, posts: List[Dict[str, Any]], *, owner: str = "") -> Dict[str, int]:
        """把一次读取的结果并入帖子库。

        只露半截的帖子（partial）不单独建档——它的作者或页脚没读全，统计会算错人；已有的完整记录
        则照常补点赞和评论。"""
        store = self.load_posts()
        bucket = store["posts"]
        now_iso = _utc_iso(self._now())
        recent = ordered_posts(bucket)[:160]
        counts = {"newPosts": 0, "refreshed": 0, "partialSkipped": 0}
        for post in posts:
            existing = self.find_stored(recent, post)
            if existing is None and post.get("partial"):
                counts["partialSkipped"] += 1
                continue
            if existing is None:
                record = copy.deepcopy(public_post(post))
                record["partial"] = False
                record.update({"firstSeenAt": now_iso, "lastSeenAt": now_iso, "seenCount": 1})
                bucket[record["key"]] = record
                recent.insert(0, record)
                counts["newPosts"] += 1
            else:
                self._refresh(existing, post, now_iso)
                counts["refreshed"] += 1
        for stale in ordered_posts(bucket)[MAX_STORED_POSTS:]:
            bucket.pop(stale.get("key"), None)
        if owner:
            store["ownerName"] = owner
        store["lastReadAt"] = now_iso
        store["updatedAt"] = now_iso
        atomic_write_json(self.posts_path, store)
        return counts

    @staticmethod
    def _refresh(existing: Dict[str, Any], post: Dict[str, Any], now_iso: str) -> None:
        existing["lastSeenAt"] = now_iso
        existing["seenCount"] = int(existing.get("seenCount") or 0) + 1
        for name in post.get("likes") or []:
            if name and name not in existing.setdefault("likes", []):
                existing["likes"].append(name)
        comments = existing.setdefault("comments", [])
        for comment in post.get("comments") or []:
            if not any(
                c.get("author") == comment.get("author") and c.get("text") == comment.get("text")
                for c in comments
            ):
                comments.append(dict(comment))
        for field in ("isOwn", "likedByMe", "commentedByMe"):
            existing[field] = bool(existing.get(field)) or bool(post.get(field))
        if not post.get("partial"):
            for field in ("text", "collapsed", "attachments", "timeText", "source", "publishedEstimate"):
                if post.get(field) not in (None, "", []):
                    existing[field] = copy.deepcopy(post[field])

    def apply_interaction(
        self, post_key: str, *, action: str, owner: str, comment_text: str = ""
    ) -> bool:
        """互动成功后同步帖子库。返回是否找到了这条帖子。"""
        store = self.load_posts()
        post = store["posts"].get(post_key)
        if not isinstance(post, dict):
            return False
        me = normalize_key_text(owner)
        likes = post.setdefault("likes", [])
        if action == "like":
            if owner and owner not in likes:
                likes.append(owner)
            post["likedByMe"] = True
        elif action == "unlike":
            post["likes"] = [name for name in likes if normalize_key_text(name) != me]
            post["likedByMe"] = False
        elif action == "comment" and comment_text:
            comments = post.setdefault("comments", [])
            if not any(
                normalize_key_text(c.get("author") or "") == me and c.get("text") == comment_text
                for c in comments
            ):
                comments.append({"author": owner, "replyTo": "", "text": comment_text})
            post["commentedByMe"] = True
        else:
            return False
        atomic_write_json(self.posts_path, store)
        return True

    # ---------- 读取记录 ----------
    def record_observation(self, note: Dict[str, Any]) -> None:
        path = self.dir / "observations.jsonl"
        try:
            if path.exists() and path.stat().st_size > OBSERVATIONS_MAX_BYTES:
                lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
                atomic_write_text(path, "".join(lines[len(lines) // 2:]))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": _utc_iso(self._now()), **note}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------- 自动互动策略 ----------
    def load_policy(self) -> Dict[str, Any]:
        doc = self._read_json(self.policy_path)
        if isinstance(doc, dict):
            doc.pop("schema", None)
        try:
            return normalize_policy(doc)
        except ValueError:
            return normalize_policy(None)

    def save_policy(self, updates: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        policy = normalize_policy(updates)
        atomic_write_json(self.policy_path, {"schema": POLICY_SCHEMA, **policy})
        return policy

    def pick_comment(self, post: Dict[str, Any], comment_generator: Optional[Callable[[Dict[str, Any]], str]] = None) -> str:
        """给这条帖子挑一条评论文案：优先用调用方注入的生成器（例如按人设生成），否则用模板轮换。"""
        if comment_generator is not None:
            try:
                text = str(comment_generator(post) or "").strip()
            except Exception:
                text = ""
            if text:
                return text[:MAX_COMMENT_CHARS]
        templates = self.load_policy()["comment"]["templates"]
        pool = templates["byContact"].get(post.get("author") or "") or templates["default"]
        if not pool:
            return ""
        return pool[int(post.get("key", "0")[-4:], 16) % len(pool)]

    @staticmethod
    def _age_days(post: Dict[str, Any], now: float) -> Optional[float]:
        ts = _est_ts(post)
        return None if ts is None else max(0.0, (now - ts) / 86400.0)

    def build_plan(
        self,
        *,
        comment_generator: Optional[Callable[[Dict[str, Any]], str]] = None,
        max_age_days: Optional[int] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """按策略列出可以自动互动的帖子，供人过目后再执行。只读，不碰界面。"""
        policy = self.load_policy()
        now = self._now()
        window_days = int(max_age_days if max_age_days is not None else policy["autoLike"]["maxAgeDays"])
        items: List[Dict[str, Any]] = []
        for post in self.complete_posts():
            if post.get("isOwn") and policy["skipOwn"]:
                continue
            if post.get("isAd") and policy["skipAds"]:
                continue
            age = self._age_days(post, now)
            if age is None or age > window_days:
                continue
            author = post.get("author") or ""
            if any(token and token in author for token in policy["autoLike"]["exclude"]):
                continue
            item = {
                "postKey": post["key"], "author": author, "timeText": post.get("timeText") or "",
                "publishedEstimate": post.get("publishedEstimate"),
                "snippet": (post.get("text") or "").replace("\n", " ")[:40],
            }
            auto_like = policy["autoLike"]
            in_scope = auto_like["scope"] == "all" or any(token and token in author for token in auto_like["contacts"])
            if auto_like["enabled"] and in_scope and not post.get("likedByMe"):
                items.append({**item, "action": "like", "text": "", "reason": "auto_like_policy"})
            if policy["comment"]["enabled"] and not post.get("commentedByMe"):
                text = self.pick_comment(post, comment_generator)
                if text:
                    items.append({**item, "action": "comment", "text": text, "reason": "comment_template"})
        return {
            "ok": True, "policy": policy, "windowDays": window_days,
            "total": len(items), "items": items[:max(0, int(limit))],
        }

    # ---------- 互动台账 ----------
    def interactions(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        doc = self._read_json(self.dir / "interactions.json")
        items = list(doc.get("items") or []) if isinstance(doc, dict) else []
        return list(reversed(items[-max(0, int(limit)):]))

    def record_interaction(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        path = self.dir / "interactions.json"
        doc = self._read_json(path)
        items = list(doc.get("items") or []) if isinstance(doc, dict) else []
        item = {"id": f"mxi_{int(self._now() * 1000):x}_{len(items):x}", "at": _utc_iso(self._now()), **entry}
        items.append(item)
        del items[:-INTERACTIONS_MAX_ITEMS]
        atomic_write_json(path, {"schema": "openbot.wechat-moments-interactions/1", "items": items})
        return item

    # ---------- 统计 ----------
    def stats(self, *, limit: int = 40, pending_days: int = 30) -> Dict[str, Any]:
        """按联系人汇总朋友圈往来。只统计完整读到的帖子；「待点赞」是近 pending_days 天里还没赞过的。"""
        store = self.load_posts()
        owner_key = normalize_key_text(store.get("ownerName") or "")
        now = self._now()
        contacts: Dict[str, Dict[str, Any]] = {}
        received = {"likes": 0, "comments": 0}

        def entry(name: str) -> Dict[str, Any]:
            return contacts.setdefault(name, {
                "author": name, "posts": 0, "likedByMe": 0, "commentedByMe": 0,
                "likedMyPosts": 0, "commentedMyPosts": 0, "pendingLike": 0,
                "lastPostAt": None, "lastPostText": "",
            })

        for post in ordered_posts(store["posts"]):
            if post.get("partial"):
                continue
            author = post.get("author") or ""
            if post.get("isOwn") or (owner_key and normalize_key_text(author) == owner_key):
                received["likes"] += len(post.get("likes") or [])
                received["comments"] += len(post.get("comments") or [])
                for name in post.get("likes") or []:
                    if normalize_key_text(name) != owner_key:
                        entry(name)["likedMyPosts"] += 1
                for comment in post.get("comments") or []:
                    if normalize_key_text(comment.get("author") or "") != owner_key:
                        entry(comment.get("author") or "")["commentedMyPosts"] += 1
                continue
            row = entry(author)
            row["posts"] += 1
            estimate = post.get("publishedEstimate")
            if estimate and (row["lastPostAt"] is None or estimate > row["lastPostAt"]):
                row["lastPostAt"] = estimate
                row["lastPostText"] = (post.get("text") or "").replace("\n", " ")[:40]
            if post.get("likedByMe"):
                row["likedByMe"] += 1
            if post.get("commentedByMe"):
                row["commentedByMe"] += 1
            age = self._age_days(post, now)
            if not post.get("likedByMe") and age is not None and age <= pending_days:
                row["pendingLike"] += 1

        ledger = [x for x in self.interactions(limit=INTERACTIONS_MAX_ITEMS) if x.get("mode") == "live"]
        done = [x for x in ledger if x.get("status") in ("verified", "sent_unverified")]
        return {
            "ok": True,
            "generatedAt": _utc_iso(self._now()),
            "ownerName": store.get("ownerName") or "",
            "lastReadAt": store.get("lastReadAt") or "",
            "storedPosts": len(store["posts"]),
            "completePosts": sum(1 for p in store["posts"].values() if not p.get("partial")),
            "myInteractions": {
                "likes": sum(1 for x in done if x.get("action") in ("like", "unlike")),
                "comments": sum(1 for x in done if x.get("action") == "comment"),
                "lastAt": done[-1].get("at") if done else "",
            },
            "received": received,
            "contacts": sorted(contacts.values(), key=lambda r: (-r["posts"], r["author"]))[:max(0, int(limit))],
            "rateLimiter": self.limiter.status(),
            "policy": self.load_policy(),
        }

    def crm_interactions(self) -> List[Dict[str, Any]]:
        """把帖子库里的点赞、评论往来展开成「一条帖子 × 一个人」的互动记录，供 SalesCRM 朋友圈指标使用。"""
        store = self.load_posts()
        owner_key = normalize_key_text(store.get("ownerName") or "")
        rows: List[Dict[str, Any]] = []
        if not owner_key:
            return rows
        for post in ordered_posts(store["posts"]):
            if post.get("partial"):
                continue
            author = post.get("author") or ""
            ts = _est_ts(post)
            when = int(ts) if ts else int(self._now())
            pairs: List[Tuple[str, str]] = []
            if normalize_key_text(author) == owner_key:
                pairs = [(name, "like_in") for name in post.get("likes") or [] if normalize_key_text(name) != owner_key]
                pairs += [
                    (c.get("author") or "", "comment_in") for c in post.get("comments") or []
                    if normalize_key_text(c.get("author") or "") != owner_key
                ]
            else:
                if any(normalize_key_text(name) == owner_key for name in post.get("likes") or []):
                    pairs.append((author, "like_out"))
                if any(normalize_key_text(c.get("author") or "") == owner_key for c in post.get("comments") or []):
                    pairs.append((author, "comment_out"))
            for person, kind in pairs:
                if not person:
                    continue
                rows.append({
                    "id": f"mm_{post['key']}_{kind}_{hashlib.sha1(normalize_key_text(person).encode('utf-8')).hexdigest()[:10]}",
                    "person": person, "kind": kind, "timestamp": when, "postKey": post["key"],
                })
        return rows

    def resolve_targets(
        self, *, post_key: str = "", author: str = "", action: str = "like", text: str = ""
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """把帖子指纹或昵称解析成要操作的目标。返回 (目标列表, 错误)。"""
        if action not in ("like", "unlike", "comment"):
            return [], {"ok": False, "error_code": "invalid_action", "error": "action 只能是 like / unlike / comment"}
        cleaned = (text or "").strip()
        if action == "comment" and not cleaned:
            return [], {"ok": False, "error_code": "comment_text_required", "error": "评论需要提供 text"}
        if len(cleaned) > MAX_COMMENT_CHARS:
            return [], {"ok": False, "error_code": "comment_too_long", "error": f"评论最多 {MAX_COMMENT_CHARS} 字"}
        posts = self.complete_posts()
        if post_key:
            post = next((p for p in posts if p.get("key") == post_key), None)
            if post is None:
                return [], {"ok": False, "error_code": "post_not_found", "error": f"帖子库里没有 {post_key}，请先读取朋友圈"}
        elif author:
            key = normalize_key_text(author)
            candidates = [p for p in posts if normalize_key_text(p.get("author") or "") == key]
            wanted = [p for p in candidates if bool(p.get("likedByMe")) == (action == "unlike")]
            if not wanted:
                code = "already_liked" if action == "like" and candidates else "no_matching_post"
                return [], {"ok": False, "error_code": code, "error": f"{author} 名下没有可{('取消点赞' if action == 'unlike' else '点赞')}的帖子"}
            post = wanted[0]
        else:
            return [], {"ok": False, "error_code": "target_required", "error": "需要提供 post_key 或 author"}
        if action == "like" and post.get("likedByMe"):
            return [], {"ok": False, "error_code": "already_liked", "error": "这条帖子已经赞过，不再重复点赞"}
        return [{
            "postKey": post["key"], "author": post.get("author") or "", "action": action,
            "text": cleaned, "snapshot": copy.deepcopy(post),
        }], None
