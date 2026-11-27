#!/usr/bin/env python3
"""Capture 10 high-DPI annotated user-guide screenshots from an isolated demo WeChatBot instance.

Strict privacy isolation:
- Uses an ephemeral `tempfile.TemporaryDirectory()` for all config, SQLite stores, logs,
  reports, snapshots, avatars, archives, and Chrome user-data-dir.
- Never reads `/Users/mac/Library/Application Support/WeChatBot`, real user Downloads/Desktop,
  or live WeChat windows.
- Binds `create_http_server(engine, host="127.0.0.1", port=0)` so no `console.pid` is written
  to Application Support.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "docs" / "assets" / "user-guide"
CHROME_BIN = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
NODE_BIN = Path("/Users/mac/.local/bin/node")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Pure-Python PNG Avatar Generator (zero external dependencies)
# ---------------------------------------------------------------------------

def _make_png_rgba(width: int, height: int, pixels: bytearray) -> bytes:
    """Encode an RGBA pixel buffer into a valid PNG file."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start : start + stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _write_demo_avatar(path: Path, rgb: Tuple[int, int, int], accent: Tuple[int, int, int]) -> None:
    """Create a clean 64x64 rounded-square gradient avatar PNG for demo contacts."""
    w = h = 64
    buf = bytearray(w * h * 4)
    r1, g1, b1 = rgb
    r2, g2, b2 = accent
    radius = 16.0
    for y in range(h):
        for x in range(w):
            # Rounded corner alpha
            dx = max(0.0, radius - x, x - (w - 1 - radius))
            dy = max(0.0, radius - y, y - (h - 1 - radius))
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > radius + 0.5:
                alpha = 0
            elif dist > radius - 0.5:
                alpha = int(255 * (radius + 0.5 - dist))
            else:
                alpha = 255
            t = (x + y) / float(w + h - 2)
            r = int(r1 * (1 - t) + r2 * t)
            g = int(g1 * (1 - t) + g2 * t)
            b = int(b1 * (1 - t) + b2 * t)
            # Subtle white monogram silhouette (head + shoulders)
            cx = x - 31.5
            cy_head = y - 24.0
            in_head = (cx * cx + cy_head * cy_head) <= 9.5 * 9.5
            in_body = ((cx / 18.0) ** 2 + ((y - 52.0) / 15.0) ** 2) <= 1.0 and y >= 37
            if in_head or in_body:
                r = int(r * 0.25 + 255 * 0.75)
                g = int(g * 0.25 + 255 * 0.75)
                b = int(b * 0.25 + 255 * 0.75)
            idx = (y * w + x) * 4
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
            buf[idx + 3] = alpha
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_make_png_rgba(w, h, buf))


# ---------------------------------------------------------------------------
# Isolated Demo Data & Engine Setup
# ---------------------------------------------------------------------------

def _iso_offset(minutes_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.isoformat(timespec="seconds")


def _hm_offset(minutes_ago: int) -> str:
    dt = datetime.now() - timedelta(minutes=minutes_ago)
    return dt.strftime("%H:%M")


def _seed_demo_histories_and_reports(reports_dir: Path, avatars_dir: Path, archives_dir: Path) -> None:
    """Write strictly fictional demo conversations, management report, avatars, and local archive."""
    contacts_dir = reports_dir / "contacts"
    contacts_dir.mkdir(parents=True, exist_ok=True)
    archives_dir.mkdir(parents=True, exist_ok=True)

    # Conversations crafted so self-training extracts domain vocabulary + risk-flagged quote/deadline drafts
    demo_threads: List[Dict[str, Any]] = [
        {
            "target": "张总（新房衣柜定制）",
            "slug": "zhang_zong_wardrobe",
            "avatar_colors": ((24, 119, 86), (16, 185, 129)),
            "records": [
                {"direction": "peer", "text": "你好，新房准备做全屋衣柜定制，你们用的是什么环保板材？", "mins": 180},
                {"direction": "self", "text": "张总您好！我们主推ENF级实木多层板，环保等级达到国标最高ENF级，防潮承重都很稳，而且提供免费上门量尺出3D效果图，您可以先看看方案。", "mins": 176},
                {"direction": "peer", "text": "ENF级实木多层板挺好，那衣柜大概怎么收费？有优惠吗？", "mins": 170},
                {"direction": "self", "text": "我们采用投影面积计价，标准主卧衣柜目前活动价1280元/平米，老带新或全屋满配还可申请打9折，具体我先安排免费上门量尺后给您出明细清单。", "mins": 165},
                {"direction": "peer", "text": "好的，工期大概多久？能赶在月底前装好吗？", "mins": 158},
                {"direction": "self", "text": "没问题张总，确认图纸下单后保证15天内交付安装完成，我们支持免费上门量尺和售后质保，方便发下小区位置我给您约设计师。", "mins": 152},
                {"direction": "peer", "text": "太好了，这周末下午可以约免费上门量尺，大概投影面积怎么算？", "mins": 18},
            ],
        },
        {
            "target": "林女士（老客复购）",
            "slug": "lin_nvshi_repurchase",
            "avatar_colors": ((37, 99, 235), (56, 189, 248)),
            "records": [
                {"direction": "peer", "text": "陈经理你好，前年找你们做的衣柜很好用，现在书房想再加一组书柜，还是用ENF级实木多层板吗？", "mins": 260},
                {"direction": "self", "text": "林女士好！感谢老客复购支持，书柜依然推荐ENF级实木多层板，同色系封边不翘边，同样支持免费上门量尺和投影面积计价。", "mins": 255},
                {"direction": "peer", "text": "上次投影面积计价很透明没有增项，这次大概多少钱一平？", "mins": 248},
                {"direction": "self", "text": "老客复购价按投影面积计价1180元/平米，含五金缓冲铰链，下周可安排设计师免费上门量尺复核。", "mins": 242},
                {"direction": "peer", "text": "行，那就帮我预约周四上午吧，大概多久能送到安装？", "mins": 42},
            ],
        },
        {
            "target": "王经理（精装房批量咨询）",
            "slug": "wang_jingli_bulk",
            "avatar_colors": ((217, 119, 6), (245, 158, 11)),
            "records": [
                {"direction": "peer", "text": "我们这边有12套样板间需要衣柜和玄关柜，批量定制按投影面积计价还是展开面积？", "mins": 340},
                {"direction": "self", "text": "王经理您好，批量项目默认按投影面积计价更直观好核算，板材统一配ENF级实木多层板并提供第三方环保检测报告。", "mins": 335},
                {"direction": "peer", "text": "批量下单周期和价格能给什么政策？", "mins": 328},
                {"direction": "self", "text": "10套以上批量可享工程底价1080元/平米，签订合同后保证20天内交付到场，全程专人跟进免费上门量尺和安装验收。", "mins": 320},
                {"direction": "peer", "text": "收到，先把ENF级实木多层板色卡和投影面积计价标准发我看看，下周安排对接。", "mins": 85},
            ],
        },
        {
            "target": "测试小号",
            "slug": "test_friend_demo",
            "avatar_colors": ((124, 58, 237), (167, 139, 250)),
            "records": [
                {"direction": "peer", "text": "你们全屋定制衣柜最低多少钱一平米？直接报个底价", "mins": 32},
                {"direction": "self", "text": "我们主推ENF级实木多层板，按投影面积计价透明无增项，先请问您家里大概多少平米、重点做衣柜还是全屋呢？", "mins": 30},
                {"direction": "peer", "text": "三室两厅大概110平米，主要做主卧衣柜和儿童房书桌柜", "mins": 9},
            ],
        },
    ]

    sessions_payload: List[Dict[str, Any]] = []
    for idx, thread in enumerate(demo_threads):
        target = thread["target"]
        slug = thread["slug"]
        _write_demo_avatar(avatars_dir / f"{target}.png", *thread["avatar_colors"])

        records = []
        for rec in thread["records"]:
            records.append(
                {
                    "text": rec["text"],
                    "kind": "message",
                    "direction": rec["direction"],
                    "timeMarker": _hm_offset(rec["mins"]),
                    "ts": _iso_offset(rec["mins"]),
                    "source": "hosting" if rec["direction"] == "self" else "peer",
                }
            )
        hp = contacts_dir / f"{slug}_history.json"
        hp.write_text(
            json.dumps(
                {
                    "ok": True,
                    "target": target,
                    "matchedTitle": target,
                    "slug": slug,
                    "observedAt": _iso_offset(5),
                    "recordCount": len(records),
                    "records": records,
                    "historyPath": str(hp),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        visible_msgs = [r["text"] for r in records[-4:]]
        sessions_payload.append(
            {
                "index": idx,
                "fullTitle": target,
                "listTitleSnippet": target,
                "unreadCount": 1 if idx == 0 else 0,
                "visibleMessages": visible_msgs,
            }
        )

    (reports_dir / "wechat_management_report.json").write_text(
        json.dumps(
            {
                "ok": True,
                "generatedAt": _iso_offset(3),
                "sessionCount": len(sessions_payload),
                "sessions": sessions_payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Local chat export sample in isolated temp archive folder (never real Downloads/Desktop)
    archive_txt = archives_dir / "星河定制家居_客户咨询聊天记录.txt"
    archive_txt.write_text(
        "\n".join(
            [
                "周先生 2026-11-26 10:12:00",
                "你好，想了解一下全屋环保实木定制怎么收费？",
                "",
                "陈经理 2026-11-26 10:13:15",
                "周先生您好，我们采用投影面积计价，主材是ENF级实木多层板，免费上门量尺后出明细报价",
                "",
                "周先生 2026-11-26 10:15:40",
                "行，那你们免费上门量尺需要预约多久？",
                "",
                "陈经理 2026-11-26 10:16:10",
                "提前1天预约即可，设计师带ENF级实木多层板小样免费上门量尺",
            ]
        ),
        encoding="utf-8",
    )


def _create_isolated_engine(tmp_root: Path) -> Tuple[Any, Dict[str, Any]]:
    """Build a strictly isolated WeChatControlEngine inside `tmp_root` with mocked native/FS hooks."""
    cfg_dir = tmp_root / "config"
    logs_dir = tmp_root / "logs"
    reports_dir = logs_dir
    snapshots_dir = logs_dir / "snapshots"
    avatars_dir = logs_dir / "avatars"
    archives_dir = tmp_root / "demo_archives"
    for d in (cfg_dir, logs_dir, snapshots_dir, avatars_dir, archives_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Set env vars defensively BEFORE importing/constructing engine
    os.environ["WECHAT_PLUGIN_AUDIT_LOG"] = str(logs_dir / "audit.jsonl")
    os.environ["WECHAT_PLUGIN_AUTH_FILE"] = str(cfg_dir / "studio_auth.json")
    os.environ["WECHAT_PLUGIN_BINDINGS_FILE"] = str(cfg_dir / "bound_contacts.json")
    os.environ["WECHAT_PLUGIN_MODELS_CONFIG"] = str(cfg_dir / "model_providers.json")
    os.environ["WECHAT_PLUGIN_KB_DB"] = str(cfg_dir / "wechat_knowledge.sqlite")
    os.environ["WECHAT_PLUGIN_PERSONAS_FILE"] = str(cfg_dir / "personas.json")
    os.environ["WECHAT_PLUGIN_SOUL_FILE"] = str(cfg_dir / "soul_memories.json")
    os.environ["WECHAT_PLUGIN_MONITOR_STATE"] = str(logs_dir / "monitor_state.json")
    os.environ["WECHAT_PLUGIN_MONITOR_EVENTS"] = str(logs_dir / "monitor_events.jsonl")
    os.environ["WECHAT_PLUGIN_ARTICLE_EXPORTS"] = str(tmp_root / "exports" / "articles")

    from wechat_control.engine import WeChatControlEngine

    _seed_demo_histories_and_reports(reports_dir, avatars_dir, archives_dir)

    engine = WeChatControlEngine(
        audit_log_path=logs_dir / "audit.jsonl",
        auth_file_path=cfg_dir / "studio_auth.json",
        bindings_file_path=cfg_dir / "bound_contacts.json",
        models_config_path=cfg_dir / "model_providers.json",
        knowledge_db_path=cfg_dir / "wechat_knowledge.sqlite",
        personas_file_path=cfg_dir / "personas.json",
        monitor_state_path=logs_dir / "monitor_state.json",
        monitor_events_path=logs_dir / "monitor_events.jsonl",
        snapshots_dir=snapshots_dir,
        reports_dir=reports_dir,
        bundle_root=REPO_ROOT,
    )
    # Never scan repo root logs/ or real Downloads/Desktop
    engine.plugin_root = tmp_root
    engine.auth_gate.grant(["*"], authorized_by="demo-guide-capture", note="isolated demo capture")

    # Toggleable state controlled by screenshot phases
    demo_state: Dict[str, Any] = {
        "permissions_granted": False,
        "hosting_active": False,
        "hosting_targets": ["张总（新房衣柜定制）", "林女士（老客复购）", "王经理（精装房批量咨询）"],
        "hosting_started_at": _iso_offset(25),
    }

    def _mock_run_native(args: List[str], timeout: float = 20.0) -> Dict[str, Any]:
        cmd = args[0] if args else ""
        if cmd == "status":
            granted = bool(demo_state["permissions_granted"])
            return {
                "ok": True,
                "accessibilityTrusted": granted,
                "postEventTrusted": granted,
                "screenCaptureTrusted": granted,
                "wechatRunning": True,
                "wechatPid": 88102,
                "windowCount": 1,
            }
        if cmd == "hid-idle":
            return {"ok": True, "idleSeconds": 180.0}
        if cmd == "dock-to-wechat":
            return {"ok": True, "docked": True, "mode": "verify"}
        if cmd in ("list-windows", "app-windows"):
            return {"ok": True, "windows": []}
        return {"ok": True}

    engine._run_native = _mock_run_native  # type: ignore[method-assign]
    engine.inspector.list_sessions = lambda: json.loads(  # type: ignore[method-assign]
        (reports_dir / "wechat_management_report.json").read_text(encoding="utf-8")
    ).get("sessions", [])
    engine.inspector.list_popout_windows = lambda app="all": []  # type: ignore[method-assign]
    engine.llm_gateway_status = lambda: {  # type: ignore[method-assign]
        "ok": True,
        "llmEnabled": True,
        "gatewayUrl": "http://127.0.0.1:18789/v1",
        "reachable": True,
        "note": "",
    }
    engine.human_guard.check_can_operate = lambda wechat_status=None: {  # type: ignore[method-assign]
        "ok": True,
        "enabled": True,
        "canOperate": True,
        "status": "idle_ready",
        "remainingCooldownSeconds": 0.0,
        "triggerReason": "",
    }

    orig_scan = engine.corpus_discovery.scan_archive_directories
    engine.corpus_discovery.scan_archive_directories = (  # type: ignore[method-assign]
        lambda search_dirs=None: orig_scan(search_dirs=search_dirs if search_dirs is not None else [archives_dir])
    )

    orig_hosting_status = engine.hosting_manager.status

    def _mock_hosting_status() -> Dict[str, Any]:
        if demo_state["hosting_active"]:
            return {
                "enabled": True,
                "running": True,
                "targets": list(demo_state["hosting_targets"]),
                "intervalSeconds": 15.0,
                "sendMode": "confirm_send",
                "startedAt": demo_state["hosting_started_at"],
                "lastRound": {"at": _iso_offset(1), "ok": True, "repliesDispatched": 2, "pausedByHumanGuard": False},
                "historyAppendedTotal": 4,
            }
        return orig_hosting_status()

    engine.hosting_manager.status = _mock_hosting_status  # type: ignore[method-assign]

    # Bind demo contacts cleanly (before onboarding)
    engine.bind_contact("张总（新房衣柜定制）", role="customer", care_level="special_care", auto_reply_enabled=True, notes="128平新房全屋衣柜定制")
    engine.bind_contact("林女士（老客复购）", role="customer", care_level="vip", auto_reply_enabled=True, notes="2024老客复购书房书柜")
    engine.bind_contact("王经理（精装房批量咨询）", role="customer", care_level="normal", auto_reply_enabled=True, notes="12套精装样板间批量采购")
    engine.bind_contact("测试小号", role="test", care_level="normal", auto_reply_enabled=True, notes="内部测试与 # 指令调优")

    # Ensure monitor recentEvents contains clean fictional interactions
    engine.monitor._append_event("auto_reply_sent", {
        "target": "张总（新房衣柜定制）",
        "incomingText": "太好了，这周末下午可以约免费上门量尺，大概投影面积怎么算？",
        "replyText": "好的张总，已为您预约周六下午设计师免费上门量尺，投影面积按衣柜正面宽×高透明核算，无隐形增项。",
        "ts": _iso_offset(12),
    })
    engine.monitor._append_event("preview_reply", {
        "target": "林女士（老客复购）",
        "incomingText": "行，那就帮我预约周四上午吧，大概多久能送到安装？",
        "replyText": "林女士好的，周四上午10点安排设计师上门复尺，确认方案后按正常排期交付安装。",
        "ts": _iso_offset(28),
    })
    engine.monitor._append_event("preview_reply", {
        "target": "测试小号",
        "incomingText": "三室两厅大概110平米，主要做主卧衣柜和儿童房书桌柜",
        "replyText": "收到！110平三室两厅全屋做主卧衣柜和儿童房书桌柜非常合适，我们主推ENF级实木多层板，先为您安排免费上门量尺出平面方案。",
        "ts": _iso_offset(5),
    })

    # Seed rich KB terminology + FAQ entries aligned with 星河定制家居 so offline smart replies & KB tab shine
    kb_demo_entries = [
        {
            "title": "ENF级实木多层板",
            "kind": "terminology",
            "keywords": ["ENF级实木多层板", "环保板材", "实木多层板", "板材", "环保"],
            "synonyms": ["ENF板材", "环保实木板", "多层实木"],
            "body": "星河定制家居主推基材，甲醛释放量符合国标最高ENF级（≤0.025mg/m³），防潮抗变形、握钉力强，适合新房主卧衣柜、儿童房书桌柜及南方潮湿户型。",
        },
        {
            "title": "免费上门量尺与3D方案设计",
            "kind": "service" if False else "faq",
            "keywords": ["免费上门量尺", "量尺", "设计师", "上门", "预约", "方案"],
            "synonyms": ["预约量尺", "上门测量", "出效果图"],
            "body": "客户预约后安排专业设计师带ENF级实木多层板色卡与小样免费上门量尺，现场沟通收纳习惯，48小时内免费出具全屋3D效果图与透明报价明细。",
        },
        {
            "title": "投影面积透明计价标准",
            "kind": "knowledge",
            "keywords": ["投影面积计价", "投影面积", "计价", "怎么算", "收费", "增项", "多少钱"],
            "synonyms": ["按投影算", "透明计价", "衣柜怎么收费"],
            "body": "投影面积计价 = 柜体正面宽度 × 高度，标准配置已含常规抽屉、挂衣杆与缓冲铰链，报价清单逐项写明，无隐藏五金增项或临时加价。",
        },
        {
            "title": "新房衣柜询价标准开场（先探需再报价）",
            "kind": "script",
            "keywords": ["多少钱", "底价", "报价", "衣柜", "平米", "户型", "三室两厅", "书桌柜"],
            "synonyms": ["询价话术", "探需话术"],
            "body": "您好！我们主推ENF级实木多层板全屋定制，按投影面积透明计价无隐形增项。方便说下新房大概多少平米、重点定制哪些柜子吗？我先发同户型参考清单并安排免费上门量尺",
        },
        {
            "title": "快速报价探需话术（禁止直接报底价）",
            "kind": "script",
            "keywords": ["最低", "便宜", "直接报", "最低价"],
            "synonyms": ["底价试探"],
            "body": "我们按投影面积透明计价，含常规五金抽屉无增项。您家大概多少平米、重点做哪些空间呢？确认后可安排免费上门量尺出明细清单",
        },
    ]
    for entry in kb_demo_entries:
        engine.knowledge.save_entry(
            title=entry["title"],
            body=entry["body"],
            kind=entry["kind"],
            library="shared",
            keywords=entry["keywords"],
            synonyms=entry.get("synonyms", []),
            source="demo-seed",
            external=True,
            status="published",
        )

    # Set workos task goal in isolated state to match 星河定制家居
    with engine._workos_lock:
        engine._workos_state["taskGoal"] = "接待全屋定制咨询，讲解ENF级实木多层板与投影面积透明计价，引导预约免费上门量尺"
        engine._save_workos_state()

    return engine, demo_state


def _seed_post_wizard_sparring_and_eval(engine: Any) -> None:
    """Populate realistic sparring turns, # directive critique, 1-5★ ratings, and regression run."""
    engine.set_test_contact("测试小号", enabled=True, note="内部测试与 # 指令调优")

    # Turn 1: Low-score turn before SOP polish -> rated 2★ with Chinese issue tags
    t1 = engine.sparring_simulate_turn(
        "能不能直接给个最低折扣价，别绕弯子",
        contact_name="测试小号",
        use_llm=False,
        record=True,
    )
    if t1.get("turnId"):
        engine.submit_reply_rating(
            int(t1["turnId"]),
            stars=2,
            tags=["缺少推进", "价格越权"],
            comment="",
        )

    # Save refined SOP script so subsequent # critique & regression use the polished phrasing
    engine.knowledge.save_entry(
        title="询价先探需再预约量尺话术",
        body="我们主推ENF级实木多层板，按投影面积透明计价无增项，先请问您家里大概多少平米、重点做哪些柜子呢？确认后可安排免费上门量尺出明细清单[旺柴]",
        kind="script",
        library="shared",
        keywords=["多少钱", "最低", "折扣", "底价", "优惠", "三室两厅", "衣柜"],
        source="supervisor-sop",
        external=True,
        status="published",
    )

    # Turn 2: Golden 5★ turn
    t2 = engine.sparring_simulate_turn(
        "全屋用ENF级实木多层板的话，怎么预约免费上门量尺？",
        contact_name="测试小号",
        use_llm=False,
        record=True,
    )
    if t2.get("turnId"):
        engine.submit_reply_rating(
            int(t2["turnId"]),
            stars=5,
            tags=[],
            comment="术语准确，推进自然",
        )

    # Turn 3: High-quality turn
    t3 = engine.sparring_simulate_turn(
        "投影面积计价包含抽屉和五金吗？会有隐形增项吗？",
        contact_name="测试小号",
        use_llm=False,
        record=True,
    )
    if t3.get("turnId"):
        engine.submit_reply_rating(
            int(t3["turnId"]),
            stars=4,
            tags=[],
            comment="回答清晰",
        )

    engine.profile_contacts()
    engine.sales_crm.get_overview(auto_sync=True)


# ---------------------------------------------------------------------------
# Node CDP Driver (Native WebSocket in Node 22+)
# ---------------------------------------------------------------------------

CDP_MJS = r"""
import fs from "node:fs";
import readline from "node:readline";

const wsUrl = process.argv[2];
const ws = new WebSocket(wsUrl);
let nextId = 1;
const pending = new Map();

ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(String(ev.data));
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  }
});

function cdp(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve, { once: true });
  ws.addEventListener("error", reject, { once: true });
});

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of rl) {
  if (!line.trim()) continue;
  const req = JSON.parse(line);
  try {
    if (req.op === "cdp") {
      const res = await cdp(req.method, req.params || {});
      process.stdout.write(JSON.stringify({ ok: true, result: res }) + "\n");
    } else if (req.op === "save_screenshot") {
      const res = await cdp("Page.captureScreenshot", { format: "png", fromSurface: true });
      fs.writeFileSync(req.path, Buffer.from(res.data, "base64"));
      process.stdout.write(JSON.stringify({ ok: true, path: req.path }) + "\n");
    } else if (req.op === "quit") {
      process.stdout.write(JSON.stringify({ ok: true }) + "\n");
      break;
    }
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(err && err.message ? err.message : err) }) + "\n");
  }
}
ws.close();
process.exit(0);
"""


class CdpClient:
    """Thin synchronous wrapper over a persistent Node 22 WebSocket CDP session."""

    def __init__(self, ws_url: str, driver_path: Path) -> None:
        driver_path.write_text(CDP_MJS, encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(NODE_BIN), str(driver_path), ws_url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"CDP driver exited unexpectedly: {err}")
        resp = json.loads(line)
        if not resp.get("ok"):
            raise RuntimeError(f"CDP error: {resp.get('error')}")
        return resp

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._send({"op": "cdp", "method": method, "params": params or {}}).get("result", {})

    def eval_js(self, expr: str, await_promise: bool = True) -> Any:
        wrapped = f"(async () => {{ {expr} }})()" if await_promise else f"(() => {{ {expr} }})()"
        res = self.call(
            "Runtime.evaluate",
            {
                "expression": wrapped,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS exception: {json.dumps(res['exceptionDetails'], ensure_ascii=False)}")
        return (res.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Page.navigate", {"url": url})
        time.sleep(0.8)

    def screenshot(self, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._send({"op": "save_screenshot", "path": str(out_path)})

    def close(self) -> None:
        try:
            self._send({"op": "quit"})
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Annotation Overlay Helpers (Temp DOM Overlay via getBoundingClientRect)
# ---------------------------------------------------------------------------

OVERLAY_JS = r"""
(() => {
  const existing = document.getElementById("__guideOverlayRoot");
  if (existing) existing.remove();
  const root = document.createElement("div");
  root.id = "__guideOverlayRoot";
  Object.assign(root.style, {
    position: "fixed",
    inset: "0",
    pointerEvents: "none",
    zIndex: "2147483647",
    overflow: "hidden",
  });
  document.body.appendChild(root);

  const specs = __SPECS_JSON__;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const circled = ["", "①", "②", "③", "④", "⑤"];

  for (const spec of specs) {
    let rect = null;
    if (Array.isArray(spec.selectors) && spec.selectors.length) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const sel of spec.selectors) {
        const el = document.querySelector(sel);
        if (!el) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        minX = Math.min(minX, r.left);
        minY = Math.min(minY, r.top);
        maxX = Math.max(maxX, r.right);
        maxY = Math.max(maxY, r.bottom);
      }
      if (minX < maxX && minY < maxY) {
        rect = { left: minX, top: minY, right: maxX, bottom: maxY, width: maxX - minX, height: maxY - minY };
      }
    } else if (spec.selector) {
      const el = document.querySelector(spec.selector);
      if (el) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) rect = r;
      }
    }
    if (!rect) continue;

    const pad = Number(spec.pad ?? 4);
    const left = Math.max(4, rect.left - pad);
    const top = Math.max(4, rect.top - pad);
    const right = Math.min(vw - 4, rect.right + pad);
    const bottom = Math.min(vh - 4, rect.bottom + pad);
    const width = Math.max(12, right - left);
    const height = Math.max(12, bottom - top);

    const box = document.createElement("div");
    Object.assign(box.style, {
      position: "fixed",
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`,
      border: "2.5px solid #e11d48",
      borderRadius: "10px",
      boxShadow: "0 0 0 3px rgba(225, 29, 72, 0.16)",
      background: "rgba(225, 29, 72, 0.03)",
      boxSizing: "border-box",
    });
    root.appendChild(box);

    const badgeSize = 26;
    const pos = spec.pos || "tl";
    let bx = left - 10;
    let by = top - 12;
    if (pos === "tr") {
      bx = right - 16;
      by = top - 12;
    } else if (pos === "bl") {
      bx = left - 10;
      by = bottom - 14;
    } else if (pos === "br") {
      bx = right - 16;
      by = bottom - 14;
    } else if (pos === "left") {
      bx = left - badgeSize - 6;
      by = top + (height - badgeSize) / 2;
    } else if (pos === "right") {
      bx = right + 6;
      by = top + (height - badgeSize) / 2;
    } else if (pos === "top-center") {
      bx = left + (width - badgeSize) / 2;
      by = top - badgeSize - 4;
    }
    bx = Math.max(6, Math.min(vw - badgeSize - 6, bx));
    by = Math.max(6, Math.min(vh - badgeSize - 6, by));

    const badge = document.createElement("div");
    badge.textContent = circled[spec.num] || String(spec.num);
    Object.assign(badge.style, {
      position: "fixed",
      left: `${bx}px`,
      top: `${by}px`,
      width: `${badgeSize}px`,
      height: `${badgeSize}px`,
      borderRadius: "999px",
      background: "#e11d48",
      color: "#ffffff",
      border: "2px solid #ffffff",
      boxShadow: "0 2px 8px rgba(15, 23, 42, 0.35)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "15px",
      fontWeight: "800",
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
      lineHeight: "1",
    });
    root.appendChild(badge);
  }
  return root.children.length;
})();
"""


def _capture_annotated(cdp: CdpClient, filename: str, specs: List[Dict[str, Any]]) -> Path:
    """Inject annotation overlay, capture 2x PNG, then remove overlay."""
    out_path = OUT_DIR / filename
    cdp.eval_js('document.getElementById("toast")?.classList.remove("show");', await_promise=False)
    js = OVERLAY_JS.strip().replace("__SPECS_JSON__", json.dumps(specs, ensure_ascii=False))
    count = cdp.eval_js(f"return {js}", await_promise=False)
    time.sleep(0.15)
    cdp.screenshot(out_path)
    cdp.eval_js('document.getElementById("__guideOverlayRoot")?.remove();', await_promise=False)
    print(f"[captured] {out_path.name} (overlays={count})")
    return out_path


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_cdp_ws(port: int, timeout: float = 12.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5) as resp:
                pages = json.loads(resp.read().decode("utf-8"))
                for p in pages:
                    if p.get("type") == "page" and p.get("webSocketDebuggerUrl"):
                        return str(p["webSocketDebuggerUrl"])
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Chrome CDP did not become ready on port {port}")


def _wait_until(cdp: CdpClient, js_cond: str, timeout: float = 10.0, desc: str = "condition") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ok = cdp.eval_js(f"return Boolean({js_cond});", await_promise=False)
        if ok:
            return
        time.sleep(0.15)
    raise TimeoutError(f"Timed out waiting for: {desc}")


def _freeze_background_polls(cdp: CdpClient) -> None:
    """Clear background polling intervals so timed refreshes never race with UI state."""
    cdp.eval_js(
        """
        for (let i = 1; i < 500; i++) {
          try { window.clearInterval(i); } catch (e) {}
        }
        """,
        await_promise=False,
    )


def main() -> int:
    if not CHROME_BIN.is_file():
        raise FileNotFoundError(f"Google Chrome not found at {CHROME_BIN}")
    if not NODE_BIN.is_file():
        raise FileNotFoundError(f"Node binary not found at {NODE_BIN}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_root = Path(tempfile.mkdtemp(prefix="wechatbot_guide_demo_"))
    chrome_profile = tmp_root / "chrome_profile"
    chrome_profile.mkdir(parents=True, exist_ok=True)

    engine, demo_state = _create_isolated_engine(tmp_root)

    from wechat_control.mcp_server import create_http_server

    server = create_http_server(engine, host="127.0.0.1", port=0)
    server.daemon_threads = True
    port = int(server.server_address[1])
    base_url = f"http://127.0.0.1:{port}/"
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    cdp_port = _find_free_port()
    chrome_proc = subprocess.Popen(
        [
            str(CHROME_BIN),
            "--headless=new",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={chrome_profile}",
            "--window-size=1360,880",
            "--force-device-scale-factor=2",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    cdp: Optional[CdpClient] = None
    try:
        ws_url = _wait_for_cdp_ws(cdp_port)
        cdp = CdpClient(ws_url, tmp_root / "cdp_driver.mjs")
        cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1360, "height": 880, "deviceScaleFactor": 2, "mobile": False},
        )

        # Force light theme deterministically for consistent documentation clarity
        cdp.navigate(base_url)
        cdp.eval_js('localStorage.setItem("openbot_wechat_theme", "light"); document.documentElement.setAttribute("data-theme", "light");', await_promise=False)

        # ------------------------------------------------------------------
        # 1) 01-permissions-modal.png
        # ------------------------------------------------------------------
        demo_state["permissions_granted"] = False
        cdp.navigate(base_url)
        _wait_until(
            cdp,
            'document.getElementById("permOverlay")?.classList.contains("visible") && document.querySelectorAll("#permModalItems .perm-item").length >= 1',
            desc="permissions modal visible",
        )
        _freeze_background_polls(cdp)
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "01-permissions-modal.png",
            [
                {"num": 1, "selector": "#permModalOpenSettings", "pos": "tl", "pad": 4},
                {"num": 2, "selector": "#permOverlay .perm-modal-actions .btn-outline", "pos": "tr", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 2) 02-wizard-step1-identity.png
        # ------------------------------------------------------------------
        demo_state["permissions_granted"] = True
        cdp.navigate(base_url)
        _wait_until(cdp, 'typeof STATE === "object" && STATE !== null', desc="STATE loaded")
        _freeze_background_polls(cdp)
        cdp.eval_js(
            """
            document.documentElement.setAttribute("data-theme", "light");
            await openOnboardingWizard(1);
            document.getElementById("wizOwnerName").value = "陈经理";
            document.getElementById("wizBusinessName").value = "星河定制家居";
            document.getElementById("wizOwnerAliases").value = "小陈, 陈顾问";
            document.getElementById("wizProductSummary").value = "全屋环保实木定制、免费上门量尺设计与投影面积透明计价";
            document.getElementById("wizIndustryPack").value = "general_sales";
            document.getElementById("wizTestContacts").value = "测试小号";
            """
        )
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "02-wizard-step1-identity.png",
            [
                {"num": 1, "selectors": ["#wizardStepPanel1 > div:nth-child(1)", "#wizardStepPanel1 > div:nth-child(4)"], "pos": "tr", "pad": 6},
                {"num": 2, "selector": "#wizSaveStep1Btn", "pos": "left", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 3) 03-wizard-step2-discover.png
        # ------------------------------------------------------------------
        cdp.eval_js("await wizardSubmitStep1();")
        _wait_until(
            cdp,
            '!document.getElementById("wizardStepPanel2").hidden && document.querySelectorAll(".wiz-sess-cb").length >= 3 && document.querySelectorAll(".wiz-arch-cb").length >= 1',
            desc="wizard step 2 sessions & archives",
        )
        cdp.eval_js(
            """
            document.getElementById("wizProductDocText").value = "主推ENF级实木多层板全屋衣柜定制，支持免费上门量尺出3D效果图，采用投影面积透明计价无隐形增项。";
            """,
            await_promise=False,
        )
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "03-wizard-step2-discover.png",
            [
                {"num": 1, "selector": "#wizDiscoveredSessions", "pos": "tr", "pad": 4},
                {"num": 2, "selector": "#wizRunTrainBtn", "pos": "tr", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 4) 04-wizard-step3-review.png
        # ------------------------------------------------------------------
        cdp.eval_js("await wizardRunTraining();")
        _wait_until(
            cdp,
            '!document.getElementById("wizardStepPanel3").hidden && document.querySelectorAll("#wizDraftsList .wiz-draft-cb").length >= 1',
            desc="wizard step 3 drafts",
        )
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "04-wizard-step3-review.png",
            [
                {"num": 1, "selector": "#wizDraftsList", "pos": "tr", "pad": 4},
                {"num": 2, "selector": "#wizardStepPanel3 .btn-solid", "pos": "left", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 5) 05-wizard-step4-simulate.png
        # ------------------------------------------------------------------
        cdp.eval_js("await wizardApproveDraftsAndNext();")
        _wait_until(cdp, '!document.getElementById("wizardStepPanel4").hidden', desc="wizard step 4")
        cdp.eval_js(
            """
            document.querySelector("#wizSimChatLog .sparring-msg.sys")?.remove();
            const wizModal = document.querySelector("#onboardingWizardOverlay .perm-modal");
            if (wizModal) { wizModal.style.maxHeight = "92vh"; }
            const simLog = document.getElementById("wizSimChatLog");
            if (simLog) { simLog.style.maxHeight = "360px"; simLog.style.minHeight = "280px"; }
            const sendBtn = document.querySelector('#wizardStepPanel4 button[onclick*="wizardSendSimTurn"]');
            if (sendBtn) { sendBtn.style.whiteSpace = "nowrap"; sendBtn.style.flexShrink = "0"; }
            """,
            await_promise=False,
        )
        for q in (
            "你们全屋定制用的什么板材，环保达标吗？",
            "衣柜大概怎么收费，会有隐形增项吗？",
            "想约设计师上门量尺看看方案，怎么安排？",
        ):
            cdp.eval_js(
                f"""
                document.getElementById("wizSimInput").value = {json.dumps(q, ensure_ascii=False)};
                await wizardSendSimTurn();
                """
            )
            time.sleep(0.15)
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "05-wizard-step4-simulate.png",
            [
                {"num": 1, "selector": "#wizSimChatLog", "pos": "tr", "pad": 4},
                {"num": 2, "selector": "#wizardStepPanel4 .btn-solid:last-child", "pos": "left", "pad": 4},
            ],
        )

        # Close wizard & seed rich sparring / ratings / regression data for tabs 06..10
        cdp.eval_js("hideOnboardingWizard();", await_promise=False)
        _seed_post_wizard_sparring_and_eval(engine)
        cdp.eval_js("await loadOverview(false);")
        _freeze_background_polls(cdp)
        time.sleep(0.3)

        # ------------------------------------------------------------------
        # 6) 06-contacts-test-friend.png
        # ------------------------------------------------------------------
        cdp.eval_js(
            """
            switchTab("care");
            window.scrollTo(0, 0);
            """,
            await_promise=False,
        )
        _wait_until(
            cdp,
            'document.getElementById("tab-care")?.classList.contains("active") && document.querySelectorAll("#contactsGrid .contact-card").length >= 3',
            desc="contacts grid rendered",
        )
        time.sleep(0.25)
        _capture_annotated(
            cdp,
            "06-contacts-test-friend.png",
            [
                {"num": 1, "selector": '#contactsGrid .contact-card:first-child .contact-actions button:nth-child(2)', "pos": "tl", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 7) 07-composer-hashtag-and-rating.png
        # ------------------------------------------------------------------
        cdp.eval_js(
            f"""
            switchTab("monitor");
            selectChatThread(encodeURIComponent("测试小号"), encodeURIComponent("三室两厅大概110平米，主要做主卧衣柜和儿童房书桌柜"), true);
            await runReplyPreview();
            selectDraftFeedbackStar(2);
            const firstTag = document.querySelector('#draftQualityFeedbackBar .tag-chip[data-tag="缺少推进"]');
            if (firstTag) toggleDraftFeedbackTag(firstTag, "缺少推进");
            const sendBox = document.getElementById("sendText");
            sendBox.value = "# 不能这样说，别一上来报底价，先问对方大概做多少平米";
            onComposerTextInput();
            const mainPane = document.querySelector(".chat-main-pane");
            if (mainPane) mainPane.scrollTop = mainPane.scrollHeight;
            document.getElementById("draftQualityFeedbackBar")?.scrollIntoView({{ block: "end" }});
            """
        )
        _wait_until(
            cdp,
            '!document.getElementById("supervisorDirectiveBanner").hidden && !document.getElementById("draftQualityFeedbackBar").hidden',
            desc="hashtag banner & draft rating bar visible",
        )
        time.sleep(0.3)
        _capture_annotated(
            cdp,
            "07-composer-hashtag-and-rating.png",
            [
                {"num": 1, "selector": "#supervisorDirectiveBanner", "pos": "left", "pad": 4},
                {"num": 2, "selector": "#draftQualityFeedbackBar", "pos": "left", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 8) 08-sparring-quality-dashboard.png
        # ------------------------------------------------------------------
        cdp.eval_js(
            """
            document.getElementById("sendText").value = "";
            onComposerTextInput();
            switchTab("sparring");
            await loadSparringWorkspace(false);
            document.getElementById("simContactInput").value = "测试小号";
            document.getElementById("simMessageInput").value = "三室两厅衣柜大概多少钱，有优惠吗？";
            await sendSparringSimMessage();
            document.getElementById("simMessageInput").value = "# 不能这样说，别一上来报底价，先问对方大概做多少平米";
            await sendSparringSimMessage();
            await runSparringRegressionSuite();
            window.scrollTo(0, 0);
            """
        )
        _wait_until(
            cdp,
            'document.getElementById("tab-sparring")?.classList.contains("active") && !document.getElementById("simRegressionBox").hidden && document.querySelectorAll("#sparringTurnsLogBox > div").length >= 2',
            desc="sparring workspace populated",
        )
        time.sleep(0.3)
        _capture_annotated(
            cdp,
            "08-sparring-quality-dashboard.png",
            [
                {"num": 1, "selector": "#simChatLogBox", "pos": "tr", "pad": 4},
                {"num": 2, "selector": "#sparringRegressionBtn", "pos": "tr", "pad": 4},
                {"num": 3, "selector": "#qualityKpiGrid", "pos": "tr", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 9) 09-hosting-workbench-home.png
        # ------------------------------------------------------------------
        demo_state["hosting_active"] = True
        cdp.eval_js(
            """
            await loadOverview(false);
            switchTab("monitor");
            selectChatThread(encodeURIComponent("张总（新房衣柜定制）"), "", true);
            document.getElementById("sendText").value = "好的张总，这周六下午安排设计师带ENF级实木多层板小样免费上门量尺，量尺后出3D图和投影面积透明清单。";
            onComposerTextInput();
            document.getElementById("replyPreviewResult").hidden = true;
            document.getElementById("draftQualityFeedbackBar").hidden = true;
            const mainPane = document.querySelector(".chat-main-pane");
            if (mainPane) mainPane.scrollTop = 0;
            window.scrollTo(0, 0);
            """
        )
        _wait_until(
            cdp,
            'document.getElementById("hostingBadge")?.textContent.includes("托管中") && document.querySelectorAll("#chatBubbleStream .bubble-row").length >= 3',
            desc="hosting workbench overview ready",
        )
        time.sleep(0.3)
        _capture_annotated(
            cdp,
            "09-hosting-workbench-home.png",
            [
                {"num": 1, "selectors": ["#topOnboardingWizardBtn", "#topUserGuideBtn"], "pos": "tl", "pad": 4},
                {"num": 2, "selector": "#hostingPanel", "pos": "bl", "pad": 4},
            ],
        )

        # ------------------------------------------------------------------
        # 10) 10-knowledge-base.png
        # ------------------------------------------------------------------
        demo_state["hosting_active"] = False
        cdp.eval_js(
            """
            switchTab("knowledge");
            document.getElementById("kbSearchInput").value = "ENF级实木多层板 投影面积 免费上门量尺";
            await searchKb();
            window.scrollTo(0, 0);
            """
        )
        _wait_until(
            cdp,
            'document.getElementById("tab-knowledge")?.classList.contains("active") && document.querySelectorAll("#kbList .kb-item").length >= 3',
            desc="knowledge base items rendered",
        )
        time.sleep(0.3)
        _capture_annotated(
            cdp,
            "10-knowledge-base.png",
            [
                {"num": 1, "selectors": ["#kbSearchInput", "#kbKindFilter", '#tab-knowledge button[onclick="searchKb()"]'], "pos": "left", "pad": 4},
                {"num": 2, "selector": "#kbDocIngestBtn", "pos": "left", "pad": 4},
                {"num": 3, "selector": "#kbList", "pos": "left", "pad": 4},
            ],
        )

        print("All 10 screenshots captured successfully in", OUT_DIR)
        return 0
    finally:
        if cdp is not None:
            cdp.close()
        try:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=4)
        except Exception:
            try:
                chrome_proc.kill()
            except Exception:
                pass
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
