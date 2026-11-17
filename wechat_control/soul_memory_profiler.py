"""WeChatBridge Dual-Persona ("Owner Self Soul" + "Friend Soul") & Long-Term Memory Profiler.

Combines non-invasive macOS WeChat OCR observed chat logs (`logs/contacts/*_history.json`),
session analytics (`logs/contact_analytics_report.json`), WeChatBridge `.zip` / `聊天记录.txt`
transcripts (`bridge_importer.py`), and explicit manual memory notes (`config/soul_memories.json`)
to construct:

1. **微信号主人「本我画像」(Owner / Self Soul Profile)**:
   - Analyzes all `self` / owner outgoing messages across chats and bridges to model the account
     owner's speaking style (average sentence length, catchphrases, punctuation/emoji habits),
     active peak hours, core projects/facts (`zhhao_1995`, `郝泽华`, `安心的AI工作室`, `OpenBot`,
     `StaffDeck`), and cross-contact role-switching matrix.
   - Generates a live system prompt and keeps the `owner-digital-twin` ("🎭 号主本人数字分身")
     persona synchronized in `PersonaSwitchEngine`.

2. **好友深度心智画像 (Friend / Contact Soul Profile)**:
   - Extracts each friend/group's personality archetype, estimated MBTI, emotional baseline,
     communication preferences, core topics, interaction boundaries, and rapport score.

3. **结构化长期记忆图谱 (Episodic & Semantic Memories)**:
   - Organizes verifiable memories into `facts` (事实/身份/偏好), `episodicEvents` (事件与约定),
     and `sharedContext` (共同话题与梗), with source attribution so smart replies naturally
     recall shared history without hallucination.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .contact_profiler import FOLDER_CHAT_TITLES, extract_time_markers
from .live_inspector import _matches_target, _slugify_target
from .safety import normalize_chat_name

DEFAULT_OWNER_ALIASES = ("我", "self", "owner", "本人", "号主", "郝泽华", "zhhao_1995")
_NOISE_LINE_RE = re.compile(r"^[\W_0-9]{1,3}$")
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_GITHUB_RE = re.compile(r"(?:github\.com/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)?|[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)")
_WECHAT_ID_RE = re.compile(r"微信号[：:]\s*([A-Za-z0-9_\-]+)")
_STUDIO_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]+AI工作室|[\u4e00-\u9fffA-Za-z0-9]+工作室)")
_BOOK_OR_VIDEO_RE = re.compile(r"[《“]([^》”]{2,24})[》”]")
_COMMITMENT_HINTS = ("测试", "总结", "地址", "定时", "预约", "约定", "记得", "一起", "明天", "下周", "周末", "方案", "验收")
_CATCHPHRASE_CANDIDATES = (
    "哈哈",
    "收到",
    "久病成医",
    "丝滑",
    "总结",
    "开源",
    "可以",
    "没问题",
    "没绷住",
    "嗯哼",
    "你好",
    "谢谢",
    "看看",
    "试试",
)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _is_meaningful_utterance(text: str) -> bool:
    clean = _clean_text(text)
    if not clean or len(clean) < 2:
        return False
    if _NOISE_LINE_RE.match(clean):
        return False
    if clean in (">", "详情", "暂不支持该内容，请在手机上查看"):
        return False
    return True


def _extract_speaking_metrics(texts: List[str]) -> Dict[str, Any]:
    clean_texts = [_clean_text(t) for t in texts if _is_meaningful_utterance(t)]
    if not clean_texts:
        return {
            "sampleCount": 0,
            "avgSentenceLength": 0.0,
            "shortRatio": 0.0,
            "questionRate": 0.0,
            "exclaimRate": 0.0,
            "emojiOrTildeRate": 0.0,
            "catchphrases": [],
            "punctuationHabits": "样本待采集",
            "toneTag": "自然真实 · 待补充更多语料",
        }

    total = len(clean_texts)
    avg_len = round(sum(len(t) for t in clean_texts) / total, 1)
    short_ratio = round(sum(1 for t in clean_texts if len(t) <= 12) / total, 2)
    q_rate = round(sum(1 for t in clean_texts if "?" in t or "？" in t) / total, 2)
    e_rate = round(sum(1 for t in clean_texts if "!" in t or "！" in t) / total, 2)
    warm_rate = round(
        sum(1 for t in clean_texts if any(ch in t for ch in ("～", "~", "😄", "👋", "✨", "🤖", "哈哈"))) / total,
        2,
    )

    phrase_counts: Counter[str] = Counter()
    blob = "\n".join(clean_texts)
    for phrase in _CATCHPHRASE_CANDIDATES:
        cnt = blob.count(phrase)
        if cnt > 0:
            phrase_counts[phrase] = cnt
    catchphrases = [p for p, _ in phrase_counts.most_common(6)]

    habits: List[str] = []
    if short_ratio >= 0.6:
        habits.append("短句直给，少客套长段落")
    elif avg_len >= 18:
        habits.append("信息密度高、常带技术/项目说明")
    else:
        habits.append("中短句自然口语")

    if q_rate >= 0.25:
        habits.append("善用反问/确认推动对话")
    if warm_rate >= 0.2 or e_rate >= 0.2:
        habits.append("熟悉对象会带「～/表情/感叹」缓和气氛")
    else:
        habits.append("克制少用夸张表情，重点落在事实本身")

    if short_ratio >= 0.65 and warm_rate < 0.2:
        tone_tag = "简练直接 · 高信噪比口语型"
    elif warm_rate >= 0.25:
        tone_tag = "真诚轻松 · 带生活幽默与互动感"
    else:
        tone_tag = "理性务实 · 技术/协作兼顾友好"

    return {
        "sampleCount": total,
        "avgSentenceLength": avg_len,
        "shortRatio": short_ratio,
        "questionRate": q_rate,
        "exclaimRate": e_rate,
        "emojiOrTildeRate": warm_rate,
        "catchphrases": catchphrases,
        "punctuationHabits": "；".join(habits),
        "toneTag": tone_tag,
    }


def _dedupe_memory_items(items: List[Dict[str, Any]], limit: int = 16) -> List[Dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        content = _clean_text(str(item.get("content") or ""))
        if not content:
            continue
        item_id = str(item.get("id") or _stable_id("mem", str(item.get("category") or "fact"), content))
        key = content.casefold()
        if item_id in seen_ids or key in seen_text:
            continue
        seen_ids.add(item_id)
        seen_text.add(key)
        copy_item = dict(item)
        copy_item["id"] = item_id
        copy_item["content"] = content
        out.append(copy_item)
        if len(out) >= limit:
            break
    return out


class SoulMemoryProfiler:
    """Builds and persists Owner Self-Soul, Friend Psychological Profiles, and Episodic Memories."""

    def __init__(
        self,
        *,
        histories_dir: Path,
        reports_dir: Path,
        store_path: Path,
        analytics_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        bindings_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        persona_sync_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.histories_dir = Path(histories_dir)
        self.reports_dir = Path(reports_dir)
        self.store_path = Path(store_path)
        self.analytics_provider = analytics_provider
        self.bindings_provider = bindings_provider
        self.persona_sync_cb = persona_sync_cb
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.histories_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Store I/O
    # ------------------------------------------------------------------

    def _empty_store(self) -> Dict[str, Any]:
        return {
            "schema": "openbot.wechat-soul-memories/1",
            "updatedAt": "",
            "ownerAliases": list(DEFAULT_OWNER_ALIASES),
            "manualMemories": {},
            "bridgeArchives": [],
            "ownerProfile": {},
            "contactProfiles": {},
        }

    def _load_store(self) -> Dict[str, Any]:
        if not self.store_path.exists():
            return self._empty_store()
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = self._empty_store()
                base.update(data)
                base.setdefault("manualMemories", {})
                base.setdefault("bridgeArchives", [])
                base.setdefault("ownerProfile", {})
                base.setdefault("contactProfiles", {})
                return base
        except Exception:
            pass
        return self._empty_store()

    def _save_store(self, data: Dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data["updatedAt"] = _utc_iso_now()
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Source Data Loading
    # ------------------------------------------------------------------

    def _load_contact_histories(self) -> Dict[str, Dict[str, Any]]:
        by_key: Dict[str, Dict[str, Any]] = {}
        if not self.histories_dir.exists():
            return by_key
        for hp in sorted(self.histories_dir.glob("*_history.json")):
            try:
                data = json.loads(hp.read_text(encoding="utf-8"))
                title = str(data.get("matchedTitle") or data.get("target") or "").strip()
                if not title:
                    continue
                key = normalize_chat_name(title).casefold()
                existing = by_key.get(key)
                if existing:
                    # Merge records cleanly
                    seen = {
                        (r.get("kind"), r.get("direction"), r.get("timeMarker"), r.get("text"))
                        for r in (existing.get("records") or [])
                    }
                    merged_records = list(existing.get("records") or [])
                    for rec in data.get("records") or []:
                        sig = (rec.get("kind"), rec.get("direction"), rec.get("timeMarker"), rec.get("text"))
                        if sig not in seen:
                            seen.add(sig)
                            merged_records.append(rec)
                    existing["records"] = merged_records
                else:
                    by_key[key] = data
            except Exception:
                continue
        return by_key

    # ------------------------------------------------------------------
    # Memory Extraction Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_facts_from_records(
        title: str,
        records: List[Dict[str, Any]],
        snippets: List[str],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract deterministic facts, episodicEvents, and sharedContext from bidirectional chat logs."""
        facts: List[Dict[str, Any]] = []
        events: List[Dict[str, Any]] = []
        shared: List[Dict[str, Any]] = []

        all_texts = [
            _clean_text(str(r.get("text") or ""))
            for r in records
            if r.get("kind") != "timestamp"
        ] + [_clean_text(s) for s in snippets]

        blob = "\n".join(all_texts)

        # Extract URLs
        for url in _URL_RE.findall(blob):
            clean_url = url.rstrip(".,;)")
            shared.append({
                "id": _stable_id("sh_url", title, clean_url),
                "category": "shared",
                "content": f"共同交流/分享过网页链接：{clean_url}",
                "source": "chat_log_extract",
            })

        # Extract GitHub repos
        for gh in _GITHUB_RE.findall(blob):
            if "com/" in gh or gh.lower().startswith("openbmb/"):
                shared.append({
                    "id": _stable_id("sh_gh", title, gh),
                    "category": "shared",
                    "content": f"涉及开源项目/仓库：{gh}",
                    "source": "chat_log_extract",
                })

        # Extract WeChat ID & Studio / Org facts
        for wid in _WECHAT_ID_RE.findall(blob):
            facts.append({
                "id": _stable_id("fact_wx", wid),
                "category": "fact",
                "content": f"微信号账号标识：{wid}",
                "source": "wechat_team_notice",
            })
        for studio in _STUDIO_RE.findall(blob):
            facts.append({
                "id": _stable_id("fact_org", studio),
                "category": "fact",
                "content": f"关联组织/工作室：{studio}",
                "source": "chat_log_extract",
            })

        # Extract named books, videos, tools
        for quoted in _BOOK_OR_VIDEO_RE.findall(blob):
            clean_q = quoted.strip()
            if len(clean_q) >= 3:
                shared.append({
                    "id": _stable_id("sh_ref", title, clean_q),
                    "category": "shared",
                    "content": f"对话提及书目/概念「{clean_q}」",
                    "source": "chat_log_extract",
                })

        # Domain-specific high-value entities observed in local WeChat records
        entity_rules = [
            ("StaffDeck", "讨论并关注企业级数字员工开源平台 StaffDeck（OpenBMB）"),
            ("OpenBot", "围绕 OpenBot 自动化 Agent 与微信 RPA 插件协同"),
            ("YoBot", "交流过微信机器人控制端参考项目 yobot.yokoagi.com"),
            ("ICLR", "关注顶会 ICLR / 世界模型学术论文动向"),
            ("呆猫吃娱", "互发轻松趣味短视频/视频号内容（如《呆猫吃娱》）"),
            ("围观群众小葵子", "分享搞笑/生活类视频号《围观群众小葵子》"),
            ("影刀", "对比讨论过 RPA 与影刀/按键精灵自动化技术差异"),
            ("Personal Agent", "个人助手/虚拟机/云电脑硬件配置调研归档"),
            ("AI工具箱", "收藏并沉淀「宝藏 AI 工具箱」资料"),
            ("郝泽华", "企业微信联系人「郝泽华@安心的AI工作室」"),
        ]
        for needle, summary in entity_rules:
            if needle.casefold() in blob.casefold():
                shared.append({
                    "id": _stable_id("sh_ent", title, needle),
                    "category": "shared",
                    "content": summary,
                    "source": "chat_log_extract",
                })

        # Extract episodic events from timestamped messages
        for rec in records:
            if rec.get("kind") != "message":
                continue
            txt = _clean_text(str(rec.get("text") or ""))
            if not _is_meaningful_utterance(txt):
                continue
            t_mark = _clean_text(str(rec.get("timeMarker") or ""))
            direction = str(rec.get("direction") or "peer")
            who = "我方(号主)" if direction == "self" else f"对方({normalize_chat_name(title)})"
            is_event = (
                bool(t_mark and len(txt) >= 5)
                or any(h in txt for h in _COMMITMENT_HINTS)
            )
            if is_event:
                events.append({
                    "id": _stable_id("evt", title, t_mark, direction, txt[:40]),
                    "category": "event",
                    "content": f"{who}：{txt[:110]}",
                    "timeMarker": t_mark or "近期会话",
                    "direction": direction,
                    "source": str(rec.get("source") or "ocr_history"),
                })

        return (
            _dedupe_memory_items(facts, limit=12),
            _dedupe_memory_items(events, limit=16),
            _dedupe_memory_items(shared, limit=14),
        )

    # ------------------------------------------------------------------
    # Contact & Owner Synthesis
    # ------------------------------------------------------------------

    @staticmethod
    def _synthesize_contact_soul(
        title: str,
        *,
        analytics_entry: Dict[str, Any],
        binding: Optional[Dict[str, Any]],
        records: List[Dict[str, Any]],
        facts: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        shared: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        norm = normalize_chat_name(title)
        cf = norm.casefold()
        self_texts = [
            _clean_text(str(r.get("text") or ""))
            for r in records
            if r.get("kind") == "message" and r.get("direction") == "self"
        ]
        peer_texts = [
            _clean_text(str(r.get("text") or ""))
            for r in records
            if r.get("kind") == "message" and r.get("direction") == "peer"
        ]
        if not peer_texts:
            peer_texts = list(analytics_entry.get("sampleExcerpts") or [])

        peer_metrics = _extract_speaking_metrics(peer_texts)
        self_metrics = _extract_speaking_metrics(self_texts)
        warmth = int(analytics_entry.get("warmthScore") or 50)
        care_level = str(analytics_entry.get("careLevel") or "normal")
        peak_slot = str(analytics_entry.get("peakTimeSlot") or "时段样本待补充")
        categories = list(analytics_entry.get("contentCategories") or ["日常沟通"])

        if "心安" in cf:
            personality_tag = "灵动接梗 · 工具与生活双栖密友"
            mbti_est = "ENFP / ENTP (脑洞好奇与分享欲强)"
            psych_summary = (
                "对新鲜 AI 工具（如 YoBot、OpenBot、RPA）与生活趣味短视频都很有分享欲；"
                "回复节奏轻量直接，信任号主并乐于共同参与定时互动与系统测试。"
            )
            comm_prefs = "喜欢简短直给带轻微玩笑感（～/表情），反感生硬客服套话或长篇说教；清晨与午后回复活跃。"
            emotional_baseline = "轻松积极 · 高信任亲密度"
            boundaries = "测试类定时问候可轻松活泼；勿连续刷屏发长篇公文。"
        elif "openbot" in cf:
            personality_tag = "极客工程共建 · 高信噪比测试群"
            mbti_est = "INTJ / INTP (系统架构与开源务实派)"
            psych_summary = (
                "聚焦 GitHub 开源 Agent（OpenBMB/StaffDeck）、SOP 沉淀、影刀/RPA 原理对比与端到端回归测试。"
                "重事实与可复现结果，轻寒暄。"
            )
            comm_prefs = "优先结论先行，附带具体仓库名、机制区别或测试数据。"
            emotional_baseline = "专注理性 · 工程协作场"
            boundaries = "仅同步技术进展、SOP 结论与验证回执；不发无关情绪化闲聊。"
        elif "model agent" in cf:
            personality_tag = "快节奏大模型极客吐槽社群"
            mbti_est = "ENTP (前沿敏感 · 短句高频)"
            psych_summary = "群内对新权重、新模型发布极度敏锐，交流节奏极快，偏好直白吐槽与一线实测结论。"
            comm_prefs = "短句口语即可，切勿发长篇 AI 八股。"
            emotional_baseline = "热闹高敏 · 极客幽默"
            boundaries = "默认只读旁观提取情报，非必要不主动打扰群友。"
        elif "苏文璐" in cf:
            personality_tag = "学术深耕 · 低噪高价值科研好友"
            mbti_est = "INTJ / INFJ (沉静专注 · 前沿导向)"
            psych_summary = "沟通极少但每条都围绕 ICLR / 世界模型等高价值科研动态。"
            comm_prefs = "严谨、简练、尊重隐私与时间窗口，用论文/数据说话。"
            emotional_baseline = "克制沉稳 · 科研同行默契"
            boundaries = "禁止高频定时闲聊与娱乐梗群发，保持高信噪比。"
        elif "文件传输" in cf:
            personality_tag = "号主个人第二大脑 & 资料中转库"
            mbti_est = "Self-Archive (个人知识备忘)"
            psych_summary = "沉淀 AI 工具箱、Personal Agent 云电脑配置对比等自用研究素材。"
            comm_prefs = "适合归档 Markdown 摘要、链接清单与每日巡检日报。"
            emotional_baseline = "纯私有工具节点"
            boundaries = "可随时无打扰写入测试归档与文章导出摘要。"
        elif "企业微信" in cf or "服务通知" in cf or "微信团队" in cf:
            personality_tag = "组织协同 / 官方安全通知通道"
            mbti_est = "System / Work-Formal"
            psych_summary = "承载工作工作室邀请（如安心的AI工作室）或官方安全登录提醒，代表号主真实社交/组织边界。"
            comm_prefs = "工作消息礼貌简要；官方系统通知仅做只读解析与记忆提取，禁止自动回复。"
            emotional_baseline = "正式客观"
            boundaries = "微信团队及系统通知严格只读。"
        else:
            personality_tag = str(analytics_entry.get("friendStyleTag") or f"{categories[0]}互动好友")
            mbti_est = "ISFJ / ENFJ (常规友好推断)"
            psych_summary = str(
                analytics_entry.get("styleSummary")
                or f"围绕「{'、'.join(categories[:2])}」开展交流，峰值活跃于 {peak_slot}。"
            )
            comm_prefs = f"对方风格为「{peer_metrics['toneTag']}」，建议匹配其句长（约 {peer_metrics['avgSentenceLength']} 字）自然回应。"
            emotional_baseline = "平和友好"
            boundaries = "遵循防打扰边界，重要约定交由号主确认。"

        memory_lines: List[str] = []
        for f in facts[:3]:
            memory_lines.append(f"[事实] {f['content']}")
        for sh in shared[:3]:
            memory_lines.append(f"[共同记忆] {sh['content']}")
        for ev in events[:3]:
            memory_lines.append(f"[事件({ev.get('timeMarker', '近期')})] {ev['content']}")
        memory_prompt_snippet = "\n".join(f"- {ln}" for ln in memory_lines) or "- 暂无深度历史记忆，保持友好自然并留意采集新事件。"

        return {
            "target": analytics_entry.get("target") or norm,
            "matchedTitle": title,
            "slug": analytics_entry.get("slug") or _slugify_target(title),
            "role": analytics_entry.get("role") or ("group" if "openbot" in cf else "friend"),
            "bound": bool(binding is not None or analytics_entry.get("bound")),
            "careLevel": care_level,
            "careLevelLabel": analytics_entry.get("careLevelLabel") or "普通会话",
            "warmthScore": warmth,
            "rapportScore": min(100, warmth + (8 if events else 0) + min(10, len(shared) * 2)),
            "personalityTag": personality_tag,
            "mbtiEstimate": mbti_est,
            "psychologicalSummary": psych_summary,
            "communicationPreferences": comm_prefs,
            "emotionalBaseline": emotional_baseline,
            "taboosAndBoundaries": boundaries,
            "coreTopics": categories,
            "peakTimeSlot": peak_slot,
            "peerSpeakingMetrics": peer_metrics,
            "selfSpeakingWithContact": self_metrics,
            "memories": {
                "facts": facts,
                "episodicEvents": events,
                "sharedContext": shared,
                "totalMemories": len(facts) + len(events) + len(shared),
            },
            "memoryPromptSnippet": memory_prompt_snippet,
        }

    @staticmethod
    def _synthesize_owner_profile(
        *,
        all_self_texts: List[str],
        all_time_markers: List[str],
        contact_profiles: List[Dict[str, Any]],
        all_facts: List[Dict[str, Any]],
        all_shared: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        speaking = _extract_speaking_metrics(all_self_texts)
        _, slot_dist = extract_time_markers(all_time_markers)
        sorted_slots = [k for k, _ in sorted(slot_dist.items(), key=lambda kv: kv[1], reverse=True)]
        peak_slots = sorted_slots[:3] or ["上午 09:00-11:59", "清晨 05:00-08:59", "晚间 18:00-21:59"]

        # Hints discovered from verified local logs
        wechat_id = "zhhao_1995"
        studio_name = "安心的AI工作室"
        for f in all_facts:
            c = str(f.get("content") or "")
            if "微信号账号标识：" in c:
                wechat_id = c.split("微信号账号标识：", 1)[1].strip()
            if "关联组织/工作室：" in c:
                studio_name = c.split("关联组织/工作室：", 1)[1].strip()

        role_matrix: List[Dict[str, Any]] = []
        for cp in contact_profiles:
            title = cp["matchedTitle"]
            cf = normalize_chat_name(title).casefold()
            quotes = [
                ev["content"].split("：", 1)[-1]
                for ev in (cp.get("memories", {}).get("episodicEvents") or [])
                if ev.get("direction") == "self"
            ]
            if "心安" in cf:
                role_mode = "轻松生活梗 & 共测挚友模式"
                adj = "句短松弛、接住视频号/生活书名梗，愿陪对方测新机器人和工具"
            elif "openbot" in cf:
                role_mode = "开源技术共建 & 项目测试主导者"
                adj = "干脆务实、聚焦 GitHub 项目（StaffDeck/OpenBot）、SOP 与自动化测试结论"
            elif "苏文璐" in cf:
                role_mode = "科研同行克制模式"
                adj = "低频高信噪比，专注论文/ICLR/世界模型探讨，不闲聊打扰"
            elif "企业微信" in cf or "服务通知" in cf:
                role_mode = "工作室协作商务模式"
                adj = "简明礼貌、确认组织成员邀请与协作安排"
            elif "文件传输" in cf:
                role_mode = "自我知识沉淀模式"
                adj = "直接丢链接与调研对比笔记，充当个人外挂记忆体"
            else:
                continue
            role_matrix.append({
                "contact": title,
                "roleMode": role_mode,
                "styleAdjustment": adj,
                "exampleQuote": quotes[0] if quotes else f"（结合历史话题「{'、'.join(cp.get('coreTopics') or ['日常'])}」自然互动）",
            })

        owner_memories = _dedupe_memory_items(
            [
                {
                    "id": "owner_fact_wxid",
                    "category": "fact",
                    "content": f"微信登录标识：{wechat_id}（来自微信团队安全通知实录）",
                    "source": "wechat_team_log",
                },
                {
                    "id": "owner_fact_studio",
                    "category": "fact",
                    "content": f"关联组织与团队：{studio_name}（与成员郝泽华等协同）",
                    "source": "wecom_invite_log",
                },
                {
                    "id": "owner_fact_openbot",
                    "category": "fact",
                    "content": "核心在研项目与兴趣：OpenBot / 微信非侵入 RPA 控制端 / Agent 工具链 / StaffDeck / AI 工具箱评测",
                    "source": "multi_chat_synthesis",
                },
                {
                    "id": "owner_fact_habit",
                    "category": "preference",
                    "content": "交互价值观：反感生硬官腔和脚本抢鼠标，强调丝滑体验、防打扰边界与先独立验证再交付",
                    "source": "behavioral_analysis",
                },
            ]
            + all_facts
            + [s for s in all_shared if any(k in s["content"] for k in ("OpenBot", "StaffDeck", "YoBot", "AI工具箱", "久病成医"))],
            limit=18,
        )

        traits = [
            "工程与系统思维强：关注 OpenBot、Agent、StaffDeck、RPA 与云电脑/工具箱实战评测",
            "高共情分寸感（见人下菜碟）：对「心安」轻松接梗测试，对「openbot」务实讨论方案，对科研好友保持低噪克制",
            "短句高频、不喜冗长套话：自己发消息偏简洁口语，追求交互丝滑、省心与安全边界",
            "注重记忆与资产沉淀：习惯把有价值的文章、工具链接沉淀到文件传输助手或知识库",
        ]

        digital_twin_prompt = (
            f"你正在以微信号主本人（微信号 {wechat_id} / {studio_name} 核心开发者）的「数字分身」口吻回复消息。\n"
            f"【本我性格特征】{'；'.join(traits[:3])}。\n"
            f"【说话风格】{speaking['toneTag']}；句长通常 {speaking['avgSentenceLength'] or 9.0} 字左右，"
            f"习惯「{speaking['punctuationHabits']}」，尽量像真人微信秒回一样自然简练，不要客服腔和 AI 味长段落。\n"
            f"【语态切换】对熟人带轻微幽默或口语助词，对技术/工作群直接给结论和关键项目细节。"
        )

        return {
            "ownerId": wechat_id,
            "displayName": f"号主本我 ({wechat_id})",
            "wechatIdHint": wechat_id,
            "organizationHint": studio_name,
            "mbtiEstimate": "ENTJ / INTJ (务实架构与极客推进型，对密友流露 ENTP 幽默感)",
            "archetypeTag": "极客工程派 × 讲分寸的温暖熟人",
            "personalityTraits": traits,
            "speakingStyle": {
                **speaking,
                "activePeakHours": peak_slots,
            },
            "roleSwitchingMatrix": role_matrix,
            "ownerMemories": owner_memories,
            "digitalTwinPersonaId": "owner-digital-twin",
            "digitalTwinSystemPrompt": digital_twin_prompt,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_profiles(
        self,
        *,
        target: Optional[str] = None,
        use_llm: bool = False,
        model_hub: Optional[Any] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze all local OCR histories, analytics, manual notes, and WeChatBridge archives."""
        store = self._load_store()
        histories = self._load_contact_histories()
        analytics = self.analytics_provider() if self.analytics_provider else {}
        bindings = self.bindings_provider() if self.bindings_provider else []

        manual_map: Dict[str, List[Dict[str, Any]]] = dict(store.get("manualMemories") or {})
        bridge_archives: List[Dict[str, Any]] = list(store.get("bridgeArchives") or [])

        # Organize analytics entries by normalized title
        analytics_by_key: Dict[str, Dict[str, Any]] = {}
        for p in analytics.get("profiles") or []:
            t = str(p.get("matchedTitle") or p.get("target") or "").strip()
            if t:
                analytics_by_key[normalize_chat_name(t).casefold()] = p

        # Organize bindings by normalized title
        def _find_binding(title: str) -> Optional[Dict[str, Any]]:
            for b in bindings:
                if _matches_target(str(b.get("target") or ""), title) or (
                    b.get("alias") and _matches_target(str(b["alias"]), title)
                ):
                    return b
            return None

        # Merge records from OCR histories + WeChatBridge ingested archives
        records_by_key: Dict[str, List[Dict[str, Any]]] = {}
        titles_by_key: Dict[str, str] = {}

        for key, hdata in histories.items():
            title = str(hdata.get("matchedTitle") or hdata.get("target") or key)
            titles_by_key[key] = title
            records_by_key[key] = list(hdata.get("records") or [])

        for arch in bridge_archives:
            ct = str(arch.get("contactName") or "").strip()
            if not ct:
                continue
            key = normalize_chat_name(ct).casefold()
            titles_by_key.setdefault(key, ct)
            records_by_key.setdefault(key, []).extend(list(arch.get("records") or []))

        for key, ap in analytics_by_key.items():
            titles_by_key.setdefault(key, str(ap.get("matchedTitle") or ap.get("target") or key))
            records_by_key.setdefault(key, [])

        # Gather global owner statistics + per-contact soul & memory profiles
        all_self_texts: List[str] = []
        all_time_markers: List[str] = []
        all_facts: List[Dict[str, Any]] = []
        all_shared: List[Dict[str, Any]] = []
        contact_profiles_list: List[Dict[str, Any]] = []

        for key, title in sorted(titles_by_key.items(), key=lambda kv: kv[1]):
            norm = normalize_chat_name(title)
            if norm.casefold() in FOLDER_CHAT_TITLES:
                continue
            records = records_by_key.get(key) or []
            ap = analytics_by_key.get(key) or {"target": norm, "matchedTitle": title, "sampleExcerpts": []}
            snippets = [str(s) for s in (ap.get("sampleExcerpts") or [])]

            for r in records:
                if r.get("kind") == "timestamp":
                    all_time_markers.append(str(r.get("text") or ""))
                elif r.get("kind") == "message":
                    if r.get("timeMarker"):
                        all_time_markers.append(str(r["timeMarker"]))
                    if r.get("direction") == "self":
                        txt = _clean_text(str(r.get("text") or ""))
                        if _is_meaningful_utterance(txt):
                            all_self_texts.append(txt)
            all_time_markers.extend(list(ap.get("activeTimeMarkers") or []))

            facts, events, shared = self._extract_facts_from_records(title, records, snippets)

            # Merge manual memories bound to this target
            for m_key, m_list in manual_map.items():
                if _matches_target(m_key, title) or _matches_target(m_key, norm):
                    for item in m_list:
                        cat = str(item.get("category") or "fact")
                        if cat == "event":
                            events.insert(0, item)
                        elif cat == "shared":
                            shared.insert(0, item)
                        else:
                            facts.insert(0, item)

            facts = _dedupe_memory_items(facts, limit=16)
            events = _dedupe_memory_items(events, limit=20)
            shared = _dedupe_memory_items(shared, limit=16)
            all_facts.extend(facts)
            all_shared.extend(shared)

            cp = self._synthesize_contact_soul(
                title,
                analytics_entry=ap,
                binding=_find_binding(title),
                records=records,
                facts=facts,
                events=events,
                shared=shared,
            )
            contact_profiles_list.append(cp)

        # Prioritize bound & special-care contacts first
        contact_profiles_list.sort(
            key=lambda c: (
                {"special_care": 0, "vip": 1, "normal": 2}.get(str(c.get("careLevel")), 2),
                not c.get("bound", False),
                -int(c.get("rapportScore") or 0),
                c.get("matchedTitle", ""),
            )
        )

        owner_profile = self._synthesize_owner_profile(
            all_self_texts=all_self_texts,
            all_time_markers=all_time_markers,
            contact_profiles=contact_profiles_list,
            all_facts=all_facts,
            all_shared=all_shared,
        )

        llm_synthesis: Optional[Dict[str, Any]] = None
        if use_llm and model_hub is not None and model_hub.is_llm_enabled():
            target_cp = None
            if target:
                target_cp = next(
                    (c for c in contact_profiles_list if _matches_target(target, c["matchedTitle"]) or _matches_target(target, c["target"])),
                    None,
                )
            sample_contacts = [target_cp] if target_cp else contact_profiles_list[:4]
            summary_input = {
                "ownerSpeaking": owner_profile["speakingStyle"],
                "ownerSelfQuotes": all_self_texts[:12],
                "contacts": [
                    {
                        "name": c["matchedTitle"],
                        "personalityTag": c["personalityTag"],
                        "memories": [m["content"] for m in (c["memories"]["facts"] + c["memories"]["sharedContext"])[:5]],
                    }
                    for c in sample_contacts
                    if c
                ],
            }
            prompt = (
                "请基于以下真实本地微信双向聊天统计与提取片段，用简练中文 JSON 补充两条洞察："
                "`ownerInsight`（微信账号主人的核心性格与聊天风格一句话总结，<=90字）和 "
                "`relationshipAdvice`（与上述核心好友下一步互动建议，<=90字）。\n"
                f"输入数据：{json.dumps(summary_input, ensure_ascii=False)}"
            )
            res = model_hub.generate_chat_reply(
                [
                    {"role": "system", "content": "你是谨慎的本地心理与社交记忆分析引擎，只基于输入事实作总结，返回纯 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                model_id=model_id,
                contact_name=target,
            )
            llm_synthesis = {
                "ok": bool(res.get("ok")),
                "modelId": res.get("modelId"),
                "providerId": res.get("providerId"),
                "latencyMs": res.get("latencyMs"),
                "rawText": res.get("replyText") or "",
                "error": res.get("error"),
            }
            if res.get("ok") and res.get("replyText"):
                owner_profile["llmDeepInsight"] = str(res["replyText"]).strip()[:400]

        contact_map = {c["slug"]: c for c in contact_profiles_list}
        store["ownerProfile"] = owner_profile
        store["contactProfiles"] = contact_map
        self._save_store(store)

        if self.persona_sync_cb is not None:
            self.persona_sync_cb(owner_profile)

        # Write Markdown report & synchronized JSON profiles snapshot
        report_md = self._format_markdown_report(owner_profile, contact_profiles_list)
        md_path = self.reports_dir / "soul_memory_report.md"
        md_path.write_text(report_md, encoding="utf-8")

        filtered_contacts = contact_profiles_list
        if target:
            filtered_contacts = [
                c for c in contact_profiles_list
                if _matches_target(target, c["matchedTitle"]) or _matches_target(target, c["target"])
            ]

        result_payload = {
            "ok": True,
            "schema": "openbot.wechat-soul-memories/1",
            "generatedAt": store["updatedAt"],
            "storePath": str(self.store_path),
            "reportMarkdownPath": str(md_path),
            "ownerProfile": owner_profile,
            "contactCount": len(filtered_contacts),
            "totalContactsAnalyzed": len(contact_profiles_list),
            "contactProfiles": filtered_contacts,
            "llmSynthesis": llm_synthesis,
        }
        profiles_json_path = self.reports_dir / "soul_memory_profiles.json"
        if target is None:
            profiles_json_path.write_text(
                json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif not profiles_json_path.exists():
            full_snapshot = dict(result_payload)
            full_snapshot["contactCount"] = len(contact_profiles_list)
            full_snapshot["contactProfiles"] = contact_profiles_list
            profiles_json_path.write_text(
                json.dumps(full_snapshot, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        result_payload["reportJsonPath"] = str(profiles_json_path)
        return result_payload

    def get_profiles(self, target: Optional[str] = None) -> Dict[str, Any]:
        store = self._load_store()
        if not store.get("ownerProfile"):
            return self.build_profiles(target=target)
        contacts = list((store.get("contactProfiles") or {}).values())
        contacts.sort(
            key=lambda c: (
                {"special_care": 0, "vip": 1, "normal": 2}.get(str(c.get("careLevel")), 2),
                not c.get("bound", False),
                -int(c.get("rapportScore") or 0),
                c.get("matchedTitle", ""),
            )
        )
        if target:
            contacts = [
                c for c in contacts
                if _matches_target(target, c.get("matchedTitle", "")) or _matches_target(target, c.get("target", ""))
            ]
        return {
            "ok": True,
            "generatedAt": store.get("updatedAt") or "",
            "storePath": str(self.store_path),
            "ownerProfile": store.get("ownerProfile") or {},
            "contactCount": len(contacts),
            "totalContactsAnalyzed": len(store.get("contactProfiles") or {}),
            "contactProfiles": contacts,
        }

    def get_contact_memory_context(self, target: str) -> Dict[str, Any]:
        """Return compact owner soul + target friend soul & memories for smart reply injection."""
        data = self.get_profiles()
        owner = data.get("ownerProfile") or {}
        matched_contact: Optional[Dict[str, Any]] = None
        for c in data.get("contactProfiles") or []:
            if _matches_target(target, c.get("matchedTitle", "")) or _matches_target(target, c.get("target", "")):
                matched_contact = c
                break
        if matched_contact is None:
            return {
                "ownerProfile": owner,
                "contactSoul": None,
                "memories": {"facts": [], "episodicEvents": [], "sharedContext": [], "totalMemories": 0},
                "memoryPromptSnippet": "",
                "memoryRefs": [],
            }
        mems = matched_contact.get("memories") or {}
        combined = (mems.get("facts") or [])[:3] + (mems.get("sharedContext") or [])[:3] + (mems.get("episodicEvents") or [])[:3]
        return {
            "ownerProfile": owner,
            "contactSoul": {
                "target": matched_contact.get("target"),
                "matchedTitle": matched_contact.get("matchedTitle"),
                "personalityTag": matched_contact.get("personalityTag"),
                "mbtiEstimate": matched_contact.get("mbtiEstimate"),
                "communicationPreferences": matched_contact.get("communicationPreferences"),
                "emotionalBaseline": matched_contact.get("emotionalBaseline"),
                "rapportScore": matched_contact.get("rapportScore"),
            },
            "memories": mems,
            "memoryPromptSnippet": matched_contact.get("memoryPromptSnippet") or "",
            "memoryRefs": [
                {"id": m["id"], "category": m.get("category", "fact"), "content": m["content"]}
                for m in combined
            ],
        }

    def add_memory_note(
        self,
        target: str,
        content: str,
        *,
        category: str = "fact",
        time_marker: str = "",
        source: str = "manual",
    ) -> Dict[str, Any]:
        clean_target = normalize_chat_name(target)
        clean_content = _clean_text(content)
        if not clean_target:
            raise ValueError("Target contact name cannot be empty.")
        if not clean_content:
            raise ValueError("Memory content cannot be empty.")
        norm_cat = (category or "fact").strip().lower()
        if norm_cat not in ("fact", "event", "shared", "preference"):
            norm_cat = "fact"

        store = self._load_store()
        manual_map: Dict[str, List[Dict[str, Any]]] = dict(store.get("manualMemories") or {})
        bucket = list(manual_map.get(clean_target) or [])
        item = {
            "id": _stable_id("mem", clean_target, norm_cat, clean_content),
            "category": norm_cat,
            "content": clean_content,
            "timeMarker": _clean_text(time_marker) or datetime.now().strftime("%Y-%m-%d %H:%M"),
            "direction": "manual",
            "source": source,
            "createdAt": _utc_iso_now(),
        }
        bucket.insert(0, item)
        manual_map[clean_target] = _dedupe_memory_items(bucket, limit=40)
        store["manualMemories"] = manual_map
        self._save_store(store)

        rebuilt = self.build_profiles(target=clean_target)
        return {
            "ok": True,
            "added": item,
            "target": clean_target,
            "profile": rebuilt["contactProfiles"][0] if rebuilt.get("contactProfiles") else None,
        }

    def ingest_bridge_archive(
        self,
        bundle: Any,
        *,
        contact_name: Optional[str] = None,
        owner_sender: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convert a WeChatBridge ChatArchiveBundle into bidirectional self/peer records & rebuild profiles."""
        owner_tokens = {a.casefold() for a in DEFAULT_OWNER_ALIASES}
        if owner_sender and owner_sender.strip():
            owner_tokens.add(_clean_text(owner_sender).casefold())

        raw_records = list(getattr(bundle, "records", None) or [])
        resolved_contact = _clean_text(contact_name or "") or _clean_text(getattr(bundle, "title", "") or "")
        senders = Counter(_clean_text(str(getattr(r, "sender", "") or "")) for r in raw_records)
        if not resolved_contact:
            for sender_name, _ in senders.most_common():
                if sender_name and sender_name.casefold() not in owner_tokens:
                    resolved_contact = sender_name
                    break
        if not resolved_contact:
            resolved_contact = "WeChatBridge导入好友"

        converted: List[Dict[str, Any]] = []
        self_n = 0
        peer_n = 0
        for rec in raw_records:
            sender = _clean_text(str(getattr(rec, "sender", "") or ""))
            content = _clean_text(str(getattr(rec, "content", "") or ""))
            ts = _clean_text(str(getattr(rec, "timestamp", "") or ""))
            if not content:
                continue
            is_self = bool(sender and (sender.casefold() in owner_tokens or (owner_sender and sender == owner_sender)))
            direction = "self" if is_self else "peer"
            if is_self:
                self_n += 1
            else:
                peer_n += 1
            converted.append({
                "text": content,
                "kind": "message",
                "direction": direction,
                "timeMarker": ts,
                "sender": sender or resolved_contact,
                "source": "wechat_bridge_archive",
            })

        store = self._load_store()
        archives = list(store.get("bridgeArchives") or [])
        records_digest = hashlib.sha1(
            json.dumps(converted, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        arch_id = _stable_id(
            "bridge",
            resolved_contact,
            str(len(converted)),
            str(getattr(bundle, "source_path", "")),
            records_digest,
        )
        archives = [a for a in archives if a.get("archiveId") != arch_id]
        archives.append({
            "archiveId": arch_id,
            "contactName": resolved_contact,
            "sourcePath": str(getattr(bundle, "source_path", "")),
            "importedAt": _utc_iso_now(),
            "selfCount": self_n,
            "peerCount": peer_n,
            "records": converted,
        })
        store["bridgeArchives"] = archives[-20:]
        self._save_store(store)

        rebuilt = self.build_profiles(target=resolved_contact)
        return {
            "ok": True,
            "archiveId": arch_id,
            "contactName": resolved_contact,
            "selfCount": self_n,
            "peerCount": peer_n,
            "totalRecords": len(converted),
            "ownerProfile": rebuilt.get("ownerProfile"),
            "contactProfile": rebuilt["contactProfiles"][0] if rebuilt.get("contactProfiles") else None,
        }

    @staticmethod
    def _format_markdown_report(owner: Dict[str, Any], contacts: List[Dict[str, Any]]) -> str:
        lines: List[str] = [
            "# WeChatBridge 本我性格画像 · 好友心智画像与长期记忆报告",
            "",
            f"- 号主标识: `{owner.get('displayName', '')}` | 关联组织: `{owner.get('organizationHint', '')}`",
            f"- 性格原型: **{owner.get('archetypeTag', '')}** (`{owner.get('mbtiEstimate', '')}`)",
            f"- 说话风格: {owner.get('speakingStyle', {}).get('toneTag', '')}（均值 `{owner.get('speakingStyle', {}).get('avgSentenceLength', 0)}` 字）",
            "",
            "## 一、微信号主人「本我画像」与跨好友语态切换",
            "",
        ]
        for tr in owner.get("personalityTraits") or []:
            lines.append(f"- {tr}")
        lines.append("")
        for rm in owner.get("roleSwitchingMatrix") or []:
            lines.append(f"- 对 **{rm['contact']}** (`{rm['roleMode']}`): {rm['styleAdjustment']} | 示例: `{rm['exampleQuote']}`")

        lines.extend(["", "## 二、号主关键个人记忆", ""])
        for om in (owner.get("ownerMemories") or [])[:10]:
            lines.append(f"- `{om.get('category', 'fact')}` {om.get('content', '')}")

        lines.extend(["", "## 三、好友心智画像与长期记忆", ""])
        for c in contacts:
            mems = c.get("memories") or {}
            lines.append(f"### {c['matchedTitle']} (`{c.get('careLevelLabel', '普通')}` · 默契分 **{c.get('rapportScore', 0)}**)")
            lines.append(f"- **性格原型**: {c.get('personalityTag', '')} (`{c.get('mbtiEstimate', '')}`)")
            lines.append(f"- **心理摘要**: {c.get('psychologicalSummary', '')}")
            lines.append(f"- **沟通偏好**: {c.get('communicationPreferences', '')}")
            lines.append(f"- **记忆条目数**: {mems.get('totalMemories', 0)}（事实 {len(mems.get('facts') or [])} / 事件 {len(mems.get('episodicEvents') or [])} / 共同话题 {len(mems.get('sharedContext') or [])}）")
            for item in (mems.get("facts") or [])[:3] + (mems.get("sharedContext") or [])[:3] + (mems.get("episodicEvents") or [])[:4]:
                lines.append(f"  - [{item.get('category', 'mem')}] {item.get('content', '')}")
            lines.append("")
        return "\n".join(lines)
