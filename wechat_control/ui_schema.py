#!/usr/bin/env python3
"""Standardized WeChat macOS UI schema, spatial regions, and protocolized navigation."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


WECHAT_UI_SCHEMA_VERSION = "1.0.0"


WECHAT_UI_VIEWS: Dict[str, Dict[str, Any]] = {
    "main_chat_split": {
        "id": "main_chat_split",
        "title": "主界面·双栏会话与聊天窗口",
        "description": "左侧导航栏 + 会话搜索与列表 + 右侧当前聊天正文与输入工具栏。",
        "regions": [
            "left_nav_rail",
            "session_search_bar",
            "session_list_pane",
            "chat_header_bar",
            "chat_message_stream",
            "chat_composer_toolbar",
            "chat_input_box",
        ],
        "landmarks": ["搜索", "文件传输助手"],
    },
    "main_chat_with_article_reader": {
        "id": "main_chat_with_article_reader",
        "title": "主界面·三栏含内置公众号文章阅读器",
        "description": "在主界面右侧展开公众号文章阅读页（顶部标签含 ⋯ 复制链接、独立窗口图标，底部含关注/点赞/转发）。",
        "regions": [
            "left_nav_rail",
            "session_search_bar",
            "session_list_pane",
            "chat_message_stream",
            "article_reader_header",
            "article_reader_body",
            "article_reader_footer",
        ],
        "landmarks": ["原创", "+关注", "推荐"],
    },
    "contacts_directory": {
        "id": "contacts_directory",
        "title": "通讯录与好友/群聊管理界面",
        "description": "通过左侧导航「通讯录」进入，左侧管理新的朋友、群聊、标签与联系人列表，右侧显示详情与发消息入口。",
        "regions": ["left_nav_rail", "session_search_bar", "session_list_pane", "chat_message_stream"],
        "landmarks": ["通讯录管理", "新的朋友", "群聊"],
    },
    "favorites_panel": {
        "id": "favorites_panel",
        "title": "收藏与笔记管理界面",
        "description": "通过左侧导航「收藏」进入，浏览全部收藏、图片、链接、文件与聊天笔记。",
        "regions": ["left_nav_rail", "session_search_bar", "session_list_pane", "chat_message_stream"],
        "landmarks": ["全部收藏", "新建笔记", "链接"],
    },
    "more_menu_popup": {
        "id": "more_menu_popup",
        "title": "左下角「更多 ≡」功能与设置弹窗",
        "description": "点击左下角 ≡ 后弹出的菜单浮层，提供设置、备份与恢复、锁定、意见反馈入口。",
        "regions": ["left_nav_rail"],
        "landmarks": ["设置", "备份与恢复", "锁定"],
    },
    "settings_window": {
        "id": "settings_window",
        "title": "微信设置独立窗口",
        "description": "可通过 ≡ -> 设置 或快捷键 Cmd+, 打开，包含账号与存储、通用、消息通知、快捷键、关于微信等分页。",
        "regions": ["settings_tabs", "settings_content"],
        "landmarks": ["账号与存储", "通用设置", "消息通知", "快捷键"],
    },
    "chat_info_drawer": {
        "id": "chat_info_drawer",
        "title": "当前聊天右侧详情与设置抽屉",
        "description": "点击聊天顶栏右上角 ⋯ 打开，可配置消息免打扰、置顶聊天、查找聊天记录、清空聊天记录等。",
        "regions": ["left_nav_rail", "chat_header_bar", "chat_info_drawer_pane"],
        "landmarks": ["查找聊天记录", "消息免打扰", "置顶聊天"],
    },
    "standalone_article_window": {
        "id": "standalone_article_window",
        "title": "独立文章/浏览器弹窗",
        "description": "点击阅读器右上角弹出按钮或链接后打开的独立微信网页浏览窗口。",
        "regions": ["article_reader_header", "article_reader_body", "article_reader_footer"],
        "landmarks": ["复制链接", "在默认浏览器中打开"],
    },
}


WECHAT_UI_REGIONS: Dict[str, Dict[str, Any]] = {
    "left_nav_rail": {
        "id": "left_nav_rail",
        "title": "最左侧固定导航栏",
        "purpose": "切换聊天、通讯录、收藏、朋友圈/看一看及左下角设置菜单。",
        "anchorSpec": {"x0": 0, "y0": 0, "x1": 54, "y1": "H"},
    },
    "session_search_bar": {
        "id": "session_search_bar",
        "title": "会话列表顶部搜索与发起群聊栏",
        "purpose": "快捷搜索联系人/群聊/聊天记录（Cmd+F）或点击 + 发起群聊/添加朋友。",
        "anchorSpec": {"x0": 54, "y0": 0, "x1": "session_split_x", "y1": 54},
    },
    "session_list_pane": {
        "id": "session_list_pane",
        "title": "中间左侧会话与联系人列表区",
        "purpose": "展示置顶聊天、未读红点/未读计数、最新摘要与时间。",
        "anchorSpec": {"x0": 54, "y0": 54, "x1": "session_split_x", "y1": "H"},
    },
    "chat_header_bar": {
        "id": "chat_header_bar",
        "title": "当前聊天顶部标题与更多抽屉栏",
        "purpose": "显示当前联系人/群名与人数，右侧 ⋯ 打开聊天设置抽屉。",
        "anchorSpec": {"x0": "session_split_x", "y0": 0, "x1": "chat_right_x", "y1": 54},
    },
    "chat_message_stream": {
        "id": "chat_message_stream",
        "title": "当前聊天消息气泡流",
        "purpose": "左侧灰/白气泡为对方消息，右侧绿气泡为本人/机器人发出消息。",
        "anchorSpec": {"x0": "session_split_x", "y0": 54, "x1": "chat_right_x", "y1": "composer_top_y"},
    },
    "chat_composer_toolbar": {
        "id": "chat_composer_toolbar",
        "title": "输入框上方功能工具栏",
        "purpose": "提供表情、发送文件、截图、聊天记录、语音/视频通话按钮。",
        "anchorSpec": {"x0": "session_split_x", "y0": "composer_top_y", "x1": "chat_right_x", "y1": "input_top_y"},
    },
    "chat_input_box": {
        "id": "chat_input_box",
        "title": "消息编辑与 Enter 发送区",
        "purpose": "聚焦粘贴内容并通过读回校验确认发送或静默测试。",
        "anchorSpec": {"x0": "session_split_x", "y0": "input_top_y", "x1": "chat_right_x", "y1": "H"},
    },
    "article_reader_header": {
        "id": "article_reader_header",
        "title": "微信内置阅读器顶栏",
        "purpose": "展示文章标签胶囊、右侧 ⋯（含复制链接）与独立窗口图标。",
        "anchorSpec": {"x0": "article_split_x", "y0": 0, "x1": "W", "y1": 56},
    },
    "article_reader_body": {
        "id": "article_reader_body",
        "title": "文章正文与配图滚动阅读区",
        "purpose": "渲染标题、作者/公众号、发布时间、正文段落与防盗链图片。",
        "anchorSpec": {"x0": "article_split_x", "y0": 56, "x1": "W", "y1": "H-56"},
    },
    "article_reader_footer": {
        "id": "article_reader_footer",
        "title": "文章底部互动工具栏",
        "purpose": "展示公众号头像/+关注、点赞、转发、推荐与留言按钮。",
        "anchorSpec": {"x0": "article_split_x", "y0": "H-56", "x1": "W", "y1": "H"},
    },
}


WECHAT_UI_TARGETS: Dict[str, Dict[str, Any]] = {
    "nav.avatar_profile": {
        "id": "nav.avatar_profile",
        "title": "左上角个人头像",
        "view": "main_chat_split",
        "region": "left_nav_rail",
        "category": "navigation",
        "description": "查看当前登录微信号昵称、微信号与状态设置。",
        "anchor": {"mode": "fixed_top_left", "x": 27, "y": 68},
        "expectedAfter": "弹出个人资料卡片",
    },
    "nav.chats": {
        "id": "nav.chats",
        "title": "导航栏 · 聊天",
        "view": "main_chat_split",
        "region": "left_nav_rail",
        "category": "navigation",
        "description": "切回主会话列表与当前聊天窗口（快捷键 Cmd+1 / 点击绿气泡图标）。",
        "anchor": {"mode": "fixed_top_left", "x": 27, "y": 118},
        "ocrHints": ["聊天"],
        "expectedView": "main_chat_split",
    },
    "nav.contacts": {
        "id": "nav.contacts",
        "title": "导航栏 · 通讯录",
        "view": "contacts_directory",
        "region": "left_nav_rail",
        "category": "navigation",
        "description": "进入通讯录管理好友、新的朋友、群聊与标签。",
        "anchor": {"mode": "fixed_top_left", "x": 27, "y": 160},
        "ocrHints": ["通讯录"],
        "expectedView": "contacts_directory",
    },
    "nav.favorites": {
        "id": "nav.favorites",
        "title": "导航栏 · 收藏",
        "view": "favorites_panel",
        "region": "left_nav_rail",
        "category": "navigation",
        "description": "进入我的收藏面板查看文章/笔记/文件。",
        "anchor": {"mode": "fixed_top_left", "x": 27, "y": 202},
        "ocrHints": ["收藏"],
        "expectedView": "favorites_panel",
    },
    "nav.discover": {
        "id": "nav.discover",
        "title": "导航栏 · 发现/看一看",
        "view": "main_chat_split",
        "region": "left_nav_rail",
        "category": "navigation",
        "description": "打开指南针图标对应的搜一搜/看一看入口。",
        "anchor": {"mode": "fixed_top_left", "x": 27, "y": 244},
        "expectedAfter": "展示内容浏览列表",
    },
    "nav.phone_handoff": {
        "id": "nav.phone_handoff",
        "title": "左下角 · 手机备份/仅传输入口",
        "view": "main_chat_split",
        "region": "left_nav_rail",
        "category": "settings",
        "description": "打开聊天记录迁移与备份快捷面板。",
        "anchor": {"mode": "fixed_bottom_left", "x": 27, "offsetBottom": 86},
        "expectedAfter": "展示手机互传/备份提示",
    },
    "nav.more_menu": {
        "id": "nav.more_menu",
        "title": "左下角 · 更多设置菜单 (≡)",
        "view": "more_menu_popup",
        "region": "left_nav_rail",
        "category": "settings",
        "description": "展开包含设置、迁移与备份、锁定、快捷键说明的主菜单。",
        "anchor": {"mode": "fixed_bottom_left", "x": 27, "offsetBottom": 42},
        "expectedView": "more_menu_popup",
    },
    "menu.settings": {
        "id": "menu.settings",
        "title": "微信全局设置窗口 (设置)",
        "view": "settings_window",
        "region": "left_nav_rail",
        "category": "settings",
        "description": "两步协议导航：先点左下角 ≡，再通过 Vision OCR 点击「设置」打开微信设置弹窗。",
        "anchor": {"mode": "two_step_menu", "preClick": "nav.more_menu", "menuTexts": ["设置", "Settings"]},
        "expectedView": "settings_window",
    },
    "menu.backup_restore": {
        "id": "menu.backup_restore",
        "title": "迁移与备份 (备份与恢复)",
        "view": "more_menu_popup",
        "region": "left_nav_rail",
        "category": "settings",
        "description": "两步协议导航：点左下角 ≡ -> 点击「迁移与备份」或「备份与恢复」。",
        "anchor": {"mode": "two_step_menu", "preClick": "nav.more_menu", "menuTexts": ["迁移与备份", "备份与恢复"]},
        "expectedAfter": "打开聊天记录迁移与备份面板",
    },
    "settings.tab_general": {
        "id": "settings.tab_general",
        "title": "设置分页 · 通用设置",
        "view": "settings_window",
        "region": "settings_tabs",
        "category": "settings",
        "description": "定位设置窗口中的「通用设置」分页（语言、字体大小、阅读设置等）。",
        "anchor": {"mode": "ocr_only", "menuTexts": ["通用设置", "通用"]},
        "expectedView": "settings_window",
    },
    "settings.tab_account_storage": {
        "id": "settings.tab_account_storage",
        "title": "设置分页 · 账号与存储",
        "view": "settings_window",
        "region": "settings_tabs",
        "category": "settings",
        "description": "定位设置窗口中的「账号与存储」分页（聊天记录管理、缓存清理）。",
        "anchor": {"mode": "ocr_only", "menuTexts": ["账号与存储", "存储空间"]},
        "expectedView": "settings_window",
    },
    "settings.tab_notifications": {
        "id": "settings.tab_notifications",
        "title": "设置分页 · 消息通知",
        "view": "settings_window",
        "region": "settings_tabs",
        "category": "settings",
        "description": "定位设置窗口中的「消息通知」分页（声音、横幅提醒）。",
        "anchor": {"mode": "ocr_only", "menuTexts": ["消息通知", "通知"]},
        "expectedView": "settings_window",
    },
    "settings.tab_shortcuts": {
        "id": "settings.tab_shortcuts",
        "title": "设置分页 · 快捷键",
        "view": "settings_window",
        "region": "settings_tabs",
        "category": "settings",
        "description": "定位设置窗口中的「快捷键」分页（发送消息热键、截图热键）。",
        "anchor": {"mode": "ocr_only", "menuTexts": ["快捷键"]},
        "expectedView": "settings_window",
    },
    "chat.search_input": {
        "id": "chat.search_input",
        "title": "顶部会话搜索框",
        "view": "main_chat_split",
        "region": "session_search_bar",
        "category": "chat_window",
        "description": "点击聚焦联系人/群聊搜索输入框。",
        "anchor": {"mode": "session_search_box"},
        "expectedAfter": "光标进入顶部搜索框",
    },
    "chat.new_group_plus": {
        "id": "chat.new_group_plus",
        "title": "顶部发起群聊/加好友按钮 (+)",
        "view": "main_chat_split",
        "region": "session_search_bar",
        "category": "chat_window",
        "description": "点击搜索栏右侧 + 按钮选择发起群聊或添加朋友。",
        "anchor": {"mode": "session_plus_btn"},
        "expectedAfter": "弹出发起群聊/添加朋友下拉菜单",
    },
    "chat.header_more_drawer": {
        "id": "chat.header_more_drawer",
        "title": "当前聊天右上角详情设置 (⋯)",
        "view": "chat_info_drawer",
        "region": "chat_header_bar",
        "category": "chat_window",
        "description": "打开当前联系人的聊天信息抽屉（置顶、免打扰、查找聊天记录）。",
        "anchor": {"mode": "chat_header_more"},
        "expectedView": "chat_info_drawer",
    },
    "chat.toolbar_emoji": {
        "id": "chat.toolbar_emoji",
        "title": "聊天工具栏 · 表情按钮",
        "view": "main_chat_split",
        "region": "chat_composer_toolbar",
        "category": "chat_window",
        "description": "打开当前聊天表情面板。",
        "anchor": {"mode": "composer_tool", "slot": 0},
        "expectedAfter": "弹出表情选择面板",
    },
    "chat.toolbar_send_file": {
        "id": "chat.toolbar_send_file",
        "title": "聊天工具栏 · 发送文件",
        "view": "main_chat_split",
        "region": "chat_composer_toolbar",
        "category": "chat_window",
        "description": "打开发送本地文件选择框。",
        "anchor": {"mode": "composer_tool", "slot": 1},
        "expectedAfter": "弹出文件选择弹窗",
    },
    "chat.toolbar_screenshot": {
        "id": "chat.toolbar_screenshot",
        "title": "聊天工具栏 · 截图",
        "view": "main_chat_split",
        "region": "chat_composer_toolbar",
        "category": "chat_window",
        "description": "触发微信框选截图工具。",
        "anchor": {"mode": "composer_tool", "slot": 2},
        "expectedAfter": "进入截图选区",
    },
    "chat.toolbar_history": {
        "id": "chat.toolbar_history",
        "title": "聊天工具栏 · 聊天记录管理",
        "view": "main_chat_split",
        "region": "chat_composer_toolbar",
        "category": "chat_window",
        "description": "打开当前联系人的历史聊天记录检索窗口。",
        "anchor": {"mode": "composer_tool", "slot": 3},
        "expectedAfter": "弹出历史消息搜索框",
    },
    "chat.input_area": {
        "id": "chat.input_area",
        "title": "聊天正文输入编辑区",
        "view": "main_chat_split",
        "region": "chat_input_box",
        "category": "chat_window",
        "description": "聚焦当前会话底部文本输入区。",
        "anchor": {"mode": "chat_input_center"},
        "expectedAfter": "光标聚焦到输入框",
    },
    "article.tab_more_menu": {
        "id": "article.tab_more_menu",
        "title": "文章阅读器标签 ⋯ 菜单",
        "view": "main_chat_with_article_reader",
        "region": "article_reader_header",
        "category": "article_reader",
        "description": "打开右侧公众号文章标签页的 ⋯ 下拉菜单（包含复制链接、刷新、浮窗等）。",
        "anchor": {"mode": "article_tab_dots"},
        "expectedAfter": "展示复制链接等文章操作项",
    },
    "article.open_standalone_window": {
        "id": "article.open_standalone_window",
        "title": "文章右上角 · 独立窗口打开",
        "view": "standalone_article_window",
        "region": "article_reader_header",
        "category": "article_reader",
        "description": "点击阅读器右上角方框箭头图标，将当前文章弹出为独立窗口。",
        "anchor": {"mode": "article_popout"},
        "expectedView": "standalone_article_window",
    },
    "article.body_scroll_area": {
        "id": "article.body_scroll_area",
        "title": "文章正文滚动阅读区",
        "view": "main_chat_with_article_reader",
        "region": "article_reader_body",
        "category": "article_reader",
        "description": "定位右侧文章正文中央安全滚动锚点。",
        "anchor": {"mode": "article_body_center"},
        "expectedAfter": "可在正文区安全滚动翻页",
    },
}


def _clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def compute_layout_geometry(
    bounds: Dict[str, Any],
    ocr_elements: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Derive exact WeChat split columns and composer coordinates for any window size."""
    win_x = float(bounds.get("x", 0.0))
    win_y = float(bounds.get("y", 0.0))
    win_w = max(320.0, float(bounds.get("width", 1029.0)))
    win_h = max(300.0, float(bounds.get("height", 640.0)))
    elements = ocr_elements or []

    # Check if an article reader pane is open on the right half (require top tab pill + strong article landmark)
    article_split_x = int(round(win_w * 0.56)) if win_w >= 880 else int(round(win_w))
    has_top_tab_pill = False
    strong_article_landmarks = 0
    for el in elements:
        box = el.get("bbox") or {}
        rx = float(box.get("x", 0.0))
        ry = float(box.get("y", 0.0))
        txt = str(el.get("text", "")).strip()
        if rx >= win_w * 0.52:
            if ry <= 56.0 and len(txt) >= 3:
                has_top_tab_pill = True
            elif any(k in txt for k in ("原创", "+关注", "阅读", "赞", "在看", "微信公众平台")):
                strong_article_landmarks += 1

    has_article_pane = bool(has_top_tab_pill and strong_article_landmarks >= 1 and win_w >= 880)
    session_split_x = int(round(_clamp(win_w * (0.205 if has_article_pane else 0.255), 195.0, 320.0)))
    chat_right_x = article_split_x if has_article_pane else int(round(win_w))
    composer_top_y = int(round(max(220.0, win_h - 140.0)))
    input_top_y = int(round(max(255.0, win_h - 102.0)))

    return {
        "windowBounds": {"x": win_x, "y": win_y, "width": win_w, "height": win_h},
        "hasArticlePane": has_article_pane,
        "sessionSplitX": session_split_x,
        "chatRightX": chat_right_x,
        "articleSplitX": article_split_x if has_article_pane else None,
        "composerTopY": composer_top_y,
        "inputTopY": input_top_y,
    }


def detect_active_view(
    bounds: Dict[str, Any],
    ocr_elements: Optional[List[Dict[str, Any]]] = None,
    window_title: str = "",
) -> str:
    """Classify the active WeChat view ID from geometry, title, and OCR cues."""
    geom = compute_layout_geometry(bounds, ocr_elements)
    elements = ocr_elements or []
    joined = " ".join(str(el.get("text", "")) for el in elements)

    if "设置" in window_title or ("账号与存储" in joined and "消息通知" in joined):
        return "settings_window"
    if "备份与恢复" in joined and "意见反馈" in joined and "锁定" in joined:
        return "more_menu_popup"
    if "查找聊天记录" in joined and ("消息免打扰" in joined or "置顶聊天" in joined):
        return "chat_info_drawer"
    if "全部收藏" in joined and "新建笔记" in joined:
        return "favorites_panel"
    if "通讯录管理" in joined or ("新的朋友" in joined and "群聊" in joined):
        return "contacts_directory"
    if geom["hasArticlePane"]:
        return "main_chat_with_article_reader"
    return "main_chat_split"


def resolve_target_coordinates(
    target_id: str,
    bounds: Dict[str, Any],
    ocr_elements: Optional[List[Dict[str, Any]]] = None,
    *,
    allow_preclick_fallback: bool = True,
) -> Dict[str, Any]:
    """Compute window-relative and absolute screen coordinates for a standardized UI target."""
    spec = WECHAT_UI_TARGETS.get(target_id)
    if not spec:
        return {"ok": False, "error": f"Unknown UI target: {target_id}"}

    geom = compute_layout_geometry(bounds, ocr_elements)
    wb = geom["windowBounds"]
    win_x, win_y, win_w, win_h = wb["x"], wb["y"], wb["width"], wb["height"]
    split_x = float(geom["sessionSplitX"])
    chat_right_x = float(geom["chatRightX"])
    anchor = spec["anchor"]
    mode = anchor["mode"]

    rel_x: Optional[float] = None
    rel_y: Optional[float] = None
    resolution_method = mode

    # Optional OCR-based refinement for visible menu/tab items
    elements = ocr_elements or []
    if mode in ("ocr_only", "two_step_menu"):
        hints = anchor.get("menuTexts") or []
        for el in elements:
            txt = str(el.get("text", "")).replace(" ", "")
            if any(h.replace(" ", "") in txt for h in hints):
                c = el.get("center") or {}
                if "x" in c and "y" in c:
                    rel_x = float(c["x"])
                    rel_y = float(c["y"])
                    resolution_method = "ocr_landmark_match"
                    break

    if rel_x is None:
        if mode == "fixed_top_left":
            rel_x = float(anchor["x"])
            rel_y = float(anchor["y"])
        elif mode == "fixed_bottom_left":
            rel_x = float(anchor["x"])
            rel_y = max(120.0, win_h - float(anchor["offsetBottom"]))
        elif mode == "session_search_box":
            rel_x = round((54.0 + split_x - 36.0) * 0.5, 1)
            rel_y = 28.0
        elif mode == "session_plus_btn":
            rel_x = max(70.0, split_x - 20.0)
            rel_y = 28.0
        elif mode == "chat_header_more":
            rel_x = max(split_x + 40.0, chat_right_x - 22.0)
            rel_y = 28.0
        elif mode == "composer_tool":
            slot = int(anchor.get("slot", 0))
            rel_x = min(chat_right_x - 24.0, split_x + 28.0 + slot * 34.0)
            rel_y = max(180.0, win_h - 122.0)
        elif mode == "chat_input_center":
            rel_x = round((split_x + chat_right_x) * 0.5, 1)
            rel_y = max(220.0, win_h - 52.0)
        elif mode == "article_tab_dots":
            art_x = float(geom.get("articleSplitX") or (win_w * 0.56))
            # Check OCR tab pill first
            tab_candidates = [
                el for el in elements
                if float(el.get("bbox", {}).get("x", 0)) >= art_x - 10
                and 8.0 <= float(el.get("bbox", {}).get("y", 999)) <= 56.0
                and len(str(el.get("text", "")).strip()) >= 3
            ]
            tab_candidates.sort(key=lambda e: float(e.get("bbox", {}).get("width", 0)), reverse=True)
            if tab_candidates:
                b = tab_candidates[0]["bbox"]
                rel_x = min(win_w - 55.0, float(b["x"]) + float(b["width"]) - 8.0)
                rel_y = float(b["y"]) + float(b["height"]) / 2.0
                resolution_method = "ocr_article_tab_pill"
            else:
                rel_x = min(win_w - 60.0, art_x + 225.0)
                rel_y = 29.0
        elif mode == "article_popout":
            rel_x = win_w - 28.0
            rel_y = 29.0
        elif mode == "article_body_center":
            art_x = float(geom.get("articleSplitX") or (win_w * 0.56))
            rel_x = round((art_x + win_w) * 0.5, 1)
            rel_y = round(win_h * 0.52, 1)
        elif mode == "two_step_menu" and allow_preclick_fallback:
            pre_id = anchor.get("preClick")
            if pre_id and pre_id != target_id:
                pre_res = resolve_target_coordinates(
                    pre_id,
                    bounds,
                    ocr_elements,
                    allow_preclick_fallback=False,
                )
                pre_rel = pre_res.get("relativePoint")
                if pre_rel:
                    rel_x = float(pre_rel["x"])
                    rel_y = float(pre_rel["y"])
                    resolution_method = "two_step_preclick_anchor"

    return {
        "ok": True,
        "targetId": target_id,
        "title": spec["title"],
        "category": spec["category"],
        "region": spec["region"],
        "expectedView": spec.get("expectedView", ""),
        "expectedAfter": spec.get("expectedAfter", ""),
        "resolutionMethod": resolution_method,
        "relativePoint": {"x": round(rel_x, 1), "y": round(rel_y, 1)} if rel_x is not None and rel_y is not None else None,
        "screenPoint": (
            {"x": round(win_x + rel_x, 1), "y": round(win_y + rel_y, 1)}
            if rel_x is not None and rel_y is not None
            else None
        ),
        "anchorSpec": anchor,
    }


class WeChatUIProtocolNavigator:
    """Protocolized UI awareness, live state detection, and safe semantic navigation."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def get_protocol_schema(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "schemaVersion": WECHAT_UI_SCHEMA_VERSION,
            "protocolName": "openbot-wechat-ui-protocol",
            "viewsCount": len(WECHAT_UI_VIEWS),
            "regionsCount": len(WECHAT_UI_REGIONS),
            "targetsCount": len(WECHAT_UI_TARGETS),
            "views": list(WECHAT_UI_VIEWS.values()),
            "regions": list(WECHAT_UI_REGIONS.values()),
            "targets": list(WECHAT_UI_TARGETS.values()),
        }

    def inspect_ui_state(self, *, refresh_ocr: bool = False) -> Dict[str, Any]:
        status = self.engine._run_native(["status"], 12.0)
        windows = status.get("windows") or []
        if not windows:
            return {
                "ok": False,
                "error": "no_visible_wechat_window",
                "wechatRunning": status.get("wechatRunning", False),
                "hidIdle": status.get("hidIdle", {}),
                "humanGuard": self.engine.human_guard.check_can_operate(status),
            }

        win = windows[0]
        bounds = win.get("bounds") or {}
        elements: List[Dict[str, Any]] = []
        ocr_used = False
        if refresh_ocr:
            snap_dir = self.engine.inspector.snapshots_dir
            snap_dir.mkdir(parents=True, exist_ok=True)
            cap = self.engine._run_native(
                ["capture-ocr", "--out", str(snap_dir / "ui_state_probe.png")],
                15.0,
            )
            elements = cap.get("elements") or []
            ocr_used = True

        geometry = compute_layout_geometry(bounds, elements)
        active_view = detect_active_view(bounds, elements, window_title=str(win.get("title") or ""))

        resolved_targets: Dict[str, Any] = {}
        for tid in WECHAT_UI_TARGETS:
            resolved_targets[tid] = resolve_target_coordinates(tid, bounds, elements)

        guard_state = self.engine.human_guard.check_can_operate(status)
        return {
            "ok": True,
            "schemaVersion": WECHAT_UI_SCHEMA_VERSION,
            "activeView": active_view,
            "viewMeta": WECHAT_UI_VIEWS.get(active_view, {}),
            "currentChatTitle": status.get("currentChatTitle", ""),
            "ocrUsed": ocr_used,
            "ocrElementCount": len(elements),
            "geometry": geometry,
            "resolvedTargets": resolved_targets,
            "hidIdle": status.get("hidIdle", {}),
            "humanGuard": guard_state,
        }

    def navigate_target(
        self,
        target_id: str,
        *,
        dry_run: bool = False,
        respect_human_guard: bool = True,
    ) -> Dict[str, Any]:
        clean_id = (target_id or "").strip()
        if clean_id not in WECHAT_UI_TARGETS:
            return {
                "ok": False,
                "error": f"Unknown UI target: {clean_id!r}",
                "availableTargets": sorted(WECHAT_UI_TARGETS.keys()),
            }

        if not dry_run and respect_human_guard:
            guard = self.engine.human_guard.check_can_operate()
            if not guard.get("canOperate", True):
                return {
                    "ok": False,
                    "blockedByHumanGuard": True,
                    "error": f"检测到人工正在操作鼠标/键盘，保留 {guard.get('remainingCooldownSeconds', 0)}s 空窗期，暂不执行 UI 点击。",
                    "humanGuard": guard,
                }

        status = self.engine._run_native(["status"], 12.0)
        windows = status.get("windows") or []
        if not windows:
            if dry_run:
                return {"ok": False, "error": "no_visible_wechat_window", "targetId": clean_id}
            act = self.engine._run_native(["activate"], 12.0)
            windows = act.get("windows") or []
            if not windows:
                return {"ok": False, "error": "no_visible_wechat_window", "targetId": clean_id}

        bounds = windows[0].get("bounds") or {}
        spec = WECHAT_UI_TARGETS[clean_id]
        anchor = spec["anchor"]

        # Resolve target point
        resolved = resolve_target_coordinates(clean_id, bounds)
        if dry_run:
            return {
                "ok": True,
                "dryRun": True,
                "targetId": clean_id,
                "targetSpec": spec,
                "resolved": resolved,
                "windowBounds": bounds,
            }

        # Activate WeChat before clicking
        self.engine._run_native(["activate"], 10.0)
        steps_executed: List[Dict[str, Any]] = []

        if anchor["mode"] == "two_step_menu":
            pre_id = anchor["preClick"]
            pre_res = resolve_target_coordinates(pre_id, bounds)
            sp = pre_res.get("screenPoint")
            if sp:
                self.engine._run_native(["click", "--x", str(sp["x"]), "--y", str(sp["y"])], 6.0)
                steps_executed.append({"step": pre_id, "click": sp})
                time.sleep(0.45)

            snap_dir = self.engine.inspector.snapshots_dir
            snap_dir.mkdir(parents=True, exist_ok=True)
            menu_ocr = self.engine._run_native(
                ["capture-ocr", "--out", str(snap_dir / f"ui_nav_{clean_id.replace('.', '_')}.png")],
                15.0,
            )
            els = menu_ocr.get("elements") or []
            resolved = resolve_target_coordinates(
                clean_id,
                bounds,
                els,
                allow_preclick_fallback=False,
            )
            sp2 = resolved.get("screenPoint")
            if not sp2:
                return {
                    "ok": False,
                    "targetId": clean_id,
                    "error": f"Menu item for {clean_id} not matched via Vision OCR.",
                    "stepsExecuted": steps_executed,
                }
            self.engine._run_native(["click", "--x", str(sp2["x"]), "--y", str(sp2["y"])], 6.0)
            steps_executed.append({"step": clean_id, "click": sp2, "method": resolved.get("resolutionMethod")})
        elif anchor["mode"] == "ocr_only":
            snap_dir = self.engine.inspector.snapshots_dir
            snap_dir.mkdir(parents=True, exist_ok=True)
            ocr = self.engine._run_native(
                ["capture-ocr", "--out", str(snap_dir / f"ui_nav_{clean_id.replace('.', '_')}.png")],
                15.0,
            )
            resolved = resolve_target_coordinates(clean_id, bounds, ocr.get("elements") or [])
            sp = resolved.get("screenPoint")
            if not sp:
                return {
                    "ok": False,
                    "targetId": clean_id,
                    "error": f"OCR could not locate {spec['title']} in current window.",
                }
            self.engine._run_native(["click", "--x", str(sp["x"]), "--y", str(sp["y"])], 6.0)
            steps_executed.append({"step": clean_id, "click": sp, "method": "ocr_landmark_match"})
        else:
            sp = resolved.get("screenPoint")
            if not sp:
                return {"ok": False, "targetId": clean_id, "error": "Could not resolve screenPoint."}
            self.engine._run_native(["click", "--x", str(sp["x"]), "--y", str(sp["y"])], 6.0)
            steps_executed.append({"step": clean_id, "click": sp, "method": resolved.get("resolutionMethod")})

        return {
            "ok": True,
            "dryRun": False,
            "targetId": clean_id,
            "targetSpec": spec,
            "stepsExecuted": steps_executed,
            "resolved": resolved,
        }
