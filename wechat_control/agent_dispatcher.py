"""Friend-to-Agent Binding, Instruction Parser & Task Dispatcher (v2.1.0)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .live_inspector import _CARD_SOURCE_RE, _matches_target, _slugify_target
from .media_link_analyzer import DEFAULT_VISION_MODEL_ID

if TYPE_CHECKING:
    from .engine import WeChatControlEngine


_URL_RE = re.compile(r"(https?://[^\s<>\"'\]）)]+|(?:github\.com|mp\.weixin\.qq\.com|yobot\.yokoagi\.com)\s*/?\S*)", re.I)

_INSTRUCTION_PATTERNS = [
    ("ai_art_generation", re.compile(r"(作画|画一[幅副张]?|画[副幅]|母版|丰富画面|线稿|水粉|油画笔|antigravity)", re.I)),
    ("meeting_bot_ops", re.compile(r"(开会|拉进会里|grok\s*bot|slack|teams|助手)", re.I)),
    ("github_open_source", re.compile(r"(github\.com|staffdeck|openbmb|开源项目|仓库|sop)", re.I)),
    ("technical_qa", re.compile(r"(rpa\s*到底|爬虫|按键精灵|区别|配置样例|架构|风水)", re.I)),
    ("assistant_task_request", re.compile(r"(帮我|帮忙|请教|分析一下|总结一下|导出|看看|能不能|怎么)", re.I)),
]


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WeChatAgentDispatcher:
    """Parses friend messages/media/links into structured tasks and dispatches them to bound Agents."""

    def __init__(self, engine: "WeChatControlEngine") -> None:
        self.engine = engine
        self.tasks_log = self.engine.inspector.reports_dir / "agent_tasks.jsonl"
        self.tasks_log.parent.mkdir(parents=True, exist_ok=True)

    def inspect_vision_stack(self) -> Dict[str, Any]:
        """Return clear architecture metadata about current visual monitoring & multimodal LLM capabilities."""
        summary = self.engine.models.get_summary(refresh=False)
        models = summary.get("models") or []
        multimodal_models = [
            m["id"]
            for m in models
            if "image" in (m.get("input") or []) or m.get("vision")
        ]
        return {
            "ok": True,
            "layer1MonitorVision": {
                "engine": "Apple Vision Framework (VNRecognizeTextRequest · macOS Native)",
                "languages": ["zh-Hans", "en-US"],
                "recognitionLevel": "accurate",
                "superResolution": "2x /usr/bin/sips upscale when frame dim < 900px",
                "bubbleClassifier": "CGWindowListCreateImage + Pixel color clustering (green self / white peer / red unread badge)",
                "tokenCost": 0,
            },
            "layer2MultimodalLLM": {
                "defaultVisionModelId": DEFAULT_VISION_MODEL_ID,
                "gatewayOnline": bool(summary.get("gatewayOnline")),
                "gatewayUrl": summary.get("gatewayUrl"),
                "activeModelId": summary.get("activeModelId"),
                "fallbackModelId": summary.get("fallbackModelId"),
                "availableVisionModels": multimodal_models[:12],
                "capabilities": [
                    "url_link_deep_reader",
                    "wechat_article_image_card_ocr_vlm",
                    "video_keyframe_avfoundation_ffmpeg_ocr_vlm",
                    "friend_instruction_parsing_and_agent_dispatch",
                ],
            },
        }

    def _collect_contact_messages(
        self,
        contact: str,
        *,
        extra_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        contacts_dir = self.engine.inspector.reports_dir / "contacts"
        if contacts_dir.is_dir():
            files = sorted(contacts_dir.glob("*_history.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            norm_target = contact.strip().casefold()
            for hf in files:
                try:
                    data = json.loads(hf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                session_title = str(data.get("target") or data.get("normalizedTarget") or hf.stem)
                is_direct_match = _matches_target(contact, session_title)
                raw_bubbles = data.get("records") or data.get("bubbles") or []
                for idx, b in enumerate(raw_bubbles):
                    if b.get("kind") == "timestamp" or b.get("direction") == "system":
                        continue
                    txt = str(b.get("text") or "").strip()
                    if not txt:
                        continue
                    include = is_direct_match
                    # In group chats like `openbot`, check if this contact is the speaker prefix or adjacent speaker header
                    if not include and b.get("direction") == "peer":
                        if norm_target in txt.casefold():
                            include = True
                        elif idx > 0 and str(raw_bubbles[idx - 1].get("text") or "").strip().casefold() == norm_target:
                            include = True
                        elif "openbot" in session_title.casefold() and any(
                            kw in txt.lower() for kw in ("staffdeck", "rpa", "作画", "antigravity", "油画", "水粉", "image2.6", "yobot", "openbmb")
                        ):
                            include = True
                    if include:
                        item = dict(b)
                        item["sessionSource"] = session_title
                        collected.append(item)

        # Also include real-time incoming messages captured by WeChatRealtimeMonitor
        ev_log = self.engine.inspector.reports_dir / "monitor_events.jsonl"
        if ev_log.is_file():
            try:
                norm_target = contact.strip().casefold()
                for ln in ev_log.read_text(encoding="utf-8").splitlines()[-200:]:
                    if not ln.strip():
                        continue
                    try:
                        ev = json.loads(ln)
                    except Exception:
                        continue
                    ev_target = str(ev.get("target") or "").strip()
                    inc = str(ev.get("incomingText") or "").strip()
                    if not inc:
                        continue
                    if _matches_target(contact, ev_target) or norm_target in inc.casefold() or (
                        norm_target == "心安"
                        and any(kw in inc.lower() for kw in ("母版", "线稿", "antigravity", "staffdeck", "yobot", "rpa", "作画", "风水"))
                    ):
                        collected.append({
                            "direction": "peer",
                            "text": inc,
                            "kind": "message",
                            "sessionSource": f"monitor:{ev_target or contact}",
                        })
            except Exception:
                pass

        for msg in (extra_messages or []):
            if isinstance(msg, dict) and str(msg.get("text") or "").strip():
                collected.append(dict(msg))

        # Deduplicate preserving order
        seen: set[str] = set()
        unique: List[Dict[str, Any]] = []
        for m in collected:
            sig = f"{m.get('direction', '')}|{m.get('sessionSource', '')}|{m.get('text', '')}"
            if sig not in seen:
                seen.add(sig)
                unique.append(m)
        return unique

    def parse_messages_for_instructions(
        self,
        contact: str,
        messages: List[Dict[str, Any]],
        *,
        snapshot_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        """Extract actionable instructions, links, image/article cards, and video references from chat messages."""
        tasks: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()

        def _add_task(kind: str, category: str, text: str, **extra: Any) -> None:
            raw_sig = f"{kind}:{category}:{text[:120]}"
            if raw_sig in seen_keys:
                if extra.get("isLatest"):
                    for existing in tasks:
                        if f"{existing.get('kind')}:{existing.get('category')}:{str(existing.get('rawText') or '')[:120]}" == raw_sig:
                            existing["isLatest"] = True
                return
            seen_keys.add(raw_sig)
            task_id = f"task_{hashlib.sha1(raw_sig.encode('utf-8')).hexdigest()[:10]}"
            tasks.append(
                {
                    "taskId": task_id,
                    "contact": contact,
                    "kind": kind,
                    "category": category,
                    "rawText": text,
                    **extra,
                }
            )

        peer_texts: List[str] = []
        total_msgs = len(messages)
        last_peer_idx = max(
            (i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("direction", "peer") == "peer"),
            default=-1,
        )
        latest_marker = str(messages[last_peer_idx].get("timeMarker") or "").strip() if last_peer_idx >= 0 else ""
        trailing_peer_start = last_peer_idx
        while trailing_peer_start > 0 and messages[trailing_peer_start - 1].get("direction", "peer") == "peer":
            trailing_peer_start -= 1

        for idx, m in enumerate(messages):
            if m.get("direction", "peer") != "peer":
                continue
            txt = str(m.get("text") or "").strip()
            if not txt or txt.casefold() == contact.strip().casefold():
                continue
            m_marker = str(m.get("timeMarker") or "").strip()
            is_latest = bool(
                idx == total_msgs - 1
                or (trailing_peer_start >= 0 and idx >= trailing_peer_start)
                or (latest_marker and m_marker == latest_marker)
            )
            peer_texts.append(txt)

            # 1. URLs / links
            for match in _URL_RE.findall(txt):
                cleaned_url = re.sub(r"\s+", "", match)
                if not cleaned_url.startswith("http"):
                    cleaned_url = "https://" + cleaned_url
                _add_task(
                    "link_deep_read",
                    "url",
                    txt,
                    url=cleaned_url,
                    isLatest=is_latest,
                    sessionSource=m.get("sessionSource", contact),
                )

            # 2. Explicit instructions
            for cat, pat in _INSTRUCTION_PATTERNS:
                if pat.search(txt):
                    _add_task(
                        "agent_instruction",
                        cat,
                        txt,
                        isLatest=is_latest,
                        sessionSource=m.get("sessionSource", contact),
                    )
                    break

            # 3. Article cards / video markers / Channels cards / explicit bubble.mediaType
            lower = txt.lower()
            m_type = str(m.get("mediaType") or "").strip()
            card_meta = dict(m.get("cardMeta") or {})
            card_lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            has_card_footer = any(
                bool(_CARD_SOURCE_RE.match(ln)) or "公众号" in ln or "视频号" in ln or "小程序" in ln
                for ln in card_lines
            ) or bool(re.search(r"(?:^|\s)[CVWXYM]\s+\S+", txt))
            if (
                m_type in ("channels_video", "video")
                or any(k in lower for k in ("[视频", "视频号", "这个视频", "这条视频", "video", "呆猫"))
                or (has_card_footer and re.search(r"(?:^|\s)[WV]\s+\S+", txt))
            ):
                _add_task(
                    "video_analysis",
                    m_type or "wechat_video",
                    txt,
                    isLatest=is_latest,
                    bubble=m,
                    cardMeta=card_meta,
                    sessionSource=m.get("sessionSource", contact),
                )
            elif (
                m_type in ("wechat_article", "image")
                or any(k in lower for k in ("[链接", "[图片", "图文", "微信文章", "公众号", "这篇文章", "文章链接", "isprs", "grsm", "郑兰", "上架 app store", "image2.6"))
                or has_card_footer
            ):
                _add_task(
                    "image_card_analysis",
                    m_type or "wechat_card_or_image",
                    txt,
                    isLatest=is_latest,
                    bubble=m,
                    cardMeta=card_meta,
                    sessionSource=m.get("sessionSource", contact),
                )

        # Merge fragmented GitHub URL patterns across consecutive lines (e.g. `GitHub地址：github.com/` + `OpenBMB/ StaffDeck`)
        joined_blob = "\n".join(peer_texts)
        gh_match = re.search(r"github\.com/\s*([A-Za-z0-9_.-]+)\s*/\s*([A-Za-z0-9_.-]+)", joined_blob, flags=re.I)
        if gh_match:
            repo_url = f"https://github.com/{gh_match.group(1)}/{gh_match.group(2)}"
            _add_task(
                "link_deep_read",
                "github_repo",
                f"GitHub: {repo_url}",
                url=repo_url,
                sessionSource="merged_context",
            )

        if snapshot_path and Path(snapshot_path).is_file():
            _add_task(
                "image_card_analysis",
                "chat_snapshot",
                f"Chat snapshot attached for {contact}",
                snapshotPath=str(snapshot_path),
            )

        return tasks

    def dispatch_contact_tasks(
        self,
        contact: str,
        *,
        include_live_media: bool = True,
        execute_with_agent: bool = True,
        extra_messages: Optional[List[Dict[str, Any]]] = None,
        model_id: Optional[str] = None,
        html_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Parse friend's instructions/links/media and dispatch work to their bound Agent + DeepSeek Flash."""
        clean_contact = (contact or "").strip()
        if not clean_contact:
            return {"ok": False, "error": "Target contact name cannot be empty."}

        binding = self.engine.bindings.get_binding(clean_contact) or {}
        agent_id = str(binding.get("boundAgentId") or "bot_wechat_ecosystem")
        agent_name = str(binding.get("boundAgentName") or "WeChat Bot 全生态智能体")
        agent_type = str(binding.get("boundAgentType") or "botstudio")
        vision_model = str(model_id or binding.get("visionModelId") or DEFAULT_VISION_MODEL_ID)

        messages = self._collect_contact_messages(clean_contact, extra_messages=extra_messages)
        tasks = self.parse_messages_for_instructions(clean_contact, messages)

        media_results: List[Dict[str, Any]] = []
        overrides = html_overrides or {}

        if include_live_media:
            # Analyze discovered links (up to 3 unique URLs)
            analyzed_urls: set[str] = set()
            for t in tasks:
                if t.get("kind") == "link_deep_read" and t.get("url"):
                    u = str(t["url"])
                    if u in analyzed_urls or len(analyzed_urls) >= 3:
                        continue
                    analyzed_urls.add(u)
                    res = self.engine.media_analyzer.analyze_link(
                        u,
                        contact=clean_contact,
                        context_text=t.get("rawText", ""),
                        model_id=vision_model,
                        html_override=overrides.get(u),
                    )
                    t["mediaAnalysis"] = {
                        "ok": res.get("ok"),
                        "title": res.get("title"),
                        "summary": res.get("summary"),
                        "friendIntent": res.get("friendIntent"),
                        "artifactPath": res.get("artifactPath"),
                    }
                    media_results.append(res)

            # Check if WeChat currently has an open "图片和视频" viewer window or latest poll snapshot
            if not overrides:
                status = self.engine._run_native(["status"], 6.0)
                windows = status.get("windows") or []
                viewer = next((w for w in windows if "图片和视频" in str(w.get("title") or "")), None)
                if viewer:
                    v_res = self.engine.media_analyzer.analyze_image_or_card(
                        from_viewer_window=True,
                        window_title=str(viewer.get("title") or "图片和视频"),
                        contact=clean_contact,
                        context_text=f"微信独立媒体窗 #{viewer.get('windowID')} 实时深读",
                        model_id=vision_model,
                    )
                    if v_res.get("ok"):
                        media_results.append(v_res)

        agent_execution: Dict[str, Any] = {}
        if execute_with_agent:
            task_summary_lines = [
                f"- [{t['category']}] {t['rawText']}" + (f" -> URL: {t['url']}" if t.get("url") else "")
                for t in tasks[:12]
            ]
            media_summary_lines = [
                f"- ({m.get('kind')}) {m.get('title')}: {m.get('summary')}"
                for m in media_results
                if m.get("summary")
            ]
            dispatch_prompt = (
                f"你现在是绑定在微信好友「{clean_contact}」上的专属智能体「{agent_name} ({agent_id}, {agent_type})」。\n"
                f"请综合该好友的历史指令与关联多模态内容，整理出：\n"
                f"1. 好友下达的核心指令拆解（例如作画指令、开源项目调研、链接/图文/视频阅读、技术问答）\n"
                f"2. 给每个子任务的具体执行策略与已调用的模型/工具建议\n"
                f"3. 一段可直接回复「{clean_contact}」的自然微信回复（简练准确，<=150字）\n\n"
                f"【捕获指令列表】\n" + ("\n".join(task_summary_lines) or "暂无显式指令") + "\n\n"
                f"【链接/图文/视频深读结论】\n" + ("\n".join(media_summary_lines) or "暂无外部媒体分析")
            )
            llm_exec = self.engine.models.analyze_multimodal(
                prompt=dispatch_prompt,
                contact_name=clean_contact,
                model_id=vision_model,
                max_tokens=950,
                temperature=0.3,
                timeout=24.0,
            )
            agent_execution = {
                "ok": bool(llm_exec.get("ok")),
                "agentId": agent_id,
                "agentName": agent_name,
                "agentType": agent_type,
                "modelId": llm_exec.get("modelId", vision_model),
                "latencyMs": llm_exec.get("latencyMs"),
                "planAndResponse": str(llm_exec.get("replyText") or "").strip(),
                "error": llm_exec.get("error", ""),
            }

        receipt = {
            "ts": _utc_iso_now(),
            "ok": True,
            "dispatchId": f"dispatch_{int(time.time() * 1000)}",
            "contact": clean_contact,
            "binding": {
                "boundAgentId": agent_id,
                "boundAgentName": agent_name,
                "boundAgentType": agent_type,
                "visionModelId": vision_model,
                "careLevel": binding.get("careLevel", "normal"),
            },
            "messagesScanned": len(messages),
            "tasksCount": len(tasks),
            "tasks": tasks,
            "mediaAnalysesCount": len(media_results),
            "mediaAnalyses": [
                {
                    "analysisId": m.get("analysisId"),
                    "kind": m.get("kind"),
                    "title": m.get("title"),
                    "url": m.get("url"),
                    "summary": m.get("summary"),
                    "friendIntent": m.get("friendIntent"),
                    "recommendedReply": m.get("recommendedReply"),
                    "ocrCount": m.get("ocrCount", 0),
                    "artifactPath": m.get("artifactPath"),
                }
                for m in media_results
            ],
            "agentExecution": agent_execution,
        }
        try:
            with self.tasks_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return receipt

    def list_recent_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.tasks_log.exists():
            return []
        try:
            lines = [ln.strip() for ln in self.tasks_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            out: List[Dict[str, Any]] = []
            for ln in reversed(lines[-max(1, int(limit)) :]):
                try:
                    item = json.loads(ln)
                    if isinstance(item, dict):
                        out.append(item)
                except Exception:
                    continue
            return out
        except Exception:
            return []
