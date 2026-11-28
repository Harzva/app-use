"""YoBot / wechat-rpa-bot-skill inspired Web Control Console HTML & UI renderer (v2.4.71)."""

from __future__ import annotations

import json
from typing import Any, Dict


WEB_CONSOLE_HTML = r"""<!DOCTYPE html>
<!-- WeChat Bot Web Control Console v2.4.71 -->
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="light dark" />
  <title>WeChat Bot · 微信工作台</title>
  <style>
    :root {
      --bg: #f4f6fb;
      --surface: #ffffff;
      --surface-soft: #f8fafd;
      --surface-hover: #f1f5fb;
      --text: #0f172a;
      --text-secondary: #475569;
      --text-muted: #64748b;
      --border: rgba(15, 23, 42, 0.08);
      --border-strong: rgba(15, 23, 42, 0.14);
      --primary: #07c160;
      --primary-hover: #06ad56;
      --primary-soft: rgba(7, 193, 96, 0.10);
      --accent: #2563eb;
      --accent-soft: rgba(37, 99, 235, 0.10);
      --special: #e11d48;
      --special-soft: rgba(225, 29, 72, 0.10);
      --vip: #d97706;
      --vip-soft: rgba(217, 119, 6, 0.11);
      --danger: #dc2626;
      --danger-soft: rgba(220, 38, 38, 0.10);
      --shadow-sm: 0 2px 10px rgba(15, 23, 42, 0.04);
      --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
      --radius-lg: 16px;
      --radius-md: 12px;
      --radius-sm: 8px;
      --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    }

    html[data-theme="dark"] {
      --bg: #11161f;
      --surface: #18202c;
      --surface-soft: #1e2736;
      --surface-hover: #243042;
      --text: #f1f5f9;
      --text-secondary: #cbd5e1;
      --text-muted: #94a3b8;
      --border: rgba(248, 250, 252, 0.09);
      --border-strong: rgba(248, 250, 252, 0.16);
      --primary: #10b981;
      --primary-hover: #059669;
      --primary-soft: rgba(16, 185, 129, 0.15);
      --accent: #60a5fa;
      --accent-soft: rgba(96, 165, 250, 0.14);
      --special: #fb7185;
      --special-soft: rgba(251, 113, 133, 0.16);
      --vip: #fbbf24;
      --vip-soft: rgba(251, 191, 36, 0.16);
      --danger: #f87171;
      --danger-soft: rgba(248, 113, 113, 0.16);
      --shadow-sm: 0 2px 10px rgba(0, 0, 0, 0.22);
      --shadow-md: 0 10px 28px rgba(0, 0, 0, 0.30);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    .container {
      max-width: 1380px;
      margin: 0 auto;
      padding: 20px 24px 56px;
    }

    /* Top Header */
    .topbar {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 18px 22px;
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .brand-icon {
      width: 44px;
      height: 44px;
      border-radius: 13px;
      background: linear-gradient(135deg, #07c160 0%, #059669 100%);
      display: grid;
      place-items: center;
      color: #fff;
      font-size: 22px;
      font-weight: 700;
      box-shadow: 0 6px 16px rgba(7, 193, 96, 0.24);
      flex-shrink: 0;
    }

    .brand-title {
      font-size: 18px;
      font-weight: 700;
      letter-spacing: -0.01em;
    }

    .brand-sub {
      font-size: 12.5px;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .status-pills {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 11px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      color: var(--text-secondary);
      white-space: nowrap;
    }

    .pill.ok { background: var(--primary-soft); color: var(--primary); border-color: transparent; }
    .pill.warn { background: var(--vip-soft); color: var(--vip); border-color: transparent; }
    .pill.special { background: var(--special-soft); color: var(--special); border-color: transparent; }
    .pill.danger { background: var(--danger-soft); color: var(--danger); border-color: transparent; }
    .pill.accent { background: var(--accent-soft); color: var(--accent); border-color: transparent; }

    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
    }

    /* Buttons & Inputs (clean soft surfaces per 2026-11-07 UI preference) */
    button, .btn {
      font-family: var(--font);
      font-size: 13px;
      font-weight: 600;
      border-radius: 10px;
      padding: 7px 14px;
      border: 1px solid var(--border);
      background: var(--surface-soft);
      color: var(--text);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 0.15s ease, transform 0.08s ease, box-shadow 0.15s ease;
    }

    button:hover { background: var(--surface-hover); }
    button:active { transform: translateY(1px); }
    button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    button.primary {
      background: var(--primary);
      color: #fff;
      border-color: transparent;
    }
    button.primary:hover { background: var(--primary-hover); }

    button.accent {
      background: var(--accent-soft);
      color: var(--accent);
      border-color: transparent;
    }
    button.accent:hover { filter: brightness(0.96); }

    button.special {
      background: var(--special-soft);
      color: var(--special);
      border-color: transparent;
    }

    button.vip {
      background: var(--vip-soft);
      color: var(--vip);
      border-color: transparent;
    }

    button.danger {
      background: var(--danger-soft);
      color: var(--danger);
      border-color: transparent;
    }

    button.ok {
      background: var(--primary-soft);
      color: var(--primary);
      border-color: transparent;
    }

    button.sm {
      padding: 5px 10px;
      font-size: 12px;
      border-radius: 8px;
    }

    input[type="text"], input[type="search"], input[type="password"], input[type="url"], input[type="number"], select, textarea, .input {
      font-family: var(--font);
      font-size: 13px;
      background: var(--surface-soft);
      color: var(--text);
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      padding: 8px 12px;
      width: 100%;
    }
    textarea { resize: vertical; min-height: 76px; }

    /* Omni Multi-Channel Checklist & Auth Cards */
    .omni-sys-strip {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    @media (max-width: 780px) { .omni-sys-strip { grid-template-columns: 1fr; } }
    .omni-sys-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 13px;
      border-radius: 12px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      font-size: 12.5px;
    }
    .omni-sys-item.is-ready { border-color: rgba(7, 193, 96, 0.35); background: var(--primary-soft); }
    .omni-sys-item.is-todo { border-color: rgba(217, 119, 6, 0.38); background: var(--vip-soft); }

    .omni-channel-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    @media (max-width: 1080px) { .omni-channel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 680px) { .omni-channel-grid { grid-template-columns: 1fr; } }
    .omni-ch-card {
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-top-width: 3px;
      border-radius: 14px;
      padding: 13px 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 10px;
      cursor: pointer;
      transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .omni-ch-card.status-ready { border-top-color: var(--primary); }
    .omni-ch-card.status-scan_qr, .omni-ch-card.status-need_launch { border-top-color: var(--vip); }
    .omni-ch-card.status-need_install { border-top-color: var(--accent); }
    .omni-ch-card.is-selected { box-shadow: 0 0 0 2px var(--accent-soft), var(--shadow-md); }
    .omni-ch-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
    .omni-ch-summary { font-size: 12px; color:var(--text-secondary); line-height: 1.5; }
    .omni-ch-actions { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 6px; border-top: 1px solid var(--border); }

    /* Universal App-Use & Any-Agent SOP Studio (#tab-appuse) */
    .appuse-app-strip {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 10px;
      max-height: 220px;
      overflow-y: auto;
      padding: 2px;
    }
    .appuse-app-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px 11px;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 4px;
      text-align: left;
    }
    .appuse-app-card:hover { border-color: var(--primary); }
    .appuse-app-card.is-selected {
      border-color: var(--primary);
      background: var(--primary-soft);
    }
    .appuse-step-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 360px;
      overflow-y: auto;
    }
    .appuse-step-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px 11px;
      font-size: 12.5px;
    }
    .appuse-sop-pre {
      white-space: pre-wrap;
      word-break: break-word;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif;
      font-size: 12.5px;
      line-height: 1.6;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      max-height: 360px;
      overflow-y: auto;
      margin: 0;
    }
    .wfagent-hero {
      border: 1px solid rgba(22, 119, 255, 0.28);
      background: linear-gradient(135deg, rgba(22, 119, 255, 0.05), rgba(16, 185, 129, 0.04));
    }
    .wfagent-round-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 12.5px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .wfagent-badge-pass { background: rgba(16, 185, 129, 0.14); color: #047857; border: 1px solid rgba(16, 185, 129, 0.35); }
    .wfagent-badge-fix { background: rgba(245, 158, 11, 0.14); color: #b45309; border: 1px solid rgba(245, 158, 11, 0.35); }
    .wfagent-badge-gate { background: rgba(220, 38, 38, 0.12); color: #b91c1c; border: 1px solid rgba(220, 38, 38, 0.3); }
    .wfagent-chat-box {
      background: var(--surface);
      border: 1px solid rgba(22, 119, 255, 0.22);
      border-radius: 12px;
      padding: 12px;
      margin-bottom: 12px;
    }
    .wfagent-chat-log {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 230px;
      overflow-y: auto;
      padding: 10px;
      border-radius: 10px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      margin-bottom: 8px;
    }
    .wfagent-chat-msg {
      max-width: 86%;
      padding: 8px 11px;
      border-radius: 10px;
      font-size: 12.5px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .wfagent-chat-msg.is-user {
      align-self: flex-end;
      background: var(--primary-soft);
      border: 1px solid rgba(7, 193, 96, 0.28);
      color: var(--text);
    }
    .wfagent-chat-msg.is-assistant {
      align-self: flex-start;
      background: var(--surface);
      border: 1px solid var(--border-strong);
      color: var(--text);
    }
    .wfagent-chat-options {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 8px;
    }
    .wfagent-edit-bar {
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 12px;
      padding: 11px 12px;
      margin-top: 10px;
    }
    .wfagent-edit-diff {
      margin-top: 8px;
      padding: 8px 10px;
      border-radius: 9px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      font-size: 12px;
      line-height: 1.55;
    }
    .wfagent-shadow-preview {
      margin-top: 6px;
      padding: 6px 8px;
      border-radius: 8px;
      background: rgba(245, 158, 11, 0.08);
      border: 1px solid rgba(245, 158, 11, 0.28);
      font-size: 11.5px;
      line-height: 1.5;
      color: var(--text-secondary);
    }
    .wfagent-direct-details {
      border: 1px dashed var(--border-strong);
      border-radius: 10px;
      padding: 8px 11px;
      margin-bottom: 10px;
      background: var(--surface);
    }
    .wfagent-direct-details > summary {
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      list-style: none;
    }
    .wfagent-direct-details[open] > summary {
      margin-bottom: 10px;
    }

    /* Magpie Multi-Provider & Model Grid */
    .provider-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .provider-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .model-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 12px;
    }
    .model-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 13px 15px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      box-shadow: var(--shadow-sm);
    }
    .model-card.is-active-model {
      border-color: rgba(7, 193, 96, 0.45);
      background: linear-gradient(180deg, rgba(7, 193, 96, 0.05), var(--surface));
    }

    /* KPI Grid */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }
    @media (max-width: 1120px) { .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
    @media (max-width: 640px) { .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

    .kpi-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      box-shadow: var(--shadow-sm);
    }
    .kpi-label { font-size: 12px; color: var(--text-muted); font-weight: 500; }
    .kpi-value { font-size: 23px; font-weight: 700; margin-top: 4px; letter-spacing: -0.02em; }
    .kpi-sub { font-size: 11.5px; color: var(--text-secondary); margin-top: 4px; }

    /* Auth Locked Banner */
    .auth-banner {
      background: var(--danger-soft);
      border: 1px solid rgba(220, 38, 38, 0.25);
      border-radius: var(--radius-md);
      padding: 16px 20px;
      margin-bottom: 18px;
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    .auth-banner.visible { display: flex; flex-wrap: wrap; }

    /* Tabs */
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 6px;
      margin-bottom: 18px;
      box-shadow: var(--shadow-sm);
    }

    .tab-btn {
      background: transparent;
      border-color: transparent;
      color: var(--text-secondary);
      padding: 8px 16px;
      border-radius: 10px;
      font-size: 13.5px;
    }
    .tab-btn.active {
      background: var(--surface-soft);
      color: var(--text);
      border-color: var(--border);
      box-shadow: var(--shadow-sm);
    }

    .tab-panel { display: none; }
    .tab-panel.active { display: block; }

    /* Cards & Layouts */
    .panel-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 18px 20px;
      box-shadow: var(--shadow-sm);
      margin-bottom: 16px;
    }

    .section-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    .section-title { font-size: 16px; font-weight: 700; margin: 0; }
    .section-desc { font-size: 12.5px; color: var(--text-muted); margin-top: 2px; }

    .grid-2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    @media (max-width: 960px) { .grid-2 { grid-template-columns: 1fr; } }
    @media (max-width: 520px) {
      .container { padding: 12px 10px 28px; }
      .topbar { padding: 10px 12px; gap: 8px; }
      .brand-title { font-size: 14.5px; }
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
      .metrics-row { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 8px; }
      .tab-btn { padding: 6px 10px; font-size: 12px; }
      .panel-card { padding: 12px; }
    }

    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }
    .filter-pills { display: flex; flex-wrap: wrap; gap: 6px; }
    .filter-pill {
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12.5px;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text-secondary);
    }
    .filter-pill.active {
      background: var(--text);
      color: var(--surface);
      border-color: transparent;
    }

    /* Global Time Slot Bars */
    .slot-bars {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    @media (max-width: 720px) { .slot-bars { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    .slot-item {
      background: var(--surface-soft);
      border-radius: 10px;
      padding: 10px 12px;
    }
    .slot-label { font-size: 12px; color: var(--text-secondary); display: flex; justify-content: space-between; }
    .progress-track {
      height: 7px;
      border-radius: 999px;
      background: rgba(148, 163, 184, 0.22);
      overflow: hidden;
      margin-top: 7px;
    }
    .progress-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--primary), #34d399);
    }

    /* Contact Cards */
    .contact-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 18px;
      box-shadow: var(--shadow-sm);
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: box-shadow 0.15s ease;
    }
    .contact-card.is-special-care {
      border-color: rgba(225, 29, 72, 0.26);
      box-shadow: 0 6px 22px rgba(225, 29, 72, 0.06);
    }
    .contact-card.is-vip {
      border-color: rgba(217, 119, 6, 0.26);
    }

    .contact-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .contact-name { font-size: 16.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .warmth-badge {
      padding: 4px 10px;
      border-radius: 10px;
      font-size: 12px;
      font-weight: 700;
      background: var(--surface-soft);
      color: var(--text);
      white-space: nowrap;
    }
    .warmth-hot { background: var(--special-soft); color: var(--special); }
    .warmth-mid { background: var(--primary-soft); color: var(--primary); }

    .metrics-row {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .mini-stat {
      background: var(--surface-soft);
      border-radius: 10px;
      padding: 8px 10px;
    }
    .mini-stat .k { font-size: 11px; color: var(--text-muted); }
    .mini-stat .v { font-size: 13px; font-weight: 600; margin-top: 2px; }

    .ratio-bar {
      height: 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      overflow: hidden;
      display: flex;
      margin-top: 6px;
    }
    .ratio-self { background: var(--primary); height: 100%; }
    .ratio-peer { background: var(--accent); height: 100%; }

    .chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip {
      font-size: 11.5px;
      padding: 3px 9px;
      border-radius: 999px;
      background: var(--surface-soft);
      color: var(--text-secondary);
    }

    .care-draft-box {
      background: var(--surface-soft);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 12.5px;
      color: var(--text-secondary);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .contact-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding-top: 6px;
      border-top: 1px solid var(--border);
    }

    .persona-inline {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      flex: 1;
      min-width: 210px;
    }
    .persona-inline select { padding: 5px 8px; font-size: 12px; }

    /* Timeline & Event Stream */
    .event-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-height: 540px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .event-item {
      background: var(--surface-soft);
      border-radius: 11px;
      padding: 11px 13px;
      font-size: 12.5px;
    }
    .event-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }

    .kb-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    @media (max-width: 860px) { .kb-list { grid-template-columns: 1fr; } }
    .kb-item {
      background: var(--surface-soft);
      border-radius: 12px;
      padding: 13px 15px;
    }

    pre.code-box {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 13px;
      font-size: 12px;
      overflow-x: auto;
      margin: 0;
      color: var(--text-secondary);
    }

    .snapshot-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 14px;
    }
    .snapshot-card {
      background: var(--surface-soft);
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    .snapshot-card img {
      width: 100%;
      height: 220px;
      object-fit: cover;
      object-position: top center;
      display: block;
      background: #0f172a;
    }
    .snapshot-meta { padding: 10px 12px; font-size: 12px; color: var(--text-secondary); word-break: break-all; }

    .toast {
      position: fixed;
      right: 22px;
      bottom: 22px;
      background: var(--text);
      color: var(--surface);
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 600;
      box-shadow: var(--shadow-md);
      z-index: 10050;
      opacity: 0;
      pointer-events: none;
      transform: translateY(10px);
      transition: all 0.2s ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    /* ===== WeChat Bot v2.4.71 · Astryx × Uncodixfy × Modern Web Guidance ===== */
    :root {
      color-scheme: light dark;
      --bg: #fafafa;
      --surface: #ffffff;
      --surface-soft: #f4f4f5;
      --surface-hover: #ececef;
      --text: #09090b;
      --text-primary: #09090b;
      --text-secondary: #52525b;
      --text-muted: #71717a;
      --border: #e4e4e7;
      --border-strong: #d4d4d8;
      --primary: #18181b;
      --primary-hover: #27272a;
      --primary-fg: #ffffff;
      --primary-soft: #f4f4f5;
      --accent: #18181b;
      --accent-soft: #f4f4f5;
      --ok: #10b981;
      --warn: #d97706;
      --danger: #dc2626;
      --bubble-user-bg: #18181b;
      --bubble-user-fg: #ffffff;
      --radius-md: 10px;
      --radius-sm: 8px;
      --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
      --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
      --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    }

    html[data-theme="dark"] {
      --bg: #09090b;
      --surface: #121215;
      --surface-soft: #18181b;
      --surface-hover: #27272a;
      --text: #fafafa;
      --text-primary: #fafafa;
      --text-secondary: #a1a1aa;
      --text-muted: #71717a;
      --border: #27272a;
      --border-strong: #3f3f46;
      --primary: #fafafa;
      --primary-hover: #e4e4e7;
      --primary-fg: #09090b;
      --primary-soft: #18181b;
      --accent: #e4e4e7;
      --accent-soft: #18181b;
      --bubble-user-bg: #27272a;
      --bubble-user-fg: #fafafa;
      --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.25);
    }

    body {
      margin: 0;
      background: var(--bg) !important;
      background-image: none !important;
      color: var(--text) !important;
      font-family: var(--font) !important;
      font-size: 14px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }

    .visually-hidden:where(:not(:focus-within, :active)) {
      position: absolute !important;
      clip-path: inset(50%) !important;
      overflow: hidden !important;
      width: 1px !important;
      height: 1px !important;
      margin: -1px !important;
      padding: 0 !important;
      border: 0 !important;
      white-space: nowrap !important;
    }

    /* Unified Top Horizontal Ribbon + Full-Height Left Chat Sidebar */
    .container {
      max-width: none !important;
      margin: 0 !important;
      padding: 0 !important;
      display: flex !important;
      flex-direction: column;
      min-height: 100dvh;
    }

    nav.tabs {
      position: sticky;
      top: 0;
      z-index: 50;
      width: 100%;
      height: auto !important;
      overflow: visible;
      display: flex !important;
      flex-direction: row !important;
      flex-wrap: wrap !important;
      align-items: center !important;
      gap: 4px !important;
      padding: 6px 14px !important;
      background: linear-gradient(180deg, color-mix(in srgb, var(--primary) 6%, var(--surface)) 0%, var(--surface) 100%) !important;
      border: 0 !important;
      border-bottom: 1px solid var(--border) !important;
      border-radius: 0 !important;
      box-shadow: none !important;
      margin: 0 !important;
    }

    .nav-brand {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 4px 12px 4px 4px;
      margin-right: 4px;
      border-right: 1px solid var(--border);
      font-size: 13.5px;
      font-weight: 650;
      letter-spacing: -0.01em;
      color: var(--text);
      white-space: nowrap;
    }

    .nav-dot {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--ok);
      flex-shrink: 0;
    }

    .nav-cta {
      width: auto;
      margin-bottom: 0;
      padding: 5px 10px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-strong);
      background: var(--surface-soft);
      color: var(--text);
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      text-align: center;
      transition: transform 140ms var(--ease-out), background-color 140ms var(--ease-out);
    }
    .nav-cta:hover { background: var(--surface-hover); }
    .nav-cta:active { transform: scale(0.97); }

    nav.tabs .tab-btn {
      position: relative;
      width: auto !important;
      text-align: left !important;
      justify-content: flex-start !important;
      padding: 5px 11px !important;
      border-radius: var(--radius-sm) !important;
      font-size: 13px !important;
      font-weight: 500 !important;
      background: transparent !important;
      color: var(--text-secondary) !important;
      border: 1px solid transparent !important;
      box-shadow: none !important;
      white-space: nowrap;
      transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out);
    }
    nav.tabs .tab-btn:hover {
      background: var(--surface-soft) !important;
      color: var(--text) !important;
    }
    nav.tabs .tab-btn.active {
      background: var(--surface-soft) !important;
      color: var(--text) !important;
      border-color: var(--border) !important;
      font-weight: 600 !important;
    }

    .nav-more {
      position: relative;
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }
    .nav-more summary {
      cursor: pointer;
      list-style: none;
      padding: 5px 10px;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
      border-radius: var(--radius-sm);
      white-space: nowrap;
      user-select: none;
    }
    .nav-more summary:hover,
    .nav-more[open] summary,
    .nav-more:has(.tab-btn.active) > summary {
      color: var(--text);
      background: var(--surface-soft);
    }
    .nav-more[open] summary { margin-bottom: 0; }
    .nav-more-list {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      min-width: 176px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      box-shadow: var(--shadow-md);
      padding: 6px;
      display: flex;
      flex-direction: column;
      gap: 2px;
      z-index: 70;
    }
    .nav-more-list .tab-btn {
      width: 100% !important;
    }

    .container > * {
      min-width: 0;
    }

    /* Compact Status & Window Tools Integrated into Top Ribbon */
    .topbar {
      margin-left: auto !important;
      display: flex !important;
      align-items: center !important;
      justify-content: flex-end !important;
      gap: 10px !important;
      padding: 0 !important;
      min-height: 0 !important;
      background: transparent !important;
      border: none !important;
      border-radius: 0 !important;
      box-shadow: none !important;
      margin-top: 0 !important;
      margin-bottom: 0 !important;
      flex-wrap: nowrap !important;
    }

    .tb-left {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex-wrap: nowrap;
    }
    .tb-pipeline {
      font-size: 12.5px;
      color: var(--text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .tb-pipeline strong { color: var(--text); font-weight: 500; }
    .status-pills {
      display: inline-flex !important;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .tb-right {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }

    .seg-group {
      display: inline-flex;
      padding: 2px;
      border-radius: var(--radius-sm);
      background: var(--surface-soft);
      border: 1px solid var(--border);
    }
    .seg-btn {
      border: none;
      background: transparent;
      color: var(--text-secondary);
      font-size: 12px;
      font-weight: 500;
      padding: 4px 9px;
      border-radius: 6px;
      cursor: pointer;
    }
    .seg-btn.active {
      background: var(--surface);
      color: var(--text);
      box-shadow: var(--shadow-sm);
    }

    .more-popover {
      margin: 0;
      padding: 6px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
      min-width: 220px;
    }
    .more-popover[popover]:is(:popover-open, .\:popover-open) {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .menu-item {
      display: flex;
      align-items: center;
      width: 100%;
      text-align: left;
      padding: 7px 10px;
      border: none;
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      font-size: 12.5px;
      font-weight: 500;
      text-decoration: none;
      cursor: pointer;
    }
    .menu-item:hover { background: var(--surface-soft); }

    .tab-panel {
      padding: 18px 24px 32px !important;
      max-width: 1120px;
      width: 100%;
      margin: 0 auto;
    }
    #tab-monitor.tab-panel {
      max-width: none !important;
      padding: 0 !important;
      margin: 0 !important;
    }

    /* Unified Calm Surfaces, Buttons, Inputs & Pill Restraint */
    .panel-card, .panel, .card, .kb-item, .field-box, .kpi-card {
      background: var(--surface) !important;
      border: 1px solid var(--border) !important;
      border-radius: var(--radius-md) !important;
      box-shadow: none !important;
      background-image: none !important;
    }

    .mini-stat {
      background: var(--surface-soft) !important;
      border: 1px solid var(--border) !important;
      border-radius: var(--radius-sm) !important;
    }

    button {
      font-family: var(--font);
      border-radius: var(--radius-sm) !important;
      transition: transform 140ms var(--ease-out), background-color 140ms var(--ease-out), border-color 140ms var(--ease-out);
    }
    button:active { transform: scale(0.97); }

    button.sm, button.action-btn, .btn-outline, .filter-pill {
      background: var(--surface) !important;
      color: var(--text) !important;
      border: 1px solid var(--border) !important;
      font-size: 12.5px;
      font-weight: 500;
      padding: 6px 11px;
      cursor: pointer;
    }
    button.sm:hover, .btn-outline:hover, .filter-pill:hover {
      background: var(--surface-soft) !important;
      border-color: var(--border-strong) !important;
    }
    .filter-pill.active {
      background: var(--surface-soft) !important;
      border-color: var(--text) !important;
      font-weight: 600 !important;
    }

    button.primary, .btn-solid, button.accent {
      background: var(--primary) !important;
      color: var(--primary-fg) !important;
      border: 1px solid var(--primary) !important;
      font-size: 12.5px;
      font-weight: 500;
      padding: 6px 13px;
      cursor: pointer;
    }
    button.primary:hover, .btn-solid:hover, button.accent:hover {
      background: var(--primary-hover) !important;
    }

    /* 知识库 tab：影刀式分类宫格 + 热门问题 chips */
    .kb-hero-hint { color: var(--text-secondary); font-size: 12.5px; margin: 10px 2px 6px; }
    .kb-chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
    .kb-chip {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 5px 13px; border-radius: 999px;
      background: var(--surface-soft); border: 1px solid var(--border);
      font-size: 12.5px; color: var(--text-secondary); cursor: pointer;
    }
    .kb-chip:hover { border-color: var(--primary); color: var(--text); }
    .kb-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 16px; }
    .kb-grid-item {
      background: var(--surface-soft); border: 1px solid var(--border);
      border-radius: 10px; padding: 12px 14px; cursor: pointer;
      display: flex; flex-direction: column; gap: 3px;
    }
    .kb-grid-item:hover { border-color: var(--primary); }
    .kb-grid-item.active { border-color: var(--primary); background: color-mix(in srgb, var(--primary) 8%, var(--surface-soft)); }
    .kb-grid-title { display: flex; align-items: center; gap: 7px; font-weight: 650; font-size: 13px; }
    .kb-grid-count { color: var(--primary); font-weight: 700; }
    .kb-grid-desc { font-size: 11.5px; color: var(--text-secondary); }

    /* 启动授权弹窗（影刀式：未授权自动弹出，逐项步骤条） */
    .perm-overlay {
      position: fixed; inset: 0; z-index: 9999;
      background: rgba(15, 18, 25, 0.55); backdrop-filter: blur(3px);
      display: none; align-items: center; justify-content: center;
    }
    .perm-overlay.visible { display: flex; }
    .perm-modal {
      width: min(560px, calc(100vw - 48px));
      background: var(--bg); border: 1px solid var(--border);
      border-radius: 14px; padding: 26px 28px;
      box-shadow: 0 18px 60px rgba(0,0,0,0.35);
      max-height: calc(100vh - 64px); overflow: auto;
    }
    .perm-modal h2 { margin: 0 0 4px; font-size: 17px; text-align: center; }
    .perm-modal .perm-sub { text-align: center; color: var(--text-secondary); font-size: 12.5px; margin-bottom: 16px; }
    .perm-steps { display: flex; align-items: center; justify-content: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
    .perm-step { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
    .perm-step .dot { width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
    .perm-step.done .dot { background: #16a34a; color: #fff; }
    .perm-step.todo .dot { background: #f59e0b; color: #fff; }
    .perm-step.done { color: var(--text); }
    .perm-step.todo { color: #b45309; }
    .perm-arrow { color: var(--text-muted); font-size: 12px; }
    .perm-modal-items { margin: 0 0 6px; }
    .perm-modal-actions { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin-top: 14px; }
    .perm-modal-actions .btn-solid { padding: 9px 22px; font-size: 14px; font-weight: 650; }
    .perm-modal-later { display: block; text-align: center; margin-top: 10px; color: var(--text-muted); font-size: 12px; cursor: pointer; }

    /* 启动权限引导面板（影刀式：未授权即见，逐项引导） */
    .perm-panel { border-left-width: 3px; }
    .perm-panel.ok { border-left-color: #86efac; }
    .perm-panel.warn { border-left-color: #f59e0b; }
    .perm-items { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
    .perm-item { background: var(--surface-soft); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
    .perm-item-head { display: flex; align-items: center; gap: 8px; font-weight: 650; font-size: 13.5px; }
    .perm-badge { margin-left: auto; font-size: 11.5px; padding: 2px 9px; border-radius: 999px; }
    .perm-badge.granted { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
    .perm-badge.denied { background: #fef3c7; color: #92400e; border: 1px solid #fbbf24; }
    .perm-purpose { font-size: 12px; color: var(--text-secondary); margin-top: 5px; }
    .perm-guide { font-size: 12px; color: var(--text-secondary); margin-top: 8px; line-height: 1.7; }
    .perm-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }

    /* 微信式聊天气泡流（对话首页） */
    .chat-bubble-wrap { display: flex; flex-direction: column; gap: 8px; }
    .chat-bubble-head { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; }
    .chat-bubble-stream {
      background: var(--surface-soft); border: 1px solid var(--border);
      border-radius: 12px; padding: 14px; min-height: 220px; max-height: 400px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 10px;
    }
    .bubble-row { display: flex; }
    .bubble-row.peer { align-items: flex-start; gap: 8px; }
    .bubble-row.self { justify-content: flex-end; }
    .chat-avatar { width: 24px; height: 24px; border-radius: 5px; object-fit: cover; flex: none; vertical-align: middle; }
    .chat-row-title { display: inline-flex; align-items: center; gap: 6px; min-inline-size: 0; max-inline-size: 100%; overflow: hidden; }
    .chat-row-title > span { min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    /* 托管自动回复的我方气泡带一点提示色边框，与人工发送区分 */
    .bubble.self.hosted { border: 1px solid color-mix(in srgb, var(--primary) 55%, transparent); }
    .bubble {
      max-width: 78%; padding: 8px 12px; border-radius: 14px;
      font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word;
    }
    .bubble.peer { background: var(--bg); border: 1px solid var(--border); color: var(--text); border-top-left-radius: 4px; }
    .bubble.self { background: var(--primary); color: var(--primary-fg); border-top-right-radius: 4px; }
    .bubble.peer.latest { outline: 1.5px dashed var(--primary); outline-offset: 2px; }
    .bubble-time { font-size: 10.5px; color: var(--text-muted); margin-top: 4px; }
    .bubble-time.warn { color: #b45309; }
    .bubble-sep { text-align: center; font-size: 11px; color: var(--text-muted); padding: 4px 0; }
    .bubble-row.system { justify-content: center; }
    .bubble.system-card {
      max-width: 92%; padding: 6px 12px; border-radius: 10px;
      background: transparent; border: 1px dashed var(--border);
      color: var(--text-secondary); font-size: 11.5px; line-height: 1.5;
      white-space: pre-wrap; word-break: break-word;
    }
    .chat-paste-details { font-size: 12.5px; }
    .chat-paste-details summary { cursor: pointer; color: var(--text-secondary); }
    .chat-paste-details textarea { margin-top: 6px; min-height: 56px; }

    /* 首页「一键托管好友」面板 */
    .hosting-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--primary);
      border-radius: 10px;
      padding: 10px 14px;
      margin-bottom: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .hosting-panel[hidden] { display: none !important; }
    .hosting-top-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
    .hosting-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; flex: 1 1 260px; }
    .hosting-badge {
      font-size: 13px; font-weight: 600;
      padding: 3px 10px; border-radius: 999px;
      background: var(--surface-soft); border: 1px solid var(--border);
      color: var(--text-secondary); white-space: nowrap;
    }
    .hosting-badge.on { background: #dcfce7; border-color: #86efac; color: #166534; }
    .hosting-badge.guard-ready { cursor: pointer; background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8; font-weight: 600; }
    .hosting-badge.guard-paused { cursor: pointer; background: #fef3c7; border-color: #fcd34d; color: #92400e; font-weight: 700; }
    .hosting-badge.guard-off { cursor: pointer; background: #fee2e2; border-color: #fca5a5; color: #991b1b; font-weight: 600; }
    .hosting-meta { color: var(--text-secondary); font-size: 12px; }
    .hosting-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    .hosting-btn { font-size: 13px !important; padding: 6px 14px !important; font-weight: 600 !important; }
    .hosting-picker summary { cursor: pointer; font-weight: 600; font-size: 13px; color: var(--text-secondary); }
    .hosting-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 8px 0; }
    .hosting-hint { color: var(--text-secondary); font-size: 12px; }
    .hosting-friend-list { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow: auto; }
    .hosting-friend-list li { border-bottom: 1px solid var(--border); }
    .hosting-friend-row { display: flex; align-items: center; gap: 8px; padding: 7px 4px; cursor: pointer; }
    .hosting-friend-row input[type="checkbox"] { width: auto; flex: none; }
    .hosting-friend-name { font-weight: 600; }
    .hosting-empty { color: var(--text-secondary); padding: 8px 4px; }

    .pill {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 7px !important;
      border-radius: 6px !important;
      font-size: 11.5px !important;
      font-weight: 500 !important;
      background: var(--surface-soft) !important;
      border: 1px solid var(--border) !important;
      color: var(--text-secondary) !important;
      box-shadow: none !important;
    }
    .pill.ok { color: #047857 !important; border-color: rgba(16, 185, 129, 0.32) !important; }
    html[data-theme="dark"] .pill.ok { color: #6ee7b7 !important; }
    .pill.danger { color: var(--danger) !important; border-color: rgba(220, 38, 38, 0.35) !important; }

    input[type="text"], input[type="search"], input[type="number"], input[type="url"], textarea, select {
      background: var(--surface) !important;
      color: var(--text) !important;
      border: 1px solid var(--border) !important;
      border-radius: var(--radius-sm) !important;
      padding: 7px 10px;
      font-size: 13.5px;
      font-family: var(--font);
    }

    textarea {
      field-sizing: content;
      width: 100%;
      min-block-size: 2.5lh;
      max-block-size: 8lh;
      resize: vertical;
      line-height: 1.5;
    }

    :is(:user-invalid, .user-invalid-fallback) {
      border-color: var(--danger) !important;
    }

    input:focus-visible, textarea:focus-visible, select:focus-visible, button:focus-visible, a:focus-visible, summary:focus-visible {
      outline: 2px solid var(--text) !important;
      outline-offset: 2px !important;
    }

    /* Two-Column Chat-First Workspace (#tab-monitor) */
    .chat-workspace {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }

    .chat-thread-list {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: calc(100vh - 96px);
      overflow-y: auto;
    }

    .chat-list-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 2px 4px 6px;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
      font-weight: 600;
    }

    .chat-thread-row {
      width: 100%;
      text-align: left;
      padding: 9px 10px;
      border-radius: var(--radius-sm) !important;
      border: 1px solid transparent !important;
      background: transparent !important;
      color: var(--text) !important;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .chat-thread-row:hover { background: var(--surface-soft) !important; }
    .chat-thread-row.active {
      background: var(--surface-soft) !important;
      border-color: var(--border) !important;
    }
    .chat-row-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      font-weight: 600;
    }
    .chat-row-meta {
      font-size: 11px;
      color: var(--text-muted);
      font-weight: 400;
    }
    .chat-row-snippet {
      font-size: 12px;
      color: var(--text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .chat-main-pane {
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-width: 820px;
    }

    .chat-context-bar {
      display: grid;
      grid-template-columns: minmax(110px, 0.9fr) 1fr 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
    }

    .chat-stream-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .chat-incoming-wrap {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 6px;
    }

    .chat-incoming-wrap textarea {
      max-width: 82%;
      background: var(--surface-soft) !important;
      border-radius: 12px !important;
      padding: 10px 13px;
    }

    .chat-preset-links {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 12px;
    }
    .link-btn {
      border: none !important;
      background: transparent !important;
      color: var(--text-muted) !important;
      padding: 2px 4px !important;
      font-size: 12px;
      cursor: pointer;
    }
    .link-btn:hover { color: var(--text) !important; text-decoration: underline; }

    .chat-ai-answer {
      font-size: 14px;
      line-height: 1.65;
      color: var(--text);
    }
    .chat-thinking-details {
      margin-top: 8px;
      font-size: 12.5px;
      color: var(--text-secondary);
    }
    .chat-thinking-details summary {
      cursor: pointer;
      color: var(--text-muted);
      font-weight: 500;
    }

    .chat-composer {
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .chat-composer textarea {
      border: none !important;
      padding: 4px 2px !important;
      background: transparent !important;
      outline: none;
    }
    .chat-composer-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      padding-top: 6px;
      border-top: 1px solid var(--border);
    }

    .chat-tools-drawer {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 10px 14px;
    }
    .chat-tools-drawer > summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
    }
    .chat-tools-drawer[open] > summary {
      margin-bottom: 12px;
      color: var(--text);
    }

    .care-kpi-details {
      margin-bottom: 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 10px 14px;
    }
    .care-kpi-details > summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      color: var(--text-secondary);
    }
    .care-kpi-details .kpi-grid {
      margin-top: 10px;
      margin-bottom: 0;
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
      }
    }

    @media (max-width: 900px) {
      .nav-brand, .nav-cta { display: none; }
      nav.tabs { padding: 6px 10px !important; }
      nav.tabs .tab-btn { flex: 0 0 auto; text-align: center !important; }
      .chat-workspace { grid-template-columns: 1fr; }
      .chat-thread-list { max-height: 220px; }
      .chat-context-bar { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 520px) {
      .topbar { padding: 0 !important; }
      .tb-pipeline { font-size: 11.5px; }
      .tab-panel { padding: 10px 10px 24px !important; }
      .chat-context-bar { grid-template-columns: 1fr; }
      .chat-incoming-wrap textarea { max-width: 100%; }
    }

    /* Shared workspace: top horizontal ribbon + leftmost conversation rail + quiet action surface. */
    .container { display: flex !important; flex-direction: column; min-height: 100dvh; }
    .tb-left { flex: 0 1 auto; }
    .tb-pipeline { min-width: 0; }
    .topbar .status-pills { display: none !important; }
    .nav-more { margin-top: 0; }
    .chat-workspace { container: conversation / inline-size; grid-template-columns: minmax(220px, 268px) minmax(0, 1fr); }
    .chat-thread-list { display: block; padding: 0; max-height: none; }
    .chat-thread-list > summary, .reply-settings > summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      padding: 10px 12px;
    }
    .chat-thread-list[open] > summary { border-bottom: 1px solid var(--border); }
    #monitorEventsList { padding: 6px; flex: 1; overflow-y: auto; }
    .chat-main-pane { width: 100%; min-width: 0; max-width: none; gap: 10px; }
    .chat-pane-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
    .conversation-recipient { display: inline-flex; align-items: center; gap: 8px; flex: 1 1 260px; max-width: 420px; margin-left: auto; }
    .conversation-recipient label, .chat-field-label { font-size: 13px; font-weight: 600; white-space: nowrap; }
    .reply-settings { border-top: 1px solid var(--border); }
    .reply-settings > summary { color: var(--text-secondary); padding-inline: 0; }
    .reply-settings .chat-context-bar { border: 0; padding: 0 0 6px; border-radius: 0; }
    .chat-stream-card { padding: 12px; }
    .chat-incoming-wrap { display: grid; gap: 6px; }
    .chat-incoming-wrap textarea { max-width: 100%; }
    .chat-field-label { color: var(--text-secondary); }
    .chat-composer { padding: 10px 12px; }
    .composer-actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .composer-mode { max-width: 100%; min-width: 0; }
    .chat-feedback { margin: 0; color: var(--text-muted); font-size: 12px; }
    .chat-tools-drawer > summary { font-weight: 400; }
    .stats-heading { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; justify-content: space-between; }
    .stats-heading h1 { font-size: 20px; margin: 0; }
    .stats-caption { color: var(--text-secondary); font-size: 13px; margin: 4px 0 14px; }
    .stats-sheet { margin: 0 0 12px; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface); }
    .stats-sheet h2 { font-size: 14px; margin: 0 0 8px; }
    .stat-rows { margin: 0; }
    .stat-rows > div {
      display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
      align-items: baseline; gap: 6px 12px; padding-block: 7px; border-top: 1px solid var(--border);
    }
    .stat-rows dt, .stats-meta { color: var(--text-secondary); font-size: 13px; }
    .stat-rows dd { margin: 0; font-size: 13px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .stat-rows strong { margin-inline-end: 6px; color: var(--text); }
    .stats-time { display: grid; gap: 7px; }
    .stats-time-row { display: grid; grid-template-columns: minmax(0, 152px) minmax(24px, 1fr) auto; align-items: center; gap: 8px; font-size: 12px; }
    .stats-time-row meter { width: 100%; height: 8px; accent-color: var(--text-secondary); }
    .stats-event-list { padding: 0; margin: 0; list-style: none; }
    .stats-event-list li { padding: 7px 0; border-top: 1px solid var(--border); overflow-wrap: anywhere; font-size: 13px; }
    .stats-event-list time { color: var(--text-secondary); margin-inline-end: 6px; }
    .priority-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-block: 6px 10px; }
    .priority-people { padding: 0; margin: 0; list-style: none; }
    .priority-people li { border-top: 1px solid var(--border); }
    .priority-person {
      width: 100%; display: flex; align-items: center; justify-content: space-between;
      text-align: start; gap: 6px 12px; flex-wrap: wrap; padding: 8px 2px;
      background: transparent !important; border: 0 !important;
    }
    .priority-person:hover { background: var(--surface-soft) !important; }
    .priority-person > span:first-child { min-width: 0; overflow-wrap: anywhere; font-weight: 600; }
    .priority-person { min-block-size: 36px; }
    .contact-heading { overflow-wrap: anywhere; }
    .contact-heading:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
    #tab-care [hidden] { display: none !important; }
    #contactsGrid.contact-detail { grid-template-columns: minmax(0, 1fr); }
    .contact-events h2 { font-size: 14px; margin-block: 4px 8px; }
    .contact-direction { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; font-size: 12px; color: var(--text-secondary); }
    .background-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 6px 0 10px; }
    .text-action { padding: 4px 7px; border-color: transparent !important; }
    .status-link { white-space: nowrap; }
    .topbar-more { position: relative; }
    .topbar-more > summary {
      list-style: none; cursor: pointer; padding: 4px 9px;
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      color: var(--text); font-size: 12.5px; white-space: nowrap;
    }
    .topbar-more > summary::-webkit-details-marker { display: none; }
    .topbar-more[open] > .more-popover {
      display: grid; position: absolute; inset: calc(100% + 6px) 0 auto auto;
      gap: 2px; z-index: 70; width: min(240px, calc(100vw - 28px));
    }

    @container conversation (max-width: 510px) {
      .chat-context-bar { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
      .composer-actions { width: 100%; }
      .composer-actions button { flex: 1; }
    }
    /* Daily workspace: one quiet action surface and a separate leftmost list of recent conversations. */
    :root {
      --work-rail: #f4f5f2;
      --work-selection: #e6efe8;
      --work-pine: #27593f;
      --work-on-pine: #ffffff;
      --work-muted: #535c55;
      --work-divider: #dce2da;
      --work-alert: #874022;
      --work-focus: #326649;
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --work-rail: #171c19;
      --work-selection: #293b31;
      --work-pine: #acd9b9;
      --work-on-pine: #14281c;
      --work-muted: #b9c2ba;
      --work-divider: #3b493f;
      --work-alert: #f3b393;
      --work-focus: #a5d9b3;
    }
    html[data-theme="light"] { color-scheme: light; }
    @media (prefers-color-scheme: dark) {
      html:not([data-theme]) { color-scheme: dark; }
    }
    nav.tabs {
      background: linear-gradient(180deg, color-mix(in srgb, var(--work-pine) 6%, var(--surface)) 0%, var(--surface) 100%) !important;
      border-bottom-color: var(--work-divider) !important;
    }
    nav.tabs .workspace-link { display: inline-flex; text-decoration: none; }
    nav.tabs .tab-btn.active { background: var(--work-selection) !important; color: var(--work-pine) !important; border-color: color-mix(in srgb, var(--work-pine) 25%, transparent) !important; }
    nav.tabs .nav-dot { background: var(--work-pine); }
    nav.tabs > :is(button,a), .nav-more > summary { min-block-size: 32px; }
    nav.tabs .tab-btn:focus-visible,
    .topbar :is(summary,button):focus-visible,
    #tab-monitor :is(button,summary,input,textarea,select):focus-visible {
      outline: 2px solid var(--work-focus) !important;
      outline-offset: 2px;
    }
    .topbar-more[open] > .more-popover { box-shadow: 0 3px 10px rgb(0 0 0 / 12%); }
    .topbar-more > summary { display: flex; align-items: center; min-block-size: 30px; }
    .home-connection { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--work-muted); white-space: nowrap; }
    .home-connection::before {
      content: ""; inline-size: 7px; block-size: 7px; flex: none;
      border: 1px solid currentColor; border-radius: 50%;
    }
    .home-connection[data-state="ready"] { color: var(--work-pine); }
    .home-connection[data-state="ready"]::before { background: currentColor; }
    .home-connection[data-state="limited"] { color: var(--work-alert); }
    #tab-monitor.tab-panel { padding: 0 !important; max-width: none !important; }
    #tab-monitor .chat-workspace {
      display: grid;
      grid-template-columns: minmax(220px, 268px) minmax(0, 1fr);
      gap: 0;
      align-items: stretch;
      min-height: calc(100dvh - 46px);
    }
    .home-conversations {
      min-inline-size: 0;
      position: sticky;
      top: 46px;
      height: calc(100dvh - 46px);
      overflow-y: auto;
      background: var(--work-rail);
      border-right: 1px solid var(--work-divider);
      display: flex;
      flex-direction: column;
    }
    #tab-monitor .chat-thread-list {
      background: transparent;
      border: 0;
      border-radius: 0;
      display: flex;
      flex-direction: column;
      flex: 1;
    }
    #tab-monitor .chat-thread-list > summary { padding: 10px 12px; border-bottom: 1px solid var(--work-divider); }
    #tab-monitor .chat-thread-list[open] > summary { border-color: var(--work-divider); }
    .conversation-count { margin-inline-start: 4px; color: var(--work-muted); font-weight: 400; font-variant-numeric: tabular-nums; }
    .home-empty { margin: 0; padding: 10px 7px; color: var(--work-muted); font-size: 13px; overflow-wrap: anywhere; }
    #tab-monitor .chat-list-head {
      display: grid; gap: 2px; justify-items: start;
      padding: 8px 10px 10px; border: 0; border-top: 1px solid var(--work-divider);
      margin-top: auto;
    }
    #tab-monitor .chat-list-head button { min-height: 29px; color: var(--work-muted) !important; }
    #tab-monitor .chat-thread-row + .chat-thread-row { border-block-start: 1px solid var(--work-divider) !important; }
    #tab-monitor .chat-thread-row { border-radius: 6px !important; min-height: 50px; }
    #tab-monitor .chat-thread-row[aria-pressed="true"] { background: var(--work-selection) !important; color: var(--work-pine) !important; }
    #tab-monitor .chat-row-top { inline-size: 100%; min-inline-size: 0; }
    #tab-monitor .chat-row-top > span:first-child,
    #tab-monitor .chat-row-snippet { min-inline-size: 0; max-inline-size: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #tab-monitor .chat-row-meta { flex: none; color: var(--work-muted); font-variant-numeric: tabular-nums; }
    #tab-monitor .chat-row-snippet, #tab-monitor .chat-feedback { color: var(--work-muted); }
    #tab-monitor .chat-main-pane { gap: 10px; padding: 14px 20px 24px; min-width: 0; max-width: 960px; }
    .conversation-heading { margin: 0; font-size: 18px; line-height: 1.3; font-weight: 650; }
    #tab-monitor :is(.chat-stream-card,.chat-composer) {
      background: transparent;
      border: 0;
      padding: 0;
    }
    #tab-monitor :is(#previewTarget, #previewIncoming, #sendText) {
      box-sizing: border-box;
      border: 1px solid var(--work-divider) !important;
      border-radius: 6px !important;
      background: var(--surface) !important;
      color: var(--text) !important;
      font-size: 14px !important;
      padding: 7px 10px !important;
      inline-size: 100%;
      max-inline-size: 100%;
      min-inline-size: 0;
    }
    #tab-monitor :is(#previewIncoming,#sendText) { min-block-size: 72px; resize: vertical; }
    #tab-monitor .chat-field-label, #tab-monitor .conversation-recipient label { color: var(--text); }
    #tab-monitor .chat-composer-bar { display: grid; justify-content: stretch; border-top: 0; padding: 1px 0 0; gap: 5px; }
    #tab-monitor .composer-actions { margin-block-end: 2px; }
    #tab-monitor .composer-actions button { min-block-size: 36px; }
    #tab-monitor :is(#generateDraftBtn, #saveDraftBtn) { transition-property: transform; }
    #tab-monitor .composer-actions .btn-solid:not([data-unavailable]) {
      color: var(--work-on-pine) !important; background: var(--work-pine) !important;
      border-color: var(--work-pine) !important;
    }
    #tab-monitor #generateDraftBtn[aria-disabled="true"] { opacity: .8; cursor: wait; }
    #tab-monitor #saveDraftBtn[data-unavailable],
    #tab-monitor #generateDraftBtn[data-unavailable],
    #tab-monitor #sendActionLabel[data-unavailable] {
      background: var(--work-rail) !important; border-color: var(--work-divider) !important;
      color: var(--work-muted) !important; cursor: not-allowed;
    }
    .saved-draft-feedback { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
    .saved-draft-feedback p { margin: 0; color: var(--work-muted); overflow-wrap: anywhere; }
    .saved-draft-feedback p[data-error] { color: var(--work-alert); }
    #openSavedTask { padding: 2px 0; color: var(--work-pine); text-underline-offset: 3px; }
    #openSavedTask:focus-visible { outline: 2px solid var(--work-focus); outline-offset: 3px; }
    #openSavedTask[hidden] { display: none !important; }
    #tab-monitor #saveDraftBtn[aria-busy="true"] { cursor: wait; }
    #homeRetry { min-block-size: 29px; }
    #homeRetry[hidden] { display: none !important; }
    .draft-status { color: var(--work-muted); margin: 2px 0 0; overflow-wrap: anywhere; }
    .draft-status[data-tone="error"] { color: var(--work-alert); }
    .draft-suggestion { padding: 9px 12px; border-left: 2px solid var(--work-focus); background: var(--work-rail); }
    .draft-suggestion p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    #confirmSendDialog {
      inline-size: min(360px, calc(100vw - 32px)); padding: 18px;
      color: var(--text); background: var(--surface);
      border: 1px solid var(--work-divider); border-radius: 8px;
    }
    #confirmSendDialog::backdrop { background: rgb(0 0 0 / 50%); }
    .send-confirm-form h2 { margin: 0; font-size: 17px; }
    .send-confirm-form p { color: var(--work-muted); overflow-wrap: anywhere; }
    #confirmSendExcerpt {
      margin: 0 0 14px; border-inline-start: 2px solid var(--work-divider);
      padding-inline-start: 8px; color: var(--work-muted); white-space: pre-wrap; overflow-wrap: anywhere;
    }
    .send-confirm-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
    .send-confirm-actions button { min-block-size: 36px; }
    .send-receipt { padding: 10px 0; border-block: 1px solid var(--work-divider); }
    .send-receipt p { margin: 0 0 4px; }
    .send-receipt details { color: var(--work-muted); }
    #tab-monitor .chat-tools-drawer { padding: 9px 0; border: 0; border-top: 1px solid var(--work-divider); background: transparent; }
    .chat-tools-drawer .grid-2 > * { min-inline-size: 0; }
    @media (max-width: 900px) {
      nav.tabs {
        padding: 5px 10px !important;
        gap: 4px !important;
      }
      nav.tabs .nav-brand, nav.tabs .nav-cta { display: none; }
      nav.tabs > .tab-btn, .nav-more > summary { padding: 5px 8px !important; font-size: 12.5px !important; }
      #tab-monitor.tab-panel { padding: 0 !important; }
      #tab-monitor .chat-workspace { grid-template-columns: minmax(0,1fr); min-height: auto; }
      .home-conversations { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--work-divider); }
      #tab-monitor .chat-main-pane { padding: 12px 14px 20px; }
      #tab-monitor .chat-thread-list:not([open]) > summary { min-block-size: 39px; }
    }
    @media (max-width: 430px) {
      #tab-monitor .chat-context-bar, #tab-monitor .chat-tools-drawer .grid-2 { grid-template-columns: minmax(0,1fr); }
    }

    /* BotStudio-Inspired Workbench Layout, Viewport-Locked Chat & Settings Center (v2.4.71) */
    nav.tabs {
      padding: 4px 12px !important;
      gap: 3px !important;
      min-height: 40px;
      flex-shrink: 0;
    }
    .bs-view-switcher {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 2px;
      padding: 3px;
      margin: 8px 8px 4px;
      border: 1px solid var(--work-divider);
      border-radius: 9px;
      background: color-mix(in srgb, var(--work-divider) 42%, var(--surface-soft));
      flex-shrink: 0;
    }
    .bs-view-tab {
      min-width: 0;
      min-height: 28px;
      padding: 4px 4px !important;
      border: 0 !important;
      border-radius: 6px !important;
      background: transparent !important;
      color: var(--work-muted) !important;
      font-size: 12px !important;
      font-weight: 500 !important;
      justify-content: center !important;
      white-space: nowrap;
      cursor: pointer;
    }
    .bs-view-tab:hover { color: var(--work-pine) !important; }
    .bs-view-tab.active, .bs-view-tab[aria-selected="true"] {
      color: var(--text) !important;
      background: var(--surface) !important;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
      font-weight: 600 !important;
    }
    #tab-monitor .chat-workspace {
      grid-template-columns: minmax(220px, 256px) minmax(0, 1fr);
      height: calc(100dvh - 41px);
      min-height: calc(100dvh - 41px);
      overflow: hidden;
    }
    #tab-monitor .home-conversations {
      position: static;
      height: 100%;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    [hidden] { display: none !important; }
    #tab-monitor .chat-thread-list {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      display: block;
    }
    #tab-monitor .chat-thread-list > summary { padding: 7px 12px; font-size: 12.5px; }
    #tab-monitor .chat-thread-list > summary.thread-summary-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      list-style: none;
      cursor: pointer;
    }
    #tab-monitor .chat-thread-list > summary.thread-summary-row::-webkit-details-marker { display: none; }
    .thread-plus-btn {
      width: 22px;
      height: 22px;
      min-height: 22px !important;
      padding: 0 !important;
      border-radius: 6px !important;
      border: 1px solid color-mix(in srgb, var(--work-pine) 35%, var(--border)) !important;
      background: color-mix(in srgb, var(--work-pine) 10%, var(--surface)) !important;
      color: var(--work-pine) !important;
      font-size: 14px !important;
      font-weight: 700 !important;
      line-height: 1 !important;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .thread-plus-btn:hover {
      background: var(--work-pine) !important;
      color: #fff !important;
    }
    .sidebar-watch-panel {
      flex-shrink: 0;
      margin: 4px 8px 4px;
      padding: 8px 9px;
      border: 1px solid var(--work-divider);
      border-radius: 9px;
      background: var(--surface);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .sidebar-watch-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      font-size: 12px;
      font-weight: 650;
      color: var(--text);
    }
    .sidebar-add-watch-btn {
      padding: 2px 8px !important;
      min-height: 24px !important;
      font-size: 11.5px !important;
      font-weight: 600 !important;
      border-radius: 6px !important;
      border-color: color-mix(in srgb, var(--work-pine) 40%, var(--border)) !important;
      color: var(--work-pine) !important;
      background: color-mix(in srgb, var(--work-pine) 9%, var(--surface)) !important;
      white-space: nowrap;
    }
    .sidebar-add-watch-btn:hover,
    .sidebar-add-watch-btn[aria-expanded="true"] {
      background: var(--work-pine) !important;
      color: #fff !important;
      border-color: var(--work-pine) !important;
    }
    .sidebar-watched-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      max-height: 74px;
      overflow-y: auto;
    }
    .watch-chip {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      max-width: 100%;
      padding: 2px 6px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--ok) 38%, var(--border));
      background: color-mix(in srgb, var(--ok) 11%, var(--surface));
      color: var(--text);
      font-size: 11.5px;
      line-height: 1.3;
    }
    .watch-chip.is-paused {
      border-color: var(--border);
      background: var(--surface-soft);
      color: var(--text-muted);
    }
    .watch-chip-name {
      background: transparent !important;
      border: 0 !important;
      padding: 0 !important;
      min-height: 0 !important;
      color: inherit !important;
      font-size: 11.5px !important;
      font-weight: 500 !important;
      max-width: 145px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      cursor: pointer;
    }
    .watch-chip-remove {
      background: transparent !important;
      border: 0 !important;
      padding: 0 2px !important;
      min-height: 0 !important;
      color: var(--text-muted) !important;
      font-size: 12px !important;
      line-height: 1 !important;
      cursor: pointer;
      border-radius: 999px !important;
    }
    .watch-chip-remove:hover { color: var(--danger) !important; }
    .sidebar-watch-drawer {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 6px;
      border-top: 1px dashed var(--work-divider);
    }
    .sidebar-watch-input-row {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .sidebar-watch-input-row input {
      width: 100%;
      box-sizing: border-box;
      padding: 5px 8px !important;
      font-size: 12px !important;
      min-height: 28px !important;
      border-radius: 6px !important;
    }
    .sidebar-watch-input-row button {
      width: 100%;
      min-height: 28px !important;
      padding: 4px 8px !important;
      font-size: 12px !important;
    }
    .sidebar-watch-autostart {
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 11.5px;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .sidebar-watch-autostart input { width: auto !important; margin: 0; }
    .sidebar-watch-candidates-label { font-size: 11px; color: var(--text-muted); margin-bottom: 3px; }
    .sidebar-watch-candidates { display: flex; flex-wrap: wrap; gap: 4px; max-height: 62px; overflow-y: auto; }
    .watch-cand-btn {
      padding: 2px 7px !important;
      min-height: 22px !important;
      font-size: 11px !important;
      border-radius: 999px !important;
      border: 1px solid var(--border) !important;
      background: var(--surface-soft) !important;
      color: var(--text-secondary) !important;
    }
    .watch-cand-btn:hover {
      border-color: var(--work-pine) !important;
      color: var(--work-pine) !important;
      background: color-mix(in srgb, var(--work-pine) 8%, var(--surface)) !important;
    }
    .hosting-quick-add {
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 6px 0 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }
    .hosting-quick-add input {
      flex: 1 1 auto;
      min-width: 0;
      padding: 5px 8px !important;
      font-size: 12px !important;
      min-height: 29px !important;
    }
    .hosting-quick-add button {
      flex-shrink: 0;
      padding: 4px 10px !important;
      font-size: 12px !important;
      min-height: 29px !important;
    }
    #tab-monitor #monitorEventsList {
      padding: 4px 6px;
    }
    #tab-monitor .chat-list-head {
      flex-shrink: 0;
      display: flex !important;
      flex-direction: row !important;
      align-items: center !important;
      justify-content: space-between !important;
      gap: 6px;
      padding: 8px 10px;
      border-top: 1px solid var(--work-divider);
      margin-top: auto;
      background: color-mix(in srgb, var(--work-rail) 88%, var(--surface));
    }
    #tab-monitor .chat-list-head .chat-feedback { display: none; }
    #tab-monitor .chat-main-pane {
      height: 100%;
      min-height: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 8px 18px 10px !important;
      max-width: none !important;
    }
    #tab-monitor #hostingPanel {
      position: relative;
      flex-shrink: 0;
      padding: 6px 12px !important;
      border-radius: 9px;
      gap: 0;
      overflow: visible;
    }
    #tab-monitor .hosting-top-row {
      flex-wrap: nowrap;
      gap: 8px;
    }
    #tab-monitor .hosting-status {
      flex: 1 1 160px;
      min-width: 0;
      flex-wrap: nowrap;
      overflow: hidden;
    }
    #tab-monitor .hosting-badge { font-size: 12px; padding: 2px 9px; flex-shrink: 0; }
    #tab-monitor .hosting-meta {
      flex: 1 1 auto;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 11.5px;
    }
    #tab-monitor .hosting-actions { flex-wrap: nowrap; flex-shrink: 0; gap: 5px; }
    #tab-monitor .hosting-actions > button, #tab-monitor #appWindowPickerBtn { padding: 4px 9px !important; font-size: 12px !important; min-height: 28px; }
    #tab-monitor .hosting-picker { position: static; flex-shrink: 0; }
    #tab-monitor .hosting-picker > summary {
      font-size: 12px; font-weight: 500;
      padding: 3px 8px; border: 1px solid var(--border); border-radius: 7px;
      background: var(--surface-soft); white-space: nowrap; list-style: none;
    }
    #tab-monitor .hosting-picker > summary::-webkit-details-marker { display: none; }
    #tab-monitor .hosting-picker-popover {
      display: none;
    }
    #tab-monitor .hosting-picker[open] > .hosting-picker-popover {
      display: block;
      position: absolute;
      top: calc(100% + 5px);
      right: 10px;
      z-index: 68;
      width: min(380px, calc(100vw - 48px));
      max-height: 300px;
      overflow-y: auto;
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.16);
      padding: 10px 12px;
    }
    #tab-monitor .chat-pane-head {
      flex-shrink: 0;
      min-height: 32px;
      gap: 10px;
      padding: 0;
    }
    #tab-monitor .conversation-heading { font-size: 15.5px; }
    #tab-monitor .conversation-recipient { flex: 0 1 380px; max-width: 420px; gap: 6px; }
    #tab-monitor #previewTarget { padding: 4px 9px !important; font-size: 13px !important; }
    #tab-monitor .chat-stream-card {
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    #tab-monitor .chat-bubble-wrap {
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 5px;
      overflow: hidden;
    }
    #tab-monitor .chat-bubble-head { flex-shrink: 0; font-size: 12.5px; }
    #tab-monitor #chatBubbleStream {
      flex: 1 1 auto;
      min-height: 110px;
      max-height: none !important;
      overflow-y: auto;
      padding: 12px 14px;
    }
    #tab-monitor .chat-paste-details { flex-shrink: 0; }
    #tab-monitor .chat-paste-details[open] { max-height: 108px; overflow-y: auto; }
    #tab-monitor .chat-composer {
      flex-shrink: 0;
      background: var(--work-rail) !important;
      border: 1px solid var(--work-divider) !important;
      border-radius: 10px !important;
      padding: 7px 11px !important;
      gap: 5px;
    }
    .composer-head-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    #tab-monitor #sendText {
      min-block-size: 46px !important;
      max-block-size: 88px !important;
      padding: 6px 9px !important;
      background: var(--surface) !important;
      font-size: 13.5px !important;
    }
    #tab-monitor .chat-composer-bar { gap: 4px; padding-top: 0; }
    #tab-monitor .composer-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    #tab-monitor .composer-actions button { min-block-size: 31px !important; padding: 4px 11px !important; font-size: 12.5px !important; }
    #tab-monitor #quickAiAssistResult:not([hidden]),
    #tab-monitor #replyPreviewResult:not([hidden]) {
      max-height: 152px;
      overflow-y: auto;
      font-size: 12.5px;
      line-height: 1.5;
      padding: 6px 10px;
      background: var(--surface);
      border: 1px solid var(--work-divider);
      border-radius: 8px;
      margin-top: 2px;
    }
    #tab-monitor .reply-settings { flex-shrink: 0; border-top: 1px solid var(--work-divider); }
    #tab-monitor .reply-settings > summary { padding: 5px 0; font-size: 12px; }
    #tab-monitor .chat-tools-drawer { flex-shrink: 0; padding: 5px 0 !important; }
    #tab-monitor .chat-tools-drawer[open] { max-height: 250px; overflow-y: auto; }
    #tab-monitor .chat-tools-drawer > summary { font-size: 12px; }

    /* BotStudio Unified Settings Modal (#settingsOverlay) */
    .settings-modal {
      width: min(760px, calc(100vw - 40px)) !important;
      max-height: min(590px, calc(100vh - 48px)) !important;
      padding: 0 !important;
      display: flex;
      flex-direction: column;
      overflow: hidden !important;
    }
    .settings-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 13px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-soft);
      flex-shrink: 0;
    }
    .settings-head h2 { margin: 0 !important; text-align: left !important; font-size: 15.5px !important; }
    .settings-shell {
      display: grid;
      grid-template-columns: 168px minmax(0, 1fr);
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }
    .settings-rail {
      padding: 10px 8px;
      border-right: 1px solid var(--border);
      background: var(--work-rail);
      display: flex;
      flex-direction: column;
      gap: 3px;
      overflow-y: auto;
    }
    .settings-nav-btn {
      width: 100%;
      justify-content: flex-start !important;
      padding: 7px 10px !important;
      border: 0 !important;
      border-radius: 7px !important;
      background: transparent !important;
      color: var(--text-secondary) !important;
      font-size: 12.5px !important;
      font-weight: 500 !important;
    }
    .settings-nav-btn:hover { background: var(--surface-hover) !important; color: var(--text) !important; }
    .settings-nav-btn.active {
      background: var(--surface) !important;
      color: var(--work-pine) !important;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
      font-weight: 600 !important;
    }
    .settings-body {
      padding: 16px 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .settings-section { display: none; flex-direction: column; gap: 12px; }
    .settings-section.active { display: flex; }
    .settings-card {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .settings-card h3 { margin: 0; font-size: 13.5px; }
    .settings-row { display: grid; grid-template-columns: 120px minmax(0, 1fr); align-items: center; gap: 10px; font-size: 13px; }

    /* Call Brief Pre-Call Advisor Modal (#callBriefOverlay) */
    .call-brief-modal {
      width: min(920px, calc(100vw - 32px)) !important;
      max-height: min(88vh, 840px) !important;
      padding: 0 !important;
      display: flex;
      flex-direction: column;
      overflow: hidden !important;
    }
    .call-brief-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      flex-shrink: 0;
    }
    .call-brief-goals {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
    }
    .call-brief-goal-pill {
      padding: 4px 10px !important;
      min-height: 27px !important;
      font-size: 12px !important;
      border-radius: 999px !important;
      border: 1px solid var(--border-strong) !important;
      background: var(--surface-soft) !important;
      color: var(--text-secondary) !important;
      cursor: pointer;
    }
    .call-brief-goal-pill.active {
      background: var(--primary) !important;
      color: var(--primary-fg) !important;
      border-color: var(--primary) !important;
      font-weight: 600 !important;
    }
    .call-brief-custom-row {
      display: flex;
      align-items: center;
      gap: 6px;
      width: 100%;
      margin-top: 2px;
    }
    .call-brief-custom-row input {
      flex: 1 1 auto;
      padding: 5px 10px !important;
      font-size: 12.5px !important;
      min-height: 30px !important;
    }
    .call-brief-coverage {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 8px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-soft);
      font-size: 12px;
      color: var(--text-secondary);
      flex-shrink: 0;
    }
    .call-brief-stat-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 9px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      font-size: 11.5px;
    }
    .call-brief-moments-nudge {
      margin-left: auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--vip, #d97706);
      font-weight: 500;
    }
    .call-brief-body {
      padding: 14px 18px 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: var(--bg);
    }
    .cb-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 13px 15px;
      display: flex;
      flex-direction: column;
      gap: 9px;
    }
    .cb-card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }
    .cb-card-title {
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text);
      margin: 0;
    }
    .cb-oneliner {
      padding: 9px 12px;
      border-radius: 9px;
      background: var(--surface-soft);
      border-left: 3px solid var(--ok, #10b981);
      font-size: 13.5px;
      font-weight: 600;
      color: var(--text);
      line-height: 1.55;
    }
    .cb-grid-2 {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    @media (max-width: 700px) { .cb-grid-2 { grid-template-columns: 1fr; } }
    .cb-subbox {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 9px 11px;
      font-size: 12.5px;
      line-height: 1.55;
    }
    .cb-subbox h4 {
      margin: 0 0 5px;
      font-size: 12px;
      font-weight: 700;
      color: var(--text-secondary);
    }
    .cb-list {
      margin: 0;
      padding-left: 17px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 12.5px;
      color: var(--text);
    }
    .cb-script-card {
      border-color: color-mix(in srgb, var(--ok, #10b981) 45%, var(--border));
      box-shadow: var(--shadow-sm);
    }
    .cb-script-block {
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .cb-script-block-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      font-weight: 700;
      color: var(--text-secondary);
    }
    .cb-script-quote {
      font-size: 13.5px;
      line-height: 1.6;
      color: var(--text);
      white-space: pre-wrap;
    }
    .cb-obj-item {
      padding: 7px 10px;
      border-radius: 8px;
      background: var(--surface);
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 12.5px;
    }
    .cb-post-item {
      padding: 7px 10px;
      border-radius: 8px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      font-size: 12.5px;
      line-height: 1.5;
    }
    .moments-suggest-hint {
      width: 100%;
      margin-top: 4px;
      padding: 6px 10px;
      border-radius: 8px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      font-size: 12px;
      color: var(--text-secondary);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
    }
    .moments-alt-chip {
      padding: 2px 8px !important;
      min-height: 24px !important;
      font-size: 11.5px !important;
      border-radius: 999px !important;
    }
    /* Thiflow See-Think-Act & Yingdao AI WorkOS Extensions (v2.4.71) */
    #tab-monitor .workos-goal-bar {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 4px 10px;
      background: color-mix(in srgb, var(--work-pine) 6%, var(--surface));
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 12px;
      flex-wrap: wrap;
    }
    .workos-presets { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
    .workos-preset-btn {
      padding: 2px 8px !important;
      min-height: 24px !important;
      font-size: 11.5px !important;
      border-radius: 999px !important;
      border: 1px solid var(--border) !important;
      background: var(--surface) !important;
      color: var(--text-secondary) !important;
    }
    .workos-preset-btn.active {
      background: var(--work-pine) !important;
      color: #fff !important;
      border-color: var(--work-pine) !important;
    }
    .workos-goal-input-wrap { display: flex; align-items: center; gap: 5px; flex: 1 1 220px; min-width: 180px; }
    .workos-goal-input-wrap input {
      padding: 3px 8px !important;
      min-height: 24px !important;
      font-size: 12px !important;
      background: var(--surface) !important;
    }
    .workos-esc-hint { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
    .see-think-act-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 6px;
    }
    .sta-step {
      padding: 5px 8px;
      border-radius: 7px;
      border: 1px solid var(--border);
      background: var(--surface-soft);
      font-size: 11.5px;
      line-height: 1.4;
    }
    .sta-step strong { display: block; font-size: 11px; color: var(--work-pine); margin-bottom: 2px; }
    .workos-pillars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .workos-pillar-box {
      padding: 8px 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--surface);
      font-size: 12px;
      line-height: 1.45;
    }
    .workos-pillar-box h4 { margin: 0 0 4px; font-size: 12.5px; color: var(--work-pine); }
    .workos-list { margin: 4px 0 0; padding-left: 16px; max-height: 125px; overflow-y: auto; font-size: 11.5px; }
    .workos-human-review-alert {
      padding: 6px 10px;
      margin-bottom: 6px;
      border-radius: 7px;
      border: 1px solid rgba(217, 119, 6, 0.45);
      background: rgba(217, 119, 6, 0.10);
      color: var(--work-alert);
      font-size: 12px;
      line-height: 1.45;
    }

    /* WeChat + WeCom Window Picker Popover (#appWindowPickerBtn / #windowPickerPopover) v2.4.71 */
    .window-picker-wrap { position: relative; flex-shrink: 0; }
    #appWindowPickerBtn {
      max-width: 176px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    #appWindowPickerBtn.is-bound {
      border-color: var(--work-pine) !important;
      color: var(--work-pine) !important;
      background: color-mix(in srgb, var(--work-pine) 9%, var(--surface)) !important;
      font-weight: 600 !important;
    }
    @supports (position-area: block-end) {
      #appWindowPickerBtn { anchor-name: --app-window-picker; }
      #windowPickerPopover {
        position-anchor: --app-window-picker;
        inset: auto;
        margin: 0;
        position-area: block-end span-inline-start;
        position-try-fallbacks: flip-block, flip-inline, flip-block flip-inline;
      }
    }
    @supports not (position-area: block-end) {
      #windowPickerPopover {
        position: fixed;
        inset: auto;
        margin: 0;
      }
    }
    .window-picker-popover {
      display: none;
      width: min(472px, calc(100vw - 24px));
      max-height: min(560px, calc(100dvh - 80px));
      padding: 0;
      border: 1px solid var(--border-strong);
      border-radius: 12px;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 14px 36px rgba(0, 0, 0, 0.18);
      z-index: 9500;
      overflow: hidden;
      accent-color: var(--work-pine);
    }
    .window-picker-popover:is(:popover-open, .open) {
      display: flex;
      flex-direction: column;
    }
    .window-picker-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-soft);
      flex-shrink: 0;
    }
    .window-picker-head strong { font-size: 13px; color: var(--text); }
    .window-picker-sub { font-size: 11px; color: var(--text-muted); margin-top: 1px; }
    .window-picker-head-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .window-picker-apps {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      padding: 7px 12px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      font-size: 11.5px;
      flex-shrink: 0;
    }
    .window-picker-body {
      overflow-y: auto;
      padding: 8px 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      flex: 1 1 auto;
      min-height: 0;
    }
    .window-group { display: flex; flex-direction: column; gap: 5px; }
    .window-group-popout {
      padding: 7px;
      border-radius: 10px;
      background: color-mix(in srgb, var(--work-pine) 6%, var(--surface-soft));
      border: 1px solid color-mix(in srgb, var(--work-pine) 25%, var(--border));
    }
    .window-group-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--text-secondary);
      padding: 1px 3px;
    }
    .window-group-popout .window-group-title { color: var(--work-pine); }
    .window-item-btn {
      width: 100%;
      text-align: left;
      display: flex !important;
      flex-direction: column;
      align-items: stretch !important;
      gap: 3px;
      padding: 7px 9px !important;
      min-height: 0 !important;
      background: var(--surface) !important;
      border: 1px solid var(--border) !important;
      border-radius: 8px !important;
      cursor: pointer;
    }
    .window-item-btn:hover {
      border-color: var(--work-pine) !important;
      background: var(--surface-hover) !important;
    }
    .window-item-btn.active {
      border-color: var(--work-pine) !important;
      background: var(--work-selection) !important;
    }
    .window-item-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      width: 100%;
    }
    .window-item-title-wrap {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
    }
    .window-item-title {
      font-size: 12.5px;
      font-weight: 650;
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .window-item-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 11px;
      color: var(--text-muted);
    }
    .win-tag {
      font-size: 10.5px;
      padding: 1px 7px;
      border-radius: 999px;
      font-weight: 600;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .win-tag.allow { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
    html[data-theme="dark"] .win-tag.allow { background: rgba(16, 185, 129, 0.16); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.35); }
    .win-tag.protected { background: var(--surface-soft); color: var(--text-secondary); border: 1px solid var(--border-strong); }
    .win-tag.app { background: var(--surface-soft); color: var(--text-secondary); border: 1px solid var(--border); }
    .window-picker-foot {
      padding: 7px 12px;
      border-top: 1px solid var(--border);
      background: var(--surface-soft);
      font-size: 11px;
      color: var(--text-muted);
      flex-shrink: 0;
    }
    .window-picker-scheduler-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
      padding: 7px 12px;
      border-bottom: 1px solid var(--border);
      background: color-mix(in srgb, var(--work-pine) 4%, var(--surface-soft));
      flex-shrink: 0;
    }
    .border-toggle-label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
      cursor: pointer;
    }
    .border-toggle-label input[type="checkbox"] {
      width: auto;
      flex: none;
      accent-color: var(--work-pine);
      cursor: pointer;
    }
    .border-state-chip {
      font-size: 11px;
      font-weight: 600;
      padding: 1px 7px;
      border-radius: 999px;
      white-space: nowrap;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text-secondary);
    }
    .border-state-chip.idle { background: #dcfce7; color: #166534; border-color: #86efac; }
    .border-state-chip.thinking { background: #dbeafe; color: #1d4ed8; border-color: #93c5fd; }
    .border-state-chip.paused { background: #fef3c7; color: #92400e; border-color: #fcd34d; }
    html[data-theme="dark"] .border-state-chip.idle { background: rgba(16, 185, 129, 0.16); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.35); }
    html[data-theme="dark"] .border-state-chip.thinking { background: rgba(59, 130, 246, 0.18); color: #93c5fd; border-color: rgba(59, 130, 246, 0.38); }
    html[data-theme="dark"] .border-state-chip.paused { background: rgba(245, 158, 11, 0.18); color: #fcd34d; border-color: rgba(245, 158, 11, 0.38); }
    .scheduler-diag-panel {
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      font-size: 11.5px;
      line-height: 1.45;
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 170px;
      overflow-y: auto;
      flex-shrink: 0;
    }
    .settings-card .scheduler-diag-panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      max-height: 220px;
    }
    .scheduler-metrics-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }
    .scheduler-metric-pill {
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 6px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }
    .scheduler-metric-pill b { color: var(--text); }
    .scheduler-lane-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 5px;
    }
    .scheduler-lane-label {
      font-weight: 650;
      color: var(--text-secondary);
      white-space: nowrap;
    }

    /* Conversational Document & PDF Knowledge Ingest Dialog (#docIngestOverlay) v2.4.71 */
    dialog.doc-ingest-dialog {
      width: min(780px, calc(100vw - 32px));
      max-height: min(88dvh, 780px);
      margin: auto;
      padding: 0;
      border: 1px solid var(--border-strong);
      border-radius: 14px;
      background: var(--bg);
      color: var(--text);
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.36);
      overflow: hidden;
      accent-color: var(--work-pine);
    }
    dialog.doc-ingest-dialog[open] {
      display: flex;
      flex-direction: column;
    }
    dialog.doc-ingest-dialog:modal {
      overscroll-behavior: contain;
    }
    dialog.doc-ingest-dialog::backdrop {
      background: rgba(15, 18, 25, 0.56);
      backdrop-filter: blur(3px);
      overflow: hidden;
      overscroll-behavior: contain;
    }
    .doc-ingest-dialog input[type="checkbox"],
    .doc-ingest-dialog input[type="radio"] {
      width: auto;
      flex: none;
      accent-color: var(--work-pine);
    }
    .doc-ingest-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 13px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--surface-soft);
      flex-shrink: 0;
    }
    .doc-ingest-head h2 { margin: 0; font-size: 15.5px; }
    .doc-ingest-head p { margin: 3px 0 0; font-size: 12px; color: var(--text-secondary); }
    .doc-ingest-body {
      padding: 14px 18px;
      overflow-y: auto;
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .doc-ingest-section {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .doc-ingest-field { display: flex; flex-direction: column; gap: 4px; }
    .doc-ingest-field label { font-size: 12.5px; font-weight: 600; color: var(--text); }
    .doc-ingest-row-2 { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 10px; }
    .doc-ingest-file-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      padding: 8px 10px;
      border: 1px dashed var(--border-strong);
      border-radius: 8px;
      background: var(--surface-soft);
    }
    .doc-ingest-file-box input[type="file"] { font-size: 12.5px; max-width: 100%; }
    .doc-ingest-file-meta { font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }
    .doc-ingest-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .doc-ingest-status { font-size: 12px; color: var(--text-secondary); }
    .doc-ingest-status[data-tone="error"] { color: var(--danger); font-weight: 600; }
    .doc-ingest-preview-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--text-secondary);
      padding: 6px 10px;
      border-radius: 8px;
      background: var(--surface-soft);
      border: 1px solid var(--border);
    }
    .doc-strategy-fieldset { border: 0; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
    .doc-strategy-fieldset legend { font-size: 12.5px; font-weight: 700; color: var(--text); padding: 0; margin-bottom: 2px; }
    .doc-strategy-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .doc-strategy-card {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 9px;
      background: var(--surface-soft);
      cursor: pointer;
      font-size: 12.5px;
      transition: border-color 140ms var(--ease-out), background-color 140ms var(--ease-out);
    }
    .doc-strategy-card.selected {
      border-color: var(--work-pine);
      background: color-mix(in srgb, var(--work-pine) 8%, var(--surface));
    }
    .doc-strategy-card input[type="radio"] { margin-top: 2px; }
    .doc-strategy-title { font-weight: 650; color: var(--text); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .doc-strategy-desc { font-size: 11.5px; color: var(--text-secondary); margin-top: 3px; line-height: 1.45; }
    .doc-draft-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
    .doc-draft-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 250px;
      overflow-y: auto;
      padding-right: 2px;
    }
    .doc-draft-item {
      border: 1px solid var(--border);
      border-radius: 9px;
      padding: 9px 10px;
      background: var(--surface-soft);
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .doc-draft-item.unchecked { opacity: 0.58; }
    .doc-draft-item-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .doc-draft-item-head select { padding: 3px 8px !important; font-size: 11.5px !important; width: auto; }
    .doc-draft-item-title { flex: 1 1 200px; padding: 4px 8px !important; font-size: 12.5px !important; font-weight: 600; }
    .doc-draft-item-body { min-block-size: 50px !important; max-block-size: 110px !important; font-size: 12.5px !important; padding: 6px 8px !important; }
    .doc-draft-item-kw { font-size: 11.5px !important; padding: 3px 8px !important; }
    .doc-confirm-card {
      background: color-mix(in srgb, var(--work-pine) 7%, var(--surface));
      border: 1px solid color-mix(in srgb, var(--work-pine) 34%, var(--border));
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .doc-confirm-title { font-size: 13.5px; font-weight: 700; color: var(--work-pine); }
    .doc-confirm-summary { font-size: 12.5px; color: var(--text-secondary); line-height: 1.5; }
    .doc-confirm-actions { display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }

    .supervisor-directive-banner {
      margin: 0 0 6px;
      padding: 7px 10px;
      border-radius: 8px;
      border: 1px solid #f59e0b;
      background: color-mix(in srgb, #f59e0b 12%, var(--surface));
      color: #92400e;
      font-size: 12.5px;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }
    [data-theme="dark"] .supervisor-directive-banner { color: #fcd34d; }
    .quality-feedback-bar {
      margin-top: 8px;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--surface-soft);
      display: flex;
      flex-direction: column;
      gap: 7px;
      font-size: 12px;
    }
    .star-rating-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .star-btn {
      padding: 3px 8px;
      font-size: 12px;
      border-radius: 7px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
    }
    .star-btn.active { background: #f59e0b; color: #fff; border-color: #d97706; }
    .tag-chip {
      padding: 2px 8px;
      font-size: 11.5px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text-secondary);
      cursor: pointer;
    }
    .tag-chip.active { background: var(--work-pine); color: #fff; border-color: var(--work-pine); }
    .wizard-steps {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 12px;
    }
    .wizard-step-pill {
      padding: 7px 9px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--surface-soft);
      font-size: 12px;
      text-align: center;
      color: var(--text-muted);
      font-weight: 600;
    }
    .wizard-step-pill.active {
      border-color: var(--work-pine);
      background: color-mix(in srgb, var(--work-pine) 12%, var(--surface));
      color: var(--work-pine);
    }
    .wizard-step-pill.done {
      border-color: #16a34a;
      color: #15803d;
    }
    .sparring-grid { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 14px; }
    @media (max-width: 980px) { .sparring-grid { grid-template-columns: 1fr; } }
    .sparring-chat-box {
      border: 1px solid var(--border);
      border-radius: 10px;
      background: var(--surface-soft);
      min-height: 240px;
      max-height: 360px;
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .sparring-msg { padding: 8px 10px; border-radius: 9px; font-size: 12.5px; line-height: 1.5; max-width: 92%; }
    .sparring-msg.peer { align-self: flex-start; background: var(--surface); border: 1px solid var(--border); }
    .sparring-msg.self { align-self: flex-end; background: color-mix(in srgb, var(--work-pine) 11%, var(--surface)); border: 1px solid color-mix(in srgb, var(--work-pine) 30%, var(--border)); }
    .sparring-msg.sys { align-self: center; background: color-mix(in srgb, #f59e0b 12%, var(--surface)); border: 1px solid #f59e0b; font-size: 12px; }
    .md-doc-body { font-size: 13px; line-height: 1.65; color: var(--text); max-height: 62vh; overflow-y: auto; padding: 6px 4px; }
    .md-doc-body h1, .md-doc-body h2, .md-doc-body h3 { margin: 14px 0 6px; color: var(--text); }
    .md-doc-body pre { background: var(--surface-soft); padding: 8px 10px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
    .md-doc-body code { background: var(--surface-soft); padding: 1px 4px; border-radius: 4px; font-size: 12px; }

    @media (max-width: 1180px) {
      #tab-monitor .hosting-top-row { flex-wrap: wrap; }
      #tab-monitor .hosting-actions { flex-wrap: wrap; }
    }
    @media (max-width: 900px) {
      #tab-monitor .chat-workspace { height: auto; min-height: auto; overflow: visible; }
      #tab-monitor .home-conversations { height: auto; max-height: 270px; }
      #tab-monitor .chat-main-pane { height: auto; overflow: visible; padding: 10px 12px 18px !important; }
      #tab-monitor .hosting-top-row { flex-wrap: wrap; }
      #tab-monitor .hosting-actions { flex-wrap: wrap; }
      #tab-monitor #chatBubbleStream { max-height: 360px !important; }
    }
    @media (max-width: 680px) {
      .settings-shell { grid-template-columns: 1fr; }
      .settings-rail { flex-direction: row; overflow-x: auto; border-right: 0; border-bottom: 1px solid var(--border); }
      .settings-nav-btn { width: auto; white-space: nowrap; }
      .settings-row { grid-template-columns: 1fr; gap: 4px; }
      .doc-ingest-row-2, .doc-strategy-grid { grid-template-columns: 1fr; }
    }

  </style>
</head>
<body>
  <div class="container">
    <nav class="tabs" aria-label="工作区">
      <div class="nav-brand">
        <span class="nav-dot" aria-hidden="true"></span>
        <span>WeChat Bot</span>
      </div>
      <button type="button" class="tab-btn active" aria-current="page" data-tab="monitor" onclick="switchTab('monitor')">对话</button>
      <a id="reviewWorkbenchLink" class="tab-btn workspace-link" href="/workbench">待办审阅</a>
      <button type="button" class="tab-btn" data-tab="care" onclick="switchTab('care')">联系人</button>
      <button type="button" class="tab-btn" data-tab="moments" onclick="switchTab('moments')">朋友圈</button>
      <button type="button" class="tab-btn" data-tab="knowledge" onclick="switchTab('knowledge')">知识库</button>
      <button type="button" class="tab-btn" data-tab="sparring" onclick="switchTab('sparring')">🧪 测试与评分</button>
      <button type="button" class="tab-btn" data-tab="salescrm" onclick="switchTab('salescrm')">客户跟进</button>
      <button type="button" class="tab-btn" data-tab="omni" onclick="switchTab('omni')">全渠道矩阵</button>
      <button type="button" class="tab-btn" data-tab="appuse" onclick="switchTab('appuse')">App-Use 流程工厂</button>
      <details class="nav-more" id="navMore">
        <summary>更多 ▾</summary>
        <div class="nav-more-list">
          <button type="button" class="tab-btn" data-tab="stats" onclick="switchTab('stats')">统计与巡检</button>
          <button type="button" class="tab-btn" data-tab="articles" onclick="switchTab('articles')">文章与视频导出</button>
          <button type="button" class="tab-btn" data-tab="soul" onclick="switchTab('soul')">本我与记忆</button>
          <button type="button" class="tab-btn" data-tab="models" onclick="switchTab('models')">模型路由</button>
          <button type="button" class="tab-btn" data-tab="uiprotocol" onclick="switchTab('uiprotocol')">防抢鼠标守卫</button>
          <button type="button" class="tab-btn" data-tab="open" onclick="switchTab('open')">独立包与外部接入</button>
        </div>
      </details>
      <header class="topbar">
        <div class="tb-left">
          <div class="home-connection" id="homeConnection" role="status" data-state="loading">正在连接工作台</div>
          <button type="button" id="homeRetry" class="btn-outline sm" onclick="loadOverview(true)" hidden>重连</button>
        </div>
        <div class="tb-right">
          <button type="button" id="topOnboardingWizardBtn" class="btn-solid sm" onclick="openOnboardingWizard()" title="4 步零配置快速训练向导：设身份 → 扫记录 → 审草稿 → 模拟试跑">✨ 快速训练向导</button>
          <button type="button" id="topUserGuideBtn" class="btn-outline sm" onclick="openUserGuideModal()" title="打开微信客服使用手册（含权限、快速训练、# 指令与打分指南）">📖 使用手册</button>
          <button type="button" id="topSettingsBtn" class="btn-outline sm" onclick="openSettingsModal()" title="打开 BotStudio 风格统一设置中心（模型、回复策略、防抢鼠标、权限与窗口）">⚙️ 设置</button>
          <details class="topbar-more" id="topbarMore">
            <summary>窗口 ▾</summary>
            <div id="topbarMoreMenu" class="more-popover" aria-label="窗口设置">
              <button type="button" class="menu-item" onclick="triggerDockSidebar('dock')">贴靠微信侧栏</button>
              <button type="button" class="menu-item" onclick="triggerDockSidebar('tile')">并排分屏</button>
              <button type="button" class="menu-item" onclick="triggerActivateWeChat()">唤醒微信窗口</button>
              <button type="button" class="menu-item" onclick="loadOverview(true)">刷新工作台状态</button>
              <button type="button" class="menu-item" onclick="toggleTheme()">切换深浅主题</button>
              <button type="button" id="btnAuthToggle" class="menu-item" onclick="toggleStudioAuth()">访问授权</button>
            </div>
          </details>
        </div>
      </header>
    </nav>

    <div id="formStatusAnnouncer" role="status" aria-live="polite" class="visually-hidden"></div>

    <!-- Fail-Closed Auth Banner -->
    <div id="authBanner" class="auth-banner">
      <div>
        <strong>工作台访问权限未开启</strong>
        <div style="font-size:12.5px; margin-top:2px;" id="authBannerMsg">开启授权后可读会话与本地统计。</div>
      </div>
      <button type="button" class="primary" onclick="grantAllAuth()">恢复访问授权</button>
    </div>

    <!-- 启动授权弹窗（影刀式）：缺权限时自动弹出 -->
    <div class="perm-overlay" id="permOverlay" role="dialog" aria-modal="true" aria-labelledby="permModalTitle">
      <div class="perm-modal">
        <h2 id="permModalTitle">需要授权以下权限才能正常使用 WeChat Bot</h2>
        <p class="perm-sub">需要两项 macOS 权限：<b>辅助功能</b>、<b>屏幕录制</b>（「系统事件控制」随辅助功能一起生效，没有单独的开关）</p>
        <details class="hosting-picker" style="margin:0 12px 8px;">
          <summary style="font-size:12px;color:#888;">为什么开关已经打开，这里还显示未授权？</summary>
          <div style="font-size:12px;color:#666;line-height:1.6;padding:6px 4px;">
            系统设置里那条开关，可能绑定的是<b>某个旧版本的 WeChat Bot</b>。macOS 只认绑定的那个版本，所以开关显示开着，当前版本却不被承认，再怎么点开关都没用。<br>
            点下方<b>「重新登记授权」</b>：它只清除 WeChat Bot 自己的旧记录，并让 macOS 把<b>当前安装的版本</b>重新加进列表，然后打开开关即可，之后更新版本不会再失效。
          </div>
        </details>
        <div class="perm-steps" id="permModalSteps"></div>
        <div id="permWizard"></div>
        <div class="perm-items perm-modal-items" id="permModalItems"></div>
        <div class="perm-modal-actions">
          <a id="permModalOpenSettings" class="btn-solid" href="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" onclick="requestPermissionThenOpen(event, (permPendingSteps(PERM_WIZARD.items || [])[0] || {}).id || 'accessibility', this.href, this)" style="text-decoration:none;">⚙️ 打开系统设置去授权</a>
          <button type="button" class="btn-outline" onclick="window.PERM_MODAL_DISMISSED = false; loadPermissions(true)">🔄 我已勾选，重新检查</button>
        </div>
        <span class="perm-modal-later" onclick="hidePermModal()">稍后再说（首页会保留警示）</span>
      </div>
    </div>

    <div class="perm-overlay" id="diagOverlay" role="dialog" aria-modal="true" aria-labelledby="diagModalTitle">
      <div class="perm-modal" style="max-width:640px;max-height:80vh;overflow:auto;">
        <h2 id="diagModalTitle">🩺 健康诊断</h2>
        <p class="perm-sub">一键查看授权、托管、频控、知识库与最近事件——排障从这里开始</p>
        <div id="diagModalBody" style="text-align:left;font-size:13px;line-height:1.7;"><p class="hosting-empty">正在读取诊断数据…</p></div>
        <div class="perm-modal-actions">
          <button type="button" class="btn-solid" onclick="loadDiagnostics(false, true)">🔍 深度检查（含权限/网关探测）</button>
          <button type="button" class="btn-outline" onclick="loadDiagnostics(true)">🔄 刷新</button>
          <button type="button" class="btn-outline" onclick="hideDiagModal()">关闭</button>
        </div>
      </div>
    </div>

    <!-- 📖 使用手册 Modal -->
    <div class="perm-overlay" id="userGuideOverlay" role="dialog" aria-modal="true" aria-labelledby="userGuideTitle" onclick="if(event.target===this)hideUserGuideModal()">
      <div class="perm-modal" style="max-width:780px; width:min(780px, 94vw); text-align:left;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:8px;">
          <h2 id="userGuideTitle" style="margin:0;">📖 WeChat Bot 使用手册</h2>
          <div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px;">
            <a href="/user-guide" target="_blank" rel="noopener" class="btn-outline sm" style="text-decoration:none; border-radius:var(--radius-sm); display:inline-flex; align-items:center; gap:4px;">🌐 在浏览器打开网页版手册</a>
            <a href="https://harzva.github.io/app-use/user-guide.html" target="_blank" rel="noopener" class="btn-outline sm" style="text-decoration:none; border-radius:var(--radius-sm); display:inline-flex; align-items:center; gap:4px;">🔗 在线网页版</a>
            <button type="button" class="btn-outline sm" onclick="hideUserGuideModal()">关闭</button>
          </div>
        </div>
        <div id="userGuideBody" class="md-doc-body"><p class="hosting-empty">正在读取操作手册…</p></div>
      </div>
    </div>

    <!-- ✨ 4 步零配置快速训练向导 Modal -->
    <div class="perm-overlay" id="onboardingWizardOverlay" role="dialog" aria-modal="true" aria-labelledby="wizardModalTitle" onclick="if(event.target===this)hideOnboardingWizard()">
      <div class="perm-modal" style="max-width:780px; width:min(780px, 94vw); max-height:88vh; overflow:auto; text-align:left;">
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px;">
          <h2 id="wizardModalTitle" style="margin:0;">✨ 快速训练向导（4 步打造你的专属销售助手）</h2>
          <button type="button" class="btn-outline sm" onclick="hideOnboardingWizard()">稍后</button>
        </div>
        <div class="wizard-steps" id="wizardStepPills">
          <div class="wizard-step-pill active" data-wstep="1">1 · 身份与行业包</div>
          <div class="wizard-step-pill" data-wstep="2">2 · 发现聊天与资料</div>
          <div class="wizard-step-pill" data-wstep="3">3 · 词汇与草稿验收</div>
          <div class="wizard-step-pill" data-wstep="4">4 · 3 轮模拟试跑</div>
        </div>

        <div id="wizardStepPanel1">
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <label style="font-size:12px; font-weight:600;">你的称呼 / 主账号名</label>
              <input type="text" id="wizOwnerName" placeholder="例如：陈经理 / 小林" />
            </div>
            <div>
              <label style="font-size:12px; font-weight:600;">企业 / 品牌名称</label>
              <input type="text" id="wizBusinessName" placeholder="例如：星河定制家居" />
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; font-weight:600;">历史聊天里的常用名/别名（逗号分隔，帮助识别哪句是你说的）</label>
            <input type="text" id="wizOwnerAliases" placeholder="例如：Kevin-华东区, 小陈" />
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; font-weight:600;">一句话主营产品 / 业务简介</label>
            <textarea id="wizProductSummary" rows="2" placeholder="例如：主打全屋环保实木定制与上门量尺设计，主要服务新房业主"></textarea>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <label style="font-size:12px; font-weight:600;">行业销售场景包</label>
              <select id="wizIndustryPack"></select>
            </div>
            <div>
              <label style="font-size:12px; font-weight:600;">测试好友名称（用于私下试跑与 # 指令调优）</label>
              <input type="text" id="wizTestContacts" placeholder="例如：测试小号（选填，逗号分隔）" />
            </div>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button type="button" class="btn-solid" id="wizSaveStep1Btn" onclick="wizardSubmitStep1()">保存并进入第 2 步 →</button>
          </div>
        </div>

        <div id="wizardStepPanel2" hidden>
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap;">
            <span style="font-size:12.5px; color:var(--text-secondary);">自动过滤公众号/系统通知与测试好友，按商机含金量排序推荐训练样本：</span>
            <button type="button" class="btn-outline sm" onclick="wizardDiscoverCorpora()">🔍 重新扫描会话与导出包</button>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <strong style="font-size:12px;">活跃高价值微信会话</strong>
              <div id="wizDiscoveredSessions" style="max-height:170px; overflow:auto; border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px; font-size:12px;">正在扫描…</div>
            </div>
            <div>
              <strong style="font-size:12px;">本地导出聊天包 (.zip / *聊天记录*.txt)</strong>
              <div id="wizDiscoveredArchives" style="max-height:170px; overflow:auto; border:1px solid var(--border); border-radius:8px; padding:8px; margin-top:4px; font-size:12px;">正在扫描…</div>
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; font-weight:600;">补充聊天记录路径（可选）或粘贴产品资料 / FAQ 文本</label>
            <input type="text" id="wizExtraArchivePath" placeholder="可选：本地 .zip 或 聊天记录.txt 路径" style="margin-bottom:6px;" />
            <textarea id="wizProductDocText" rows="3" placeholder="可选：粘贴产品介绍、常见问答或报价说明文本，系统将自动脱敏并提炼话术…"></textarea>
          </div>
          <div style="display:flex; justify-content:space-between; gap:8px;">
            <button type="button" class="btn-outline" onclick="goWizardStep(1)">← 上一步</button>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-outline" onclick="goWizardStep(3)">跳过训练直接看话术</button>
              <button type="button" class="btn-solid" id="wizRunTrainBtn" onclick="wizardRunTraining()">⚡ 开始自训练并提炼话术 →</button>
            </div>
          </div>
        </div>

        <div id="wizardStepPanel3" hidden>
          <div id="wizTrainStatsBox" style="font-size:12.5px; color:var(--text-secondary); margin-bottom:8px;">尚未执行本次训练，可直接进入模拟测试。</div>
          <div style="margin-bottom:10px;">
            <strong style="font-size:12.5px;">提炼业务词汇表</strong>
            <div id="wizMinedVocabBox" style="display:flex; gap:6px; flex-wrap:wrap; margin-top:6px;"></div>
          </div>
          <div style="margin-bottom:10px;">
            <strong style="font-size:12.5px;">待审核发布草稿（含价格/折扣/承诺等高风险条款，需勾选取舍后发布）</strong>
            <div id="wizDraftsList" style="max-height:200px; overflow:auto; display:flex; flex-direction:column; gap:8px; margin-top:6px;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; gap:8px;">
            <button type="button" class="btn-outline" onclick="goWizardStep(2)">← 上一步</button>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-solid" onclick="wizardApproveDraftsAndNext()">✅ 审核发布所选并试跑 →</button>
            </div>
          </div>
        </div>

        <div id="wizardStepPanel4" hidden>
          <p style="font-size:12.5px; color:var(--text-secondary); margin:0 0 8px;">无需打开微信，在这里先模拟 3 轮客户提问，看看 AI 回复是否准确自然：</p>
          <div id="wizSimChatLog" class="sparring-chat-box" style="min-height:170px; max-height:220px; margin-bottom:8px;">
            <div class="sparring-msg sys">试发一句客户常问的话，例如“你们这套方案多少钱？”或“能先看看案例吗？”</div>
          </div>
          <div style="display:flex; gap:8px; margin-bottom:10px;">
            <input type="text" id="wizSimInput" placeholder="输入模拟客户提问…" onkeydown="if(event.key==='Enter'){event.preventDefault();wizardSendSimTurn();}" />
            <button type="button" class="btn-solid sm" onclick="wizardSendSimTurn()">发送测试</button>
          </div>
          <div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">
            <button type="button" class="btn-outline" onclick="goWizardStep(3)">← 上一步</button>
            <div style="display:flex; gap:8px;">
              <button type="button" class="btn-outline" onclick="hideOnboardingWizard(); switchTab('sparring');">前往「🧪 测试与评分」工作区</button>
              <button type="button" class="btn-solid" onclick="hideOnboardingWizard(); loadOverview(true);">🎉 完成初始化</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- BotStudio Unified Settings Modal -->
    <div class="perm-overlay" id="settingsOverlay" role="dialog" aria-modal="true" aria-labelledby="settingsModalTitle" onclick="if(event.target===this)hideSettingsModal()">
      <div class="perm-modal settings-modal">
        <div class="settings-head">
          <h2 id="settingsModalTitle">⚙️ 工作台设置中心</h2>
          <div style="display:flex; gap:8px; align-items:center;">
            <button type="button" class="btn-outline sm" onclick="toggleTheme()">🌓 深浅主题</button>
            <button type="button" class="btn-outline sm" onclick="hideSettingsModal()">关闭</button>
          </div>
        </div>
        <div class="settings-shell">
          <nav class="settings-rail" aria-label="设置分类">
            <button type="button" class="settings-nav-btn active" data-settings-sec="reply" onclick="switchSettingsSection('reply')">💬 回复与 AI 助手</button>
            <button type="button" class="settings-nav-btn" data-settings-sec="models" onclick="switchSettingsSection('models')">🧠 模型与网关</button>
            <button type="button" class="settings-nav-btn" data-settings-sec="guard" onclick="switchSettingsSection('guard')">🛡️ 防抢鼠标与安全</button>
            <button type="button" class="settings-nav-btn" data-settings-sec="workos" onclick="switchSettingsSection('workos')">🔄 评估与自学习</button>
            <button type="button" class="settings-nav-btn" data-settings-sec="window" onclick="switchSettingsSection('window')">🪟 窗口与系统权限</button>
            <button type="button" class="settings-nav-btn" data-settings-sec="bridge" onclick="switchSettingsSection('bridge')">🔌 BotStudio 接入</button>
          </nav>
          <div class="settings-body">
            <div class="settings-section active" data-settings-panel="reply">
              <div class="settings-card">
                <h3>默认回复性格与发送安全</h3>
                <div class="settings-row">
                  <label for="cfgPersonaSelect">回复性格</label>
                  <select id="cfgPersonaSelect" onchange="const p=document.getElementById('previewPersona'); if(p){p.value=this.value;}"></select>
                </div>
                <div class="settings-row">
                  <label for="cfgModelSelect">驱动模型</label>
                  <select id="cfgModelSelect" onchange="const m=document.getElementById('previewModelSelect'); if(m){m.value=this.value;}"></select>
                </div>
                <div class="settings-row">
                  <label for="cfgSendModeSelect">发送安全模式</label>
                  <select id="cfgSendModeSelect" onchange="const s=document.getElementById('sendMode'); if(s){s.value=this.value; syncSendModeLabel();}">
                    <option value="dry_run">模拟检查（不写入微信）</option>
                    <option value="silent_verify">粘贴校验后清空</option>
                    <option value="confirm_send">确认并发送</option>
                  </select>
                </div>
                <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
                  <input type="checkbox" id="cfgUseLlmCheckbox" checked style="width:auto;" onchange="const u=document.getElementById('previewUseLlm'); if(u){u.checked=this.checked;}" />
                  启用大模型与知识库协同生成回复
                </label>
              </div>
              <div class="settings-card">
                <h3>微信原生助手（@元宝 / 小微）</h3>
                <p style="margin:0; font-size:12.5px; color:var(--text-secondary);">遇到视频号、公众号卡片或复杂链接时，可直接点主操作栏的 <b>@元宝 解析</b> 或 <b>转发小微</b>，将原生摘要写入联系人记忆并自动重算回复草稿。</p>
              </div>
            </div>
            <div class="settings-section" data-settings-panel="models">
              <div class="settings-card">
                <h3>LLM 网关与模型路由</h3>
                <div id="cfgGatewayStatusBox" style="font-size:12.5px; color:var(--text-secondary);">正在读取网关状态…</div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-outline sm" onclick="relaunchLlmGateway()">🔧 启动 Magpie 网关</button>
                  <button type="button" class="btn-solid sm" onclick="hideSettingsModal(); switchTab('models')">前往模型路由详情页 →</button>
                </div>
              </div>
            </div>
            <div class="settings-section" data-settings-panel="guard">
              <div class="settings-card">
                <h3>防抢鼠标 / 键盘自动让路守卫</h3>
                <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
                  <input type="checkbox" id="cfgGuardEnabled" checked style="width:auto;" /> 启用人工键鼠活动自动避让
                </label>
                <div class="settings-row">
                  <label for="cfgGuardCooldown">干预空窗期 (秒)</label>
                  <input type="number" id="cfgGuardCooldown" min="3" max="600" value="45" style="max-width:120px;" />
                </div>
                <div class="settings-row">
                  <label for="cfgGuardIdle">静止恢复阈值 (秒)</label>
                  <input type="number" id="cfgGuardIdle" min="3" max="600" value="45" style="max-width:120px;" />
                </div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-solid sm" onclick="saveHumanGuardFromSettings()">💾 保存守卫配置</button>
                  <button type="button" class="btn-outline sm" onclick="resetHumanGuardCooldown()">⚡ 立即结束当前空窗</button>
                  <button type="button" class="btn-outline sm" onclick="hideSettingsModal(); switchTab('uiprotocol')">打开守卫详情页 →</button>
                </div>
              </div>
            </div>
            <div class="settings-section" data-settings-panel="workos">
              <div class="settings-card">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                  <h3>🔄 AI WorkOS 四维闭环（治理 · 评估 · 反思 · 进化）</h3>
                  <button type="button" class="btn-outline sm" onclick="loadWorkosHarness(true)">刷新指标</button>
                </div>
                <div class="workos-pillars" id="workosHarnessGrid">
                  <div class="workos-pillar-box"><h4>🛡️ 治理 (Governance)</h4><div id="workosGovBox">加载中…</div></div>
                  <div class="workos-pillar-box"><h4>📊 评估 (Evaluation)</h4><div id="workosEvalBox">加载中…</div></div>
                  <div class="workos-pillar-box"><h4>🔍 反思 (Reflection · 未命中盲区)</h4><div id="workosReflectBox">暂无待补盲区</div></div>
                  <div class="workos-pillar-box"><h4>🧬 进化 (Evolution · 纠偏沉淀 SOP)</h4><div id="workosEvolveBox">暂无自学习条目</div></div>
                </div>
              </div>
              <div class="settings-card">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
                  <h3>⚡ 多窗并发调度 &amp; 🟢 零风控透明呼吸边框</h3>
                  <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                    <label class="border-toggle-label" for="settingsBorderOverlayToggle" title="开启后将在白名单独立聊天小窗外围叠加透明鼠标穿透光圈（100% 不注入微信）">
                      <input type="checkbox" id="settingsBorderOverlayToggle" onchange="toggleBorderOverlay(this.checked)" />
                      <span>透明呼吸边框</span>
                    </label>
                    <span id="settingsBorderStateBadge" class="border-state-chip off">⚪ 已关闭</span>
                  </div>
                </div>
                <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                  <button type="button" id="settingsRunMultiWinBtn" class="btn-solid sm" onclick="runMultiWindowScheduler(false)">⚡ 跑一轮多窗调度诊断</button>
                  <button type="button" class="btn-outline sm" onclick="setBorderOverlayState('idle')" title="守护状态（暗绿 #10B981）">🟢 守护中</button>
                  <button type="button" class="btn-outline sm" onclick="setBorderOverlayState('thinking')" title="思考状态（呼吸蓝 #3B82F6）">🔵 思考中</button>
                  <button type="button" class="btn-outline sm" onclick="setBorderOverlayState('human_paused')" title="让路状态（琥珀黄 #F59E0B）">🟠 让路中</button>
                  <button type="button" class="btn-outline sm" onclick="refreshSchedulerAndOverlay(true)">🔄 刷新状态</button>
                </div>
                <div id="workosSchedulerBox" class="scheduler-diag-panel">
                  <div style="color:var(--text-muted);">点击「⚡ 跑一轮多窗调度诊断」可实时查看快车道独立小窗、主窗兜底目标、受保护只读小窗与 dHash/窗口合并指标。</div>
                </div>
              </div>
              <div class="settings-card">
                <h3>📱 手机伴侣遥控台 (/mobile)</h3>
                <p style="margin:0; font-size:12.5px; color:var(--text-secondary);">借鉴识流AI伴侣体验：在同一局域网或本机浏览器打开 <code id="mobileRemoteUrlCode">/mobile</code>，即可远程看状态、一键开停托管、看人工待办与最近会话。</p>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-solid sm" onclick="hideSettingsModal(); openMobileRemoteOverlay()">📱 打开手机遥控台预览</button>
                  <a class="btn-outline sm" href="/mobile" target="_blank" style="text-decoration:none;">在新标签打开 /mobile ↗</a>
                </div>
              </div>
            </div>
            <div class="settings-section" data-settings-panel="window">
              <div class="settings-card">
                <h3>窗口贴靠与 macOS 系统权限</h3>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-outline sm" onclick="triggerDockSidebar('dock')">📌 贴靠微信侧栏</button>
                  <button type="button" class="btn-outline sm" onclick="triggerDockSidebar('tile')">◫ 与微信并排</button>
                  <button type="button" class="btn-outline sm" onclick="triggerActivateWeChat()">💬 唤醒微信窗口</button>
                  <button type="button" class="btn-outline sm" onclick="hideSettingsModal(); window.PERM_MODAL_DISMISSED=false; loadPermissions(true)">🔐 检查系统权限</button>
                  <button type="button" class="btn-outline sm" onclick="hideSettingsModal(); loadDiagnostics(true, true)">🩺 深度健康诊断</button>
                </div>
              </div>
              <div class="settings-card">
                <h3>工作台授权</h3>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-outline sm" onclick="toggleStudioAuth()">🔑 切换工作台访问授权</button>
                </div>
              </div>
            </div>
            <div class="settings-section" data-settings-panel="bridge">
              <div class="settings-card">
                <h3>BotStudio & 独立应用集成</h3>
                <p style="margin:0; font-size:12.5px; color:var(--text-secondary);">管理独立 App 打包、DSH 插件导出与 BotStudio 四标签工作台接入。</p>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                  <button type="button" class="btn-solid sm" onclick="hideSettingsModal(); switchTab('open')">打开 BotStudio 集成页 →</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Mobile Companion Remote Overlay (/mobile) -->
    <div class="perm-overlay" id="mobileRemoteOverlay" role="dialog" aria-modal="true" aria-labelledby="mobileRemoteModalTitle" onclick="if(event.target===this)hideMobileRemoteOverlay()">
      <div class="perm-modal" style="max-width:440px; padding:14px !important;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <h2 id="mobileRemoteModalTitle" style="margin:0; font-size:15px;">📱 手机伴侣遥控台 (/mobile)</h2>
          <div style="display:flex; gap:6px;">
            <a class="btn-outline sm" href="/mobile" target="_blank" style="text-decoration:none;">独立窗口 ↗</a>
            <button type="button" class="btn-outline sm" onclick="hideMobileRemoteOverlay()">关闭</button>
          </div>
        </div>
        <iframe id="mobileRemoteFrame" title="手机伴侣遥控台" style="width:100%; height:520px; border:1px solid var(--border); border-radius:16px; background:#f8fafc;"></iframe>
      </div>
    </div>

    <!-- Pre-Call Brief & Spoken Phone Script Advisor Modal (#callBriefOverlay) -->
    <div class="perm-overlay" id="callBriefOverlay" role="dialog" aria-modal="true" aria-labelledby="callBriefModalTitle" onclick="if(event.target===this)hideCallBriefModal()">
      <div class="perm-modal settings-modal call-brief-modal">
        <div class="settings-head">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; min-width:0;">
            <h2 id="callBriefModalTitle">📋 电话前速览 · 话术参谋</h2>
            <span id="callBriefModelBadge" class="call-brief-stat-chip">准备就绪</span>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <button type="button" id="callBriefCopyAllBtn" class="btn-outline sm" onclick="copyFullCallBrief()">📋 复制整张话术卡</button>
            <button type="button" class="btn-outline sm" onclick="hideCallBriefModal()">关闭</button>
          </div>
        </div>
        <div class="call-brief-toolbar">
          <div class="call-brief-goals" id="callBriefGoalPills" role="group" aria-label="通话沟通目标">
            <button type="button" class="call-brief-goal-pill active" data-cb-goal="general" onclick="switchCallBriefGoal('general')">综合沟通</button>
            <button type="button" class="call-brief-goal-pill" data-cb-goal="followup" onclick="switchCallBriefGoal('followup')">日常破冰</button>
            <button type="button" class="call-brief-goal-pill" data-cb-goal="quote" onclick="switchCallBriefGoal('quote')">推进报价</button>
            <button type="button" class="call-brief-goal-pill" data-cb-goal="care" onclick="switchCallBriefGoal('care')">客情关怀</button>
            <button type="button" class="call-brief-goal-pill" data-cb-goal="recovery" onclick="switchCallBriefGoal('recovery')">异议安抚</button>
            <button type="button" class="call-brief-goal-pill" data-cb-goal="custom" onclick="switchCallBriefGoal('custom')">自定义</button>
            <select id="callBriefGoalSelect" aria-label="选择通话目标" onchange="switchCallBriefGoal(this.value)" style="width:auto; padding:3px 8px; font-size:12px;">
              <option value="general">综合沟通</option>
              <option value="followup">日常破冰</option>
              <option value="quote">推进报价</option>
              <option value="care">客情关怀</option>
              <option value="recovery">异议安抚</option>
              <option value="custom">自定义目标</option>
            </select>
          </div>
          <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
            <button type="button" id="callBriefAiBtn" class="btn-solid sm" onclick="refreshCallBrief(true)">✨ AI 深度研判</button>
            <button type="button" id="callBriefFastBtn" class="btn-outline sm" onclick="refreshCallBrief(false)">⚡ 快速汇总</button>
          </div>
          <div id="callBriefCustomWrap" class="call-brief-custom-row" hidden>
            <input type="text" id="callBriefCustomGoalInput" placeholder="输入本次通话目标（如：确认下周现场演示时间与预算范围）" onkeydown="if(event.key==='Enter'){event.preventDefault();refreshCallBrief(CALL_BRIEF_STATE.useLlm);}" />
            <button type="button" class="btn-solid sm" onclick="refreshCallBrief(CALL_BRIEF_STATE.useLlm)">应用目标</button>
          </div>
        </div>
        <div id="callBriefCoverageBar" class="call-brief-coverage"></div>
        <div id="callBriefContent" class="call-brief-body">
          <div class="cb-card"><div style="color:var(--text-muted); font-size:13px;">正在聚合聊天记录、Soul 记忆、朋友圈动态与 CRM 信息…</div></div>
        </div>
      </div>
    </div>

    <!-- Conversational Document & PDF Knowledge Ingest Dialog (#docIngestOverlay) -->
    <dialog id="docIngestOverlay" class="doc-ingest-dialog" closedby="any" aria-labelledby="docIngestModalTitle">
      <div class="doc-ingest-head">
        <div>
          <h2 id="docIngestModalTitle">📄 喂资料入库 · AI 自动学习与知识沉淀</h2>
          <p>上传 PDF / TXT / MD / JSON 手册或直接粘贴产品资料，一句话说明客服要求，AI 自动拆解并可选绑进知识库</p>
        </div>
        <button type="button" class="btn-outline sm" onclick="hideDocIngestModal()" aria-label="关闭喂资料入库弹窗">关闭</button>
      </div>
      <div class="doc-ingest-body" id="docIngestModalBody">
        <section class="doc-ingest-section" aria-label="上传或粘贴产品资料">
          <div class="doc-ingest-row-2">
            <div class="doc-ingest-field">
              <label for="docIngestFile">1. 选择资料文件（.pdf / .txt / .md / .json）</label>
              <div class="doc-ingest-file-box">
                <input type="file" id="docIngestFile" name="docIngestFile" accept=".pdf,.txt,.md,.json" onchange="handleDocIngestFileChange(this)" />
                <div id="docIngestFileMeta" class="doc-ingest-file-meta">支持 PDF 文本与扫描页自动识别（≤25MB）</div>
              </div>
            </div>
            <div class="doc-ingest-field">
              <label for="docIngestDocName">资料名称（可选，留空自动识别）</label>
              <input type="text" id="docIngestDocName" name="docIngestDocName" placeholder="例如：极光净水器 S1 产品手册" />
            </div>
          </div>
          <div class="doc-ingest-field">
            <label for="docIngestText">2. 或直接粘贴长文本产品资料 / 问答口径</label>
            <textarea id="docIngestText" name="docIngestText" rows="5" placeholder="粘贴产品介绍、核心卖点、使用方法、注意事项或常见客户问答…（如已选择 PDF 文件可留空或补充重点）"></textarea>
          </div>
          <div class="doc-ingest-field">
            <label for="docIngestInstruction">3. 你的接待需求指令</label>
            <input type="text" id="docIngestInstruction" name="docIngestInstruction" value="希望你能够替代我去和顾客聊天" placeholder="例如：希望你能够替代我去和顾客聊天，先共情再按资料作答" />
          </div>
          <div class="doc-ingest-actions">
            <button type="button" id="docIngestPreviewBtn" class="btn-solid" onclick="previewDocIngest()">🤖 AI 解析资料</button>
            <button type="button" class="btn-outline sm" onclick="resetDocIngestForm()">清空重填</button>
            <span id="docIngestStatus" class="doc-ingest-status" role="status" aria-live="polite"></span>
          </div>
        </section>

        <section id="docIngestResultPane" class="doc-ingest-section" hidden aria-label="解析结果与确认执行任务">
          <div id="docIngestPreviewMeta" class="doc-ingest-preview-meta"></div>
          <fieldset class="doc-strategy-fieldset">
            <legend>方案对比（请选择执行策略）</legend>
            <div id="docIngestStrategyGrid" class="doc-strategy-grid"></div>
          </fieldset>
          <div class="doc-draft-toolbar">
            <strong id="docIngestItemsHeading" style="font-size:12.5px;">拆解后的结构化知识卡片（可勾选 / 微调）</strong>
            <div style="display:flex; gap:8px; align-items:center;">
              <button type="button" class="link-btn" onclick="docIngestSelectAll(true)">全选</button>
              <button type="button" class="link-btn" onclick="docIngestSelectAll(false)">全不选</button>
            </div>
          </div>
          <div id="docIngestItemsList" class="doc-draft-list"></div>
          <div id="docIngestConfirmCard" class="doc-confirm-card">
            <div id="docIngestConfirmTitle" class="doc-confirm-title">确认执行任务 · 绑进知识库</div>
            <div id="docIngestConfirmSummary" class="doc-confirm-summary">保持现有营销人设不变，将已勾选条目批量写入 FTS5 知识库。</div>
            <div class="doc-confirm-actions">
              <button type="button" id="docIngestContinueEditBtn" class="btn-outline" onclick="continueEditingDocIngest()">继续修改</button>
              <button type="button" id="docIngestConfirmBtn" class="btn-solid" onclick="confirmDocIngest()">确认</button>
            </div>
          </div>
        </section>
      </div>
    </dialog>

    <!-- Tab 2 (Default Chat-First Home): Live Chat & AI Copilot -->
    <section id="tab-monitor" class="tab-panel active">
      <div class="chat-workspace">
        <aside class="home-conversations" aria-label="最近会话">
          <div class="bs-view-switcher" role="tablist" aria-label="工作台视图切换">
            <button type="button" class="bs-view-tab active" aria-selected="true" onclick="switchTab('monitor')">会话</button>
            <button type="button" class="bs-view-tab" aria-selected="false" onclick="switchTab('care')">联系人</button>
            <button type="button" class="bs-view-tab" aria-selected="false" onclick="switchTab('knowledge')">知识库</button>
            <button type="button" class="bs-view-tab" aria-selected="false" onclick="location.href='/workbench'">待办</button>
          </div>
          <div id="sidebarWatchPanel" class="sidebar-watch-panel" aria-label="关注与监视好友">
            <div class="sidebar-watch-head">
              <span>👁️ 关注好友 <span id="watchedCountBadge" class="conversation-count"></span></span>
              <span style="display:inline-flex; align-items:center; gap:4px; flex-shrink:0;">
                <button type="button" id="sidebarPopoutAllBtn" class="btn-outline sm sidebar-add-watch-btn" onclick="openWatchedPopoutWindows()" title="一键将所有已关注好友弹出独立微信/企微聊天小窗">🪟 小窗</button>
                <button type="button" id="sidebarAddWatchBtn" class="btn-outline sm sidebar-add-watch-btn" onclick="toggleSidebarWatchDrawer()" aria-expanded="false" aria-controls="sidebarWatchDrawer" title="添加关注 / 监视好友（对方发消息时自动回复）">＋ 关注</button>
              </span>
            </div>
            <div id="sidebarWatchedChips" class="sidebar-watched-chips" aria-live="polite"></div>
            <div id="sidebarWatchDrawer" class="sidebar-watch-drawer" hidden>
              <div class="sidebar-watch-input-row">
                <input type="text" id="sidebarWatchInput" placeholder="输入微信/企微好友或机器人名（如 clawBOT）" aria-label="关注的好友或机器人名称" onkeydown="if(event.key==='Enter'){event.preventDefault();submitSidebarWatchContact();}" />
                <button type="button" id="sidebarWatchSubmitBtn" class="btn-solid sm" onclick="submitSidebarWatchContact()">＋ 关注并自动回复</button>
              </div>
              <label class="sidebar-watch-autostart">
                <input type="checkbox" id="sidebarWatchAutoStart" checked />
                <span>对方发消息时立即自动回复</span>
              </label>
              <div>
                <div class="sidebar-watch-candidates-label">快捷添加推荐（点击即关注）：</div>
                <div id="sidebarWatchCandidates" class="sidebar-watch-candidates"></div>
              </div>
            </div>
          </div>
          <details class="chat-thread-list" id="conversationThreads" open>
            <summary class="thread-summary-row">
              <span>最近会话 <span id="conversationCount" class="conversation-count"></span></span>
              <span style="display:inline-flex; align-items:center; gap:5px;">
                <button type="button" id="refreshAvatarsBtn" class="btn-outline sm" style="padding:1px 7px; font-size:11px; line-height:1.4; min-height:22px;" onclick="event.preventDefault(); event.stopPropagation(); refreshSidebarAvatars()" title="实时扫描微信/企微窗口并批量更新左侧联系人头像">🖼️ 更新头像</button>
                <button type="button" id="threadListPlusBtn" class="thread-plus-btn" onclick="event.preventDefault(); event.stopPropagation(); toggleSidebarWatchDrawer(true)" title="添加关注/监视好友（对方发消息时自动回复）" aria-label="添加关注或监视好友">＋</button>
              </span>
            </summary>
            <div id="monitorEventsList"><p class="home-empty">正在读取最近会话…</p></div>
          </details>
          <div class="chat-list-head">
            <button type="button" class="link-btn" onclick="triggerWatchOnce(false)" aria-describedby="watchPreviewHint">🔍 巡检会话</button>
            <button type="button" id="sidebarSettingsBtn" class="btn-outline sm" onclick="openSettingsModal()" style="padding:3px 9px; font-size:11.5px;">⚙️ 设置</button>
            <p id="watchPreviewHint" class="chat-feedback">可能切换微信会话，只生成草稿，不发送。</p>
          </div>
          <div id="watchRunReceipt" style="display:none;"></div>
        </aside>

        <main class="chat-main-pane" aria-labelledby="conversationHeading">
          <details class="hosting-panel perm-panel" id="permPanel">
            <summary id="permSummary">🔐 系统权限检查（首次使用必读）</summary>
            <div id="permPanelBody" style="margin-top:10px;">
              <div class="perm-items" id="permItems"><p class="hosting-empty">正在检查系统权限…</p></div>
              <div class="perm-actions">
                <a id="permOpenSettings" class="btn-outline" href="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" style="text-decoration:none;">⚙️ 打开系统设置 · 隐私与安全性</a>
                <button type="button" id="permRecheckBtn" class="btn-solid" onclick="window.PERM_MODAL_DISMISSED = false; loadPermissions(true)">🔄 重新检查</button>
                <span class="hosting-hint" id="permHint">授权后回到这里点「重新检查」即可，无需重启。</span>
              </div>
            </div>
          </details>
          <div class="hosting-panel" id="hostingPanel">
            <div class="hosting-top-row">
              <div class="hosting-status">
                <span id="hostingBadge" class="hosting-badge off">⚪ 托管未开启</span>
                <button type="button" id="hostingGuardPill" class="hosting-badge guard-ready" onclick="openSettingsModal('guard')" title="防抢鼠标/键盘自动让路守卫：点击可调整等待与空窗参数">🛡️ 防抢鼠标护航中</button>
                <span id="hostingMeta" class="hosting-meta">加载中…</span>
              </div>
              <div class="hosting-actions">
                <details class="hosting-picker">
                  <summary>托管好友 <span id="hostingCheckedCount" class="conversation-count"></span> ▾</summary>
                  <div class="hosting-picker-popover">
                    <div class="hosting-toolbar">
                      <button type="button" class="link-btn" onclick="hostingSelectAll(true)">全选</button>
                      <button type="button" class="link-btn" onclick="hostingSelectAll(false)">清空</button>
                      <button type="button" class="link-btn" onclick="refreshHostingFriends()">刷新好友列表</button>
                      <span class="hosting-hint">勾选即托管对象；也可在下方直接新增关注好友。</span>
                    </div>
                    <div class="hosting-quick-add">
                      <input type="text" id="hostingQuickAddInput" placeholder="新增关注好友名（如 clawBOT）" aria-label="新增关注好友名" onkeydown="if(event.key==='Enter'){event.preventDefault();quickAddWatchFromHostingPicker();}" />
                      <button type="button" id="hostingQuickAddBtn" class="btn-solid sm" onclick="quickAddWatchFromHostingPicker()">＋ 添加关注</button>
                    </div>
                    <ul class="hosting-friend-list" id="hostingFriendList"><li class="hosting-empty">正在读取好友列表…</li></ul>
                  </div>
                </details>
                <div class="window-picker-wrap">
                  <button type="button" id="appWindowPickerBtn" class="btn-outline sm" aria-expanded="false" aria-controls="windowPickerPopover" onclick="toggleWindowPickerPopover()" title="选择并绑定微信或企业微信窗口（支持独立聊天小窗免切换直连）">🪟 窗口: 自动</button>
                  <div id="windowPickerPopover" class="window-picker-popover" popover="auto" aria-label="微信与企业微信窗口选择器">
                    <div class="window-picker-head">
                      <div>
                        <strong>🪟 选择应用 / 聊天窗口</strong>
                        <div class="window-picker-sub">微信 + 企业微信 · 独立小窗免切换直连</div>
                      </div>
                      <div class="window-picker-head-actions">
                        <button type="button" class="link-btn" onclick="refreshAppWindows(true)">🔄 刷新</button>
                        <button type="button" class="link-btn" onclick="bindAppWindow({ appId: 'auto', windowID: null, windowTitle: '' })">自动跟随</button>
                      </div>
                    </div>
                    <div id="windowPickerAppsSummary" class="window-picker-apps">正在检测应用状态…</div>
                    <div class="window-picker-scheduler-bar" id="windowPickerSchedulerBar">
                      <label class="border-toggle-label" for="borderOverlayToggle" title="开启后在白名单独立聊天小窗外围渲染透明点击穿透呼吸边框（🟢 守护中 / 🔵 思考中 / 🟠 让路中）">
                        <input type="checkbox" id="borderOverlayToggle" onchange="toggleBorderOverlay(this.checked)" />
                        <span>🟢 透明呼吸边框</span>
                        <span id="popoverBorderStateBadge" class="border-state-chip off">⚪ 已关闭</span>
                      </label>
                      <button type="button" id="runMultiWinSchedulerBtn" class="btn-outline sm" onclick="runMultiWindowScheduler(false)" title="执行 dHash 64位初筛 + 快慢双车道分流 + 优先级老化队列诊断">⚡ 跑一轮多窗调度诊断</button>
                    </div>
                    <div id="popoverSchedulerSummary" class="scheduler-diag-panel" hidden></div>
                    <div id="windowPickerBody" class="window-picker-body">
                      <div class="hosting-empty">正在扫描微信与企业微信可见窗口…</div>
                    </div>
                    <div class="window-picker-foot">🔒 非白名单独立小窗仅作只读保护，禁止一键开启发送托管</div>
                  </div>
                </div>
                <button type="button" id="popoutWatchedWindowsBtn" class="btn-outline sm" onclick="openWatchedPopoutWindows()" title="为所有已关注/托管好友自动双击弹出独立聊天小窗">🪟 弹出小窗</button>
                <button type="button" id="hostingEnableBtn" class="btn-solid hosting-btn" onclick="applyHosting(true)">🚀 一键托管</button>
                <button type="button" id="hostingDisableBtn" class="btn-outline sm" onclick="applyHosting(false)">⏹ 停止</button>
                <button type="button" id="speedModeBtn" class="btn-outline sm" onclick="toggleWorkosSpeedMode()" title="在「⚡ 极速」低延迟与「🔬 深思」深度推理档位间切换">⚡ 极速</button>
                <button type="button" id="workosModalBtn" class="btn-outline sm" onclick="openSettingsModal('workos')" title="查看 AI WorkOS 治理、评估、反思与进化面板">🔄 进化</button>
                <button type="button" id="mobileRemoteBtn" class="btn-outline sm" onclick="openMobileRemoteOverlay()" title="打开手机伴侣遥控台 (/mobile)">📱 遥控</button>
                <button type="button" id="llmFixBtn" class="btn-outline sm" onclick="relaunchLlmGateway()" hidden>🔧 启动 Magpie（修复 LLM 网关）</button>
                <button type="button" id="diagBtn" class="btn-outline sm" onclick="loadDiagnostics(true)">🩺 诊断</button>
              </div>
            </div>
          </div>
          <div class="workos-goal-bar" id="workosGoalBar" aria-label="AI 员工岗位目标">
            <div class="workos-presets" role="group" aria-label="AI 员工岗位模板">
              <button type="button" class="workos-preset-btn active" data-workos-preset="private_ops" onclick="selectWorkosPreset('private_ops')">私域运营</button>
              <button type="button" class="workos-preset-btn" data-workos-preset="tech_consultant" onclick="selectWorkosPreset('tech_consultant')">售前顾问</button>
              <button type="button" class="workos-preset-btn" data-workos-preset="community_steward" onclick="selectWorkosPreset('community_steward')">社群管家</button>
            </div>
            <div class="workos-goal-input-wrap">
              <label for="workosGoalInput" style="white-space:nowrap; font-weight:600; color:var(--text-secondary);">🎯 目标</label>
              <input type="text" id="workosGoalInput" value="接待咨询，回答产品与技术问题，收集客户需求并沉淀常见问答 SOP" placeholder="一句话设定 AI 员工任务目标…" />
              <button type="button" class="btn-outline sm" style="padding:2px 8px !important; min-height:24px !important; font-size:11.5px !important;" onclick="saveWorkosGoal()">应用</button>
            </div>
            <span class="workos-esc-hint" title="在工作台任一位置连按两次 Esc 键可立即暂停托管">⌨️ 双击 Esc 暂停</span>
          </div>
          <div class="chat-pane-head">
            <div style="display:flex; align-items:baseline; gap:8px; min-width:0;">
              <h1 id="conversationHeading" class="conversation-heading">对话</h1>
              <span class="hosting-hint">生成草稿自动针对最新来信</span>
            </div>
            <div class="conversation-recipient">
              <label for="previewTarget">回复对象</label>
              <input type="text" id="previewTarget" placeholder="选择最近会话，或输入会话名称" oninput="syncChatRecipient(this.value)" />
              <button type="button" id="chatTestContactBtn" class="btn-outline sm" style="white-space:nowrap; flex-shrink:0;" onclick="toggleActiveChatTestContact()" title="将该联系人标记为内部测试好友（允许 # 纠偏指令并从客户 CRM 统计中剔除）">🧪 设为测试好友</button>
              <button type="button" id="chatHeadCallBriefBtn" class="btn-outline sm" style="white-space:nowrap; flex-shrink:0;" onclick="openCallBriefFromChat()" title="电话前一键速览：聚合历史聊天、Soul 记忆、朋友圈近况与话术提词卡">📋 电话前速览</button>
            </div>
          </div>

          <div class="chat-stream-card">
            <div class="chat-bubble-wrap">
              <div class="chat-bubble-head">💬 聊天记录 <span id="chatStreamTarget" class="conversation-count"></span></div>
              <div id="chatBubbleStream" class="chat-bubble-stream" aria-live="polite"><div class="bubble-sep">选择左侧会话查看往来记录</div></div>
              <details class="chat-paste-details">
                <summary>✏️ 手动粘贴来信（覆盖自动提取）</summary>
                <textarea id="pasteIncoming" placeholder="粘贴需要回复的消息…" oninput="document.getElementById('previewIncoming').value = this.value;"></textarea>
              </details>
              <textarea id="previewIncoming" style="display:none;" aria-hidden="true" tabindex="-1"></textarea>
            </div>
          </div>

          <div class="chat-composer">
            <input type="hidden" id="sendTarget" />
            <div class="composer-head-row">
              <label for="sendText" class="chat-field-label">回复草稿</label>
              <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                <p class="chat-feedback" id="saveDraftHint">手动加入待办不会发送。</p>
                <p class="chat-feedback" id="sendModeHint">模拟检查不写入微信。</p>
                <p class="draft-status" id="draftStatus" role="status" hidden></p>
              </div>
            </div>
            <div id="emojiQuickBar" style="display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-bottom:6px; font-size:12px;">
              <span style="color:var(--text-muted); font-size:11.5px;">😊 微信小表情：</span>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[旺柴]')">[旺柴]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[捂脸]')">[捂脸]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[机智]')">[机智]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[破涕为笑]')">[破涕为笑]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[呲牙]')">[呲牙]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[偷笑]')">[偷笑]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[吃瓜]')">[吃瓜]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[让我看看]')">[让我看看]</button>
              <button type="button" class="btn-outline sm" onclick="insertWeChatEmoji('[苦笑]')">[苦笑]</button>
              <button type="button" class="btn-outline sm" onclick="sendWeChatStickerQuick('favorites', 0)" title="点击微信表情面板「❤️ 收藏表情」第1个并发送">❤️ 发收藏表情</button>
              <input type="text" id="quickImageQuery" placeholder="搜图词/框选词(逗号分隔)" style="width:148px; padding:3px 7px; font-size:11.5px; border:1px solid var(--border); border-radius:6px; background:var(--surface); color:var(--text);" />
              <input type="text" id="quickAnnotateNote" placeholder="红框标注说明" style="width:116px; padding:3px 7px; font-size:11.5px; border:1px solid var(--border); border-radius:6px; background:var(--surface); color:var(--text);" />
              <button type="button" class="btn-outline sm" onclick="searchAndSendWebImageQuick()" title="联网搜图并发送给当前好友">🔍 搜图发送</button>
              <button type="button" class="btn-outline sm" onclick="annotateAndSendImageQuick()" title="对好友发来的图片画红框编号标注重点并回传">🖍️ 标注图片回传</button>
              <button type="button" class="btn-outline sm" onclick="joinTencentMeetingQuick()" title="点击微信里的腾讯会议卡片入会并拉起 Bot Studio 语音参会发言">🎧 点卡片入会+Bot发言</button>
              <button type="button" id="chatBarCallBriefBtn" class="btn-solid sm" onclick="openCallBriefFromChat()" title="打电话前先看速览：聚合并提炼近期聊天、朋友圈近况与口语通话话术">📋 电话前速览</button>
              <button type="button" class="btn-outline sm" onclick="voiceCallQuick('dial')" title="向当前好友拨打微信/企微语音电话并用 AI 语音实时对话">📞 打语音电话</button>
              <button type="button" class="btn-outline sm" onclick="voiceCallQuick('answer')" title="一键接听微信/企微来电并连入 AI 语音对话">📲 接听来电</button>
              <button type="button" class="btn-outline sm" onclick="voiceCallQuick('hangup')" title="挂断当前通话并自动恢复本机麦克风">📴 挂断</button>
            </div>
            <div id="supervisorDirectiveBanner" class="supervisor-directive-banner" hidden>
              <span>🛡️ 管理员指令模式：仅指导 AI 改写，不直接发给客户</span>
              <button type="button" class="btn-outline sm" onclick="executeSupervisorDirectiveFromComposer()">立即按指令改写</button>
            </div>
            <textarea id="sendText" placeholder="输入回复，或点下方「生成草稿」/「@元宝 解析」自动起草（以 # 开头进入管理员纠偏指令模式）" oninput="onComposerTextInput()"></textarea>
            <div class="chat-composer-bar">
              <div class="composer-actions">
                <button type="button" id="generateDraftBtn" class="btn-solid" onclick="runReplyPreview()">生成草稿</button>
                <button type="button" id="quickYuanbaoBtn" class="btn-outline" onclick="runQuickWeChatAiAssist('at_yuanbao')" title="在当前会话唤起 @元宝 总结视频号/公众号卡片并自动生成回复草稿">@元宝 解析</button>
                <button type="button" id="quickXiaoweiBtn" class="btn-outline" onclick="runQuickWeChatAiAssist('relay_xiaowei')" title="转发给微信小微/腾讯元宝解析链接、视频与文章并自动生成回复草稿">转发小微</button>
                <button type="button" id="saveDraftBtn" class="btn-outline" aria-describedby="saveDraftHint" onclick="saveConversationDraft()">加入待办</button>
                <button type="button" id="sendActionLabel" class="btn-outline" onclick="executeSafeSend()" aria-describedby="sendModeHint">模拟检查</button>
                <button type="button" id="learnCorrectionBtn" class="btn-outline" onclick="learnFromDraftCorrection()" title="将当前来信与修改后定稿一键沉淀进知识库 SOP，越用越懂你的业务">✨ 纠偏沉淀 SOP</button>
                <button type="button" id="docIngestBtn" class="btn-outline" onclick="openDocIngestModal()" title="上传 PDF / Markdown / TXT 资料或粘贴长文本，AI 自动拆解并绑进知识库">📄 喂资料入库</button>
                <button type="button" id="composerSettingsBtn" class="btn-outline" onclick="openSettingsModal('reply')" title="打开回复性格、模型与发送安全设置">⚙️ 设置</button>
              </div>
              <div class="saved-draft-feedback">
                <p id="savedDraftStatus" role="status"></p>
                <a id="openSavedTask" href="/workbench" hidden>查看待办</a>
              </div>
            </div>
            <div id="quickAiAssistResult" class="chat-ai-answer" hidden></div>
            <div id="replyPreviewResult" class="chat-ai-answer" hidden></div>
            <div id="draftQualityFeedbackBar" class="quality-feedback-bar" hidden></div>
            <details class="reply-settings">
              <summary>回复设置</summary>
              <div class="chat-context-bar">
                <select id="previewPersona" aria-label="回复性格"></select>
                <select id="previewModelSelect" aria-label="驱动模型"></select>
                <label><input type="checkbox" id="previewUseLlm" checked style="width:auto;" /> 模型和知识库</label>
                <select id="sendMode" class="composer-mode" aria-label="发送安全模式" onchange="syncSendModeLabel()">
                  <option value="dry_run">模拟检查（不写入微信）</option>
                  <option value="silent_verify">粘贴校验后清空</option>
                  <option value="confirm_send">确认并发送</option>
                </select>
              </div>
            </details>
          </div>

          <div id="sendReceiptBox" aria-live="polite"></div>
          <dialog id="confirmSendDialog" aria-labelledby="confirmSendTitle" aria-describedby="confirmSendTarget">
            <form method="dialog" class="send-confirm-form">
              <h2 id="confirmSendTitle">发送到微信？</h2>
              <p id="confirmSendTarget"></p>
              <blockquote id="confirmSendExcerpt"></blockquote>
              <div class="send-confirm-actions">
                <button type="submit" class="btn-outline" value="cancel" autofocus>返回修改</button>
                <button type="submit" class="btn-solid" value="send">确认发送</button>
              </div>
            </form>
          </dialog>

          <details class="chat-tools-drawer">
            <summary>媒体与智能体工具</summary>
            <div class="panel-card" id="visionAgentDispatchPanel" style="border:none !important; padding:0 !important;">
              <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:10px; flex-wrap:wrap;">
                <div style="font-size:12.5px; color:var(--text-secondary);">读取链接和媒体，或配置指定会话的智能体。</div>
                <div style="display:flex; gap:6px;">
                  <button type="button" class="sm" onclick="loadOverview(true)">刷新</button>
                </div>
              </div>
              <div class="metrics-row" style="grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom:12px;">
                <div class="mini-stat"><div class="k">1 层巡检</div><div class="v" id="vStackLayer1" style="font-size:12.5px;">Apple Vision 2x OCR</div></div>
                <div class="mini-stat"><div class="k">2 层深读</div><div class="v" id="vStackLayer2" style="font-size:12.5px;">—</div></div>
                <div class="mini-stat"><div class="k">侧栏贴靠</div><div class="v" id="vStackDock" style="font-size:12.5px;">--</div></div>
                <div class="mini-stat"><div class="k">派活/深读数</div><div class="v" id="vStackCounts" style="font-size:12.5px;">0 / 0</div></div>
              </div>
              <div class="grid-2" style="margin-bottom:12px;">
                <div class="field-box">
                  <div style="font-size:13px; font-weight:600; margin-bottom:8px;">绑定智能体到好友/群</div>
                  <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
                    <input type="text" id="agentBindTarget" placeholder="好友或群名" aria-label="绑定的会话" />
                    <input type="text" id="agentBindId" value="bot_wechat_ecosystem" placeholder="智能体 ID" />
                    <input type="text" id="agentBindName" value="WeChat Bot" placeholder="显示名" />
                    <select id="agentBindType">
                      <option value="botstudio">botstudio</option>
                      <option value="dsh">dsh</option>
                      <option value="openbot">openbot</option>
                      <option value="custom">custom</option>
                    </select>
                  </div>
                  <div style="display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; margin-bottom:8px;">
                    <input type="text" id="agentBindVisionModel" value="auto/deepseek-v4.1-flash" />
                    <button type="button" class="primary sm" onclick="bindFriendAgent()">保存绑定</button>
                  </div>
                  <div style="display:flex; gap:12px; flex-wrap:wrap; font-size:12px; margin-bottom:8px;">
                    <label style="display:flex; align-items:center; gap:5px; cursor:pointer;"><input type="checkbox" id="agentAutoDispatch" checked style="width:auto;" /> 自动派活</label>
                    <label style="display:flex; align-items:center; gap:5px; cursor:pointer;"><input type="checkbox" id="agentAutoAnalyzeMedia" checked style="width:auto;" /> 自动深读媒体</label>
                  </div>
                  <div id="boundAgentsList" class="chip-row"></div>
                </div>
                <div class="field-box">
                  <div style="font-size:13px; font-weight:600; margin-bottom:8px;">链接 / 图片 / 视频深读</div>
                  <div style="display:grid; grid-template-columns:110px 1fr; gap:8px; margin-bottom:8px;">
                    <select id="mediaKindSelect">
                      <option value="link">网页链接</option>
                      <option value="image">图片/图文卡</option>
                      <option value="video">视频/播放窗</option>
                    </select>
                    <input type="text" id="mediaContactInput" placeholder="关联会话（可选）" aria-label="媒体关联的会话" />
                  </div>
                  <input type="text" id="mediaUrlOrPathInput" placeholder="URL 或本地路径" aria-label="媒体地址" style="margin-bottom:8px; width:100%;" />
                  <input type="text" id="mediaContextInput" placeholder="好友附言/指令补充" style="margin-bottom:8px; width:100%;" />
                  <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px;">
                    <button type="button" class="primary sm" onclick="runMediaDeepRead(false)">执行深读分析</button>
                    <button type="button" class="sm" onclick="runMediaDeepRead(true)">读取当前媒体窗</button>
                    <button type="button" class="sm" onclick="runWeChatAiAssist('at_yuanbao')" title="在当前会话发送 @元宝 总结视频号/公众号文章并写入客服记忆">@元宝 辅助解析</button>
                    <button type="button" class="sm" onclick="runWeChatAiAssist('relay_xiaowei')" title="转发给微信小微/腾讯元宝会话解析链接、视频与文章并写回记忆">转发小微解析</button>
                  </div>
                  <div id="mediaAnalysisPreviewBox" style="font-size:12px; color:var(--text-secondary);"></div>
                </div>
              </div>
              <div class="grid-2">
                <div>
                  <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">
                    <strong style="font-size:12.5px;">最近派活回执</strong>
                    <div style="display:flex; gap:6px;"><input type="text" id="dispatchTargetInput" placeholder="会话名称" aria-label="派发来源会话" style="width:120px;" /><button type="button" class="sm" onclick="runAgentDispatchFor()">派发</button></div>
                  </div>
                  <div class="event-list" id="agentDispatchReceiptsBox" style="max-height:200px;"></div>
                </div>
                <div>
                  <strong style="font-size:12.5px; display:block; margin-bottom:6px;">最近媒体深读记录</strong>
                  <div class="event-list" id="mediaAnalysesList" style="max-height:200px;"></div>
                </div>
              </div>
            </div>
          </details>
        </main>
      </div>
    </section>

    <section id="tab-stats" class="tab-panel" aria-labelledby="statsTitle">
      <div class="stats-heading">
        <h1 id="statsTitle" class="contact-heading" tabindex="-1">统计</h1>
        <button type="button" class="btn-outline sm" onclick="loadOverview(true); loadBackgroundObservation()">刷新</button>
      </div>
      <p id="statsCaption" class="stats-caption" role="status">正在读取本地统计…</p>
      <section class="stats-sheet" aria-labelledby="priorityStatsTitle">
        <h2 id="priorityStatsTitle">特别关心与重点关照</h2>
        <div class="priority-actions">
          <button type="button" class="btn-outline sm" id="specialCareShortcut" onclick="openContactGroup('special_care')">查看特别关心</button>
          <button type="button" class="btn-outline sm" id="vipShortcut" onclick="openContactGroup('vip')">查看重点关照</button>
        </div>
        <p class="chat-feedback" id="priorityStatsEmpty"></p>
        <ul class="priority-people" id="statsPriorityList" role="list"></ul>
      </section>
      <section class="stats-sheet" aria-labelledby="backgroundTitle">
        <h2 id="backgroundTitle">后台巡检</h2>
        <div class="background-actions">
          <strong id="backgroundState" aria-live="polite">正在读取</strong>
          <button type="button" id="backgroundToggle" class="btn-outline sm" onclick="toggleBackgroundObservation()" disabled>开始巡检</button>
        </div>
        <p class="chat-feedback" id="backgroundDescription">持续读取可见微信窗口，不抢前台，不切换会话，不回复消息。</p>
        <dl class="stat-rows">
          <div><dt>已完成检查</dt><dd id="backgroundChecks">—</dd></div>
          <div><dt>可见会话 / 未读</dt><dd id="backgroundSessions">—</dd></div>
          <div><dt>上次检查</dt><dd id="backgroundLastChecked">—</dd></div>
        </dl>
      </section>
      <section class="stats-sheet" aria-labelledby="historyStatsTitle">
        <h2 id="historyStatsTitle">本地历史</h2>
        <dl class="stat-rows" id="kpiGrid">
          <div><dt>已分析消息</dt><dd><strong id="kpiMsgs">—</strong><span class="stats-meta" id="kpiMsgsSub"></span></dd></div>
          <div><dt>会话 / 已绑定</dt><dd><strong id="kpiProfileCount">—</strong><span class="stats-meta" id="kpiWarmthSub"></span></dd></div>
          <div><dt>平均互动温度</dt><dd id="kpiWarmth">—</dd></div>
          <div><dt>特别关心 / 重点</dt><dd><strong id="kpiSpecialCare">—</strong><span class="stats-meta" id="kpiSpecialCareSub"></span></dd></div>
          <div><dt>旧版监控</dt><dd><strong id="kpiMonitor">—</strong><span class="stats-meta" id="kpiMonitorSub"></span></dd></div>
          <div><dt>知识库</dt><dd><strong id="kpiKb">—</strong><span class="stats-meta" id="kpiKbSub"></span></dd></div>
          <div><dt>安全护栏</dt><dd><strong id="kpiGuard">—</strong><span class="stats-meta" id="kpiGuardSub"></span></dd></div>
        </dl>
      </section>
      <section class="stats-sheet" aria-labelledby="slotsTitle">
        <h2 id="slotsTitle">活跃时段</h2>
        <p class="chat-feedback" id="slotsSummary"></p>
        <div class="stats-time" id="globalSlotsBar"></div>
      </section>
      <section class="stats-sheet" aria-labelledby="recentStatsTitle">
        <h2 id="recentStatsTitle">最近监控事件</h2>
        <p class="chat-feedback" id="statsEventCaption"></p>
        <ul class="stats-event-list" id="statsEventList"></ul>
      </section>
    </section>

    <section id="tab-care" class="tab-panel">
      <div class="stats-heading">
        <h1 id="contactsHeading" class="contact-heading" tabindex="-1">联系人</h1>
        <button type="button" id="contactBack" class="btn-outline sm" onclick="closeContactProfile()" hidden>返回名单</button>
        <button type="button" id="contactStatsBack" class="btn-outline sm" onclick="openStatsFromContacts()">查看总览统计</button>
      </div>
      <details class="hosting-panel" id="historyImportPanel">
        <summary>📥 导入历史聊天记录（支持勾选部分 / 一键全部导入）</summary>
        <div class="hosting-toolbar">
          <input type="text" id="historySourceDir" class="history-source-input"
                 placeholder="历史文件所在目录（*_history.json）"
                 value="/Volumes/SanDisk/WeChatBot/logs/contacts" style="flex:1; min-width:260px;" />
          <button type="button" class="btn-solid sm" onclick="scanHistorySources()">扫描目录</button>
        </div>
        <div class="hosting-toolbar">
          <button type="button" class="link-btn" onclick="historySelectAll(true)">全选</button>
          <button type="button" class="link-btn" onclick="historySelectAll(false)">清空</button>
          <button type="button" id="historyImportBtn" class="btn-solid sm" onclick="importHistorySources()">📥 导入所选历史</button>
          <button type="button" id="historyImportAllBtn" class="btn-outline sm" onclick="importHistorySourcesAll()">📥 一键导入全部</button>
          <span class="hosting-hint">导入后联系人画像 / 来信统计 / 机器人记忆上下文立即生效。</span>
        </div>
          <ul class="hosting-friend-list" id="historySourceList"><li class="hosting-empty">点「扫描目录」读取历史文件列表。</li></ul>
        <p class="hosting-hint" id="historyImportStatus" role="status"></p>
        <div style="border-top:1px solid var(--border); margin:12px 0 10px; padding-top:12px;">
          <div class="hosting-toolbar">
            <span class="hosting-hint" style="font-weight:600;">📄 从聊天记录文件导入（微信「聊天记录迁移」导出的 .zip / .txt / 文件夹）：</span>
          </div>
          <div class="hosting-toolbar">
            <input type="text" id="chatlogFilePath" placeholder="聊天记录文件路径（.zip / .txt / 文件夹）" style="flex:1; min-width:220px;" />
          </div>
          <div class="hosting-toolbar">
            <input type="text" id="chatlogTarget" placeholder="聊天对象名称（会话存到该联系人名下）" style="flex:1; min-width:180px;" />
            <input type="text" id="chatlogOwner" placeholder="我的微信昵称（可选，用于区分我方/对方）" style="flex:1; min-width:180px;" />
            <button type="button" id="chatlogImportBtn" class="btn-solid sm" onclick="importChatlogFile()">📄 解析并导入</button>
          </div>
          <p class="hosting-hint" id="chatlogImportStatus" role="status">导入后立即进入联系人画像 / 往来上下文 / CRM。</p>
        </div>
      </details>
      <div class="filter-bar" id="contactFilters">
        <div class="filter-pills" id="contactFilterPills">
          <button type="button" class="filter-pill active" data-filter="all" aria-pressed="true" onclick="setContactFilter('all')">全部会话</button>
          <button type="button" class="filter-pill" data-filter="special_care" aria-pressed="false" onclick="setContactFilter('special_care')">特别关心</button>
          <button type="button" class="filter-pill" data-filter="vip" aria-pressed="false" onclick="setContactFilter('vip')">重点关照</button>
          <button type="button" class="filter-pill" data-filter="bound" aria-pressed="false" onclick="setContactFilter('bound')">已绑定画像</button>
          <button type="button" class="filter-pill" data-filter="folder" aria-pressed="false" onclick="setContactFilter('folder')">折叠容器</button>
        </div>
        <div style="width:240px; max-width:100%;">
          <input type="search" id="contactSearchInput" aria-label="搜索联系人" placeholder="搜索好友 / 群名 / 话题..." oninput="renderContacts()" />
        </div>
      </div>

      <ul class="priority-people" role="list" id="contactsPriorityList" hidden></ul>
      <div class="grid-2" id="contactsGrid"></div>
    </section>

    <!-- Tab 3: KF Knowledge & Terminology Studio -->
    <section id="tab-knowledge" class="tab-panel">
      <div class="panel-card">
        <div class="section-header">
          <div>
            <h2 class="section-title">微信企业客服知识库与专业术语管理 (FTS5)</h2>
            <div class="section-desc" id="kbDbPathDesc">支持 OpenBot 本地知识库同步 + 术语 / 话术 / FAQ / 知识条目在线检索与发布</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button type="button" id="kbDocIngestBtn" class="sm primary" onclick="openDocIngestModal()">📄 喂资料 / PDF 入库</button>
            <button class="sm accent" onclick="syncOpenBotKb()">🔄 同步 OpenBot SQLite 知识库</button>
          </div>
        </div>

        <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:6px;">
          <div style="flex:1; min-width:220px;">
            <input type="search" id="kbSearchInput" placeholder="有什么可以帮你？输入客户原话测试机器人会怎么答（如：你们是做什么的、多少钱）..." onkeydown="if(event.key==='Enter') searchKb();" />
          </div>
          <div style="width:170px;">
            <select id="kbKindFilter" onchange="searchKb()">
              <option value="">全部分类</option>
              <option value="terminology">terminology · 专业术语</option>
              <option value="knowledge">knowledge · 业务知识</option>
              <option value="script">script · 客服话术</option>
              <option value="faq">faq · 常见问题</option>
            </select>
          </div>
          <button class="accent" onclick="searchKb()">🔍 FTS5 检索</button>
          <button onclick="resetKbView()">显示全部</button>
        </div>
        <div class="kb-hero-hint">🔥 热门问题（点一下看机器人会怎么答）：</div>
        <div class="kb-chip-row" id="kbQuickChips"></div>
        <div class="kb-grid" id="kbKindGrid"></div>

        <details style="background:var(--surface-soft); border-radius:12px; padding:12px 14px; margin-bottom:16px;">
          <summary style="cursor:pointer; font-weight:600; font-size:13.5px;">➕ 新增专业术语 / 客服知识条目</summary>
          <div style="display:grid; grid-template-columns:2fr 1fr 1.5fr; gap:10px; margin-top:12px;">
            <input type="text" id="kbNewTitle" placeholder="条目标题（例如：特别关心 P0 巡检）" />
            <select id="kbNewKind">
              <option value="terminology">terminology · 术语</option>
              <option value="knowledge">knowledge · 知识</option>
              <option value="script">script · 话术</option>
              <option value="faq">faq · FAQ</option>
            </select>
            <input type="text" id="kbNewKeywords" placeholder="关键词（逗号分隔，如：VIP,特别关心）" />
          </div>
          <div style="margin-top:10px;">
            <textarea id="kbNewBody" placeholder="输入术语定义、标准话术或知识内容..."></textarea>
          </div>
          <div style="margin-top:8px;">
            <button class="primary sm" onclick="saveKbEntry()">💾 发布并写入 FTS5 索引</button>
          </div>
        </details>

        <div class="kb-list" id="kbList"></div>
      </div>
    </section>

    <!-- Tab 4: Magpie Multi-Provider & Multi-Model Hub -->
    <section id="tab-models" class="tab-panel">
      <div class="panel-card">
        <div class="section-header">
          <div>
            <h2 class="section-title">🤖 Magpie 开源多供应商模型网关中心 (dsh-x-magpie 适配)</h2>
            <div class="section-desc" id="modelsGatewayMeta">复用开源 Magpie 网关与多供应商协议，支持 DeepSeek / GLM / Kimi / Qwen / Mistral / MiniMax / Ollama 与自定义接口一键热切</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <label style="display:flex; align-items:center; gap:6px; font-size:12.5px; padding:6px 10px; background:var(--surface-soft); border-radius:10px; cursor:pointer;">
              <input type="checkbox" id="globalLlmToggle" onchange="toggleGlobalLlm(this.checked)" style="width:auto;" />
              <span>启用 LLM 智能回复</span>
            </label>
            <button class="sm accent" onclick="refreshModelsHub()">🔄 同步 Magpie 模型目录</button>
            <button class="sm primary" onclick="probeModel()">⚡ 实测当前默认模型</button>
          </div>
        </div>

        <div class="metrics-row" style="grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom:14px;">
          <div class="mini-stat">
            <div class="k">Magpie 网关状态</div>
            <div class="v" id="mHubGatewayStatus">--</div>
          </div>
          <div class="mini-stat">
            <div class="k">当前全局默认模型</div>
            <div class="v" id="mHubActiveModel">--</div>
          </div>
          <div class="mini-stat">
            <div class="k">降级容灾模型 (Fallback)</div>
            <div class="v" id="mHubFallbackModel">--</div>
          </div>
          <div class="mini-stat">
            <div class="k">已发现模型 / 供应商</div>
            <div class="v" id="mHubCounts">--</div>
          </div>
        </div>

        <div id="modelProbeReceipt" style="display:none; margin-bottom:14px;"></div>

        <div style="font-size:13.5px; font-weight:700; margin-bottom:8px;">已接入多供应商连接池（凭据脱敏保护）</div>
        <div class="provider-grid" id="providersGrid"></div>

        <details style="background:var(--surface-soft); border-radius:12px; padding:12px 14px; margin-bottom:16px;">
          <summary style="cursor:pointer; font-weight:600; font-size:13.5px;">⚙️ 配置 Magpie 网关或新增自定义 OpenAI 兼容供应商</summary>
          <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-top:12px;">
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">供应商 ID (例如 magpie-gateway / deepseek-official)</label>
              <input type="text" id="provIdInput" value="magpie-gateway" />
            </div>
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">显示名称</label>
              <input type="text" id="provNameInput" value="Magpie 多供应商聚合网关" />
            </div>
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">API 协议类型</label>
              <select id="provApiInput">
                <option value="openai-completions">openai-completions</option>
                <option value="openai-responses">openai-responses</option>
                <option value="anthropic-messages">anthropic-messages</option>
              </select>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1.4fr 1fr 1fr; gap:10px; margin-top:10px;">
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">Base URL / 网关地址</label>
              <input type="url" id="provBaseUrlInput" value="http://127.0.0.1:3425" />
            </div>
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">API 密钥（留空保留已存密钥）</label>
              <input type="password" id="provApiKeyInput" placeholder="••••••••" />
            </div>
            <div>
              <label style="font-size:11.5px; color:var(--text-muted);">默认模型 ID</label>
              <input type="text" id="provDefaultModelInput" value="auto/deepseek-v4-pro" />
            </div>
          </div>
          <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
            <button class="primary sm" onclick="saveProviderConfig()">💾 保存供应商配置</button>
            <span style="font-size:12px; color:var(--text-muted);">与 OpenBot openbot-magpie.js 一致：密钥仅存于本机安全配置文件，永不回传明文</span>
          </div>
        </details>

        <div class="filter-bar">
          <div class="filter-pills" id="modelFilterPills"></div>
          <div style="width:260px; max-width:100%;">
            <input type="search" id="modelSearchInput" placeholder="搜索模型 ID / 供应商 / 标签..." oninput="renderModelsCatalog()" />
          </div>
        </div>

        <div class="model-grid" id="modelsCatalogGrid"></div>
      </div>

      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🏷️ 好友专属模型绑定 & Magpie 连接档案</h2>
              <div class="section-desc">参照 MagpieManager useModel 生成 SHA-256 连接 ID (magpie_&lt;hash&gt;)</div>
            </div>
          </div>
          <div id="contactModelBindingsBox" style="margin-bottom:10px;"></div>
          <div id="magpieProfilesBox"></div>
        </div>
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">📊 最近模型调用与探针回执</h2>
              <div class="section-desc">实时记录每一次大模型生成 / 探针探测的供应商与延迟 (ms)</div>
            </div>
          </div>
          <div class="event-list" id="modelCallsList" style="max-height:300px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 5: Standalone Software, Native DSH Plugin, Bot Studio Integration & Open APIs -->
    <section id="tab-open" class="tab-panel">
      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">独立桌面软件与网页控制端 (`v2.4.71`)</h2>
              <div class="section-desc">可脱离 Bot Studio 独立运行：原生 macOS `.app` (Swift Cocoa + WKWebView) + Web Console + CLI</div>
            </div>
            <span class="pill ok" id="standaloneStatusPill"><span class="dot"></span> 检测中</span>
          </div>
          <div id="standaloneSoftwareBody" class="kpi-grid" style="margin-bottom:12px;"></div>
          <pre class="code-box" id="standalonePathsBox"></pre>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🧩 原生 DSH 插件 & Bot Studio 1.0.33 (`dsh2codex`) 集成中心</h2>
              <div class="section-desc">遵循 `openbot.dsh-plugin/1` + `openbot.agent-plugin-catalog/1` 规范，一键编译 4-Tab 页面并导出集成包</div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <button class="sm primary" onclick="compileAndExportBotStudioBundle()">🧩 编译 DSH -> Bot Studio 集成包</button>
              <button class="sm" onclick="rebuildStandaloneAppSilent()">⚡ 一键静默重编 App & 固定签名 (0弹窗)</button>
              <a href="/botstudio-page/" target="_blank" style="text-decoration:none;"><button class="sm accent" type="button">🌐 打开 4-Tab 独立页</button></a>
            </div>
          </div>
          <div id="dshBridgeMetrics" class="kpi-grid" style="margin-bottom:12px;"></div>
          <pre class="code-box" id="dshBridgeOutputsBox"></pre>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🤝 Kimi × OpenBot 场景共创与架构纪要</h2>
              <div class="section-desc" id="kimiMeta">对比 YoBot 与 LeoMusk/wechat-rpa-bot-skill 后落地的场景体系</div>
            </div>
          </div>
          <div id="kimiPanelBody"></div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🔌 YoBot 风格 MCP / HTTP 开放配置</h2>
              <div class="section-desc">单服务同时提供：Web Console (/) + REST API (/api/*) + MCP stdio (`serve-mcp`)</div>
            </div>
            <button class="sm" onclick="copyMcpConfig()">📋 复制 MCP JSON</button>
          </div>
          <pre class="code-box" id="mcpConfigBox"></pre>
          <div style="margin-top:14px;">
            <div style="font-size:13px; font-weight:600; margin-bottom:6px;">极简 CLI 封装 (`./bin/wechat-bot` · 人与 Agent 丝滑调用)</div>
            <pre class="code-box" style="margin-bottom:12px;">./bin/wechat-bot console                          # 启动本地网页控制端 (18788)
./bin/wechat-bot models                           # 查看 Magpie 网关与多供应商模型目录
./bin/wechat-bot model-set auto/deepseek-v4-pro   # 切换全局模型或 --contact 绑定好友专属模型
./bin/wechat-bot model-probe                      # 实测模型连通性与延迟
./bin/wechat-bot care "示例会话" --level special_care # 设置特别关心 / VIP 重点关照
./bin/wechat-bot ask "示例会话" "你好能回复吗"         # FTS5知识库 + 性格 + LLM 预览回复
./bin/wechat-bot watch --confirm-send             # 启动后台实时监控自动回复</pre>
            <div style="font-size:13px; font-weight:600; margin-bottom:6px;">主要本地 HTTP API 端点</div>
            <pre class="code-box">GET  /                    -> 可视化 Web Control Console
GET  /api/overview        -> 全盘聚合状态、统计、特别关心、模型与日志
GET  /api/models          -> Magpie 网关同步模型目录与多供应商状态
POST /api/model-select    -> 切换默认/容灾模型或绑定联系人专属模型
POST /api/model-probe     -> 实测模型单轮对话连通性与延迟
POST /api/provider-save   -> 配置 Magpie 网关或自定义 OpenAI 兼容供应商
POST /api/special-care    -> 切换特别关心 / 重点关照 / 普通三级
POST /api/persona-switch  -> 切换好友专属 AI 性格 / MBTI
POST /api/reply-preview   -> 智能回复（Magpie LLM + FTS5 知识库）预览
POST /api/watch-once      -> 立即执行一轮实时监控巡检</pre>
          </div>
        </div>
      </div>

      <div class="panel-card">
        <div class="section-header">
          <div>
            <h2 class="section-title">📸 实机截图与发送回执画廊</h2>
            <div class="section-desc">真实微信窗口截图、2x Vision OCR 巡检帧与消息发送后像素级校验留证</div>
          </div>
        </div>
        <div class="snapshot-grid" id="snapshotsGrid"></div>
      </div>
    </section>

    <!-- Tab 6: WeChat Article Export to Markdown + Local Assets -->
    <section id="tab-articles" class="tab-panel">
      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">📄 微信文章导出为 Markdown + 本地图片保存</h2>
              <div class="section-desc">支持从当前打开的微信文章窗自动抓取链接/逐页 OCR 裁图，或直接解析 mp.weixin.qq.com URL 并将防盗链图片本地化到 assets/</div>
            </div>
          </div>
          <div class="control-row" style="margin-bottom:12px;">
            <button class="primary" onclick="exportOpenWeChatArticle()">🪟 从当前打开的微信文章一键导出 MD + 图片</button>
          </div>
          <div class="control-row">
            <input id="articleUrlInput" type="text" style="flex:2; min-width:260px;" placeholder="可选：粘贴公众号文章链接 https://mp.weixin.qq.com/s/..." />
            <input id="articlePagesInput" type="number" min="1" max="12" value="4" style="max-width:96px;" title="窗口逐页滚动最大页数" />
            <label style="display:flex; align-items:center; gap:6px; font-size:13px; color:var(--text-muted);">
              <input id="articleDownloadImgs" type="checkbox" checked /> 本地保存图片 (assets/)
            </label>
          </div>
          <div class="control-row" style="margin-top:8px;">
            <button class="accent" onclick="exportWeChatArticleByUrl()">🔗 从输入链接导出 MD + 原图</button>
            <button class="sm" onclick="refreshExportedArticles()">🔄 刷新已导出列表</button>
          </div>
          <div class="section-header" style="margin-top:16px;">
            <div>
              <h3 class="section-title" style="font-size:14px;">已导出文章存档 (exports/articles/)</h3>
            </div>
            <span class="chip" id="exportedCountBadge">0 篇</span>
          </div>
          <div class="event-list" id="exportedArticlesList" style="max-height:360px;"></div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">📝 导出结果预览与本地图片画廊</h2>
              <div class="section-desc" id="articleResultMeta">点击左侧导出按钮或选中已有存档查看 article.md 与 assets/</div>
            </div>
          </div>
          <div class="field-box" id="articlePathsBox" style="margin-bottom:10px; font-size:12px; color:var(--text-muted);">
            尚未选择或导出文章。支持：1) 自动点击微信文章标签 ⋯ 复制链接 + 下载 mmbiz.qpic.cn 高清原图；2) 逐页滚屏 Vision OCR + 插图裁切兜底。
          </div>
          <pre id="articleMdPreview" class="code-box" style="max-height:260px; overflow:auto; margin-bottom:12px; white-space:pre-wrap; word-break:break-word;">(暂无 Markdown 预览)</pre>
          <div class="section-header">
            <div>
              <h3 class="section-title" style="font-size:14px;">本地保存的图片 / 裁切插图 (assets/)</h3>
            </div>
          </div>
          <div class="snapshot-grid" id="articleImagesGrid"></div>
        </div>
      </div>

      <div class="grid-2" style="margin-top:16px;">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">📚 服务号 / 公众号全部历史文章批量导出</h2>
              <div class="section-desc">支持按服务号主页/合集链接 (appmsgalbum)、文章 URL 清单、本地 HTML 档案或微信窗口滚屏 OCR 批量归档为 Markdown + 原图，并自动生成 INDEX.md</div>
            </div>
            <span class="chip" id="exportedAccountsBadge">0 个服务号</span>
          </div>
          <div class="control-row">
            <input id="accountNameInput" type="text" style="flex:1; min-width:180px;" placeholder="服务号 / 公众号名称（如 OpenBot 服务号）" />
            <input id="accountMaxArticles" type="number" min="1" max="200" value="30" style="max-width:100px;" title="最大导出篇数" />
          </div>
          <div class="control-row" style="margin-top:8px;">
            <input id="accountAlbumUrlInput" type="text" style="flex:2; min-width:240px;" placeholder="可选：服务号合集/主页链接 https://mp.weixin.qq.com/mp/appmsgalbum?..." />
          </div>
          <div class="control-row" style="margin-top:8px;">
            <textarea id="accountUrlsTextarea" rows="2" style="width:100%;" placeholder="可选：每行粘贴一篇公众号文章 URL（或填写本地列表文件路径，留空则结合上方链接或勾选窗体扫描）"></textarea>
          </div>
          <div class="control-row" style="margin-top:8px;">
            <label style="display:flex; align-items:center; gap:6px; font-size:13px; color:var(--text-muted);">
              <input id="accountScanWindow" type="checkbox" /> 滚屏 OCR 当前打开的微信服务号窗口
            </label>
            <button class="primary" onclick="exportAccountBatch()">🚀 批量导出全部历史文章</button>
            <button class="sm" onclick="refreshAccountExports()">🔄 刷新服务号存档</button>
          </div>
          <div class="event-list" id="exportedAccountsList" style="max-height:240px; margin-top:12px;"></div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🎬 微信视频号（Channels）作者全部视频批量导出</h2>
              <div class="section-desc">支持通过作者主页流清单 / 视频 URL（含可选 decode_key XOR 前缀解码）、本地微信缓存目录 MP4/MOV 扫描或视频号窗口 OCR 归档</div>
            </div>
            <span class="chip" id="exportedChannelsBadge">0 个作者</span>
          </div>
          <div class="control-row">
            <input id="channelsAuthorInput" type="text" style="flex:1; min-width:180px;" placeholder="视频号作者名称（如 极客频道）" />
            <input id="channelsMaxVideos" type="number" min="1" max="200" value="30" style="max-width:100px;" title="最大导出视频数" />
          </div>
          <div class="control-row" style="margin-top:8px;">
            <input id="channelsCacheDirInput" type="text" style="flex:1; min-width:200px;" placeholder="可选：本地视频号缓存目录路径 (自动扫描 ftyp/MP4/MOV)" />
            <input id="channelsManifestInput" type="text" style="flex:1; min-width:200px;" placeholder="可选：Manifest JSON/JSONL 路径" />
          </div>
          <div class="control-row" style="margin-top:8px;">
            <textarea id="channelsUrlsTextarea" rows="2" style="width:100%;" placeholder="可选：每行粘贴一条视频流直链 URL"></textarea>
          </div>
          <div class="control-row" style="margin-top:8px;">
            <label style="display:flex; align-items:center; gap:6px; font-size:13px; color:var(--text-muted);">
              <input id="channelsScanWindow" type="checkbox" /> 滚屏 OCR 当前打开的视频号窗口
            </label>
            <button class="accent" onclick="exportChannelsVideos()">📥 批量导出作者全部视频</button>
            <button class="sm" onclick="refreshChannelsExports()">🔄 刷新视频号存档</button>
          </div>
          <div class="event-list" id="exportedChannelsList" style="max-height:240px; margin-top:12px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 7: Standardized WeChat UI Protocol & Human Activity Guard -->
    <section id="tab-uiprotocol" class="tab-panel">
      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🛡️ 防抢鼠标 / 键盘自动让路守卫</h2>
              <div class="section-desc">实时监测 OS 硬件 HID 空闲时间与光标偏移：人工操作时立即停检并留出空窗期，静止达标后自动恢复。</div>
            </div>
            <span class="chip" id="guardStatusChip">状态加载中</span>
          </div>
          <div class="field-box" id="guardMetricsBox" style="margin-bottom:12px; font-size:13px; line-height:1.6;">
            等待读取 HID 空闲与空窗状态...
          </div>
          <div class="control-row">
            <label style="display:flex; align-items:center; gap:6px; font-size:13px;">
              <input id="guardEnabledInput" type="checkbox" checked /> 启用防抢鼠标自动避让
            </label>
            <label style="font-size:12.5px; color:var(--text-muted);">
              干预空窗期 (秒):
              <input id="guardCooldownInput" type="number" min="3" max="600" value="45" style="max-width:86px; margin-left:4px;" />
            </label>
            <label style="font-size:12.5px; color:var(--text-muted);">
              静止恢复阈值 (秒):
              <input id="guardIdleInput" type="number" min="3" max="600" value="45" style="max-width:86px; margin-left:4px;" />
            </label>
          </div>
          <div class="control-row" style="margin-top:10px;">
            <button class="primary" onclick="saveHumanGuardConfig()">💾 保存守卫策略</button>
            <button class="accent" onclick="resetHumanGuardCooldown()">⚡ 人工忙完·立即结束空窗</button>
            <button class="sm" onclick="refreshUiProtocolState(false)">🔄 刷新 HID 检测</button>
          </div>
          <div class="section-header" style="margin-top:16px;">
            <div>
              <h3 class="section-title" style="font-size:14px;">📐 标准化微信视图 (Views) & 聊天窗口分区 (Regions)</h3>
            </div>
            <span class="chip" id="activeViewChip">-</span>
          </div>
          <div class="event-list" id="uiViewsRegionsList" style="max-height:360px;"></div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🧭 标准化界面协议导航目标 (UI Targets Schema)</h2>
              <div class="section-desc">面向人工、OpenBot 与外部 Agent 的统一坐标协议（支持设置、通讯录、收藏、聊天抽屉、文章 ⋯ 菜单）。</div>
            </div>
            <button class="sm accent" onclick="refreshUiProtocolState(true)">🔍 OCR 实机探测界面</button>
          </div>
          <div class="field-box" id="uiNavResultBox" style="margin-bottom:10px; font-size:12.5px; color:var(--text-muted);">
            点击下方任意目标的「Dry-Run 定位」可不移动鼠标校验当前窗口解析坐标；点击「安全导航」将按协议执行。
          </div>
          <div class="event-list" id="uiTargetsList" style="max-height:480px;"></div>
        </div>
      </div>
    </section>

    <!-- Tab 8: WeChatBridge Owner Self-Soul, Friend Psychological & Memory Profiler, and Kimi Acceptance Benchmark -->
    <section id="tab-soul" class="tab-panel">
      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🎭 微信号主「本我画像」& 数字分身</h2>
              <div class="section-desc">汇总本机全部 `self` 发出消息与组织痕迹，提炼号主性格特征、语态习惯与跨好友分寸切换矩阵</div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              <button class="sm" onclick="rebuildSoulProfiles(false)">🔄 重新分析语料</button>
              <button class="sm accent" onclick="rebuildSoulProfiles(true)">🤖 LLM 深度提炼</button>
            </div>
          </div>
          <div id="ownerSoulCard"></div>
          <div class="section-header" style="margin-top:14px;">
            <h3 class="section-title" style="font-size:14px;">➕ 录入 / 矫正一条好友长期记忆 (Fact / Event / Shared)</h3>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
            <input type="text" id="memTargetInput" placeholder="好友或群名称" />
            <select id="memCategoryInput">
              <option value="fact">📌 事实记忆 (Fact / 偏好)</option>
              <option value="event">🗓️ 事件与约定 (Episodic Event)</option>
              <option value="shared">💬 共同话题与梗 (Shared Context)</option>
            </select>
          </div>
          <div style="display:flex; gap:8px;">
            <input type="text" id="memContentInput" placeholder="例如：每周二早晨喜欢看视频号短片，约定测试定时 AI 问候" />
            <button class="primary sm" onclick="addSoulMemoryItem()">💾 写入记忆</button>
          </div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">🏆 全链路 Benchmark & Kimi (`codexma`) 独立验收报告</h2>
              <div class="section-desc">涵盖 8 大核心能力自动化评测 + 外部旗舰模型 Kimi 的真实 CLI 独立核验回执与改进意见</div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              <button class="sm primary" onclick="runBenchmarkSuite(false)">🚀 跑 Benchmark</button>
              <button class="sm" onclick="runBenchmarkSuite(true)">🧪 跑全量 + 单测</button>
            </div>
          </div>
          <div id="benchmarkSummaryBox" style="margin-bottom:12px;"></div>
          <div class="event-list" id="benchmarkModulesList" style="max-height:280px; margin-bottom:14px;"></div>
          <div class="section-header">
            <h3 class="section-title" style="font-size:14px;">🦊 Kimi (`codexma`) 独立测试报告与架构意见</h3>
          </div>
          <div id="kimiAcceptanceBox"></div>
        </div>
      </div>

      <div class="panel-card">
        <div class="section-header">
          <div>
            <h2 class="section-title">🧠 好友心智画像与结构化长期记忆图谱 (WeChatBridge Soul Atlas)</h2>
            <div class="section-desc">区分「心理性格」「情绪与边界」「事实/事件/共同记忆胶囊」，支持一键启用「号主数字分身」生成带记忆回复</div>
          </div>
          <span class="chip" id="soulContactsBadge">加载中</span>
        </div>
        <div class="grid-2" id="friendSoulsGrid"></div>
      </div>
    </section>

    <section id="tab-moments" class="tab-panel">
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">◎ 朋友圈 · 好友动态与往来</div>
            <div class="panel-meta" id="momentsMeta">读取朋友圈后，这里按联系人汇总点赞、评论往来。</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-primary btn-sm" id="momentsReadBtn" onclick="readMoments()">📖 读取朋友圈</button>
            <button class="btn btn-ghost btn-sm" onclick="loadMoments(true)">刷新</button>
          </div>
        </div>
        <p class="panel-meta" style="margin:0 0 10px;">读取会在微信里打开「发现 → 朋友圈」并向下滚动，结束后切回聊天页；你正在用鼠标键盘时不会开始。点赞和评论默认只是演练——打开菜单、核对位置，不点击。</p>
        <div class="kpi-grid" id="momentsKpiGrid"></div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">按联系人的朋友圈往来</div>
            <div class="panel-meta">「待点赞」是最近 30 天里还没赞过的帖子</div>
          </div>
          <div id="momentsContactsBox"></div>
        </div>
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">自动互动策略</div>
            <div class="panel-meta">先读朋友圈，再按策略生成清单，过目后执行</div>
          </div>
          <div style="display:grid; gap:8px; font-size:13px;">
            <label><input type="checkbox" id="momentsPolicyAutoLike" onchange="saveMomentsPolicy()" /> 自动点赞：近期还没赞过的帖子</label>
            <label><input type="checkbox" id="momentsPolicyComments" onchange="saveMomentsPolicy()" /> 自动评论：按下面的模板轮换</label>
            <input id="momentsPolicyTemplates" class="input" placeholder="评论模板，多条用 | 分隔，例如：真不错！| 学习了" onchange="saveMomentsPolicy()" />
            <label style="font-size:12px; color:var(--text-muted);">只看最近
              <input id="momentsPolicyDays" type="number" min="1" max="365" class="input" style="width:76px; display:inline-block;" onchange="saveMomentsPolicy()" /> 天的帖子
            </label>
          </div>
          <div id="momentsPlanBox" style="margin-top:10px;"></div>
          <div style="margin-top:10px;">
            <button class="btn btn-ghost btn-sm" onclick="loadMomentsPlan()">查看互动清单</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">帖子</div>
          <div class="panel-meta" id="momentsPostsMeta">新 → 旧</div>
          <label style="font-size:12px; color:var(--text-muted); display:flex; gap:6px; align-items:center;">操作方式
            <select id="momentsMode" class="input" style="width:auto;">
              <option value="dry_run">演练（不点击）</option>
              <option value="silent_verify">评论演练（粘贴后读回，不发送）</option>
              <option value="live">正式发出</option>
            </select>
          </label>
        </div>
        <input id="momentsAuthorFilter" class="input" placeholder="按昵称筛选" oninput="renderMomentsPosts()" style="margin-bottom:8px;" />
        <div id="momentsPostsBox"></div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">互动记录</div>
          <div class="panel-meta">每一次演练与正式互动都有记录；不保存评论正文，只记字数</div>
        </div>
        <div id="momentsLogBox"></div>
      </div>
    </section>

    <section id="tab-salescrm" class="tab-panel">
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">客户跟进与营销漏斗</div>
            <div class="panel-meta" id="crmUpstreamBadge">等待本地服务确认客户跟进模块。</div>
            <p id="crmUnavailable" role="status" hidden></p>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-primary btn-sm" onclick="crmSyncNow()">🔄 一键同步微信联系人与历史</button>
            <button class="btn btn-ghost btn-sm" onclick="loadOverview(true)">刷新 CRM 全景</button>
          </div>
        </div>
        <div class="kpi-grid" id="crmKpiGrid"></div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">⏰ 北京时间跟进提醒收件箱 (Due / Upcoming CST)</div>
            <div class="panel-meta" id="crmReminderMeta">CST +08:00 · 逾期自动置顶</div>
          </div>
          <div id="crmRemindersBox"></div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">📝 客户纳入 / 阶段编辑与统一身份档案</div>
            <div class="panel-meta">支持 7 大漏斗阶段、北京时间精确排期与预期成交额</div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">客户姓名 / 备注 / wxid</label>
              <input id="crmTargetInput" class="input" placeholder="输入或选择联系人" />
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">营销阶段</label>
              <select id="crmStageSelect" class="input">
                <option value="新线索">新线索</option>
                <option value="初步触达">初步触达</option>
                <option value="跟进中" selected>跟进中</option>
                <option value="方案推进">方案推进</option>
                <option value="已报价">已报价</option>
                <option value="已成交">已成交</option>
                <option value="退出/失败">退出/失败</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">下次跟进时间 (北京时间 YYYY-MM-DDTHH:MM)</label>
              <input id="crmFollowUpInput" class="input" placeholder="2026-11-16T10:30" />
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">预计成交金额 (CNY)</label>
              <input id="crmDealValueInput" class="input" type="number" min="0" step="100" value="38000" />
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">客户跟进备注 (不超过 2000 字)</label>
            <textarea id="crmNoteInput" class="input" rows="2" placeholder="记录关键需求、决策链角色、预算或异议点..."></textarea>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-primary btn-sm" onclick="crmEnrollOrUpdate('enroll')">➕ 纳入 / 登记客户</button>
            <button class="btn btn-success btn-sm" onclick="crmEnrollOrUpdate('update')">💾 保存阶段与排期更新</button>
            <button class="btn btn-ghost btn-sm" onclick="loadCrmContactAnalysis()">🔍 载入右侧详情分析</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">🏆 SalesCRM 客户量化排序榜单 (Ranker)</div>
          <div class="panel-meta">点击任意客户行，立即加载 15 维指标条、公式引擎、事件时间线与 Top 1-3 跟进草稿</div>
        </div>
        <div class="table-wrap">
          <table style="width:100%; border-collapse:collapse; font-size:13px;">
            <thead>
              <tr style="text-align:left; border-bottom:1px solid var(--border-strong); color:var(--text-muted);">
                <th style="padding:8px;">#</th>
                <th style="padding:8px;">客户</th>
                <th style="padding:8px;">阶段</th>
                <th style="padding:8px;">综合分 / 紧迫度</th>
                <th style="padding:8px;">意向与互动模式</th>
                <th style="padding:8px;">BQ · BSP · BWS · PV</th>
                <th style="padding:8px;">建议动作</th>
                <th style="padding:8px;">预期金额</th>
                <th style="padding:8px;">下次跟进 (CST)</th>
              </tr>
            </thead>
            <tbody id="crmRankingsTableBody"></tbody>
          </table>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-header">
            <div>
              <div class="panel-title">📊 15 维定量特征雷达 (<span id="crmSelectedNameBadge">未选择</span>)</div>
              <div class="panel-meta">源自 vendor/salescrm 15 维特征引擎与置信度计算</div>
            </div>
            <button type="button" id="crmCallBriefBtn" class="btn btn-primary btn-sm" onclick="openCallBriefFromCrm()" title="聚合该客户的聊天、Soul、朋友圈与 CRM 阶段，生成电话前速览与话术提词卡">📞 电话前速览</button>
          </div>
          <div id="crmMetrics15Grid" style="display:grid; grid-template-columns:1fr; gap:8px;"></div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">🧮 BQ / BSP / BWS / PV 数学公式计算器</div>
            <div class="panel-meta">支持覆盖关键参数并实时重算最优商业动作</div>
          </div>
          <div id="crmFormulasBox" style="margin-bottom:12px;"></div>
          <div class="field-box" style="padding:10px;">
            <div style="font-size:12.5px; font-weight:600; margin-bottom:8px;">参数实时试算覆写 (Overrides)</div>
            <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:8px;">
              <div>
                <label style="font-size:11px; color:var(--text-muted);">p_succ 成功率</label>
                <input id="crmOvPSucc" class="input" type="number" step="0.05" min="0" max="1" placeholder="auto" />
              </div>
              <div>
                <label style="font-size:11px; color:var(--text-muted);">sp 战略潜力</label>
                <input id="crmOvSp" class="input" type="number" step="0.05" min="0" max="1" placeholder="auto" />
              </div>
              <div>
                <label style="font-size:11px; color:var(--text-muted);">pface 阻力</label>
                <input id="crmOvPface" class="input" type="number" step="0.05" min="0" max="1" placeholder="auto" />
              </div>
              <div>
                <label style="font-size:11px; color:var(--text-muted);">bs 竞争强度</label>
                <input id="crmOvBs" class="input" type="number" step="0.05" min="0" max="1" placeholder="auto" />
              </div>
            </div>
            <button class="btn btn-primary btn-sm" onclick="crmRecalcFormulas()">⚡ 重新计算 BQ / BSP / BWS / PV</button>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">🕒 客户互动事件与里程碑时间线</div>
            <div class="panel-meta">自动识别议价、约见、产品询问、报价发送与 CRM 状态变更</div>
          </div>
          <div id="crmTimelineBox"></div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">✉️ Top 1-3 跟进策略草稿 (一键采纳 / Dry-Run / 3x 静默核验)</div>
            <div class="panel-meta">结合客户 15 维得分、灵魂记忆与 FTS5 知识库生成</div>
          </div>
          <div id="crmDraftsBox"></div>
        </div>
      </div>
    </section>

    <section id="tab-omni" class="tab-panel">
      <div class="panel-card">
        <div class="section-header">
          <div>
            <div class="section-title">全渠道扫码与授权总览（挨个点击按钮授权 / 扫码 · 飞书 → 钉钉 / 小红书 → 抖音 · 微信 / 企微）</div>
            <div class="section-desc" id="omniStatusBadge">正在检查各渠道登录状态与系统权限，标橙卡片点击即可在最前端弹出对应扫码窗口…</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="btn-solid sm" onclick="loadOmniChannels(true)">🔍 一键检测全部登录态</button>
            <button type="button" class="btn-outline sm" onclick="loadOmniChannels(false)">🔄 刷新状态</button>
            <button type="button" class="btn-outline sm" onclick="omniFinishBrowser()">🧹 关闭网页扫码页</button>
          </div>
        </div>
        <div id="omniSysAuthStrip" class="omni-sys-strip"></div>
        <div id="omniCardsGrid" class="omni-channel-grid"></div>
      </div>

      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">🎯 渠道工作台（按优先级：飞书 → 钉钉 → 小红书 → 抖音）</div>
              <div class="section-desc">桌面端使用 AX+OCR；Web/社交渠道经 ego-browser + xhs-publisher 防封审计</div>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">目标渠道</label>
              <select id="omniChannelSelect" class="input" onchange="omniSelectChannel(this.value)">
                <option value="feishu" selected>1 · 飞书 (Feishu / Lark)</option>
                <option value="dingtalk">2 · 钉钉 (DingTalk)</option>
                <option value="xiaohongshu">3 · 小红书 (Xiaohongshu)</option>
                <option value="douyin">4 · 抖音 (Douyin)</option>
                <option value="wechat">5 · 微信 (WeChat)</option>
                <option value="wecom">6 · 企业微信 (WeCom)</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">发送通道模式</label>
              <select id="omniModeSelect" class="input">
                <option value="auto" selected>智能选路 (Auto)</option>
                <option value="rpa">桌面 RPA (AX + Vision)</option>
                <option value="web">网页 RPA (ego-browser)</option>
                <option value="webhook">开源加签机器人 Webhook</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">目标会话 / 用户 / 帖子</label>
              <input id="omniTargetInput" type="text" class="input" placeholder="会话名 / 群名 / 评论用户（可选）" />
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">检索关键词（小红书 / 抖音获客）</label>
              <input id="omniQueryInput" type="text" class="input" placeholder="如：AI工作流 / 私有化部署" />
            </div>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">拟发送 / 回复内容（默认 Dry-Run 防封合规演练，XHS/抖音自动去 AI 味与导流词）</label>
            <textarea id="omniReplyInput" class="input" rows="2" placeholder="输入回复文案；点击演练会验证输入框贴入与防封改写结果，不会直接发送..."></textarea>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px;">
            <button type="button" class="btn-solid sm" onclick="omniProbeChannel(true)">🚀 探测 / 核验登录态</button>
            <button type="button" class="btn-outline sm" onclick="omniInspectSessions('sessions')">📋 读取会话 / 互动</button>
            <button type="button" class="btn-outline sm" onclick="omniInspectSessions('messages')">💬 读取当前消息</button>
            <button type="button" class="btn-outline sm" onclick="omniExtractLeads(true)">🧲 识别高意向线索入 CRM</button>
            <button type="button" class="btn-outline sm" onclick="omniSendReply(true)">🧪 Dry-Run 合规演练</button>
            <button type="button" class="btn-outline sm" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="omniSendReply(false)">📤 确认实发</button>
          </div>
          <div id="omniActionResultBox" style="font-size:12.5px; color:var(--text-secondary); background:var(--surface-soft); border:1px solid var(--border); border-radius:12px; padding:12px; max-height:290px; overflow:auto;">选择上方任意渠道并点击授权/扫码按钮，或在此直接探测会话与演练回复。</div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">🧩 开源方案连接器与 Webhook / Stream 配置</div>
              <div class="section-desc">对应 lark-oapi / lark-mcp / dingtalk-stream / xiaohongshu-mcp / ChatGPT-On-CS</div>
            </div>
          </div>
          <div id="omniOpenSourceList" style="margin-bottom:12px; font-size:12.5px; color:var(--text-secondary);"></div>
          <details id="omniCredDetails" style="border:1px solid var(--border); border-radius:10px; padding:10px; background:var(--surface-soft);">
            <summary style="cursor:pointer; font-weight:600; font-size:13px;">⚙️ 配置飞书 / 钉钉开源机器人凭据（本机 0600 加密权限落盘）</summary>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:10px;">
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">飞书自定义机器人 Webhook URL</label>
                <input id="omniFeishuWebhook" type="url" class="input" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">飞书签名 Secret（可选）</label>
                <input id="omniFeishuSecret" type="password" class="input" placeholder="SEC..." />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">飞书应用 App ID</label>
                <input id="omniFeishuAppId" type="text" class="input" placeholder="cli_..." />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">飞书应用 App Secret</label>
                <input id="omniFeishuAppSecret" type="password" class="input" placeholder="留空表示不修改" />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">钉钉机器人 Webhook URL</label>
                <input id="omniDingWebhook" type="url" class="input" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">钉钉加签 Secret（可选）</label>
                <input id="omniDingSecret" type="password" class="input" placeholder="SEC..." />
              </div>
            </div>
            <div style="margin-top:10px;">
              <button type="button" class="btn-solid sm" onclick="omniSaveConfig()">💾 保存连接器配置</button>
            </div>
          </details>
        </div>
      </div>

      <div class="panel-card" style="margin-top:14px;">
        <div class="section-header">
          <div>
            <div class="section-title">🧲 抖音引流获客 → 提取微信号 → 微信加好友闭环</div>
            <div class="section-desc">读取抖音私信并回复引导对方留微信号 → 自动提取微信号/手机号并写入 CRM → 微信「添加朋友」查号与打招呼加好友（含每日上限与冷却护栏）</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="btn-solid sm" onclick="douyinFunnelRunCycle(false, false, true)">🔍 扫描抖音私信并提取微信号 (Dry-Run)</button>
            <button type="button" class="btn-outline sm" onclick="loadDouyinFunnel()">🔄 刷新漏斗状态</button>
          </div>
        </div>

        <div id="dyFunnelStatsStrip" style="display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:8px; margin-bottom:12px;"></div>

        <div class="grid-2" style="margin-bottom:12px;">
          <div style="border:1px solid var(--border); border-radius:12px; padding:12px; background:var(--surface-soft);">
            <div style="font-weight:600; font-size:13px; margin-bottom:8px;">⚙️ 抖音引流 &amp; 微信加好友护栏配置</div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              <div style="grid-column:1 / -1;">
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">抖音私信引导留微信号话术</label>
                <input id="dyCfgReplyTpl" type="text" class="input" placeholder="你好，方便发一下你的微信号吗？这边加你发详细资料～" />
              </div>
              <div style="grid-column:1 / -1;">
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">微信添加朋友验证打招呼语</label>
                <input id="dyCfgGreetingTpl" type="text" class="input" placeholder="你好呀，我是智拓巨浪的安晓心，刚在抖音看到你发来的消息，这边加你微信详聊～" />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">微信备注前缀</label>
                <input id="dyCfgRemarkPrefix" type="text" class="input" placeholder="抖音引流-" />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">每日微信加好友上限</label>
                <input id="dyCfgDailyLimit" type="number" min="1" max="50" class="input" value="15" />
              </div>
            </div>
            <div style="margin-top:8px;">
              <button type="button" class="btn-outline sm" onclick="douyinFunnelSaveConfig()">💾 保存引流配置</button>
            </div>
          </div>

          <div style="border:1px solid var(--border); border-radius:12px; padding:12px; background:var(--surface-soft);">
            <div style="font-weight:600; font-size:13px; margin-bottom:8px;">🧪 单号微信查号 / 加好友联调</div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">微信号 / 手机号</label>
                <input id="wxQuickAccount" type="text" class="input" placeholder="如：wxid_xxx 或 13800138000" />
              </div>
              <div>
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">设置备注（可选）</label>
                <input id="wxQuickRemark" type="text" class="input" placeholder="抖音引流-客户昵称" />
              </div>
              <div style="grid-column:1 / -1;">
                <label style="font-size:11.5px; color:var(--text-muted); display:block; margin-bottom:3px;">验证打招呼语</label>
                <input id="wxQuickGreeting" type="text" class="input" placeholder="你好呀，我是智拓巨浪的安晓心，刚在抖音看到你发来的消息，这边加你微信详聊～" />
              </div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
              <button type="button" class="btn-outline sm" onclick="wechatQuickAddFriend(false, true)">🔍 查号演练（不发送）</button>
              <button type="button" id="wxQuickConfirmBtn" class="btn-outline sm" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="wechatQuickAddFriend(true, false)">➕ 确认发送好友申请</button>
            </div>
          </div>
        </div>

        <div id="dyFunnelLeadsBox" style="font-size:12.5px; color:var(--text-secondary); background:var(--surface-soft); border:1px solid var(--border); border-radius:12px; padding:10px; max-height:280px; overflow:auto;">
          点击上方「扫描抖音私信并提取微信号」，即可查看已提取微信号的抖音线索并一键加微信。
        </div>
      </div>
    </section>

    <section id="tab-appuse" class="tab-panel">
      <div class="panel-card wfagent-hero" id="wfagentStudioCard">
        <div class="section-header">
          <div>
            <div class="section-title">🧠 AI 场景自建与自动调试工坊（一句话跨软件自动写流程 · 自动修 Bug）</div>
            <div class="section-desc">不用找程序员改代码！用大白话说出你的新需求（例如：飞书客户加微信并写入 CRM 档案），AI 自动识别相关软件、生成验收标准、试跑排错打补丁，并锁定成日常可一键复用的工作流。</div>
          </div>
          <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
            <span class="pill" id="wfagentStatusPill">待命 · 零黑话自建</span>
          </div>
        </div>
        <div id="wfagentChatBox" class="wfagent-chat-box">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px;">
            <div>
              <div style="font-size:13px; font-weight:700;">💬 对话式自建工作流（像聊天一样理清需求）</div>
              <div style="font-size:11.5px; color:var(--text-muted);">先说个模糊想法（如「帮我搞个飞书同步」），AI 会发几个小选择题帮您补齐条件与安全门禁，确认后自动生成并安全试跑。</div>
            </div>
            <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
              <select id="wfagentChatHistorySelect" class="input" style="width:auto; min-width:150px; padding:4px 8px; font-size:11.5px;" onchange="wfagentSelectHistoryChat(this.value)">
                <option value="">最近对话会话…</option>
              </select>
              <button type="button" class="btn-outline sm" id="wfagentChatResetBtn" onclick="wfagentResetChat()">🆕 新建对话</button>
            </div>
          </div>
          <div id="wfagentChatLog" class="wfagent-chat-log"></div>
          <div id="wfagentChatOptions" class="wfagent-chat-options"></div>
          <div style="display:flex; gap:8px; align-items:center;">
            <input id="wfagentChatInput" type="text" class="input" placeholder="像聊天一样说想法（例如：帮我搞个飞书同步，或直接点击上方推荐选项）" onkeydown="if(event.key==='Enter'){event.preventDefault();wfagentSendChat();}" />
            <button type="button" class="btn-solid sm" id="wfagentChatSendBtn" style="flex-shrink:0;" onclick="wfagentSendChat()">发送</button>
          </div>
        </div>
        <details id="wfagentDirectPanel" class="wfagent-direct-details">
          <summary>
            <span>⚡ 高级直出与验证参数（点击展开单句直出 / 切换实机 Live）</span>
            <span class="pill" id="wfagentModeSummaryBadge" style="font-size:11px;">安全影子调试 Shadow</span>
          </summary>
          <div style="margin-bottom:8px;">
            <textarea id="wfagentGoalInput" class="input" rows="2" placeholder="用大白话描述你要新增的跨软件工作流（例如：从飞书客户聊天中提取微信号，用智拓巨浪话术自报家门加微信，备注飞书引流并写入后端CRM档案）"></textarea>
          </div>
          <div class="kb-chip-row" style="margin-bottom:10px;">
            <button type="button" class="kb-chip" onclick="wfagentFillChip('feishu_wx')">🪶 飞书客户引流加微信 + CRM 建档</button>
            <button type="button" class="kb-chip" onclick="wfagentFillChip('feishu_doc')">📋 飞书待办汇总写文档简报</button>
            <button type="button" class="kb-chip" onclick="wfagentFillChip('calc_doc')">🧮 计算器验算 + 文本编辑出报告（本机实测）</button>
          </div>
          <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:10px; font-size:12.5px;">
            <label style="display:inline-flex; align-items:center; gap:6px;">
              <span>验证模式：</span>
              <select id="wfagentModeSelect" class="input" style="width:auto; min-width:240px; padding:4px 8px; font-size:12px;" onchange="wfagentSyncModeSummary()">
                <option value="shadow">安全影子调试 Shadow · 推荐（绝不乱发外部消息）</option>
                <option value="dry_run">仅静态方案与控件预检 (Dry-Run)</option>
                <option value="live">实机联跑调试 Live（需二次确认 · 适合本地办公软件）</option>
              </select>
            </label>
            <label style="display:inline-flex; align-items:center; gap:6px;">
              <span>最多自动修补轮次：</span>
              <input id="wfagentMaxRoundsInput" type="number" min="1" max="5" value="4" class="input" style="width:62px; padding:4px 8px; font-size:12px;" />
            </label>
            <label style="display:inline-flex; align-items:center; gap:5px; cursor:pointer;">
              <input id="wfagentOminiChk" type="checkbox" />
              <span>启用 Omini 独立安全审查</span>
            </label>
            <label style="display:inline-flex; align-items:center; gap:5px; cursor:pointer;">
              <input id="wfagentExportSkillChk" type="checkbox" checked />
              <span>验证通过后自动导出 Skill</span>
            </label>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="btn-outline sm" id="wfagentSpecBtn" onclick="wfagentProposeSpec()">1️⃣ 生成方案与验收标准 (Spec)</button>
            <button type="button" class="btn-solid sm" id="wfagentRunBtn" onclick="wfagentRunAuthorDebugClick()">2️⃣ 自动写流程并自己调试好</button>
            <button type="button" class="btn-outline sm" id="wfagentRepairCurrentBtn" onclick="wfagentDebugCurrentWorkflow()">🔧 对当前已载入流程一键智能修复</button>
          </div>
        </details>
        <div class="grid-2" style="gap:10px;">
          <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px;">
            <div style="font-size:12px; font-weight:600; margin-bottom:6px;">📄 方案边界、安全门禁与验收标准</div>
            <div id="wfagentSpecBox" style="font-size:12px; color:var(--text-secondary); max-height:220px; overflow-y:auto;">点击「生成方案与验收标准」或「自动写流程并自己调试好」，这里会显示识别到的应用、安全门禁与独立验收项。</div>
          </div>
          <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px;">
            <div style="font-size:12px; font-weight:600; margin-bottom:6px;">🔁 逐轮自调试与补丁时间线</div>
            <div id="wfagentTimelineBox" style="display:flex; flex-direction:column; gap:6px; max-height:220px; overflow-y:auto;">
              <div style="font-size:12px; color:var(--text-muted);">尚未运行自调试循环；失败会自动定位根因、生成补丁版本并复跑验证。</div>
            </div>
          </div>
        </div>
        <div class="wfagent-edit-bar">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:6px;">
            <div style="font-size:12.5px; font-weight:700;">✏️ 一句话改当前流程（自动回归验证）</div>
            <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
              <select id="wfagentEditWorkflowSelect" class="input" style="width:auto; min-width:160px; max-width:240px; padding:3px 8px; font-size:11.5px;" onchange="wfagentPickEditWorkflow(this.value)">
                <option value="">切换要修改的流程…</option>
              </select>
              <span class="pill" id="wfagentEditTargetPill" style="font-size:11px;">尚未载入工作流</span>
            </div>
          </div>
          <div class="kb-chip-row" style="margin-bottom:8px;">
            <button type="button" class="kb-chip" onclick="wfagentFillEditChip('remark')">🏷️ 改备注前缀</button>
            <button type="button" class="kb-chip" onclick="wfagentFillEditChip('branch')">🔀 加老客户跳过判断</button>
            <button type="button" class="kb-chip" onclick="wfagentFillEditChip('crm_tag')">🔖 给CRM加标签</button>
            <button type="button" class="kb-chip" onclick="wfagentFillEditChip('greeting')">💬 改打招呼话术</button>
            <button type="button" class="kb-chip" onclick="wfagentFillEditChip('gate')">✋ 加人工确认门禁</button>
          </div>
          <div style="display:flex; gap:8px; align-items:center;">
            <input id="wfagentEditInput" type="text" class="input" placeholder="用一句话修改已载入的工作流（例如：把备注前缀改成 飞书大客户- / 第3步之后加个判断如果微信号为空就跳过）" onkeydown="if(event.key==='Enter'){event.preventDefault();wfagentChatEditCurrent();}" />
            <button type="button" class="btn-outline sm" id="wfagentEditBtn" style="flex-shrink:0;" onclick="wfagentChatEditCurrent()">✏️ 一句话修改并回归验证</button>
          </div>
          <div id="wfagentEditDiffBox" class="wfagent-edit-diff" style="color:var(--text-muted);">载入或生成工作流后，可在这里用一句话微调步骤、备注、分支或计算表达式；系统会自动备份旧版本并做安全体检与回归验证。</div>
        </div>
      </div>

      <div class="panel-card">
        <div class="section-header">
          <div>
            <div class="section-title">🤖 通用 App-Use · 任意 Agent 自动建立操作流程与 SOP</div>
            <div class="section-desc" id="appuseStatusDesc">选择任意本机 App（含普通应用与 ChatGPT / 豆包 / Gemini / Bot Studio 等 Agent 应用），探测界面 AX+OCR 并由任意 Agent 自动生成 SOP 与可执行 RPA 工作流。</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="filter-pill active" id="appuseFilterAll" onclick="setAppUseCategory('all', this)">全部应用</button>
            <button type="button" class="filter-pill" id="appuseFilterAgent" onclick="setAppUseCategory('agent_app', this)">🤖 仅 Agent 应用</button>
            <button type="button" class="filter-pill" id="appuseFilterProd" onclick="setAppUseCategory('productivity', this)">🧰 系统/办公应用</button>
            <button type="button" class="filter-pill" id="appuseFilterRun" onclick="toggleAppUseRunningOnly(this)">🟢 仅运行中</button>
            <button type="button" class="btn-outline sm" onclick="loadAppUseStudio(true)">🔄 刷新应用与 Agent</button>
          </div>
        </div>
        <div id="appuseAppGrid" class="appuse-app-strip"></div>
      </div>

      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">1 · 选择目标 App 与任意构建 Agent</div>
              <div class="section-desc">支持普通应用自动化与对 Agent App 建模（提问 → 等流式输出稳定 → 提取结果）</div>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">目标 macOS 应用</label>
              <select id="appuseAppSelect" class="input" onchange="onAppUseSelectChange()"></select>
            </div>
            <div>
              <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">构建 SOP 的 Agent / 模型</label>
              <select id="appuseAgentSelect" class="input"></select>
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px; font-size:12.5px;">
            <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
              <input id="appuseLaunchChk" type="checkbox" checked />
              <span>目标应用未运行时自动拉起</span>
            </label>
            <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
              <input id="appuseAttachShotChk" type="checkbox" />
              <span>附带窗口截屏传给视觉 Agent</span>
            </label>
            <button type="button" class="btn-outline sm" onclick="appuseInspectSelected()">🔍 扫描界面结构 (AX + Vision OCR)</button>
          </div>
          <div id="appuseInspectSummary" style="font-size:12px; color:var(--text-secondary); background:var(--surface-soft); border:1px solid var(--border); border-radius:10px; padding:8px 10px; margin-bottom:10px;">
            尚未扫描目标界面；生成 SOP 时也会按需自动扫描。
          </div>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px;">
            <span id="appuseArchetypeBadge" class="pill">Archetype：待探测</span>
            <span id="appuseReadinessBadge" class="pill">就绪度：待评估</span>
            <span id="appuseRiskBadge" class="pill">风控策略：待识别</span>
          </div>
          <div style="margin-bottom:8px;">
            <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">希望自动建立的操作流程与 SOP 目标</label>
            <textarea id="appuseGoalInput" class="input" rows="2" placeholder="例如：打开计算器清空后输入 125*8 并回车回读结果；或对豆包/ChatGPT 建立提问并等待流式回答稳定的 SOP..."></textarea>
          </div>
          <div class="kb-chip-row" style="margin-bottom:10px;">
            <button type="button" class="kb-chip" onclick="fillAppUseExample('calc')">🧮 Calculator 计算并回读结果</button>
            <button type="button" class="kb-chip" onclick="fillAppUseExample('textedit')">📝 TextEdit 新建文档写纪要</button>
            <button type="button" class="kb-chip" onclick="fillAppUseExample('agent_app')">🤖 Agent App 提问→等回复→提取 SOP</button>
          </div>
          <details style="margin-bottom:10px;">
            <summary style="cursor:pointer; font-size:12px; color:var(--text-muted);">可选：自定义构建 Agent 额外提示词 / 约束</summary>
            <textarea id="appuseCustomPromptInput" class="input" rows="2" style="margin-top:6px;" placeholder="例如：每步操作之间必须验证回读，涉及外部发送必须加 pause_for_human 门禁..."></textarea>
          </details>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="btn-solid sm" id="appuseGeneralizeBtn" onclick="appuseGeneralizeNewApp()">🚀 一键泛化未知新 App → 生成 Skill</button>
            <button type="button" class="btn-outline sm" id="appuseBuildBtn" onclick="appuseBuildSOP()">✨ 选定 Agent 自动生成 SOP 与可执行 RPA 流程</button>
            <button type="button" class="btn-outline sm" id="appuseWatchParallelBtn" onclick="appuseWatchRunningParallel()">🔀 多窗口并行监控快照</button>
            <button type="button" class="btn-outline sm" id="appuseInstallMetaSkillBtn" onclick="appuseInstallMetaSkill()">🧩 安装全局 Meta Skill (app-use-meta-builder)</button>
          </div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">2 · 生成结果：可执行步骤、SOP 文档与安全执行</div>
              <div class="section-desc" id="appuseCurrentWfMeta">生成或加载一条流程后，可在此演练、实机运行或沉淀入库</div>
            </div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px;">
            <button type="button" class="btn-outline sm" onclick="appuseRunCurrent(true)">🧪 Dry-Run 安全演练</button>
            <button type="button" class="btn-outline sm" id="appuseLiveRunBtn" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="appuseLiveRunStepClick()">▶️ 实机执行流程</button>
            <button type="button" class="btn-outline sm" onclick="appuseExportToKB()">📚 沉淀 SOP 到知识库</button>
            <button type="button" class="btn-outline sm" onclick="appuseExportSkill()">📦 导出为 Agent Skill</button>
            <button type="button" class="btn-outline sm" onclick="appuseRollbackCurrent()">↩️ 回滚版本</button>
          </div>
          <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px; font-size:12px; color:var(--text-secondary);">
            <label style="display:inline-flex; align-items:center; gap:5px; cursor:pointer;">
              <input id="appuseSelfHealChk" type="checkbox" checked />
              <span>🔧 运行时自愈重试</span>
            </label>
            <label style="display:inline-flex; align-items:center; gap:5px; cursor:pointer;">
              <input id="appuseAutoPatchChk" type="checkbox" />
              <span>自愈成功后自动升级流程版本</span>
            </label>
            <label style="display:inline-flex; align-items:center; gap:6px;">
              <span>执行通道：</span>
              <select id="appuseDispatchModeSelect" class="input" style="width:auto; min-width:210px; font-size:12px; padding:4px 8px;">
                <option value="auto">auto（智能风控双通道 · 推荐）</option>
                <option value="headless_ax_first">headless_ax_first（无焦点 AX 直调优先）</option>
                <option value="foreground_hid_only">foreground_hid_only（强制前台真实键鼠）</option>
              </select>
            </label>
          </div>
          <div style="margin-bottom:10px;">
            <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:4px;">运行时参数覆盖 JSON（如 <code>{"prompt":"..."}</code> / <code>{"expression":"1,2,5,*,8,return"}</code>）</label>
            <input id="appuseRunParamsInput" type="text" class="input" value="{}" placeholder='{"prompt":"总结今天的工作重点"}' />
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <div>
              <div style="font-size:12px; font-weight:600; margin-bottom:6px;">可执行 RPA 步骤列表</div>
              <div id="appuseStepsBox" class="appuse-step-list">
                <div style="font-size:12px; color:var(--text-muted);">等待生成流程…</div>
              </div>
            </div>
            <div>
              <div style="font-size:12px; font-weight:600; margin-bottom:6px;">生成的标准 SOP 文档 (Markdown)</div>
              <pre id="appuseSopPreview" class="appuse-sop-pre">等待 Agent 生成 SOP…</pre>
            </div>
          </div>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">3 · 运行回执与界面实时回读日志</div>
              <div class="section-desc">每步坐标解析方式、耗时、AX/OCR 回读内容与截图存证路径</div>
            </div>
          </div>
          <pre id="appuseRunReceiptBox" class="appuse-sop-pre" style="max-height:260px;">尚未执行或演练流程。</pre>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">4 · 已保存的 App-Use SOP 与流程库</div>
              <div class="section-desc">支持跨普通应用与 Agent 应用一键复用、演练与删除</div>
            </div>
          </div>
          <div id="appuseSavedList" style="display:flex; flex-direction:column; gap:8px; max-height:260px; overflow-y:auto;"></div>
        </div>
      </div>

      <div class="grid-2" style="margin-top:14px;">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">5 · 🧭 自主探索 (Observe→Think→Act) &amp; 🎬 示范录制转 SOP</div>
              <div class="section-desc">多轮动态试探并编译流程，或录制真人鼠标/键盘示范自动提炼参数化 SOP</div>
            </div>
          </div>
          <div style="padding:10px; border:1px solid var(--border); border-radius:10px; background:var(--surface-soft); margin-bottom:10px;">
            <div style="font-size:12px; font-weight:600; margin-bottom:6px;">🧭 自主探索模式（结合上方目标应用、需求描述与构建 Agent）</div>
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <label style="font-size:12px; color:var(--text-muted); display:inline-flex; align-items:center; gap:5px;">
                最大探索轮次
                <input id="appuseExploreTurns" type="number" min="1" max="10" value="4" class="input" style="width:68px; padding:4px 8px;" />
              </label>
              <button type="button" class="btn-outline sm" id="appuseExploreDryBtn" onclick="appuseExplore(true)">🧪 Dry-Run 探索</button>
              <button type="button" class="btn-outline sm" id="appuseExploreLiveBtn" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="appuseExploreLiveClick()">🚀 实机自主探索</button>
            </div>
          </div>
          <div style="padding:10px; border:1px solid var(--border); border-radius:10px; background:var(--surface-soft);">
            <div style="font-size:12px; font-weight:600; margin-bottom:6px;">🎬 人类示范录制 → 自动编译 SOP（只读采集前台切换/AX焦点）</div>
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:6px;">
              <button type="button" class="btn-outline sm" id="appuseRecStartBtn" onclick="appuseStartRecording()">🔴 开始示范录制</button>
              <button type="button" class="btn-solid sm" id="appuseRecStopBtn" onclick="appuseStopRecording()">⏹ 停止并编译 SOP</button>
            </div>
            <div id="appuseRecStatus" style="font-size:12px; color:var(--text-secondary);">录制器空闲 · 点击「开始示范录制」后去目标 App 操作，再回来点停止编译。</div>
          </div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <div class="section-title">6 · 🔗 跨应用流水线 (Cross-App Pipelines) &amp; 📸 运行历史存证</div>
              <div class="section-desc">把前一个 App 采集到的 <code>captureAs</code> 变量自动注入后续 App，附截图缩略图审计</div>
            </div>
          </div>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px;">
            <button type="button" class="kb-chip" onclick="appuseLoadCalcTextEditPreset()">🧮 计算器算值 → 📝 文本编辑出报告</button>
            <button type="button" class="btn-outline sm" onclick="appuseSavePipeline()">💾 保存流水线</button>
            <button type="button" class="btn-outline sm" onclick="appuseRunPipeline(true)">🧪 演练流水线</button>
            <button type="button" class="btn-outline sm" id="appusePipelineLiveBtn" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="appuseRunPipelineLiveClick()">▶️ 实机联跑流水线</button>
          </div>
          <textarea id="appusePipelineJson" class="input" rows="4" style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; margin-bottom:8px;" placeholder='点上方预设或粘贴 {"name":"...", "stages":[...]} 流水线 JSON'></textarea>
          <div id="appusePipelinesList" style="display:flex; flex-direction:column; gap:6px; max-height:110px; overflow-y:auto; margin-bottom:10px;"></div>
          <div style="font-size:12px; font-weight:600; margin-bottom:5px;">📸 最近运行历史与截图存证</div>
          <div id="appuseRunsList" style="display:flex; flex-direction:column; gap:6px; max-height:140px; overflow-y:auto; margin-bottom:10px;"></div>
          <div style="font-size:12px; font-weight:600; margin-bottom:5px;">🗺️ App UI 状态图谱 (跨运行沉淀)</div>
          <div id="appuseStateGraphBox" style="display:flex; flex-direction:column; gap:5px; max-height:120px; overflow-y:auto; margin-bottom:10px;"></div>
          <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:5px;">
            <span style="font-size:12px; font-weight:600;">🧵 多窗口并发泳道 &amp; 风控调度监控</span>
            <button type="button" class="btn-outline sm" onclick="appuseRefreshConcurrencyStatus()">🔄 刷新泳道</button>
          </div>
          <div id="appuseConcurrencyBox" style="display:flex; flex-direction:column; gap:6px; max-height:170px; overflow-y:auto;"></div>
        </div>
      </div>
    </section>

    <!-- Tab: 🧪 测试与评分工作区 -->
    <section id="tab-sparring" class="tab-panel" aria-labelledby="sparringWorkspaceTitle">
      <div class="stats-heading">
        <div>
          <h1 id="sparringWorkspaceTitle" class="contact-heading" tabindex="-1">🧪 测试与评分</h1>
          <p class="chat-feedback" style="margin:2px 0 0;">无需打开微信即可模拟客户压测、查看测试好友对练日志、执行回归验证并追踪 1-5 星质量趋势</p>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button type="button" class="btn-outline sm" onclick="loadSparringWorkspace(true)">🔄 刷新数据</button>
          <button type="button" class="btn-solid sm" id="sparringRegressionBtn" onclick="runSparringRegressionSuite()">🧪 一键回归验证</button>
        </div>
      </div>

      <div class="sparring-grid" style="margin-top:10px;">
        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">1 · 模拟客户对练窗口（本地零风险试跑）</h2>
              <div class="section-desc">支持普通客户提问，或以 <code>#</code> 开头发送管理员纠偏指令（如 <code>#别一上来报底价，先问需求</code>）</div>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr auto; gap:8px; margin-bottom:8px;">
            <input type="text" id="simContactInput" value="模拟测试客户" placeholder="测试好友/模拟客户名" />
            <select id="simPersonaSelect" aria-label="模拟测试性格"></select>
            <button type="button" class="btn-outline sm" onclick="clearSimChatLog()">清空窗口</button>
          </div>
          <div id="simChatLogBox" class="sparring-chat-box">
            <div class="sparring-msg sys">输入客户消息试测知识库与话术；以 <code>#</code> 开头则按管理员指令即时纠偏并沉淀约束。</div>
          </div>
          <div style="display:flex; gap:8px; margin-top:8px;">
            <input type="text" id="simMessageInput" placeholder="输入客户提问或 #纠偏指令…" onkeydown="if(event.key==='Enter'){event.preventDefault();sendSparringSimMessage();}" />
            <button type="button" class="btn-solid" id="simSendBtn" onclick="sendSparringSimMessage()">发送试跑</button>
          </div>
          <div id="simRegressionBox" style="margin-top:10px;" hidden></div>
        </div>

        <div class="panel-card">
          <div class="section-header">
            <div>
              <h2 class="section-title">2 · 1-5 星质量仪表盘 &amp; 低分改进清单</h2>
              <div class="section-desc">双轨质量统计（5 维自动分 + 主管 1-5 星人工评分）</div>
            </div>
          </div>
          <div id="qualityKpiGrid" class="metrics-row" style="grid-template-columns:repeat(3, minmax(0,1fr)); margin-bottom:10px;"></div>
          <div id="qualityStarDistBox" style="margin-bottom:10px;"></div>
          <div style="margin-bottom:10px;">
            <strong style="font-size:12.5px;">高频问题标签</strong>
            <div id="qualityIssueTagsBox" class="chip-row" style="margin-top:4px;"></div>
          </div>
          <div>
            <strong style="font-size:12.5px;">低分 / 需关注改进项</strong>
            <div id="qualityLowScoreList" style="max-height:190px; overflow:auto; display:flex; flex-direction:column; gap:6px; margin-top:6px;"></div>
          </div>
        </div>
      </div>

      <div class="panel-card" style="margin-top:14px;">
        <div class="section-header">
          <div>
            <h2 class="section-title">3 · 测试好友管理 &amp; 对练日志打分</h2>
            <div class="section-desc">测试好友拥有 <code>#</code> 指令纠偏权限，且自动从客户 CRM 漏斗与成单统计中剔除</div>
          </div>
          <div style="display:flex; gap:6px; align-items:center;">
            <input type="text" id="newTestContactInput" placeholder="新增测试好友微信名…" style="width:180px;" onkeydown="if(event.key==='Enter'){event.preventDefault();addTestContactFromWorkspace();}" />
            <button type="button" class="btn-outline sm" onclick="addTestContactFromWorkspace()">＋ 添加测试好友</button>
          </div>
        </div>
        <div id="testContactsChipsBox" class="chip-row" style="margin-bottom:10px;"></div>
        <div id="sparringTurnsLogBox" style="display:flex; flex-direction:column; gap:8px; max-height:380px; overflow:auto;"></div>
      </div>
    </section>
  </div>

  <div id="toast" class="toast"></div>

  <script>
    let STATE = null;
    let AVATAR_CACHE_BUST = 0;
    let ACTIVE_TAB = "monitor";
    let CONTACT_FILTER = "all";
    let CONTACT_DETAIL = null;
    let MODEL_FILTER = "all";

    function escapeHtml(val) {
      return String(val ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function encArg(val) {
      return encodeURIComponent(String(val ?? "")).replace(/'/g, "%27");
    }

    function showToast(msg) {
      const el = document.getElementById("toast");
      el.textContent = msg;
      el.classList.add("show");
      clearTimeout(el._timer);
      el._timer = setTimeout(() => el.classList.remove("show"), 2600);
    }

    function toggleTheme() {
      const html = document.documentElement;
      const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
      html.setAttribute("data-theme", next);
      try { localStorage.setItem("openbot_wechat_theme", next); } catch (e) {}
      showToast(next === "dark" ? "已切换为深色主题" : "已切换为浅色主题");
    }

    (function initTheme() {
      try {
        const saved = localStorage.getItem("openbot_wechat_theme");
        const scheme = saved === "dark" || saved === "light" ? saved :
          (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", scheme);
      } catch (e) {}
    })();

    /* ---------- 朋友圈：读取好友动态、按联系人统计往来、点赞评论（默认演练） ---------- */
    let MOMENTS_STATE = { stats: null, posts: [], log: [] };
    const MOMENTS_TH = 'style="text-align:left; padding:6px 4px; border-bottom:1px solid var(--border);"';
    const MOMENTS_THR = MOMENTS_TH.replace("left", "right");
    const MOMENTS_TD = 'style="padding:6px 4px; border-bottom:1px solid var(--border);"';
    const MOMENTS_TDR = MOMENTS_TD.replace("padding", "text-align:right; padding");

    function momentsMode() {
      return (document.getElementById("momentsMode") || {}).value || "dry_run";
    }

    async function readMoments() {
      const btn = document.getElementById("momentsReadBtn");
      const meta = document.getElementById("momentsMeta");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 正在读取朋友圈…"; }
      if (meta) meta.textContent = "正在微信里打开朋友圈并向下滚动，这期间请不要操作鼠标键盘…";
      try {
        const { status, data } = await apiJson("/api/moments/read", { method: "POST", body: JSON.stringify({}) });
        if (status === 403 || !data.ok) {
          showToast(data.blockedByHumanGuard ? "检测到你正在操作鼠标键盘，稍后再试" : ("读取朋友圈失败：" + (data.error || "需要授权")));
          if (meta) meta.textContent = data.error || "读取失败";
          return;
        }
        const why = {
          end_of_feed: "已经到底", reached_known: "读到了之前读过的帖子", max_posts: "读够了设定条数",
          max_pages: "达到滚动上限", view_lost: "中途没有再认出朋友圈视图",
        }[data.stoppedBecause] || data.stoppedBecause;
        if (meta) meta.textContent = "读到 " + data.postsRead + " 条，新入库 " + ((data.store || {}).newPosts || 0) + " 条（" + why + "）";
        showToast("读取完成：" + data.postsRead + " 条，新入库 " + ((data.store || {}).newPosts || 0) + " 条");
      } catch (err) {
        showToast("读取朋友圈失败：" + ((err && err.message) || err));
        if (meta) meta.textContent = String((err && err.message) || err);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "📖 读取朋友圈"; }
        await loadMoments(false);
      }
    }

    async function loadMoments(notify) {
      try {
        const [statsRes, postsRes, logRes, policyRes] = await Promise.all([
          apiJson("/api/moments/stats"), apiJson("/api/moments/posts?limit=60"),
          apiJson("/api/moments/log?limit=30"), apiJson("/api/moments/policy"),
        ]);
        if (statsRes.status === 403) return;
        MOMENTS_STATE.stats = statsRes.data || null;
        MOMENTS_STATE.posts = (postsRes.data && postsRes.data.posts) || [];
        MOMENTS_STATE.log = (logRes.data && logRes.data.items) || [];
        renderMomentsKpi();
        renderMomentsContacts();
        renderMomentsPosts();
        renderMomentsLog();
        if (policyRes.data && policyRes.data.policy) renderMomentsPolicy(policyRes.data.policy);
        if (notify) showToast("朋友圈数据已刷新");
      } catch (err) { /* 页面还没就绪时静默 */ }
    }

    function momentsCard(label, value, sub) {
      return '<div class="kpi-card"><div class="kpi-label">' + escapeHtml(label) + '</div><div class="kpi-value">' +
        escapeHtml(value) + '</div><div class="kpi-sub">' + escapeHtml(sub) + "</div></div>";
    }

    function renderMomentsKpi() {
      const el = document.getElementById("momentsKpiGrid");
      const s = MOMENTS_STATE.stats;
      if (!el || !s) return;
      const mine = s.myInteractions || {};
      const got = s.received || {};
      const limiter = s.rateLimiter || {};
      const contacts = s.contacts || [];
      const pending = contacts.reduce((sum, c) => sum + (c.pendingLike || 0), 0);
      const lastRead = s.lastReadAt ? "上次读取 " + String(s.lastReadAt).slice(0, 16).replace("T", " ") : "还没读取过";
      el.innerHTML = [
        momentsCard("已入库的帖子", s.completePosts || 0, (s.ownerName ? "号主 " + s.ownerName + " · " : "") + lastRead),
        momentsCard("发过帖子的联系人", contacts.length, "只统计完整读到的帖子"),
        momentsCard("我赞过 / 评论过", (mine.likes || 0) + " / " + (mine.comments || 0), "正式发出的互动"),
        momentsCard("收到的赞 / 评论", (got.likes || 0) + " / " + (got.comments || 0), "别人在我帖子上的互动"),
        momentsCard("待点赞", pending, "最近 30 天里还没赞过的"),
        momentsCard("今日正式互动", (limiter.dailyUsed || 0) + " / " + (limiter.dailyLimit || 0), "超出上限会自动停下"),
      ].join("");
    }

    function renderMomentsContacts() {
      const el = document.getElementById("momentsContactsBox");
      if (!el) return;
      const rows = (MOMENTS_STATE.stats && MOMENTS_STATE.stats.contacts) || [];
      if (!rows.length) {
        el.innerHTML = '<p class="hosting-empty">还没有数据，点上方「读取朋友圈」开始。</p>';
        return;
      }
      const head = ["联系人", "帖子", "我赞过", "我评论过", "赞过我", "评论过我", "待点赞", "最近一条", "操作"]
        .map((title, index) => "<th " + (index === 0 || index === 7 || index === 8 ? MOMENTS_TH : MOMENTS_THR) + ">" + title + "</th>").join("");
      el.innerHTML = '<div style="overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:13px;"><thead><tr>' + head +
        "</tr></thead><tbody>" + rows.map((c) => {
          const authorEnc = encArg(c.author || "");
          return "<tr>" +
            "<td " + MOMENTS_TD + ">" + escapeHtml(c.author) + "</td>" +
            [c.posts, c.likedByMe, c.commentedByMe, c.likedMyPosts, c.commentedMyPosts, c.pendingLike]
              .map((n) => "<td " + MOMENTS_TDR + ">" + (n || 0) + "</td>").join("") +
            '<td ' + MOMENTS_TD + ' style="color:var(--text-secondary);">' + escapeHtml(c.lastPostText || "") + "</td>" +
            '<td ' + MOMENTS_TD + ' style="white-space:nowrap;"><button type="button" class="btn btn-ghost btn-sm" onclick="openCallBrief(decodeURIComponent(\'' + authorEnc + '\'))">📞 通话建议</button></td>' +
          "</tr>";
        }).join("") + "</tbody></table></div>";
    }

    function renderMomentsPosts() {
      const el = document.getElementById("momentsPostsBox");
      if (!el) return;
      const filter = ((document.getElementById("momentsAuthorFilter") || {}).value || "").trim();
      const posts = MOMENTS_STATE.posts.filter((p) => !filter || String(p.author || "").includes(filter));
      const meta = document.getElementById("momentsPostsMeta");
      if (meta) meta.textContent = "新 → 旧 · " + posts.length + " 条" + (filter ? "（已按昵称筛选）" : "");
      if (!posts.length) {
        el.innerHTML = '<p class="hosting-empty">' + (MOMENTS_STATE.posts.length ? "没有匹配的帖子。" : "还没有帖子，点上方「读取朋友圈」开始。") + "</p>";
        return;
      }
      el.innerHTML = posts.map((p, idx) => {
        const key = escapeHtml(p.key);
        const keyEnc = encArg(p.key || "");
        const body = String(p.text || (p.attachments || [])[0] || "").split("\n").join(" ").slice(0, 60);
        const like = p.isOwn ? '<span class="kpi-sub">自己的帖子</span>'
          : (p.likedByMe ? "✅ 已赞" : '<button class="btn btn-ghost btn-sm" onclick="momentsInteract(\'' + key + "', 'like')\">👍 点赞</button>");
        const comment = p.commentedByMe ? "✅ 已评论"
          : '<input class="input" id="momentsComment_' + key + '" placeholder="评论内容" style="height:30px; display:inline-block; width:170px;" ' +
            'onkeydown="if(event.key===\'Enter\'){momentsInteract(\'' + key + "', 'comment');}\" /> " +
            '<button type="button" class="btn btn-ghost btn-sm" id="momentsSuggestBtn_' + idx + '" onclick="momentsSuggestComment(\'' + keyEnc + "', " + idx + ')" title="结合好友画像与帖子内容拟写一句自然口语评论">✨ AI 拟评</button> ' +
            '<button class="btn btn-ghost btn-sm" onclick="momentsInteract(\'' + key + "', 'comment')\">💬 评论</button>";
        const counts = (p.likes && p.likes.length ? " · 👍 " + p.likes.length : "") + (p.comments && p.comments.length ? " · 💬 " + p.comments.length : "");
        return '<div style="display:flex; gap:10px; align-items:center; padding:8px 4px; border-bottom:1px solid var(--border); flex-wrap:wrap;">' +
          '<div style="min-width:150px; max-width:230px;"><div>' + (p.isAd ? '<span class="kpi-sub">广告</span> ' : "") +
          "<strong>" + escapeHtml(p.author || "") + "</strong></div>" +
          '<div class="kpi-sub">' + escapeHtml(p.timeText || "") + counts + "</div></div>" +
          '<div style="flex:1; min-width:200px; font-size:13px; color:var(--text-secondary);">' + escapeHtml(body) + "</div>" +
          '<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">' + like + comment + "</div>" +
          '<div id="momentsSuggestHint_' + idx + '" class="moments-suggest-hint" style="display:none;"></div>' +
          "</div>";
      }).join("");
    }

    function renderMomentsLog() {
      const el = document.getElementById("momentsLogBox");
      if (!el) return;
      const items = MOMENTS_STATE.log || [];
      if (!items.length) {
        el.innerHTML = '<p class="hosting-empty">还没有互动记录。</p>';
        return;
      }
      const statusText = {
        verified: "✅ 已完成并核对", sent_unverified: "⚠️ 已发出，但没核对到结果", dry_run: "演练通过（没有点击）",
        silent_verified: "评论已粘贴并读回（没有发送）", skipped: "跳过", blocked: "被人工操作打断", failed: "失败",
      };
      const modeText = { live: "正式", dry_run: "演练", silent_verify: "评论演练" };
      const actionText = { like: "点赞", unlike: "取消点赞", comment: "评论" };
      el.innerHTML = '<table style="width:100%; border-collapse:collapse; font-size:13px;"><tbody>' + items.map((it) => "<tr>" +
        "<td " + MOMENTS_TD + ' style="white-space:nowrap; color:var(--text-secondary);">' + escapeHtml(String(it.at || "").slice(0, 19).replace("T", " ")) + "</td>" +
        "<td " + MOMENTS_TD + ">" + escapeHtml(it.author || "") + "</td>" +
        "<td " + MOMENTS_TD + ">" + escapeHtml(actionText[it.action] || it.action || "") + (it.textLength ? "（" + it.textLength + " 字）" : "") + "</td>" +
        "<td " + MOMENTS_TD + ">" + escapeHtml(modeText[it.mode] || it.mode || "") + "</td>" +
        "<td " + MOMENTS_TD + ">" + escapeHtml(statusText[it.status] || it.status || "") +
        (it.errorCode ? '<span class="kpi-sub"> ' + escapeHtml(it.errorCode) + "</span>" : "") + "</td></tr>").join("") + "</tbody></table>";
    }

    async function momentsInteract(key, action) {
      const mode = momentsMode();
      const input = document.getElementById("momentsComment_" + key);
      const text = action === "comment" ? ((input && input.value) || "").trim() : "";
      const label = action === "comment" ? "评论" : "点赞";
      if (action === "comment" && !text) { showToast("请先填写评论内容"); return; }
      showToast(mode === "live" ? "正在正式" + label + "…" : "演练：核对「" + label + "」菜单的位置，不点击…");
      let status = 0;
      let data = {};
      try {
        ({ status, data } = await apiJson("/api/moments/interact", { method: "POST", body: JSON.stringify({ postKey: key, action, text, mode }) }));
      } catch (err) {
        showToast(label + "失败：" + ((err && err.message) || err));
        return;
      }
      if (status === 403) { showToast("需要授权：" + (data.error || "")); return; }
      const r = (data.results || [])[0] || {};
      const note = {
        verified: "已完成并核对", sent_unverified: "已发出，但没能核对到结果，请到微信里确认", dry_run: "演练通过，没有点击",
        silent_verified: "评论已粘贴并读回一致，没有发送", skipped: "跳过", blocked: "检测到有人在操作，已停下", failed: "失败",
      }[r.status] || r.status || data.error || "";
      showToast(label + "：" + note + (r.error ? "（" + r.error + "）" : ""));
      await loadMoments(false);
    }

    function renderMomentsPolicy(policy) {
      const autoLike = (policy && policy.autoLike) || {};
      const comment = (policy && policy.comment) || {};
      const box = (id, checked) => { const el = document.getElementById(id); if (el) el.checked = !!checked; };
      const field = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
      box("momentsPolicyAutoLike", autoLike.enabled);
      box("momentsPolicyComments", comment.enabled);
      field("momentsPolicyTemplates", ((comment.templates || {}).default || []).join(" | "));
      field("momentsPolicyDays", autoLike.maxAgeDays || 30);
    }

    async function saveMomentsPolicy() {
      const val = (id) => document.getElementById(id) || {};
      const updates = {
        autoLike: {
          enabled: !!val("momentsPolicyAutoLike").checked,
          maxAgeDays: Math.max(1, parseInt(val("momentsPolicyDays").value, 10) || 30),
        },
        comment: {
          enabled: !!val("momentsPolicyComments").checked,
          templates: { default: String(val("momentsPolicyTemplates").value || "").split("|").map((s) => s.trim()).filter(Boolean) },
        },
      };
      let status = 0;
      let data = {};
      try {
        ({ status, data } = await apiJson("/api/moments/policy", { method: "POST", body: JSON.stringify({ updates }) }));
      } catch (err) {
        showToast("策略没有保存：" + ((err && err.message) || err));
        return;
      }
      if (status === 403) { showToast("需要授权"); return; }
      if (!data.ok) { showToast("策略没有保存：" + (data.error || "")); return; }
      showToast("策略已保存");
      loadMomentsPlan();
    }

    async function loadMomentsPlan() {
      const el = document.getElementById("momentsPlanBox");
      if (!el) return;
      let status = 0;
      let data = {};
      try {
        ({ status, data } = await apiJson("/api/moments/plan?limit=12"));
      } catch (err) {
        el.textContent = "读取清单失败：" + ((err && err.message) || err);
        return;
      }
      if (status === 403) { el.innerHTML = '<p class="hosting-empty">需要授权</p>'; return; }
      const items = data.items || [];
      if (!items.length) {
        el.innerHTML = '<p class="hosting-empty">策略当前不产生任何互动项目。勾选自动点赞或填写评论模板后，清单会列在这里。</p>';
        return;
      }
      el.innerHTML = '<p class="panel-meta">共 ' + (data.total || items.length) + " 项，下面显示前 " + items.length + " 项：</p>" +
        items.map((it) => '<div style="font-size:13px; padding:4px 0; border-bottom:1px solid var(--border);"><strong>' + escapeHtml(it.author) +
          "</strong> · " + (it.action === "comment" ? "评论「" + escapeHtml(it.text) + "」" : "点赞") + " · " + escapeHtml(it.snippet || "") + "</div>").join("") +
        '<div style="margin-top:8px;"><button class="btn btn-ghost btn-sm" onclick="runMomentsPlan()">按上方「操作方式」执行前 5 项</button></div>';
    }

    async function runMomentsPlan() {
      const { status, data } = await apiJson("/api/moments/run-plan", { method: "POST", body: JSON.stringify({ mode: momentsMode(), limit: 5 }) });
      if (status === 403) { showToast("需要授权"); return; }
      const results = data.results || [];
      const done = results.filter((r) => ["verified", "dry_run", "silent_verified", "skipped"].includes(r.status)).length;
      showToast("清单执行完毕：" + done + "/" + results.length + " 项完成" + (data.error ? "（" + data.error + "）" : ""));
      await loadMoments(false);
    }

    function switchTab(tab) {
      ACTIVE_TAB = tab;
      document.getElementById("toast")?.classList.remove("show");
      document.querySelectorAll(".tab-btn").forEach((b) => {
        const active = b.dataset.tab === tab;
        b.classList.toggle("active", active);
        if (active) b.setAttribute("aria-current", "page");
        else b.removeAttribute("aria-current");
      });
      document.querySelectorAll(".bs-view-tab").forEach((b) => {
        const oc = String(b.getAttribute("onclick") || "");
        const isCurrent = oc.includes("'" + tab + "'");
        b.classList.toggle("active", isCurrent);
        b.setAttribute("aria-selected", String(isCurrent));
      });
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.toggle("active", p.id === "tab-" + tab);
      });
      const more = document.querySelector(".nav-more");
      if (more) more.open = false;
      if (tab === "stats") loadBackgroundObservation();
      if (tab === "omni") { loadOmniChannels(false); loadDouyinFunnel(); }
      if (tab === "appuse") loadAppUseStudio(false);
      if (tab === "moments") loadMoments(false);
      if (tab === "sparring") loadSparringWorkspace(false);
    }

    function contactKey(profile) {
      return encArg(profile.target || profile.matchedTitle || "");
    }

    function setContactFilter(filter) {
      CONTACT_DETAIL = null;
      CONTACT_FILTER = filter;
      document.querySelectorAll("#contactFilterPills .filter-pill").forEach((b) => {
        const active = b.dataset.filter === filter;
        b.classList.toggle("active", active);
        b.setAttribute("aria-pressed", String(active));
      });
      renderContacts();
    }

    function openContactGroup(filter) {
      switchTab("care");
      document.getElementById("contactSearchInput").value = "";
      setContactFilter(filter);
      document.getElementById("contactsHeading").focus();
    }

    function openContactProfile(key, filter) {
      const profiles = STATE?.analytics?.profiles;
      const profile = Array.isArray(profiles) && profiles.find(p => contactKey(p) === key);
      if (!key || !profile) {
        showToast("这份联系人详情暂不可用。");
        return;
      }
      if (filter) {
        switchTab("care");
        document.getElementById("contactSearchInput").value = "";
        setContactFilter(filter);
      }
      CONTACT_DETAIL = key;
      renderContacts();
      document.getElementById("contactsHeading").focus();
    }

    function openStatsFromContacts() {
      switchTab("stats");
      document.getElementById("statsTitle").focus();
    }

    function closeContactProfile() {
      const key = CONTACT_DETAIL;
      CONTACT_DETAIL = null;
      renderContacts();
      const opener = Array.from(document.querySelectorAll("#contactsPriorityList [data-priority-key]"))
        .find(button => button.dataset.priorityKey === key);
      (opener || document.getElementById("contactsHeading")).focus();
    }

    async function apiJson(url, options) {
      const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const data = await res.json();
      if (!res.ok && res.status !== 403) {
        throw new Error(data.error || ("HTTP " + res.status));
      }
      return { status: res.status, data };
    }

    async function loadOverview(notify = false) {
      try {
        const { status, data } = await apiJson("/api/overview");
        if (status === 403 || !data.ok) {
          renderUnauthorized(data);
          return;
        }
        STATE = data;
        document.getElementById("authBanner").classList.remove("visible");
        if (serviceBlocked) {
          setWorkspaceAvailability("");
          if (document.getElementById("draftStatus").dataset.tone === "availability") setDraftStatus("");
        }
        renderAll();
        loadHosting();
        setStatText("statsCaption", "本地归档与监控记录 · " + new Date().toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"}) + " 已读取");
        if (notify) showToast("已刷新最新微信控制端状态");
      } catch (err) {
        setStatText("statsCaption", STATE ? "刷新失败，以下为上一次读取的本地数据。" : "暂时读不到本地统计。");
        setHomeConnection("offline", STATE ? "连接中断 · 显示上次记录" : "无法连接工作台");
        setWorkspaceAvailability("离线时可继续编辑，暂不能生成、保存待办或执行发送检查。", true);
        if (!STATE) renderMonitorEvents();
        if (notify) showToast("刷新失败，请重试。");
      }
    }

    /* ---------- 健康诊断浮层 ---------- */
    function hideDiagModal() {
      document.getElementById("diagOverlay").classList.remove("visible");
    }

    function diagRow(label, value, tone) {
      const cls = tone === "bad" ? "hosting-badge off" : (tone === "good" ? "hosting-badge on" : "hosting-badge");
      const style = "display:inline-block;margin-right:6px;";
      return '<div><span class="' + cls + '" style="' + style + '">' + label + '</span>' + (value || "-") + '</div>';
    }

    async function loadDiagnostics(open = false, deep = false) {
      if (open) document.getElementById("diagOverlay").classList.add("visible");
      const body = document.getElementById("diagModalBody");
      if (open && !deep) body.innerHTML = '<p class="hosting-empty">正在读取诊断数据…</p>';
      try {
        const { status, data } = await apiJson("/api/diagnostics" + (deep ? "?deep=1" : ""));
        if (status !== 200 || !data.ok) {
          body.innerHTML = '<p class="hosting-empty">诊断读取失败：' + ((data && data.error) || status) + '</p>';
          return;
        }
        const hosting = data.hosting || {};
        const auth = (data.auth || {}).authorization || {};
        const anti = data.antiban || {};
        const events = Array.isArray(data.recentEvents) ? data.recentEvents : [];
        const warnEvents = events.filter(e => /error|failed|rate_limited|paused|occluded/.test(String(e.event || ""))).slice(-6);
        let html = "";
        html += diagRow("版本", data.version || "?", "");
        html += diagRow("授权", (auth.capabilities || []).length + " 项能力", (auth.capabilities || []).length ? "good" : "bad");
        html += diagRow("托管", hosting.enabled ? ("🟢 托管中 · " + (hosting.targets || []).length + " 位好友") : "⚪ 未开启", hosting.enabled ? "good" : "");
        html += diagRow("频控", "今日 " + (anti.daily || 0) + "/" + (anti.globalDaily || anti.global_daily || 60) + " · 全局小时 " + (anti.hourlyCount || anti.hourly || 0), "");
        html += diagRow("知识库", data.knowledgeEntries + " 条已发布", "");
        if (deep) {
          const perms = data.permissions || {};
          const llm = data.llmGateway || {};
          html += diagRow("权限", perms.ok ? "✅ 三项权限就绪" : "❌ " + (perms.error || "存在缺失"), perms.ok ? "good" : "bad");
          html += diagRow("LLM 网关", llm.ok ? ("✅ " + (llm.baseUrl || "可达")) : "❌ 不可达", llm.ok ? "good" : "bad");
        }
        if (warnEvents.length) {
          html += '<div style="margin-top:10px;"><b>⚠️ 最近异常事件</b></div>';
          html += '<div style="font-size:12px;color:#888;">' + warnEvents.map(e =>
            '<div>' + new Date(e.ts || "").toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"}) + ' · ' + (e.event || "?") + ' · ' + ((e.target || e.error || e.reason || "") + "").slice(0, 40) + '</div>'
          ).join("") + '</div>';
        } else {
          html += '<div style="margin-top:10px;color:#2a7;">✅ 最近无异常事件</div>';
        }
        body.innerHTML = html;
      } catch (err) {
        body.innerHTML = '<p class="hosting-empty">诊断请求失败：' + (err && err.message || err) + '</p>';
      }
    }

    /* ---------- 首页「一键托管好友」 & 左侧「+ 关注/监视好友」 ---------- */
    const HOSTING_STATE = { hosting: null, friends: [], checked: new Set(), dirty: false };
    const WATCH_STATE = { watchedTargets: [], loaded: false, drawerOpen: false, busy: false };

    function _syncWatchedTargetsFromStates() {
      const merged = [];
      const seen = new Set();
      const push = (raw) => {
        const clean = String(raw || "").trim();
        if (!clean) return;
        const key = clean.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        merged.push(clean);
      };
      const h = HOSTING_STATE.hosting || {};
      for (const t of (h.targets || [])) push(t);
      for (const f of (HOSTING_STATE.friends || [])) {
        if (f && f.bound && f.autoReplyEnabled) push(f.target);
      }
      if (!HOSTING_STATE.friends?.length && Array.isArray(STATE?.bindings)) {
        for (const b of STATE.bindings) {
          if (b && b.autoReplyEnabled !== false) push(b.target);
        }
      }
      if (!merged.length && WATCH_STATE.loaded) {
        for (const t of (WATCH_STATE.watchedTargets || [])) push(t);
      }
      WATCH_STATE.watchedTargets = merged;
      return merged;
    }

    function getWatchedTargets() {
      return _syncWatchedTargetsFromStates();
    }

    async function loadWatchContacts() {
      try {
        const { status, data } = await apiJson("/api/watch-contacts");
        if (status !== 200 || !data.ok) return;
        WATCH_STATE.loaded = true;
        if (Array.isArray(data.watchedTargets)) WATCH_STATE.watchedTargets = data.watchedTargets;
        if (data.hosting) HOSTING_STATE.hosting = data.hosting;
        if (Array.isArray(data.friends)) HOSTING_STATE.friends = data.friends;
        renderSidebarWatchPanel();
      } catch (err) { /* 静默等待下次刷新 */ }
    }

    function toggleSidebarWatchDrawer(forceOpen) {
      const drawer = document.getElementById("sidebarWatchDrawer");
      const btn = document.getElementById("sidebarAddWatchBtn");
      if (!drawer) return;
      const next = (typeof forceOpen === "boolean") ? forceOpen : drawer.hidden;
      WATCH_STATE.drawerOpen = next;
      drawer.hidden = !next;
      if (btn) btn.setAttribute("aria-expanded", String(next));
      if (next) {
        renderSidebarWatchPanel();
        const inp = document.getElementById("sidebarWatchInput");
        if (inp) setTimeout(() => inp.focus(), 20);
      }
    }

    function isHostingActive() {
      const hh = HOSTING_STATE?.hosting;
      const sh = STATE?.hosting;
      const h = (hh && (hh.running !== undefined || hh.enabled !== undefined))
        ? hh
        : (sh && (sh.running !== undefined || sh.enabled !== undefined) ? sh : (hh || sh || {}));
      return Boolean(h.running || h.enabled);
    }

    function renderSidebarWatchPanel() {
      const chipsBox = document.getElementById("sidebarWatchedChips");
      const badge = document.getElementById("watchedCountBadge");
      const candBox = document.getElementById("sidebarWatchCandidates");
      if (!chipsBox) return;
      const watched = getWatchedTargets();
      const watchedLower = new Set(watched.map((t) => String(t).trim().toLowerCase()));
      if (badge) badge.textContent = watched.length ? `(${watched.length})` : "";

      if (!watched.length) {
        chipsBox.innerHTML = `<span class="home-empty" style="padding:2px 0; font-size:11.5px;">暂无关注好友，点右上角「＋ 关注」添加</span>`;
      } else {
        const active = isHostingActive();
        const chipClass = active ? "watch-chip" : "watch-chip is-paused";
        const dot = active ? "🟢" : "⚪";
        const chipStatusHint = active ? "对方发消息将自动回复" : "已关注（托管已停止，开启后自动回复）";
        chipsBox.innerHTML = watched.map((t) => {
          const enc = encArg(t);
          return `<span class="${chipClass}" title="${escapeHtml(t)} · ${chipStatusHint}"><button type="button" class="watch-chip-name" onclick="selectChatThread('${enc}', '')">${dot} ${escapeHtml(t)}</button><button type="button" class="watch-chip-remove" onclick="event.stopPropagation(); openWatchedPopoutWindows(['${enc}'])" title="弹出 ${escapeHtml(t)} 独立聊天小窗" aria-label="弹出 ${escapeHtml(t)} 独立小窗">🪟</button><button type="button" class="watch-chip-remove" onclick="event.stopPropagation(); unwatchContact('${enc}')" title="取消关注 ${escapeHtml(t)}" aria-label="取消关注 ${escapeHtml(t)}">×</button></span>`;
        }).join("");
      }

      if (candBox) {
        const candidates = [];
        const candSeen = new Set(watchedLower);
        const addCand = (raw) => {
          const clean = String(raw || "").trim();
          if (!clean) return;
          const k = clean.toLowerCase();
          if (candSeen.has(k)) return;
          candSeen.add(k);
          candidates.push(clean);
        };
        addCand("微信ClawBot");
        addCand("clawBOT");
        for (const f of (HOSTING_STATE.friends || [])) {
          if (f && f.target) addCand(f.target);
        }
        for (const p of (STATE?.analytics?.profiles || []).slice(0, 10)) {
          if (p && !p.isFolderContainer) addCand(p.target || p.matchedTitle);
        }
        candBox.innerHTML = candidates.length
          ? candidates.slice(0, 12).map((c) => {
              const enc = encArg(c);
              return `<button type="button" class="watch-cand-btn" onclick="watchContact('${enc}', document.getElementById('sidebarWatchAutoStart')?.checked !== false)">＋ ${escapeHtml(c)}</button>`;
            }).join("")
          : `<span style="font-size:11px; color:var(--text-muted);">已在上方输入名称即可添加</span>`;
      }
    }

    async function watchContact(encOrRawTarget, autoStart = true) {
      const target = (() => {
        const raw = String(encOrRawTarget || "").trim();
        try { return decodeURIComponent(raw); } catch (e) { return raw; }
      })().trim();
      if (!target) {
        showToast("请输入要关注的好友或机器人名称（如 微信ClawBot）");
        document.getElementById("sidebarWatchInput")?.focus();
        return;
      }
      if (WATCH_STATE.busy) return;
      WATCH_STATE.busy = true;
      const subBtn = document.getElementById("sidebarWatchSubmitBtn");
      if (subBtn) subBtn.disabled = true;
      try {
        const { status, data } = await apiJson("/api/watch-contacts", {
          method: "POST",
          body: JSON.stringify({
            action: "watch",
            target,
            auto_start_hosting: Boolean(autoStart),
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "关注失败");
        WATCH_STATE.loaded = true;
        if (Array.isArray(data.watchedTargets)) WATCH_STATE.watchedTargets = data.watchedTargets;
        if (data.hosting) HOSTING_STATE.hosting = data.hosting;
        HOSTING_STATE.dirty = false;
        HOSTING_STATE.checked.add(data.target || target);
        renderHosting();
        renderSidebarWatchPanel();
        renderMonitorEvents();
        selectChatThread(encArg(data.target || target), "");
        showToast(`👁️ 已关注「${data.target || target}」${autoStart ? "，对方发消息将自动回复" : ""}`);
        await Promise.all([loadHosting(), loadOverview(false)]);
      } catch (err) {
        showToast("关注好友失败: " + (err.message || err));
      } finally {
        WATCH_STATE.busy = false;
        if (subBtn) subBtn.disabled = false;
      }
    }

    async function unwatchContact(encTarget) {
      const target = (() => {
        const raw = String(encTarget || "").trim();
        try { return decodeURIComponent(raw); } catch (e) { return raw; }
      })().trim();
      if (!target || WATCH_STATE.busy) return;
      WATCH_STATE.busy = true;
      try {
        const { status, data } = await apiJson("/api/watch-contacts", {
          method: "POST",
          body: JSON.stringify({ action: "unwatch", target }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "取消关注失败");
        WATCH_STATE.loaded = true;
        if (Array.isArray(data.watchedTargets)) WATCH_STATE.watchedTargets = data.watchedTargets;
        if (data.hosting) HOSTING_STATE.hosting = data.hosting;
        HOSTING_STATE.dirty = false;
        HOSTING_STATE.checked.delete(target);
        for (const f of (HOSTING_STATE.friends || [])) {
          if (String(f.target || "").trim().toLowerCase() === target.toLowerCase()) {
            f.autoReplyEnabled = false;
          }
        }
        renderHosting();
        renderSidebarWatchPanel();
        renderMonitorEvents();
        showToast(`已取消关注「${target}」`);
        await Promise.all([loadHosting(), loadOverview(false)]);
      } catch (err) {
        showToast("取消关注失败: " + (err.message || err));
      } finally {
        WATCH_STATE.busy = false;
      }
    }

    async function openWatchedPopoutWindows(specificTargets = null) {
      const btnIds = ["sidebarPopoutAllBtn", "popoutWatchedWindowsBtn"];
      const btns = btnIds.map((id) => document.getElementById(id)).filter(Boolean);
      const targets = Array.isArray(specificTargets)
        ? specificTargets.map((t) => {
            try { return decodeURIComponent(String(t || "")); } catch (e) { return String(t || ""); }
          }).filter(Boolean)
        : null;
      btns.forEach((b) => { b.disabled = true; });
      try {
        const payload = targets && targets.length ? { targets } : {};
        const { status, data } = await apiJson("/api/workos/popout-windows", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "弹出独立小窗失败");
        const opened = Number(data.openedCount || 0);
        const already = Number(data.alreadyPopoutCount || 0);
        const ready = opened + already;
        const missing = (data.notFoundTargets || []).length;
        showToast(
          `🪟 已就绪 ${ready} 个独立小窗（新弹出 ${opened} 个 · 已存在 ${already} 个${missing ? ` · 未找到 ${missing} 个` : ""}）`
        );
        if (typeof refreshAppWindows === "function") await refreshAppWindows(false);
        if (typeof loadWorkosHarness === "function") loadWorkosHarness(false);
      } catch (err) {
        showToast("弹出独立小窗失败: " + (err.message || err));
      } finally {
        btns.forEach((b) => { b.disabled = false; });
      }
    }

    function submitSidebarWatchContact() {
      const inp = document.getElementById("sidebarWatchInput");
      const target = (inp?.value || "").trim();
      if (!target) {
        showToast("请输入要关注的好友或机器人名称（如 微信ClawBot）");
        inp?.focus();
        return;
      }
      const autoStart = document.getElementById("sidebarWatchAutoStart")?.checked !== false;
      if (inp) inp.value = "";
      watchContact(target, autoStart);
    }

    function quickAddWatchFromHostingPicker() {
      const inp = document.getElementById("hostingQuickAddInput");
      const target = (inp?.value || "").trim();
      if (!target) {
        showToast("请输入新增关注好友名（如 微信ClawBot）");
        inp?.focus();
        return;
      }
      if (inp) inp.value = "";
      watchContact(target, true);
    }

    function _syncHostingCheckedFromState() {
      if (HOSTING_STATE.dirty) return;
      const next = new Set();
      const h = HOSTING_STATE.hosting || {};
      const activeTargets = Array.isArray(h.targets) ? h.targets : [];
      if (activeTargets.length > 0) {
        for (const t of activeTargets) {
          const clean = String(t || "").trim();
          if (clean) next.add(clean);
        }
      } else {
        for (const f of (HOSTING_STATE.friends || [])) {
          if (f && f.target && f.autoReplyEnabled) next.add(f.target);
        }
      }
      HOSTING_STATE.checked = next;
    }

    async function loadHosting() {
      try {
        const { status, data } = await apiJson("/api/hosting");
        if (status !== 200 || !data.ok) return;
        HOSTING_STATE.hosting = data.hosting || {};
        HOSTING_STATE.friends = data.friends || [];
        _syncHostingCheckedFromState();
        renderHosting();
        renderSidebarWatchPanel();
        renderMonitorEvents();
      } catch (err) { /* 轮询静默：下一次 loadOverview 会再试 */ }
    }

    // 人工活动让路状态：最近一条守卫事件若是 paused 且未恢复 → 托管正自动暂停让路
    function hostingHumanPause() {
      const evs = STATE?.monitor?.recentEvents || [];
      let paused = false, ts = 0;
      for (const ev of evs) {
        if (ev.event === "human_active_paused" || ev.event === "human_idle_resumed") {
          const t = new Date(ev.ts || "").getTime();
          if (Number.isFinite(t) && t >= ts) { ts = t; paused = ev.event === "human_active_paused"; }
        }
      }
      return { paused, agoMs: ts ? Date.now() - ts : 0, ts };
    }

    function updateHostingGuardPill() {
      const pill = document.getElementById("hostingGuardPill");
      if (!pill) return;
      const hg = (typeof STATE !== "undefined" && STATE && STATE.humanGuard) ? STATE.humanGuard : {};
      pill.classList.remove("guard-ready", "guard-paused", "guard-off");
      if (hg.enabled === false) {
        pill.classList.add("guard-off");
        pill.textContent = "⚠️ 防抢鼠标已关闭";
        pill.title = "点击前往设置重新开启防抢鼠标与键盘避让守卫";
        return;
      }
      if (hg.status === "human_active_cooldown" || hg.canOperate === false) {
        const rem = Math.max(0, Math.round(Number(hg.remainingCooldownSeconds || 0)));
        pill.classList.add("guard-paused");
        pill.textContent = `🛡️ 人工操作中 · 自动聊天已暂停让路（剩 ${rem}s）`;
        pill.title = hg.triggerReason ? `让路原因：${hg.triggerReason}（点击查看防抢鼠标设置）` : "人工正在操作电脑，自动聊天已完全让路";
        return;
      }
      pill.classList.add("guard-ready");
      pill.textContent = "🛡️ 防抢鼠标护航中";
      pill.title = "检测到您的鼠标或键盘输入时，自动聊天会立刻让路并暂停抢鼠标";
    }

    function renderHosting() {
      updateHostingGuardPill();
      const h = HOSTING_STATE.hosting || {};
      const badge = document.getElementById("hostingBadge");
      const meta = document.getElementById("hostingMeta");
      if (!badge || !meta) return;
      const targets = Array.isArray(h.targets) ? h.targets : [];
      if (h.running || h.enabled) {
        const pause = hostingHumanPause();
        const pauseFresh = pause.paused && pause.agoMs < 5 * 60_000;
        // 微信窗口被遮挡：环境状态，需明确提示（否则用户以为机器人坏了）
        const evsNow = STATE?.monitor?.recentEvents || [];
        let occludedTs = 0;
        for (const ev of evsNow) {
          if (ev.event === "window_occluded" || ev.event === "human_idle_resumed") {
            const t = new Date(ev.ts || "").getTime();
            if (Number.isFinite(t) && t >= occludedTs) {
              occludedTs = t;
              if (ev.event === "window_occluded") { /* last state = occluded */ }
            }
          }
        }
        const lastOccluded = evsNow.filter(e => e.event === "window_occluded").map(e => new Date(e.ts || "").getTime()).sort((a,b)=>b-a)[0] || 0;
        const occludedFresh = lastOccluded && (Date.now() - lastOccluded) < 5 * 60_000;
        if (occludedFresh && !pauseFresh) {
          badge.textContent = "🟠 微信窗口被遮挡 · " + targets.length + " 位好友";
          badge.classList.add("on");
          badge.classList.remove("off");
          meta.textContent = "微信被其他应用完全遮挡，巡检暂停（macOS 遮挡保护）· 把微信切到前台即可自动恢复 · 消息不会丢失";
        } else if (pauseFresh) {
          badge.textContent = "🟡 托管让路中 · " + targets.length + " 位好友";
          badge.classList.add("on");
          badge.classList.remove("off");
          meta.textContent = "检测到您正在操作电脑，巡检自动暂停让路（" + (fmtRelativeTime(pause.ts) || "刚刚") + "起）"
            + " · 停手约 45 秒自动恢复 · 消息不会丢失";
        } else {
          const llm = STATE?.llmGateway || {};
          const llmDown = llm.reachable === false && llm.llmEnabled !== false;
          const llmTag = (llm.llmEnabled === false)
            ? " · ⚠️ LLM 未开启"
            : (llmDown ? " · 🔴 LLM 网关不可达·回复降级模板" : (llm.reachable === true ? " · 🟢 LLM 在线" : ""));
          badge.textContent = "🟢 托管中 · " + targets.length + " 位好友";
          badge.classList.add("on");
          badge.classList.remove("off");
          const ab = STATE?.antiban || {};
          const quota = (ab.dailySent !== undefined) ? " · 今日自动回复 " + ab.dailySent + "/" + ab.dailyLimit + "（超限自动暂停）" : "";
          meta.textContent = "真发送模式 · 每 " + Math.round(h.intervalSeconds || 45) + " 秒巡检一轮"
            + llmTag
            + quota
            + (h.startedAt ? " · 开启于 " + String(h.startedAt).slice(11, 19) + " UTC" : "");
          // 网关挂了 → meta 旁给一键自愈按钮（检测→显示→点击→拉起→复探活）
          const fixBtn = document.getElementById("llmFixBtn");
          if (fixBtn) fixBtn.hidden = !llmDown;
        }
      } else {
        badge.textContent = "⚪ 托管未开启";
        badge.classList.add("off");
        badge.classList.remove("on");
        meta.textContent = "勾选好友后开启，机器人只负责被托管好友的自动回复（真发送，带防封频控）。";
      }
      meta.title = meta.textContent || "";
      const list = document.getElementById("hostingFriendList");
      if (!list) return;
      const friends = HOSTING_STATE.friends || [];
      if (!friends.length) {
        list.replaceChildren();
        const li = document.createElement("li");
        li.className = "hosting-empty";
        li.textContent = "暂无好友数据：让微信窗口保持打开，点「刷新好友列表」先做一次巡检。";
        list.appendChild(li);
        return;
      }
      const frag = document.createDocumentFragment();
      for (const f of friends) {
        const li = document.createElement("li");
        const label = document.createElement("label");
        label.className = "hosting-friend-row";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.target = f.target;
        cb.checked = HOSTING_STATE.checked.has(f.target);
        cb.addEventListener("change", () => {
          HOSTING_STATE.dirty = true;
          if (cb.checked) HOSTING_STATE.checked.add(f.target);
          else HOSTING_STATE.checked.delete(f.target);
          updateHostingCheckedCount();
        });
        label.appendChild(cb);
        const name = document.createElement("span");
        name.className = "hosting-friend-name";
        name.textContent = f.matchedTitle || f.target;
        label.appendChild(name);
        if (f.takenOver) {
          const pill = document.createElement("span");
          pill.className = "pill";
          pill.textContent = "🤚 人工接管中";
          label.appendChild(pill);
        } else if (f.autoReplyEnabled) {
          const pill = document.createElement("span");
          pill.className = "pill";
          pill.textContent = "自动回复已开";
          label.appendChild(pill);
        }
        if (!f.bound) {
          const pill = document.createElement("span");
          pill.className = "pill";
          pill.textContent = "未绑定 · 开启时自动创建";
          label.appendChild(pill);
        }
        li.appendChild(label);
        frag.appendChild(li);
      }
      list.replaceChildren(frag);
      updateHostingCheckedCount();
    }

    function updateHostingCheckedCount() {
      const el = document.getElementById("hostingCheckedCount");
      if (!el) return;
      const n = HOSTING_STATE.checked.size;
      el.textContent = n ? "(" + n + ")" : "";
    }

    function hostingSelectAll(flag) {
      HOSTING_STATE.dirty = true;
      for (const cb of document.querySelectorAll("#hostingFriendList input[type=checkbox]")) {
        cb.checked = flag;
        if (flag) HOSTING_STATE.checked.add(cb.dataset.target);
        else HOSTING_STATE.checked.delete(cb.dataset.target);
      }
      updateHostingCheckedCount();
    }

    async function refreshHostingFriends() {
      showToast("正在通过微信实时巡检刷新好友列表…");
      try {
        const { status, data } = await apiJson("/inspect-live", { method: "POST", body: JSON.stringify({}) });
        if (status !== 200 || !data.ok) throw new Error(data.error || "巡检失败");
      } catch (err) { /* 巡检失败时继续用缓存列表渲染 */ }
      await loadHosting();
      showToast("好友列表已刷新");
    }

    async function applyHosting(enable) {
      const domChecked = Array.from(document.querySelectorAll("#hostingFriendList input[type=checkbox]:checked"))
        .map((cb) => cb.dataset.target)
        .filter(Boolean);
      const targets = [...new Set([...HOSTING_STATE.checked, ...domChecked])];
      if (enable && targets.length === 0) {
        showToast("请先在「托管好友」里勾选要托管的好友，或在左侧点「＋ 关注」");
        return;
      }
      const btn = document.getElementById(enable ? "hostingEnableBtn" : "hostingDisableBtn");
      const original = btn.textContent;
      btn.disabled = true;
      try {
        const { status, data } = await apiJson("/api/hosting", {
          method: "POST",
          body: JSON.stringify({ action: enable ? "enable" : "disable", targets, disable_replies: !enable }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "操作失败");
        if (data.hosting) {
          HOSTING_STATE.hosting = data.hosting;
        } else if (!enable) {
          HOSTING_STATE.hosting = { ...(HOSTING_STATE.hosting || {}), running: false, enabled: false };
        }
        HOSTING_STATE.dirty = false;
        HOSTING_STATE.checked = enable ? new Set(targets) : new Set();
        renderHosting();
        renderSidebarWatchPanel();
        renderMonitorEvents();
        showToast(enable
          ? "已开启托管：" + targets.length + " 位好友 · 机器人真发送回复"
          : "已停止托管" + (targets.length ? "，并关闭所选好友的自动回复" : ""));
        await loadHosting();
        await loadOverview();
      } catch (err) {
        showToast("托管操作失败: " + err.message);
      } finally {
        btn.textContent = original;
        btn.disabled = false;
      }
    }

    /* ---------- 历史聊天导入（联系人 tab） ---------- */
    const HISTORY_STATE = { sources: [], checked: new Set(), scannedDir: "" };

    async function scanHistorySources() {
      const dirInput = document.getElementById("historySourceDir");
      const list = document.getElementById("historySourceList");
      const dir = (dirInput && dirInput.value || "").trim();
      list.replaceChildren();
      const li = document.createElement("li");
      li.className = "hosting-empty";
      li.textContent = "正在扫描目录…";
      list.appendChild(li);
      try {
        const { status, data } = await apiJson("/api/history-import?source_dir=" + encodeURIComponent(dir));
        if (status !== 200 || !data.ok) throw new Error(data.error || "扫描失败");
        HISTORY_STATE.scannedDir = data.sourceDir || dir;
        HISTORY_STATE.sources = data.sources || [];
        HISTORY_STATE.checked = new Set();
        renderHistorySources();
      } catch (err) {
        list.replaceChildren();
        const li2 = document.createElement("li");
        li2.className = "hosting-empty";
        li2.textContent = "扫描失败: " + err.message;
        list.appendChild(li2);
      }
    }

    function renderHistorySources() {
      const list = document.getElementById("historySourceList");
      if (!list) return;
      const frag = document.createDocumentFragment();
      if (!HISTORY_STATE.sources.length) {
        const li = document.createElement("li");
        li.className = "hosting-empty";
        li.textContent = "目录里没有找到 *_history.json 历史文件。";
        frag.appendChild(li);
      }
      for (const s of HISTORY_STATE.sources) {
        const li = document.createElement("li");
        const label = document.createElement("label");
        label.className = "hosting-friend-row";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.target = s.target;
        cb.checked = HISTORY_STATE.checked.has(s.target);
        cb.addEventListener("change", () => {
          if (cb.checked) HOSTING_STATE.checked.add(s.target);
          else HOSTING_STATE.checked.delete(s.target);
        });
        label.appendChild(cb);
        const name = document.createElement("span");
        name.className = "hosting-friend-name";
        name.textContent = s.target;
        label.appendChild(name);
        const meta = document.createElement("span");
        meta.className = "hosting-meta";
        meta.textContent = s.recordCount + " 条记录"
          + (s.observedAt ? " · " + String(s.observedAt).slice(0, 10) : "")
          + (s.alreadyImported ? " · 已导入" : "");
        label.appendChild(meta);
        li.appendChild(label);
        frag.appendChild(li);
      }
      list.replaceChildren(frag);
    }

    function historySelectAll(flag) {
      for (const s of HISTORY_STATE.sources) {
        if (flag) HOSTING_STATE.checked.add(s.target);
        else HOSTING_STATE.checked.delete(s.target);
      }
      for (const cb of document.querySelectorAll("#historySourceList input[type=checkbox]")) {
        cb.checked = flag;
      }
    }

    async function importHistorySources(all = false) {
      const targets = all ? HISTORY_STATE.sources.map(s => s.target) : [...HOSTING_STATE.checked];
      if (targets.length === 0) {
        showToast("请先扫描目录并勾选要导入的联系人");
        return;
      }
      const btn = document.getElementById(all ? "historyImportAllBtn" : "historyImportBtn");
      const original = btn.textContent;
      btn.disabled = true;
      setStatText("historyImportStatus", "正在导入…");
      try {
        const { status, data } = await apiJson("/api/history-import", {
          method: "POST",
          body: JSON.stringify({
            source_dir: HISTORY_STATE.scannedDir,
            targets: all ? undefined : targets,
            import_all: !!all,
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "导入失败");
        const total = (data.imported || []).reduce((a, b) => a + (b.recordCount || 0), 0);
        setStatText("historyImportStatus", "已导入 " + (data.imported || []).length + " 位联系人 · " + total + " 条历史记录，画像已刷新。");
        showToast("历史聊天导入完成");
        await loadOverview();
      } catch (err) {
        setStatText("historyImportStatus", "导入失败: " + err.message);
        showToast("历史聊天导入失败: " + err.message);
      } finally {
        btn.textContent = original;
        btn.disabled = false;
      }
    }

    /* ---------- 启动权限引导 ---------- */
    const PERM_GUIDE_STEPS = [
      "1. 点上方按钮：打开对应的系统设置面板，设置窗口右下角会出现一张小卡片；",
      "2. 列表里已有 <b>WeChat Bot</b> → 直接打开它的开关；没有 → 把卡片里的 <b>WeChat Bot</b> 拖进列表，再打开开关（不用点「+」找路径）；",
      "3. 屏幕录制打开后若系统提示「退出并重新打开」，点它——这一项要重启应用才生效；",
      "4. 开关已经打开却仍显示未授权：在弹出的授权窗口里点「重新登记」，它会清掉绑在旧版本上的记录。",
    ];

    const PERM_PANE_BY_ID = { accessibility: "Privacy_Accessibility", post_event: "Privacy_Accessibility", screen_capture: "Privacy_ScreenCapture" };

    /* ---------- 分步授权向导：一次聚焦一个权限，点击去授权，回来自动检测并进入下一项 ---------- */
    const PERM_WIZARD = { active: false, timer: null, stepId: null, focusId: null, items: [] };

    /* 可独立操作的步骤只有「辅助功能」「屏幕录制」。「系统事件控制」没有独立开关、跟随辅助功能，
       只有辅助功能已授权而它仍未通过时，才单独列出来提示。 */
    function permPendingSteps(items) {
      const axGranted = items.some(p => p.id === "accessibility" && p.granted);
      return items.filter(p => !p.granted && (p.id !== "post_event" || axGranted));
    }
    function permStepTotal(items) {
      return permPendingSteps(items.map(p => ({ ...p, granted: false }))).length;
    }

    function stopWizardPolling() {
      PERM_WIZARD.active = false;
      if (PERM_WIZARD.timer) { clearInterval(PERM_WIZARD.timer); PERM_WIZARD.timer = null; }
    }

    /* 重新登记授权：清除绑在旧构建上的失效记录，并让 macOS 把当前版本重新加进列表。
       会改动系统隐私设置，所以用两段式确认（控制台约定不用 window.confirm）。 */
    let PERM_REPAIR_ARMED_AT = 0;

    function repairPermissions(btn) {
      const now = Date.now();
      if (now - PERM_REPAIR_ARMED_AT > 8000) {
        PERM_REPAIR_ARMED_AT = now;
        if (btn) {
          btn.dataset.label = btn.textContent;
          btn.textContent = "⚠️ 只清除 WeChat Bot 自己的旧授权记录，再点一次确认";
          btn.style.background = "#c0392b";
          setTimeout(repairPermissionsDisarm, 8000);
        }
        return;
      }
      PERM_REPAIR_ARMED_AT = 0;
      stopWizardPolling();
      if (btn) btn.textContent = "正在清除并重新登记…";
      // 只重登记当前这一项：修屏幕录制时不连已经正常的辅助功能一起清掉
      const repairStepId = PERM_WIZARD.stepId;
      apiJson("/api/permissions/repair", { method: "POST", body: JSON.stringify({ confirm: true, services: repairStepId ? [repairStepId] : [] }) })
        .then(({ status, data }) => {
          const failed = (data.reset || []).filter(r => r.returncode !== 0);
          if (status === 200 && data.ok) {
            showToast("已清除旧记录，系统已重新登记当前版本——请在系统提示或系统设置里打开开关");
          } else {
            showToast("部分旧记录未能清除：" + (failed.map(r => r.service + "：" + (r.output || r.returncode)).join("；") || data.error || "未知原因"));
          }
        })
        .catch(err => showToast("重新登记失败：" + (err && err.message || err)))
        .then(() => new Promise(resolve => setTimeout(resolve, 1200)))
        .then(() => apiJson("/api/permissions"))
        .then(({ data }) => {
          if (!data || !data.items) return;
          PERM_WIZARD.items = data.items;
          renderPermWizard();
        })
        .catch(() => { /* 重新读取失败：下一次轮询会再试 */ });
    }

    function repairPermissionsDisarm() {
      if (Date.now() - PERM_REPAIR_ARMED_AT >= 7900) renderPermWizard();
    }

    /* 「去授权」先让 App 向 macOS 申请登记（系统弹出授权提示，并把 WeChat Bot 加进对应面板的列表），
       再打开系统设置。只跳转不申请的话，列表里没有 WeChat Bot，用户只能手动「+」添加。
       跑在 App 外壳里时交给外壳处理：它打开面板，并在设置窗口右下角浮出一张带可拖拽「WeChat Bot」
       的小卡片——列表里已有就直接打开开关，没有就把卡片拖进列表。浏览器里打开控制台则直接跳转。
       申请失败也照常进行（旧版后端没有该接口）。 */
    function permissionCardBridge() {
      return (typeof window !== "undefined" && window.webkit && window.webkit.messageHandlers)
        ? window.webkit.messageHandlers.permissionCard : null;
    }
    function requestPermissionThenOpen(event, stepId, deepLink, el) {
      if (event && event.preventDefault) event.preventDefault();
      const service = stepId === "screen_capture" ? "screen_capture" : "accessibility";
      const label = el && (el.dataset.label || el.textContent);
      if (el) {
        el.dataset.label = label;
        el.textContent = "⏳ 正在向系统申请登记…";
        el.style.pointerEvents = "none";
      }
      const restore = () => {
        if (el) {
          el.textContent = label;
          el.style.pointerEvents = "";
        }
      };
      const openPane = () => {
        restore();
        const a = document.createElement("a");
        a.href = deepLink;
        document.body.appendChild(a);
        a.click();
        a.remove();
      };
      apiJson("/api/permissions/request", { method: "POST", body: JSON.stringify({ service }) })
        .catch(() => null)
        .then(() => new Promise(resolve => setTimeout(resolve, 900)))
        .then(() => {
          const bridge = permissionCardBridge();
          if (bridge) {
            restore();
            bridge.postMessage(stepId);
            return;
          }
          openPane();
        });
    }

    function renderPermWizard(focusId) {
      const wizardEl = document.getElementById("permWizard");
      if (!wizardEl) return;
      const items = PERM_WIZARD.items || [];
      let steps = permPendingSteps(items);
      if (!steps.length) {
        wizardEl.innerHTML = "<p class=\"hosting-empty\">权限全部就绪 ✅</p>";
        stopWizardPolling();
        return;
      }
      // 点击某张卡片进入对应步骤：把该项排到最前，授权成功后恢复自然顺序
      if (focusId && steps.some(p => p.id === focusId)) PERM_WIZARD.focusId = focusId;
      if (PERM_WIZARD.focusId && steps.some(p => p.id === PERM_WIZARD.focusId)) {
        steps = steps.filter(p => p.id === PERM_WIZARD.focusId).concat(steps.filter(p => p.id !== PERM_WIZARD.focusId));
      } else {
        PERM_WIZARD.focusId = null;
      }
      const current = steps[0];
      PERM_WIZARD.stepId = current.id;
      const doneCount = Math.max(0, permStepTotal(items) - steps.length);
      const pane = PERM_PANE_BY_ID[current.id] || "Privacy_Accessibility";
      const deepLink = "x-apple.systempreferences:com.apple.preference.security?" + pane;
      const extraHint = current.id === "screen_capture"
        ? "打开开关后若系统提示「退出并重新打开」，请点它——屏幕录制要重启 WeChat Bot 才生效。"
        : "";
      wizardEl.innerHTML = `
        <div style="text-align:center;padding:6px 8px 2px;">
          <div style="font-size:13px;color:#888;margin-bottom:6px;">第 <b>${doneCount + 1}</b> 步 / 共 ${permStepTotal(items)} 步 · 当前授权项</div>
          <div style="font-size:20px;font-weight:700;margin-bottom:4px;">${current.name}</div>
          <div style="font-size:13px;color:#666;margin-bottom:14px;">${current.purpose}</div>
          <a class="btn-solid" href="${deepLink}" onclick="requestPermissionThenOpen(event, '${current.id}', this.href, this)" style="display:inline-block;padding:12px 28px;font-size:15px;text-decoration:none;cursor:pointer;">🔑 去授权「${current.name}」</a>
          <div style="font-size:12px;color:#999;margin-top:12px;">点击后会打开系统设置，设置窗口右下角出现一张小卡片：列表里已有 WeChat Bot 就直接打开开关，没有就把卡片里的 WeChat Bot 拖进列表。回到这里我会自动检测并进入下一步（每 2 秒检查一次）</div>
          ${extraHint ? `<div style="font-size:12px;color:#b25e00;margin-top:6px;">${extraHint}</div>` : ""}
          <div style="margin-top:14px;padding-top:12px;border-top:1px dashed #e5e5e5;">
            <button type="button" class="btn-outline" onclick="repairPermissions(this)" style="padding:9px 16px;font-size:13px;cursor:pointer;">🔁 开关已经打开，却还显示未授权？点这里重新登记</button>
          </div>
        </div>`;
      startWizardPolling();
    }

    function startWizardPolling() {
      if (PERM_WIZARD.active) return;
      PERM_WIZARD.active = true;
      PERM_WIZARD.timer = setInterval(async () => {
        if (!PERM_WIZARD.active) return;
        try {
          const { status, data } = await apiJson("/api/permissions");
          if (status !== 200 || !data.ok) return;
          PERM_WIZARD.items = data.items || [];
          const current = (data.items || []).find(p => p.id === PERM_WIZARD.stepId);
          if (current && current.granted) {
            showToast("✅ 「" + current.name + "」授权成功，检测到啦！");
            renderPermWizard(); // 检测到当前项成功 → 自动渲染下一步
            const stillPending = permPendingSteps(data.items || []);
            if (!stillPending.length) {
              stopWizardPolling();
              hidePermModal();
              showToast("🎉 权限全部就绪，机器人功能全部可用！");
              loadPermissions(false);
            }
          }
        } catch (err) { /* 轮询静默 */ }
      }, 2000);
    }

    function showPermModal() {
      document.getElementById("permOverlay").classList.add("visible");
    }
    window.PERM_MODAL_DISMISSED = false; // 「稍后再说」后本轮会话不再自动弹窗（首页警示条仍保留；内联 onclick 需挂 window）
    function hidePermModal() {
      stopWizardPolling(); // 关窗即停轮询：否则用户不再授权时，每 2 秒的原生探测会一直跑下去
      PERM_MODAL_DISMISSED = true;
      document.getElementById("permOverlay").classList.remove("visible");
    }

    async function loadPermissions(notify = false) {
      const panel = document.getElementById("permPanel");
      const summary = document.getElementById("permSummary");
      const itemsEl = document.getElementById("permItems");
      try {
        const { status, data } = await apiJson("/api/permissions");
        if (status !== 200 || !data.ok) throw new Error(data.error || "检查失败");
        const axGranted = data.items.some(p => p.id === "accessibility" && p.granted);
        const pendingSteps = permPendingSteps(data.items);

        // 弹窗步骤条：✅已授权 / ⚠未授权（「系统事件控制」不是独立步骤，跟随辅助功能）
        const steps = document.getElementById("permModalSteps");
        const modalItems = document.getElementById("permModalItems");
        if (steps && modalItems) {
          const stepItems = data.items.filter(p => p.id !== "post_event" || axGranted);
          steps.innerHTML = stepItems.map((p, i) =>
            `<span class="perm-step ${p.granted ? "done" : "todo"}"><span class="dot">${p.granted ? "✓" : i + 1}</span>${p.name}</span>`
          ).join('<span class="perm-arrow">≫</span>');
          // 卡片可点击：点哪张就进入对应那一步
          modalItems.innerHTML = pendingSteps.map((p) => `
            <div class="perm-item" style="cursor:pointer;" onclick="renderPermWizard('${p.id}')" title="点击进入这一步">
              <div class="perm-item-head">⚠️ ${p.name}
                <span class="perm-badge denied">未授权</span>
              </div>
              <div class="perm-purpose">${p.purpose} <span style="color:#2a7;">点击进入这一步 →</span></div>
            </div>
          `).join("") || `<p class="hosting-empty">权限全部就绪。</p>`;
          const firstDenied = pendingSteps[0];
          const link = document.getElementById("permModalOpenSettings");
          if (link && firstDenied) link.href = "x-apple.systempreferences:com.apple.preference.security?" + (PERM_PANE_BY_ID[firstDenied.id] || "Privacy_Accessibility");
        }

        itemsEl.innerHTML = data.items.map((p) => {
          const pane = PERM_PANE_BY_ID[p.id] || "Privacy_Accessibility";
          const deepLink = `x-apple.systempreferences:com.apple.preference.security?${pane}`;
          const followsAx = p.id === "post_event" && !p.granted && !axGranted;
          return `
          <div class="perm-item">
            <div class="perm-item-head">${p.granted ? "✅" : (followsAx ? "↪️" : "⚠️")} ${p.name}
              <span class="perm-badge ${p.granted ? "granted" : (followsAx ? "" : "denied")}">${p.granted ? "已授权" : (followsAx ? "随辅助功能开通" : "未授权")}</span>
            </div>
            <div class="perm-purpose">${p.purpose}</div>
            ${p.granted || followsAx ? "" : `<div class="perm-guide">
              <a class="btn-outline sm" href="${deepLink}" onclick="requestPermissionThenOpen(event, '${p.id}', this.href, this)" style="text-decoration:none;">⚙️ 一键打开「${p.name}」授权面板</a>
              <div style="margin-top:6px;">${PERM_GUIDE_STEPS.join("<br>")}</div>
            </div>`}
          </div>`;
        }).join("");
        if (data.allGranted) {
          panel.classList.remove("warn");
          panel.classList.add("ok");
          panel.open = false;
          panel.hidden = true;
          summary.textContent = "✅ 系统权限就绪（辅助功能 / 系统事件 / 屏幕录制）";
          document.getElementById("permHint").textContent = "微信" + (data.wechatRunning ? "运行中 (PID " + data.wechatPid + ")" : "未运行——自动回复需要微信保持打开");
          hidePermModal();
        } else {
          panel.hidden = false;
          panel.classList.remove("ok");
          panel.classList.add("warn");
          panel.open = true;
          const denied = pendingSteps.map((p) => p.name).join(" / ");
          summary.textContent = "🔐 系统权限未就绪：缺 " + denied + " ——机器人会“睁眼瞎”";
          document.getElementById("permHint").textContent = "打开开关即可，这里会自动检测；开关已开却仍显示未授权时，在弹出的授权窗口里点「重新登记」。";
          if (!window.PERM_MODAL_DISMISSED) {
            showPermModal();
            PERM_WIZARD.items = data.items || [];
            renderPermWizard(); // 分步向导：聚焦第一个未授权项，点击去授权，回来自动检测
          }
        }
        if (notify) showToast(data.allGranted ? "✅ 权限全部就绪，机器人功能全部可用" : "仍有权限未授权，按步骤操作后重新检查");
      } catch (err) {
        panel.hidden = false;
        panel.classList.add("warn");
        panel.open = true;
        itemsEl.innerHTML = `<p class="hosting-empty">权限检查失败: ${err.message}</p>`;
      }
    }

    async function importChatlogFile() {
      const pathEl = document.getElementById("chatlogFilePath");
      const targetEl = document.getElementById("chatlogTarget");
      const ownerEl = document.getElementById("chatlogOwner");
      const statusEl = document.getElementById("chatlogImportStatus");
      const btn = document.getElementById("chatlogImportBtn");
      const sourcePath = (pathEl.value || "").trim();
      const target = (targetEl.value || "").trim();
      if (!sourcePath || !target) {
        showToast("请填写聊天记录文件路径和聊天对象名称");
        return;
      }
      btn.disabled = true;
      setStatText("chatlogImportStatus", "正在解析聊天记录…");
      try {
        const { status, data } = await apiJson("/api/import-chatlog-file", {
          method: "POST",
          body: JSON.stringify({
            source_path: sourcePath,
            target,
            owner_name: (ownerEl.value || "").trim(),
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "导入失败");
        setStatText("chatlogImportStatus",
          "✅ 已导入 " + data.imported + " 条消息到「" + data.target + "」· 参与会话者：" +
          (data.participants || []).join("、").slice(0, 60) + " · 画像已刷新");
        showToast("聊天记录导入完成：" + data.imported + " 条");
        await loadOverview();
      } catch (err) {
        setStatText("chatlogImportStatus", "导入失败: " + err.message);
        showToast("聊天记录导入失败: " + err.message);
      } finally {
        btn.disabled = false;
      }
    }

    async function resumeContact(encTarget) {
      const target = decodeURIComponent(encTarget || "");
      try {
        await apiJson("/api/takeover", {
          method: "POST",
          body: JSON.stringify({ target, action: "resume" }),
        });
        showToast(`已恢复「${target}」AI 自动回复`);
        await loadOverview();
      } catch (err) {
        showToast("恢复失败: " + err.message);
      }
    }

    async function relaunchLlmGateway() {
      const btn = document.getElementById("llmFixBtn");
      btn.disabled = true;
      showToast("正在拉起 Magpie 网关…");
      try {
        const { status, data } = await apiJson("/api/llm-gateway/relaunch", { method: "POST", body: JSON.stringify({}) });
        if (status !== 200 || !data.ok) throw new Error(data.error || "拉起失败");
        if (data.gateway && data.gateway.reachable) {
          showToast("✅ Magpie 网关已恢复，智能回复上线");
        } else {
          showToast("已拉起 Magpie，网关还在启动中，稍后会自动刷新状态");
        }
        await loadOverview();
      } catch (err) {
        showToast("修复失败: " + err.message);
      } finally {
        btn.disabled = false;
      }
    }

    function renderUnauthorized(data) {
      STATE = null;
      setStatText("statsCaption", "授权未开启，无法读取统计。");
      for (const el of document.querySelectorAll("#kpiGrid dd, #statsEventList, #globalSlotsBar, #statsPriorityList, #priorityStatsEmpty, #slotsSummary, #statsEventCaption")) {
        if (["statsEventList", "globalSlotsBar", "statsPriorityList"].includes(el.id)) el.replaceChildren();
        else if (el.matches("dd:not([id])")) for (const child of el.children) child.textContent = child.tagName === "STRONG" ? "—" : "";
        else el.textContent = el.matches("dd") ? "—" : "";
      }
      setStatText("specialCareShortcut", "查看特别关心");
      setStatText("vipShortcut", "查看重点关照");
      CONTACT_DETAIL = null;
      renderContacts();
      renderSalesCrmTab();
      const auth = data.authorization || {};
      const btn = document.getElementById("btnAuthToggle");
      if (btn) btn.textContent = "访问授权：未解锁";
      document.getElementById("authBanner").classList.add("visible");
      document.getElementById("authBannerMsg").textContent = data.error || auth.reason || "等待恢复本地授权";
      setHomeConnection("limited", "工作台未授权");
      resetDraftContext();
      document.getElementById("previewTarget").value = "";
      document.getElementById("sendTarget").value = "";
      setWorkspaceAvailability("当前未授权，暂不能生成、保存待办或执行发送检查。");
      renderMonitorEvents();
    }

    function renderAll() {
      if (!STATE) return;
      renderHeaderAndKpi();
      renderGlobalSlots();
      renderPriorityContacts();
      renderStatisticsEvents();
      renderContacts();
      renderMonitorEvents();
      renderPersonaOptions();
      renderKnowledgeList(STATE.knowledgeSummary?.entries || []);
      renderKbQuickChips();
      renderKbKindGrid();
      // 聊天气泡流实时性：轮询刷新时当前打开的会话自动重渲染（新消息即时可见）
      renderChatStream((document.getElementById("previewTarget")?.value || "").trim());
      renderModelsHub();
      renderOpenTab();
      renderArticlesTab();
      renderUiProtocolTab();
      renderSoulAndBenchmarkTab();
      renderSalesCrmTab();
      if (typeof renderSparringFromState === "function") renderSparringFromState();
    }

    function setHomeConnection(state, message) {
      const el = document.getElementById("homeConnection");
      el.dataset.state = state;
      if (el.textContent !== message) el.textContent = message;
    }

    function renderHeaderAndKpi() {
      const auth = STATE.authorization || {};
      const wx = STATE.wechatStatus || {};
      const mon = STATE.monitor || {};
      const daemon = mon.daemon || {};
      const analytics = STATE.analytics || {};
      const scSummary = analytics.specialCareSummary || {};
      const kb = STATE.knowledgeSummary || {};

      const btn = document.getElementById("btnAuthToggle");
      if (btn) {
        btn.textContent = auth.authorized ? "外部接入授权：已开启（点击撤权）" : "外部接入授权：未开启（点击授权）";
      }

      const hg = STATE.humanGuard || {};
      if (!wx.wechatRunning) setHomeConnection("offline", "等待打开微信");
      else if (!wx.accessibilityTrusted || !wx.screenCaptureTrusted) setHomeConnection("limited", "微信已打开 · 权限受限");
      else if (wx.windowCount === 0) setHomeConnection("idle", "等待打开微信窗口");
      else setHomeConnection("ready", "微信已连接");

      setStatText("kpiSpecialCare", countLabel(scSummary.specialCareCount) + " / " + countLabel(scSummary.vipCount));
      setStatText("kpiProfileCount", countLabel(analytics.profileCount) + " / " + countLabel(analytics.boundProfileCount));
      setStatText("kpiWarmth", analytics.profileCount > 0 ? countLabel(scSummary.averageWarmthScore) + " / 100" : "—");
      const profiles = Array.isArray(analytics.profiles) ? analytics.profiles : [];
      const directions = profiles.reduce((out, p) => [out[0] + (Number(p.selfCount) || 0), out[1] + (Number(p.peerCount) || 0)], [0, 0]);
      setStatText("kpiMsgs", countLabel(scSummary.totalMessagesAnalyzed));
      setStatText("kpiMsgsSub", profiles.length ? `已识别方向：我方 ${countLabel(directions[0])} · 对方 ${countLabel(directions[1])}` : "仅含本地已分析的记录");
      setStatText("kpiMonitor", typeof daemon.running !== "boolean" ? "—" : (daemon.running ? "记录为运行中" : "未运行"));
      setStatText("kpiMonitorSub", `累计巡检 ${countLabel(daemon.cyclesCompleted)} 轮 · 回复 ${countLabel(daemon.repliesDispatched)} 条`);
      const byKind = kb.byKind || {};
      setStatText("kpiKb", countLabel(kb.count) + (Number.isFinite(kb.count) ? " 条已列出" : ""));
      setStatText("kpiKbSub", kb.byKind ? `术语 ${byKind.terminology || 0} · 知识 ${byKind.knowledge || 0} · 话术 ${byKind.script || 0}` : "");
      const doc = STATE.doctor || {};
      setStatText("kpiGuard", hg.enabled ? (hg.canOperate ? "可用" : "正在让位") : "—");
      setStatText("kpiGuardSub", Number.isFinite(doc.dedupWindowSeconds) ? `${doc.dedupWindowSeconds}s 去重` : "");
      updateHostingGuardPill();
    }

    const statNumber = new Intl.NumberFormat("zh-CN");
    function countLabel(value) { return Number.isFinite(value) ? statNumber.format(value) : "—"; }
    function setStatText(id, value) {
      const el = document.getElementById(id);
      if (el && el.textContent !== String(value)) el.textContent = value;
    }
    function formatStatTime(value) {
      if (!value) return "—";
      const date = new Date(value);
      return Number.isFinite(date.valueOf()) ? date.toLocaleString("zh-CN", {month:"numeric", day:"numeric", hour:"2-digit", minute:"2-digit"}) : "—";
    }

    function renderGlobalSlots() {
      const dist = STATE.analytics?.overallTimeSlotDistribution;
      const slots = [
        "清晨 05:00-08:59",
        "上午 09:00-11:59",
        "下午 12:00-17:59",
        "晚间 18:00-21:59",
        "深夜 22:00-04:59",
      ];
      const counts = slots.map((key) => Math.max(0, Number(dist?.[key]) || 0));
      const total = counts.reduce((sum, count) => sum + count, 0);
      setStatText("slotsSummary", total ? `按 ${countLabel(total)} 条已归入时段的记录计算。` : (dist ? "还没有带时段的本地记录。" : "暂未读取到时段统计。"));
      document.getElementById("globalSlotsBar").innerHTML = total ? slots.map((key, i) => {
        const count = counts[i];
        const percentage = Math.round(count / total * 100);
        return `<div class="stats-time-row"><span>${key}</span><meter aria-label="${key}，${percentage}%" min="0" max="${total}" value="${count}"></meter><strong>${countLabel(count)} · ${percentage}%</strong></div>`;
      }).join("") : "";

    }

    function renderPriorityContacts() {
      const summary = STATE.analytics?.specialCareSummary;
      const counts = [["specialCareShortcut", "查看特别关心", summary?.specialCareCount],
                      ["vipShortcut", "查看重点关照", summary?.vipCount]];
      counts.forEach(([id, label, count]) => setStatText(id, Number.isFinite(count) ? `${label}（${countLabel(count)}）` : label));
      const items = Array.isArray(summary?.priorityTargets) ? summary.priorityTargets : [];
      setStatText("priorityStatsEmpty", items.length ? "" : (summary ? "还没有特别关心或重点关照的联系人。" : "未读取到重点关照统计。"));
      document.getElementById("statsPriorityList").innerHTML = items.map(t => priorityPersonRow(t, true)).join("");
    }

    function priorityPersonRow(profile, fromStats = false) {
      const key = contactKey(profile);
      const level = profile.careLevel === "special_care" ? "特别关心" : "重点关照";
      const temp = Number.isFinite(profile.warmthScore) ? ` · 互动温度 ${countLabel(profile.warmthScore)}/100` : "";
      const messages = Number.isFinite(profile.messageCount) ? ` · ${countLabel(profile.messageCount)} 条消息` : "";
      const group = fromStats ? `,'${profile.careLevel === "special_care" ? "special_care" : "vip"}'` : "";
      return `<li><button type="button" class="priority-person" data-priority-key="${key}" onclick="openContactProfile('${key}'${group})"><span>${escapeHtml(profile.matchedTitle || profile.target || "未命名会话")}</span><span class="stats-meta">${level}${messages}${temp}</span></button></li>`;
    }

    function monitorEventRows(events, includeTarget) {
      const labels = {daemon_started:"启动旧版监控", daemon_stopped:"停止旧版监控", poll_error:"巡检失败", human_active_paused:"让位给人工", human_idle_resumed:"恢复巡检", peer_message:"收到消息", takeover:"人工接管", resume_contact:"恢复会话", window_auto_restored:"微信窗口恢复"};
      return events.map((ev) => {
        const type = String(ev.event || "");
        const label = Object.hasOwn(labels, type) ? labels[type] : (type || "监控事件");
        return `<li><time>${escapeHtml(formatStatTime(ev.ts))}</time>${escapeHtml(label)}${includeTarget && ev.target ? " · " + escapeHtml(ev.target) : ""}</li>`;
      }).join("");
    }

    function renderStatisticsEvents() {
      const source = STATE.monitor?.recentEvents;
      const events = Array.isArray(source) ? source : [];
      const list = document.getElementById("statsEventList");
      setStatText("statsEventCaption", !Array.isArray(source) ? "未读取到监控事件。" : (!events.length ? "暂无监控事件。" : `最近 ${countLabel(events.length)} 条，来自本地监控日志。`));
      list.innerHTML = monitorEventRows(events, true);
    }

    let backgroundObservation = null;
    let backgroundRequest = false;
    function renderBackgroundObservation(data, unavailable = false) {
      backgroundObservation = data;
      const labels = {standby:"未开启", starting:"正在启动", running:"运行中", waiting_no_visible_window:"等待微信窗口", failed:"巡检异常", stopping:"正在停止"};
      const state = data?.state;
      const label = state && Object.hasOwn(labels, state) ? labels[state] : "状态不可用";
      setStatText("backgroundState", label);
      setStatText("backgroundChecks", countLabel(data?.checks));
      setStatText("backgroundSessions", Number.isFinite(data?.visibleSessions) ? `${countLabel(data.visibleSessions)} / ${countLabel(data.unreadSessions)}` : "—");
      setStatText("backgroundLastChecked", formatStatTime(data?.lastCheckedAt));
      const hints = {screen_capture_denied:"需要系统的屏幕录制权限。", authorization_required:"需要恢复本地授权。", native_status_failed:"读不到微信窗口状态。", capture_failed:"未能读取可见窗口。"};
      const description = state === "waiting_no_visible_window" ? "打开微信主窗口后会继续检查。"
        : (Object.hasOwn(hints, data?.errorCode) ? hints[data.errorCode]
          : (unavailable ? "本地服务暂未提供后台巡检状态。" : "持续读取可见微信窗口，不抢前台，不切换会话，不回复消息。"));
      setStatText("backgroundDescription", description);
      const button = document.getElementById("backgroundToggle");
      button.disabled = backgroundRequest || !data || unavailable || state === "stopping";
      setStatText("backgroundToggle", data?.running ? "停止巡检" : "开始巡检");
    }
    async function loadBackgroundObservation() {
      if (backgroundRequest || document.hidden) return;
      backgroundRequest = true;
      try {
        const {data} = await apiJson("/api/background-observation");
        backgroundRequest = false;
        renderBackgroundObservation(data.ok ? data : null, !data.ok);
      } catch {
        backgroundRequest = false;
        renderBackgroundObservation(null, true);
      }
    }
    async function toggleBackgroundObservation() {
      if (!backgroundObservation || backgroundRequest) return;
      const action = backgroundObservation.running ? "stop" : "start";
      backgroundRequest = true;
      document.getElementById("backgroundToggle").disabled = true;
      try {
        const {data} = await apiJson("/api/background-observation", {method:"POST", body:JSON.stringify({action})});
        if (!data.ok) showToast("后台巡检操作未完成，请核对授权。");
      } catch (err) {
        showToast("后台巡检操作未完成：" + err.message);
      } finally {
        backgroundRequest = false;
        await loadBackgroundObservation();
      }
    }

    function renderContacts() {
      const source = STATE?.analytics?.profiles;
      const profiles = Array.isArray(source) ? source : [];
      const detail = CONTACT_DETAIL && profiles.find(p => contactKey(p) === CONTACT_DETAIL);
      const groupLabel = CONTACT_FILTER === "special_care" ? "特别关心" : (CONTACT_FILTER === "vip" ? "重点关照" : "");
      const grid = document.getElementById("contactsGrid");
      const list = document.getElementById("contactsPriorityList");
      setStatText("contactsHeading", CONTACT_DETAIL ? (detail?.matchedTitle || detail?.target || "联系人详情") : (groupLabel || "联系人"));
      document.getElementById("contactFilters").hidden = !!CONTACT_DETAIL;
      document.getElementById("contactBack").hidden = !CONTACT_DETAIL;
      document.getElementById("contactStatsBack").hidden = !!CONTACT_DETAIL;
      grid.classList.toggle("contact-detail", !!CONTACT_DETAIL);
      list.hidden = true;
      list.replaceChildren();
      if (!STATE) {
        grid.textContent = "尚未读取到联系人。";
        return;
      }
      const monContacts = STATE.monitor?.contacts || {};
      const personas = STATE.personas?.personas || {};
      const contactOverrides = STATE.personas?.contactOverrides || {};
      const testContactKeys = new Set((STATE.testContacts || []).map((tc) => String(tc.displayName || "").trim().toLowerCase()).filter(Boolean));
      const q = (document.getElementById("contactSearchInput").value || "").trim().toLowerCase();

      const filtered = CONTACT_DETAIL ? (detail ? [detail] : []) : profiles.filter((p) => {
        if (CONTACT_FILTER === "special_care" && p.careLevel !== "special_care") return false;
        if (CONTACT_FILTER === "vip" && p.careLevel !== "vip") return false;
        if (CONTACT_FILTER === "bound" && !p.bound) return false;
        if (CONTACT_FILTER === "folder" && !p.isFolderContainer) return false;
        if (q) {
          const hay = [
            p.matchedTitle,
            p.target,
            p.friendStyleTag,
            ...(p.contentCategories || []),
            ...(p.careTags || []),
          ].join(" ").toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      if (!filtered.length) {
        grid.innerHTML = `<p class="panel-card" style="grid-column:1/-1;">${CONTACT_DETAIL
          ? "这份联系人详情暂不可用。"
          : "当前筛选没有会话画像，可切换到「全部会话」。"}</p>`;
        return;
      }
      if (!CONTACT_DETAIL && groupLabel) {
        grid.replaceChildren();
        list.hidden = false;
        list.innerHTML = filtered.map(p => priorityPersonRow(p)).join("");
        return;
      }

      const personaList = Object.values(personas);

      grid.innerHTML = filtered.map((p) => {
        const monEntry = findMonitorContact(monContacts, p.target, p.matchedTitle);
        const takenOver = !!(monEntry && monEntry.takenOver);
        const override = findMonitorContact(contactOverrides, p.target, p.matchedTitle);
        const currentPersonaId = (override && override.personaId) || p.aiPersona || "warm-friend";

        const cardCls = p.careLevel === "special_care" ? "is-special-care" : (p.careLevel === "vip" ? "is-vip" : "");
        const careBadge = p.careLevel === "special_care"
          ? `<span class="pill special">🌟 特别关心 (${escapeHtml(p.monitorPriority)})</span>`
          : (p.careLevel === "vip"
            ? `<span class="pill warn">⭐ 重点关照 (${escapeHtml(p.monitorPriority)})</span>`
            : `<span class="pill">${escapeHtml(p.role || "普通会话")}</span>`);

        const self = Number.isFinite(p.selfCount) && p.selfCount >= 0 ? p.selfCount : null;
        const peer = Number.isFinite(p.peerCount) && p.peerCount >= 0 ? p.peerCount : null;
        const totalDir = self === null || peer === null ? 0 : self + peer;
        const selfPct = totalDir > 0 ? Math.round(self / totalDir * 100) : 0;
        const peerPct = totalDir > 0 ? (100 - selfPct) : 0;
        const times = Object.entries(p.timeSlotDistribution || {}).filter(([, count]) => Number.isFinite(count) && count > 0);
        const events = Array.isArray(STATE.monitor?.recentEvents) ? STATE.monitor.recentEvents : [];
        const ownEvents = CONTACT_DETAIL ? events.filter(ev => ev.target && [p.target, p.matchedTitle].includes(ev.target)) : [];
        const warmthCls = p.warmthScore >= 75 ? "warmth-hot" : (p.warmthScore >= 45 ? "warmth-mid" : "");

        const personaOpts = personaList.map((per) => {
          const sel = per.id === currentPersonaId ? "selected" : "";
          return `<option value="${escapeHtml(per.id)}" ${sel}>${escapeHtml(per.name)} (${escapeHtml(per.mbti)})</option>`;
        }).join("");

        const titleEsc = escapeHtml(p.matchedTitle || p.target || "未命名会话");
        const draftAttr = encArg(p.proactiveCareDraft || "");
        const rawTargetEnc = encArg(p.target || p.matchedTitle);
        const targetRawName = String(p.target || p.matchedTitle || "").trim();
        const isTestContact = testContactKeys.has(targetRawName.toLowerCase()) || testContactKeys.has(String(p.matchedTitle || "").trim().toLowerCase());

        return `
          <article class="contact-card ${cardCls}" data-contact-key="${rawTargetEnc}">
            <div class="contact-top">
              <div>
                <div class="contact-name">
                  <span>${titleEsc}</span>
                  ${careBadge}
                  ${p.bound ? `<span class="pill ok">已绑定</span>` : ""}
                  ${isTestContact ? `<span class="pill warn">🧪 测试好友</span>` : ""}
                  ${takenOver ? `<span class="pill danger">🤚 人工接管中</span>` : ""}
                </div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
                  ${escapeHtml(p.friendStyleTag)} · ${escapeHtml(p.interactionBalance || "")}
                </div>
              </div>
              <div class="warmth-badge ${warmthCls}">互动温度 ${countLabel(p.warmthScore)}${Number.isFinite(p.warmthScore) ? "/100" : ""}</div>
            </div>

            <div class="metrics-row">
              <div class="mini-stat">
                <div class="k">聊天消息统计</div>
                <div class="v">${countLabel(p.messageCount)} 条（均值 ${countLabel(p.avgLength)} 字）</div>
              </div>
              <div class="mini-stat">
                <div class="k">聊天频率</div>
                <div class="v">${escapeHtml(p.frequencyLabel)}</div>
              </div>
              <div class="mini-stat">
                <div class="k">最佳触达窗口</div>
                <div class="v" style="font-size:12px;">${escapeHtml(p.bestContactWindow)}</div>
              </div>
            </div>

            <div>
              <div class="contact-direction">
                <span>我方发出：${countLabel(self)}${totalDir ? `（${selfPct}%）` : ""}</span>
                <span>对方发出：${countLabel(peer)}${totalDir ? `（${peerPct}%）` : ""}</span>
              </div>
              ${totalDir ? `<div class="ratio-bar" aria-hidden="true">
                <div class="ratio-self" style="width:${selfPct}%"></div>
                <div class="ratio-peer" style="width:${peerPct}%"></div>
              </div>` : ""}
            </div>

            <div class="chip-row">
              ${(p.contentCategories || []).map((c) => `<span class="chip">🏷️ ${escapeHtml(c)}</span>`).join("")}
              ${(p.activeTimeMarkers || []).slice(0, 4).map((t) => `<span class="chip">🕒 ${escapeHtml(t)}</span>`).join("")}
            </div>

            ${CONTACT_DETAIL ? `<section class="contact-events">
              <h2>活跃时段</h2>
              ${times.length ? `<dl class="stat-rows">${times.map(([slot, count]) => `<div><dt>${escapeHtml(slot)}</dt><dd>${countLabel(count)} 条</dd></div>`).join("")}</dl>` : "<p>没有归入时段的本地记录。</p>"}
              <h2>近期本会话监控事件</h2>
              ${ownEvents.length ? `<ul class="stats-event-list" role="list">${monitorEventRows(ownEvents, false)}</ul>` : "<p>最近的本地监控日志中暂无此会话的事件。</p>"}
            </section>` : ""}

            <div style="font-size:12.5px; color:var(--text-secondary);">
              <strong>画像洞察：</strong>${escapeHtml(p.styleSummary)}
            </div>

            <div class="care-draft-box">
              <div><strong>💌 主动关怀/跟进建议：</strong>${escapeHtml(p.proactiveCareDraft)}</div>
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="sm" onclick="useCareDraft('${rawTargetEnc}', '${draftAttr}')">💬 填入发送台</button>
                <button class="sm accent" onclick="quickPreviewContact('${rawTargetEnc}')">✨ 测试智能回复</button>
              </div>
            </div>

            <div class="contact-actions">
              <button type="button" class="sm accent" onclick="openCallBrief(decodeURIComponent('${rawTargetEnc}'))">📞 电话前建议</button>
              <button type="button" class="sm ${isTestContact ? "primary" : ""}" onclick="toggleTestContact('${rawTargetEnc}', ${!isTestContact})">${isTestContact ? "🧪 取消测试好友" : "🧪 设为测试好友"}</button>
              ${p.careLevel !== "special_care"
                ? `<button class="sm special" onclick="changeCareLevel('${rawTargetEnc}', 'special_care', true)">🌟 设为特别关心</button>`
                : `<button class="sm" onclick="changeCareLevel('${rawTargetEnc}', 'normal', false)">取消特关</button>`}
              ${p.careLevel !== "vip"
                ? `<button class="sm vip" onclick="changeCareLevel('${rawTargetEnc}', 'vip', true)">⭐ 重点关照</button>`
                : `<button class="sm" onclick="changeCareLevel('${rawTargetEnc}', 'normal', false)">取消 VIP</button>`}
              <button class="sm ${takenOver ? "primary" : "danger"}" onclick="toggleTakeover('${rawTargetEnc}', ${!takenOver})">
                ${takenOver ? "🤖 恢复 AI" : "🤚 人工接管"}
              </button>
              <div class="persona-inline">
                <select id="sel-persona-${escapeHtml(p.slug)}">${personaOpts}</select>
                <button class="sm" onclick="applyContactPersona('${rawTargetEnc}', 'sel-persona-${escapeHtml(p.slug)}')">切换性格</button>
              </div>
            </div>
          </article>
        `;
      }).join("");
    }

    function findMonitorContact(mapObj, target, matchedTitle) {
      if (!mapObj) return null;
      const keys = Object.keys(mapObj);
      const tLow = String(target || "").toLowerCase();
      const mLow = String(matchedTitle || "").toLowerCase();
      for (const k of keys) {
        const kl = k.toLowerCase();
        if (kl === tLow || kl === mLow || (tLow && kl.includes(tLow)) || (tLow && tLow.includes(kl))) {
          return mapObj[k];
        }
      }
      return null;
    }

    let draftRequest = 0;
    let draftRevision = 0;
    let draftBusy = false;
    let serviceBlocked = "";
    let draftContext = 0;
    let savedDraft = null;
    let pendingDraftId = null;
    let savingDraft = false;

    const savedDraftIdPattern = /^[0-9a-f]{32}$/;
    const savedDraftRoot = "/api/workbench/saved-drafts";

    function composerSnapshot() {
      return {
        target: document.getElementById("previewTarget").value.trim(),
        incoming: document.getElementById("previewIncoming").value,
        draft: document.getElementById("sendText").value,
      };
    }

    function sameComposer(a, b) {
      return a.target === b.target && a.incoming === b.incoming && a.draft === b.draft;
    }

    function savedDraftFeedback(message, error = false, showLink = false) {
      const status = document.getElementById("savedDraftStatus");
      status.textContent = message;
      status.toggleAttribute("data-error", error);
      document.getElementById("openSavedTask").hidden = !showLink;
    }

    function updateSaveDraftButton() {
      const button = document.getElementById("saveDraftBtn");
      const generate = document.getElementById("generateDraftBtn");
      const queued = !!savedDraft;
      button.closest(".chat-composer").toggleAttribute("data-queued-draft", queued);
      button.classList.toggle("btn-solid", queued);
      button.classList.toggle("btn-outline", !queued);
      generate.classList.toggle("btn-solid", !queued);
      generate.classList.toggle("btn-outline", queued);
      button.textContent = savingDraft ? "保存中…" : (queued ? "更新待办" : "加入待办");
      button.setAttribute("aria-busy", String(savingDraft));
      button.setAttribute("aria-disabled", String(savingDraft || !!serviceBlocked));
      button.toggleAttribute("data-unavailable", !!serviceBlocked);
    }

    function clearSavedDraftContext(preserveRoute = false) {
      draftContext++;
      savedDraft = null;
      pendingDraftId = null;
      savedDraftFeedback("");
      updateSaveDraftButton();
      if (!preserveRoute && location.hash.startsWith("#saved-draft=")) {
        history.replaceState(null, "", location.pathname + location.search);
      }
    }

    async function savedDraftRequest(id = "", payload) {
      const response = await fetch(savedDraftRoot + (id ? "/" + id : ""), {
        method: payload ? "POST" : "GET",
        ...(payload ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)} : {}),
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error_code || "saved_draft_unavailable");
      return data.draft;
    }

    function draftErrorMessage(error) {
      const errors = {
        invalid_saved_draft: "请检查会话和草稿长度，草稿最多 3000 字。",
        saved_draft_not_found: "找不到这条草稿待办。",
        saved_draft_changed: "这条待办已有更新，未覆盖。当前编辑仍在，可先复制后从待办重新打开。",
        saved_draft_completed: "这条待办已完成，未更新。当前编辑仍在；请先从待办重新打开。",
        authorization_required: "未授权访问本机草稿待办。",
      };
      return errors[error.message];
    }

    async function saveConversationDraft() {
      if (savingDraft || serviceBlocked) return;
      const current = composerSnapshot();
      if (!current.target || !current.draft.trim()) {
        savedDraftFeedback(current.target ? "请先填写回复草稿。" : "请先填写回复对象。", true, !!savedDraft);
        document.getElementById(current.target ? "sendText" : "previewTarget").focus();
        return;
      }
      if ([...current.target].length > 256 || [...current.incoming].length > 3000 || [...current.draft].length > 3000) {
        savedDraftFeedback("会话名称最多 256 字，来信与草稿各最多 3000 字。", true, !!savedDraft);
        return;
      }
      if (savedDraft && savedDraft.target !== current.target) clearSavedDraftContext();
      if (!pendingDraftId) {
        pendingDraftId = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, "0")).join("");
      }
      const epoch = draftContext;
      const currentRoute = location.hash;
      const id = savedDraft?.id || pendingDraftId;
      const updating = !!savedDraft;
      const payload = {id, version: savedDraft?.version || 0, ...current};
      savingDraft = true;
      updateSaveDraftButton();
      savedDraftFeedback("");
      try {
        const row = await savedDraftRequest("", payload);
        if (epoch !== draftContext || location.hash !== currentRoute ||
            composerSnapshot().target !== current.target) return;
        if (!row || row.id !== id || row.target !== current.target) throw new Error("saved_draft_unavailable");
        savedDraft = {id: row.id, version: row.version, target: row.target};
        history.replaceState(null, "", "#saved-draft=" + row.id);
        const unchanged = sameComposer(current, composerSnapshot());
        savedDraftFeedback(unchanged
          ? (updating ? "已更新待办，未发送。" : "已加入待办，未发送。")
          : "已保存提交时的版本，后续修改尚未保存。", false, true);
      } catch (error) {
        if (epoch === draftContext && location.hash === currentRoute) {
          savedDraftFeedback(draftErrorMessage(error) || "未确认保存结果，可重试；当前草稿仍在。", true,
            !!savedDraft || error.message === "saved_draft_changed");
        }
      } finally {
        savingDraft = false;
        updateSaveDraftButton();
      }
    }

    async function resumeSavedDraft() {
      if (!location.hash.startsWith("#saved-draft=")) return;
      const id = location.hash.slice("#saved-draft=".length);
      if (!savedDraftIdPattern.test(id)) {
        savedDraftFeedback("这条待办链接无效。", true, true);
        return;
      }
      const epoch = draftContext;
      const current = composerSnapshot();
      const revision = draftRevision;
      savedDraftFeedback("正在读取草稿待办…");
      const stillCurrent = () => location.hash === "#saved-draft=" + id && epoch === draftContext;
      try {
        const row = await savedDraftRequest(id);
        if (!stillCurrent()) return;
        if (draftRevision !== revision || !sameComposer(current, composerSnapshot())) {
          savedDraftFeedback("已保留当前编辑，没有载入待办草稿。", true, true);
          return;
        }
        if (!row || row.id !== id || typeof row.target !== "string" ||
            typeof row.incoming !== "string" || typeof row.draft !== "string") {
          throw new Error("saved_draft_unavailable");
        }
        if (row.state === "completed") {
          savedDraftFeedback("这条待办已完成。请到待办选择「重新打开」，再继续编辑。", true, true);
          return;
        }
        resetDraftContext(true);
        document.getElementById("previewTarget").value = row.target;
        document.getElementById("sendTarget").value = row.target;
        document.getElementById("previewIncoming").value = row.incoming;
        const editor = document.getElementById("sendText");
        editor.value = row.draft;
        document.getElementById("sendMode").value = "dry_run";
        syncSendModeLabel();
        savedDraft = {id: row.id, version: row.version, target: row.target};
        pendingDraftId = id;
        updateSaveDraftButton();
        switchTab("monitor");
        markSelectedThread(row.target);
        savedDraftFeedback("正在编辑已保存的草稿。修改后可更新待办。", false, true);
        editor.focus();
      } catch (error) {
        if (stillCurrent()) savedDraftFeedback(draftErrorMessage(error) || "暂时读不到草稿待办。", true, true);
      }
    }

    function setWorkspaceAvailability(reason, retry = false) {
      serviceBlocked = reason;
      if (reason && draftBusy) {
        draftRequest++;
        setDraftBusy(false);
      }
      for (const id of ["generateDraftBtn", "sendActionLabel"]) {
        const button = document.getElementById(id);
        button.toggleAttribute("data-unavailable", !!reason);
        button.setAttribute("aria-disabled", String(!!reason || (id === "generateDraftBtn" && draftBusy)));
      }
      document.getElementById("homeRetry").hidden = !retry;
      updateSaveDraftButton();
      if (reason) setDraftStatus(reason, "availability");
    }

    function setDraftStatus(text, tone = "") {
      const status = document.getElementById("draftStatus");
      status.textContent = text;
      status.hidden = !text;
      status.dataset.tone = tone;
    }

    function setDraftBusy(busy) {
      draftBusy = busy;
      const button = document.getElementById("generateDraftBtn");
      button.setAttribute("aria-disabled", String(busy || !!serviceBlocked));
      button.textContent = busy ? "正在生成…" : "生成草稿";
    }

    function resetDraftContext(preserveRoute = false) {
      clearSavedDraftContext(preserveRoute);
      draftRequest++;
      setDraftBusy(false);
      setDraftStatus(serviceBlocked, serviceBlocked ? "availability" : "");
      document.getElementById("previewIncoming").value = "";
      document.getElementById("sendText").value = "";
      const preview = document.getElementById("replyPreviewResult");
      preview.replaceChildren();
      preview.hidden = true;
      preview.removeAttribute("data-last-reply");
      document.getElementById("sendReceiptBox").replaceChildren();
    }

    function markSelectedThread(target) {
      document.querySelectorAll(".chat-thread-row").forEach((row) => {
        const selected = row.dataset.target === target;
        row.classList.toggle("active", selected);
        row.setAttribute("aria-pressed", String(selected));
      });
    }

    function selectChatThread(encTarget, encIncoming, fromUser = true) {
      const target = decodeURIComponent(encTarget || "");
      if (!target) return;
      const incoming = decodeURIComponent(encIncoming || "");
      const pt = document.getElementById("previewTarget");
      pt.value = target;
      syncChatRecipient(target);
      const source = document.getElementById("previewIncoming");
      // 优先带入该联系人的最近往来上下文（时间正序，最新在末尾），让手动生成草稿有据可依
      let threadText = "";
      const norm = target.toLowerCase();
      const thread = Object.values(STATE?.recentThreads || {}).find((t) => (t.target || "").toLowerCase() === norm);
      if (thread && (thread.messages || []).length) {
        const lines = thread.messages.map((m) => {
          const lowConf = (m.confidence !== null && m.confidence !== undefined && m.confidence < 0.6);
          return (m.direction === "self" ? "我方" : "对方") + "：" + m.text
            + (m.at ? "（" + m.at + "）" : "")
            + (lowConf ? " ⚠️OCR识别可能不准" : "");
        });
        threadText = "[最近往来 · 新消息在最后]\n" + lines.join("\n");
      } else if (incoming) {
        threadText = incoming;
      }
      if (threadText && source.value !== threadText) {
        resetDraftContext();
        source.value = threadText;
      } else if (!threadText && source.value !== incoming) {
        resetDraftContext();
        source.value = incoming;
      }
      if (fromUser && compactConversation.matches) document.getElementById("conversationThreads").open = false;
      renderChatStream(target);
    }

    function avatarUrlFor(target) {
      const avatars = STATE?.avatars || {};
      const versions = STATE?.avatarVersions || {};
      const key = String(target || "").trim();
      if (!key) return "";
      let url = "";
      let matchedKey = "";
      if (avatars[key]) {
        url = avatars[key];
        matchedKey = key;
      } else {
        const lower = key.toLowerCase();
        if (avatars[lower]) {
          url = avatars[lower];
          matchedKey = lower;
        } else {
          for (const [k, v] of Object.entries(avatars)) {
            if (k.toLowerCase() === lower) {
              url = v;
              matchedKey = k;
              break;
            }
          }
        }
      }
      if (!url) return "";
      const ver = Number(versions[matchedKey] || versions[key] || versions[key.toLowerCase()] || AVATAR_CACHE_BUST || 0);
      if (ver > 0) {
        return url + (url.includes("?") ? "&" : "?") + "v=" + encodeURIComponent(String(ver));
      }
      return url;
    }

    async function refreshSidebarAvatars() {
      const btn = document.getElementById("refreshAvatarsBtn");
      const prevText = btn ? btn.textContent : "🖼️ 更新头像";
      if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ 更新中…";
      }
      try {
        const { status, data } = await apiJson("/api/avatars/refresh", {
          method: "POST",
          body: JSON.stringify({ capture_fresh: true }),
        });
        if (status !== 200 || !data?.ok) {
          throw new Error(data?.error || "刷新头像失败");
        }
        AVATAR_CACHE_BUST = Date.now();
        if (!STATE) STATE = {};
        if (data.avatars) STATE.avatars = data.avatars;
        if (data.avatarVersions) STATE.avatarVersions = data.avatarVersions;
        renderMonitorEvents();
        if (typeof currentTarget !== "undefined" && currentTarget) renderChatStream(currentTarget);
        if (typeof renderContacts === "function") renderContacts();
        await loadOverview();
        const upd = Number(data.updatedCount || 0);
        const miss = Array.isArray(data.missingTargets) ? data.missingTargets.length : 0;
        if (upd > 0) {
          showToast(`已更新 ${upd} 位联系人头像${miss ? "（" + miss + " 位未在当前会话列表截图中）" : ""}`);
        } else {
          showToast(`已完成扫描（本地共 ${Object.keys(data.avatars || {}).length} 枚头像；如需采集新头像请将微信/企微主窗口保持可见）`);
        }
      } catch (err) {
        showToast("更新头像失败: " + (err?.message || err));
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.textContent = prevText;
        }
      }
    }

    // 微信式气泡流：渲染当前会话的往来记录（peer 左 / self 右 / 时间居中 / OCR 低置信标注）
    function renderChatStream(target) {
      const stream = document.getElementById("chatBubbleStream");
      const headTarget = document.getElementById("chatStreamTarget");
      if (!stream) return;
      const norm = String(target || "").toLowerCase();
      const thread = Object.values(STATE?.recentThreads || {}).find((t) => (t.target || "").toLowerCase() === norm);
      const msgs = (thread && thread.messages) || [];
      const avatarUrl = avatarUrlFor(target);
      if (headTarget) {
        headTarget.replaceChildren();
        if (target) {
          if (avatarUrl) {
            const img = document.createElement("img");
            img.className = "chat-avatar";
            img.src = avatarUrl;
            img.alt = "";
            img.style.marginRight = "4px";
            img.onerror = function () { this.style.display = "none"; };
            headTarget.appendChild(img);
          }
          headTarget.appendChild(document.createTextNode("· " + target));
        }
      }
      if (!msgs.length) {
        stream.replaceChildren();
        const sep = document.createElement("div");
        sep.className = "bubble-sep";
        sep.textContent = "暂无往来记录——对方发消息后会自动出现在这里";
        stream.appendChild(sep);
        return;
      }
      let lastPeerIdx = -1;
      msgs.forEach((m, i) => { if (m.direction === "peer") lastPeerIdx = i; });
      const frag = document.createDocumentFragment();
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i];
        // 深读理解记录（链接/图片/视频摘要）→ 居中虚线系统卡片
        if (m.kind === "media_note") {
          const srow = document.createElement("div");
          srow.className = "bubble-row system";
          const card = document.createElement("div");
          card.className = "bubble system-card";
          card.textContent = "🤖 " + m.text;
          srow.appendChild(card);
          frag.appendChild(srow);
          continue;
        }
        const row = document.createElement("div");
        row.className = "bubble-row " + (m.direction === "self" ? "self" : "peer");
        if (m.direction !== "self" && avatarUrl) {
          const av = document.createElement("img");
          av.className = "chat-avatar";
          av.src = avatarUrl;
          av.alt = "";
          av.onerror = function () { this.style.display = "none"; };
          row.appendChild(av);
        }
        const bubble = document.createElement("div");
        bubble.className = "bubble " + (m.direction === "self" ? "self" : "peer") + (i === lastPeerIdx ? " latest" : "") + (m.direction === "self" && m.source === "hosting" ? " hosted" : "");
        const mediaPrefix = m.mediaType === "channels_video"
          ? "🎬 [视频号] "
          : (m.mediaType === "wechat_article"
            ? "📄 [公众号文章] "
            : (m.mediaType === "image"
              ? "🖼️ [图片] "
              : (m.mediaType === "video" ? "🎥 [视频] " : "")));
        bubble.textContent = (mediaPrefix && !String(m.text || "").startsWith("[") ? mediaPrefix : "") + (m.text || "");
        const lowConf = (m.confidence !== null && m.confidence !== undefined && m.confidence < 0.6);
        const meta = document.createElement("div");
        meta.className = "bubble-time" + (lowConf ? " warn" : "");
        // 谁发的一目了然：source=manual_human（人工本人发送）/ hosting（托管自动回复）
        const actorTag = (m.direction === "self")
          ? (m.source === "manual_human" ? "👤 人工" : "🤖 托管自动")
          : "";
        meta.textContent = (m.at || "") + (actorTag ? " · " + actorTag : "") + (lowConf ? " · ⚠️OCR识别可能不准" : "");
        bubble.appendChild(meta);
        if (i === lastPeerIdx && m.direction === "peer") {
          const mark = document.createElement("div");
          mark.className = "bubble-time";
          mark.style.color = "var(--primary)";
          mark.textContent = "⬆ 待回复";
          bubble.appendChild(mark);
        }
        row.appendChild(bubble);
        frag.appendChild(row);
      }
      stream.replaceChildren(frag);
      stream.scrollTop = stream.scrollHeight;
    }

    function syncChatRecipient(value) {
      const recipient = document.getElementById("sendTarget");
      const previous = recipient.value.trim();
      const next = value.trim();
      if (previous !== next && !previous && location.hash.startsWith("#saved-draft=")) clearSavedDraftContext();
      if (previous !== next && previous) {
        const hadDraft = !!document.getElementById("sendText").value;
        resetDraftContext();
        if (hadDraft) setDraftStatus("已更换回复对象，请核对来信后重新起草。");
      }
      recipient.value = value;
      markSelectedThread(value.trim());
      syncChatTestContactBtn(value.trim());
    }

    // 相对时间：客服一眼看出「这条消息多久之前的」（刚刚/x分钟前/x小时前/x天前/日期）
    function fmtRelativeTime(tsMs) {
      if (!tsMs) return "";
      const diff = Date.now() - tsMs;
      if (diff < 0) return "";
      if (diff < 60_000) return "刚刚";
      if (diff < 3_600_000) return Math.floor(diff / 60_000) + " 分钟前";
      if (diff < 86_400_000) return Math.floor(diff / 3_600_000) + " 小时前";
      if (diff < 7 * 86_400_000) return Math.floor(diff / 86_400_000) + " 天前";
      const d = new Date(tsMs);
      const hm = d.toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"});
      const sameYear = d.getFullYear() === new Date().getFullYear();
      const md = (d.getMonth() + 1) + "-" + d.getDate();
      return sameYear ? md + " " + hm : d.getFullYear() + "-" + md + " " + hm;
    }

    function renderMonitorEvents() {
      const events = STATE?.monitor?.recentEvents || [];
      const container = document.getElementById("monitorEventsList");
      const currentTarget = (document.getElementById("previewTarget")?.value || "").trim();
      const focused = document.activeElement?.closest(".chat-thread-row")?.dataset.target;
      const conversations = new Map();
      for (const ev of events) {
        const target = (ev.target || "").trim();
        if (!target) continue;
        if (!conversations.has(target)) conversations.set(target, {title: target, incoming: "", time: "", sortTs: 0});
        const conversation = conversations.get(target);
        const stamp = new Date(ev.ts);
        if (Number.isFinite(stamp.getTime()) && stamp.getTime() > (conversation.sortTs || 0)) conversation.sortTs = stamp.getTime();
        // 频控暂停可视化：机器人对某人静默停手时，首页必须看得见
        if (ev.event === "auto_reply_rate_limited") {
          const t = Number.isFinite(stamp.getTime()) ? stamp.getTime() : 0;
          if (t >= (conversation.limitedTs || 0)) {
            conversation.limitedTs = t;
            conversation.limitedReason = String(ev.reason || "").split(":")[0];
          }
        }
        if (!conversation.incoming && ev.incomingText) {
          conversation.incoming = ev.incomingText;
          conversation.time = fmtRelativeTime(stamp.getTime());
        }
      }
      const disabledTargets = new Set(
        (STATE?.bindings || [])
          .filter((b) => b && b.autoReplyEnabled === false)
          .map((b) => String(b.target || "").trim().toLowerCase())
          .filter(Boolean)
      );
      const watchedSet = new Set(getWatchedTargets().map((t) => String(t).trim().toLowerCase()).filter(Boolean));
      for (const profile of (STATE?.analytics?.profiles || []).slice(0, 12)) {
        const target = (profile.target || profile.matchedTitle || "").trim();
        if (!target) continue;
        if (!conversations.has(target)) {
          if (disabledTargets.has(target.toLowerCase()) && !watchedSet.has(target.toLowerCase()) && !profile.messageCount) continue;
          conversations.set(target, {title: target, incoming: "", time: "", sortTs: 0, fromProfileOnly: true});
        }
        conversations.get(target).title = profile.matchedTitle || target;
      }
      const hostingActive = isHostingActive();
      for (const wt of getWatchedTargets()) {
        const target = String(wt || "").trim();
        if (!target) continue;
        const exists = [...conversations.keys()].some((k) => k.toLowerCase() === target.toLowerCase());
        if (!exists) {
          conversations.set(target, {title: target, incoming: "", time: hostingActive ? "关注中" : "已停止", sortTs: 0, isWatchedOnly: true});
        }
      }
      // 历史来信兜底：事件流里没有 incomingText 的会话，从联系人历史（含导入+实时回写）取最近一条客户来信
      const inboundByTarget = {};
      for (const lb of Object.values(STATE?.latestInbound || {})) {
        if (lb && lb.target) inboundByTarget[lb.target] = lb;
      }
      for (const [target, conversation] of [...conversations.entries()]) {
        const lb = inboundByTarget[target];
        if (lb) {
          const lbStamp = new Date(lb.sortAt || "");
          if (Number.isFinite(lbStamp.getTime()) && lbStamp.getTime() > (conversation.sortTs || 0)) conversation.sortTs = lbStamp.getTime();
        }
        if (conversation.fromProfileOnly && !conversation.incoming && !(lb && lb.text) && disabledTargets.has(target.toLowerCase())) {
          conversations.delete(target);
          continue;
        }
        if (conversation.incoming) continue;
        if (lb && lb.text) {
          conversation.incoming = lb.text;
          const lbTs = (conversation.sortTs || 0);
          conversation.time = fmtRelativeTime(lbTs) || lb.at || "";
        }
      }
      // 按「最新互动时间」排序：最近有动静的联系人在前，无时间信息的沉底（客服最关心"谁最近找我"）
      const orderedConversations = [...conversations.entries()].sort((a, b) => (b[1].sortTs || 0) - (a[1].sortTs || 0));
      setStatText("conversationCount", conversations.size ? String(conversations.size) : "");
      if (!conversations.size) {
        const offline = document.getElementById("homeConnection").dataset.state === "offline" && !STATE;
        container.innerHTML = `<p class="home-empty">${offline ? "暂时读不到会话。请刷新工作台，或手动填写会话。" : "还没有最近记录。可以手动填写会话，或巡检已绑定会话。"}</p>`;
        return;
      }
      container.innerHTML = orderedConversations.map(([target, entry]) => {
        const selected = currentTarget === target;
        const limitedFresh = entry.limitedTs && (Date.now() - entry.limitedTs) < 10 * 60_000;
        const limitedPill = limitedFresh
          ? `<span class="pill" title="防封频控暂停自动回复，配额/冷却恢复后自动继续">⏸ 频控中${entry.limitedReason ? " · " + escapeHtml(entry.limitedReason) : ""}</span>`
          : "";
        // 人工接管可视化+一键恢复：转人工后首页一眼可见、一键恢复，不用去联系人卡片里找
        const takenOver = Object.values(STATE?.monitor?.contacts || {}).find((c) => {
          const t = String(c?.target || "").trim().toLowerCase();
          return t ? t === target.toLowerCase() : false;
        })?.takenOver || Object.entries(STATE?.monitor?.contacts || {}).some(([k, c]) => {
          const t = String(c?.target || "").trim().toLowerCase();
          if (!t) return k.toLowerCase() === target.toLowerCase() && c?.takenOver;
          return false;
        }) || (() => {
          const k = target.toLowerCase();
          return Boolean((STATE?.monitor?.contacts || {})[k]?.takenOver);
        })();
        const resumeBtn = takenOver
          ? `<span class="link-btn" role="button" tabindex="0" onclick="event.stopPropagation(); resumeContact('${encArg(target)}')">▶️ 恢复 AI</span>`
          : "";
        const avatarUrl = avatarUrlFor(target);
        const avatarImg = avatarUrl
          ? `<img class="chat-avatar" src="${escapeHtml(avatarUrl)}" alt="" onerror="this.style.display='none'">`
          : "";
        const isWatched = watchedSet.has(target.toLowerCase());
        const watchBadge = isWatched
          ? (hostingActive
              ? `<span class="pill ok" style="font-size:10.5px; padding:1px 6px;">🟢 监视中</span>`
              : `<span class="pill" style="font-size:10.5px; padding:1px 6px; color:var(--text-muted); background:var(--surface-soft); border-color:var(--border);">⏸ 已停止</span>`)
          : "";
        const fallbackSnippet = isWatched
          ? (hostingActive ? "已关注监视 · 对方发消息将自动回复" : "已关注（托管已停止 · 点击顶部「一键托管」恢复）")
          : "暂无来信 · 对方发消息后会自动记录";
        return `
          <button type="button" class="chat-thread-row ${selected ? "active" : ""}" aria-pressed="${selected}" data-target="${escapeHtml(target)}" onclick="selectChatThread('${encArg(target)}', '${encArg(entry.incoming)}')">
            <span class="chat-row-top"><span class="chat-row-title">${avatarImg}<span>${escapeHtml(entry.title)}</span></span>${watchBadge}${takenOver ? `<span class="pill danger">🤚 人工接管中</span>` : ""}${limitedPill}<span class="chat-row-meta">${escapeHtml(entry.time)}</span></span>
            <span class="chat-row-snippet">${escapeHtml(entry.incoming || fallbackSnippet)}</span>
            ${resumeBtn}
          </button>`;
      }).join("");
      if (focused) [...container.querySelectorAll(".chat-thread-row")]
        .find(row => row.dataset.target === focused)?.focus({preventScroll:true});
      if (!currentTarget && !(document.getElementById("sendText")?.value || "").trim() && orderedConversations.length > 0) {
        const [firstTarget, firstEntry] = orderedConversations[0];
        selectChatThread(encArg(firstTarget), encArg(firstEntry.incoming || ""), false);
      }
    }

    function renderPersonaOptions() {
      const personas = Object.values(STATE.personas?.personas || {});
      const sel = document.getElementById("previewPersona");
      const cur = sel.value;
      sel.innerHTML = `<option value="">自动（使用该联系人当前绑定性格）</option>` + personas.map((p) => {
        return `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${escapeHtml(p.mbti)} · ${escapeHtml(p.interactionStyle)})</option>`;
      }).join("");
      if (cur) sel.value = cur;

      const models = STATE.models?.models || [];
      const mSel = document.getElementById("previewModelSelect");
      if (mSel) {
        const curM = mSel.value;
        const activeM = STATE.models?.activeModelId || "auto/deepseek-v4-pro";
        mSel.innerHTML = `<option value="">全局默认 (${escapeHtml(activeM)})</option>` + models.slice(0, 80).map((m) => {
          return `<option value="${escapeHtml(m.id)}">${escapeHtml(m.displayName || m.id)} · ${escapeHtml(m.ownedBy || m.routeGroup || "")}</option>`;
        }).join("");
        if (curM) mSel.value = curM;
      }
      const useLlmEl = document.getElementById("previewUseLlm");
      if (useLlmEl && STATE.models) {
        useLlmEl.checked = !!STATE.models.llmReplyEnabled;
      }
      if (typeof syncSettingsModalFromState === "function") {
        syncSettingsModalFromState();
      }
    }

    function renderKnowledgeList(entries) {
      const kb = STATE.knowledgeSummary || {};
      if (kb.dbPath) {
        document.getElementById("kbDbPathDesc").textContent = `FTS5 SQLite: ${kb.dbPath} · 共 ${kb.count} 条`;
      }
      const listEl = document.getElementById("kbList");
      if (!entries.length) {
        listEl.innerHTML = `<div style="grid-column:1/-1; padding:24px; text-align:center; color:var(--text-muted);">未命中相关知识或术语词条。</div>`;
        return;
      }
      listEl.innerHTML = entries.map((e) => {
        const cls = e.kind === "terminology" ? "special" : (e.kind === "script" ? "ok" : "accent");
        return `
          <div class="kb-item">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px;">
              <span class="pill ${cls}">${escapeHtml(e.kind)}</span>
              <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(e.source || "")} · rev ${escapeHtml(e.revision)}</span>
            </div>
            <div style="font-weight:700; font-size:14px; margin-bottom:4px;">${escapeHtml(e.title)}</div>
            <div style="font-size:12.5px; color:var(--text-secondary); white-space:pre-wrap;">${escapeHtml(e.body)}</div>
            ${(e.keywords && e.keywords.length) ? `<div class="chip-row" style="margin-top:8px;">${e.keywords.map((k) => `<span class="chip">#${escapeHtml(k)}</span>`).join("")}</div>` : ""}
          </div>
        `;
      }).join("");
    }

    function renderBotStudioBridge() {
      const b = STATE.botStudioBridge || {};
      const st = b.standalone || {};
      const dsh = b.dshPlugin || {};
      const bs = b.botStudio || {};

      const pillEl = document.getElementById("standaloneStatusPill");
      if (pillEl) {
        pillEl.className = st.appReady ? "pill ok" : "pill warn";
        pillEl.innerHTML = `<span class="dot"></span> ${st.appReady ? "独立 App 已就绪" : "待编译 .app"}`;
      }

      const stBody = document.getElementById("standaloneSoftwareBody");
      if (stBody) {
        stBody.innerHTML = `
          <div class="kpi-card">
            <div class="kpi-label">原生 macOS 桌面软件</div>
            <div class="kpi-value">${st.appReady ? "READY" : "MISSING"}</div>
            <div class="kpi-sub">${escapeHtml(st.appName || "WeChat Bot.app")}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">独立 Web 控制端</div>
            <div class="kpi-value">18788</div>
            <div class="kpi-sub">${escapeHtml(st.webConsoleUrl || "http://127.0.0.1:18788/")}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">MCP Tools 总数</div>
            <div class="kpi-value">${b.mcpToolCount || 0}</div>
            <div class="kpi-sub">stdio + HTTP Fail-Closed</div>
          </div>
        `;
      }
      const stBox = document.getElementById("standalonePathsBox");
      if (stBox) {
        const sig = st.signing || {};
        const targets = Array.isArray(sig.targets) ? sig.targets : [];
        const firstTarget = targets[0] || {};
        const authName = sig.name || firstTarget.authority || sig.mode || "unconfigured";
        const usesCdhash = targets.length > 0 ? targets.some(t => Boolean(t.usesCdhash)) : false;
        stBox.textContent =
          `App Bundle : ${st.appBundlePath || ""}\n` +
          `Native Bin : ${st.appExecutablePath || ""}\n` +
          `CLI Entry  : ${st.cliPath || ""}\n` +
          `Launch Cmd : open "${st.appBundlePath || ""}"\n` +
          `Signing    : ${authName} (${sig.certificateSha1 || "n/a"})\n` +
          `No-Popup   : zeroPopupVerified=${Boolean(sig.zeroPopupVerified)} · usesCdhash=${usesCdhash}`;
      }

      const dshMetrics = document.getElementById("dshBridgeMetrics");
      if (dshMetrics) {
        const tabs = (bs.fourTabPages || []).join(" · ") || "overview · console · workflows · page_spec";
        dshMetrics.innerHTML = `
          <div class="kpi-card">
            <div class="kpi-label">DSH Plugin ID</div>
            <div class="kpi-value" style="font-size:15px;">${escapeHtml(dsh.pluginId || "dsh-plugin-wechat-ecosystem")}</div>
            <div class="kpi-sub">${escapeHtml(dsh.packageName || "@dsh-market/wechat-ecosystem")}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">dsh2codex 编译验收</div>
            <div class="kpi-value">${dsh.dsh2codexVerified ? "PASS" : "PENDING"}</div>
            <div class="kpi-sub">${dsh.panelCount || 0} Panels · ${dsh.toolCount || 0} Tools · ${dsh.verticalTaskCount || 0} Vertical</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Bot Studio Host & 4-Tab</div>
            <div class="kpi-value">${bs.hostAppInstalled ? "FOUND" : "LOCAL"}</div>
            <div class="kpi-sub">${escapeHtml(tabs)}</div>
          </div>
        `;
      }
      const dshBox = document.getElementById("dshBridgeOutputsBox");
      if (dshBox) {
        dshBox.textContent =
          `DSH Manifest    : ${dsh.manifestPath || ""}\n` +
          `Catalog Entry   : ${dsh.catalogEntryPath || ""}\n` +
          `4-Tab Preset    : ${bs.workbenchPresetPath || ""}\n` +
          `4-Tab Plugin    : ${bs.workbenchPluginPath || ""}\n` +
          `Standalone Page : ${bs.standalonePageHtmlPath || ""}\n` +
          `Integration Pkg : ${bs.bundlePath || ""}\n` +
          `Workbench SHA   : ${bs.workbenchSha256 || ""}`;
      }
    }

    async function compileAndExportBotStudioBundle() {
      try {
        const { data } = await apiJson("/api/botstudio-bridge", {
          method: "POST",
          body: JSON.stringify({ action: "export_bundle" }),
        });
        showToast(
          data.dsh2codexVerified
            ? `编译并导出成功 (${data.engine}) -> ${data.fourTabPages ? data.fourTabPages.length : 4}-Tab Ready`
            : `已导出兼容包 (${data.engine})`
        );
        await loadOverview(true);
      } catch (err) {
        showToast(`编译导出失败: ${err.message || err}`);
      }
    }

    async function rebuildStandaloneAppSilent() {
      showToast("正在静默重编原生 App 并校验固定签名 (0 弹窗)...");
      try {
        const { data } = await apiJson("/api/botstudio-bridge", {
          method: "POST",
          body: JSON.stringify({ action: "rebuild_app", installToHost: true }),
        });
        const sig = data.signing || {};
        showToast(
          data.zeroPopupVerified
            ? `静默编译完成 (${sig.name || sig.mode || "local-leaf"}) · 0弹窗已核验`
            : `重编完成 · ok=${Boolean(data.ok)}`
        );
        await loadOverview(true);
      } catch (err) {
        showToast(`静默重编失败: ${err.message || err}`);
      }
    }

    function renderOpenTab() {
      renderBotStudioBridge();
      const kimi = STATE.kimiDiscussion || {};
      const bodyEl = document.getElementById("kimiPanelBody");
      if (kimi.model) {
        document.getElementById("kimiMeta").textContent = `真实调用模型: ${kimi.model} · Session ${kimi.kimiSessionId || ""} · ${kimi.recordedAt || ""}`;
        const themes = (kimi.coreThemes || []).map((t) => `
          <div class="kb-item" style="margin-bottom:10px;">
            <div style="font-weight:700; font-size:13.5px;">${escapeHtml(t.title)}</div>
            <div style="font-size:12.5px; color:var(--text-secondary); margin-top:4px;">${escapeHtml(t.summary)}</div>
          </div>
        `).join("");
        const guards = (kimi.safetyGuardrails || []).map((g) => `<li style="margin-bottom:4px;">${escapeHtml(g)}</li>`).join("");
        bodyEl.innerHTML = `${themes}<div style="font-size:13px; font-weight:600; margin:10px 0 6px;">🛡️ Kimi 评审确认的防封控护栏</div><ul style="margin:0; padding-left:18px; font-size:12.5px; color:var(--text-secondary);">${guards}</ul>`;
      } else {
        bodyEl.innerHTML = `<div style="color:var(--text-muted);">暂未找到 Kimi 讨论回执文件。</div>`;
      }

      document.getElementById("mcpConfigBox").textContent = JSON.stringify(STATE.mcpConfig || {}, null, 2);

      const snaps = STATE.snapshots || [];
      document.getElementById("snapshotsGrid").innerHTML = snaps.length
        ? snaps.map((s) => `
            <div class="snapshot-card">
              <a href="${escapeHtml(s.url)}" target="_blank">
                <img src="${escapeHtml(s.url)}?t=${Math.floor(s.mtime || 0)}" alt="${escapeHtml(s.name)}" loading="lazy" />
              </a>
              <div class="snapshot-meta">
                <strong>${escapeHtml(s.name)}</strong><br/>
                ${Math.round((s.sizeBytes || 0) / 1024)} KB
              </div>
            </div>
          `).join("")
        : `<div style="color:var(--text-muted);">暂无截图快照。</div>`;
    }

    async function toggleStudioAuth() {
      const authorized = !!(STATE && STATE.authorization && STATE.authorization.authorized);
      const { data } = await apiJson("/api/auth-toggle", {
        method: "POST",
        body: JSON.stringify({ action: authorized ? "revoke" : "grant" }),
      });
      showToast(authorized ? "已演练撤回 Studio 授权" : "已恢复 Bot Studio 全量授权");
      await loadOverview();
    }

    async function grantAllAuth() {
      await apiJson("/api/auth-toggle", {
        method: "POST",
        body: JSON.stringify({ action: "grant" }),
      });
      showToast("已授权 WeChat RPA 插件所有能力");
      await loadOverview();
    }

    async function changeCareLevel(encTarget, careLevel, enabled) {
      const target = decodeURIComponent(encTarget);
      await apiJson("/api/special-care", {
        method: "POST",
        body: JSON.stringify({ target, care_level: careLevel, enabled }),
      });
      showToast(`已更新「${target}」关怀等级 -> ${careLevel}`);
      await loadOverview();
    }

    async function toggleTakeover(encTarget, enableTakeover) {
      const target = decodeURIComponent(encTarget);
      await apiJson("/api/takeover", {
        method: "POST",
        body: JSON.stringify({
          target,
          action: enableTakeover ? "takeover" : "resume",
          reason: enableTakeover ? "Web 控制台人工接管" : "",
        }),
      });
      showToast(enableTakeover ? `已开启「${target}」人工接管` : `已恢复「${target}」AI 自动回复`);
      await loadOverview();
    }

    async function applyContactPersona(encTarget, selectId) {
      const target = decodeURIComponent(encTarget);
      const personaId = document.getElementById(selectId).value;
      await apiJson("/api/persona-switch", {
        method: "POST",
        body: JSON.stringify({ target, persona_id: personaId }),
      });
      showToast(`已将「${target}」性格切换为 ${personaId}`);
      await loadOverview();
    }

    function useCareDraft(encTarget, encDraft) {
      const target = decodeURIComponent(encTarget);
      const draft = decodeURIComponent(encDraft);
      document.getElementById("previewTarget").value = target;
      syncChatRecipient(target);
      document.getElementById("sendText").value = draft;
      switchTab("monitor");
      showToast(`已将「${target}」关怀草稿填入回复框`);
    }

    function quickPreviewContact(encTarget) {
      const target = decodeURIComponent(encTarget);
      document.getElementById("previewTarget").value = target;
      syncChatRecipient(target);
      switchTab("monitor");
      runReplyPreview();
    }

    // 从往来上下文框提取「最新一条对方来信」作为草稿生成的输入：
    // 框里的完整上下文是给人看的；生成草稿只应针对最新来信，而不是整个对话块。
    function extractLatestPeerMessage(raw) {
      const text = (raw || "").trim();
      if (!text.startsWith("[最近往来")) return text;
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean).slice(1);
      for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].startsWith("对方：")) {
          let m = lines[i].slice(3).trim();
          m = m.replace(/\s*⚠️OCR识别可能不准$/, "").trim();  // 先剥置信度标注
          const paren = m.lastIndexOf("（");
          if (paren !== -1 && m.endsWith("）")) m = m.slice(0, paren).trim();
          return m || text;
        }
      }
      return text;
    }

    async function runReplyPreview() {
      if (draftBusy || serviceBlocked) return;
      const target = document.getElementById("previewTarget").value.trim();
      syncChatRecipient(target);
      const incoming_text = extractLatestPeerMessage(document.getElementById("previewIncoming").value.trim());
      if (!target || !incoming_text) {
        setDraftStatus(target ? "请先填写对方消息。" : "请先选择或填写回复对象。", "error");
        document.getElementById(target ? "previewIncoming" : "previewTarget").focus();
        return;
      }
      const persona_override = document.getElementById("previewPersona").value || null;
      const model_id = (document.getElementById("previewModelSelect")?.value || "").trim() || null;
      const use_llm_el = document.getElementById("previewUseLlm");
      const use_llm = use_llm_el ? !!use_llm_el.checked : true;
      const request = ++draftRequest;
      const revision = draftRevision;
      const draftInput = document.getElementById("sendText");
      const originalDraft = draftInput.value;
      const rawIncoming = incoming_text;
      setDraftBusy(true);
      setDraftStatus("正在生成回复草稿，可继续查看会话。");
      let data;
      try {
        const speed_mode = WORKOS_STATE?.speedMode || "fast";
        const task_goal = (document.getElementById("workosGoalInput")?.value || WORKOS_STATE?.taskGoal || "").trim();
        ({ data } = await apiJson("/api/reply-preview", {
          method: "POST",
          body: JSON.stringify({ target, incoming_text, persona_override, model_id, use_llm, speed_mode, task_goal }),
        }));
      } catch (err) {
        if (request === draftRequest) setDraftStatus("生成失败，请重试。已保留你的输入。", "error");
        return;
      } finally {
        if (request === draftRequest) setDraftBusy(false);
      }
      if (request !== draftRequest) return;
      if (extractLatestPeerMessage(document.getElementById("previewIncoming").value.trim()) !== rawIncoming) {
        setDraftStatus("来信已更改，请重新生成。");
        return;
      }
      if (!data.ok || !data.replyText) {
        setDraftStatus("未能生成草稿，请重试。已保留你的输入。", "error");
        return;
      }
      const el = document.getElementById("replyPreviewResult");
      el.hidden = false;
      el.dataset.lastReply = data.replyText || "";
      el.dataset.lastIncoming = rawIncoming || "";
      el.dataset.lastOriginalDraft = data.replyText || "";
      const sendBox = document.getElementById("sendText");
      const edited = revision !== draftRevision || originalDraft !== draftInput.value;
      if (!edited) sendBox.value = data.replyText;
      const refs = data.basis?.documentRefs || data.matchedEntries || [];
      const personaLabel = data.persona?.name || "默认人格";
      const personaMeta = data.persona?.mbti ? `${personaLabel} · ${data.persona.mbti}` : personaLabel;
      const reviewBanner = data.needsHumanReview
        ? `<div class="workos-human-review-alert" role="status">⚠️ <b>建议人工核实</b>：${escapeHtml(data.humanReviewReason || "涉及退款/投诉或当前资料未覆盖，请人工核实后再发送")}</div>`
        : "";
      const sta = data.seeThinkAct || null;
      const staHtml = sta ? `
        <div class="see-think-act-grid" id="seeThinkActBar">
          <div class="sta-step"><strong>👁️ 看 · 感知</strong>${escapeHtml(sta.see?.summary || "")}</div>
          <div class="sta-step"><strong>🧠 想 · 推理</strong>${escapeHtml(sta.think?.summary || "")}</div>
          <div class="sta-step"><strong>✍️ 做 · 执行</strong>${escapeHtml(sta.act?.summary || "")}</div>
        </div>
      ` : "";
      const modelMeta = data.generationMode === "llm_magpie"
        ? `${data.modelUsed || "Magpie"} · ${data.latencyMs ?? "-"}ms`
        : "知识库规则匹配";
      const autoScore = data.autoScore || null;
      const scoreBadge = autoScore
        ? `<span class="pill ${Number(autoScore.overallScore || 0) >= 70 ? "ok" : "warn"}" style="margin-right:6px;">自评 ${escapeHtml(autoScore.overallScore)}分 · ${"★".repeat(Math.max(1, Number(autoScore.stars || 3)))}</span>`
        : "";
      el.innerHTML = `
        <div>
          ${reviewBanner}
          ${staHtml}
          ${edited ? `<div class="draft-suggestion"><strong>新建议</strong><p>${escapeHtml(data.replyText)}</p></div>` : ""}
          <details class="chat-thinking-details">
            <summary>${scoreBadge}草稿依据 · ${escapeHtml(personaMeta)} · ${escapeHtml(modelMeta)} · 引用 ${data.matchedCount ?? refs.length ?? 0} 条</summary>
            ${refs.length ? `<ul style="margin:8px 0 0; padding-left:18px;">${refs.map((r) => `<li>${escapeHtml(r.title)}</li>`).join("")}</ul>` : `<div style="margin-top:6px;">无额外知识条目命中（已自动记录至 WorkOS 反思队列）。</div>`}
          </details>
        </div>
      `;
      renderDraftQualityFeedbackBar({
        target,
        incomingText: rawIncoming,
        replyText: data.replyText || "",
        turnId: data.turnId || null,
        autoScore,
      });
      if (!refs.length) loadWorkosHarness(false);
      setDraftStatus(edited ? "已保留手工修改，新建议显示在下方。" : "草稿已填入，可继续编辑；修改后可点「✨ 纠偏沉淀 SOP」。");
    }

    function copyPreviewToSender() {
      const txt = document.getElementById("replyPreviewResult").dataset.lastReply || "";
      if (!txt) {
        showToast("请先生成智能回复预览");
        return;
      }
      document.getElementById("sendTarget").value = document.getElementById("previewTarget").value.trim();
      document.getElementById("sendText").value = txt;
      showToast("已填入安全发送闸门");
    }

    let sendInFlight = false;

    function confirmLiveSend(target, text) {
      const dialog = document.getElementById("confirmSendDialog");
      if (typeof dialog.showModal !== "function") {
        setDraftStatus("当前窗口无法打开发送确认，消息未发送。", "error");
        return Promise.resolve(false);
      }
      setStatText("confirmSendTarget", `将当前草稿发送给「${target}」。`);
      const excerpt = Array.from(text.replace(/\s+/g, " "));
      setStatText("confirmSendExcerpt", excerpt.slice(0, 100).join("") + (excerpt.length > 100 ? "…" : ""));
      dialog.returnValue = "";
      document.getElementById("sendActionLabel").focus({preventScroll: true});
      return new Promise(resolve => {
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "send"), {once: true});
        dialog.showModal();
      });
    }

    async function executeSafeSend() {
      if (sendInFlight || serviceBlocked) return;
      const recipient = document.getElementById("sendTarget");
      const editor = document.getElementById("sendText");
      const modeSelect = document.getElementById("sendMode");
      const target = recipient.value.trim();
      const text = editor.value.trim();
      const mode = modeSelect.value;
      if (!target || !text) {
        setDraftStatus(target ? "请先填写回复草稿。" : "请先选择或填写回复对象。", "error");
        (target ? editor : document.getElementById("previewTarget")).focus();
        return;
      }
      if (/^\s*[#＃]\s*\S/.test(text)) {
        await executeSupervisorDirectiveFromComposer();
        return;
      }
      sendInFlight = true;
      try {
        if (mode === "confirm_send" && !(await confirmLiveSend(target, text))) return;
        if (serviceBlocked) return;
        if (target !== recipient.value.trim() || text !== editor.value.trim() || mode !== modeSelect.value) {
          setDraftStatus("回复对象、草稿或操作方式已变更，请重新确认。", "error");
          return;
        }
        const { data } = await apiJson("/send", {
          method: "POST",
          body: JSON.stringify({
            target, text, dry_run: mode === "dry_run",
            silent_mode: mode !== "confirm_send", confirm_send: mode === "confirm_send",
          }),
        });
        if (target !== recipient.value.trim()) return;
        const title = data.ok
          ? (mode === "dry_run" ? "模拟检查完成，未发送消息。" : mode === "silent_verify"
            ? "校验操作完成，请查看回执。" : "发送操作已完成，请查看回执确认结果。")
          : "操作未确认成功，请查看回执。";
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${title}</p><details><summary>查看回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
        const prevEl = document.getElementById("replyPreviewResult");
        renderDraftQualityFeedbackBar({
          target,
          incomingText: (document.getElementById("previewIncoming")?.value || prevEl?.dataset.lastIncoming || "").trim(),
          replyText: text,
          turnId: data.turnId || null,
          autoScore: null,
        });
        await loadOverview();
      } catch (err) {
        setDraftStatus("没有收到操作回执。请核对微信后再决定是否重试。", "error");
      } finally {
        sendInFlight = false;
      }
    }

    function insertWeChatEmoji(code) {
      const editor = document.getElementById("sendText");
      if (!editor) return;
      const start = editor.selectionStart ?? editor.value.length;
      const end = editor.selectionEnd ?? editor.value.length;
      const cur = editor.value || "";
      const prefixSpace = (start > 0 && !/\s$/.test(cur.slice(0, start))) ? " " : "";
      const insertText = prefixSpace + code;
      editor.value = cur.slice(0, start) + insertText + cur.slice(end);
      editor.focus();
      const pos = start + insertText.length;
      editor.setSelectionRange(pos, pos);
    }

    async function sendWeChatStickerQuick(tab = "favorites", slot = 0) {
      if (sendInFlight || serviceBlocked) return;
      const recipient = document.getElementById("sendTarget");
      const modeSelect = document.getElementById("sendMode");
      const target = (recipient?.value || "").trim();
      if (!target) {
        setDraftStatus("请先选择要发送表情的好友。", "error");
        return;
      }
      const mode = modeSelect ? modeSelect.value : "dry_run";
      const dryRun = mode !== "confirm_send";
      if (!dryRun && !(await confirmLiveSend(target, `[微信${tab === "emoji" ? "小表情" : "收藏表情"} #${slot + 1}]`))) return;
      try {
        const { data } = await apiJson("/api/send-sticker", {
          method: "POST",
          body: JSON.stringify({ target, tab, slot, dry_run: dryRun, confirm_send: !dryRun }),
        });
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${data.ok ? (dryRun ? "表情坐标模拟检查完成，未真实点击。" : "已触发微信表情发送。") : "表情发送未成功。"}</p><details><summary>查看回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
      } catch (err) {
        setDraftStatus("发送表情失败: " + err.message, "error");
      }
    }

    async function searchAndSendWebImageQuick() {
      if (sendInFlight || serviceBlocked) return;
      const target = (document.getElementById("sendTarget")?.value || "").trim();
      if (!target) { setDraftStatus("请先选择好友。", "error"); return; }
      const rawQuery = (document.getElementById("quickImageQuery")?.value || "").trim();
      const draftFallback = (document.getElementById("sendText")?.value || "").trim().slice(0, 24);
      const query = rawQuery || draftFallback;
      if (!query) {
        setDraftStatus("请在左侧输入框填入搜图关键词（或先在草稿框输入主题）。", "error");
        document.getElementById("quickImageQuery")?.focus();
        return;
      }
      const mode = document.getElementById("sendMode")?.value || "dry_run";
      const dryRun = mode !== "confirm_send";
      try {
        const { data } = await apiJson("/api/search-send-image", {
          method: "POST",
          body: JSON.stringify({ target, query, dry_run: dryRun, confirm_send: !dryRun, manualTrigger: true }),
        });
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${data.ok ? (dryRun ? "已搜图并完成发送预检（未实发）。" : "已搜图并发送给好友。") : "搜图发送未成功。"}</p><details><summary>查看回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
      } catch (err) {
        setDraftStatus("搜图失败: " + err.message, "error");
      }
    }

    async function annotateAndSendImageQuick() {
      if (sendInFlight || serviceBlocked) return;
      const target = (document.getElementById("sendTarget")?.value || "").trim();
      if (!target) { setDraftStatus("请先选择好友。", "error"); return; }
      const kwRaw = (document.getElementById("quickImageQuery")?.value || "").trim();
      const noteRaw = (document.getElementById("quickAnnotateNote")?.value || "").trim();
      const draftNote = (document.getElementById("sendText")?.value || "").trim().slice(0, 80);
      const note = noteRaw || draftNote || "重点关注红框位置";
      const mode = document.getElementById("sendMode")?.value || "dry_run";
      const dryRun = mode !== "confirm_send";
      try {
        const { data } = await apiJson("/api/annotate-send-image", {
          method: "POST",
          body: JSON.stringify({ target, keywords: kwRaw, note, dry_run: dryRun, confirm_send: !dryRun, manualTrigger: true }),
        });
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${data.ok ? (dryRun ? "已生成红框标注图并预检（未实发）。" : "已将标注图片回传给好友。") : "标注失败。"}</p><details><summary>查看回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
      } catch (err) {
        setDraftStatus("标注图片失败: " + err.message, "error");
      }
    }

    async function joinTencentMeetingQuick() {
      if (sendInFlight || serviceBlocked) return;
      const target = (document.getElementById("sendTarget")?.value || "").trim();
      const rawHint = (document.getElementById("quickImageQuery")?.value || "").trim();
      const codeMatch = rawHint.match(/(\d[\d\s\-]{7,13}\d)/);
      const meetingCode = codeMatch ? codeMatch[1].replace(/[\s\-]+/g, "") : "";
      const pwdMatch = rawHint.match(/(?:密码[:：\s]*)([A-Za-z0-9]{4,8})/);
      const pwdVal = (document.getElementById("quickAnnotateNote")?.value || "").trim() || (pwdMatch ? pwdMatch[1] : "");
      const mode = document.getElementById("sendMode")?.value || "dry_run";
      const dryRun = mode !== "confirm_send";
      try {
        const { data } = await apiJson("/api/join-meeting-botstudio", {
          method: "POST",
          body: JSON.stringify({
            target,
            meeting_code: meetingCode,
            password: pwdVal,
            click_card: true,
            dry_run: dryRun,
            confirm_send: !dryRun,
          }),
        });
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${data.joined ? "已点击腾讯会议卡片入会并拉起 Bot Studio 语音参会。" : (data.needsPassword ? "已点开卡片唤起腾讯会议，请在右侧输入会议密码。" : (dryRun ? "已完成腾讯会议卡片入会预检（未实点击）。" : "已触发入会流程。"))}</p><details><summary>查看回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
      } catch (err) {
        setDraftStatus("腾讯会议入会失败: " + err.message, "error");
      }
    }

    async function voiceCallQuick(action) {
      if (sendInFlight || serviceBlocked) return;
      const target = (document.getElementById("sendTarget")?.value || "").trim();
      const mode = document.getElementById("sendMode")?.value || "dry_run";
      const dryRun = mode !== "confirm_send";
      const hint = (document.getElementById("quickImageQuery")?.value || "").trim().toLowerCase();
      const app = hint.includes("wecom") || hint.includes("企微") || hint.includes("企业") ? "wecom" : (action === "dial" ? "wechat" : "all");
      const greeting = (document.getElementById("sendText")?.value || "").trim();
      try {
        const { data } = await apiJson("/api/voice-call", {
          method: "POST",
          body: JSON.stringify({
            target,
            action: action || "dial",
            app,
            call_type: "audio",
            greeting,
            dry_run: dryRun,
            confirm_send: !dryRun,
          }),
        });
        const label = action === "hangup"
          ? (dryRun ? "已预检挂断通话。" : "已挂断通话并恢复本机麦克风。")
          : (action === "answer"
            ? (dryRun ? "已预检接听来电。" : "已尝试接听来电并拉起 AI 语音通话。")
            : (dryRun ? "已完成微信语音拨号预检（未实点击）。" : "已拨出微信语音电话并启动实时语音伴侣。"));
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${label}</p><details><summary>查看通话回执</summary><pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre></details></div>`;
      } catch (err) {
        setDraftStatus("语音通话操作失败: " + err.message, "error");
      }
    }

    function syncSendModeLabel() {
      const mode = document.getElementById("sendMode").value;
      const labels = {
        dry_run: ["模拟检查", "模拟检查不会向微信写入消息。"],
        silent_verify: ["校验草稿", "会粘贴到微信校验，随后清空，不发送。"],
        confirm_send: ["发送到微信…", "先确认回复对象，再发送到微信。"],
      };
      setStatText("sendActionLabel", labels[mode][0]);
      setStatText("sendModeHint", labels[mode][1]);
    }

    async function triggerActivateWeChat() {
      showToast("正在尝试唤醒并点击微信窗口 / Dock 图标...");
      try {
        const { data } = await apiJson("/api/activate-wechat", {
          method: "POST",
          body: JSON.stringify({}),
        });
        const box = document.getElementById("watchRunReceipt");
        box.style.display = "block";
        box.innerHTML = `<pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
        showToast(data.ok ? `已恢复微信窗口 (${data.recoveryMethod || "frontmost"})` : `唤醒失败: ${data.error || ""}`);
      } catch (err) {
        showToast("唤醒失败: " + err.message);
      }
      await loadOverview();
    }

    async function triggerWatchOnce(confirmSend) {
      const { data } = await apiJson("/api/watch-once", {
        method: "POST",
        body: JSON.stringify({ auto_reply: true, confirm_send: confirmSend }),
      });
      const box = document.getElementById("watchRunReceipt");
      box.style.display = "block";
      box.innerHTML = `<pre class="code-box">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
      showToast(`巡检完成 · 扫描 ${data.boundTargetsScanned || 0} 个对象 · 回复 ${data.repliesDispatched || 0} 条`);
      await loadOverview();
    }

    const KB_QUICK_QUESTIONS = ["你们是做什么的", "是机器人吗", "多少钱", "什么时候在线", "怎么转人工"];
    const KB_KIND_DEFS = [
      { kind: "faq", icon: "❓", label: "faq · 常见问题", desc: "客户高频问答，机器人直接引用作答" },
      { kind: "knowledge", icon: "📘", label: "knowledge · 业务知识", desc: "公司介绍 / 产品与服务" },
      { kind: "script", icon: "💬", label: "script · 客服话术", desc: "标准应答话术模板" },
      { kind: "terminology", icon: "🏷️", label: "terminology · 专业术语", desc: "术语与内部缩写" },
    ];

    function renderKbQuickChips() {
      const box = document.getElementById("kbQuickChips");
      if (!box) return;
      box.innerHTML = KB_QUICK_QUESTIONS.map(
        (q) => `<span class="kb-chip" onclick="kbQuickSearch('${q}')">💬 ${q}</span>`
      ).join("");
    }

    function renderKbKindGrid() {
      const grid = document.getElementById("kbKindGrid");
      if (!grid) return;
      const entries = STATE?.knowledgeSummary?.entries || [];
      const activeKind = document.getElementById("kbKindFilter").value || "";
      grid.innerHTML = KB_KIND_DEFS.map((def) => {
        const n = entries.filter((e) => e.kind === def.kind).length;
        return `
          <div class="kb-grid-item${activeKind === def.kind ? " active" : ""}" onclick="kbFilterKind('${def.kind}')">
            <div class="kb-grid-title"><span>${def.icon}</span><span>${def.label}</span><span class="kb-grid-count">${n}</span></div>
            <div class="kb-grid-desc">${def.desc}</div>
          </div>
        `;
      }).join("");
    }

    function kbQuickSearch(q) {
      document.getElementById("kbSearchInput").value = q;
      document.getElementById("kbKindFilter").value = "";
      searchKb();
    }

    function kbFilterKind(kind) {
      const select = document.getElementById("kbKindFilter");
      select.value = (select.value === kind) ? "" : kind;
      searchKb();
    }

    async function searchKb() {
      const query = document.getElementById("kbSearchInput").value.trim();
      const kind = document.getElementById("kbKindFilter").value || null;
      renderKbKindGrid();
      if (!query && !kind) {
        renderKnowledgeList(STATE?.knowledgeSummary?.entries || []);
        return;
      }
      if (!query && kind) {
        const list = (STATE?.knowledgeSummary?.entries || []).filter((e) => e.kind === kind);
        renderKnowledgeList(list);
        return;
      }
      const { data } = await apiJson("/api/kb-search", {
        method: "POST",
        body: JSON.stringify({ query, kind, limit: 30 }),
      });
      renderKnowledgeList(data.entries || data.hits || []);
    }

    function resetKbView() {
      document.getElementById("kbSearchInput").value = "";
      document.getElementById("kbKindFilter").value = "";
      renderKbKindGrid();
      renderKnowledgeList(STATE?.knowledgeSummary?.entries || []);
    }

    async function saveKbEntry() {
      const title = document.getElementById("kbNewTitle").value.trim();
      const kind = document.getElementById("kbNewKind").value;
      const body = document.getElementById("kbNewBody").value.trim();
      const kws = document.getElementById("kbNewKeywords").value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      if (!title || !body) {
        showToast("标题和内容不能为空");
        return;
      }
      await apiJson("/api/kb-save", {
        method: "POST",
        body: JSON.stringify({ title, body, kind, keywords: kws }),
      });
      document.getElementById("kbNewTitle").value = "";
      document.getElementById("kbNewBody").value = "";
      document.getElementById("kbNewKeywords").value = "";
      showToast(`已发布条目「${title}」到 FTS5 知识库`);
      await loadOverview();
    }

    async function syncOpenBotKb() {
      const { data } = await apiJson("/api/kb-sync", {
        method: "POST",
        body: JSON.stringify({}),
      });
      showToast(`同步完成：共 ${data.totalPublishedEntries || 0} 条`);
      await loadOverview();
    }

    function copyMcpConfig() {
      const txt = JSON.stringify(STATE?.mcpConfig || {}, null, 2);
      navigator.clipboard?.writeText(txt).then(() => showToast("已复制 MCP 配置 JSON"));
    }

    function renderModelsHub() {
      const hub = STATE?.models || {};
      const online = !!hub.gatewayOnline;
      document.getElementById("mHubGatewayStatus").innerHTML = online
        ? `<span style="color:var(--primary);">🟢 在线 · ${escapeHtml(hub.gatewayUrl || "127.0.0.1:3425")}</span>`
        : `<span style="color:var(--warn);">🟡 离线降级目录 · ${escapeHtml(hub.gatewayUrl || "")}</span>`;
      document.getElementById("mHubActiveModel").textContent = hub.activeModelId || "-";
      document.getElementById("mHubFallbackModel").textContent = hub.fallbackModelId || "-";
      document.getElementById("mHubCounts").textContent = `${hub.totalModelCount ?? 0} 个模型 · ${(hub.providers || []).length} 个供应商`;
      const tog = document.getElementById("globalLlmToggle");
      if (tog) tog.checked = !!hub.llmReplyEnabled;

      const providers = hub.providers || [];
      document.getElementById("providersGrid").innerHTML = providers.map((p) => {
        const badge = p.enabled ? `<span class="pill ok">已启用</span>` : `<span class="pill">未启用</span>`;
        const keyBadge = p.hasKey
          ? `<span class="chip">🔑 密钥: ${escapeHtml(p.maskedKey || "••••••••")}</span>`
          : (p.apiKeyEnv ? `<span class="chip">🔑 环境变量 ${escapeHtml(p.apiKeyEnv)}</span>` : `<span class="chip">无需密钥 / 未填</span>`);
        return `
          <div class="provider-card">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
              <strong>${escapeHtml(p.name)}</strong>
              ${badge}
            </div>
            <div style="font-size:11.5px; color:var(--text-muted); word-break:break-all;">${escapeHtml(p.baseUrl)} · ${escapeHtml(p.api)}</div>
            <div class="chip-row">${keyBadge}<span class="chip">默认: ${escapeHtml(p.defaultModel || "-")}</span></div>
            <div style="display:flex; gap:6px; margin-top:4px;">
              <button class="sm" onclick="fillProviderForm('${encArg(p.id)}')">✏️ 配置 / 填写密钥</button>
            </div>
          </div>
        `;
      }).join("");

      const groups = hub.providerGroups || [];
      const pills = [
        `<button class="filter-pill ${MODEL_FILTER === "all" ? "active" : ""}" onclick="setModelFilter('all')">全部 (${hub.totalModelCount ?? 0})</button>`,
        `<button class="filter-pill ${MODEL_FILTER === "recommended" ? "active" : ""}" onclick="setModelFilter('recommended')">⭐ 推荐模型</button>`,
        ...groups.map((g) => `<button class="filter-pill ${MODEL_FILTER === g.name ? "active" : ""}" onclick="setModelFilter('${encArg(g.name)}')">${escapeHtml(g.name)} (${g.count})</button>`),
      ];
      document.getElementById("modelFilterPills").innerHTML = pills.join("");

      renderModelsCatalog();

      const bindingsMap = hub.contactModelBindings || {};
      const bindKeys = Object.keys(bindingsMap);
      document.getElementById("contactModelBindingsBox").innerHTML = bindKeys.length
        ? `<div class="chip-row">${bindKeys.map((k) => `<span class="pill accent">🎯 ${escapeHtml(k)} → ${escapeHtml(bindingsMap[k])}</span>`).join("")}</div>`
        : `<div style="font-size:12.5px; color:var(--text-muted);">暂未单独绑定好友模型，所有好友默认使用全局模型 <strong>${escapeHtml(hub.activeModelId || "")}</strong></div>`;

      const profs = hub.profiles || [];
      document.getElementById("magpieProfilesBox").innerHTML = profs.length
        ? profs.map((pr) => `<div class="kb-item" style="margin-top:8px;"><strong>${escapeHtml(pr.name)}</strong><div style="font-size:11.5px; color:var(--text-muted);">Profile ID: ${escapeHtml(pr.id)} · ${escapeHtml(pr.baseUrl)}</div></div>`).join("")
        : `<div style="font-size:12px; color:var(--text-muted); margin-top:8px;">点击任意模型卡片「设为全局默认」即可生成 Magpie SHA-256 命名连接档案。</div>`;

      const calls = hub.recentCalls || [];
      document.getElementById("modelCallsList").innerHTML = calls.length
        ? calls.map((c) => `
            <div class="event-item">
              <div class="event-head">
                <div><span class="pill ${c.ok ? "ok" : "danger"}">${c.ok ? "OK" : "ERR"}</span> <strong>${escapeHtml(c.modelId)}</strong> <span class="chip">${escapeHtml(c.providerId || "")}</span></div>
                <span style="font-size:11.5px; color:var(--text-muted);">${escapeHtml(c.latencyMs ?? "-")} ms</span>
              </div>
              <div style="font-size:12px; color:var(--text-secondary);">${escapeHtml(c.preview || c.error || "")}</div>
            </div>
          `).join("")
        : `<div style="padding:18px; text-align:center; color:var(--text-muted);">暂无调用回执，可点击右上角「⚡ 实测当前默认模型」。</div>`;

      renderVisionAndAgentPanel();
    }

    function setModelFilter(filterEnc) {
      MODEL_FILTER = decodeURIComponent(filterEnc);
      renderModelsHub();
    }

    function renderModelsCatalog() {
      const hub = STATE?.models || {};
      const models = hub.models || [];
      const activeId = hub.activeModelId || "";
      const fallbackId = hub.fallbackModelId || "";
      const q = (document.getElementById("modelSearchInput")?.value || "").trim().toLowerCase();

      const filtered = models.filter((m) => {
        if (MODEL_FILTER === "recommended" && !m.recommended) return false;
        if (MODEL_FILTER !== "all" && MODEL_FILTER !== "recommended" && m.routeGroup !== MODEL_FILTER && m.ownedBy !== MODEL_FILTER && m.providerId !== MODEL_FILTER) return false;
        if (q) {
          const hay = [m.id, m.displayName, m.magpieLabel, m.ownedBy, m.routeGroup].join(" ").toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      });

      const grid = document.getElementById("modelsCatalogGrid");
      if (!filtered.length) {
        grid.innerHTML = `<div style="grid-column:1/-1; padding:20px; text-align:center; color:var(--text-muted);">未匹配到模型，请切换供应商筛选或刷新目录。</div>`;
        return;
      }

      grid.innerHTML = filtered.slice(0, 60).map((m) => {
        const isActive = m.id === activeId;
        const isFallback = m.id === fallbackId;
        const ctxStr = m.contextWindow ? `${Math.round(m.contextWindow / 1024)}K ctx` : "-";
        const mEnc = encArg(m.id);
        const pEnc = encArg(m.providerId || "magpie-gateway");
        return `
          <div class="model-card ${isActive ? "is-active-model" : ""}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px;">
              <div>
                <div style="font-weight:700; font-size:14px;">${escapeHtml(m.displayName || m.id)}</div>
                <div style="font-size:11.5px; color:var(--text-muted); word-break:break-all;">${escapeHtml(m.id)}</div>
              </div>
              <span class="pill ${isActive ? "ok" : (m.recommended ? "accent" : "")}">${isActive ? "当前默认" : (isFallback ? "容灾" : escapeHtml(m.ownedBy || m.routeGroup || ""))}</span>
            </div>
            <div class="chip-row">
              <span class="chip">📏 ${escapeHtml(ctxStr)}</span>
              ${m.reasoning ? `<span class="chip">🧠 Reasoning</span>` : ""}
              ${m.toolCall ? `<span class="chip">🔧 ToolCall</span>` : ""}
              ${m.vision ? `<span class="chip">👁️ Vision</span>` : ""}
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:4px;">
              <button class="sm ${isActive ? "ok" : "primary"}" onclick="selectModel('${mEnc}', '${pEnc}')">${isActive ? "✓ 已选用" : "设为全局默认"}</button>
              <button class="sm" onclick="bindModelToPreviewContact('${mEnc}', '${pEnc}')">🎯 绑定好友</button>
              <button class="sm accent" onclick="probeModel('${mEnc}', '${pEnc}')">⚡ 实测</button>
            </div>
          </div>
        `;
      }).join("");
    }

    async function refreshModelsHub() {
      const { data } = await apiJson("/api/models?refresh=1");
      if (!STATE) STATE = {};
      STATE.models = data;
      renderHeaderAndKpi();
      renderPersonaOptions();
      renderModelsHub();
      showToast(`已从 Magpie 同步 ${data.totalModelCount ?? 0} 个模型`);
    }

    async function selectModel(modelEnc, providerEnc) {
      const model_id = decodeURIComponent(modelEnc);
      const provider_id = providerEnc ? decodeURIComponent(providerEnc) : null;
      await apiJson("/api/model-select", {
        method: "POST",
        body: JSON.stringify({ model_id, provider_id }),
      });
      showToast(`已切换全局默认模型 -> ${model_id}`);
      await loadOverview();
    }

    async function bindModelToPreviewContact(modelEnc, providerEnc) {
      const model_id = decodeURIComponent(modelEnc);
      const provider_id = providerEnc ? decodeURIComponent(providerEnc) : null;
      const contact = (document.getElementById("previewTarget")?.value || "").trim();
      if (!contact) { showToast("请先在对话页选择要绑定的会话。"); return; }
      await apiJson("/api/model-select", {
        method: "POST",
        body: JSON.stringify({ model_id, provider_id, contact }),
      });
      showToast(`已将「${contact}」专属模型绑定为 ${model_id}`);
      await loadOverview();
    }

    async function toggleGlobalLlm(enabled) {
      await apiJson("/api/model-select", {
        method: "POST",
        body: JSON.stringify({ llm_enabled: !!enabled }),
      });
      showToast(enabled ? "已开启 Magpie LLM + 知识库融合回复" : "已切换为纯本地 KB 模板快速回复");
      await loadOverview();
    }

    async function probeModel(modelEnc, providerEnc) {
      const model_id = modelEnc ? decodeURIComponent(modelEnc) : null;
      const provider_id = providerEnc ? decodeURIComponent(providerEnc) : null;
      showToast(`正在探测模型 ${model_id || "当前默认"} 连通性...`);
      try {
        const { data } = await apiJson("/api/model-probe", {
          method: "POST",
          body: JSON.stringify({ model_id, provider_id }),
        });
        const box = document.getElementById("modelProbeReceipt");
        box.style.display = "block";
        box.innerHTML = `<div class="kb-item" style="border:1px solid var(--primary);"><strong>⚡ 探针实测结果 (${escapeHtml(data.modelId)} · ${escapeHtml(data.latencyMs)}ms · HTTP ${escapeHtml(data.statusCode)})</strong><div style="margin-top:4px;">${escapeHtml(data.replyText || data.error || "")}</div></div>`;
        showToast(data.ok ? `探针成功 · ${data.latencyMs}ms` : `探针失败: ${data.error || ""}`);
      } catch (err) {
        const box = document.getElementById("modelProbeReceipt");
        box.style.display = "block";
        box.innerHTML = `<div class="kb-item" style="border:1px solid var(--danger);"><strong>⚡ 探针调用失败</strong><div>${escapeHtml(err.message)}</div></div>`;
        showToast("探针失败: " + err.message);
      }
      await loadOverview();
    }

    function fillProviderForm(provEnc) {
      const pid = decodeURIComponent(provEnc);
      const prov = (STATE?.models?.providers || []).find((p) => p.id === pid);
      if (!prov) return;
      document.getElementById("provIdInput").value = prov.id || "";
      document.getElementById("provNameInput").value = prov.name || "";
      document.getElementById("provApiInput").value = prov.api || "openai-completions";
      document.getElementById("provBaseUrlInput").value = prov.baseUrl || "";
      document.getElementById("provApiKeyInput").value = "";
      document.getElementById("provDefaultModelInput").value = prov.defaultModel || "";
      showToast(`已载入供应商「${prov.name}」配置`);
    }

    async function saveProviderConfig() {
      const provider_id = document.getElementById("provIdInput").value.trim() || "custom-openai";
      const name = document.getElementById("provNameInput").value.trim() || provider_id;
      const api = document.getElementById("provApiInput").value;
      const base_url = document.getElementById("provBaseUrlInput").value.trim();
      const api_key = document.getElementById("provApiKeyInput").value.trim();
      const default_model = document.getElementById("provDefaultModelInput").value.trim();
      if (!base_url) {
        showToast("请填写 Base URL");
        return;
      }
      const payload = {
        provider_id,
        name,
        api,
        base_url,
        default_model,
        enabled: true,
      };
      if (api_key) payload.api_key = api_key;
      if (provider_id === "magpie-gateway") payload.gateway_url = base_url;
      await apiJson("/api/provider-save", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      document.getElementById("provApiKeyInput").value = "";
      showToast(`已保存供应商「${name}」并刷新模型池`);
      await refreshModelsHub();
    }

    let LAST_EXPORTED_ARTICLE = null;

    function renderArticlesTab() {
      const items = (STATE && STATE.exportedArticles) ? STATE.exportedArticles : [];
      const badge = document.getElementById("exportedCountBadge");
      if (badge) badge.textContent = `${items.length} 篇`;
      const listEl = document.getElementById("exportedArticlesList");
      if (!listEl) return;
      if (!items.length) {
        listEl.innerHTML = `<div class="event-item"><div style="color:var(--text-muted); font-size:13px;">暂无导出记录。点击上方「从当前打开的微信文章一键导出 MD + 图片」即可生成。</div></div>`;
      } else {
        listEl.innerHTML = items.map((art) => {
          const slug = String(art.slug || "");
          const title = String(art.title || "未命名文章");
          const imgCnt = art.downloaded_image_count || art.image_count || 0;
          return `
            <div class="event-item" style="cursor:pointer;" onclick="selectExportedArticle('${escapeHtml(slug)}')">
              <div class="event-top">
                <span class="chip">${escapeHtml(art.mode || "export")}</span>
                <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(art.exported_at || "")}</span>
              </div>
              <div style="font-weight:700; font-size:13px; margin-top:4px;">${escapeHtml(title)}</div>
              <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
                图片 ${imgCnt} 张 · Markdown ${art.markdown_chars || 0} 字符 · <code>${escapeHtml(slug)}</code>
              </div>
            </div>
          `;
        }).join("");
      }
      if (LAST_EXPORTED_ARTICLE) {
        renderArticlePreview(LAST_EXPORTED_ARTICLE);
      } else if (items.length) {
        renderArticlePreview(items[0]);
      }
      renderAccountExportsList();
      renderChannelsExportsList();
    }

    function renderAccountExportsList() {
      const items = (STATE && STATE.exportedAccounts) ? STATE.exportedAccounts : [];
      const badge = document.getElementById("exportedAccountsBadge");
      if (badge) badge.textContent = `${items.length} 个服务号`;
      const listEl = document.getElementById("exportedAccountsList");
      if (!listEl) return;
      if (!items.length) {
        listEl.innerHTML = `<div class="event-item"><div style="color:var(--text-muted); font-size:12px;">暂无服务号批量导出存档。</div></div>`;
        return;
      }
      listEl.innerHTML = items.map((acc, idx) => `
        <div class="event-item" style="cursor:pointer;" onclick="previewBatchArchive('account', ${idx})">
          <div class="event-top">
            <span class="chip">${escapeHtml(acc.accountName || acc.slug || "Official Account")}</span>
            <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(acc.exportedAt || "")}</span>
          </div>
          <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
            已导出 ${acc.exportedCount || 0} / ${acc.totalDiscovered || 0} 篇 · <code>${escapeHtml(acc.indexMarkdownPath || acc.catalogDir || "")}</code>
          </div>
        </div>
      `).join("");
    }

    function renderChannelsExportsList() {
      const items = (STATE && STATE.exportedChannels) ? STATE.exportedChannels : [];
      const badge = document.getElementById("exportedChannelsBadge");
      if (badge) badge.textContent = `${items.length} 个作者`;
      const listEl = document.getElementById("exportedChannelsList");
      if (!listEl) return;
      if (!items.length) {
        listEl.innerHTML = `<div class="event-item"><div style="color:var(--text-muted); font-size:12px;">暂无视频号批量导出存档。</div></div>`;
        return;
      }
      listEl.innerHTML = items.map((ch, idx) => `
        <div class="event-item" style="cursor:pointer;" onclick="previewBatchArchive('channels', ${idx})">
          <div class="event-top">
            <span class="chip">${escapeHtml(ch.authorName || ch.slug || "Channels Author")}</span>
            <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(ch.exportedAt || "")}</span>
          </div>
          <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">
            已导出 ${ch.exportedCount || 0} 条 · 失败 ${ch.failedCount || 0} 条 · <code>${escapeHtml(ch.indexMarkdownPath || ch.bundleDir || "")}</code>
          </div>
        </div>
      `).join("");
    }

    function previewBatchArchive(kind, idx) {
      const list = kind === "account"
        ? ((STATE && STATE.exportedAccounts) || [])
        : ((STATE && STATE.exportedChannels) || []);
      const item = list[idx];
      if (!item) return;
      const title = kind === "account"
        ? `服务号：${item.accountName || item.slug || ""}`
        : `视频号：${item.authorName || item.slug || ""}`;
      document.getElementById("articleResultMeta").textContent = `${title} · 导出时间 ${item.exportedAt || ""}`;
      document.getElementById("articlePathsBox").innerHTML = `
        <div><strong>索引 INDEX.md：</strong><code>${escapeHtml(item.indexMarkdownPath || "")}</code></div>
        <div style="margin-top:4px;"><strong>目录 JSON：</strong><code>${escapeHtml(item.catalogJsonPath || "")}</code></div>
        <div style="margin-top:4px;"><strong>归档目录：</strong><code>${escapeHtml(item.catalogDir || item.bundleDir || "")}</code></div>
      `;
      document.getElementById("articleMdPreview").textContent = JSON.stringify(item, null, 2);
      document.getElementById("articleImagesGrid").innerHTML = `<div style="color:var(--text-muted); font-size:12px;">批量归档摘要已加载；单篇正文与图片请查看各子目录 article.md / assets/，视频请查看 videos/。</div>`;
    }

    function selectExportedArticle(slug) {
      const items = (STATE && STATE.exportedArticles) ? STATE.exportedArticles : [];
      const found = items.find((a) => String(a.slug || "") === String(slug));
      if (found) {
        LAST_EXPORTED_ARTICLE = found;
        renderArticlePreview(found);
      }
    }

    function renderArticlePreview(art) {
      const metaEl = document.getElementById("articleResultMeta");
      const pathsEl = document.getElementById("articlePathsBox");
      const mdEl = document.getElementById("articleMdPreview");
      const gridEl = document.getElementById("articleImagesGrid");
      if (!art || !metaEl || !pathsEl || !mdEl || !gridEl) return;
      const slug = String(art.slug || "");
      metaEl.textContent = `${art.title || ""} · ${art.mode || ""} · 本地图片 ${art.downloaded_image_count || 0} 张`;
      pathsEl.innerHTML = `
        <div><strong>Markdown 文件：</strong><code>${escapeHtml(art.markdown_path || "")}</code></div>
        <div style="margin-top:4px;"><strong>本地图片目录：</strong><code>${escapeHtml(art.assets_dir || "")}</code></div>
        ${art.source_url ? `<div style="margin-top:4px;"><strong>原文 URL：</strong><code>${escapeHtml(art.source_url)}</code></div>` : ""}
      `;
      mdEl.textContent = art.markdown_content || art.markdown_preview || "(点击「一键导出」后在此展示完整 Markdown，已保存到本地 article.md)";
      const imgs = (art.images || []).filter((r) => r.ok && r.local_rel_path && slug);
      if (!imgs.length) {
        gridEl.innerHTML = `<div style="color:var(--text-muted); font-size:12px;">本次导出暂无本地图片。</div>`;
      } else {
        gridEl.innerHTML = imgs.map((img) => {
          const src = `/exports/articles/${encodeURIComponent(slug)}/${img.local_rel_path}`;
          return `
            <div class="snap-card">
              <img src="${src}" alt="${escapeHtml(img.alt || "")}" loading="lazy" />
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px; word-break:break-all;">
                ${escapeHtml(img.local_rel_path)} (${Math.round((img.size_bytes || 0) / 1024)} KB)
              </div>
            </div>
          `;
        }).join("");
      }
    }

    async function refreshExportedArticles() {
      const { data } = await apiJson("/api/exported-articles?limit=20");
      if (STATE) {
        STATE.exportedArticles = data.articles || [];
      }
      renderArticlesTab();
      showToast(`已刷新 ${data.count || 0} 篇导出文章`);
    }

    async function exportOpenWeChatArticle() {
      const pages = Math.max(1, Number(document.getElementById("articlePagesInput").value || 4));
      const downloadImages = !!document.getElementById("articleDownloadImgs").checked;
      showToast("正在抓取当前微信打开的文章并保存本地图片...");
      const { data } = await apiJson("/api/export-article", {
        method: "POST",
        body: JSON.stringify({
          fromWindow: true,
          maxScrollPages: pages,
          downloadImages,
          tryCopyLink: true,
        }),
      });
      LAST_EXPORTED_ARTICLE = data;
      renderArticlePreview(data);
      await refreshExportedArticles();
      showToast(`导出成功：${data.title || "article.md"}（图片 ${data.downloaded_image_count || 0} 张）`);
    }

    async function exportWeChatArticleByUrl() {
      const url = (document.getElementById("articleUrlInput").value || "").trim();
      if (!url) {
        showToast("请先输入微信公众号文章链接（https://mp.weixin.qq.com/s/...）");
        return;
      }
      const downloadImages = !!document.getElementById("articleDownloadImgs").checked;
      showToast("正在抓取文章正文与下载防盗链图片...");
      const { data } = await apiJson("/api/export-article", {
        method: "POST",
        body: JSON.stringify({
          url,
          fromWindow: false,
          downloadImages,
        }),
      });
      LAST_EXPORTED_ARTICLE = data;
      renderArticlePreview(data);
      await refreshExportedArticles();
      showToast(`已导出：${data.title || "article.md"}`);
    }

    async function refreshAccountExports() {
      const { data } = await apiJson("/api/account-exports?limit=20");
      if (STATE) {
        STATE.exportedAccounts = data.accounts || [];
      }
      renderAccountExportsList();
      showToast(`已刷新 ${data.count || 0} 个服务号归档`);
    }

    async function exportAccountBatch() {
      const accountName = (document.getElementById("accountNameInput").value || "").trim();
      const albumUrl = (document.getElementById("accountAlbumUrlInput").value || "").trim();
      const urlsText = (document.getElementById("accountUrlsTextarea").value || "").trim();
      const scanOpenWindow = !!document.getElementById("accountScanWindow").checked;
      const maxArticles = Math.max(1, Number(document.getElementById("accountMaxArticles").value || 30));
      const downloadImages = !!document.getElementById("articleDownloadImgs").checked;
      const payload = {
        accountName,
        albumUrl,
        scanOpenWindow,
        maxArticles,
        downloadImages,
      };
      if (urlsText) {
        if (!urlsText.includes("\n") && !urlsText.startsWith("http")) {
          payload.fromFile = urlsText;
        } else {
          payload.articleUrls = urlsText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
        }
      }
      showToast("正在批量导出服务号 / 公众号历史文章...");
      const { data } = await apiJson("/api/account-exports", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refreshAccountExports();
      document.getElementById("articleResultMeta").textContent = `服务号批量导出完成：${data.accountName || accountName || ""} · ${data.exportedCount || 0} 篇`;
      document.getElementById("articlePathsBox").innerHTML = `
        <div><strong>索引文件：</strong><code>${escapeHtml(data.indexMarkdownPath || "")}</code></div>
        <div style="margin-top:4px;"><strong>Catalog JSON：</strong><code>${escapeHtml(data.catalogJsonPath || "")}</code></div>
      `;
      document.getElementById("articleMdPreview").textContent = JSON.stringify(data, null, 2);
      showToast(`服务号文章批量导出完成：共 ${data.exportedCount || 0} 篇`);
    }

    async function refreshChannelsExports() {
      const { data } = await apiJson("/api/channels-exports?limit=20");
      if (STATE) {
        STATE.exportedChannels = data.channels || [];
      }
      renderChannelsExportsList();
      showToast(`已刷新 ${data.count || 0} 个视频号作者归档`);
    }

    async function exportChannelsVideos() {
      const authorName = (document.getElementById("channelsAuthorInput").value || "").trim();
      const cacheDir = (document.getElementById("channelsCacheDirInput").value || "").trim();
      const manifestPath = (document.getElementById("channelsManifestInput").value || "").trim();
      const urlsText = (document.getElementById("channelsUrlsTextarea").value || "").trim();
      const scanOpenWindow = !!document.getElementById("channelsScanWindow").checked;
      const maxVideos = Math.max(1, Number(document.getElementById("channelsMaxVideos").value || 30));
      const payload = {
        authorName,
        cacheDir: cacheDir || null,
        manifestPath: manifestPath || null,
        scanOpenWindow,
        maxVideos,
        downloadMedia: true,
      };
      if (urlsText) {
        payload.videoUrls = urlsText.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
      }
      showToast("正在批量导出视频号视频与清单索引...");
      const { data } = await apiJson("/api/channels-exports", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refreshChannelsExports();
      document.getElementById("articleResultMeta").textContent = `视频号批量导出完成：${data.authorName || authorName || ""} · ${data.exportedCount || 0} 条`;
      document.getElementById("articlePathsBox").innerHTML = `
        <div><strong>索引文件：</strong><code>${escapeHtml(data.indexMarkdownPath || "")}</code></div>
        <div style="margin-top:4px;"><strong>Catalog JSON：</strong><code>${escapeHtml(data.catalogJsonPath || "")}</code></div>
      `;
      document.getElementById("articleMdPreview").textContent = JSON.stringify(data, null, 2);
      showToast(`视频号批量导出完成：共 ${data.exportedCount || 0} 条`);
    }

    let UI_SCHEMA_CACHE = null;
    let UI_STATE_CACHE = null;

    function renderUiProtocolTab() {
      const hg = (UI_STATE_CACHE && UI_STATE_CACHE.humanGuard) || (STATE && STATE.humanGuard) || {};
      const chip = document.getElementById("guardStatusChip");
      const metrics = document.getElementById("guardMetricsBox");
      const enabledEl = document.getElementById("guardEnabledInput");
      const cooldownEl = document.getElementById("guardCooldownInput");
      const idleEl = document.getElementById("guardIdleInput");

      if (enabledEl && typeof hg.enabled === "boolean") enabledEl.checked = hg.enabled;
      if (cooldownEl && hg.cooldownSeconds !== undefined) cooldownEl.value = hg.cooldownSeconds;
      if (idleEl && hg.idleResumeSeconds !== undefined) idleEl.value = hg.idleResumeSeconds;

      if (chip) {
        chip.textContent = !hg.enabled
          ? "已停用"
          : (hg.canOperate ? "🟢 空闲可恢复巡检" : `🟡 人工让路空窗期 (${hg.remainingCooldownSeconds ?? 0}s)`);
      }
      if (metrics) {
        const pos = hg.cursorPosition ? `(${hg.cursorPosition.x}, ${hg.cursorPosition.y})` : "未采样";
        metrics.innerHTML = `
          <div><strong>当前策略状态：</strong>${escapeHtml(hg.status || "-")} · ${hg.canOperate ? "✅ 允许自动检测" : "🛑 已暂停防抢鼠标"}</div>
          <div><strong>硬件静止时长：</strong>综合 ${escapeHtml(String(hg.anyInputIdleSeconds ?? "-"))}s · 鼠标 ${escapeHtml(String(hg.mouseIdleSeconds ?? "-"))}s · 键盘 ${escapeHtml(String(hg.keyboardIdleSeconds ?? "-"))}s</div>
          <div><strong>累计让路次数：</strong>${escapeHtml(String(hg.interventionsDetected ?? 0))} 次 · 光标坐标：<code>${escapeHtml(pos)}</code></div>
          ${hg.triggerReason ? `<div><strong>最近触发原因：</strong><code>${escapeHtml(hg.triggerReason)}</code></div>` : ""}
        `;
      }

      if (!UI_SCHEMA_CACHE) {
        fetchUiSchemaAndState();
        return;
      }
      const viewChip = document.getElementById("activeViewChip");
      if (viewChip) {
        viewChip.textContent = UI_STATE_CACHE?.activeView
          ? `当前识别视图: ${UI_STATE_CACHE.activeView}`
          : `Schema v${UI_SCHEMA_CACHE.schemaVersion || "1.0.0"}`;
      }

      const vrEl = document.getElementById("uiViewsRegionsList");
      if (vrEl) {
        const views = UI_SCHEMA_CACHE.views || [];
        const regions = UI_SCHEMA_CACHE.regions || [];
        vrEl.innerHTML = [
          ...views.map((v) => `
            <div class="event-item">
              <div class="event-top">
                <span class="chip">${UI_STATE_CACHE?.activeView === v.id ? "🟢 当前视图" : "视图 View"}</span>
                <code>${escapeHtml(v.id)}</code>
              </div>
              <div style="font-weight:700; font-size:13px; margin-top:4px;">${escapeHtml(v.title)}</div>
              <div style="font-size:12px; color:var(--text-muted);">${escapeHtml(v.description)}</div>
            </div>
          `),
          ...regions.map((r) => `
            <div class="event-item">
              <div class="event-top">
                <span class="chip">分区 Region</span>
                <code>${escapeHtml(r.id)}</code>
              </div>
              <div style="font-weight:700; font-size:13px; margin-top:4px;">${escapeHtml(r.title)}</div>
              <div style="font-size:12px; color:var(--text-muted);">${escapeHtml(r.purpose)}</div>
            </div>
          `),
        ].join("");
      }

      const targetsEl = document.getElementById("uiTargetsList");
      if (targetsEl) {
        const targets = UI_SCHEMA_CACHE.targets || [];
        const resolved = UI_STATE_CACHE?.resolvedTargets || {};
        targetsEl.innerHTML = targets.map((t) => {
          const rt = resolved[t.id] || {};
          const sp = rt.screenPoint ? `屏幕 (${rt.screenPoint.x}, ${rt.screenPoint.y})` : "等待实机探测坐标";
          return `
            <div class="event-item">
              <div class="event-top">
                <span class="chip">${escapeHtml(t.category)}</span>
                <code>${escapeHtml(t.id)}</code>
              </div>
              <div style="font-weight:700; font-size:13px; margin-top:4px;">${escapeHtml(t.title)}</div>
              <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">${escapeHtml(t.description)}</div>
              <div style="font-size:11.5px; color:var(--text-muted); margin-top:4px;">定位：<code>${escapeHtml(sp)}</code></div>
              <div style="display:flex; gap:6px; margin-top:6px;">
                <button class="sm" onclick="navigateUiTarget('${escapeHtml(t.id)}', true)">🧪 Dry-Run 定位</button>
                <button class="sm accent" onclick="navigateUiTarget('${escapeHtml(t.id)}', false)">🖱️ 安全导航</button>
              </div>
            </div>
          `;
        }).join("");
      }
    }

    async function fetchUiSchemaAndState(refreshOcr = false) {
      try {
        const [{ data: schemaData }, { data: stateData }] = await Promise.all([
          apiJson("/api/ui-schema"),
          apiJson(`/api/ui-state?refresh_ocr=${refreshOcr ? 1 : 0}`),
        ]);
        UI_SCHEMA_CACHE = schemaData;
        UI_STATE_CACHE = stateData;
        renderUiProtocolTab();
      } catch (err) {
        // Defer toast if unauthorized
      }
    }

    async function refreshUiProtocolState(refreshOcr = false) {
      showToast(refreshOcr ? "正在执行实机 Vision OCR 识别当前微信界面..." : "正在刷新 HID 鼠标/键盘静止状态...");
      await fetchUiSchemaAndState(refreshOcr);
      const { data: hgData } = await apiJson("/api/human-guard");
      if (STATE) STATE.humanGuard = hgData;
      renderHeaderAndKpi();
      renderUiProtocolTab();
      showToast("已更新微信界面协议与防抢鼠标状态");
    }

    async function saveHumanGuardConfig() {
      const enabled = !!document.getElementById("guardEnabledInput").checked;
      const cooldownSeconds = Number(document.getElementById("guardCooldownInput").value || 45);
      const idleResumeSeconds = Number(document.getElementById("guardIdleInput").value || 45);
      const { data } = await apiJson("/api/human-guard", {
        method: "POST",
        body: JSON.stringify({ enabled, cooldownSeconds, idleResumeSeconds }),
      });
      if (STATE) STATE.humanGuard = data;
      renderHeaderAndKpi();
      renderUiProtocolTab();
      showToast(`已更新防抢鼠标守卫：空窗 ${cooldownSeconds}s / 静止恢复 ${idleResumeSeconds}s`);
    }

    async function resetHumanGuardCooldown() {
      const { data } = await apiJson("/api/human-guard", {
        method: "POST",
        body: JSON.stringify({ resetCooldown: true }),
      });
      if (STATE) STATE.humanGuard = data;
      renderHeaderAndKpi();
      renderUiProtocolTab();
      showToast("已清除当前人工空窗期，可立即恢复巡检");
    }

    async function navigateUiTarget(targetId, dryRun) {
      const box = document.getElementById("uiNavResultBox");
      const { data } = await apiJson("/api/ui-navigate", {
        method: "POST",
        body: JSON.stringify({
          targetId,
          dryRun,
          respectHumanGuard: true,
        }),
      });
      if (box) {
        box.innerHTML = `<pre style="margin:0; white-space:pre-wrap; font-size:11.5px;">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
      }
      showToast(data.ok ? (dryRun ? `Dry-Run 定位成功: ${targetId}` : `导航成功: ${targetId}`) : `已拦截: ${data.error || "failed"}`);
    }

    function renderSoulAndBenchmarkTab() {
      const soul = STATE?.soulSummary || {};
      const owner = soul.ownerProfile || {};
      const ownerCard = document.getElementById("ownerSoulCard");
      if (ownerCard) {
        const sp = owner.speakingStyle || {};
        const traits = (owner.personalityTraits || []).map((t) => `<li>${escapeHtml(t)}</li>`).join("");
        const matrix = (owner.roleSwitchingMatrix || []).map((m) => `
          <div class="event-item" style="margin-bottom:6px;">
            <div class="event-top">
              <strong>对 ${escapeHtml(m.contact)}</strong>
              <span class="chip">${escapeHtml(m.roleMode)}</span>
            </div>
            <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">${escapeHtml(m.styleAdjustment)}</div>
            <div style="font-size:11.5px; color:var(--text-muted); margin-top:2px;">实录/语态：<code>${escapeHtml(m.exampleQuote)}</code></div>
          </div>
        `).join("");
        const oMems = (owner.ownerMemories || []).slice(0, 6).map((m) => `<span class="chip">${escapeHtml(m.category)}: ${escapeHtml(m.content)}</span>`).join("");

        ownerCard.innerHTML = `
          <div class="field-box" style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
              <div>
                <div style="font-size:15px; font-weight:700;">${escapeHtml(owner.displayName || "号主本我")} · <span style="color:var(--accent);">${escapeHtml(owner.archetypeTag || "")}</span></div>
                <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">MBTI 推断：<code>${escapeHtml(owner.mbtiEstimate || "-")}</code> · 组织：<code>${escapeHtml(owner.organizationHint || "-")}</code></div>
              </div>
              <button class="sm primary" onclick="activateDigitalTwin()">使用分身生成草稿</button>
            </div>
            <div style="margin-top:8px; font-size:12.5px; color:var(--text-secondary);">
              <strong>说话习惯：</strong>${escapeHtml(sp.toneTag || "-")} · 均长 <strong>${escapeHtml(String(sp.avgSentenceLength ?? "-"))}</strong> 字 · ${escapeHtml(sp.punctuationHabits || "-")}
            </div>
            <ul style="margin:8px 0 0 18px; padding:0; font-size:12.5px; color:var(--text-secondary);">${traits}</ul>
            <div class="chip-row" style="margin-top:8px;">${oMems}</div>
          </div>
          <div>${matrix}</div>
        `;
      }

      const contacts = soul.contactProfiles || [];
      const badge = document.getElementById("soulContactsBadge");
      if (badge) {
        badge.textContent = `已建立 ${contacts.length} 份好友心智 & 记忆图谱`;
      }
      const grid = document.getElementById("friendSoulsGrid");
      if (grid) {
        grid.innerHTML = contacts.map((c) => {
          const mems = c.memories || {};
          const factTags = (mems.facts || []).slice(0, 4).map((m) => `<span class="pill accent">📌 ${escapeHtml(m.content)}</span>`).join("");
          const sharedTags = (mems.sharedContext || []).slice(0, 4).map((m) => `<span class="pill ok">💬 ${escapeHtml(m.content)}</span>`).join("");
          const evtRows = (mems.episodicEvents || []).slice(0, 4).map((e) => `
            <div style="font-size:12px; color:var(--text-secondary); padding:4px 0; border-bottom:1px dashed var(--border);">
              <code style="font-size:11px;">${escapeHtml(e.timeMarker || "近期")}</code> ${escapeHtml(e.content)}
            </div>
          `).join("");
          return `
            <div class="panel-card" style="margin-bottom:0;">
              <div class="section-header" style="margin-bottom:8px;">
                <div>
                  <h3 class="section-title" style="font-size:15px;">${escapeHtml(c.matchedTitle)} <span class="chip">${escapeHtml(c.careLevelLabel || "普通")}</span></h3>
                  <div class="section-desc">${escapeHtml(c.personalityTag)} · <code>${escapeHtml(c.mbtiEstimate)}</code> · 默契分 <strong>${escapeHtml(String(c.rapportScore || 0))}</strong></div>
                </div>
                <button class="sm" onclick="activateDigitalTwin('${encArg(c.target)}')">🎭 分身试聊</button>
              </div>
              <div style="font-size:12.5px; color:var(--text-secondary); margin-bottom:6px;">${escapeHtml(c.psychologicalSummary || "")}</div>
              <div style="font-size:12px; color:var(--text-muted); margin-bottom:6px;"><strong>偏好：</strong>${escapeHtml(c.communicationPreferences || "")}</div>
              <div style="font-size:12px; color:var(--danger); margin-bottom:8px;"><strong>边界：</strong>${escapeHtml(c.taboosAndBoundaries || "")}</div>
              <div class="chip-row" style="margin-bottom:8px;">${factTags}${sharedTags}</div>
              <div>${evtRows || '<div style="font-size:12px; color:var(--text-muted);">暂无时间戳事件记录</div>'}</div>
            </div>
          `;
        }).join("");
      }

      const bench = STATE?.benchmarkSummary || {};
      const bSummaryBox = document.getElementById("benchmarkSummaryBox");
      if (bSummaryBox) {
        bSummaryBox.innerHTML = `
          <div class="field-box" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>
              <div style="font-size:16px; font-weight:700;">综合评分：<span style="color:var(--primary);">${escapeHtml(String(bench.overallScore ?? "--"))} / 100</span> · 通过模块 ${escapeHtml(String(bench.passedModules ?? 0))}/${escapeHtml(String(bench.totalModules ?? 0))}</div>
              <div style="font-size:12px; color:var(--text-muted);">最近评测：${escapeHtml(bench.generatedAt || "-")} · 总耗时 ${escapeHtml(String(bench.totalElapsedMs ?? "-"))} ms</div>
            </div>
            <span class="pill ${bench.ok ? "ok" : "warn"}">${bench.ok ? "✅ 全部模块通过（含 Kimi 验收）" : "⏳ 待补齐/待验收"}</span>
          </div>
        `;
      }
      const bList = document.getElementById("benchmarkModulesList");
      if (bList) {
        bList.innerHTML = (bench.benchmarks || []).map((b) => `
          <div class="event-item">
            <div class="event-top">
              <strong>${escapeHtml(b.name)}</strong>
              <span class="pill ${b.passed ? "ok" : "warn"}">${b.passed ? "✅ PASS" : "⚠️ PENDING"} · ${escapeHtml(String(b.score))}分 · ${escapeHtml(String(b.latencyMs))}ms</span>
            </div>
            <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">${escapeHtml(b.summary || "")}</div>
          </div>
        `).join("");
      }

      const kimi = bench.kimiAcceptance || STATE?.kimiDiscussion || {};
      const kimiBox = document.getElementById("kimiAcceptanceBox");
      if (kimiBox) {
        if (kimi && kimi.verdict) {
          const recs = (kimi.recommendations || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
          const chkRows = (kimi.checks || []).map((ck) => `<li><code>${escapeHtml(ck.item)}</code>: <strong>${escapeHtml(ck.status)}</strong> — ${escapeHtml(ck.detail)}</li>`).join("");
          kimiBox.innerHTML = `
            <div class="field-box">
              <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:6px;">
                <strong>模型：<code>${escapeHtml(kimi.modelRequested || "kimi")}</code> · 回执：<code>${escapeHtml(kimi.receiptStatus || "-")}</code></strong>
                <span class="pill ${String(kimi.verdict).toLowerCase() === "pass" ? "ok" : "warn"}">验收结论：${escapeHtml(String(kimi.verdict).toUpperCase())} (${escapeHtml(String(kimi.score ?? "-"))}分)</span>
              </div>
              <div style="font-size:12.5px; color:var(--text-secondary); margin-bottom:6px;">${escapeHtml(kimi.summary || "")}</div>
              ${chkRows ? `<ul style="margin:4px 0 6px 18px; padding:0; font-size:12px;">${chkRows}</ul>` : ""}
              ${recs ? `<div style="font-size:12px; font-weight:600; margin-top:4px;">Kimi 改进建议 & 已落实状态：</div><ul style="margin:4px 0 0 18px; padding:0; font-size:12px;">${recs}</ul>` : ""}
            </div>
          `;
        } else {
          kimiBox.innerHTML = `<div class="field-box" style="font-size:12.5px; color:var(--text-muted);">Kimi (codexma) 独立验收报告待写入，完成 codexma Kimi 验证后将在此展示完整实测回执与意见。</div>`;
        }
      }
    }

    async function rebuildSoulProfiles(useLlm) {
      showToast(useLlm ? "正在用 Magpie 大模型深度提炼本我性格与好友记忆..." : "正在重新扫描本地聊天记录与 WeChatBridge 归档...");
      const { data } = await apiJson("/api/soul-profiles/rebuild", {
        method: "POST",
        body: JSON.stringify({ useLlm: !!useLlm }),
      });
      if (STATE) STATE.soulSummary = data;
      renderSoulAndBenchmarkTab();
      showToast(`已构建本我画像 + ${data.totalContactsAnalyzed || 0} 位好友长期记忆`);
    }

    async function addSoulMemoryItem() {
      const target = (document.getElementById("memTargetInput").value || "").trim();
      const category = document.getElementById("memCategoryInput").value || "fact";
      const content = (document.getElementById("memContentInput").value || "").trim();
      if (!target || !content) {
        showToast("请填写目标好友与记忆内容");
        return;
      }
      await apiJson("/api/memory-add", {
        method: "POST",
        body: JSON.stringify({ target, category, content }),
      });
      document.getElementById("memContentInput").value = "";
      showToast(`已写入「${target}」的长期记忆并刷新画像`);
      await loadOverview();
      switchTab("soul");
    }

    async function activateDigitalTwin(encodedTarget) {
      const target = encodedTarget ? decodeURIComponent(encodedTarget) :
        document.getElementById("previewTarget").value.trim();
      if (!target) {
        switchTab("monitor");
        setDraftStatus("请先选择要回复的会话。", "error");
        document.getElementById("previewTarget").focus();
        return;
      }
      switchTab("monitor");
      document.getElementById("previewTarget").value = target;
      syncChatRecipient(target);
      document.getElementById("previewPersona").value = "owner-digital-twin";
      await runReplyPreview();
    }

    async function runBenchmarkSuite(includeTests) {
      showToast(includeTests ? "正在运行全量 Benchmark 与单元测试套件..." : "正在运行 8 模块 Benchmark...");
      const { data } = await apiJson("/api/benchmark/run", {
        method: "POST",
        body: JSON.stringify({ includeTests: !!includeTests }),
      });
      if (STATE) STATE.benchmarkSummary = data;
      renderSoulAndBenchmarkTab();
      showToast(`Benchmark 完成：综合得分 ${data.overallScore}/100 (${data.passedModules}/${data.totalModules} 通过)`);
    }

    function renderVisionAndAgentPanel() {
      const vs = STATE?.visionStack || {};
      const l1 = vs.layer1MonitorVision || {};
      const l2 = vs.layer2MultimodalLLM || {};
      const dock = STATE?.sidebarDockStatus || {};
      const tasksObj = STATE?.agentTasks || {};
      const analysesObj = STATE?.mediaAnalyses || {};
      const tasks = tasksObj.tasks || [];
      const analyses = analysesObj.analyses || [];

      const l1El = document.getElementById("vStackLayer1");
      if (l1El) l1El.textContent = l1.engine ? "Apple Vision 2x OCR (0 Token)" : "Apple Vision 2x OCR";
      const l2El = document.getElementById("vStackLayer2");
      if (l2El) {
        const stLabel = l2.gatewayOnline ? "在线" : "离线回退";
        l2El.textContent = `${l2.defaultVisionModelId || "auto/deepseek-v4.1-flash"} (${stLabel})`;
      }
      const dockEl = document.getElementById("vStackDock");
      if (dockEl) {
        const plan = dock.calculatedDockPlan || {};
        dockEl.textContent = dock.wechatFound
          ? `已就绪 · Win#${dock.wechatWindowId ?? "-"} (${plan.side || "dock"})`
          : "未检测到活跃微信窗";
      }
      const cntEl = document.getElementById("vStackCounts");
      if (cntEl) cntEl.textContent = `${tasks.length} 次派活 / ${analyses.length} 条深读`;

      const bindings = STATE?.bindings?.bindings || [];
      const boundAgentsBox = document.getElementById("boundAgentsList");
      if (boundAgentsBox) {
        const bound = bindings.filter((b) => b.boundAgentId || b.visionModelId);
        boundAgentsBox.innerHTML = bound.length
          ? bound.map((b) => `<span class="pill accent">🤖 ${escapeHtml(b.target)} → ${escapeHtml(b.boundAgentName || b.boundAgentId || "Agent")} (${escapeHtml(b.visionModelId || "auto/deepseek-v4.1-flash")})</span>`).join("")
          : `<span style="font-size:12px; color:var(--text-muted);">暂未绑定智能体，可为指定会话配置。</span>`;
      }

      const receiptsBox = document.getElementById("agentDispatchReceiptsBox");
      if (receiptsBox) {
        receiptsBox.innerHTML = tasks.length
          ? tasks.slice(0, 8).map((t) => {
              const ex = t.agentExecution || {};
              const agentTxt = ex.planAndResponse || "";
              const cats = (t.tasks || []).map((x) => x.category).filter(Boolean).slice(0, 4);
              return `
                <div class="event-item">
                  <div class="event-head">
                    <div><span class="pill ok">🤖 ${escapeHtml(t.contact || "")}</span> <strong>${escapeHtml(t.binding?.boundAgentName || t.binding?.boundAgentId || "Agent")}</strong></div>
                    <span style="font-size:11px; color:var(--text-muted);">${t.tasksCount ?? 0} 指令 · ${t.mediaAnalysesCount ?? 0} 媒体</span>
                  </div>
                  <div class="chip-row" style="margin:4px 0;">${cats.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("")}</div>
                  ${agentTxt ? `<div style="font-size:12px; color:var(--text-secondary); white-space:pre-wrap;">${escapeHtml(agentTxt.slice(0, 260))}${agentTxt.length > 260 ? "..." : ""}</div>` : ""}
                </div>
              `;
            }).join("")
          : `<div style="padding:14px; color:var(--text-muted); font-size:12.5px;">暂无指令派活记录，点击「🚀 派发」立即解析好友消息与链接。</div>`;
      }

      const analysesBox = document.getElementById("mediaAnalysesList");
      if (analysesBox) {
        analysesBox.innerHTML = analyses.length
          ? analyses.slice(0, 8).map((a) => `
              <div class="event-item">
                <div class="event-head">
                  <div><span class="pill ${a.ok ? "ok" : "warn"}">${escapeHtml(a.kind || "media")}</span> <strong>${escapeHtml(a.title || a.url || "-")}</strong></div>
                  <span style="font-size:11px; color:var(--text-muted);">OCR ${a.ocrCount ?? 0} 行</span>
                </div>
                <div style="font-size:12px; color:var(--text-secondary);">${escapeHtml((a.summary || a.ocrText || "").slice(0, 220))}</div>
              </div>
            `).join("")
          : `<div style="padding:14px; color:var(--text-muted); font-size:12.5px;">暂无多模态深读记录，可在右侧直接解析 URL / 图片 / 视频。</div>`;
      }
    }

    async function triggerDockSidebar(mode) {
      showToast(mode === "tile" ? "正在将 WeChat Bot 与微信窗口左右并排分屏..." : "正在把 WeChat Bot 固定到微信窗口侧栏...");
      try {
        const { data } = await apiJson("/api/dock-sidebar", {
          method: "POST",
          body: JSON.stringify({ mode: mode || "dock" }),
        });
        if (STATE) STATE.sidebarDockStatus = data;
        renderVisionAndAgentPanel();
        const plan = data.calculatedDockPlan || {};
        showToast(data.ok ? `已吸附至微信 ${plan.side || "sidebar"}` : `侧栏操作提示: ${data.error || "请先打开微信主窗口"}`);
      } catch (err) {
        showToast("侧栏吸附失败: " + err.message);
      }
    }

    async function bindFriendAgent() {
      const target = (document.getElementById("agentBindTarget")?.value || "").trim();
      if (!target) { showToast("请输入目标好友或群名"); return; }
      const payload = {
        target,
        boundAgentId: (document.getElementById("agentBindId")?.value || "bot_wechat_ecosystem").trim(),
        boundAgentName: (document.getElementById("agentBindName")?.value || "WeChat Bot 全生态智能体").trim(),
        boundAgentType: document.getElementById("agentBindType")?.value || "botstudio",
        visionModelId: (document.getElementById("agentBindVisionModel")?.value || "auto/deepseek-v4.1-flash").trim(),
        autoDispatchInstructions: !!document.getElementById("agentAutoDispatch")?.checked,
        autoAnalyzeLinksAndMedia: !!document.getElementById("agentAutoAnalyzeMedia")?.checked,
      };
      try {
        await apiJson("/api/bind-agent", { method: "POST", body: JSON.stringify(payload) });
        showToast(`已将「${payload.boundAgentName}」绑定到「${target}」`);
        await loadOverview();
      } catch (err) {
        showToast("绑定智能体失败: " + err.message);
      }
    }

    async function runMediaDeepRead(fromViewer) {
      const kind = fromViewer ? "image" : (document.getElementById("mediaKindSelect")?.value || "link");
      const contact = (document.getElementById("mediaContactInput")?.value || "").trim();
      const rawInput = (document.getElementById("mediaUrlOrPathInput")?.value || "").trim();
      const contextText = (document.getElementById("mediaContextInput")?.value || "").trim();
      const modelId = (document.getElementById("agentBindVisionModel")?.value || "auto/deepseek-v4.1-flash").trim();
      const payload = { kind, contact, contextText, modelId, fromViewerWindow: !!fromViewer };
      if (!fromViewer) {
        if (kind === "link") payload.url = rawInput;
        else if (kind === "image") payload.imagePath = rawInput;
        else if (kind === "video") {
          if (rawInput.startsWith("http")) payload.videoUrl = rawInput;
          else payload.videoPath = rawInput;
        }
      }
      showToast(fromViewer ? "正在抓取微信“图片和视频”窗并执行 2x OCR + DeepSeek Flash 分析..." : "正在执行多模态深读...");
      try {
        const { data } = await apiJson("/api/analyze-media", { method: "POST", body: JSON.stringify(payload) });
        const box = document.getElementById("mediaAnalysisPreviewBox");
        if (box) {
          box.innerHTML = `<div class="field-box" style="margin-top:6px;"><strong>${escapeHtml(data.title || data.kind || "分析完成")}</strong><div>${escapeHtml(data.summary || data.ocrText || "")}</div>${data.recommendedReply ? `<div style="margin-top:4px; color:var(--primary);">建议回复：${escapeHtml(data.recommendedReply)}</div>` : ""}</div>`;
        }
        showToast(data.ok ? "多模态深读完成" : ("分析提示: " + (data.error || "部分完成")));
        await loadOverview();
      } catch (err) {
        showToast("多模态深读失败: " + err.message);
      }
    }

    async function runWeChatAiAssist(mode) {
      const target = (
        document.getElementById("mediaContactInput")?.value ||
        document.getElementById("previewTarget")?.value ||
        ""
      ).trim();
      const rawUrl = (document.getElementById("mediaUrlOrPathInput")?.value || "").trim();
      const ctx = (document.getElementById("mediaContextInput")?.value || "").trim();
      const previewInc = typeof extractLatestPeerMessage === "function"
        ? extractLatestPeerMessage((document.getElementById("previewIncoming")?.value || "").trim())
        : (document.getElementById("previewIncoming")?.value || "").trim();
      const contentHint = [rawUrl, ctx].filter(Boolean).join(" ").trim() || previewInc;
      const modelId = (document.getElementById("agentBindVisionModel")?.value || "auto/deepseek-v4.1-flash").trim();
      const dryRun = !target;
      showToast(mode === "relay_xiaowei" ? "正在转发给微信小微/元宝解析链接与视频..." : "正在在会话中调用 @元宝 解析文章/视频...");
      try {
        const { data } = await apiJson("/api/wechat-ai-assist", {
          method: "POST",
          body: JSON.stringify({ target, contentHint, mode, modelId, dryRun }),
        });
        const box = document.getElementById("mediaAnalysisPreviewBox");
        if (box) {
          const badge = data.mode === "relay_xiaowei" ? "小微/元宝转发现场解析" : "@元宝 群内协同解析";
          box.innerHTML = `<div class="field-box" style="margin-top:6px;"><strong>${escapeHtml(badge)} · ${escapeHtml(data.assistant || "元宝")}</strong><div style="font-size:11.5px; color:var(--text-muted); margin:3px 0;">指令：${escapeHtml(data.promptText || "")}</div><div>${escapeHtml(data.summary || data.note || "")}</div>${data.recommendedReply ? `<div style="margin-top:4px; color:var(--primary);">建议回复：${escapeHtml(data.recommendedReply)}</div>` : ""}</div>`;
        }
        showToast(data.ok ? `${data.assistant || "微信助手"} 解析已写入记忆` : ("解析提示: " + (data.error || "部分完成")));
        await loadOverview();
      } catch (err) {
        showToast("微信助手协同解析失败: " + err.message);
      }
    }

    async function runQuickWeChatAiAssist(mode) {
      const target = (document.getElementById("previewTarget")?.value || "").trim();
      const previewInc = typeof extractLatestPeerMessage === "function"
        ? extractLatestPeerMessage((document.getElementById("previewIncoming")?.value || "").trim())
        : (document.getElementById("previewIncoming")?.value || "").trim();
      const pasteInc = (document.getElementById("pasteIncoming")?.value || "").trim();
      const contentHint = previewInc || pasteInc;
      const modelId = (document.getElementById("previewModelSelect")?.value || "auto/deepseek-v4.1-flash").trim();
      const dryRun = !target;
      const outEl = document.getElementById("quickAiAssistResult");
      if (outEl) {
        outEl.hidden = false;
        outEl.innerHTML = `<span style="color:var(--text-muted);">正在调用 ${mode === "relay_xiaowei" ? "小微/元宝转发解析" : "@元宝 群内/会话解析"}…</span>`;
      }
      try {
        const { data } = await apiJson("/api/wechat-ai-assist", {
          method: "POST",
          body: JSON.stringify({ target, contentHint, mode, modelId, dryRun }),
        });
        if (outEl) {
          const tag = data.mode === "relay_xiaowei" ? "小微/元宝转发" : "@元宝";
          outEl.hidden = false;
          outEl.innerHTML = `<strong>${escapeHtml(tag)} 已解析</strong> · ${escapeHtml(data.summary || data.note || "")}`;
        }
        showToast(data.ok ? `${data.assistant || "微信助手"} 解析已写入记忆，正在生成回复草稿…` : "解析已尝试，继续生成草稿");
        if (target && contentHint) {
          await runReplyPreview();
        }
      } catch (err) {
        if (outEl) {
          outEl.hidden = false;
          outEl.textContent = "解析提示: " + (err.message || err);
        }
        showToast("微信助手协同失败: " + (err.message || err));
      }
    }

    function syncSettingsModalFromState() {
      const pSrc = document.getElementById("previewPersona");
      const pDst = document.getElementById("cfgPersonaSelect");
      if (pSrc && pDst) {
        pDst.innerHTML = pSrc.innerHTML;
        pDst.value = pSrc.value;
      }
      const mSrc = document.getElementById("previewModelSelect");
      const mDst = document.getElementById("cfgModelSelect");
      if (mSrc && mDst) {
        mDst.innerHTML = mSrc.innerHTML;
        mDst.value = mSrc.value;
      }
      const sSrc = document.getElementById("sendMode");
      const sDst = document.getElementById("cfgSendModeSelect");
      if (sSrc && sDst) sDst.value = sSrc.value;
      const uSrc = document.getElementById("previewUseLlm");
      const uDst = document.getElementById("cfgUseLlmCheckbox");
      if (uSrc && uDst) uDst.checked = !!uSrc.checked;

      const gw = STATE?.llmGateway || {};
      const gwBox = document.getElementById("cfgGatewayStatusBox");
      if (gwBox) {
        const activeM = STATE?.models?.activeModelId || "-";
        gwBox.innerHTML = `当前默认模型：<code>${escapeHtml(activeM)}</code> · 网关：${gw.reachable ? "🟢 在线" : "🔴 不可达"} (${escapeHtml(gw.gatewayUrl || "http://127.0.0.1:3425")})`;
      }
      const hg = STATE?.humanGuard || {};
      const ge = document.getElementById("cfgGuardEnabled");
      const gc = document.getElementById("cfgGuardCooldown");
      const gi = document.getElementById("cfgGuardIdle");
      if (ge && typeof hg.enabled === "boolean") ge.checked = hg.enabled;
      if (gc && hg.cooldownSeconds !== undefined) gc.value = hg.cooldownSeconds;
      if (gi && hg.idleResumeSeconds !== undefined) gi.value = hg.idleResumeSeconds;
    }

    function switchSettingsSection(section) {
      const targetSec = section || "reply";
      document.querySelectorAll(".settings-nav-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.settingsSec === targetSec);
      });
      document.querySelectorAll(".settings-section").forEach((s) => {
        s.classList.toggle("active", s.dataset.settingsPanel === targetSec);
      });
    }

    const WORKOS_STATE = {
      speedMode: "fast",
      postPreset: "private_ops",
      taskGoal: "接待咨询，回答产品与技术问题，收集客户需求并沉淀常见问答 SOP",
      harness: null,
      lastEscAt: 0,
    };

    const WINDOW_BIND_STATE = {
      apps: [],
      windows: [],
      boundWindow: { appId: "auto", appLabel: "自动跟随", windowID: null, windowTitle: "", followUpIsolation: true },
      loading: false,
      lastClosedAt: 0,
    };

    const DOC_INGEST_STATE = {
      fileUpload: null,
      preview: null,
      items: [],
      strategy: "bind_kb",
      docName: "",
      busy: false,
      lastClosedAt: 0,
    };

    const MULTI_WIN_STATE = {
      scheduler: null,
      lastRun: null,
      borderOverlay: {
        enabled: false,
        state: "idle",
        modeColorState: "idle",
        color: "#10B981",
        activeWindows: [],
        activePopoutWindowIDs: [],
      },
      busy: false,
    };

    function _renderWorkosControls(harness) {
      if (!harness) return;
      WORKOS_STATE.harness = harness;
      const gov = harness.governance || {};
      WORKOS_STATE.speedMode = gov.speedMode || "fast";
      WORKOS_STATE.postPreset = gov.postPreset || "private_ops";
      if (gov.taskGoal) WORKOS_STATE.taskGoal = gov.taskGoal;
      if (gov.boundWindow && typeof gov.boundWindow === "object") {
        WINDOW_BIND_STATE.boundWindow = gov.boundWindow;
        renderBoundWindowButton();
      }
      if (harness.scheduler && typeof harness.scheduler === "object") {
        MULTI_WIN_STATE.scheduler = harness.scheduler;
      }
      if (harness.borderOverlay && typeof harness.borderOverlay === "object") {
        MULTI_WIN_STATE.borderOverlay = harness.borderOverlay;
      }
      renderMultiWindowSchedulerState();

      const sBtn = document.getElementById("speedModeBtn");
      if (sBtn) {
        const isDeep = WORKOS_STATE.speedMode === "deep";
        sBtn.textContent = isDeep ? "🔬 深思" : "⚡ 极速";
        sBtn.style.borderColor = isDeep ? "var(--work-pine)" : "";
        sBtn.style.color = isDeep ? "var(--work-pine)" : "";
      }
      document.querySelectorAll(".workos-preset-btn").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.workosPreset === WORKOS_STATE.postPreset);
      });
      const goalInput = document.getElementById("workosGoalInput");
      if (goalInput && document.activeElement !== goalInput && gov.taskGoal) {
        goalInput.value = gov.taskGoal;
      }

      const govBox = document.getElementById("workosGovBox");
      if (govBox) {
        const targets = (gov.allowedTargets || []).join("、") || "未设置";
        const hgActive = gov.humanGuard?.enabled ? "已启用让路" : "已关闭";
        const winLabel = formatBoundWindowLabel(gov.boundWindow || WINDOW_BIND_STATE.boundWindow);
        govBox.innerHTML = `<div>允许联系人：<b>${escapeHtml(targets)}</b></div><div>防抢鼠标：${escapeHtml(hgActive)} · 当前档位：<b>${WORKOS_STATE.speedMode === "deep" ? "🔬 深思" : "⚡ 极速"}</b></div><div>岗位：${escapeHtml(gov.postLabel || "私域运营专员")} · 窗口：<b>${escapeHtml(winLabel)}</b></div>`;
      }
      const evalBox = document.getElementById("workosEvalBox");
      if (evalBox) {
        const ev = harness.evaluation || {};
        const b = ev.benchmark || {};
        const benchLine = b.totalCases ? `基准评测：${b.passed}/${b.totalCases}（术语泄漏 ${b.jargonLeaks ?? 0} 条）` : "基准评测：暂无离线报告";
        evalBox.innerHTML = `<div>知识库总条目：<b>${ev.knowledgeEntriesCount ?? 0}</b> 条</div><div>自学习沉淀 SOP：<b>${ev.selfLearnedCount ?? 0}</b> 条 · 文档入库：<b>${ev.docIngestedCount ?? 0}</b> 条</div><div>${escapeHtml(benchLine)}</div>`;
      }
      const refBox = document.getElementById("workosReflectBox");
      if (refBox) {
        const items = harness.reflection?.items || [];
        if (!items.length) {
          refBox.innerHTML = `<div style="color:var(--text-muted);">暂未发现未命中知识库的盲区来信。</div>`;
        } else {
          refBox.innerHTML = `<ul class="workos-list">${items.slice(0, 6).map((it, idx) => `<li><b>[${escapeHtml(it.target)}]</b> ${escapeHtml(it.incomingText)} <button type="button" class="link-btn" style="font-size:11px;" onclick="fillFromReflection(${idx})">填入草稿</button></li>`).join("")}</ul>`;
        }
      }
      const evoBox = document.getElementById("workosEvolveBox");
      if (evoBox) {
        const coev = harness.coevolution || {};
        const vlse = coev.vlseBotLayer || {};
        const rpa = coev.wechatRpaLayer || {};
        const mm = rpa.multimodalByKind || {};
        const coevBanner = `<div style="margin-bottom:6px; padding:6px 8px; border-radius:6px; background:var(--panel-soft, rgba(16,185,129,0.08)); border:1px solid rgba(16,185,129,0.2);">` +
          `<div><b>🧬 双产品共进化</b> · VLSE Bot 真人度 <b>${vlse.avgHumanLikenessScore ?? 0}</b> · 知识沉淀 <b>${vlse.distilledKnowledgeCount ?? 0}</b> 条 · 规则 <b>${vlse.evolvedRulesCount ?? 0}</b> 条</div>` +
          `<div><b>🤖 WeChatBot RPA 训练</b> · 零切窗率 <b>${rpa.zeroSwitchRate ?? 0}%</b> · 多模态深读 <b>${rpa.multimodalDeepReadTotal ?? 0}</b> 次 (链${mm.link ?? 0}/图${mm.image ?? 0}/视${(mm.video ?? 0) + (mm.channels_video ?? 0)}/文${mm.wechat_article ?? 0})</div>` +
          `</div>`;
        const items = harness.evolution?.items || [];
        if (!items.length) {
          evoBox.innerHTML = coevBanner + `<div style="color:var(--text-muted);">修改回复草稿后点击底部「✨ 纠偏沉淀 SOP」或保持双Bot对聊即可持续进化。</div>`;
        } else {
          evoBox.innerHTML = coevBanner + `<ul class="workos-list">${items.slice(0, 6).map((it) => `<li><b>${escapeHtml(it.title)}</b> → ${escapeHtml(it.correctedReply)}</li>`).join("")}</ul>`;
        }
      }
      const mCode = document.getElementById("mobileRemoteUrlCode");
      if (mCode) mCode.textContent = `${location.origin}/mobile`;
    }

    async function loadWorkosHarness(notify = false) {
      try {
        const { status, data } = await apiJson("/api/workos/harness");
        if (status === 200 && data.ok) {
          _renderWorkosControls(data);
          if (notify) showToast("已刷新 WorkOS 四维闭环指标");
        }
      } catch (err) {
        if (notify) showToast("刷新 WorkOS 指标失败: " + err.message);
      }
    }

    async function toggleWorkosSpeedMode() {
      const next = WORKOS_STATE.speedMode === "deep" ? "fast" : "deep";
      try {
        const { status, data } = await apiJson("/api/workos/goal", {
          method: "POST",
          body: JSON.stringify({ speed_mode: next }),
        });
        if (status === 200 && data.ok) {
          showToast(next === "deep" ? "🔬 已切换至「深思」深度推理模式" : "⚡ 已切换至「极速」低延迟模式");
          await loadWorkosHarness(false);
        }
      } catch (err) {
        showToast("切换推理档位失败: " + err.message);
      }
    }

    async function selectWorkosPreset(presetKey) {
      try {
        const { status, data } = await apiJson("/api/workos/goal", {
          method: "POST",
          body: JSON.stringify({ post_preset: presetKey }),
        });
        if (status === 200 && data.ok) {
          const goalInput = document.getElementById("workosGoalInput");
          if (goalInput && data.taskGoal) goalInput.value = data.taskGoal;
          showToast(`🎯 已切换岗位目标：${data.postLabel || presetKey}`);
          await loadWorkosHarness(false);
        }
      } catch (err) {
        showToast("切换岗位模板失败: " + err.message);
      }
    }

    async function saveWorkosGoal() {
      const goal = (document.getElementById("workosGoalInput")?.value || "").trim();
      if (!goal) { showToast("请填写一句 AI 员工任务目标"); return; }
      try {
        const { status, data } = await apiJson("/api/workos/goal", {
          method: "POST",
          body: JSON.stringify({ task_goal: goal }),
        });
        if (status === 200 && data.ok) {
          showToast("🎯 已更新 AI 员工任务目标");
          await loadWorkosHarness(false);
        }
      } catch (err) {
        showToast("保存目标失败: " + err.message);
      }
    }

    function fillFromReflection(index) {
      const items = WORKOS_STATE.harness?.reflection?.items || [];
      const item = items[index];
      if (!item) return;
      hideSettingsModal();
      syncChatRecipient(item.target || "");
      const pt = document.getElementById("previewTarget");
      if (pt) pt.value = item.target || "";
      const pi = document.getElementById("previewIncoming");
      const paste = document.getElementById("pasteIncoming");
      if (pi) pi.value = item.incomingText || "";
      if (paste) paste.value = item.incomingText || "";
      const st = document.getElementById("sendText");
      if (st) {
        st.value = item.replyText || "";
        st.focus();
      }
      showToast("已填入待优化来信与参考回复，修改后点「✨ 纠偏沉淀 SOP」即可入库");
    }

    async function learnFromDraftCorrection() {
      const target = (document.getElementById("previewTarget")?.value || document.getElementById("sendTarget")?.value || "").trim();
      const prevEl = document.getElementById("replyPreviewResult");
      const rawIn = extractLatestPeerMessage((document.getElementById("previewIncoming")?.value || prevEl?.dataset.lastIncoming || "").trim());
      const corrected = (document.getElementById("sendText")?.value || "").trim();
      const originalDraft = prevEl?.dataset.lastOriginalDraft || "";
      if (!rawIn) {
        showToast("请先选择或粘贴客户来信原话");
        return;
      }
      if (!corrected) {
        showToast("请先填写或修改定稿回复后再沉淀 SOP");
        document.getElementById("sendText")?.focus();
        return;
      }
      const btn = document.getElementById("learnCorrectionBtn");
      if (btn) btn.disabled = true;
      try {
        const { status, data } = await apiJson("/api/workos/learn-correction", {
          method: "POST",
          body: JSON.stringify({
            target,
            incoming_text: rawIn,
            corrected_reply: corrected,
            original_draft: originalDraft,
            kind: "script",
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "沉淀失败");
        showToast(`✨ 已沉淀 SOP《${data.entry?.title || ""}》，后续同类咨询自动命中`);
        setDraftStatus("已沉淀进知识库 SOP（自学习 +1）。");
        await loadWorkosHarness(false);
        await loadOverview(false);
      } catch (err) {
        showToast("纠偏沉淀失败: " + err.message);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function openMobileRemoteOverlay() {
      const frame = document.getElementById("mobileRemoteFrame");
      if (frame) frame.src = "/mobile?embed=1&ts=" + Date.now();
      document.getElementById("mobileRemoteOverlay")?.classList.add("visible");
    }

    function hideMobileRemoteOverlay() {
      document.getElementById("mobileRemoteOverlay")?.classList.remove("visible");
    }

    function openSettingsModal(section = "reply") {
      syncSettingsModalFromState();
      switchSettingsSection(section);
      renderMultiWindowSchedulerState();
      loadWorkosHarness(false);
      document.getElementById("settingsOverlay")?.classList.add("visible");
    }

    function hideSettingsModal() {
      document.getElementById("settingsOverlay")?.classList.remove("visible");
    }

    function supportsPopoverApi() {
      return typeof HTMLElement !== "undefined" && Object.hasOwn(HTMLElement.prototype, "popover");
    }

    function isWindowPickerOpen() {
      const pop = document.getElementById("windowPickerPopover");
      if (!pop) return false;
      if (supportsPopoverApi()) {
        try { return pop.matches(":popover-open"); } catch (e) {}
      }
      return pop.classList.contains("open");
    }

    function positionWindowPickerPopover() {
      const btn = document.getElementById("appWindowPickerBtn");
      const pop = document.getElementById("windowPickerPopover");
      if (!btn || !pop) return;
      if (typeof CSS !== "undefined" && CSS.supports && CSS.supports("position-area: block-end")) {
        pop.style.top = "";
        pop.style.left = "";
        return;
      }
      const rect = btn.getBoundingClientRect();
      const popWidth = Math.min(472, window.innerWidth - 24);
      const popHeight = Math.min(560, pop.offsetHeight || 420);
      const spaceBelow = window.innerHeight - rect.bottom - 12;
      const spaceAbove = rect.top - 12;
      let top = rect.bottom + 6;
      if (spaceBelow < 220 && spaceAbove > spaceBelow) {
        top = Math.max(8, rect.top - Math.min(popHeight, spaceAbove) - 6);
      } else {
        top = Math.min(top, Math.max(8, window.innerHeight - Math.min(popHeight, 260) - 8));
      }
      let left = rect.right - popWidth;
      if (left < 12) left = Math.max(12, rect.left);
      if (left + popWidth > window.innerWidth - 12) {
        left = Math.max(12, window.innerWidth - popWidth - 12);
      }
      pop.style.top = `${Math.round(top)}px`;
      pop.style.left = `${Math.round(left)}px`;
    }

    function formatBoundWindowLabel(bound) {
      const b = bound || {};
      const appId = String(b.appId || "auto").toLowerCase();
      const wid = b.windowID;
      const title = String(b.windowTitle || "").trim();
      if (appId === "auto" && !wid && !title) {
        return "🪟 窗口: 自动";
      }
      const appShort = appId === "wecom" ? "企业微信" : (appId === "wechat" ? "微信" : (b.appLabel || "自动"));
      if (title) {
        if (title === appShort || ["微信", "WeChat", "企业微信", "WeCom"].includes(title)) {
          return `🪟 ${appShort}主窗`;
        }
        return `🪟 ${appShort} · ${title}`;
      }
      if (wid) return `🪟 ${appShort} #${wid}`;
      return `🪟 ${appShort}主窗`;
    }

    function renderBoundWindowButton() {
      const btn = document.getElementById("appWindowPickerBtn");
      if (!btn) return;
      const b = WINDOW_BIND_STATE.boundWindow || {};
      const label = formatBoundWindowLabel(b);
      const isBound = (String(b.appId || "auto") !== "auto") || Boolean(b.windowID);
      btn.textContent = label;
      btn.classList.toggle("is-bound", isBound);
      btn.title = isBound
        ? `当前已绑定目标窗口：${label}${b.windowID ? " (#" + b.windowID + ")" : ""} · 点击切换微信 / 企业微信窗口`
        : "选择并绑定微信或企业微信窗口（支持独立聊天小窗免切换直连）";
    }

    function _isWindowAllowlisted(win) {
      if (typeof win?.isAllowlistedTarget === "boolean") return win.isAllowlistedTarget;
      const rawTitle = String(win?.title || "").trim().toLowerCase();
      if (!rawTitle) return false;
      const allowed = WORKOS_STATE?.harness?.governance?.allowedTargets || ["安晓心", "心安", "openbot"];
      return allowed.some((t) => {
        const clean = String(t || "").trim().toLowerCase();
        return clean && (rawTitle === clean || rawTitle.includes(clean));
      });
    }

    function _isWindowActiveBinding(win) {
      const b = WINDOW_BIND_STATE.boundWindow || {};
      if (b.windowID && win.windowID) return Number(b.windowID) === Number(win.windowID);
      if (b.appId && b.appId !== "auto" && b.appId === win.appId && !b.windowID) {
        return Boolean(win.isMainWindow);
      }
      return false;
    }

    function renderAppWindowPickerList() {
      const appsBox = document.getElementById("windowPickerAppsSummary");
      const bodyBox = document.getElementById("windowPickerBody");
      if (!appsBox || !bodyBox) return;

      const apps = Array.isArray(WINDOW_BIND_STATE.apps) ? WINDOW_BIND_STATE.apps : [];
      if (apps.length) {
        appsBox.innerHTML = apps.map((a) => {
          const icon = a.appId === "wecom" ? "🏢" : "💬";
          const cls = a.running ? "win-tag allow" : "win-tag protected";
          const statusTxt = a.running ? `运行中 · ${a.windowCount ?? 0} 窗` : "未运行";
          return `<span class="${cls}">${icon} ${escapeHtml(a.appLabel || a.appId)} · ${escapeHtml(statusTxt)}</span>`;
        }).join("");
      } else {
        appsBox.innerHTML = `<span class="win-tag app">等待扫描微信 / 企业微信…</span>`;
      }

      const b = WINDOW_BIND_STATE.boundWindow || {};
      const isAuto = (!b.appId || b.appId === "auto") && !b.windowID;
      const windows = Array.isArray(WINDOW_BIND_STATE.windows) ? WINDOW_BIND_STATE.windows : [];
      const popouts = [];
      const mains = [];
      windows.forEach((w, idx) => {
        const isPopout = w.isPopout === true || w.isMainWindow === false;
        if (isPopout) popouts.push({ win: w, idx });
        else mains.push({ win: w, idx });
      });

      const autoRowHtml = `
        <button type="button" class="window-item-btn${isAuto ? " active" : ""}" onclick="bindAppWindow({ appId: 'auto', windowID: null, windowTitle: '' })">
          <div class="window-item-top">
            <span class="window-item-title">✨ 自动跟随当前前台微信 / 企业微信</span>
            <span class="win-tag ${isAuto ? "allow" : "app"}">${isAuto ? "当前使用" : "默认"}</span>
          </div>
          <div class="window-item-meta">不锁定特定 windowID，按托管与安全白名单自动跟随</div>
        </button>
      `;

      const renderItem = ({ win, idx }, isPopoutSection) => {
        const icon = win.appId === "wecom" ? "🏢" : "💬";
        const appTxt = win.appLabel || (win.appId === "wecom" ? "企业微信" : "微信");
        const active = _isWindowActiveBinding(win);
        const allowlisted = isPopoutSection ? _isWindowAllowlisted(win) : true;
        const sizeTxt = win.bounds ? `${Math.round(win.bounds.width || 0)}×${Math.round(win.bounds.height || 0)}` : "";
        const titleTxt = win.title || (win.isMainWindow === false ? "独立聊天小窗" : `${appTxt}主窗`);
        const statusTag = isPopoutSection
          ? (allowlisted ? `<span class="win-tag allow">🟢 免切换直连</span>` : `<span class="win-tag protected">🔒 非白名单只读保护</span>`)
          : `<span class="win-tag app">🖥️ 主窗口</span>`;
        return `
          <button type="button" class="window-item-btn${active ? " active" : ""}" onclick="selectAppWindowByIndex(${idx})">
            <div class="window-item-top">
              <span class="window-item-title-wrap">
                <span class="win-tag app">${icon} ${escapeHtml(appTxt)}</span>
                <span class="window-item-title" title="${escapeHtml(titleTxt)}">${escapeHtml(titleTxt)}</span>
              </span>
              ${statusTag}
            </div>
            <div class="window-item-meta">
              <span>windowID: #${escapeHtml(String(win.windowID ?? "-"))}</span>
              ${sizeTxt ? `<span>尺寸 ${escapeHtml(sizeTxt)}</span>` : ""}
              ${active ? `<span style="color:var(--work-pine); font-weight:650;">✓ 已绑定</span>` : ""}
            </div>
          </button>
        `;
      };

      const popoutGroupHtml = `
        <div class="window-group window-group-popout">
          <div class="window-group-title">
            <span>📌 独立聊天小窗（免切换直连）</span>
            <span>${popouts.length} 窗</span>
          </div>
          ${popouts.length
            ? popouts.map((entry) => renderItem(entry, true)).join("")
            : `<div class="hosting-empty" style="font-size:11.5px; padding:4px 2px;">暂未检测到独立弹出的聊天小窗（双击微信/企业微信好友会话即可独立成窗）</div>`}
        </div>
      `;

      const mainGroupHtml = `
        <div class="window-group">
          <div class="window-group-title">
            <span>🖥️ 应用主窗口</span>
            <span>${mains.length} 窗</span>
          </div>
          ${mains.length
            ? mains.map((entry) => renderItem(entry, false)).join("")
            : `<div class="hosting-empty" style="font-size:11.5px; padding:4px 2px;">未检测到微信或企业微信主窗口</div>`}
        </div>
      `;

      bodyBox.innerHTML = autoRowHtml + popoutGroupHtml + mainGroupHtml;
    }

    async function refreshAppWindows(notify = false) {
      if (WINDOW_BIND_STATE.loading) return;
      WINDOW_BIND_STATE.loading = true;
      const bodyBox = document.getElementById("windowPickerBody");
      if (bodyBox && !WINDOW_BIND_STATE.windows.length) {
        bodyBox.innerHTML = `<div class="hosting-empty">正在扫描微信与企业微信可见窗口…</div>`;
      }
      try {
        const { status, data } = await apiJson("/api/workos/windows?app=all");
        if (status !== 200 || !data.ok) throw new Error(data.error || "扫描窗口失败");
        WINDOW_BIND_STATE.apps = Array.isArray(data.apps) ? data.apps : [];
        WINDOW_BIND_STATE.windows = Array.isArray(data.windows) ? data.windows : [];
        if (data.boundWindow) {
          WINDOW_BIND_STATE.boundWindow = data.boundWindow;
          renderBoundWindowButton();
        }
        renderAppWindowPickerList();
        if (isWindowPickerOpen()) positionWindowPickerPopover();
        if (notify) showToast(`🪟 已扫描到 ${WINDOW_BIND_STATE.windows.length} 个可见窗口`);
      } catch (err) {
        if (bodyBox) {
          bodyBox.innerHTML = `<div class="hosting-empty" style="color:var(--danger);">扫描窗口失败：${escapeHtml(err.message || err)}</div>`;
        }
        if (notify) showToast("扫描窗口失败: " + (err.message || err));
      } finally {
        WINDOW_BIND_STATE.loading = false;
      }
    }

    function openWindowPickerPopover() {
      const pop = document.getElementById("windowPickerPopover");
      const btn = document.getElementById("appWindowPickerBtn");
      if (!pop || !btn) return;
      if (supportsPopoverApi()) {
        try {
          if (!pop.matches(":popover-open")) pop.showPopover();
        } catch (e) {
          pop.classList.add("open");
        }
      } else {
        pop.classList.add("open");
      }
      btn.setAttribute("aria-expanded", "true");
      renderMultiWindowSchedulerState();
      positionWindowPickerPopover();
      refreshAppWindows(false);
      refreshSchedulerAndOverlay(false);
    }

    function _formatBorderBadge(bo) {
      const enabled = Boolean(bo?.enabled);
      const rawState = String(bo?.state || bo?.modeColorState || "idle").toLowerCase();
      if (!enabled) {
        return { cls: "off", text: "⚪ 已关闭" };
      }
      if (rawState === "thinking") {
        return { cls: "thinking", text: "🔵 思考中" };
      }
      if (rawState === "human_paused" || rawState === "paused" || rawState === "human_guard") {
        return { cls: "paused", text: "🟠 让路中" };
      }
      return { cls: "idle", text: "🟢 守护中" };
    }

    function renderMultiWindowSchedulerState() {
      const bo = MULTI_WIN_STATE.borderOverlay || {};
      const enabled = Boolean(bo.enabled);
      const badgeInfo = _formatBorderBadge(bo);
      const winCnt = Array.isArray(bo.activeWindows) ? bo.activeWindows.length : (Array.isArray(bo.activePopoutWindowIDs) ? bo.activePopoutWindowIDs.length : 0);

      for (const cbId of ["borderOverlayToggle", "settingsBorderOverlayToggle"]) {
        const cb = document.getElementById(cbId);
        if (cb) cb.checked = enabled;
      }
      const popBadge = document.getElementById("popoverBorderStateBadge");
      if (popBadge) {
        popBadge.className = `border-state-chip ${badgeInfo.cls}`;
        popBadge.textContent = enabled && winCnt > 0 ? `${badgeInfo.text} · ${winCnt}窗` : badgeInfo.text;
      }
      const cfgBadge = document.getElementById("settingsBorderStateBadge");
      if (cfgBadge) {
        cfgBadge.className = `border-state-chip ${badgeInfo.cls}`;
        cfgBadge.textContent = enabled
          ? `${badgeInfo.text}（${winCnt} 个独立小窗光圈）`
          : "⚪ 已关闭（🟢 守护中 / 🔵 思考中 / 🟠 让路中）";
      }

      const run = MULTI_WIN_STATE.lastRun;
      const sched = MULTI_WIN_STATE.scheduler || {};
      const lanes = run
        ? {
            fastLanePopouts: run.fastLanePopouts || [],
            mainWindowFallbackTargets: run.mainWindowFallbackTargets || [],
            protectedReadOnlyPopouts: run.protectedReadOnlyPopouts || [],
          }
        : (sched.lanes || {});
      const fastList = Array.isArray(lanes.fastLanePopouts) ? lanes.fastLanePopouts : [];
      const fallbackList = Array.isArray(lanes.mainWindowFallbackTargets) ? lanes.mainWindowFallbackTargets : [];
      const protectedList = Array.isArray(lanes.protectedReadOnlyPopouts) ? lanes.protectedReadOnlyPopouts : [];
      const dhash = run?.dhash || sched.dhash || {};
      const coalescer = run?.coalescer || sched.coalescer || {};
      const pq = run?.priorityQueue || sched.priorityQueue || {};
      const lastRound = run || sched.lastRound || null;

      const skipped = dhash.ocrSkippedByDHash ?? lastRound?.ocrSkippedByDHash ?? 0;
      const bursts = coalescer.coalescedBursts ?? lastRound?.coalescedBursts ?? 0;
      const qDepth = pq.queueDepth ?? 0;
      const hasDiagData = Boolean(
        run || sched.lastRound || fastList.length || fallbackList.length || protectedList.length || skipped || bursts || qDepth
      );

      const renderFastChip = (w) => {
        const title = w.target || w.title || ("#" + w.windowID);
        const ocrTag = typeof w.shouldRunOcr === "boolean"
          ? (w.shouldRunOcr ? " · OCR激活" : ` · dHash跳过(Δ=${w.dhashDistance ?? 0})`)
          : "";
        return `<span class="win-tag allow">🟢 ${escapeHtml(title)} #${escapeHtml(String(w.windowID ?? ""))}${escapeHtml(ocrTag)}</span>`;
      };
      const renderFallbackChip = (t) => `<span class="win-tag app">🖥️ ${escapeHtml(String(t))}</span>`;
      const renderProtectedChip = (w) => `<span class="win-tag protected">🔒 ${escapeHtml(w.title || ("#" + w.windowID))}</span>`;

      const diagHtml = `
        <div class="scheduler-metrics-grid">
          <span class="scheduler-metric-pill">dHash 跳过无效 OCR：<b>${escapeHtml(String(skipped))}</b></span>
          <span class="scheduler-metric-pill">滑动窗口合并：<b>${escapeHtml(String(bursts))}</b></span>
          <span class="scheduler-metric-pill">老化队列深度：<b>${escapeHtml(String(qDepth))}</b></span>
          ${lastRound?.elapsedMs !== undefined ? `<span class="scheduler-metric-pill">${escapeHtml(String(lastRound.scanSource || "dhash"))} · <b>${escapeHtml(String(lastRound.elapsedMs))}ms</b></span>` : ""}
        </div>
        <div class="scheduler-lane-row">
          <span class="scheduler-lane-label">⚡ 快车道小窗 (${fastList.length})：</span>
          ${fastList.length ? fastList.map(renderFastChip).join("") : `<span style="color:var(--text-muted);">暂无已打开的白名单独立小窗</span>`}
        </div>
        <div class="scheduler-lane-row">
          <span class="scheduler-lane-label">🖥️ 主窗左栏兜底去重 (${fallbackList.length})：</span>
          ${fallbackList.length ? fallbackList.map(renderFallbackChip).join("") : `<span style="color:var(--text-muted);">全部已在快车道覆盖</span>`}
        </div>
        <div class="scheduler-lane-row">
          <span class="scheduler-lane-label">🔒 受保护只读小窗 (${protectedList.length})：</span>
          ${protectedList.length ? protectedList.map(renderProtectedChip).join("") : `<span style="color:var(--text-muted);">无外部只读小窗</span>`}
        </div>
      `;

      const popSummary = document.getElementById("popoverSchedulerSummary");
      if (popSummary) {
        popSummary.hidden = !hasDiagData;
        if (hasDiagData) popSummary.innerHTML = diagHtml;
      }
      const cfgBox = document.getElementById("workosSchedulerBox");
      if (cfgBox) {
        cfgBox.innerHTML = hasDiagData
          ? diagHtml
          : `<div style="color:var(--text-muted);">点击「⚡ 跑一轮多窗调度诊断」可实时查看快车道独立小窗、主窗兜底目标、受保护只读小窗与 dHash/窗口合并指标。</div>`;
      }
    }

    async function refreshSchedulerAndOverlay(notify = false) {
      try {
        const [{ status: sStatus, data: sData }, { status: bStatus, data: bData }] = await Promise.all([
          apiJson("/api/workos/scheduler").catch(() => ({ status: 0, data: null })),
          apiJson("/api/workos/border-overlay").catch(() => ({ status: 0, data: null })),
        ]);
        if (sStatus === 200 && sData?.ok) {
          MULTI_WIN_STATE.scheduler = sData;
          if (sData.borderOverlay) MULTI_WIN_STATE.borderOverlay = sData.borderOverlay;
        }
        if (bStatus === 200 && bData?.ok) {
          MULTI_WIN_STATE.borderOverlay = bData;
        }
        renderMultiWindowSchedulerState();
        if (isWindowPickerOpen()) positionWindowPickerPopover();
        if (notify) showToast("🔄 已刷新多窗调度与透明呼吸边框状态");
      } catch (err) {
        if (notify) showToast("刷新调度状态失败: " + (err.message || err));
      }
    }

    async function toggleBorderOverlay(enabled) {
      try {
        const { status, data } = await apiJson("/api/workos/border-overlay", {
          method: "POST",
          body: JSON.stringify({ enabled: Boolean(enabled) }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "切换边框光圈失败");
        MULTI_WIN_STATE.borderOverlay = data;
        renderMultiWindowSchedulerState();
        const badge = _formatBorderBadge(data);
        const cnt = Array.isArray(data.activeWindows) ? data.activeWindows.length : 0;
        showToast(
          data.enabled
            ? `${badge.text} · 已开启零风控透明呼吸边框（覆盖 ${cnt} 个白名单独立小窗）`
            : "⚪ 已关闭独立小窗透明呼吸边框"
        );
      } catch (err) {
        renderMultiWindowSchedulerState();
        showToast("设置透明呼吸边框失败: " + (err.message || err));
      }
    }

    async function setBorderOverlayState(state) {
      try {
        const { status, data } = await apiJson("/api/workos/border-overlay", {
          method: "POST",
          body: JSON.stringify({ enabled: true, state }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "切换光圈状态失败");
        MULTI_WIN_STATE.borderOverlay = data;
        renderMultiWindowSchedulerState();
        const badge = _formatBorderBadge(data);
        showToast(`已切换光圈状态：${badge.text} (${data.color || ""})`);
      } catch (err) {
        showToast("切换光圈状态失败: " + (err.message || err));
      }
    }

    async function runMultiWindowScheduler(autoThink = false) {
      if (MULTI_WIN_STATE.busy) return;
      MULTI_WIN_STATE.busy = true;
      const btns = [
        document.getElementById("runMultiWinSchedulerBtn"),
        document.getElementById("settingsRunMultiWinBtn"),
      ].filter(Boolean);
      btns.forEach((b) => {
        b.disabled = true;
        b.textContent = "⏳ 调度诊断中…";
      });
      try {
        const { status, data } = await apiJson("/api/workos/scheduler/run", {
          method: "POST",
          body: JSON.stringify({ auto_think: Boolean(autoThink), dry_run: true, app: "all", dhash_threshold: 4 }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "多窗调度诊断失败");
        MULTI_WIN_STATE.lastRun = data;
        if (data.borderOverlay) MULTI_WIN_STATE.borderOverlay = data.borderOverlay;
        renderMultiWindowSchedulerState();
        if (isWindowPickerOpen()) positionWindowPickerPopover();
        const fastCnt = (data.fastLanePopouts || []).length;
        const fbCnt = (data.mainWindowFallbackTargets || []).length;
        const protCnt = (data.protectedReadOnlyPopouts || []).length;
        const skipped = data.dhash?.ocrSkippedByDHash ?? 0;
        showToast(`⚡ 多窗调度完成 (${data.elapsedMs ?? "-"}ms)：快车道 ${fastCnt} 窗 · 主窗兜底 ${fbCnt} 人 · 只读保护 ${protCnt} 窗 · dHash 跳过 ${skipped} 次`);
        loadWorkosHarness(false);
      } catch (err) {
        showToast("多窗调度诊断失败: " + (err.message || err));
      } finally {
        MULTI_WIN_STATE.busy = false;
        btns.forEach((b) => {
          b.disabled = false;
          b.textContent = "⚡ 跑一轮多窗调度诊断";
        });
      }
    }

    function hideWindowPickerPopover() {
      const pop = document.getElementById("windowPickerPopover");
      const btn = document.getElementById("appWindowPickerBtn");
      if (!pop) return;
      if (supportsPopoverApi()) {
        try {
          if (pop.matches(":popover-open")) pop.hidePopover();
        } catch (e) {}
      }
      pop.classList.remove("open");
      if (btn) btn.setAttribute("aria-expanded", "false");
    }

    function toggleWindowPickerPopover() {
      if (isWindowPickerOpen()) hideWindowPickerPopover();
      else openWindowPickerPopover();
    }

    function selectAppWindowByIndex(index) {
      const win = WINDOW_BIND_STATE.windows?.[index];
      if (!win) return;
      const isPopout = win.isPopout === true || win.isMainWindow === false;
      const allowlisted = isPopout ? _isWindowAllowlisted(win) : true;
      bindAppWindow({
        appId: win.appId || "auto",
        windowID: win.windowID ?? null,
        windowTitle: win.title || win.appLabel || "",
        appLabel: win.appLabel || "",
        isMainWindow: !isPopout,
        isAllowlistedTarget: allowlisted,
      });
    }

    async function bindAppWindow(opts) {
      const payload = {
        appId: opts?.appId || "auto",
        windowID: opts?.windowID ?? null,
        windowTitle: opts?.windowTitle || "",
        followUpIsolation: true,
      };
      if (opts?.appLabel) payload.appLabel = opts.appLabel;
      try {
        const { status, data } = await apiJson("/api/workos/bind-window", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "绑定窗口失败");
        WINDOW_BIND_STATE.boundWindow = data.binding || data;
        renderBoundWindowButton();
        renderAppWindowPickerList();
        hideWindowPickerPopover();
        const label = formatBoundWindowLabel(WINDOW_BIND_STATE.boundWindow);
        if (payload.appId === "auto") {
          showToast("🪟 已切回自动跟随当前窗口");
        } else if (opts?.isMainWindow === false) {
          showToast(
            opts.isAllowlistedTarget
              ? `🟢 已绑定免切换直连小窗：${label} (#${data.windowID})`
              : `🔒 已切至只读观察小窗：${label}（非白名单目标，禁止开启发送托管）`
          );
        } else {
          showToast(`🪟 已绑定目标窗口：${label}`);
        }
        loadWorkosHarness(false);
      } catch (err) {
        showToast("绑定窗口失败: " + (err.message || err));
      }
    }

    function arrayBufferToBase64(buffer) {
      const bytes = new Uint8Array(buffer);
      const chunkSize = 0x8000;
      const chunks = [];
      for (let i = 0; i < bytes.length; i += chunkSize) {
        chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize)));
      }
      return btoa(chunks.join(""));
    }

    function setDocIngestStatus(msg, tone = "") {
      const el = document.getElementById("docIngestStatus");
      if (!el) return;
      el.textContent = msg || "";
      if (tone) el.dataset.tone = tone;
      else el.removeAttribute("data-tone");
    }

    function openDocIngestModal() {
      const dlg = document.getElementById("docIngestOverlay");
      if (!dlg) return;
      if (typeof dlg.showModal === "function") {
        if (!dlg.open) dlg.showModal();
      } else {
        dlg.setAttribute("open", "");
      }
      const textEl = document.getElementById("docIngestText");
      if (textEl) textEl.focus();
    }

    function hideDocIngestModal() {
      const dlg = document.getElementById("docIngestOverlay");
      if (!dlg) return;
      if (typeof dlg.close === "function" && dlg.open) {
        dlg.close();
      } else {
        dlg.removeAttribute("open");
        DOC_INGEST_STATE.lastClosedAt = Date.now();
      }
    }

    function clearDocIngestFile() {
      const fileEl = document.getElementById("docIngestFile");
      if (fileEl) fileEl.value = "";
      DOC_INGEST_STATE.fileUpload = null;
      const metaEl = document.getElementById("docIngestFileMeta");
      if (metaEl) metaEl.textContent = "支持 PDF 文本与扫描页自动识别（≤25MB）";
    }

    function resetDocIngestForm() {
      clearDocIngestFile();
      const docNameEl = document.getElementById("docIngestDocName");
      const textEl = document.getElementById("docIngestText");
      const instrEl = document.getElementById("docIngestInstruction");
      const resPane = document.getElementById("docIngestResultPane");
      if (docNameEl) docNameEl.value = "";
      if (textEl) textEl.value = "";
      if (instrEl) instrEl.value = "希望你能够替代我去和顾客聊天";
      if (resPane) resPane.hidden = true;
      DOC_INGEST_STATE.preview = null;
      DOC_INGEST_STATE.items = [];
      DOC_INGEST_STATE.strategy = "bind_kb";
      DOC_INGEST_STATE.docName = "";
      setDocIngestStatus("");
    }

    async function handleDocIngestFileChange(inputEl) {
      const file = inputEl?.files?.[0];
      if (!file) {
        clearDocIngestFile();
        return;
      }
      const ext = (file.name.match(/\.[^.]+$/)?.[0] || "").toLowerCase();
      if (![".pdf", ".txt", ".md", ".markdown", ".json"].includes(ext)) {
        setDocIngestStatus(`不支持的文件格式 ${ext || "未知"}，请选择 .pdf / .txt / .md / .json`, "error");
        clearDocIngestFile();
        return;
      }
      if (file.size > 25 * 1024 * 1024) {
        setDocIngestStatus("文件大小超过 25MB 限制，请拆分后再上传。", "error");
        clearDocIngestFile();
        return;
      }
      const metaEl = document.getElementById("docIngestFileMeta");
      if (metaEl) metaEl.textContent = `正在读取 ${file.name}…`;
      try {
        const buf = await file.arrayBuffer();
        const b64 = arrayBufferToBase64(buf);
        DOC_INGEST_STATE.fileUpload = { filename: file.name, file_bytes_b64: b64, size: file.size };
        const kb = Math.max(1, Math.round(file.size / 1024));
        if (metaEl) {
          metaEl.innerHTML = `<span>已加载：<b>${escapeHtml(file.name)}</b> (${kb} KB)</span> <button type="button" class="link-btn" onclick="clearDocIngestFile()">清除</button>`;
        }
        setDocIngestStatus(`已就绪「${file.name}」，点击「🤖 AI 解析资料」开始拆解。`);
      } catch (err) {
        setDocIngestStatus("读取文件失败: " + (err.message || err), "error");
        clearDocIngestFile();
      }
    }

    function renderDocIngestStrategyOptions() {
      const grid = document.getElementById("docIngestStrategyGrid");
      if (!grid) return;
      const options = DOC_INGEST_STATE.preview?.strategyOptions || [
        { id: "bind_kb", recommended: true, title: "绑进知识库（推荐）", desc: "保持现有营销人设不变，AI 回答精准按产品资料作答" },
        { id: "merge_prompt", recommended: false, title: "直接优化岗位提示词", desc: "把关键卖点并入 AI 员工任务目标" },
      ];
      grid.innerHTML = options.map((opt) => {
        const checked = DOC_INGEST_STATE.strategy === opt.id;
        const badge = opt.recommended ? `<span class="win-tag allow">推荐 · 营销人设不变</span>` : `<span class="win-tag app">同步改写目标</span>`;
        return `
          <label class="doc-strategy-card${checked ? " selected" : ""}">
            <input type="radio" name="docIngestStrategy" value="${escapeHtml(opt.id)}" ${checked ? "checked" : ""} onchange="selectDocIngestStrategy('${escapeHtml(opt.id)}')" />
            <div>
              <div class="doc-strategy-title"><span>${escapeHtml(opt.title)}</span>${badge}</div>
              <div class="doc-strategy-desc">${escapeHtml(opt.desc)}</div>
            </div>
          </label>
        `;
      }).join("");
    }

    function renderDocIngestConfirmCard() {
      const titleEl = document.getElementById("docIngestConfirmTitle");
      const summaryEl = document.getElementById("docIngestConfirmSummary");
      const headingEl = document.getElementById("docIngestItemsHeading");
      const confirmBtn = document.getElementById("docIngestConfirmBtn");
      const total = DOC_INGEST_STATE.items.length;
      const selectedCount = DOC_INGEST_STATE.items.filter((it) => it.selected !== false).length;
      if (headingEl) {
        headingEl.textContent = `拆解后的结构化知识卡片（已选 ${selectedCount} / ${total} 条，可勾选 / 微调）`;
      }
      const docLabel = DOC_INGEST_STATE.docName || "当前资料";
      if (DOC_INGEST_STATE.strategy === "merge_prompt") {
        if (titleEl) titleEl.textContent = "确认执行任务 · 直接优化岗位提示词";
        if (summaryEl) {
          summaryEl.textContent = `将把《${docLabel}》已选的 ${selectedCount} 条内容写入 FTS5 知识库，并同步将核心卖点合并进 AI 员工岗位任务目标。`;
        }
      } else {
        const cardTitle = DOC_INGEST_STATE.preview?.confirmCard?.title || "确认执行任务 · 绑进知识库";
        if (titleEl) titleEl.textContent = cardTitle;
        if (summaryEl) {
          summaryEl.textContent = `已将《${docLabel}》拆解并勾选 ${selectedCount} 条结构化知识，推荐绑进共享知识库：保持现有营销人设不变，AI 回复精准按产品资料作答。`;
        }
      }
      if (confirmBtn) {
        confirmBtn.textContent = DOC_INGEST_STATE.preview?.confirmCard?.confirmLabel || "确认";
      }
    }

    function renderDocIngestItems() {
      const listEl = document.getElementById("docIngestItemsList");
      if (!listEl) return;
      const items = DOC_INGEST_STATE.items || [];
      if (!items.length) {
        listEl.innerHTML = `<div class="hosting-empty">未拆解出知识条目。</div>`;
        renderDocIngestConfirmCard();
        return;
      }
      const kindOpts = [
        { val: "knowledge", label: "knowledge · 业务知识" },
        { val: "faq", label: "faq · 常见问题" },
        { val: "script", label: "script · 推荐话术" },
        { val: "terminology", label: "terminology · 注意事项/术语" },
      ];
      listEl.innerHTML = items.map((it, idx) => {
        const checked = it.selected !== false;
        const kwText = Array.isArray(it.keywords) ? it.keywords.join(", ") : String(it.keywords || "");
        const confPct = it.confidence ? Math.round(Number(it.confidence) * 100) + "%" : "";
        return `
          <div class="doc-draft-item${checked ? "" : " unchecked"}">
            <div class="doc-draft-item-head">
              <input type="checkbox" aria-label="勾选条目 ${idx + 1}" ${checked ? "checked" : ""} onchange="updateDocIngestItemField(${idx}, 'selected', this.checked)" />
              <span class="win-tag allow">${escapeHtml(it.category || "产品知识")}</span>
              <select aria-label="条目分类 ${idx + 1}" onchange="updateDocIngestItemField(${idx}, 'kind', this.value)">
                ${kindOpts.map((o) => `<option value="${o.val}" ${it.kind === o.val ? "selected" : ""}>${o.label}</option>`).join("")}
              </select>
              <input type="text" class="doc-draft-item-title" aria-label="条目标题 ${idx + 1}" value="${escapeHtml(it.title || "")}" oninput="updateDocIngestItemField(${idx}, 'title', this.value)" />
              ${confPct ? `<span class="win-tag app">置信度 ${confPct}</span>` : ""}
            </div>
            <textarea class="doc-draft-item-body" aria-label="条目正文 ${idx + 1}" oninput="updateDocIngestItemField(${idx}, 'body', this.value)">${escapeHtml(it.body || "")}</textarea>
            <input type="text" class="doc-draft-item-kw" aria-label="条目关键词 ${idx + 1}" placeholder="关键词（逗号分隔）" value="${escapeHtml(kwText)}" oninput="updateDocIngestItemField(${idx}, 'keywords', this.value)" />
          </div>
        `;
      }).join("");
      renderDocIngestConfirmCard();
    }

    function updateDocIngestItemField(idx, field, value) {
      const it = DOC_INGEST_STATE.items?.[idx];
      if (!it) return;
      if (field === "selected") {
        it.selected = Boolean(value);
        const card = document.querySelectorAll("#docIngestItemsList .doc-draft-item")[idx];
        if (card) card.classList.toggle("unchecked", !it.selected);
        renderDocIngestConfirmCard();
      } else if (field === "keywords") {
        it.keywords = String(value || "").split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      } else {
        it[field] = String(value || "");
      }
    }

    function docIngestSelectAll(flag) {
      (DOC_INGEST_STATE.items || []).forEach((it) => { it.selected = Boolean(flag); });
      renderDocIngestItems();
    }

    function selectDocIngestStrategy(strategyId) {
      DOC_INGEST_STATE.strategy = strategyId === "merge_prompt" ? "merge_prompt" : "bind_kb";
      renderDocIngestStrategyOptions();
      renderDocIngestConfirmCard();
    }

    function continueEditingDocIngest() {
      setDocIngestStatus("可继续修改原始资料或微调下方卡片，确认无误后点「确认」入库。");
      const textEl = document.getElementById("docIngestText");
      if (textEl) {
        textEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
        textEl.focus();
      }
    }

    async function previewDocIngest() {
      if (DOC_INGEST_STATE.busy) return;
      const rawText = document.getElementById("docIngestText")?.value || "";
      const hasFile = Boolean(DOC_INGEST_STATE.fileUpload?.file_bytes_b64);
      if (!hasFile && !rawText.trim()) {
        setDocIngestStatus("请先上传 PDF/文本文件，或粘贴产品资料长文本。", "error");
        document.getElementById("docIngestText")?.focus();
        return;
      }
      const instruction = (document.getElementById("docIngestInstruction")?.value || "").trim() || "希望你能够替代我去和顾客聊天";
      const docName = (document.getElementById("docIngestDocName")?.value || "").trim();
      const btn = document.getElementById("docIngestPreviewBtn");
      DOC_INGEST_STATE.busy = true;
      if (btn) {
        btn.disabled = true;
        btn.textContent = "🤖 AI 正在解析资料…";
      }
      setDocIngestStatus(hasFile ? "正在提取文件内容并拆解结构化知识卡片…" : "正在分析长文本并拆解结构化知识卡片…");
      try {
        const { status, data } = await apiJson("/api/workos/doc-ingest/preview", {
          method: "POST",
          body: JSON.stringify({
            filename: DOC_INGEST_STATE.fileUpload?.filename || "",
            file_bytes_b64: DOC_INGEST_STATE.fileUpload?.file_bytes_b64 || "",
            raw_text: rawText,
            instruction,
            doc_name: docName,
            max_pages: 12,
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "解析资料失败");
        DOC_INGEST_STATE.preview = data;
        DOC_INGEST_STATE.docName = data.docName || docName || "上传产品资料";
        DOC_INGEST_STATE.strategy = data.recommendedStrategy || "bind_kb";
        DOC_INGEST_STATE.items = (data.items || []).map((it) => ({
          ...it,
          selected: it.selected !== false,
          keywords: Array.isArray(it.keywords) ? [...it.keywords] : [],
        }));
        const metaBox = document.getElementById("docIngestPreviewMeta");
        if (metaBox) {
          const pageInfo = data.pageCount ? ` · 页数 ${data.processedPages ?? data.pageCount}/${data.pageCount}${data.truncated ? "（已截断前12页）" : ""}` : "";
          const modeLabel = data.extractionMode === "llm_structured" ? "大模型智能拆解" : "结构化规则切块";
          metaBox.innerHTML = `
            <span class="win-tag allow">解析完成</span>
            <span><b>${escapeHtml(DOC_INGEST_STATE.docName)}</b> · 提取 ${data.extractedTextLength ?? 0} 字${escapeHtml(pageInfo)} · ${escapeHtml(modeLabel)}</span>
          `;
        }
        renderDocIngestStrategyOptions();
        renderDocIngestItems();
        const resPane = document.getElementById("docIngestResultPane");
        if (resPane) {
          resPane.hidden = false;
          resPane.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        setDocIngestStatus(`已拆解出 ${DOC_INGEST_STATE.items.length} 条知识卡片，请确认执行策略后点「确认」。`);
      } catch (err) {
        setDocIngestStatus("解析失败: " + (err.message || err), "error");
      } finally {
        DOC_INGEST_STATE.busy = false;
        if (btn) {
          btn.disabled = false;
          btn.textContent = "🤖 AI 解析资料";
        }
      }
    }

    async function confirmDocIngest() {
      if (DOC_INGEST_STATE.busy) return;
      const selected = (DOC_INGEST_STATE.items || []).filter((it) => it.selected !== false && String(it.title || "").trim() && String(it.body || "").trim());
      if (!selected.length) {
        setDocIngestStatus("请至少勾选 1 条标题与正文非空的知识卡片后再确认入库。", "error");
        return;
      }
      const btn = document.getElementById("docIngestConfirmBtn");
      DOC_INGEST_STATE.busy = true;
      if (btn) {
        btn.disabled = true;
        btn.textContent = "写入知识库中…";
      }
      setDocIngestStatus("正在批量写入 FTS5 知识库并刷新索引…");
      try {
        const strategy = DOC_INGEST_STATE.strategy || "bind_kb";
        const instruction = (document.getElementById("docIngestInstruction")?.value || "").trim();
        const docName = DOC_INGEST_STATE.docName || (document.getElementById("docIngestDocName")?.value || "").trim();
        const { status, data } = await apiJson("/api/workos/doc-ingest/confirm", {
          method: "POST",
          body: JSON.stringify({
            items: selected,
            strategy,
            doc_name: docName,
            apply_prompt_target: strategy === "merge_prompt",
            instruction,
          }),
        });
        if (status !== 200 || !data.ok) throw new Error(data.error || "入库失败");
        resetDocIngestForm();
        hideDocIngestModal();
        await Promise.all([loadWorkosHarness(false), loadOverview(false)]);
        showToast(
          `✅ 已将《${data.docName || docName || "资料"}》${data.savedCount ?? selected.length} 条知识写入 FTS5 知识库（共 ${data.knowledgeEntriesCount ?? "-"} 条）`
          + (data.promptUpdated ? "，并已同步更新岗位目标" : "")
        );
      } catch (err) {
        setDocIngestStatus("入库失败: " + (err.message || err), "error");
      } finally {
        DOC_INGEST_STATE.busy = false;
        if (btn) {
          btn.disabled = false;
          btn.textContent = DOC_INGEST_STATE.preview?.confirmCard?.confirmLabel || "确认";
        }
      }
    }

    async function saveHumanGuardFromSettings() {
      const enabled = !!document.getElementById("cfgGuardEnabled")?.checked;
      const cooldownSeconds = Number(document.getElementById("cfgGuardCooldown")?.value || 45);
      const idleResumeSeconds = Number(document.getElementById("cfgGuardIdle")?.value || 45);
      const ge = document.getElementById("guardEnabledInput");
      const gc = document.getElementById("guardCooldownInput");
      const gi = document.getElementById("guardIdleInput");
      if (ge) ge.checked = enabled;
      if (gc) gc.value = cooldownSeconds;
      if (gi) gi.value = idleResumeSeconds;
      await saveHumanGuardConfig();
    }

    async function runAgentDispatchFor(targetOverride) {
      const target = (targetOverride || document.getElementById("dispatchTargetInput")?.value || "").trim();
      if (!target) { showToast("请填写目标联系人"); return; }
      showToast(`正在解析「${target}」的指令、链接与媒体并派发给绑定智能体...`);
      try {
        const { data } = await apiJson("/api/agent-dispatch", {
          method: "POST",
          body: JSON.stringify({ target, includeLiveMedia: true, executeWithAgent: true }),
        });
        showToast(`派发完成：识别 ${data.tasksCount ?? 0} 条指令，${data.mediaAnalysesCount ?? 0} 项媒体分析`);
        await loadOverview();
      } catch (err) {
        showToast("指令派发失败: " + err.message);
      }
    }

    let SALES_CRM_ANALYSIS = null;

    function _actionBadgeColor(actionCode) {
      if (actionCode === "bargain") return "background:var(--primary-soft); color:var(--primary);";
      if (actionCode === "push") return "background:var(--accent-soft); color:var(--accent);";
      if (actionCode === "reset") return "background:var(--special-soft); color:var(--special);";
      return "background:var(--vip-soft); color:var(--vip);";
    }

    function renderSalesCrmDetail(analysis) {
      if (!isSalesCrmAvailable()) return;
      const targetBadge = document.getElementById("crmSelectedNameBadge");
      const mGrid = document.getElementById("crmMetrics15Grid");
      const fBox = document.getElementById("crmFormulasBox");
      const tBox = document.getElementById("crmTimelineBox");
      const dBox = document.getElementById("crmDraftsBox");
      if (!analysis || !analysis.person) {
        if (targetBadge) targetBadge.textContent = "暂无客户";
        if (mGrid) mGrid.innerHTML = `<div style="color:var(--text-muted);">请先点击下方客户行或同步微信历史。</div>`;
        if (fBox) fBox.innerHTML = `<div style="color:var(--text-muted);">等待选择客户...</div>`;
        if (tBox) tBox.innerHTML = `<div style="color:var(--text-muted);">暂无时间线事件。</div>`;
        if (dBox) dBox.innerHTML = `<div style="color:var(--text-muted);">暂无草稿。</div>`;
        return;
      }

      const prevPersonId = SALES_CRM_ANALYSIS && SALES_CRM_ANALYSIS._formPopulatedPersonId;
      SALES_CRM_ANALYSIS = analysis;
      const p = analysis.person;
      const m = analysis.metrics || {};
      const f = analysis.formulas || {};
      if (targetBadge) {
        targetBadge.textContent = `${p.displayName || ""} · ${p.stage || ""} (建议下一阶段: ${p.nextStage || p.stage || ""})`;
      }

      if (prevPersonId !== p.personId || analysis._forceFormSync) {
        const targetInput = document.getElementById("crmTargetInput");
        if (targetInput) targetInput.value = p.displayName || "";
        const stageSelect = document.getElementById("crmStageSelect");
        if (stageSelect && p.stage) stageSelect.value = p.stage;
        const fuInput = document.getElementById("crmFollowUpInput");
        if (fuInput) fuInput.value = p.followUpBeijing ? String(p.followUpBeijing).slice(0, 16) : "";
        const dvInput = document.getElementById("crmDealValueInput");
        if (dvInput && typeof p.dealValue === "number") dvInput.value = String(p.dealValue);
        const noteInput = document.getElementById("crmNoteInput");
        if (noteInput && p.note !== undefined) noteInput.value = p.note || "";
      }
      SALES_CRM_ANALYSIS._formPopulatedPersonId = p.personId;

      if (mGrid) {
        const dims = m.dimensions15 || [];
        mGrid.innerHTML = `
          <div class="field-box" style="padding:8px 10px; margin-bottom:4px;">
            综合评分 <strong>${((m.compositeScore || 0) * 100).toFixed(1)}</strong> · 基准分 <strong>${((m.baseScore || 0) * 100).toFixed(1)}</strong> · 意向 <strong>${escapeHtml(m.signalLevel || "")}</strong> · 模式 <strong>${escapeHtml(m.interactionPatternLabel || "")}</strong> (${m.messageCount || 0} 条消息)
          </div>
        ` + dims.map((d) => {
          const pct = Math.max(0, Math.min(100, Math.round((Number(d.normalized) || 0) * 100)));
          const barColor = d.key === "neediness_penalty" ? "var(--danger)" : "var(--primary)";
          return `
            <div style="font-size:12px;">
              <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
                <span><strong>${escapeHtml(d.label || d.key)}</strong> <span style="color:var(--text-muted);">(${escapeHtml(d.key)})</span></span>
                <span>norm=${Number(d.normalized || 0).toFixed(3)} · raw=${escapeHtml(String(d.raw ?? ""))} · conf=${Number(d.confidence || 0).toFixed(2)}</span>
              </div>
              <div style="height:6px; border-radius:4px; background:var(--surface-soft); overflow:hidden;">
                <div style="width:${pct}%; height:100%; background:${barColor};"></div>
              </div>
            </div>
          `;
        }).join("");
      }

      if (fBox) {
        const bq = f.bq || {};
        const bsp = f.bsp || {};
        const bws = f.bws || {};
        const pv = f.pv || {};
        const act = f.salesAction || {};
        fBox.innerHTML = `
          <div class="kpi-grid" style="grid-template-columns:repeat(2,1fr); gap:8px;">
            <div class="kpi-card">
              <div class="kpi-label">BQ 商机质量 (${escapeHtml(bq.label || bq.interpretation || "")})</div>
              <div class="kpi-value">${Number(bq.bq || 0).toFixed(3)}</div>
              <div class="kpi-sub">SP + FBACK + Investment - PFACE</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">BSP 销售势能 (${escapeHtml(bsp.label || bsp.interpretation || "")})</div>
              <div class="kpi-value">${Number(bsp.bsp || 0).toFixed(3)}</div>
              <div class="kpi-sub">对话深度差 / 时延反比</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">BWS 成交信号 (${escapeHtml(bws.label || bws.interpretation || "")})</div>
              <div class="kpi-value">${Number(bws.bws || 0).toFixed(3)}</div>
              <div class="kpi-sub">${escapeHtml((bws.recommendedAction || bws.action || "").slice(0, 28))}</div>
            </div>
            <div class="kpi-card">
              <div class="kpi-label">PV 推进价值 (${escapeHtml(pv.label || pv.interpretation || "")})</div>
              <div class="kpi-value">${Number(pv.pv || 0).toFixed(3)}</div>
              <div class="kpi-sub">预期成交金额 ¥${Number(f.expectedDealValue || 0).toLocaleString()}</div>
            </div>
          </div>
          <div class="field-box" style="margin-top:8px; padding:10px;">
            <div>推荐商业动作：<span class="badge" style="${_actionBadgeColor(act.action)} padding:2px 8px; border-radius:999px; font-weight:700;">${escapeHtml(act.action || "maintain")}</span></div>
            <div style="font-size:12.5px; color:var(--text-secondary); margin-top:4px;">${escapeHtml(act.reason || "")}</div>
          </div>
        `;
      }

      if (tBox) {
        const events = analysis.timeline || [];
        tBox.innerHTML = events.length
          ? events.map((ev) => `
              <div class="field-box" style="padding:8px 10px; margin-bottom:6px;">
                <div style="display:flex; justify-content:space-between; font-size:12px;">
                  <strong>[${escapeHtml(ev.category || ev.eventType || "")}] ${escapeHtml(ev.title || "")}</strong>
                  <span style="color:var(--text-muted);">${escapeHtml(ev.at || "")}</span>
                </div>
                <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">${escapeHtml(ev.detail || "")}</div>
              </div>
            `).join("")
          : `<div style="color:var(--text-muted);">暂无互动事件记录</div>`;
      }

      if (dBox) {
        const drafts = analysis.topDrafts || [];
        const encTarget = encodeURIComponent(p.displayName || p.personId || "");
        dBox.innerHTML = drafts.length
          ? drafts.map((dr) => `
              <div class="field-box" style="padding:10px; margin-bottom:8px; ${dr.status === "adopted" ? "border-color:var(--primary);" : ""}">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                  <strong>Top ${dr.rank} · ${escapeHtml(dr.styleTag || "")}</strong>
                  <span class="badge" style="font-size:11px;">${escapeHtml(dr.status || "candidate")}</span>
                </div>
                <div style="font-size:13px; margin-bottom:6px; white-space:pre-wrap;">${escapeHtml(dr.content || "")}</div>
                <div style="font-size:11.5px; color:var(--text-muted); margin-bottom:6px;">依据：${escapeHtml((dr.basis && dr.basis.reason) || "")}</div>
                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                  <button class="btn btn-primary btn-sm" onclick="crmAdoptDraft('${encTarget}', ${dr.rank}, 'adopt_only')">✅ 采纳并记入时间线</button>
                  <button class="btn btn-ghost btn-sm" onclick="crmAdoptDraft('${encTarget}', ${dr.rank}, 'dry_run')">🧪 安全预演 Dry-Run</button>
                  <button class="btn btn-success btn-sm" onclick="crmAdoptDraft('${encTarget}', ${dr.rank}, 'silent_verify')">🛡️ 3x 回读静默校验</button>
                </div>
              </div>
            `).join("")
          : `<div style="color:var(--text-muted);">点击客户或分析按钮生成 Top 1-3 跟进草稿</div>`;
      }
    }

    function isSalesCrmAvailable() {
      return Boolean(STATE?.salesCrm && STATE.salesCrm.available !== false);
    }

    function requireSalesCrm() {
      if (isSalesCrmAvailable()) return true;
      showToast("客户跟进模块当前不可用。");
      return false;
    }

    function renderSalesCrmTab() {
      const crm = STATE?.salesCrm;
      const available = isSalesCrmAvailable();
      const status = document.getElementById("crmUnavailable");
      document.querySelectorAll("#tab-salescrm button, #tab-salescrm input, #tab-salescrm textarea, #tab-salescrm select")
        .forEach(control => { control.disabled = !available; });
      status.hidden = available;
      status.textContent = available ? "" : (crm?.available === false
        ? "当前构建未启用客户跟进模块。仍可使用联系人和统计。"
        : "暂未读取到客户跟进模块的状态。");
      if (!available) {
        SALES_CRM_ANALYSIS = null;
        setStatText("crmUpstreamBadge", "");
        setStatText("crmSelectedNameBadge", "未选择");
        for (const id of ["crmKpiGrid", "crmRemindersBox", "crmRankingsTableBody", "crmMetrics15Grid", "crmFormulasBox", "crmTimelineBox", "crmDraftsBox"]) {
          document.getElementById(id)?.replaceChildren();
        }
        return;
      }
      const summary = crm.summary || {};
      const up = crm.upstream || {};
      const upstream = up.repo ? ` · ${up.repo}${up.commit ? " " + up.commit.slice(0, 7) : ""}` : "";
      setStatText("crmUpstreamBadge", "15 维量化 · BQ/BSP/BWS/PV · 北京时间跟进提醒" + upstream);

      const kpiEl = document.getElementById("crmKpiGrid");
      if (kpiEl) {
        const rankings = crm.rankings || [];
        const topAction = rankings.length ? rankings[0].salesAction : "maintain";
        kpiEl.innerHTML = `
          <div class="kpi-card">
            <div class="kpi-label">CRM 客户总数</div>
            <div class="kpi-value">${summary.totalPeople ?? 0}</div>
            <div class="kpi-sub">微信联系人 + Soul 自动合并</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">强 / 中意向客户</div>
            <div class="kpi-value">${summary.strongIntentCount ?? 0} / ${summary.mediumIntentCount ?? 0}</div>
            <div class="kpi-sub">SalesCRM 15D Composite 阈值判定</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">到期 / 待办提醒 (CST)</div>
            <div class="kpi-value" style="color:${(summary.dueRemindersCount || 0) > 0 ? "var(--special)" : "var(--primary)"};">${summary.dueRemindersCount ?? 0} / ${summary.upcomingRemindersCount ?? 0}</div>
            <div class="kpi-sub">北京时间 YYYY-MM-DDTHH:MM</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">漏斗预期成交额</div>
            <div class="kpi-value">¥${Number(summary.totalPipelineExpectedValue || 0).toLocaleString()}</div>
            <div class="kpi-sub">∑(DealValue × p_succ)</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">首选推进策略</div>
            <div class="kpi-value">${escapeHtml(topAction || "maintain")}</div>
            <div class="kpi-sub">sales_action 四象限决策</div>
          </div>
        `;
      }

      const rem = crm.reminders || {};
      const remBox = document.getElementById("crmRemindersBox");
      if (remBox) {
        const items = (rem.due || []).concat(rem.upcoming || []);
        remBox.innerHTML = items.length
          ? items.map((it, idx) => {
              const rawName = it.displayName || it.personId || "";
              const enc = encodeURIComponent(rawName);
              const safeNameEnc = encArg(rawName);
              return `
                <div class="field-box" style="padding:8px 10px; margin-bottom:8px; border-left:3px solid ${it.isDue ? "var(--special)" : "var(--primary)"};">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong>${it.isDue ? "🔴 已到期" : "🟢 待跟进"} · ${escapeHtml(it.displayName || "")} (${escapeHtml(it.stage || "")})</strong>
                    <span style="font-size:12px; color:var(--text-muted);">${escapeHtml(it.followUpBeijing || "")} CST</span>
                  </div>
                  <div style="font-size:12px; color:var(--text-secondary); margin:4px 0;">${escapeHtml(it.note || "暂无备注")}${it.isDue ? ` · 已逾期 ${it.overdueMinutes || 0} 分钟` : ""}</div>
                  <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                    <button type="button" class="btn btn-primary btn-sm" onclick="openCallBrief(decodeURIComponent('${safeNameEnc}'))">📞 电话前速览</button>
                    <button class="btn btn-success btn-sm" onclick="crmCompleteReminder('${enc}')">✅ 标记完成</button>
                    <input id="crmRemResched_${idx}" class="input" style="max-width:170px; padding:4px 6px; font-size:12px;" value="${escapeHtml(String(it.followUpBeijing || "2026-11-16T14:00").slice(0, 16))}" />
                    <button class="btn btn-ghost btn-sm" onclick="crmRescheduleReminder('${enc}', 'crmRemResched_${idx}')">📅 改期</button>
                  </div>
                </div>
              `;
            }).join("")
          : `<div style="color:var(--text-muted);">当前暂无设定的跟进提醒。请在右侧登记客户并填写 YYYY-MM-DDTHH:MM 北京时间。</div>`;
      }

      const tbody = document.getElementById("crmRankingsTableBody");
      if (tbody) {
        const rows = crm.rankings || [];
        tbody.innerHTML = rows.length
          ? rows.map((r) => {
              const enc = encodeURIComponent(r.displayName || r.personId || "");
              return `
                <tr style="border-bottom:1px solid var(--border); cursor:pointer;" onclick="loadCrmContactAnalysis('${enc}')">
                  <td style="padding:8px; font-weight:700;">#${r.rank}</td>
                  <td style="padding:8px;"><strong>${escapeHtml(r.displayName || "")}</strong>${r.specialCare ? ' <span class="badge" style="background:var(--special-soft); color:var(--special);">特别关心</span>' : ""}</td>
                  <td style="padding:8px;">${escapeHtml(r.stage || "")}</td>
                  <td style="padding:8px;">${(Number(r.compositeScore || 0) * 100).toFixed(1)} / ${(Number(r.urgencyScore || 0) * 100).toFixed(1)}</td>
                  <td style="padding:8px;">${escapeHtml(r.signalLevel || "")} · ${escapeHtml(r.interactionPatternLabel || "")}</td>
                  <td style="padding:8px; font-family:monospace;">${Number(r.bq || 0).toFixed(2)} · ${Number(r.bsp || 0).toFixed(2)} · ${Number(r.bws || 0).toFixed(2)} · ${Number(r.pv || 0).toFixed(2)}</td>
                  <td style="padding:8px;"><span class="badge" style="${_actionBadgeColor(r.salesAction)} padding:2px 8px; border-radius:999px;">${escapeHtml(r.salesAction || "")}</span></td>
                  <td style="padding:8px;">¥${Number(r.expectedDealValue || 0).toLocaleString()}</td>
                  <td style="padding:8px; font-size:12px;">${escapeHtml(r.followUpBeijing || "-")}</td>
                </tr>
              `;
            }).join("")
          : `<tr><td colspan="9" style="padding:12px; color:var(--text-muted);">暂无 CRM 记录</td></tr>`;
      }

      if (!SALES_CRM_ANALYSIS && crm.focusAnalysis) {
        renderSalesCrmDetail(crm.focusAnalysis);
      } else if (SALES_CRM_ANALYSIS) {
        renderSalesCrmDetail(SALES_CRM_ANALYSIS);
      }
    }

    async function loadCrmContactAnalysis(encodedTarget) {
      if (!requireSalesCrm()) return;
      const target = encodedTarget ? decodeURIComponent(encodedTarget) : (document.getElementById("crmTargetInput")?.value || "").trim();
      if (!target) { showToast("请先输入或选择客户名"); return; }
      try {
        const { data } = await apiJson("/api/crm/analyze", {
          method: "POST",
          body: JSON.stringify({ target }),
        });
        data._forceFormSync = true;
        renderSalesCrmDetail(data);
        showToast(`已加载「${data.person?.displayName || target}」的 15 维分析与 Top 3 草稿`);
      } catch (err) {
        showToast(`加载分析失败: ${err.message || err}`);
      }
    }

    async function crmSyncNow() {
      if (!requireSalesCrm()) return;
      showToast("正在同步客户跟进资料…");
      try {
        const { data } = await apiJson("/api/crm/sync", { method: "POST", body: JSON.stringify({}) });
        SALES_CRM_ANALYSIS = null;
        await loadOverview(true);
        showToast(`同步完成：${data.syncedContacts ?? 0} 位客户 · 新增 ${data.ingestedMessages ?? 0} 条消息`);
      } catch (err) {
        showToast(`同步失败: ${err.message || err}`);
      }
    }

    async function crmEnrollOrUpdate(mode) {
      if (!requireSalesCrm()) return;
      const target = (document.getElementById("crmTargetInput")?.value || "").trim();
      const stage = document.getElementById("crmStageSelect")?.value || "跟进中";
      const followUp = (document.getElementById("crmFollowUpInput")?.value || "").trim() || null;
      const dealValueRaw = document.getElementById("crmDealValueInput")?.value;
      const note = document.getElementById("crmNoteInput")?.value || "";
      if (!target) { showToast("请填写客户姓名 / wxid"); return; }
      const endpoint = mode === "update" ? "/api/crm/update" : "/api/crm/enroll";
      try {
        const { data } = await apiJson(endpoint, {
          method: "POST",
          body: JSON.stringify({
            target,
            stage,
            note,
            follow_up: followUp,
            deal_value: dealValueRaw ? Number(dealValueRaw) : 0,
          }),
        });
        renderSalesCrmDetail(data);
        await loadOverview(true);
        showToast(`${mode === "update" ? "已更新" : "已纳入"}「${target}」 -> ${stage}`);
      } catch (err) {
        showToast(`保存失败: ${err.message || err}`);
      }
    }

    async function crmCompleteReminder(encodedTarget) {
      if (!requireSalesCrm()) return;
      const target = decodeURIComponent(encodedTarget);
      try {
        await apiJson("/api/crm/reminder-action", {
          method: "POST",
          body: JSON.stringify({ action: "complete", target }),
        });
        SALES_CRM_ANALYSIS = null;
        await loadOverview(true);
        showToast(`已完成「${target}」的跟进提醒`);
      } catch (err) {
        showToast(`操作失败: ${err.message || err}`);
      }
    }

    async function crmRescheduleReminder(encodedTarget, inputId) {
      if (!requireSalesCrm()) return;
      const target = decodeURIComponent(encodedTarget);
      const fu = (document.getElementById(inputId)?.value || "").trim();
      if (!fu) { showToast("请先输入北京时间 YYYY-MM-DDTHH:MM"); return; }
      try {
        await apiJson("/api/crm/reminder-action", {
          method: "POST",
          body: JSON.stringify({ action: "reschedule", target, follow_up: fu }),
        });
        SALES_CRM_ANALYSIS = null;
        await loadOverview(true);
        showToast(`已改期「${target}」至 ${fu} (CST)`);
      } catch (err) {
        showToast(`改期失败: ${err.message || err}`);
      }
    }

    async function crmRecalcFormulas() {
      if (!requireSalesCrm()) return;
      const target = (SALES_CRM_ANALYSIS?.person?.displayName || document.getElementById("crmTargetInput")?.value || "").trim();
      if (!target) { showToast("请先输入或选择客户名"); return; }
      const overrides = {};
      const fields = [
        ["crmOvPSucc", "p_succ"],
        ["crmOvSp", "sp"],
        ["crmOvPface", "pface"],
        ["crmOvBs", "bs"],
      ];
      for (const [elId, key] of fields) {
        const val = (document.getElementById(elId)?.value || "").trim();
        if (val !== "" && !Number.isNaN(Number(val))) overrides[key] = Number(val);
      }
      try {
        const { data } = await apiJson("/api/crm/analyze", {
          method: "POST",
          body: JSON.stringify({ target, formula_overrides: overrides }),
        });
        renderSalesCrmDetail(data);
        showToast(`公式重算完成：action=${data.formulas?.salesAction?.action || "maintain"}`);
      } catch (err) {
        showToast(`重算失败: ${err.message || err}`);
      }
    }

    async function crmAdoptDraft(encodedTarget, rankIndex, sendMode) {
      if (!requireSalesCrm()) return;
      const target = decodeURIComponent(encodedTarget);
      try {
        const { data } = await apiJson("/api/crm/adopt-draft", {
          method: "POST",
          body: JSON.stringify({ target, rank_index: rankIndex, send_mode: sendMode }),
        });
        await loadCrmContactAnalysis(encodedTarget);
        showToast(`已采纳 Top ${rankIndex} 草稿 (${data.sendMode || sendMode})`);
      } catch (err) {
        showToast(`草稿采纳失败: ${err.message || err}`);
      }
    }

    (function initAccessibleValidationAndImeSubmit() {
      const bindImeEnter = (id, onSubmit) => {
        const el = document.getElementById(id);
        if (!el) return;
        let lastCompEnd = null;
        el.addEventListener("compositionend", (e) => { lastCompEnd = e.timeStamp; });
        el.addEventListener("keydown", (e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            if (e.isComposing || e.keyCode === 229) return;
            if (lastCompEnd !== null && Math.abs(e.timeStamp - lastCompEnd) < 50) return;
            e.preventDefault();
            onSubmit();
          }
        });
      };
      bindImeEnter("previewIncoming", runReplyPreview);
      // Composing a draft stays separate from the explicit send action.

      const announcer = document.getElementById("formStatusAnnouncer");
      const syncFieldAria = (el, announce = false) => {
        if (!el?.matches?.("input, select, textarea")) return;
        const invalid = CSS.supports("selector(:user-invalid)") && el.matches(":user-invalid");
        el.setAttribute("aria-invalid", invalid ? "true" : "false");
        if (invalid && announce && announcer) {
          announcer.textContent = el.validationMessage || "输入格式需要检查";
        }
      };
      document.querySelectorAll("input, select, textarea").forEach((el) => syncFieldAria(el, false));
      document.addEventListener("blur", (e) => syncFieldAria(e.target, true), true);
      document.addEventListener("input", (e) => {
        if (e.target?.hasAttribute?.("aria-invalid")) syncFieldAria(e.target, false);
      });
      document.addEventListener("change", (e) => syncFieldAria(e.target, true), true);
    })();

    const compactConversation = matchMedia("(max-width: 900px)");
    const setConversationDensity = () => {
      document.getElementById("conversationThreads").open = !compactConversation.matches;
    };
    compactConversation.addEventListener("change", setConversationDensity);
    setConversationDensity();
    const moreActions = document.getElementById("topbarMore");
    const navMore = document.getElementById("navMore");
    const hostingPicker = document.querySelector("#hostingPanel .hosting-picker");
    const windowPickerBtnEl = document.getElementById("appWindowPickerBtn");
    const windowPickerPopEl = document.getElementById("windowPickerPopover");
    const docIngestDialogEl = document.getElementById("docIngestOverlay");
    if (windowPickerPopEl) {
      windowPickerPopEl.addEventListener("toggle", (e) => {
        const isOpen = e.newState === "open";
        if (windowPickerBtnEl) windowPickerBtnEl.setAttribute("aria-expanded", String(isOpen));
        if (!isOpen) WINDOW_BIND_STATE.lastClosedAt = Date.now();
      });
    }
    if (docIngestDialogEl) {
      docIngestDialogEl.addEventListener("close", () => {
        docIngestDialogEl.returnValue = "";
        DOC_INGEST_STATE.lastClosedAt = Date.now();
      });
      if (!("closedBy" in HTMLDialogElement.prototype)) {
        const outsideDialog = (e, dlg) => {
          const r = dlg.getBoundingClientRect();
          return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
        };
        let pressedOutsideDlg = false;
        docIngestDialogEl.addEventListener("pointerdown", (e) => {
          pressedOutsideDlg = docIngestDialogEl.open && outsideDialog(e, docIngestDialogEl);
        });
        docIngestDialogEl.addEventListener("pointerup", (e) => {
          if (pressedOutsideDlg && docIngestDialogEl.open && outsideDialog(e, docIngestDialogEl)) {
            hideDocIngestModal();
          }
          pressedOutsideDlg = false;
        });
      }
    }
    window.addEventListener("resize", () => {
      if (isWindowPickerOpen()) positionWindowPickerPopover();
    });
    document.addEventListener("click", event => {
      if (moreActions && (!moreActions.contains(event.target) || event.target.closest(".menu-item"))) moreActions.open = false;
      if (navMore && !navMore.contains(event.target)) navMore.open = false;
      if (hostingPicker && !hostingPicker.contains(event.target)) hostingPicker.open = false;
      if (!supportsPopoverApi() && isWindowPickerOpen() && windowPickerPopEl && windowPickerBtnEl) {
        if (!windowPickerPopEl.contains(event.target) && !windowPickerBtnEl.contains(event.target)) {
          hideWindowPickerPopover();
        }
      }
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        let closedAny = false;
        const now = Date.now();
        if (docIngestDialogEl?.open || (now - DOC_INGEST_STATE.lastClosedAt) < 120) {
          if (docIngestDialogEl?.open) hideDocIngestModal();
          closedAny = true;
        }
        if (isWindowPickerOpen() || (now - WINDOW_BIND_STATE.lastClosedAt) < 120) {
          if (isWindowPickerOpen()) hideWindowPickerPopover();
          closedAny = true;
        }
        if (document.getElementById("callBriefOverlay")?.classList.contains("visible")) {
          hideCallBriefModal();
          closedAny = true;
        }
        if (document.getElementById("mobileRemoteOverlay")?.classList.contains("visible")) {
          hideMobileRemoteOverlay();
          closedAny = true;
        }
        if (document.getElementById("settingsOverlay")?.classList.contains("visible")) {
          hideSettingsModal();
          closedAny = true;
        }
        if (moreActions?.open) {
          moreActions.open = false;
          moreActions.querySelector("summary").focus();
          closedAny = true;
        }
        if (navMore?.open) {
          navMore.open = false;
          navMore.querySelector("summary").focus();
          closedAny = true;
        }
        if (hostingPicker?.open) {
          hostingPicker.open = false;
          closedAny = true;
        }
        if (!closedAny) {
          if (WORKOS_STATE.lastEscAt && (now - WORKOS_STATE.lastEscAt) <= 420) {
            WORKOS_STATE.lastEscAt = 0;
            if (HOSTING_STATE?.hosting?.running) {
              applyHosting(false);
              showToast("⏸ 已通过双击 Esc 紧急暂停托管");
            } else {
              showToast("⏸ 双击 Esc 已确认：当前托管处于未开启状态");
            }
          } else {
            WORKOS_STATE.lastEscAt = now;
          }
        }
      }
    });
    document.getElementById("sendText").addEventListener("input", () => { draftRevision++; });
    syncSendModeLabel();
    renderBoundWindowButton();
    renderMultiWindowSchedulerState();
    renderSidebarWatchPanel();
    renderSalesCrmTab();
    loadOverview();
    loadWatchContacts();
    loadWorkosHarness(false);
    loadPermissions();
    loadBackgroundObservation();
    setInterval(loadBackgroundObservation, 5000);
    setInterval(() => {
      if (document.hidden) return;
      const ae = document.activeElement;
      if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT")) return;
      if (document.getElementById("hostingPicker")?.open) return;
      if (document.getElementById("settingsOverlay")?.classList.contains("visible")) return;
      if (document.getElementById("callBriefOverlay")?.classList.contains("visible")) return;
      loadOverview(false);
    }, 6000);
    document.addEventListener("visibilitychange", loadBackgroundObservation);
    updateSaveDraftButton();
    window.addEventListener("hashchange", resumeSavedDraft);
    resumeSavedDraft();
    const linkedTab = location.hash.slice(1);
    if (["care", "moments", "monitor", "stats", "articles", "uiprotocol", "knowledge", "soul", "salescrm", "omni", "models", "open"].includes(linkedTab)) {
      switchTab(linkedTab);
    }

    let OMNI_STATE = null;

    function omniRenderCards(data) {
      const grid = document.getElementById("omniCardsGrid");
      const sysStrip = document.getElementById("omniSysAuthStrip");
      const stackList = document.getElementById("omniOpenSourceList");
      const badgeEl = document.getElementById("omniStatusBadge");
      if (!grid) return;
      const channels = data?.channels || [];
      const selected = document.getElementById("omniChannelSelect")?.value || "feishu";

      if (badgeEl) {
        const ready = Number(data?.readyCount ?? 0);
        const todo = Number(data?.actionNeededCount ?? 0);
        const tools = data?.tools || {};
        badgeEl.innerHTML = `已就绪 <strong>${ready}/${channels.length || 6}</strong> 渠道 · 待扫码/安装 <strong>${todo}</strong> 项（依次点击标橙按钮即可完成授权） · 原生RPA:${tools.nativeBinaryExists ? "✓" : "✗"} · ego网页:${tools.egoBrowserAvailable ? "✓" : "✗"} · xhs防封:${tools.xhsPublisherAvailable ? "✓" : "✗"}`;
      }

      if (sysStrip) {
        const sysAuth = data?.systemAuth || {};
        const mac = sysAuth.macosPermissions || {};
        const studio = sysAuth.studioAuth || {};
        sysStrip.innerHTML = `
          <div class="omni-sys-item ${mac.ready ? "is-ready" : "is-todo"}">
            <div>
              <div style="font-weight:700;">1 · 系统辅助功能与录屏权限</div>
              <div style="color:var(--text-secondary); margin-top:2px;">${escapeHtml(mac.label || "检测中")}</div>
            </div>
            ${mac.ready
              ? `<span class="pill ok">✅ 已授权</span>`
              : `<button type="button" class="btn-solid sm" onclick="window.PERM_MODAL_DISMISSED=false; loadPermissions(true)">⚙️ 点击去系统设置勾选</button>`}
          </div>
          <div class="omni-sys-item ${studio.ready ? "is-ready" : "is-todo"}">
            <div>
              <div style="font-weight:700;">2 · 全渠道工作台操控授权</div>
              <div style="color:var(--text-secondary); margin-top:2px;">${escapeHtml(studio.label || "检测中")}</div>
            </div>
            ${studio.ready
              ? `<span class="pill ok">✅ 已授权</span>`
              : `<button type="button" class="btn-solid sm" onclick="grantAllAuth().then(() => loadOmniChannels(false))">🔑 一键点击授权</button>`}
          </div>
        `;
      }

      grid.innerHTML = channels.map((c) => {
        const guide = c.authGuide || {};
        const status = guide.status || (c.desktopRunning ? "ready" : "need_launch");
        const pillCls = status === "ready" ? "ok" : (status === "need_install" ? "accent" : "warn");
        const isSel = c.channelId === selected;
        const metaParts = [];
        if (c.desktopRunning) metaParts.push(`PID ${escapeHtml(c.pid || "-")} · 窗口 ${c.desktopWindowCount || 0}`);
        else if (c.installed) metaParts.push("客户端已安装（待启动）");
        else if (c.egoBrowserAvailable) metaParts.push("支持 ego 网页扫码");
        if (c.supportsVoiceCall) metaParts.push("语音对话");

        const actionBtns = (guide.actions || []).map((act) => {
          const cls = act.style === "solid" ? "btn-solid sm" : "btn-outline sm";
          return `<button type="button" class="${cls}" onclick="event.stopPropagation(); omniRunAuthAction('${escapeHtml(c.channelId)}', '${escapeHtml(act.actionType)}', '${escapeHtml(act.targetView || "home")}')">${escapeHtml(act.label)}</button>`;
        }).join("");

        return `
          <div class="omni-ch-card status-${escapeHtml(status)} ${isSel ? "is-selected" : ""}" onclick="omniSelectChannel('${escapeHtml(c.channelId)}')">
            <div>
              <div class="omni-ch-head">
                <div>
                  <div style="font-size:11.5px; color:var(--text-muted); font-weight:600;">优先级 #${c.priority}</div>
                  <div style="font-size:14px; font-weight:700; margin-top:2px;">${escapeHtml(c.label)}</div>
                </div>
                <span class="pill ${pillCls}">${escapeHtml(guide.badgeText || "待核验")}</span>
              </div>
              <div class="omni-ch-summary" style="margin-top:8px;">${escapeHtml(guide.summary || "")}</div>
              <div style="font-size:11.5px; color:var(--text-muted); margin-top:6px;">${metaParts.join(" · ") || "点击检测状态"}</div>
            </div>
            <div class="omni-ch-actions">${actionBtns}</div>
          </div>
        `;
      }).join("");

      if (stackList) {
        const activeCh = channels.find((c) => c.channelId === selected);
        const items = [
          ...((activeCh && activeCh.openSourceStacks) || []),
          ...((data && data.globalOpenSourceFrameworks) || []),
        ];
        stackList.innerHTML = items.map((s) => `
          <div style="padding:7px 9px; border:1px solid var(--border); border-radius:8px; margin-bottom:6px; background:var(--surface-soft);">
            <strong>${escapeHtml(s.repo)}</strong> <span style="color:var(--accent); font-size:11.5px;">[${escapeHtml(s.role)}]</span>
            <div style="color:var(--text-muted); font-size:12px; margin-top:2px;">${escapeHtml(s.note)}</div>
          </div>
        `).join("");
      }
    }

    function omniSelectChannel(cid) {
      const sel = document.getElementById("omniChannelSelect");
      if (sel && cid) sel.value = cid;
      if (OMNI_STATE) omniRenderCards(OMNI_STATE);
    }

    function omniShowResult(obj) {
      const box = document.getElementById("omniActionResultBox");
      if (!box) return;
      const guide = obj?.authGuide || {};
      const ok = obj?.ok !== false;
      const headline = obj?.message
        || guide.summary
        || (obj?.enrolledCount != null ? `已识别高意向线索 ${obj.hotOrWarmCount ?? 0} 条，成功纳入 CRM ${obj.enrolledCount} 条。` : "")
        || (obj?.dryRun ? `Dry-Run 合规演练完成（未实发）${obj?.text ? "：" + obj.text : ""}` : "")
        || (ok ? "操作完成" : (obj?.error || "操作未完成"));

      const bullets = [];
      if (guide.badgeText) bullets.push(`<div>当前状态：<strong>${escapeHtml(guide.badgeText)}</strong></div>`);
      if (obj?.web?.url) bullets.push(`<div>网页地址：<code>${escapeHtml(obj.web.url)}</code>（${obj.web.loggedIn ? "已登录" : "待扫码登录"}）</div>`);
      if (obj?.browser?.url) bullets.push(`<div>已弹出登录页：<code>${escapeHtml(obj.browser.url)}</code></div>`);
      if (obj?.downloadUrl) bullets.push(`<div>官方下载页：<code>${escapeHtml(obj.downloadUrl)}</code></div>`);
      if (Array.isArray(obj?.sessions) && obj.sessions.length) {
        bullets.push(`<div>检测到 <strong>${obj.sessions.length}</strong> 条会话/互动：${obj.sessions.slice(0, 5).map((s) => escapeHtml(s.title || s.text || "")).join("、")}</div>`);
      }
      if (Array.isArray(obj?.messages) && obj.messages.length) {
        bullets.push(`<div>读取到 <strong>${obj.messages.length}</strong> 条最新消息（当前对话：${escapeHtml(obj.currentChatTitle || "-")}）</div>`);
      }
      if (obj?.error && headline !== obj.error) {
        bullets.push(`<div style="color:var(--danger);">提示：${escapeHtml(obj.error)}</div>`);
      }

      box.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:6px;">
          <span class="pill ${ok ? "ok" : "warn"}">${ok ? "✅ 执行结果" : "⚠️ 需处理"}</span>
          ${obj?.channel ? `<span style="font-size:11.5px; color:var(--text-muted);">渠道：${escapeHtml(obj.channel)}</span>` : ""}
        </div>
        <div style="font-weight:600; color:var(--text); line-height:1.5;">${escapeHtml(headline)}</div>
        ${bullets.length ? `<div style="margin-top:6px; font-size:12px; display:flex; flex-direction:column; gap:3px;">${bullets.join("")}</div>` : ""}
        <details style="margin-top:8px;">
          <summary style="cursor:pointer; font-size:11.5px; color:var(--text-muted);">查看底层调试 JSON</summary>
          <pre style="margin:6px 0 0; white-space:pre-wrap; word-break:break-word; font-family:ui-monospace,Menlo,monospace; font-size:11px;">${escapeHtml(JSON.stringify(obj, null, 2))}</pre>
        </details>
      `;
    }

    async function omniRunAuthAction(channelId, actionType, targetView) {
      omniSelectChannel(channelId);
      if (actionType === "verify") {
        await omniProbeChannel(false);
        return;
      }
      if (actionType === "open_config") {
        const det = document.getElementById("omniCredDetails");
        if (det) {
          det.open = true;
          det.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
      showToast(`正在为 ${channelId} 准备授权/扫码页面...`);
      try {
        const { data } = await apiJson("/api/omni/open-auth", {
          method: "POST",
          body: JSON.stringify({
            channel: channelId,
            action_type: actionType || "auto",
            target_view: targetView || "home",
            dry_run: false,
          }),
        });
        omniShowResult(data);
        showToast(data?.message || (data?.ok ? "已弹出授权/扫码窗口" : "请检查提示"));
        await loadOmniChannels(false);
      } catch (err) {
        showToast("打开授权窗口失败：" + (err?.message || err));
      }
    }

    async function loadOmniChannels(probeLive) {
      try {
        if (probeLive) showToast("正在逐一核验 6 端登录与扫码状态，请稍候...");
        const { data } = await apiJson(`/api/omni/channels?probe=${probeLive ? "1" : "0"}`);
        OMNI_STATE = data;
        omniRenderCards(data);
      } catch (err) {
        showToast("加载全渠道矩阵失败：" + (err?.message || err));
      }
    }

    async function omniProbeChannel(launchIfNeeded) {
      const channel = document.getElementById("omniChannelSelect")?.value || "feishu";
      showToast(`正在核验 ${channel} 登录状态...`);
      const { data } = await apiJson("/api/omni/probe", {
        method: "POST",
        body: JSON.stringify({ channel, launch_if_needed: Boolean(launchIfNeeded), include_web: true }),
      });
      omniShowResult(data);
      await loadOmniChannels(false);
    }

    async function omniInspectSessions(kind) {
      const channel = document.getElementById("omniChannelSelect")?.value || "feishu";
      const target = encodeURIComponent(document.getElementById("omniTargetInput")?.value || "");
      const query = encodeURIComponent(document.getElementById("omniQueryInput")?.value || "");
      const url = kind === "messages"
        ? `/api/omni/messages?channel=${encodeURIComponent(channel)}&target=${target}&limit=20`
        : `/api/omni/sessions?channel=${encodeURIComponent(channel)}&query=${query}&limit=20`;
      const { data } = await apiJson(url);
      omniShowResult(data);
    }

    async function omniExtractLeads(syncCrm) {
      const channel = document.getElementById("omniChannelSelect")?.value || "feishu";
      const target = document.getElementById("omniTargetInput")?.value || "";
      const query = document.getElementById("omniQueryInput")?.value || "";
      const { data } = await apiJson("/api/omni/leads", {
        method: "POST",
        body: JSON.stringify({ channel, target, query, sync_crm: Boolean(syncCrm) }),
      });
      omniShowResult(data);
      if (data?.enrolledCount > 0) {
        showToast(`已将 ${data.enrolledCount} 条高意向线索纳入 SalesCRM`);
        loadOverview(false);
      }
    }

    async function omniSendReply(dryRun) {
      const channel = document.getElementById("omniChannelSelect")?.value || "feishu";
      const mode = document.getElementById("omniModeSelect")?.value || "auto";
      const target = document.getElementById("omniTargetInput")?.value || "";
      const text = (document.getElementById("omniReplyInput")?.value || "").trim();
      if (!text) {
        showToast("请输入要演练或发送的内容");
        return;
      }
      const { data } = await apiJson("/api/omni/send", {
        method: "POST",
        body: JSON.stringify({ channel, target, text, mode, dry_run: Boolean(dryRun), confirm_send: !dryRun }),
      });
      omniShowResult(data);
      showToast(dryRun ? "Dry-Run 合规演练完成" : (data?.sent ? "已发送" : "发送未执行"));
    }

    async function omniSaveConfig() {
      const updates = {
        feishu: {},
        dingtalk: {},
      };
      const fw = document.getElementById("omniFeishuWebhook")?.value?.trim();
      const fs = document.getElementById("omniFeishuSecret")?.value?.trim();
      const fa = document.getElementById("omniFeishuAppId")?.value?.trim();
      const fk = document.getElementById("omniFeishuAppSecret")?.value?.trim();
      const dw = document.getElementById("omniDingWebhook")?.value?.trim();
      const ds = document.getElementById("omniDingSecret")?.value?.trim();
      if (fw) updates.feishu.webhook_url = fw;
      if (fs) updates.feishu.webhook_secret = fs;
      if (fa) updates.feishu.app_id = fa;
      if (fk) updates.feishu.app_secret = fk;
      if (dw) updates.dingtalk.webhook_url = dw;
      if (ds) updates.dingtalk.webhook_secret = ds;
      const { data } = await apiJson("/api/omni/config", {
        method: "POST",
        body: JSON.stringify({ updates }),
      });
      omniShowResult(data);
      showToast("已保存开源连接器配置");
      await loadOmniChannels(false);
    }

    async function omniFinishBrowser() {
      const { data } = await apiJson("/api/omni/finish-browser", { method: "POST", body: JSON.stringify({}) });
      omniShowResult(data);
      showToast("已释放 ego-browser 代理受控标签页");
    }

    let DY_FUNNEL_ARMED_ID = "";
    let WX_QUICK_ARMED = false;

    function renderDouyinFunnel(data) {
      const counts = data?.counts || {};
      const quota = data?.quota || {};
      const cfg = data?.config || {};
      const strip = document.getElementById("dyFunnelStatsStrip");
      if (strip) {
        const cards = [
          ["总线索", counts.total ?? 0],
          ["待留微信号", counts.awaitingWechat ?? 0],
          ["已提取微信号", counts.wechatCaptured ?? 0],
          ["已发好友申请", counts.friendRequested ?? 0],
          ["今日加好友余量", `${quota.remaining ?? 0}/${quota.dailyLimit ?? 15}`],
        ];
        strip.innerHTML = cards.map(([lbl, val]) => `
          <div style="border:1px solid var(--border); border-radius:10px; padding:8px 10px; background:var(--surface-soft);">
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(lbl)}</div>
            <div style="font-size:16px; font-weight:700; margin-top:2px;">${escapeHtml(String(val))}</div>
          </div>
        `).join("");
      }
      const rEl = document.getElementById("dyCfgReplyTpl");
      const gEl = document.getElementById("dyCfgGreetingTpl");
      const pEl = document.getElementById("dyCfgRemarkPrefix");
      const lEl = document.getElementById("dyCfgDailyLimit");
      if (rEl && !rEl.matches(":focus")) rEl.value = cfg.replyTemplate || "";
      if (gEl && !gEl.matches(":focus")) gEl.value = cfg.wechatGreetingTemplate || "";
      if (pEl && !pEl.matches(":focus")) pEl.value = cfg.wechatRemarkPrefix || "[抖音]";
      if (lEl && !lEl.matches(":focus")) lEl.value = String(cfg.dailyAddLimit ?? 15);

      const box = document.getElementById("dyFunnelLeadsBox");
      if (!box) return;
      const leads = Array.isArray(data?.leads) ? data.leads : [];
      if (!leads.length) {
        box.innerHTML = `<div style="color:var(--text-muted);">暂无抖音引流线索。可点击「扫描抖音私信并提取微信号」或先在抖音收到用户消息。</div>`;
        return;
      }
      box.innerHTML = leads.map((l) => {
        const wxBadge = l.wechatAccount
          ? `<span class="pill" style="background:rgba(16,185,129,0.12); color:#047857;">微信号: ${escapeHtml(l.wechatAccount)}</span>`
          : `<span class="pill">未留微信号</span>`;
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; padding:8px 4px; border-bottom:1px solid var(--border); flex-wrap:wrap;">
            <div style="min-width:220px; flex:1;">
              <div style="font-weight:600;">${escapeHtml(l.douyinUser || "抖音访客")} ${wxBadge} <span class="pill">${escapeHtml(l.status || "new_message")}</span></div>
              <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">${escapeHtml(l.lastIncoming || "")}</div>
            </div>
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              <button type="button" class="btn-outline sm" onclick="douyinFunnelSuggestReply('${escapeHtml(l.douyinUser || "")}')">💬 生成引导回复</button>
              ${l.wechatAccount ? `
                <button type="button" class="btn-outline sm" onclick="douyinFunnelAddWechat('${escapeHtml(l.leadId)}', false, true)">🔍 微信查号演练</button>
                <button type="button" class="btn-outline sm" style="color:var(--danger); border-color:rgba(220,38,38,0.35);" onclick="douyinFunnelAddWechat('${escapeHtml(l.leadId)}', true, false, this)">➕ 发好友申请</button>
              ` : ""}
            </div>
          </div>
        `;
      }).join("");
    }

    async function loadDouyinFunnel() {
      try {
        const { data } = await apiJson("/api/douyin-funnel/overview");
        if (data?.ok) renderDouyinFunnel(data);
      } catch (_) {}
    }

    async function douyinFunnelSaveConfig() {
      const updates = {
        replyTemplate: document.getElementById("dyCfgReplyTpl")?.value?.trim() || "",
        wechatGreetingTemplate: document.getElementById("dyCfgGreetingTpl")?.value?.trim() || "",
        wechatRemarkPrefix: document.getElementById("dyCfgRemarkPrefix")?.value?.trim() || "[抖音]",
        dailyAddLimit: Number(document.getElementById("dyCfgDailyLimit")?.value || 15),
      };
      const { data } = await apiJson("/api/douyin-funnel/config", {
        method: "POST",
        body: JSON.stringify({ updates }),
      });
      omniShowResult(data);
      showToast("已保存抖音引流与微信加好友配置");
      await loadDouyinFunnel();
    }

    async function douyinFunnelRunCycle(autoReply, autoAddWechat, dryRun) {
      showToast("正在读取抖音私信并提取微信号...");
      const { data } = await apiJson("/api/douyin-funnel/run-cycle", {
        method: "POST",
        body: JSON.stringify({
          auto_reply: Boolean(autoReply),
          auto_add_wechat: Boolean(autoAddWechat),
          dry_run: Boolean(dryRun),
          confirm_send: !dryRun,
        }),
      });
      omniShowResult(data);
      if (data?.overview) renderDouyinFunnel(data.overview);
      if (data?.loginRequired) showToast("请先在抖音窗口扫码登录后再扫描");
      else if (data?.ok) showToast(`已扫描 ${data.messageCount || 0} 条消息，提取 ${data.ingest?.capturedCount || 0} 个微信号`);
    }

    async function douyinFunnelSuggestReply(douyinUser) {
      const { data } = await apiJson("/api/douyin-funnel/suggest-reply", {
        method: "POST",
        body: JSON.stringify({ douyin_user: douyinUser, surface: "dm" }),
      });
      omniShowResult(data);
      const replyBox = document.getElementById("omniReplyInput");
      const chSel = document.getElementById("omniChannelSelect");
      const tgtIn = document.getElementById("omniTargetInput");
      if (chSel) chSel.value = "douyin";
      if (tgtIn) tgtIn.value = douyinUser;
      if (replyBox && data?.text) replyBox.value = data.text;
      showToast("已生成抖音合规引流话术到上方输入框");
    }

    async function douyinFunnelAddWechat(leadId, liveSend, probeUi, btnEl) {
      if (liveSend && DY_FUNNEL_ARMED_ID !== leadId) {
        DY_FUNNEL_ARMED_ID = leadId;
        if (btnEl) btnEl.textContent = "⚠️ 再次点击确认实发";
        showToast("再次点击按钮将真实发送微信好友申请");
        setTimeout(() => {
          if (DY_FUNNEL_ARMED_ID === leadId) {
            DY_FUNNEL_ARMED_ID = "";
            if (btnEl) btnEl.textContent = "➕ 发好友申请";
          }
        }, 6000);
        return;
      }
      DY_FUNNEL_ARMED_ID = "";
      const { data } = await apiJson("/api/douyin-funnel/add-wechat", {
        method: "POST",
        body: JSON.stringify({
          lead: leadId,
          dry_run: !liveSend,
          probe_ui: Boolean(probeUi),
          confirm_send: Boolean(liveSend),
        }),
      });
      omniShowResult(data);
      showToast(data?.sent ? "已发送微信好友申请" : `微信查号结果：${data?.lookupStatus || data?.status || "完成"}`);
      await loadDouyinFunnel();
    }

    async function wechatQuickAddFriend(liveSend, probeUi) {
      const account = (document.getElementById("wxQuickAccount")?.value || "").trim();
      if (!account) {
        showToast("请输入要查找或添加的微信号 / 手机号");
        return;
      }
      const btn = document.getElementById("wxQuickConfirmBtn");
      if (liveSend && !WX_QUICK_ARMED) {
        WX_QUICK_ARMED = true;
        if (btn) btn.textContent = "⚠️ 再次点击确认实发";
        showToast("为防误触，请在 6 秒内再次点击确认发送好友申请");
        setTimeout(() => {
          WX_QUICK_ARMED = false;
          if (btn) btn.textContent = "➕ 确认发送好友申请";
        }, 6000);
        return;
      }
      WX_QUICK_ARMED = false;
      if (btn) btn.textContent = "➕ 确认发送好友申请";
      const greeting = (document.getElementById("wxQuickGreeting")?.value || "").trim();
      const remark = (document.getElementById("wxQuickRemark")?.value || "").trim();
      const { data } = await apiJson("/api/wechat/add-friend", {
        method: "POST",
        body: JSON.stringify({
          account,
          greeting,
          remark,
          source_channel: "douyin",
          dry_run: !liveSend,
          probe_ui: Boolean(probeUi),
          confirm_send: Boolean(liveSend),
        }),
      });
      omniShowResult(data);
      showToast(data?.sent ? "已发送微信好友申请" : `查号完成：${data?.lookupStatus || data?.status || "OK"}`);
    }

    // ------------------------------------------------------------------
    // Universal App-Use & Any-Agent SOP Studio (#tab-appuse)
    // ------------------------------------------------------------------
    let APPUSE_APPS = [];
    let APPUSE_AGENTS = [];
    let APPUSE_WORKFLOWS = [];
    let APPUSE_PIPELINES = [];
    let APPUSE_RUNS = [];
    let APPUSE_STATE_GRAPH = {};
    let APPUSE_CONCURRENCY = {};
    let APPUSE_CURRENT_WF = null;
    let APPUSE_CATEGORY = "all";
    let APPUSE_RUNNING_ONLY = false;
    let APPUSE_LIVE_ARMED = false;
    let APPUSE_LIVE_TIMER = null;
    let APPUSE_EXPLORE_ARMED = false;
    let APPUSE_EXPLORE_TIMER = null;
    let APPUSE_PIPE_ARMED = false;
    let APPUSE_PIPE_TIMER = null;
    let APPUSE_REC_POLL = null;

    function appuseResetLiveArm() {
      APPUSE_LIVE_ARMED = false;
      clearTimeout(APPUSE_LIVE_TIMER);
      const btn = document.getElementById("appuseLiveRunBtn");
      if (btn) btn.textContent = "▶️ 实机执行流程";
      APPUSE_EXPLORE_ARMED = false;
      clearTimeout(APPUSE_EXPLORE_TIMER);
      const ebtn = document.getElementById("appuseExploreLiveBtn");
      if (ebtn) ebtn.textContent = "🚀 实机自主探索";
      APPUSE_PIPE_ARMED = false;
      clearTimeout(APPUSE_PIPE_TIMER);
      const pbtn = document.getElementById("appusePipelineLiveBtn");
      if (pbtn) pbtn.textContent = "▶️ 实机联跑流水线";
    }

    function setAppUseCategory(cat, btnEl) {
      APPUSE_CATEGORY = cat || "all";
      ["appuseFilterAll", "appuseFilterAgent", "appuseFilterProd"].forEach((id) => {
        document.getElementById(id)?.classList.remove("active");
      });
      if (btnEl) btnEl.classList.add("active");
      renderAppUseApps();
    }

    function toggleAppUseRunningOnly(btnEl) {
      APPUSE_RUNNING_ONLY = !APPUSE_RUNNING_ONLY;
      btnEl?.classList.toggle("active", APPUSE_RUNNING_ONLY);
      renderAppUseApps();
    }

    function renderAppUseApps() {
      const filtered = APPUSE_APPS.filter((a) => {
        if (APPUSE_RUNNING_ONLY && !a.running) return false;
        if (APPUSE_CATEGORY !== "all" && a.category !== APPUSE_CATEGORY) return false;
        return true;
      });
      const sel = document.getElementById("appuseAppSelect");
      const prevVal = sel ? sel.value : "";
      if (sel) {
        sel.innerHTML = filtered.length
          ? filtered.map((a) => {
              const badge = a.isAgentApp ? "[🤖 Agent] " : "";
              const run = a.running ? "🟢 " : "";
              const val = encodeURIComponent(a.bundleID || a.appPath || a.name || "");
              return `<option value="${val}">${escapeHtml(run + badge + a.name + " (" + (a.bundleID || a.installSource || "app") + ")")}</option>`;
            }).join("")
          : `<option value="">未匹配到应用</option>`;
        if (prevVal && Array.from(sel.options).some((o) => o.value === prevVal)) {
          sel.value = prevVal;
        }
      }
      const grid = document.getElementById("appuseAppGrid");
      if (!grid) return;
      if (!filtered.length) {
        grid.innerHTML = `<div style="font-size:12.5px; color:var(--text-muted);">当前筛选下暂无应用。</div>`;
        return;
      }
      const curSel = sel ? decodeURIComponent(sel.value || "") : "";
      grid.innerHTML = filtered.slice(0, 36).map((a) => {
        const key = a.bundleID || a.appPath || a.name || "";
        const isSel = curSel && key === curSel;
        return `
          <button type="button" class="appuse-app-card ${isSel ? "is-selected" : ""}" onclick="selectAppUseCard('${encArg(key)}')">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
              <strong style="font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(a.name)}</strong>
              <span class="pill ${a.running ? "ok" : ""}">${a.isAgentApp ? "🤖 Agent" : (a.running ? "运行中" : "已安装")}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(a.bundleID || a.appPath)}</div>
          </button>
        `;
      }).join("");
    }

    function selectAppUseCard(encodedKey) {
      const sel = document.getElementById("appuseAppSelect");
      if (sel) sel.value = encodedKey;
      renderAppUseApps();
      renderAppUseRiskBadge();
    }

    function onAppUseSelectChange() {
      renderAppUseApps();
      renderAppUseRiskBadge();
    }

    function getSelectedAppUseTarget() {
      const sel = document.getElementById("appuseAppSelect");
      const key = sel ? decodeURIComponent(sel.value || "") : "";
      const found = APPUSE_APPS.find((a) => (a.bundleID || a.appPath || a.name || "") === key);
      return found || { bundleID: key, name: key, appPath: "" };
    }

    function renderAppUseAgents() {
      const sel = document.getElementById("appuseAgentSelect");
      if (!sel) return;
      const prev = sel.value;
      sel.innerHTML = APPUSE_AGENTS.map((ag) => {
        const tag = ag.kind === "cli_agent" ? "[CLI Agent] " : (ag.kind === "local_heuristic" ? "[离线引擎] " : "[模型/路由] ");
        const avail = ag.available ? "" : " (未就绪)";
        return `<option value="${escapeHtml(ag.id)}">${escapeHtml(tag + ag.label + avail)}</option>`;
      }).join("");
      if (prev && Array.from(sel.options).some((o) => o.value === prev)) {
        sel.value = prev;
      } else {
        const def = APPUSE_AGENTS.find((a) => a.available && a.recommended) || APPUSE_AGENTS.find((a) => a.available);
        if (def) sel.value = def.id;
      }
    }

    const WFAGENT_APP_LABELS = {
      "com.bytedance.macos.feishu": "飞书",
      "com.tencent.xinWeChat": "微信",
      "com.tencent.WeWorkMac": "企业微信",
      "com.alibaba.DingTalkMac": "钉钉",
      "com.ss.iphone.ugc.Aweme": "抖音",
      "com.xingin.xhs": "小红书",
      "com.apple.calculator": "计算器",
      "com.apple.TextEdit": "文本编辑",
      "com.apple.Notes": "备忘录",
      "com.apple.Safari": "Safari 浏览器",
    };

    const WFAGENT_ACTION_LABELS = {
      switch_app: "切换应用",
      activate_app: "打开应用",
      inspect_ui: "读取界面",
      wait_and_read: "等待回读",
      llm_extract: "提取信息",
      llm_draft: "生成话术",
      branch_if: "条件判断",
      pause_for_human: "✋ 人工确认",
      builtin_tool: "内置动作",
      assert_check: "✅ 结果验收",
      focus_and_type: "输入文字",
      press_shortcut: "快捷键",
      click: "点击按钮",
    };

    const WFAGENT_RISK_LABELS = {
      high_risk_social: "高风控社交·已护栏",
      moderate_agent_or_web: "中风控·网页/AI",
      safe_native: "低风险原生应用",
    };

    const WFAGENT_PHASE_LABELS = {
      clarifying: "待补充细节",
      ready_to_build: "待确认生成",
      built_and_debugged: "已完成调试",
    };

    const WFAGENT_STATUS_LABELS = {
      shadow_verified: "影子验证通过",
      verified: "实机验证通过",
      dry_run_passed: "静态预检通过",
      effect_ok: "实机结果已验收",
      shadow_only: "影子安全预览",
      dry_run_only: "静态预检",
      shadow: "影子模式",
      live: "实机模式",
      dry_run: "预检模式",
    };

    function wfagentFormatAppLabel(bid) {
      return WFAGENT_APP_LABELS[bid] || bid;
    }

    function wfagentFormatStepMeta(s) {
      if (!s || typeof s !== "object") return "";
      const p = s.params && typeof s.params === "object" ? s.params : {};
      if (s.action === "builtin_tool") {
        if (s.tool === "wechat_add_friend" && p.remark) return `备注：${p.remark}`;
        if (s.tool === "crm_enroll") {
          const tags = Array.isArray(p.tags) ? p.tags.join("/") : "";
          return `阶段：${p.stage || "-"}${tags ? ` · 标签：${tags}` : ""}`;
        }
        return s.tool ? `工具：${s.tool}` : "";
      }
      if (s.action === "branch_if") {
        return `判断：${s.var || ""} ${s.operator || ""}${s.value ? " " + s.value : ""}`.trim();
      }
      if (s.action === "assert_check") {
        return `验收包含：${s.expected || "非空"}`;
      }
      if (s.action === "press_shortcut") {
        return s.combo ? `快捷键：${s.combo}` : (s.sequence ? `按键：${s.sequence}` : "");
      }
      return "";
    }

    function wfagentPickEditWorkflow(wid) {
      if (!wid) return;
      loadSavedAppUseWorkflow(encodeURIComponent(wid));
    }

    function renderAppUseWorkflow(wf) {
      APPUSE_CURRENT_WF = wf || null;
      appuseResetLiveArm();
      const metaEl = document.getElementById("appuseCurrentWfMeta");
      const stepsEl = document.getElementById("appuseStepsBox");
      const sopEl = document.getElementById("appuseSopPreview");
      const paramsEl = document.getElementById("appuseRunParamsInput");
      const editPillEl = document.getElementById("wfagentEditTargetPill");
      const editSelEl = document.getElementById("wfagentEditWorkflowSelect");
      if (!wf) {
        if (metaEl) metaEl.textContent = "等待生成或选择流程";
        if (stepsEl) stepsEl.innerHTML = `<div style="font-size:12px; color:var(--text-muted);">暂无步骤</div>`;
        if (sopEl) sopEl.textContent = "等待 Agent 生成 SOP…";
        if (editPillEl) { editPillEl.textContent = "尚未载入工作流"; editPillEl.className = "pill"; }
        if (editSelEl) editSelEl.value = "";
        return;
      }
      if (editPillEl) {
        editPillEl.textContent = `当前修改对象：${wf.name || wf.id} (v${wf.version || 1})`;
        editPillEl.className = "pill ok";
      }
      if (editSelEl && Array.from(editSelEl.options).some((o) => o.value === wf.id)) {
        editSelEl.value = wf.id;
      }
      const tapp = wf.targetApp || {};
      const bag = wf.builderAgent || {};
      if (metaEl) {
        metaEl.textContent = `${wf.name || ""} (v${wf.version || 1}) · 目标 ${tapp.name || ""} · Agent ${bag.label || bag.agentId || ""}${bag.usedFallback ? "（已触发本地回退）" : ""}`;
      }
      const archBadge = document.getElementById("appuseArchetypeBadge");
      if (archBadge) {
        const ar = wf.archetype || {};
        archBadge.textContent = ar.id ? `Archetype：${ar.label || ar.id}` : "Archetype：通用桌面应用";
        archBadge.className = "pill " + (ar.id ? "ok" : "");
      }
      const readyBadge = document.getElementById("appuseReadinessBadge");
      if (readyBadge) {
        const rd = wf.readiness || {};
        const vMap = { verified: "✅ 已实机验证", shadow_verified: "🛡️ 影子验证通过", dry_run_only: "🧪 仅静态演练" };
        const vTxt = wf.verificationStatus && vMap[wf.verificationStatus] ? ` · ${vMap[wf.verificationStatus]}` : "";
        readyBadge.textContent = (rd.score !== undefined ? `就绪度：${rd.grade || "-"} (${rd.score}分)` : "就绪度：已加载") + vTxt;
        readyBadge.className = "pill " + (wf.verificationStatus === "verified" || Number(rd.score || 0) >= 70 ? "ok" : "");
      }
      if (sopEl) sopEl.textContent = wf.sopMarkdown || "";
      if (paramsEl) {
        const defParams = {};
        (wf.parameters || []).forEach((p) => { if (p && p.name) defParams[p.name] = p.defaultValue ?? ""; });
        paramsEl.value = JSON.stringify(defParams);
      }
      if (stepsEl) {
        const steps = wf.steps || [];
        stepsEl.innerHTML = steps.map((s) => {
          const actionLabel = WFAGENT_ACTION_LABELS[s.action] || s.action;
          const stepMeta = wfagentFormatStepMeta(s);
          const accentStyle = s.action === "pause_for_human"
            ? "border-left:3px solid #f59e0b;"
            : (s.action === "assert_check" ? "border-left:3px solid #10b981;" : "");
          return `
          <div class="appuse-step-card" style="${accentStyle}">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:3px; flex-wrap:wrap;">
              <strong>第 ${s.step} 步 · ${escapeHtml(s.title)}</strong>
              <span style="display:inline-flex; gap:4px; align-items:center;">
                ${s.captureAs ? `<span class="pill ok">输出：${escapeHtml(s.captureAs)}</span>` : ""}
                <span class="pill" title="${escapeHtml(s.action)}">${escapeHtml(actionLabel)}</span>
              </span>
            </div>
            <div style="font-size:12px; color:var(--text-secondary);">${escapeHtml(s.description || "")}</div>
            ${stepMeta ? `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(stepMeta)}</div>` : ""}
          </div>
        `;
        }).join("");
      }
    }

    function renderSavedAppUseWorkflows() {
      const box = document.getElementById("appuseSavedList");
      const editSel = document.getElementById("wfagentEditWorkflowSelect");
      if (editSel) {
        const curId = APPUSE_CURRENT_WF?.id || editSel.value || "";
        editSel.innerHTML = `<option value="">切换要修改的流程 (${APPUSE_WORKFLOWS.length})…</option>` + APPUSE_WORKFLOWS.map((wf) => (
          `<option value="${escapeHtml(wf.id)}">${escapeHtml(wf.name || wf.id)} (v${wf.version || 1})</option>`
        )).join("");
        if (curId && APPUSE_WORKFLOWS.some((w) => w.id === curId)) {
          editSel.value = curId;
        }
      }
      if (!box) return;
      if (!APPUSE_WORKFLOWS.length) {
        box.innerHTML = `<div style="font-size:12.5px; color:var(--text-muted);">暂未保存 App-Use 流程，请在上方选择一个应用与 Agent 自动生成。</div>`;
        return;
      }
      box.innerHTML = APPUSE_WORKFLOWS.map((wf) => {
        const rd = wf.readiness || {};
        const st = wf.stats || {};
        const gradeTag = rd.grade ? `<span class="pill ${Number(rd.score || 0) >= 70 ? "ok" : ""}" style="font-size:10.5px;">${escapeHtml(rd.grade)} (${rd.score ?? "-"})</span>` : "";
        const rateTag = st.runs ? ` · 成功率 ${Math.round(Number(st.successRate || 0) * 100)}% (${st.runs}次)` : "";
        const vMap = {
          verified: `<span class="pill wfagent-badge-pass" style="font-size:10.5px;">✅ 已验证</span>`,
          shadow_verified: `<span class="pill wfagent-badge-fix" style="font-size:10.5px;">🛡️ 影子验证</span>`,
          dry_run_only: `<span class="pill" style="font-size:10.5px;">🧪 仅演练</span>`,
        };
        const vTag = vMap[wf.verificationStatus] || "";
        return `
        <div class="appuse-step-card" style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
          <div style="min-width:0;">
            <div style="font-weight:600; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:flex; align-items:center; gap:5px;">
              <span>${escapeHtml(wf.name)}</span>
              <span style="font-weight:400; color:var(--text-muted);">v${wf.version || 1}</span>
              ${gradeTag}
              ${vTag}
            </div>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml((wf.targetApp || {}).name || "")} · ${(wf.steps || []).length} 步 · ${escapeHtml((wf.builderAgent || {}).modelId || "")}${escapeHtml(rateTag)}</div>
          </div>
          <div style="display:flex; gap:6px; flex-shrink:0;">
            <button type="button" class="btn-outline sm" onclick="wfagentDebugSaved('${encArg(wf.id)}')">🔧 修复</button>
            <button type="button" class="btn-outline sm" onclick="loadSavedAppUseWorkflow('${encArg(wf.id)}')">载入</button>
            <button type="button" class="btn-outline sm" onclick="deleteSavedAppUseWorkflow('${encArg(wf.id)}')">删除</button>
          </div>
        </div>
      `;
      }).join("");
    }

    async function loadAppUseStudio(refreshModels) {
      const [appsRes, agentsRes, wfRes, pipeRes, runsRes, recRes, graphRes, concRes] = await Promise.all([
        apiJson("/api/app-use/apps"),
        apiJson("/api/app-use/agents?refresh=" + (refreshModels ? "1" : "0")),
        apiJson("/api/app-use/workflows"),
        apiJson("/api/app-use/pipelines").catch(() => ({ data: { pipelines: [] } })),
        apiJson("/api/app-use/runs?limit=15").catch(() => ({ data: { runs: [] } })),
        apiJson("/api/app-use/recording").catch(() => ({ data: { active: false } })),
        apiJson("/api/app-use/state-graph").catch(() => ({ data: { apps: [] } })),
        apiJson("/api/app-use/concurrency-status").catch(() => ({ data: {} })),
      ]);
      APPUSE_APPS = appsRes.data?.apps || [];
      APPUSE_AGENTS = agentsRes.data?.agents || [];
      APPUSE_WORKFLOWS = wfRes.data?.workflows || [];
      APPUSE_PIPELINES = pipeRes.data?.pipelines || [];
      APPUSE_RUNS = runsRes.data?.runs || [];
      APPUSE_STATE_GRAPH = graphRes.data || {};
      APPUSE_CONCURRENCY = concRes.data || {};
      const counts = appsRes.data?.counts || {};
      const desc = document.getElementById("appuseStatusDesc");
      if (desc) {
        desc.textContent = `已发现 ${counts.total || APPUSE_APPS.length} 款本机应用（其中 ${counts.agent_app || 0} 款 AI Agent 应用，${counts.running || 0} 款运行中）· 可选 ${APPUSE_AGENTS.length} 个构建 Agent。`;
      }
      renderAppUseApps();
      renderAppUseRiskBadge();
      renderAppUseAgents();
      renderSavedAppUseWorkflows();
      renderAppUsePipelines();
      renderAppUseRuns();
      renderAppUseStateGraph();
      renderAppUseConcurrency();
      renderAppUseRecording(recRes.data || {});
      await wfagentLoadSessions();
      if (!APPUSE_CURRENT_WF && APPUSE_WORKFLOWS.length) {
        renderAppUseWorkflow(APPUSE_WORKFLOWS[0]);
      }
    }

    function fillAppUseExample(kind) {
      const goalEl = document.getElementById("appuseGoalInput");
      let targetMatch = "";
      if (kind === "calc") {
        targetMatch = "com.apple.calculator";
        if (goalEl) goalEl.value = "打开计算器，清零后计算 125*8 并回车回读最终显示数值，截图存证。";
      } else if (kind === "textedit") {
        targetMatch = "com.apple.TextEdit";
        if (goalEl) goalEl.value = "在文本编辑中新建空白文档，粘贴结构化会议纪要内容并通过 AX 与 OCR 验证写入完整。";
      } else {
        const firstAgentApp = APPUSE_APPS.find((a) => a.isAgentApp && a.running) || APPUSE_APPS.find((a) => a.isAgentApp);
        targetMatch = firstAgentApp ? (firstAgentApp.bundleID || firstAgentApp.name) : "com.openai.codex";
        if (goalEl) goalEl.value = "唤醒该 Agent 应用，定位输入框填入任务提示词并发送，持续等待流式输出稳定后回读完整回答。";
      }
      const sel = document.getElementById("appuseAppSelect");
      if (sel && targetMatch) {
        const opt = Array.from(sel.options).find((o) => decodeURIComponent(o.value).toLowerCase() === targetMatch.toLowerCase());
        if (opt) sel.value = opt.value;
        renderAppUseApps();
      }
    }

    async function appuseInspectSelected() {
      const target = getSelectedAppUseTarget();
      const launch = Boolean(document.getElementById("appuseLaunchChk")?.checked);
      const sumEl = document.getElementById("appuseInspectSummary");
      if (sumEl) sumEl.textContent = `正在扫描 ${target.name || target.bundleID} 的 AXUIElement 与 Vision OCR…`;
      const { data } = await apiJson("/api/app-use/inspect", {
        method: "POST",
        body: JSON.stringify({
          bundle_id: target.bundleID || "",
          app_name: target.name || "",
          app_path: target.appPath || "",
          launch_if_needed: launch,
          allow_activate: true,
        }),
      });
      if (data?.ok) {
        const u = data.uiSummary || {};
        const arch = data.archetype || u.archetype || {};
        const ab = document.getElementById("appuseArchetypeBadge");
        if (ab && arch.id) {
          ab.textContent = `Archetype：${arch.label || arch.id}`;
          ab.className = "pill ok";
        }
        const m = data.modalStatus || u.modalStatus || {};
        const modalTxt = (m.kind && m.kind !== "none") ? ` · ⚠️ 阻断弹窗: ${m.kind}` : "";
        if (sumEl) {
          sumEl.textContent = `扫描成功 · 窗口「${u.windowTitle || "-"}」 · AX控件 ${u.axControlCount || 0}（输入 ${u.inputCount || 0} / 按钮 ${u.buttonCount || 0}）· OCR文本块 ${u.ocrCount || 0}${modalTxt} · 截图: ${data.savedPath || "-"}`;
        }
        showToast("已完成目标 App 界面扫描");
      } else {
        if (sumEl) sumEl.textContent = `扫描失败: ${data?.error || "unknown"}`;
        showToast("界面扫描未成功");
      }
    }

    async function appuseBuildSOP() {
      const target = getSelectedAppUseTarget();
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const goal = document.getElementById("appuseGoalInput")?.value?.trim() || "";
      const customPrompt = document.getElementById("appuseCustomPromptInput")?.value?.trim() || "";
      const launch = Boolean(document.getElementById("appuseLaunchChk")?.checked);
      const attachShot = Boolean(document.getElementById("appuseAttachShotChk")?.checked);
      if (!goal) { showToast("请先填写 SOP 目标需求"); return; }

      const btn = document.getElementById("appuseBuildBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ Agent 正在分析界面并构建 SOP…"; }
      try {
        const { data } = await apiJson("/api/app-use/build-sop", {
          method: "POST",
          body: JSON.stringify({
            goal,
            bundle_id: target.bundleID || "",
            app_name: target.name || "",
            app_path: target.appPath || "",
            agent_id: agentId,
            custom_agent_prompt: customPrompt,
            inspect_live: true,
            launch_if_needed: launch,
            attach_screenshot: attachShot,
            save: true,
          }),
        });
        if (data?.ok && data.workflow) {
          renderAppUseWorkflow(data.workflow);
          document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data.inspection || data.workflow.builderAgent, null, 2);
          showToast("已由选定 Agent 自动生成 SOP 与 RPA 流程");
          const wfRes = await apiJson("/api/app-use/workflows");
          APPUSE_WORKFLOWS = wfRes.data?.workflows || [];
          renderSavedAppUseWorkflows();
        } else {
          showToast(data?.error || "生成失败");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "✨ 选定 Agent 自动生成 SOP 与可执行 RPA 流程"; }
      }
    }

    function appuseLiveRunStepClick() {
      if (!APPUSE_CURRENT_WF) { showToast("请先生成或载入一条流程"); return; }
      if (!APPUSE_LIVE_ARMED) {
        APPUSE_LIVE_ARMED = true;
        const btn = document.getElementById("appuseLiveRunBtn");
        if (btn) btn.textContent = "⚠️ 再次点击确认实机执行";
        clearTimeout(APPUSE_LIVE_TIMER);
        APPUSE_LIVE_TIMER = setTimeout(appuseResetLiveArm, 5000);
        return;
      }
      appuseResetLiveArm();
      appuseRunCurrent(false);
    }

    async function appuseRefreshRuns() {
      try {
        const res = await apiJson("/api/app-use/runs?limit=15");
        APPUSE_RUNS = res.data?.runs || [];
        renderAppUseRuns();
      } catch (e) { /* ignore */ }
    }

    async function appuseRefreshWorkflowsList() {
      try {
        const wfRes = await apiJson("/api/app-use/workflows");
        APPUSE_WORKFLOWS = wfRes.data?.workflows || [];
        renderSavedAppUseWorkflows();
      } catch (e) { /* ignore */ }
    }

    async function appuseRunCurrent(dryRun) {
      if (!APPUSE_CURRENT_WF) { showToast("请先生成或载入一条流程"); return; }
      let params = {};
      try {
        const raw = document.getElementById("appuseRunParamsInput")?.value?.trim() || "{}";
        params = JSON.parse(raw);
      } catch (e) {
        showToast("参数 JSON 格式有误");
        return;
      }
      const selfHeal = Boolean(document.getElementById("appuseSelfHealChk")?.checked ?? true);
      const autoPatch = Boolean(document.getElementById("appuseAutoPatchChk")?.checked ?? false);
      const dispatchMode = document.getElementById("appuseDispatchModeSelect")?.value || "auto";
      const { data } = await apiJson("/api/app-use/run", {
        method: "POST",
        body: JSON.stringify({
          workflow_id: APPUSE_CURRENT_WF.id,
          workflow: APPUSE_CURRENT_WF,
          params,
          dry_run: Boolean(dryRun),
          confirm_run: !dryRun,
          respect_human_guard: true,
          self_heal: selfHeal,
          auto_patch_workflow: autoPatch,
          dispatch_mode: dispatchMode,
        }),
      });
      document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
      if (data?.workflowPatched) {
        await appuseRefreshWorkflowsList();
        const updated = APPUSE_WORKFLOWS.find((w) => w.id === APPUSE_CURRENT_WF?.id);
        if (updated) renderAppUseWorkflow(updated);
      }
      await appuseRefreshRuns();
      await appuseRefreshConcurrencyStatus();
      showToast(dryRun ? "Dry-Run 演练完成" : (data?.ok ? "实机流程执行完成" : "实机执行中止"));
    }

    async function appuseExportToKB() {
      if (!APPUSE_CURRENT_WF?.id) { showToast("请先生成或载入一条已保存流程"); return; }
      const { data } = await apiJson("/api/app-use/export-kb", {
        method: "POST",
        body: JSON.stringify({ workflow_id: APPUSE_CURRENT_WF.id }),
      });
      if (data?.ok) {
        showToast("已将当前 App-Use SOP 存入知识库");
      } else {
        showToast(data?.error || "存入失败");
      }
    }

    async function appuseExportSkill() {
      if (!APPUSE_CURRENT_WF?.id) { showToast("请先生成或载入一条已保存流程"); return; }
      const { data } = await apiJson("/api/app-use/export-skill", {
        method: "POST",
        body: JSON.stringify({ workflow_id: APPUSE_CURRENT_WF.id }),
      });
      document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
      if (data?.ok) {
        showToast("已导出便携 Agent Skill：" + (data.skillName || data.skillMdPath || ""));
      } else {
        showToast(data?.error || "导出 Skill 失败");
      }
    }

    async function appuseRollbackCurrent() {
      if (!APPUSE_CURRENT_WF?.id) { showToast("请先载入一条已保存流程"); return; }
      const { data } = await apiJson("/api/app-use/rollback", {
        method: "POST",
        body: JSON.stringify({ workflow_id: APPUSE_CURRENT_WF.id, revision_index: -1 }),
      });
      document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
      if (data?.ok && data.workflow) {
        renderAppUseWorkflow(data.workflow);
        await appuseRefreshWorkflowsList();
        showToast(`已回滚至版本 v${data.workflow.version || 1}`);
      } else {
        showToast(data?.error || "暂无历史版本可回滚");
      }
    }

    function appuseExploreLiveClick() {
      if (!APPUSE_EXPLORE_ARMED) {
        APPUSE_EXPLORE_ARMED = true;
        const btn = document.getElementById("appuseExploreLiveBtn");
        if (btn) btn.textContent = "⚠️ 再次点击确认实机探索";
        clearTimeout(APPUSE_EXPLORE_TIMER);
        APPUSE_EXPLORE_TIMER = setTimeout(appuseResetLiveArm, 5000);
        return;
      }
      appuseResetLiveArm();
      appuseExplore(false);
    }

    async function appuseExplore(dryRun) {
      const target = getSelectedAppUseTarget();
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const goal = document.getElementById("appuseGoalInput")?.value?.trim() || "";
      const maxTurns = Number(document.getElementById("appuseExploreTurns")?.value || 4) || 4;
      const launch = Boolean(document.getElementById("appuseLaunchChk")?.checked);
      if (!goal) { showToast("请先在上方填写探索目标需求"); return; }
      const btn = document.getElementById(dryRun ? "appuseExploreDryBtn" : "appuseExploreLiveBtn");
      const prev = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 自主探索中…"; }
      try {
        const { data } = await apiJson("/api/app-use/explore", {
          method: "POST",
          body: JSON.stringify({
            goal,
            bundle_id: target.bundleID || "",
            app_name: target.name || "",
            app_path: target.appPath || "",
            agent_id: agentId,
            max_turns: maxTurns,
            dry_run: Boolean(dryRun),
            confirm_run: !dryRun,
            respect_human_guard: true,
            launch_if_needed: launch,
            save: true,
          }),
        });
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        if (data?.ok && data.workflow) {
          renderAppUseWorkflow(data.workflow);
          await appuseRefreshWorkflowsList();
          await appuseRefreshRuns();
          showToast(`自主探索完成（${data.turns || 0} 轮）并已生成 SOP`);
        } else {
          showToast(data?.error || "自主探索未成功");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    function renderAppUseRecording(rec) {
      const el = document.getElementById("appuseRecStatus");
      if (!el) return;
      if (rec?.active) {
        el.textContent = `🔴 正在录制（会话 ${rec.sessionId || ""} · 已采集 ${rec.eventCount || 0} 条操作轨迹 · ${rec.elapsedSec || 0}s）`;
        if (!APPUSE_REC_POLL) {
          APPUSE_REC_POLL = setInterval(appusePollRecording, 1500);
        }
      } else {
        clearInterval(APPUSE_REC_POLL);
        APPUSE_REC_POLL = null;
        if (Number(rec?.eventCount || 0) > 0) {
          el.textContent = `⏸ 录制已结束（上次采集 ${rec.eventCount} 条事件 · 可点击开始新一轮示范录制）`;
        } else {
          el.textContent = "录制器空闲 · 点击「开始示范录制」后去目标 App 操作，再回来点停止编译。";
        }
      }
    }

    async function appusePollRecording() {
      try {
        const { data } = await apiJson("/api/app-use/recording");
        renderAppUseRecording(data || {});
      } catch (e) { /* ignore */ }
    }

    async function appuseStartRecording() {
      const { data } = await apiJson("/api/app-use/recording/start", {
        method: "POST",
        body: JSON.stringify({ max_duration_sec: 180, poll_interval_sec: 0.45 }),
      });
      renderAppUseRecording(data || {});
      if (data?.ok) {
        showToast("🔴 示范录制已开始，请切换到目标应用操作");
      } else {
        showToast(data?.error || "启动录制失败");
      }
    }

    async function appuseStopRecording() {
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const goalHint = document.getElementById("appuseGoalInput")?.value?.trim() || "";
      const btn = document.getElementById("appuseRecStopBtn");
      const prev = btn ? btn.textContent : "⏹ 停止并编译 SOP";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 正在编译示范轨迹…"; }
      try {
        const { data } = await apiJson("/api/app-use/recording/stop", {
          method: "POST",
          body: JSON.stringify({ goal_hint: goalHint, agent_id: agentId, save: true }),
        });
        renderAppUseRecording({ active: false, eventCount: data?.eventCount || 0 });
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        if (data?.ok && data.workflow) {
          renderAppUseWorkflow(data.workflow);
          await appuseRefreshWorkflowsList();
          showToast(`示范已编译为参数化 SOP（采集 ${data.eventCount || 0} 条轨迹）`);
        } else {
          showToast(data?.error || "未采集到可编译事件");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    function appuseLoadCalcTextEditPreset() {
      const preset = {
        id: "pipe_calc_to_textedit_v27",
        name: "计算器算值 → TextEdit 自动写入报告",
        stages: [
          {
            name: "阶段1：Calculator 计算 256×4",
            workflow: {
              id: "wf_pipe_calc_stage",
              name: "Calculator 算值采集",
              targetApp: { bundleID: "com.apple.calculator", name: "Calculator" },
              steps: [
                { step: 1, action: "activate_app", title: "唤醒计算器", launchIfNeeded: true },
                { step: 2, action: "press_shortcut", title: "清零", combo: "escape" },
                { step: 3, action: "press_shortcut", title: "输入 256*4 并回车", sequence: "2,5,6,*,4,return", delayMs: 110 },
                { step: 4, action: "wait_and_read", title: "采集计算结果", delaySec: 0.4, captureAs: "calc_result", extractMode: "ax_last", saveScreenshot: true },
              ],
            },
          },
          {
            name: "阶段2：TextEdit 写入管道变量",
            workflow: {
              id: "wf_pipe_textedit_stage",
              name: "TextEdit 出报告",
              targetApp: { bundleID: "com.apple.TextEdit", name: "TextEdit" },
              steps: [
                { step: 1, action: "activate_app", title: "唤醒文本编辑", launchIfNeeded: true },
                { step: 2, action: "press_shortcut", title: "新建文稿", combo: "cmd+n" },
                { step: 3, action: "focus_and_type", title: "写入跨应用变量", text: "跨应用 RPA 流水线实测：Calculator 算得 {{calc_result}} → 自动写入 TextEdit" },
                { step: 4, action: "wait_and_read", title: "AX+OCR 回读验收", delaySec: 0.5, expectText: "{{calc_result}}", saveScreenshot: true },
              ],
            },
          },
        ],
      };
      const el = document.getElementById("appusePipelineJson");
      if (el) el.value = JSON.stringify(preset, null, 2);
      showToast("已填入「计算器 → 文本编辑」跨应用流水线模板");
    }

    function _parseAppUsePipelineInput() {
      const raw = document.getElementById("appusePipelineJson")?.value?.trim() || "";
      if (!raw) throw new Error("请先点击预设或填入流水线 JSON");
      return JSON.parse(raw);
    }

    async function appuseSavePipeline() {
      let obj;
      try {
        obj = _parseAppUsePipelineInput();
      } catch (e) {
        showToast(e.message || "流水线 JSON 格式有误");
        return;
      }
      const { data } = await apiJson("/api/app-use/pipelines/save", {
        method: "POST",
        body: JSON.stringify({ pipeline: obj }),
      });
      if (data?.ok) {
        const listRes = await apiJson("/api/app-use/pipelines").catch(() => ({ data: { pipelines: [] } }));
        APPUSE_PIPELINES = listRes.data?.pipelines || [];
        renderAppUsePipelines();
        showToast("已保存跨应用流水线：" + (data.pipeline?.name || ""));
      } else {
        showToast(data?.error || "保存流水线失败");
      }
    }

    function appuseRunPipelineLiveClick() {
      if (!APPUSE_PIPE_ARMED) {
        APPUSE_PIPE_ARMED = true;
        const btn = document.getElementById("appusePipelineLiveBtn");
        if (btn) btn.textContent = "⚠️ 再次点击确认实机联跑";
        clearTimeout(APPUSE_PIPE_TIMER);
        APPUSE_PIPE_TIMER = setTimeout(appuseResetLiveArm, 5000);
        return;
      }
      appuseResetLiveArm();
      appuseRunPipeline(false);
    }

    async function appuseRunPipeline(dryRun) {
      let obj;
      try {
        obj = _parseAppUsePipelineInput();
      } catch (e) {
        showToast(e.message || "请先点击预设或填入合法流水线 JSON");
        return;
      }
      const selfHeal = Boolean(document.getElementById("appuseSelfHealChk")?.checked ?? true);
      const { data } = await apiJson("/api/app-use/pipelines/run", {
        method: "POST",
        body: JSON.stringify({
          pipeline: obj,
          dry_run: Boolean(dryRun),
          confirm_run: !dryRun,
          respect_human_guard: true,
          self_heal: selfHeal,
        }),
      });
      document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
      await appuseRefreshRuns();
      showToast(dryRun ? "流水线 Dry-Run 完成" : (data?.ok ? "跨应用流水线实机联跑成功" : "流水线实机中止"));
    }

    function appuseLoadSavedPipeline(encodedId) {
      const pid = decodeURIComponent(encodedId || "");
      const pl = APPUSE_PIPELINES.find((p) => p.id === pid);
      if (pl) {
        const el = document.getElementById("appusePipelineJson");
        if (el) el.value = JSON.stringify(pl, null, 2);
        showToast("已载入流水线：" + (pl.name || pl.id));
      }
    }

    async function appuseDeletePipeline(encodedId) {
      const pid = decodeURIComponent(encodedId || "");
      const { data } = await apiJson("/api/app-use/pipelines/delete", {
        method: "POST",
        body: JSON.stringify({ pipeline_id: pid }),
      });
      if (data?.ok) {
        APPUSE_PIPELINES = APPUSE_PIPELINES.filter((p) => p.id !== pid);
        renderAppUsePipelines();
        showToast("已删除流水线");
      }
    }

    function renderAppUsePipelines() {
      const box = document.getElementById("appusePipelinesList");
      if (!box) return;
      if (!APPUSE_PIPELINES.length) {
        box.innerHTML = `<div style="font-size:11.5px; color:var(--text-muted);">暂未保存跨应用流水线；可点上方「🧮 计算器算值 → 📝 文本编辑出报告」快速载入。</div>`;
        return;
      }
      box.innerHTML = APPUSE_PIPELINES.map((pl) => `
        <div class="appuse-step-card" style="display:flex; justify-content:space-between; align-items:center; gap:8px; padding:6px 8px;">
          <div style="min-width:0;">
            <div style="font-weight:600; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(pl.name || pl.id)}</div>
            <div style="font-size:11px; color:var(--text-muted);">${(pl.stages || []).length} 个跨应用阶段</div>
          </div>
          <div style="display:flex; gap:5px; flex-shrink:0;">
            <button type="button" class="btn-outline sm" onclick="appuseLoadSavedPipeline('${encArg(pl.id)}')">载入</button>
            <button type="button" class="btn-outline sm" onclick="appuseDeletePipeline('${encArg(pl.id)}')">删除</button>
          </div>
        </div>
      `).join("");
    }

    function renderAppUseRuns() {
      const box = document.getElementById("appuseRunsList");
      if (!box) return;
      if (!APPUSE_RUNS.length) {
        box.innerHTML = `<div style="font-size:11.5px; color:var(--text-muted);">暂无运行审计记录。</div>`;
        return;
      }
      box.innerHTML = APPUSE_RUNS.map((r) => {
        const title = r.kind === "pipeline" ? (r.pipelineName || "跨应用流水线") : (r.workflowName || r.targetApp || r.runId);
        const modeTag = r.dryRun ? "Dry-Run" : "实机";
        const badgeCls = r.ok ? "ok" : "";
        const thumb = r.artifactName
          ? `<a href="/api/app-use/artifact/${encodeURIComponent(r.artifactName)}" target="_blank" title="查看高清截图存证" style="display:inline-block; margin-top:4px;"><img src="/api/app-use/artifact/${encodeURIComponent(r.artifactName)}" alt="" style="width:110px; max-height:68px; object-fit:cover; border-radius:6px; border:1px solid var(--border);" loading="lazy" /></a>`
          : "";
        const capTxt = r.capturedVars && Object.keys(r.capturedVars).length ? ` · 变量: ${JSON.stringify(r.capturedVars)}` : "";
        return `
          <div class="appuse-step-card" style="padding:6px 8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:6px;">
              <strong style="font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(title)}</strong>
              <span class="pill ${badgeCls}" style="font-size:10.5px;">${escapeHtml(modeTag)} · ${r.ok ? "成功" : "中止"}</span>
            </div>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(r.ts || "")} · ${Math.round(r.elapsedMs || 0)}ms${escapeHtml(capTxt)}</div>
            ${thumb}
          </div>
        `;
      }).join("");
    }

    function loadSavedAppUseWorkflow(encodedId) {
      const wid = decodeURIComponent(encodedId || "");
      const wf = APPUSE_WORKFLOWS.find((w) => w.id === wid);
      if (wf) {
        renderAppUseWorkflow(wf);
        showToast("已载入流程：" + wf.name);
      }
    }

    async function deleteSavedAppUseWorkflow(encodedId) {
      const wid = decodeURIComponent(encodedId || "");
      const { data } = await apiJson("/api/app-use/delete-workflow", {
        method: "POST",
        body: JSON.stringify({ workflow_id: wid }),
      });
      if (data?.ok) {
        APPUSE_WORKFLOWS = APPUSE_WORKFLOWS.filter((w) => w.id !== wid);
        if (APPUSE_CURRENT_WF?.id === wid) renderAppUseWorkflow(APPUSE_WORKFLOWS[0] || null);
        renderSavedAppUseWorkflows();
        showToast("已删除流程");
      }
    }

    function renderAppUseStateGraph() {
      const box = document.getElementById("appuseStateGraphBox");
      if (!box) return;
      const apps = APPUSE_STATE_GRAPH?.apps || [];
      if (!apps.length) {
        box.innerHTML = `<div style="font-size:11.5px; color:var(--text-muted);">暂未积累状态图谱（运行或泛化任意 App 后自动沉淀界面状态与迁移边）。</div>`;
        return;
      }
      box.innerHTML = apps.map((g) => `
        <div class="appuse-step-card" style="padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:8px;">
          <div style="min-width:0;">
            <strong style="font-size:12px;">${escapeHtml(g.appName || g.bundleID)}</strong>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(g.bundleID)} · ${escapeHtml(g.archetypeId || "generic")}</div>
          </div>
          <span class="pill" style="font-size:10.5px;">节点 ${g.nodeCount || 0} · 迁移边 ${g.edgeCount || 0}</span>
        </div>
      `).join("");
    }

    async function appuseRefreshStateGraph() {
      try {
        const res = await apiJson("/api/app-use/state-graph");
        APPUSE_STATE_GRAPH = res.data || {};
        renderAppUseStateGraph();
      } catch (e) { /* ignore */ }
    }

    function renderAppUseRiskBadge() {
      const badge = document.getElementById("appuseRiskBadge");
      if (!badge) return;
      const target = getSelectedAppUseTarget();
      const rp = target?.riskProfile || null;
      if (!rp) {
        badge.className = "pill";
        badge.textContent = "风控策略：待识别";
        return;
      }
      const tier = rp.tier || "safe_native";
      if (tier === "high_risk_social") {
        badge.className = "pill warn";
        badge.textContent = "🛡️ 社交风控保护 · 强制前台拟真节奏";
      } else if (tier === "moderate_agent_or_web") {
        badge.className = "pill";
        badge.textContent = "🟡 中度 · Agent/WebView 双通道";
      } else {
        badge.className = "pill ok";
        badge.textContent = "🟢 安全原生 · 支持无焦点 AX 真并发";
      }
      badge.title = rp.advice || "";
    }

    function renderAppUseConcurrency() {
      const box = document.getElementById("appuseConcurrencyBox");
      if (!box) return;
      const metrics = APPUSE_CONCURRENCY?.metrics || {};
      const active = APPUSE_CONCURRENCY?.activeLanes || [];
      const recent = APPUSE_CONCURRENCY?.recentLanes || [];
      const lease = APPUSE_CONCURRENCY?.hidLeaseStats || {};
      const stateLabels = {
        observing: "👀 后台只读感知",
        ax_headless: "⚡ 无焦点 AX 直调",
        waiting_hid_lease: "⏳ 排队等前景锁",
        holding_hid_lease: "🖱️ 持有前景真焦点",
        human_paced_cooldown: "🛡️ 拟真节奏抖动",
        paused_for_human: "✋ 待人工确认",
        done: "✅ 已完成",
        failed: "❌ 失败",
      };
      const summaryHtml = `
        <div style="display:flex; gap:6px; flex-wrap:wrap; font-size:11px;">
          <span class="pill ok">无焦点 AX ${metrics.totalHeadlessAxOps || 0} 次 (${metrics.headlessSharePct || 0}%)</span>
          <span class="pill">前台 HID ${metrics.totalForegroundHidOps || 0} 次 (租约 ${lease.totalAcquisitions || 0} · 争用 ${lease.contendedAcquisitions || 0})</span>
          <span class="pill ${(metrics.totalRiskBlockedHeadless || 0) > 0 ? "warn" : ""}">风控拦截注入 ${metrics.totalRiskBlockedHeadless || 0} · 平滑降级 ${metrics.totalFallbackCount || 0}</span>
        </div>
      `;
      const lanes = [...active, ...recent.slice(0, 8)];
      if (!lanes.length) {
        box.innerHTML = summaryHtml + `<div style="font-size:11.5px; color:var(--text-muted);">暂无并发泳道记录（运行任意并行监控或双通道流程后实时展示）。</div>`;
        return;
      }
      box.innerHTML = summaryHtml + lanes.map((ln) => {
        const stText = stateLabels[ln.state] || ln.state || "idle";
        const pillCls = ln.state === "done" || ln.state === "ax_headless" ? "ok" : (ln.state === "failed" || ln.riskTier === "high_risk_social" ? "warn" : "");
        return `
          <div class="appuse-step-card" style="padding:6px 8px; display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <div style="min-width:0;">
              <strong style="font-size:12px;">${escapeHtml(ln.appName || ln.bundleID || ln.laneId)}</strong>
              <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(ln.riskTier || "safe_native")} · AX ${ln.headlessAxOps || 0} / HID ${ln.foregroundHidOps || 0} · ${ln.elapsedMs || 0}ms</div>
            </div>
            <span class="pill ${pillCls}" style="font-size:10.5px; flex-shrink:0;">${escapeHtml(stText)}</span>
          </div>
        `;
      }).join("");
    }

    async function appuseRefreshConcurrencyStatus() {
      try {
        const res = await apiJson("/api/app-use/concurrency-status");
        APPUSE_CONCURRENCY = res.data || {};
        renderAppUseConcurrency();
      } catch (e) { /* ignore */ }
    }

    async function appuseGeneralizeNewApp() {
      const target = getSelectedAppUseTarget();
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const goal = document.getElementById("appuseGoalInput")?.value?.trim() || "";
      const customPrompt = document.getElementById("appuseCustomPromptInput")?.value?.trim() || "";
      const launch = Boolean(document.getElementById("appuseLaunchChk")?.checked);
      if (!goal) { showToast("请先填写新 App 要自动完成的业务目标"); return; }

      const btn = document.getElementById("appuseGeneralizeBtn");
      const prev = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 正在泛化未知 App → 合成 → 优化 → 打包 Skill…"; }
      try {
        const { data } = await apiJson("/api/app-use/generalize", {
          method: "POST",
          body: JSON.stringify({
            goal,
            bundle_id: target.bundleID || "",
            app_name: target.name || "",
            app_path: target.appPath || "",
            agent_id: agentId,
            mode: "auto",
            launch_if_needed: launch,
            dry_run_verify: true,
            export_skill: true,
            save: true,
            custom_agent_prompt: customPrompt,
          }),
        });
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        if (data?.ok && data.workflow) {
          renderAppUseWorkflow(data.workflow);
          await appuseRefreshWorkflowsList();
          await appuseRefreshRuns();
          await appuseRefreshStateGraph();
          const grade = data.readiness?.grade || "-";
          const score = data.readiness?.score ?? "-";
          const sk = data.exportedSkill?.skillMdPath || "";
          showToast(`泛化完成！就绪度 ${grade} (${score}分)${sk ? " · 已生成 Skill" : ""}`);
        } else {
          showToast(data?.error || "泛化未成功");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    async function appuseWatchRunningParallel() {
      const candidates = APPUSE_APPS.filter((a) => a.running && Number(a.windowCount || 0) > 0 && a.bundleID)
        .slice(0, 4)
        .map((a) => ({ bundle_id: a.bundleID, app_name: a.name }));
      if (!candidates.length) {
        const cur = getSelectedAppUseTarget();
        if (cur?.bundleID) candidates.push({ bundle_id: cur.bundleID, app_name: cur.name });
      }
      if (!candidates.length) { showToast("当前未检测到带窗口的运行中应用"); return; }

      const btn = document.getElementById("appuseWatchParallelBtn");
      const prev = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 并发扫描窗口中…"; }
      try {
        const { data } = await apiJson("/api/app-use/watch-parallel", {
          method: "POST",
          body: JSON.stringify({ targets: candidates, include_ocr: false, max_workers: 4 }),
        });
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        await appuseRefreshStateGraph();
        await appuseRefreshConcurrencyStatus();
        if (data?.ok) {
          showToast(`已并发监测 ${data.succeededCount}/${data.targetCount} 个窗口（加速比 ${data.speedupRatio || 1}x · ${data.wallElapsedMs || 0}ms）`);
        } else {
          showToast(data?.error || "并行监控失败");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    async function appuseInstallMetaSkill() {
      const btn = document.getElementById("appuseInstallMetaSkillBtn");
      const prev = btn ? btn.textContent : "";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 安装全局元技能中…"; }
      try {
        const { data } = await apiJson("/api/app-use/install-meta-skill", {
          method: "POST",
          body: JSON.stringify({ install_global: true }),
        });
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        if (data?.ok) {
          const cnt = (data.linkedTargets || []).length + (data.installedPaths || []).length;
          showToast(`已安装全局元技能 app-use-meta-builder（${cnt} 处目录）`);
        } else {
          showToast(data?.error || "安装失败");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    // Workflow Agent Self-Authoring & Self-Debugging Studio (v3.1)
    let WFAGENT_LIVE_ARMED = false;
    let WFAGENT_LIVE_TIMER = null;

    function wfagentResetLiveArm() {
      WFAGENT_LIVE_ARMED = false;
      clearTimeout(WFAGENT_LIVE_TIMER);
      const btn = document.getElementById("wfagentRunBtn");
      if (btn) btn.textContent = "2️⃣ 自动写流程并自己调试好";
    }

    function wfagentSyncModeSummary() {
      const modeEl = document.getElementById("wfagentModeSelect");
      const badge = document.getElementById("wfagentModeSummaryBadge");
      if (!modeEl || !badge) return;
      const labels = {
        shadow: "安全影子调试 Shadow",
        dry_run: "静态预检 Dry-Run",
        live: "实机联跑 Live",
      };
      badge.textContent = labels[modeEl.value] || modeEl.value || "Shadow";
      badge.className = modeEl.value === "live" ? "pill wfagent-badge-fix" : "pill";
    }

    function wfagentFillChip(kind) {
      const goalEl = document.getElementById("wfagentGoalInput");
      const modeEl = document.getElementById("wfagentModeSelect");
      if (!goalEl) return;
      if (kind === "feishu_wx") {
        goalEl.value = "从飞书客户聊天中提取微信号，用智拓巨浪话术自报家门加微信，备注飞书引流并写入后端CRM档案";
        if (modeEl) modeEl.value = "shadow";
      } else if (kind === "feishu_doc") {
        goalEl.value = "读取飞书当前聊天或待办内容，提炼关键事项并在文本编辑中新建简报文档保存";
        if (modeEl) modeEl.value = "shadow";
      } else if (kind === "calc_doc") {
        goalEl.value = "打开计算器计算 125*8 并提取数值结果，随后切换到文本编辑新建文档写入计算简报并回读验证";
        if (modeEl) modeEl.value = "live";
      }
      wfagentSyncModeSummary();
      wfagentResetLiveArm();
    }

    function wfagentRenderSpec(spec, lintReport) {
      const box = document.getElementById("wfagentSpecBox");
      if (!box) return;
      if (!spec) { box.textContent = "暂无方案"; return; }
      const apps = (spec.targetApps || []).map((a) => {
        const nm = wfagentFormatAppLabel(a.bundleID) !== a.bundleID
          ? wfagentFormatAppLabel(a.bundleID)
          : (a.name || a.bundleID);
        const rk = WFAGENT_RISK_LABELS[a.riskTier] || a.riskTier || "低风险原生应用";
        return `${nm} [${rk}]`;
      }).join(" → ");
      const lintOk = lintReport ? lintReport.ok : true;
      const criticHtml = spec.ominiCriticReview?.review
        ? `<div style="margin-top:6px; padding:6px 8px; border-radius:8px; background:rgba(22,119,255,0.06);"><strong>Omini 安全审查：</strong>${escapeHtml(spec.ominiCriticReview.review)}</div>`
        : "";
      box.innerHTML = `
        <div style="margin-bottom:4px;"><strong>涉及软件链路：</strong>${escapeHtml(apps || "自动识别")}</div>
        <div style="margin-bottom:4px;"><strong>安全体检评分：</strong><span class="pill ${lintOk ? "wfagent-badge-pass" : "wfagent-badge-gate"}">${lintReport?.score ?? 100} 分 (${lintOk ? "安全校验通过" : "存在告警"})</span></div>
        <div style="margin-bottom:4px;"><strong>安全护栏：</strong>${(spec.safetyBoundaries || []).slice(0, 3).map((x) => escapeHtml(x)).join(" · ")}</div>
        <div><strong>独立验收项：</strong>${(spec.acceptanceCriteria || []).map((x) => escapeHtml(x)).join(" / ") || "动作后 UI/工具独立断言"}</div>
        ${criticHtml}
      `;
    }

    function wfagentRenderShadowPreviewsHtml(previews) {
      const list = Array.isArray(previews) ? previews : [];
      if (!list.length) return "";
      const items = list.slice(0, 5).map((p) => {
        if (!p || typeof p !== "object") return "";
        const tool = String(p.tool || p.action || "");
        const params = p.params && typeof p.params === "object" ? p.params : {};
        if (tool === "wechat_add_friend") {
          const acct = params.account ? `账号：${params.account}` : "";
          const rem = params.remark ? `备注：${params.remark}` : "";
          const gr = params.greeting ? `打招呼：「${params.greeting}」` : "（无自我介绍打招呼语）";
          const txt = [acct, rem, gr].filter(Boolean).join(" · ");
          return `<div>➕ <strong>微信加好友（Shadow 已拦截未真实外发）</strong>：${escapeHtml(txt)}</div>`;
        }
        if (tool === "crm_enroll") {
          const tags = Array.isArray(params.tags) ? params.tags.join(", ") : "";
          return `<div>📇 <strong>CRM 建档预览</strong>：${escapeHtml(params.target || "")}${tags ? ` · 标签 [${escapeHtml(tags)}]` : ""}</div>`;
        }
        if (tool === "memory_add") {
          return `<div>🧠 <strong>本我记忆预览</strong>：${escapeHtml(params.content || params.target || "")}</div>`;
        }
        if (p.action === "pause_for_human") {
          return `<div>✋ <strong>人工确认门禁</strong>：${escapeHtml(p.message || "发送前暂停确认")}</div>`;
        }
        return `<div>🛡️ <strong>${escapeHtml(tool || "拦截动作")}</strong>：${escapeHtml(JSON.stringify(params || p).slice(0, 120))}</div>`;
      }).filter(Boolean).join("");
      return items ? `<div class="wfagent-shadow-preview">${items}</div>` : "";
    }

    function wfagentRenderTimeline(sessionDoc) {
      const pill = document.getElementById("wfagentStatusPill");
      const box = document.getElementById("wfagentTimelineBox");
      if (pill) {
        const sMap = {
          verified: ["✅ 已实机验证可复用", "pill wfagent-badge-pass"],
          shadow_verified: ["🛡️ 影子调试通过（外发已安全预览）", "pill wfagent-badge-fix"],
          dry_run_passed: ["🧪 静态方案演练通过", "pill ok"],
          paused_auth_gate: ["🔐 遇到登录/授权弹窗已暂停", "pill wfagent-badge-gate"],
          needs_human_demo: ["🎬 连续同因失败，建议录制一次人工示范", "pill wfagent-badge-gate"],
        };
        const chosen = sMap[sessionDoc?.status] || [`状态：${sessionDoc?.status || "完成"}`, "pill"];
        pill.textContent = chosen[0];
        pill.className = chosen[1];
      }
      if (!box) return;
      const rounds = sessionDoc?.debugRounds || [];
      if (!rounds.length) {
        box.innerHTML = `<div style="font-size:12px; color:var(--text-muted);">暂无调试轮次记录。</div>`;
        return;
      }
      const lastPreviews = Array.isArray(sessionDoc?.lastRun?.shadowPreviews) ? sessionDoc.lastRun.shadowPreviews : [];
      box.innerHTML = rounds.map((r, idx) => {
        const artName = r.artifactName || (r.screenshotPath ? String(r.screenshotPath).split(/[\\/]/).pop() : "");
        const thumbHtml = artName
          ? `<a href="/api/app-use/artifact/${encodeURIComponent(artName)}" target="_blank" title="点击查看高清截图存证" style="display:inline-flex; align-items:center; gap:6px; margin-top:4px; text-decoration:none;"><img src="/api/app-use/artifact/${encodeURIComponent(artName)}" alt="调试截图" style="width:96px; max-height:60px; object-fit:cover; border-radius:6px; border:1px solid var(--border);" loading="lazy" /><span style="font-size:11px; color:var(--text-muted);">📸 查看界面截图</span></a>`
          : "";
        const roundPreviews = Array.isArray(r.shadowPreviews) && r.shadowPreviews.length
          ? r.shadowPreviews
          : (idx === rounds.length - 1 ? lastPreviews : []);
        const previewHtml = wfagentRenderShadowPreviewsHtml(roundPreviews);
        const modeOrEvRaw = String(r.evidenceLevel || r.executionMode || "");
        const modeOrEvLabel = WFAGENT_STATUS_LABELS[modeOrEvRaw] || modeOrEvRaw;
        return `
        <div class="wfagent-round-card">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap;">
            <strong>第 ${r.round} 轮 · 流程 v${r.workflowVersion} (${escapeHtml(modeOrEvLabel)})</strong>
            <span class="pill ${r.ok ? "wfagent-badge-pass" : "wfagent-badge-gate"}">${r.ok ? "✅ 全部断言通过" : `❌ ${escapeHtml(r.failureCategory || r.errorCode || "未通过")}`}</span>
          </div>
          ${r.error ? `<div style="color:#b91c1c; font-size:11.5px;">失败原因：${escapeHtml(r.error)}</div>` : ""}
          ${r.patchSummary ? `<div style="color:#b45309; font-size:11.5px;">🔧 自动诊断与补丁：${escapeHtml(r.patchSummary)}</div>` : ""}
          ${(r.shadowPreviewsCount || 0) > 0 ? `<div style="color:var(--text-secondary); font-size:11.5px;">🛡️ Shadow 模式已安全拦截 ${r.shadowPreviewsCount} 处高风险外发/门禁</div>` : ""}
          ${previewHtml}
          ${thumbHtml}
        </div>
      `;
      }).join("");
    }

    async function wfagentProposeSpec() {
      const goal = document.getElementById("wfagentGoalInput")?.value?.trim() || "";
      if (!goal) { showToast("请先输入你的场景需求"); return; }
      const useCritic = Boolean(document.getElementById("wfagentOminiChk")?.checked);
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const btn = document.getElementById("wfagentSpecBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 正在识别软件与生成 Spec…"; }
      try {
        const { data } = await apiJson("/api/workflow-agent/spec", {
          method: "POST",
          body: JSON.stringify({ goal, agent_id: agentId, inspect_live: true, use_omini_critic: useCritic }),
        });
        if (data?.ok) {
          wfagentRenderSpec(data.spec, data.lintReport);
          if (data.workflow) renderAppUseWorkflow(data.workflow);
          document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data.spec, null, 2);
          showToast("已生成 OpenSpec 方案与独立验收标准");
        } else {
          showToast(data?.error || "Spec 生成失败");
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "1️⃣ 生成方案与验收标准 (Spec)"; }
      }
    }

    function wfagentRunAuthorDebugClick() {
      const mode = document.getElementById("wfagentModeSelect")?.value || "shadow";
      if (mode === "live" && !WFAGENT_LIVE_ARMED) {
        WFAGENT_LIVE_ARMED = true;
        const btn = document.getElementById("wfagentRunBtn");
        if (btn) btn.textContent = "⚠️ 再次点击确认实机联跑调试";
        clearTimeout(WFAGENT_LIVE_TIMER);
        WFAGENT_LIVE_TIMER = setTimeout(wfagentResetLiveArm, 5000);
        return;
      }
      wfagentResetLiveArm();
      wfagentRunAuthorDebug();
    }

    async function wfagentRunAuthorDebug() {
      const goal = document.getElementById("wfagentGoalInput")?.value?.trim() || "";
      if (!goal) { showToast("请先输入你想让 AI 自建的场景需求"); return; }
      const mode = document.getElementById("wfagentModeSelect")?.value || "shadow";
      const maxRounds = Number(document.getElementById("wfagentMaxRoundsInput")?.value || 4) || 4;
      const useCritic = Boolean(document.getElementById("wfagentOminiChk")?.checked);
      const autoExport = Boolean(document.getElementById("wfagentExportSkillChk")?.checked);
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const btn = document.getElementById("wfagentRunBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ AI 正在自建并多轮调试…"; }
      try {
        const { data } = await apiJson("/api/workflow-agent/author-debug", {
          method: "POST",
          body: JSON.stringify({
            goal,
            agent_id: agentId,
            mode,
            max_debug_rounds: maxRounds,
            confirm_run: mode === "live",
            respect_human_guard: true,
            inspect_live: true,
            use_omini_critic: useCritic,
            auto_export_skill: autoExport,
          }),
        });
        if (data?.spec) wfagentRenderSpec(data.spec, data.spec.lintReport);
        wfagentRenderTimeline(data);
        if (data?.workflow) renderAppUseWorkflow(data.workflow);
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        await appuseRefreshWorkflowsList();
        await appuseRefreshRuns();
        showToast(data?.ok ? `自调试成功 (${data.roundsUsed} 轮 · ${data.status})` : `已结束 (${data?.status || data?.error || "需关注"})`);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "2️⃣ 自动写流程并自己调试好"; }
      }
    }

    async function wfagentDebugSaved(encodedId) {
      const wid = decodeURIComponent(encodedId);
      await wfagentDebugWorkflowById(wid);
    }

    async function wfagentDebugCurrentWorkflow() {
      if (!APPUSE_CURRENT_WF?.id) { showToast("请先生成或载入一条已保存流程"); return; }
      await wfagentDebugWorkflowById(APPUSE_CURRENT_WF.id);
    }

    async function wfagentDebugWorkflowById(wid) {
      const mode = document.getElementById("wfagentModeSelect")?.value || "shadow";
      const maxRounds = Number(document.getElementById("wfagentMaxRoundsInput")?.value || 3) || 3;
      const agentId = document.getElementById("appuseAgentSelect")?.value || "";
      const btn = document.getElementById("wfagentRepairCurrentBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 智能诊断修复中…"; }
      try {
        const { data } = await apiJson("/api/workflow-agent/debug", {
          method: "POST",
          body: JSON.stringify({
            workflow_id: wid,
            mode: mode === "live" ? "shadow" : mode,
            max_debug_rounds: maxRounds,
            confirm_run: false,
            agent_id: agentId,
          }),
        });
        wfagentRenderTimeline(data);
        if (data?.workflow) renderAppUseWorkflow(data.workflow);
        document.getElementById("appuseRunReceiptBox").textContent = JSON.stringify(data, null, 2);
        await appuseRefreshWorkflowsList();
        showToast(data?.ok ? "智能修复与重跑验证通过" : `修复未完成：${data?.status || data?.error || ""}`);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "🔧 对当前已载入流程一键智能修复"; }
      }
    }

    async function wfagentLoadSessions() {
      try {
        const { data } = await apiJson("/api/workflow-agent/sessions?limit=5");
        const latest = (data?.sessions || [])[0];
        if (latest) {
          if (latest.spec) wfagentRenderSpec(latest.spec, latest.spec.lintReport);
          wfagentRenderTimeline(latest);
        }
      } catch (e) { /* ignore */ }
      await wfagentLoadChats(true);
    }

    // Conversational Chat-to-Workflow & Chat-to-Edit (v3.2)
    let WFAGENT_CHAT_ID = "";
    let WFAGENT_CHAT_MESSAGES = [];
    let WFAGENT_CHATS_LIST = [];

    function wfagentGetParamsSafe() {
      try {
        const raw = document.getElementById("appuseRunParamsInput")?.value?.trim() || "{}";
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
      } catch (e) {
        return {};
      }
    }

    function wfagentRenderChatLog(messages, collectedConfig) {
      const logEl = document.getElementById("wfagentChatLog");
      if (!logEl) return;
      const list = Array.isArray(messages) ? messages : [];
      if (!list.length) {
        logEl.innerHTML = `
          <div class="wfagent-chat-msg is-assistant">你好！直接用大白话告诉我你想让软件自动做什么（例如「帮我搞个飞书同步」或「帮我把钉钉客户提取微信号加微信」），我会通过几个简单的选择题帮你理清条件、客户备注和确认门禁，然后自动生成并安全试跑。</div>
          <div class="kb-chip-row" style="margin:2px 0 0;">
            <button type="button" class="kb-chip" onclick="wfagentPickChatOption('${encArg("帮我搞个飞书同步")}')">💬 试一试：帮我搞个飞书同步</button>
            <button type="button" class="kb-chip" onclick="wfagentPickChatOption('${encArg("帮我把钉钉客户提取微信号加微信")}')">🔔 试一试：钉钉客户引流加微信</button>
            <button type="button" class="kb-chip" onclick="wfagentPickChatOption('${encArg("读取飞书待办汇总并写文本简报")}')">📋 试一试：飞书待办写简报</button>
          </div>
        `;
        return;
      }
      logEl.innerHTML = list.map((m) => {
        const isUser = m.role === "user";
        const roleLabel = isUser ? "你" : "AI 流程助手";
        const tsTxt = m.at ? ` · ${escapeHtml(String(m.at).slice(11, 19))}` : "";
        return `
          <div class="wfagent-chat-msg ${isUser ? "is-user" : "is-assistant"}">
            <div style="font-size:10.5px; color:var(--text-muted); margin-bottom:2px;">${roleLabel}${tsTxt}</div>
            <div>${escapeHtml(m.text || "")}</div>
          </div>
        `;
      }).join("");
      logEl.scrollTop = logEl.scrollHeight;
    }

    function wfagentRenderChatOptions(phase, questions, collectedConfig) {
      const box = document.getElementById("wfagentChatOptions");
      if (!box) return;
      const parts = [];
      const cfg = collectedConfig && typeof collectedConfig === "object" ? collectedConfig : {};
      const cfgTags = [];
      const appLabels = Array.isArray(cfg.targetAppLabels) && cfg.targetAppLabels.length
        ? cfg.targetAppLabels
        : (Array.isArray(cfg.targetApps) ? cfg.targetApps.map(wfagentFormatAppLabel) : []);
      if (appLabels.length) {
        cfgTags.push(`软件：${appLabels.join(" → ")}`);
      }
      if (cfg.remarkPrefix) {
        cfgTags.push(`备注前缀：${cfg.remarkPrefix}`);
      }
      if (cfg.skipGreeting) {
        cfgTags.push("不发自我介绍");
      } else if (cfg.greeting) {
        cfgTags.push(`话术：${String(cfg.greeting).slice(0, 18)}${String(cfg.greeting).length > 18 ? "…" : ""}`);
      }
      if (cfg.requireConfirm !== undefined) {
        cfgTags.push(cfg.requireConfirm ? "外发需人工确认" : "无需外发门禁");
      }
      if (cfgTags.length) {
        parts.push(`<div style="display:flex; gap:6px; flex-wrap:wrap;">${cfgTags.map((t) => `<span class="pill" style="font-size:11px;">${escapeHtml(t)}</span>`).join("")}</div>`);
      }
      const qList = Array.isArray(questions) ? questions : [];
      qList.forEach((q) => {
        const opts = Array.isArray(q.options) ? q.options : [];
        const qTitle = q.question ? `<div style="font-size:11.5px; font-weight:600; color:var(--text-secondary); margin-bottom:4px;">${escapeHtml(q.question)}</div>` : "";
        const pills = opts.map((opt) => `<button type="button" class="kb-chip" onclick="wfagentPickChatOption('${encArg(opt)}')">${escapeHtml(opt)}</button>`).join("");
        parts.push(`<div>${qTitle}<div class="kb-chip-row" style="margin-bottom:2px;">${pills}</div></div>`);
      });
      if (phase === "ready_to_build") {
        parts.push(`
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button type="button" class="btn-solid sm" onclick="wfagentConfirmChatBuild()">✅ 确认并自动调试</button>
            <span style="font-size:11.5px; color:var(--text-muted);">也可以继续补充条件，或直接点左侧按钮开始生成并调试。</span>
          </div>
        `);
      } else if (phase === "built_and_debugged") {
        parts.push(`<div style="display:flex; gap:6px; align-items:center;"><span class="pill wfagent-badge-pass">🎉 已完成生成与自动调试 · 可在下方继续「一句话改当前流程」</span></div>`);
      }
      box.innerHTML = parts.join("");
    }

    function wfagentPickChatOption(encodedOption) {
      const opt = decodeURIComponent(encodedOption || "");
      if (!opt) return;
      wfagentSendChat(opt);
    }

    function wfagentConfirmChatBuild() {
      wfagentSendChat("确认开始调试");
    }

    function wfagentResetChat() {
      WFAGENT_CHAT_ID = "";
      WFAGENT_CHAT_MESSAGES = [];
      const sel = document.getElementById("wfagentChatHistorySelect");
      if (sel) sel.value = "";
      const inp = document.getElementById("wfagentChatInput");
      if (inp) { inp.value = ""; inp.focus(); }
      wfagentRenderChatLog([], {});
      wfagentRenderChatOptions("", [], {});
      showToast("已开启新的对话式建流程会话");
    }

    function wfagentApplyChatPayload(data) {
      if (!data) return;
      if (data.chatId) WFAGENT_CHAT_ID = data.chatId;
      if (Array.isArray(data.messages)) {
        WFAGENT_CHAT_MESSAGES = data.messages;
      } else if (data.assistantReply) {
        WFAGENT_CHAT_MESSAGES = [...WFAGENT_CHAT_MESSAGES, { role: "assistant", text: data.assistantReply }];
      }
      wfagentRenderChatLog(WFAGENT_CHAT_MESSAGES, data.collectedConfig);
      wfagentRenderChatOptions(data.phase, data.questions, data.collectedConfig);
      if (data.collectedConfig?.goal) {
        const goalEl = document.getElementById("wfagentGoalInput");
        if (goalEl) goalEl.value = data.collectedConfig.goal;
      }
      if (data.spec) wfagentRenderSpec(data.spec, data.spec.lintReport || data.workflow?.lintReport);
      if (data.workflow) renderAppUseWorkflow(data.workflow);
      if (data.debugSession) wfagentRenderTimeline(data.debugSession);
      if (data.debugSession || data.workflow) {
        const receiptEl = document.getElementById("appuseRunReceiptBox");
        if (receiptEl) receiptEl.textContent = JSON.stringify(data.debugSession || data.workflow, null, 2);
      }
    }

    async function wfagentLoadChats(autoRestoreLatest) {
      try {
        const { data } = await apiJson("/api/workflow-agent/chats?limit=20");
        const chats = Array.isArray(data?.chats) ? data.chats : [];
        WFAGENT_CHATS_LIST = chats;
        const sel = document.getElementById("wfagentChatHistorySelect");
        if (sel) {
          sel.innerHTML = `<option value="">最近对话会话 (${chats.length})…</option>` + chats.map((c) => {
            const firstMsg = (c.messages || []).find((m) => m.role === "user")?.text || c.collectedConfig?.goal || c.chatId;
            const shortTitle = String(firstMsg || c.chatId).slice(0, 22);
            const phaseLabel = WFAGENT_PHASE_LABELS[c.phase] || c.phase || "";
            return `<option value="${escapeHtml(c.chatId)}">${escapeHtml(shortTitle)}${phaseLabel ? ` (${escapeHtml(phaseLabel)})` : ""}</option>`;
          }).join("");
          if (WFAGENT_CHAT_ID && chats.some((c) => c.chatId === WFAGENT_CHAT_ID)) {
            sel.value = WFAGENT_CHAT_ID;
          }
        }
        if (autoRestoreLatest && !WFAGENT_CHAT_ID && chats.length && !WFAGENT_CHAT_MESSAGES.length) {
          wfagentRenderChatLog([], {});
        } else if (!WFAGENT_CHAT_MESSAGES.length) {
          wfagentRenderChatLog([], {});
        }
      } catch (e) {
        if (!WFAGENT_CHAT_MESSAGES.length) wfagentRenderChatLog([], {});
      }
    }

    function wfagentSelectHistoryChat(chatId) {
      if (!chatId) { wfagentResetChat(); return; }
      const found = WFAGENT_CHATS_LIST.find((c) => c.chatId === chatId);
      if (!found) return;
      WFAGENT_CHAT_ID = found.chatId;
      wfagentApplyChatPayload(found);
      showToast("已恢复历史对话会话");
    }

    async function wfagentPostJson(url, payload) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
      let data = {};
      try {
        data = await res.json();
      } catch (e) {
        data = { ok: false, error: "HTTP " + res.status };
      }
      return { status: res.status, data };
    }

    async function wfagentSendChat(overrideMsg) {
      const inp = document.getElementById("wfagentChatInput");
      const msg = String(overrideMsg !== undefined ? overrideMsg : (inp?.value || "")).trim();
      if (!msg) { showToast("请先输入想法或点击上方选项"); return; }
      if (inp && overrideMsg === undefined) inp.value = "";
      WFAGENT_CHAT_MESSAGES = [...WFAGENT_CHAT_MESSAGES, { role: "user", text: msg }];
      wfagentRenderChatLog(
        [...WFAGENT_CHAT_MESSAGES, { role: "assistant", text: "⏳ 正在分析你的需求并准备方案…" }],
        {}
      );
      const btn = document.getElementById("wfagentChatSendBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 思考中…"; }
      try {
        const mode = document.getElementById("wfagentModeSelect")?.value || "shadow";
        const agentId = document.getElementById("appuseAgentSelect")?.value || "";
        const { data } = await wfagentPostJson("/api/workflow-agent/chat", {
          chat_id: WFAGENT_CHAT_ID || "",
          message: msg,
          agent_id: agentId,
          mode,
          auto_run_on_confirm: true,
          params: wfagentGetParamsSafe(),
        });
        if (data?.ok) {
          wfagentApplyChatPayload(data);
          if (data.workflow || data.debugSession) {
            await appuseRefreshWorkflowsList();
            await appuseRefreshRuns();
          }
          await wfagentLoadChats(false);
          if (data.phase === "built_and_debugged") {
            showToast("对话需求已转为可复用工作流并完成自动调试");
          }
        } else {
          const errMsg = data?.error || "对话请求失败，请重试";
          WFAGENT_CHAT_MESSAGES = [...WFAGENT_CHAT_MESSAGES, { role: "assistant", text: `⚠️ ${errMsg}` }];
          wfagentRenderChatLog(WFAGENT_CHAT_MESSAGES, {});
          showToast(errMsg);
        }
      } catch (err) {
        const errMsg = err?.message || String(err || "对话请求异常");
        WFAGENT_CHAT_MESSAGES = [...WFAGENT_CHAT_MESSAGES, { role: "assistant", text: `⚠️ ${errMsg}` }];
        wfagentRenderChatLog(WFAGENT_CHAT_MESSAGES, {});
        showToast(errMsg);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "发送"; }
      }
    }

    function wfagentFillEditChip(kind) {
      const inp = document.getElementById("wfagentEditInput");
      if (!inp) return;
      if (kind === "remark") {
        inp.value = "把备注前缀改成 飞书VIP-";
      } else if (kind === "branch") {
        inp.value = "如果是老客户就跳过，不重复加好友";
      } else if (kind === "crm_tag") {
        inp.value = "给CRM加标签 高意向客户";
      } else if (kind === "greeting") {
        inp.value = "把打招呼语改成 你好呀，我是智拓巨浪的安晓心，这边加你微信发方案～";
      } else if (kind === "gate") {
        inp.value = "在发送或加好友前加一步人工确认门禁";
      }
      inp.focus();
    }

    function wfagentFormatMsgItem(item) {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        return item.message || item.summary || item.code || JSON.stringify(item);
      }
      return String(item ?? "");
    }

    function wfagentRenderEditDiff(data) {
      const box = document.getElementById("wfagentEditDiffBox");
      if (!box) return;
      if (!data) return;
      const lint = data.lintReport || {};
      const lintOk = lint.ok !== false;
      const lintBadge = `<span class="pill ${lintOk ? "wfagent-badge-pass" : "wfagent-badge-gate"}" style="font-size:11px;">安全体检 ${lint.score ?? 100} 分 (${lintOk ? "通过" : "已拦截风险"})</span>`;
      if (!data.ok) {
        const errs = Array.isArray(lint.errors) && lint.errors.length
          ? `<div style="margin-top:4px; color:#b91c1c;">${lint.errors.map((e) => escapeHtml(wfagentFormatMsgItem(e))).join("；")}</div>`
          : "";
        box.innerHTML = `<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;"><span class="pill wfagent-badge-gate">❌ 未应用修改（保留原版）</span>${lintBadge}</div><div style="margin-top:4px; color:#b91c1c;">${escapeHtml(data.error || "修改未通过安全校验")}</div>${errs}`;
        return;
      }
      const prevVer = Number(data.previousVersion || 0);
      const nextVer = Number(data.newVersion || 0);
      const edits = Array.isArray(data.appliedEdits) && data.appliedEdits.length
        ? `<div style="margin-top:4px;"><strong>已应用修改：</strong>${data.appliedEdits.map((x) => escapeHtml(wfagentFormatMsgItem(x))).join(" · ")}</div>`
        : "";
      if (data.rolledBack) {
        box.innerHTML = `<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;"><span class="pill wfagent-badge-pass" style="font-size:11px;">↩️ 已撤销并回滚 (v${prevVer || "?"} → v${nextVer || 1})</span></div>${edits}`;
        return;
      }
      const verTag = `<span class="pill ok" style="font-size:11px;">v${prevVer || 1} → v${nextVer || 2}</span>`;
      const vRun = data.verificationRun || {};
      const vStatusTxt = WFAGENT_STATUS_LABELS[vRun.status] || vRun.status;
      const vBadge = vRun.status ? `<span class="pill ${vRun.ok ? "wfagent-badge-pass" : "wfagent-badge-fix"}" style="font-size:11px;">回归验证：${escapeHtml(vStatusTxt)}</span>` : "";
      const undoBtn = (prevVer > 0 && nextVer > prevVer)
        ? `<button type="button" class="btn-outline sm" style="padding:2px 8px; font-size:11px;" onclick="wfagentUndoLastEdit()">↩️ 撤销本次修改（回滚到 v${escapeHtml(String(prevVer))}）</button>`
        : "";
      const diffs = Array.isArray(data.stepDiffs) && data.stepDiffs.length
        ? `<ul style="margin:4px 0 0 18px; padding:0;">${data.stepDiffs.map((d) => `<li>${escapeHtml(wfagentFormatMsgItem(d))}</li>`).join("")}</ul>`
        : "";
      box.innerHTML = `<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">${verTag}${lintBadge}${vBadge}${undoBtn}</div>${edits}${diffs}`;
    }

    async function wfagentUndoLastEdit() {
      if (!APPUSE_CURRENT_WF?.id) {
        showToast("当前没有可回滚的工作流");
        return;
      }
      const { data } = await apiJson("/api/app-use/rollback", {
        method: "POST",
        body: JSON.stringify({ workflow_id: APPUSE_CURRENT_WF.id, revision_index: -1 }),
      });
      if (data?.ok && data.workflow) {
        renderAppUseWorkflow(data.workflow);
        await appuseRefreshWorkflowsList();
        const box = document.getElementById("wfagentEditDiffBox");
        if (box) {
          const fromVer = data.workflow.rolledBackFromVersion || "";
          box.innerHTML = `<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;"><span class="pill wfagent-badge-pass" style="font-size:11px;">↩️ 已撤销上次修改并回滚到 v${escapeHtml(String(fromVer || data.workflow.version || 1))}</span></div>`;
        }
        showToast("已撤销本次修改并恢复历史版本");
      } else {
        showToast(data?.error || "暂无可回滚的历史版本");
      }
    }

    async function wfagentChatEditCurrent() {
      if (!APPUSE_CURRENT_WF?.id) {
        showToast("请先生成或载入一条要修改的工作流");
        return;
      }
      const inp = document.getElementById("wfagentEditInput");
      const instruction = inp?.value?.trim() || "";
      if (!instruction) {
        showToast("请输入一句话修改要求，例如：把备注前缀改成 飞书VIP-");
        return;
      }
      const btn = document.getElementById("wfagentEditBtn");
      const prev = btn ? btn.textContent : "✏️ 一句话修改并回归验证";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 修改并回归验证中…"; }
      try {
        const rawMode = document.getElementById("wfagentModeSelect")?.value || "shadow";
        const safeMode = rawMode === "dry_run" ? "dry_run" : "shadow";
        const agentId = document.getElementById("appuseAgentSelect")?.value || "";
        const { data } = await wfagentPostJson("/api/workflow-agent/chat-edit", {
          workflow_id: APPUSE_CURRENT_WF.id,
          instruction,
          agent_id: agentId,
          mode: safeMode,
          auto_verify: true,
          confirm_run: false,
          respect_human_guard: true,
          params: wfagentGetParamsSafe(),
        });
        wfagentRenderEditDiff(data);
        if (data?.ok) {
          if (inp) inp.value = "";
          if (data.workflow) renderAppUseWorkflow(data.workflow);
          if (data.verificationRun) {
            if (Array.isArray(data.verificationRun.debugRounds)) {
              wfagentRenderTimeline(data.verificationRun);
            }
            const receiptEl = document.getElementById("appuseRunReceiptBox");
            if (receiptEl) receiptEl.textContent = JSON.stringify(data, null, 2);
          }
          await appuseRefreshWorkflowsList();
          showToast(`流程已升级至 v${data.newVersion || "?"} 并完成回归验证`);
        } else {
          showToast(data?.error || "修改未通过校验，已保留原版本");
        }
      } catch (err) {
        const errObj = { ok: false, error: err?.message || String(err || "修改请求失败"), lintReport: { ok: false, score: 0, errors: [] } };
        wfagentRenderEditDiff(errObj);
        showToast(errObj.error);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prev; }
      }
    }

    /* ---------- 朋友圈 AI 拟评 & 电话前一键速览 / 话术提词卡 ---------- */
    const MOMENTS_SUGGEST_ALT_POOL = {};

    function applyMomentsAlt(rowIdx, altIdx) {
      const entry = MOMENTS_SUGGEST_ALT_POOL[rowIdx];
      if (!entry) return;
      const alt = entry.alts && entry.alts[altIdx];
      if (!alt) return;
      const input = document.getElementById("momentsComment_" + entry.postKey);
      if (input) {
        input.value = alt;
        input.focus();
        showToast("已填入备选评论");
      }
    }

    async function momentsSuggestComment(encodedKey, rowIdx) {
      const postKey = decodeURIComponent(String(encodedKey || ""));
      if (!postKey) return;
      const btn = document.getElementById("momentsSuggestBtn_" + rowIdx);
      const input = document.getElementById("momentsComment_" + postKey);
      const hintEl = document.getElementById("momentsSuggestHint_" + rowIdx);
      const prevText = btn ? btn.textContent : "✨ AI 拟评";
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 拟写中…"; }
      try {
        const { status, data } = await apiJson("/api/moments/suggest-comment", {
          method: "POST",
          body: JSON.stringify({ postKey, style: "natural" }),
        });
        if (status === 403) {
          showToast("需要授权 read_moments：" + (data.error || ""));
          return;
        }
        if (!data || !data.ok) {
          showToast("AI 拟评失败：" + ((data && (data.error || data.error_code)) || "未知错误"));
          return;
        }
        const suggested = String(data.suggestedText || "").trim();
        if (input && suggested) {
          input.value = suggested;
          input.focus();
        }
        const alts = Array.isArray(data.alternatives) ? data.alternatives.filter(Boolean) : [];
        MOMENTS_SUGGEST_ALT_POOL[rowIdx] = { postKey, alts };
        if (hintEl) {
          const sourceLabel = data.usedLlm
            ? ("✨ AI 拟写" + (data.modelId ? " · " + data.modelId : ""))
            : (data.source === "policy_template" ? "📋 策略模板" : "⚡ 规则短评");
          const altHtml = alts.length
            ? ('<span style="color:var(--text-muted);">备选：</span>' + alts.map((a, idx) =>
                '<button type="button" class="btn-outline sm moments-alt-chip" onclick="applyMomentsAlt(' + rowIdx + ', ' + idx + ')">' + escapeHtml(a) + '</button>'
              ).join(""))
            : "";
          hintEl.innerHTML = '<span class="call-brief-stat-chip">' + escapeHtml(sourceLabel) + '</span>' + altHtml;
          hintEl.style.display = "flex";
        }
        showToast("已填入 AI 拟写评论");
      } catch (err) {
        showToast("AI 拟评失败：" + ((err && err.message) || err));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = prevText; }
      }
    }

    const CALL_BRIEF_STATE = {
      target: "",
      goal: "general",
      customGoal: "",
      useLlm: true,
      loading: false,
      lastData: null,
      copyPool: [],
    };

    function copyCallBriefText(text, toastMsg) {
      const str = String(text || "");
      if (!str) { showToast("暂无可复制内容"); return; }
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        navigator.clipboard.writeText(str).then(
          () => showToast(toastMsg || "已复制到剪贴板"),
          () => _fallbackCopyCallBrief(str, toastMsg)
        );
      } else {
        _fallbackCopyCallBrief(str, toastMsg);
      }
    }

    function _fallbackCopyCallBrief(str, toastMsg) {
      try {
        const ta = document.createElement("textarea");
        ta.value = str;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        showToast(toastMsg || "已复制到剪贴板");
      } catch (e) {
        showToast("复制失败，请手动选中复制");
      }
    }

    function registerCallBriefCopy(text) {
      const idx = CALL_BRIEF_STATE.copyPool.length;
      CALL_BRIEF_STATE.copyPool.push(String(text || ""));
      return idx;
    }

    function copyCallBriefItem(idx, toastMsg) {
      if (idx < 0 || idx >= CALL_BRIEF_STATE.copyPool.length) return;
      copyCallBriefText(CALL_BRIEF_STATE.copyPool[idx], toastMsg || "已复制到剪贴板");
    }

    function openCallBriefFromChat() {
      const pt = document.getElementById("previewTarget");
      const st = document.getElementById("sendTarget");
      const target = String((pt && pt.value) || (st && st.value) || "").trim();
      if (!target) {
        showToast("请先选择左侧会话或填写回复对象");
        if (pt) pt.focus();
        return;
      }
      openCallBrief(target);
    }

    function openCallBriefFromCrm() {
      const target = String(
        (SALES_CRM_ANALYSIS && SALES_CRM_ANALYSIS.person && SALES_CRM_ANALYSIS.person.displayName) ||
        (document.getElementById("crmTargetInput") && document.getElementById("crmTargetInput").value) ||
        ""
      ).trim();
      if (!target) {
        showToast("请先选择或输入客户名称");
        const inp = document.getElementById("crmTargetInput");
        if (inp) inp.focus();
        return;
      }
      openCallBrief(target);
    }

    function _syncCallBriefGoalUi() {
      const goal = CALL_BRIEF_STATE.goal || "general";
      document.querySelectorAll("#callBriefGoalPills .call-brief-goal-pill").forEach((b) => {
        b.classList.toggle("active", b.dataset.cbGoal === goal);
      });
      const sel = document.getElementById("callBriefGoalSelect");
      if (sel && sel.value !== goal) sel.value = goal;
      const customWrap = document.getElementById("callBriefCustomWrap");
      if (customWrap) customWrap.hidden = (goal !== "custom");
    }

    function openCallBrief(target, opts) {
      const cleanTarget = String(target || "").trim();
      if (!cleanTarget) { showToast("请先指定联系人"); return; }
      const options = opts || {};
      CALL_BRIEF_STATE.target = cleanTarget;
      if (options.goal) CALL_BRIEF_STATE.goal = String(options.goal);
      if (typeof options.useLlm === "boolean") CALL_BRIEF_STATE.useLlm = options.useLlm;
      _syncCallBriefGoalUi();
      const titleEl = document.getElementById("callBriefModalTitle");
      if (titleEl) titleEl.textContent = "📋 电话前速览 · " + cleanTarget;
      const overlay = document.getElementById("callBriefOverlay");
      if (overlay) overlay.classList.add("visible");
      refreshCallBrief(CALL_BRIEF_STATE.useLlm);
    }

    function hideCallBriefModal() {
      document.getElementById("callBriefOverlay")?.classList.remove("visible");
    }

    function switchCallBriefGoal(goal) {
      CALL_BRIEF_STATE.goal = String(goal || "general");
      _syncCallBriefGoalUi();
      if (CALL_BRIEF_STATE.goal === "custom") {
        const inp = document.getElementById("callBriefCustomGoalInput");
        if (inp) {
          inp.focus();
          if (inp.value.trim()) refreshCallBrief(CALL_BRIEF_STATE.useLlm);
        }
        return;
      }
      refreshCallBrief(CALL_BRIEF_STATE.useLlm);
    }

    async function refreshCallBrief(useLlm) {
      if (!CALL_BRIEF_STATE.target) return;
      CALL_BRIEF_STATE.useLlm = (useLlm !== false);
      CALL_BRIEF_STATE.loading = true;
      const customInp = document.getElementById("callBriefCustomGoalInput");
      CALL_BRIEF_STATE.customGoal = String((customInp && customInp.value) || "").trim();

      const aiBtn = document.getElementById("callBriefAiBtn");
      const fastBtn = document.getElementById("callBriefFastBtn");
      const badge = document.getElementById("callBriefModelBadge");
      const bodyEl = document.getElementById("callBriefContent");
      const covEl = document.getElementById("callBriefCoverageBar");
      if (aiBtn) aiBtn.disabled = true;
      if (fastBtn) fastBtn.disabled = true;
      if (badge) badge.textContent = CALL_BRIEF_STATE.useLlm ? "⏳ AI 深度研判中…" : "⚡ 快速汇总中…";
      if (covEl) covEl.innerHTML = '<span style="color:var(--text-muted);">正在汇总 5 路本地数据源…</span>';
      if (bodyEl) {
        bodyEl.innerHTML = '<div class="cb-card"><div style="font-size:13px; color:var(--text-secondary);">正在为您梳理「' +
          escapeHtml(CALL_BRIEF_STATE.target) + '」的聊天记录、Soul 记忆、朋友圈动态与 CRM 商机，请稍候…</div></div>';
      }

      try {
        const { status, data } = await apiJson("/api/call-brief", {
          method: "POST",
          body: JSON.stringify({
            target: CALL_BRIEF_STATE.target,
            goal: CALL_BRIEF_STATE.goal,
            custom_goal: CALL_BRIEF_STATE.customGoal,
            use_llm: CALL_BRIEF_STATE.useLlm,
          }),
        });
        if (status === 403) {
          if (badge) badge.textContent = "需要授权";
          if (bodyEl) {
            bodyEl.innerHTML = '<div class="cb-card"><div class="cb-card-title">需要授权 read_contacts</div><div style="font-size:13px; color:var(--text-secondary);">' +
              escapeHtml((data && data.error) || "请先在工作台开启权限授权") + '</div></div>';
          }
          return;
        }
        if (!data || !data.ok) {
          if (badge) badge.textContent = "生成失败";
          if (bodyEl) {
            bodyEl.innerHTML = '<div class="cb-card"><div class="cb-card-title">无法生成电话前速览</div><div style="font-size:13px; color:var(--danger);">' +
              escapeHtml((data && data.error) || "未知错误") + '</div></div>';
          }
          return;
        }
        CALL_BRIEF_STATE.lastData = data;
        renderCallBrief(data);
      } catch (err) {
        if (badge) badge.textContent = "请求异常";
        if (bodyEl) {
          bodyEl.innerHTML = '<div class="cb-card"><div class="cb-card-title">加载速览失败</div><div style="font-size:13px; color:var(--danger);">' +
            escapeHtml((err && err.message) || String(err)) + '</div></div>';
        }
      } finally {
        CALL_BRIEF_STATE.loading = false;
        if (aiBtn) aiBtn.disabled = false;
        if (fastBtn) fastBtn.disabled = false;
      }
    }

    function _renderCbList(items, emptyText) {
      const list = Array.isArray(items) ? items.filter((x) => String(x || "").trim()) : [];
      if (!list.length) return '<div style="color:var(--text-muted); font-size:12.5px;">' + escapeHtml(emptyText || "暂无记录") + '</div>';
      return '<ul class="cb-list">' + list.map((it) => '<li>' + escapeHtml(it) + '</li>').join("") + '</ul>';
    }

    function renderCallBrief(data) {
      CALL_BRIEF_STATE.copyPool = [];
      const titleEl = document.getElementById("callBriefModalTitle");
      if (titleEl) {
        titleEl.textContent = "📋 电话前速览 · " + (data.matchedTitle || data.target || CALL_BRIEF_STATE.target);
      }
      const badge = document.getElementById("callBriefModelBadge");
      if (badge) {
        if (data.usedLlm) {
          badge.textContent = "✨ AI 深度研判" + (data.modelId ? " · " + data.modelId : "");
        } else {
          badge.textContent = "⚡ 本地规则汇总" + (data.llmFallbackReason ? " · " + data.llmFallbackReason : "");
        }
      }

      const cov = data.dataCoverage || {};
      const covEl = document.getElementById("callBriefCoverageBar");
      if (covEl) {
        const momentsCount = Number(cov.momentsPosts || 0);
        const crmLabel = cov.hasCrmRecord ? (cov.crmStage || "已建档") : "未入漏斗";
        const nudgeHtml = momentsCount === 0
          ? '<span class="call-brief-moments-nudge"><span>尚未读取该联系人朋友圈</span>' +
            '<button type="button" class="btn-outline sm" onclick="hideCallBriefModal(); switchTab(\'moments\')">前往「朋友圈」读取 →</button></span>'
          : "";
        covEl.innerHTML = [
          '<span class="call-brief-stat-chip">💬 聊天消息 ' + (cov.chatMessages ?? 0) + ' 条</span>',
          '<span class="call-brief-stat-chip">◎ 朋友圈 ' + momentsCount + ' 条</span>',
          '<span class="call-brief-stat-chip">🤝 互赞/互评 ' + (cov.momentsMutualHits ?? 0) + ' 次</span>',
          '<span class="call-brief-stat-chip">🧠 Soul 记忆 ' + (cov.soulMemories ?? 0) + ' 条</span>',
          '<span class="call-brief-stat-chip">📈 CRM：' + escapeHtml(crmLabel) + '</span>',
          nudgeHtml,
        ].join("");
      }

      const sum = data.summaryCard || {};
      const mom = data.momentsInsights || {};
      const needs = data.needsAndFocus || {};
      const scripts = data.phoneScripts || {};
      const history = Array.isArray(data.historyHighlights) ? data.historyHighlights : [];

      const oneLinerCopy = registerCallBriefCopy(sum.oneLiner || "");
      const icebreakers = Array.isArray(mom.icebreakers) ? mom.icebreakers.filter(Boolean) : [];
      const recentPosts = Array.isArray(mom.recentPosts) ? mom.recentPosts : [];
      const postsHtml = recentPosts.length
        ? '<details style="margin-top:4px;" open><summary style="cursor:pointer; font-size:12.5px; font-weight:600; color:var(--text-secondary);">展开近期朋友圈原文（' + recentPosts.length + ' 条）</summary>' +
          '<div style="display:flex; flex-direction:column; gap:6px; margin-top:8px;">' +
          recentPosts.map((p) => {
            const metaBits = [p.timeText || "", p.likesCount ? ("👍 " + p.likesCount) : "", p.commentsCount ? ("💬 " + p.commentsCount) : ""].filter(Boolean).join(" · ");
            const bodyTxt = p.text || (Array.isArray(p.attachments) && p.attachments.length ? "[附件] " + p.attachments.join(" / ") : "（图片/动态）");
            return '<div class="cb-post-item"><div style="font-size:11.5px; color:var(--text-muted); margin-bottom:2px;">' + escapeHtml(metaBits || "近期动态") + '</div>' +
              '<div>' + escapeHtml(bodyTxt) + '</div></div>';
          }).join("") + '</div></details>'
        : '<div style="font-size:12.5px; color:var(--text-muted);">暂未读到该联系人的公开朋友圈原文（不会编造内容）。</div>';

      const openingIdx = registerCallBriefCopy(scripts.opening || "");
      const dqList = Array.isArray(scripts.discoveryQuestions) ? scripts.discoveryQuestions.filter(Boolean) : [];
      const dqAllIdx = registerCallBriefCopy(dqList.map((q, i) => (i + 1) + ". " + q).join("\n"));
      const objList = Array.isArray(scripts.objectionHandlers) ? scripts.objectionHandlers : [];
      const closingIdx = registerCallBriefCopy(scripts.closing || "");

      const bodyEl = document.getElementById("callBriefContent");
      if (!bodyEl) return;
      bodyEl.innerHTML = [
        '<section class="cb-card">' +
          '<div class="cb-card-head"><h3 class="cb-card-title">1 · 一句话速览与性格脾气</h3>' +
          '<button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + oneLinerCopy + ', \'已复制一句话速览\')">📋 复制速览</button></div>' +
          '<div class="cb-oneliner">' + escapeHtml(sum.oneLiner || "暂无足够上下文，建议温和寒暄开场。") + '</div>' +
          '<div class="cb-grid-2">' +
            '<div class="cb-subbox"><h4>🎭 脾气与沟通风格</h4><div>' + escapeHtml(sum.temperamentAndStyle || "待补充互动样本") + '</div></div>' +
            '<div class="cb-subbox"><h4>🌡️ 当前情绪基线</h4><div>' + escapeHtml(sum.emotionalTone || "平稳正常") + '</div></div>' +
          '</div>' +
          '<div class="cb-grid-2">' +
            '<div class="cb-subbox"><h4>✅ 建议做法 (Do\'s)</h4>' + _renderCbList(sum.dos, "保持自然真诚、节奏适中") + '</div>' +
            '<div class="cb-subbox"><h4>⛔ 忌讳雷区 (Don\'ts)</h4>' + _renderCbList(sum.donts, "避免生硬推销或连续追问") + '</div>' +
          '</div>' +
        '</section>',

        '<section class="cb-card">' +
          '<div class="cb-card-head"><h3 class="cb-card-title">2 · 近期朋友圈洞察与破冰话题</h3></div>' +
          '<div style="font-size:13px; color:var(--text);">' + escapeHtml(mom.summary || "暂无朋友圈洞察。") + '</div>' +
          (icebreakers.length
            ? '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;"><span style="font-size:12px; color:var(--text-muted);">破冰话术（点击复制）：</span>' +
              icebreakers.map((ib) => {
                const cidx = registerCallBriefCopy(ib);
                return '<button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + cidx + ', \'已复制破冰话题\')">💬 ' + escapeHtml(ib) + '</button>';
              }).join("") + '</div>'
            : "") +
          postsHtml +
        '</section>',

        '<section class="cb-card">' +
          '<div class="cb-card-head"><h3 class="cb-card-title">3 · 核心需求 · 关注点 · 未闭环事项 &amp; CRM 推进</h3></div>' +
          '<div class="cb-grid-2">' +
            '<div class="cb-subbox"><h4>🎯 核心需求</h4>' + _renderCbList(needs.coreNeeds, "待通过通话探需确认") + '</div>' +
            '<div class="cb-subbox"><h4>🔎 重点关注话题</h4>' + _renderCbList(needs.focusTopics, "暂无高频聚焦话题") + '</div>' +
          '</div>' +
          '<div class="cb-grid-2">' +
            '<div class="cb-subbox"><h4>⏳ 未闭环事项 (Open Loops)</h4>' + _renderCbList(needs.openLoops, "暂无待确认承诺或遗留问题") + '</div>' +
            '<div class="cb-subbox"><h4>📈 CRM 推进提示</h4><div>' + escapeHtml(needs.crmHint || "暂无 SalesCRM 阶段记录") + '</div></div>' +
          '</div>' +
        '</section>',

        '<section class="cb-card cb-script-card">' +
          '<div class="cb-card-head"><h3 class="cb-card-title">4 · 人工口语电话话术提词卡（目标：' + escapeHtml(data.goalLabel || data.goal || "综合沟通") + '）</h3></div>' +
          '<div class="cb-script-block">' +
            '<div class="cb-script-block-head"><span>📞 开场白</span><button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + openingIdx + ', \'已复制开场白\')">📋 复制</button></div>' +
            '<div class="cb-script-quote">' + escapeHtml(scripts.opening || "") + '</div>' +
          '</div>' +
          '<div class="cb-script-block">' +
            '<div class="cb-script-block-head"><span>❓ 探需提问列表</span>' +
            (dqList.length ? '<button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + dqAllIdx + ', \'已复制全部探需提问\')">📋 复制全部</button>' : "") +
            '</div>' +
            (dqList.length
              ? dqList.map((q, qi) => {
                  const qIdx = registerCallBriefCopy(q);
                  return '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px; font-size:13px;">' +
                    '<span>' + (qi + 1) + '. ' + escapeHtml(q) + '</span>' +
                    '<button type="button" class="btn-outline sm" style="flex-shrink:0;" onclick="copyCallBriefItem(' + qIdx + ', \'已复制提问\')">📋 复制</button></div>';
                }).join("")
              : '<div style="font-size:12.5px; color:var(--text-muted);">暂无预设提问</div>') +
          '</div>' +
          '<div class="cb-script-block">' +
            '<div class="cb-script-block-head"><span>🛡️ 常见异议拆解</span></div>' +
            (objList.length
              ? objList.map((oh) => {
                  const resp = String((oh && oh.response) || "");
                  const rIdx = registerCallBriefCopy(resp);
                  return '<div class="cb-obj-item">' +
                    '<div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">' +
                    '<strong style="color:var(--special, #e11d48);">异议：' + escapeHtml((oh && oh.concern) || "") + '</strong>' +
                    '<button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + rIdx + ', \'已复制异议回应\')">📋 复制回应</button></div>' +
                    '<div style="color:var(--text);">回应：' + escapeHtml(resp) + '</div></div>';
                }).join("")
              : '<div style="font-size:12.5px; color:var(--text-muted);">暂无预置异议拆解</div>') +
          '</div>' +
          '<div class="cb-script-block">' +
            '<div class="cb-script-block-head"><span>🤝 收口动作</span><button type="button" class="btn-outline sm" onclick="copyCallBriefItem(' + closingIdx + ', \'已复制收口话术\')">📋 复制</button></div>' +
            '<div class="cb-script-quote">' + escapeHtml(scripts.closing || "") + '</div>' +
          '</div>' +
        '</section>',

        '<section class="cb-card">' +
          '<div class="cb-card-head"><h3 class="cb-card-title">5 · 近期关键历史往来摘要（最多 8 条）</h3></div>' +
          _renderCbList(history.map((h) => typeof h === "string" ? h : JSON.stringify(h)), "暂无本地历史往来摘要") +
        '</section>',
      ].join("");
    }

    function copyFullCallBrief() {
      const d = CALL_BRIEF_STATE.lastData;
      if (!d) { showToast("请先等待速览加载完成"); return; }
      const sum = d.summaryCard || {};
      const mom = d.momentsInsights || {};
      const needs = d.needsAndFocus || {};
      const sc = d.phoneScripts || {};
      const lines = [
        "【电话前速览】" + (d.matchedTitle || d.target || "") + "（目标：" + (d.goalLabel || d.goal || "") + "）",
        "",
        "1. 一句话速览：" + (sum.oneLiner || ""),
        "   脾气与风格：" + (sum.temperamentAndStyle || ""),
        "   情绪基线：" + (sum.emotionalTone || ""),
        "   建议做法：" + ((sum.dos || []).join("；") || "—"),
        "   忌讳雷区：" + ((sum.donts || []).join("；") || "—"),
        "",
        "2. 朋友圈洞察：" + (mom.summary || ""),
        ((mom.icebreakers || []).length ? "   破冰话题：" + mom.icebreakers.join(" | ") : ""),
        "",
        "3. 核心需求与待闭环：",
        "   核心需求：" + ((needs.coreNeeds || []).join("；") || "—"),
        "   关注点：" + ((needs.focusTopics || []).join("；") || "—"),
        "   未闭环：" + ((needs.openLoops || []).join("；") || "—"),
        "   CRM 提示：" + (needs.crmHint || "—"),
        "",
        "4. 电话话术提词卡：",
        "   [开场白] " + (sc.opening || ""),
        "   [探需提问]",
        ...(sc.discoveryQuestions || []).map((q, i) => "   " + (i + 1) + ". " + q),
        "   [异议拆解]",
        ...(sc.objectionHandlers || []).map((o) => "   - 异议：" + (o.concern || "") + " -> 回应：" + (o.response || "")),
        "   [收口动作] " + (sc.closing || ""),
        "",
        "5. 近期关键往来：",
        ...(d.historyHighlights || []).map((h) => "   - " + h),
      ].filter((x) => x !== undefined);
      copyCallBriefText(lines.join("\n"), "已复制整张电话话术卡");
    }

    /* ---------- v3 Zero-FDE 向导 / 使用手册 / 测试好友 / #指令 / 测试与评分 ---------- */
    const WIZARD_STATE = { step: 1, discovered: null, trainResult: null, simCount: 0, autoOpened: false };
    const DRAFT_FEEDBACK_STATE = { target: "", incomingText: "", replyText: "", turnId: null, stars: 0, tags: new Set() };

    function renderSimpleMarkdown(md) {
      const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");
      const out = [];
      let inCode = false;
      let inList = false;
      const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
      const fmtInline = (s) => escapeHtml(s)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      for (const raw of lines) {
        if (raw.trim().startsWith("```")) {
          closeList();
          out.push(inCode ? "</pre>" : "<pre>");
          inCode = !inCode;
          continue;
        }
        if (inCode) { out.push(escapeHtml(raw) + "\n"); continue; }
        const t = raw.trim();
        if (!t) { closeList(); continue; }
        if (t === "---") { closeList(); out.push('<hr style="border:none;border-top:1px solid var(--border);margin:12px 0;" />'); continue; }
        const hm = t.match(/^(#{1,3})\s+(.*)$/);
        if (hm) {
          closeList();
          const lvl = hm[1].length;
          out.push(`<h${lvl}>${fmtInline(hm[2])}</h${lvl}>`);
          continue;
        }
        if (/^[-*]\s+/.test(t) || /^\d+\.\s+/.test(t)) {
          if (!inList) { out.push('<ul style="margin:4px 0 8px; padding-left:20px;">'); inList = true; }
          const body = t.replace(/^[-*]\s+|^\d+\.\s+/, "");
          out.push(`<li>${fmtInline(body)}</li>`);
          continue;
        }
        if (t.startsWith("> ")) {
          closeList();
          out.push(`<blockquote style="margin:6px 0;padding:6px 10px;border-left:3px solid var(--work-pine);background:var(--surface-soft);">${fmtInline(t.slice(2))}</blockquote>`);
          continue;
        }
        closeList();
        out.push(`<p style="margin:4px 0;">${fmtInline(t)}</p>`);
      }
      closeList();
      if (inCode) out.push("</pre>");
      return out.join("");
    }

    async function openUserGuideModal() {
      const overlay = document.getElementById("userGuideOverlay");
      const body = document.getElementById("userGuideBody");
      if (overlay) overlay.classList.add("visible");
      if (body) body.innerHTML = '<p class="hosting-empty">正在读取使用手册…</p>';
      try {
        const { status, data } = await apiJson("/api/docs/user-guide");
        if (status !== 200 || !data.ok) throw new Error(data.error || "读取失败");
        if (body) body.innerHTML = renderSimpleMarkdown(data.markdown || "");
      } catch (err) {
        if (body) body.innerHTML = `<p class="hosting-empty">读取使用手册失败：${escapeHtml(err.message || err)}</p>`;
      }
    }

    function hideUserGuideModal() {
      document.getElementById("userGuideOverlay")?.classList.remove("visible");
    }

    function goWizardStep(step) {
      WIZARD_STATE.step = step;
      for (let i = 1; i <= 4; i++) {
        const panel = document.getElementById("wizardStepPanel" + i);
        if (panel) panel.hidden = (i !== step);
      }
      document.querySelectorAll("#wizardStepPills .wizard-step-pill").forEach((el) => {
        const s = Number(el.dataset.wstep || 0);
        el.classList.toggle("active", s === step);
        el.classList.toggle("done", s < step);
      });
    }

    async function openOnboardingWizard(startStep = 1) {
      const overlay = document.getElementById("onboardingWizardOverlay");
      if (overlay) overlay.classList.add("visible");
      goWizardStep(startStep);
      try {
        const [{ data: statusData }, { data: packsData }] = await Promise.all([
          apiJson("/api/onboarding/status"),
          apiJson("/api/sales-packs"),
        ]);
        const prof = statusData.profile || {};
        const sel = document.getElementById("wizIndustryPack");
        const packs = packsData.packs || statusData.salesPacks || [];
        if (sel) {
          sel.innerHTML = (packs.length ? packs : [{ packId: "general_sales", name: "通用私域与顾问式销售" }])
            .map((pk) => `<option value="${escapeHtml(pk.packId)}" ${pk.packId === (prof.industryPack || "general_sales") ? "selected" : ""}>${escapeHtml(pk.name || pk.packId)} (${escapeHtml(pk.entryCount ?? "")}条)</option>`)
            .join("");
        }
        if (prof.ownerName) document.getElementById("wizOwnerName").value = prof.ownerName;
        if (prof.businessName) document.getElementById("wizBusinessName").value = prof.businessName;
        if (prof.productSummary) document.getElementById("wizProductSummary").value = prof.productSummary;
        if (Array.isArray(prof.ownerAliases) && prof.ownerAliases.length) {
          document.getElementById("wizOwnerAliases").value = prof.ownerAliases.join(", ");
        }
        if (Array.isArray(prof.testContacts) && prof.testContacts.length) {
          document.getElementById("wizTestContacts").value = prof.testContacts.join(", ");
        }
      } catch (err) { /* ignore initial load failure */ }
    }

    function hideOnboardingWizard() {
      try { localStorage.setItem("wb_wizard_dismissed", "1"); } catch (e) {}
      document.getElementById("onboardingWizardOverlay")?.classList.remove("visible");
    }

    async function wizardSubmitStep1() {
      const ownerName = (document.getElementById("wizOwnerName")?.value || "").trim();
      const businessName = (document.getElementById("wizBusinessName")?.value || "").trim();
      const productSummary = (document.getElementById("wizProductSummary")?.value || "").trim();
      const industryPack = (document.getElementById("wizIndustryPack")?.value || "general_sales").trim();
      const ownerAliases = (document.getElementById("wizOwnerAliases")?.value || "").split(/[,，\n]+/).map((s) => s.trim()).filter(Boolean);
      const testContacts = (document.getElementById("wizTestContacts")?.value || "").split(/[,，\n]+/).map((s) => s.trim()).filter(Boolean);
      const btn = document.getElementById("wizSaveStep1Btn");
      if (btn) btn.disabled = true;
      try {
        const { data } = await apiJson("/api/onboarding/setup", {
          method: "POST",
          body: JSON.stringify({ ownerName, businessName, productSummary, industryPack, ownerAliases, testContacts }),
        });
        if (!data.ok) throw new Error(data.error || "保存失败");
        showToast("已保存基础身份与行业话术包");
        goWizardStep(2);
        await wizardDiscoverCorpora();
      } catch (err) {
        showToast("保存失败: " + (err.message || err));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function wizardDiscoverCorpora() {
      const sessEl = document.getElementById("wizDiscoveredSessions");
      const archEl = document.getElementById("wizDiscoveredArchives");
      if (sessEl) sessEl.innerHTML = '<span class="hosting-empty">正在扫描高价值微信会话…</span>';
      if (archEl) archEl.innerHTML = '<span class="hosting-empty">正在扫描导出记录包…</span>';
      try {
        const { data } = await apiJson("/api/training/discover", { method: "POST", body: JSON.stringify({ limit: 15 }) });
        WIZARD_STATE.discovered = data;
        const sessions = data.sessions || [];
        const archives = data.archives || [];
        if (sessEl) {
          sessEl.innerHTML = sessions.length
            ? sessions.map((s, idx) => `<label style="display:flex;align-items:flex-start;gap:6px;margin-bottom:5px;cursor:pointer;">
                <input type="checkbox" class="wiz-sess-cb" value="${escapeHtml(s.target)}" ${idx < 3 ? "checked" : ""} style="width:auto;margin-top:3px;" />
                <span><strong>${escapeHtml(s.target)}</strong> (${escapeHtml(s.messageCount || 0)}条 · 分值${escapeHtml(s.score || 0)})<br><span style="color:var(--text-muted);font-size:11px;">${escapeHtml((s.reasonTags || []).join(" · "))}</span></span>
              </label>`).join("")
            : '<span class="hosting-empty">暂未发现可导入的本地会话记录，可直接在下方粘贴产品资料。</span>';
        }
        if (archEl) {
          archEl.innerHTML = archives.length
            ? archives.map((a) => `<label style="display:flex;align-items:flex-start;gap:6px;margin-bottom:5px;cursor:pointer;">
                <input type="checkbox" class="wiz-arch-cb" value="${escapeHtml(a.path)}" checked style="width:auto;margin-top:3px;" />
                <span><strong>${escapeHtml(a.name)}</strong><br><span style="color:var(--text-muted);font-size:11px;">${escapeHtml(a.transcriptEntry || a.path)}</span></span>
              </label>`).join("")
            : '<span class="hosting-empty">下载/桌面目录未扫到聊天记录导出包，可在下方手动输入路径。</span>';
        }
      } catch (err) {
        if (sessEl) sessEl.innerHTML = `<span class="hosting-empty">扫描失败: ${escapeHtml(err.message || err)}</span>`;
      }
    }

    async function wizardRunTraining() {
      const contactTargets = Array.from(document.querySelectorAll(".wiz-sess-cb:checked")).map((el) => el.value);
      const archivePaths = Array.from(document.querySelectorAll(".wiz-arch-cb:checked")).map((el) => el.value);
      const extraPath = (document.getElementById("wizExtraArchivePath")?.value || "").trim();
      if (extraPath) archivePaths.push(extraPath);
      const docText = (document.getElementById("wizProductDocText")?.value || "").trim();
      const docTexts = docText ? [{ name: "向导业务资料", text: docText }] : [];
      const btn = document.getElementById("wizRunTrainBtn");
      if (btn) { btn.disabled = true; btn.textContent = "⏳ 正在提炼话术…"; }
      try {
        const { data } = await apiJson("/api/training/run", {
          method: "POST",
          body: JSON.stringify({ contactTargets, archivePaths, docTexts, useLlm: false, autoPublishSafe: true }),
        });
        WIZARD_STATE.trainResult = data;
        renderWizardStep3(data);
        goWizardStep(3);
      } catch (err) {
        showToast("训练失败: " + (err.message || err));
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = "⚡ 开始自训练并提炼话术 →"; }
      }
    }

    function renderWizardStep3(report) {
      const statsBox = document.getElementById("wizTrainStatsBox");
      const vocabBox = document.getElementById("wizMinedVocabBox");
      const draftsBox = document.getElementById("wizDraftsList");
      const st = (report && report.stats) || {};
      if (statsBox) {
        statsBox.textContent = `本次共分析 ${st.conversationCount || 0} 段会话（${st.messageCount || 0} 条消息），提炼词汇 ${st.vocabularyCount || 0} 个，生成话术 ${st.synthesizedCount || 0} 条（安全自动发布 ${st.publishedCount || 0} 条，高风险待审核 ${st.draftCount || 0} 条）。`;
      }
      const vocab = (report && report.vocabulary) || [];
      if (vocabBox) {
        vocabBox.innerHTML = vocab.length
          ? vocab.map((v) => `<span class="chip" title="${escapeHtml(v.definition || "")}">${escapeHtml(v.term)} (${escapeHtml(v.frequency || 1)})</span>`).join("")
          : '<span class="hosting-empty">暂无新增业务词汇</span>';
      }
      const drafts = ((report && report.entries) || []).filter((e) => e.status === "draft" || e.needsApproval);
      if (draftsBox) {
        draftsBox.innerHTML = drafts.length
          ? drafts.map((d) => `<div style="border:1px solid var(--border);border-radius:8px;padding:8px;background:var(--surface-soft);">
              <label style="display:flex;align-items:center;gap:6px;font-weight:600;font-size:12.5px;margin-bottom:4px;">
                <input type="checkbox" class="wiz-draft-cb" value="${escapeHtml(d.id)}" checked style="width:auto;" />
                <span>${escapeHtml(d.title)}</span>
                <span class="pill warn">${escapeHtml((d.riskFlags || ["需复核"]).join(", "))}</span>
              </label>
              <textarea class="wiz-draft-body" data-entry-id="${escapeHtml(d.id)}" rows="2" style="font-size:12px;">${escapeHtml(d.body)}</textarea>
            </div>`).join("")
          : '<span class="hosting-empty">无高风险待审核草稿，安全条目已自动发布。</span>';
      }
    }

    async function wizardApproveDraftsAndNext() {
      const checked = Array.from(document.querySelectorAll(".wiz-draft-cb:checked")).map((el) => el.value);
      if (checked.length) {
        const edits = {};
        document.querySelectorAll(".wiz-draft-body").forEach((ta) => {
          const eid = ta.dataset.entryId;
          if (eid && checked.includes(eid)) edits[eid] = { body: ta.value };
        });
        try {
          await apiJson("/api/training/approve", { method: "POST", body: JSON.stringify({ entryIds: checked, edits }) });
          showToast(`已审核发布 ${checked.length} 条话术`);
        } catch (err) {
          showToast("审核发布失败: " + (err.message || err));
        }
      }
      goWizardStep(4);
    }

    async function wizardSendSimTurn() {
      const inp = document.getElementById("wizSimInput");
      const log = document.getElementById("wizSimChatLog");
      const msg = (inp?.value || "").trim();
      if (!msg) return;
      if (inp) inp.value = "";
      if (log) log.innerHTML += `<div class="sparring-msg peer"><strong>模拟客户：</strong>${escapeHtml(msg)}</div>`;
      try {
        const { data } = await apiJson("/api/sparring/chat", { method: "POST", body: JSON.stringify({ message: msg, contactName: "向导试跑客户" }) });
        WIZARD_STATE.simCount += 1;
        const sc = (data.autoScore && data.autoScore.overallScore !== undefined) ? ` [自评 ${data.autoScore.overallScore}分]` : "";
        if (log) {
          log.innerHTML += `<div class="sparring-msg self"><strong>AI 回复${escapeHtml(sc)}：</strong>${escapeHtml(data.replyText || data.error || "")}</div>`;
          log.scrollTop = log.scrollHeight;
        }
      } catch (err) {
        if (log) log.innerHTML += `<div class="sparring-msg sys">试跑出错: ${escapeHtml(err.message || err)}</div>`;
      }
    }

    function syncChatTestContactBtn(target) {
      const btn = document.getElementById("chatTestContactBtn");
      if (!btn) return;
      const clean = String(target || "").trim();
      const list = (STATE && STATE.testContacts) || [];
      const isTest = !!clean && list.some((c) => String(c.displayName || "").trim().toLowerCase() === clean.toLowerCase());
      btn.textContent = isTest ? "🧪 取消测试好友" : "🧪 设为测试好友";
      btn.classList.toggle("btn-solid", isTest);
      btn.classList.toggle("btn-outline", !isTest);
    }

    async function toggleTestContact(encTarget, enable) {
      const target = decodeURIComponent(encTarget);
      if (!target) return;
      try {
        const { data } = await apiJson("/api/test-contacts", {
          method: "POST",
          body: JSON.stringify({ name: target, enabled: !!enable }),
        });
        if (!data.ok) throw new Error(data.error || "操作失败");
        showToast(enable ? `已将「${target}」设为测试好友（允许 # 指令纠偏，且不计入 CRM）` : `已取消「${target}」的测试好友标记`);
        await loadOverview(false);
        syncChatTestContactBtn(document.getElementById("previewTarget")?.value || "");
      } catch (err) {
        showToast("设置测试好友失败: " + (err.message || err));
      }
    }

    async function toggleActiveChatTestContact() {
      const target = (document.getElementById("previewTarget")?.value || document.getElementById("sendTarget")?.value || "").trim();
      if (!target) { showToast("请先选择或填写会话对象"); return; }
      const list = (STATE && STATE.testContacts) || [];
      const isTest = list.some((c) => String(c.displayName || "").trim().toLowerCase() === target.toLowerCase());
      await toggleTestContact(encodeURIComponent(target), !isTest);
    }

    function onComposerTextInput() {
      const box = document.getElementById("sendText");
      const banner = document.getElementById("supervisorDirectiveBanner");
      if (!box || !banner) return;
      const val = String(box.value || "").trim();
      const isDir = /^[#＃]\s*\S/.test(val);
      banner.hidden = !isDir;
    }

    async function executeSupervisorDirectiveFromComposer() {
      const target = (document.getElementById("previewTarget")?.value || document.getElementById("sendTarget")?.value || "模拟测试客户").trim();
      const box = document.getElementById("sendText");
      const text = (box?.value || "").trim();
      if (!text) return;
      try {
        const { data } = await apiJson("/api/supervisor/directive", {
          method: "POST",
          body: JSON.stringify({ contact: target, text, channel: "workbench" }),
        });
        if (!data.ok) throw new Error(data.error || data.reason || "指令执行失败");
        showToast(data.ackMessage || "已执行管理员指令");
        if (data.revisedReply && box) {
          box.value = data.revisedReply;
          onComposerTextInput();
        }
        document.getElementById("sendReceiptBox").innerHTML =
          `<div class="send-receipt"><p>${escapeHtml(data.ackMessage || "管理员指令已生效")}</p></div>`;
        await loadOverview(false);
      } catch (err) {
        showToast("指令执行失败: " + (err.message || err));
      }
    }

    function renderDraftQualityFeedbackBar({ target, incomingText, replyText, turnId, autoScore }) {
      const bar = document.getElementById("draftQualityFeedbackBar");
      if (!bar) return;
      DRAFT_FEEDBACK_STATE.target = target || "";
      DRAFT_FEEDBACK_STATE.incomingText = incomingText || "";
      DRAFT_FEEDBACK_STATE.replyText = replyText || "";
      DRAFT_FEEDBACK_STATE.turnId = turnId || null;
      DRAFT_FEEDBACK_STATE.stars = 0;
      DRAFT_FEEDBACK_STATE.tags = new Set();

      const tags = ["语气太硬", "未答重点", "缺少推进", "术语不准", "价格越权"];
      const scoreHtml = autoScore
        ? `<span style="color:var(--text-secondary);">5 维自评：<b>${escapeHtml(autoScore.overallScore)}分</b>（知识${escapeHtml(autoScore.kbGrounding)} · 术语${escapeHtml(autoScore.terminologyAlignment)} · 推进${escapeHtml(autoScore.salesProgression)} · 合规${escapeHtml(autoScore.complianceSafety)} · 拟人${escapeHtml(autoScore.humanLikeness)}）</span>`
        : "";
      bar.hidden = false;
      bar.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong>⭐ 回复质量打分 &amp; 沉淀 SOP</strong>
          ${scoreHtml}
        </div>
        <div class="star-rating-row">
          ${[1, 2, 3, 4, 5].map((n) => `<button type="button" class="star-btn" data-star="${n}" onclick="selectDraftFeedbackStar(${n})">${"★".repeat(n)} ${n}星</button>`).join("")}
          ${tags.map((tg) => `<button type="button" class="tag-chip" data-tag="${escapeHtml(tg)}" onclick="toggleDraftFeedbackTag(this, '${escapeHtml(tg)}')">${escapeHtml(tg)}</button>`).join("")}
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          <input type="text" id="draftFeedbackComment" placeholder="可选：纠偏备注（例如：先问规模再报价）" style="flex:1;min-width:180px;padding:4px 8px;font-size:12px;" />
          <button type="button" class="btn-outline sm" onclick="submitDraftFeedbackRating()">提交评分</button>
          <button type="button" class="btn-solid sm" onclick="learnFromDraftCorrection()">✨ 一键存为 SOP</button>
        </div>
      `;
    }

    function selectDraftFeedbackStar(n) {
      DRAFT_FEEDBACK_STATE.stars = n;
      document.querySelectorAll("#draftQualityFeedbackBar .star-btn").forEach((b) => {
        b.classList.toggle("active", Number(b.dataset.star) === n);
      });
    }

    function toggleDraftFeedbackTag(el, tag) {
      if (DRAFT_FEEDBACK_STATE.tags.has(tag)) {
        DRAFT_FEEDBACK_STATE.tags.delete(tag);
        el.classList.remove("active");
      } else {
        DRAFT_FEEDBACK_STATE.tags.add(tag);
        el.classList.add("active");
      }
    }

    async function submitDraftFeedbackRating() {
      const stars = DRAFT_FEEDBACK_STATE.stars;
      if (!stars) { showToast("请先点击 1-5 星评分"); return; }
      const comment = (document.getElementById("draftFeedbackComment")?.value || "").trim();
      const tags = Array.from(DRAFT_FEEDBACK_STATE.tags);
      const rewrite = (document.getElementById("sendText")?.value || "").trim();
      try {
        let turnId = DRAFT_FEEDBACK_STATE.turnId;
        if (!turnId) {
          const simRes = await apiJson("/api/sparring/chat", {
            method: "POST",
            body: JSON.stringify({
              message: DRAFT_FEEDBACK_STATE.incomingText || "客户咨询",
              contactName: DRAFT_FEEDBACK_STATE.target || "工作台草稿评分",
              record: true,
            }),
          });
          turnId = simRes.data?.turnId;
          DRAFT_FEEDBACK_STATE.turnId = turnId;
        }
        if (!turnId) throw new Error("未能定位评分轮次");
        const { data } = await apiJson("/api/supervisor/rate", {
          method: "POST",
          body: JSON.stringify({
            turnId,
            stars,
            tags,
            comment,
            rewrittenReply: rewrite !== DRAFT_FEEDBACK_STATE.replyText ? rewrite : "",
          }),
        });
        if (!data.ok) throw new Error(data.error || "评分失败");
        showToast(`已记录 ${stars} 星评分，已同步更新知识库权重与质量面板`);
        await loadOverview(false);
      } catch (err) {
        showToast("评分提交失败: " + (err.message || err));
      }
    }

    function renderSparringFromState() {
      if (!STATE) return;
      syncChatTestContactBtn(document.getElementById("previewTarget")?.value || "");
      const simSel = document.getElementById("simPersonaSelect");
      if (simSel && STATE.personas?.personas) {
        const cur = simSel.value || "wecom-kf-pro";
        simSel.innerHTML = (STATE.personas.personas || [])
          .map((p) => `<option value="${escapeHtml(p.id)}" ${p.id === cur ? "selected" : ""}>${escapeHtml(p.name)}</option>`)
          .join("");
      }
      if (STATE.qualityDashboard) renderQualityDashboard(STATE.qualityDashboard);
      renderTestContactsChips(STATE.testContacts || []);
      if (
        !WIZARD_STATE.autoOpened
        && STATE.isCustomerMode
        && STATE.tenantProfile
        && !STATE.tenantProfile.onboardingCompleted
      ) {
        WIZARD_STATE.autoOpened = true;
        try {
          if (!localStorage.getItem("wb_wizard_dismissed")) openOnboardingWizard(1);
        } catch (e) {}
      }
    }

    function renderTestContactsChips(contacts) {
      const box = document.getElementById("testContactsChipsBox");
      if (!box) return;
      if (!contacts.length) {
        box.innerHTML = '<span class="hosting-empty">暂无测试好友，可点击联系人卡片「🧪 设为测试好友」或在右侧添加。</span>';
        return;
      }
      box.innerHTML = contacts.map((c) => `<span class="chip">🧪 ${escapeHtml(c.displayName)} <button type="button" class="link-btn" style="padding:0 4px;" onclick="toggleTestContact('${encArg(c.displayName)}', false)">×</button></span>`).join("");
    }

    function renderQualityDashboard(dash) {
      if (!dash || !dash.summary) return;
      const s = dash.summary;
      const kpi = document.getElementById("qualityKpiGrid");
      if (kpi) {
        kpi.innerHTML = `
          <div class="mini-stat"><div class="k">对练总轮次</div><div class="v">${escapeHtml(s.totalTurns || 0)}（已评 ${escapeHtml(s.ratedTurns || 0)}）</div></div>
          <div class="mini-stat"><div class="k">平均自动分 / 合格率</div><div class="v">${escapeHtml(s.avgAutoScore || 0)} 分 · ${escapeHtml(s.passRate || 0)}%</div></div>
          <div class="mini-stat"><div class="k">平均星级 / 约束数</div><div class="v">${escapeHtml(s.avgSupervisorStars || 0)} ★ · 约束 ${escapeHtml(s.activeNegativeConstraints || 0)}</div></div>
        `;
      }
      const distBox = document.getElementById("qualityStarDistBox");
      if (distBox && dash.ratingDistribution) {
        const dist = dash.ratingDistribution;
        const maxCnt = Math.max(1, ...[1, 2, 3, 4, 5].map((k) => Number(dist[k] || dist[String(k)] || 0)));
        distBox.innerHTML = [5, 4, 3, 2, 1].map((st) => {
          const cnt = Number(dist[st] || dist[String(st)] || 0);
          const pct = Math.round((cnt / maxCnt) * 100);
          return `<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0;">
            <span style="width:36px;">${st} ★</span>
            <div style="flex:1;height:7px;background:var(--surface-soft);border-radius:99px;overflow:hidden;"><div style="width:${pct}%;height:100%;background:${st >= 4 ? "#16a34a" : (st <= 2 ? "#dc2626" : "#f59e0b")};"></div></div>
            <span style="width:28px;text-align:right;">${cnt}</span>
          </div>`;
        }).join("");
      }
      const tagsBox = document.getElementById("qualityIssueTagsBox");
      if (tagsBox) {
        const tags = dash.topIssueTags || [];
        tagsBox.innerHTML = tags.length
          ? tags.map((t) => `<span class="chip">${escapeHtml(t.tag)} (${escapeHtml(t.count)})</span>`).join("")
          : '<span class="hosting-empty">暂无低分问题标签</span>';
      }
      const lowBox = document.getElementById("qualityLowScoreList");
      if (lowBox) {
        const lows = dash.lowScoreTurns || [];
        lowBox.innerHTML = lows.length
          ? lows.map((t) => `<div style="border:1px solid var(--border);border-radius:8px;padding:7px;font-size:12px;background:var(--surface-soft);">
              <div style="display:flex;justify-content:space-between;gap:6px;">
                <strong>${escapeHtml(t.contactName)}</strong>
                <span>自评 ${escapeHtml((t.autoScore || {}).overallScore ?? "-")}分${t.supervisorRating ? ` · ${t.supervisorRating}★` : ""}</span>
              </div>
              <div style="color:var(--text-secondary);margin-top:2px;">问：${escapeHtml(t.incomingText)}</div>
              <div>答：${escapeHtml(t.revisedReply || t.aiReply)}</div>
            </div>`).join("")
          : '<span class="hosting-empty">暂无低分项，表现良好。</span>';
      }
    }

    async function loadSparringWorkspace(notify = false) {
      try {
        const [{ data: dash }, { data: turnsRes }, { data: tcRes }] = await Promise.all([
          apiJson("/api/supervisor/dashboard?days=30"),
          apiJson("/api/sparring/turns?limit=25"),
          apiJson("/api/test-contacts"),
        ]);
        renderQualityDashboard(dash);
        renderTestContactsChips(tcRes.contacts || []);
        const logBox = document.getElementById("sparringTurnsLogBox");
        const turns = turnsRes.turns || [];
        if (logBox) {
          logBox.innerHTML = turns.length
            ? turns.map((t) => `<div style="border:1px solid var(--border);border-radius:9px;padding:9px;font-size:12.5px;">
                <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
                  <span><strong>${escapeHtml(t.contactName)}</strong> <span class="pill">${escapeHtml(t.channel)}</span></span>
                  <span>自评 ${escapeHtml((t.autoScore || {}).overallScore ?? "-")}分 ${t.supervisorRating ? `· 主管 ${t.supervisorRating}★` : ""}</span>
                </div>
                <div style="color:var(--text-secondary);">客户：${escapeHtml(t.incomingText)}</div>
                <div style="margin:3px 0;">AI：${escapeHtml(t.aiReply)}</div>
                ${t.revisedReply ? `<div style="color:var(--work-pine);">改写：${escapeHtml(t.revisedReply)}</div>` : ""}
                <div class="star-rating-row" style="margin-top:6px;">
                  ${[1, 2, 3, 4, 5].map((n) => `<button type="button" class="star-btn ${t.supervisorRating === n ? "active" : ""}" onclick="rateTurnInline(${Number(t.turnId)}, ${n})">${n}★</button>`).join("")}
                </div>
              </div>`).join("")
            : '<p class="hosting-empty">暂无对练日志，可在上方模拟测试窗口发送消息或绑定测试好友对练。</p>';
        }
        if (notify) showToast("测试与评分数据已刷新");
      } catch (err) {
        if (notify) showToast("刷新失败: " + (err.message || err));
      }
    }

    async function rateTurnInline(turnId, stars) {
      try {
        const { data } = await apiJson("/api/supervisor/rate", {
          method: "POST",
          body: JSON.stringify({ turnId, stars }),
        });
        if (!data.ok) throw new Error(data.error || "评分失败");
        showToast(`轮次 #${turnId} 已评 ${stars} 星`);
        await loadSparringWorkspace(false);
      } catch (err) {
        showToast("评分失败: " + (err.message || err));
      }
    }

    async function addTestContactFromWorkspace() {
      const inp = document.getElementById("newTestContactInput");
      const name = (inp?.value || "").trim();
      if (!name) return;
      if (inp) inp.value = "";
      await toggleTestContact(encodeURIComponent(name), true);
      await loadSparringWorkspace(false);
    }

    function clearSimChatLog() {
      const box = document.getElementById("simChatLogBox");
      if (box) box.innerHTML = '<div class="sparring-msg sys">模拟对话已清空，可继续试跑或发 # 指令调优。</div>';
    }

    async function sendSparringSimMessage() {
      const inp = document.getElementById("simMessageInput");
      const box = document.getElementById("simChatLogBox");
      const contactName = (document.getElementById("simContactInput")?.value || "模拟测试客户").trim();
      const personaId = (document.getElementById("simPersonaSelect")?.value || "").trim() || null;
      const msg = (inp?.value || "").trim();
      if (!msg) return;
      if (inp) inp.value = "";
      if (box) {
        box.innerHTML += `<div class="sparring-msg peer"><strong>${escapeHtml(contactName)}：</strong>${escapeHtml(msg)}</div>`;
        box.scrollTop = box.scrollHeight;
      }
      try {
        if (/^[#＃]\s*\S/.test(msg)) {
          const { data } = await apiJson("/api/supervisor/directive", {
            method: "POST",
            body: JSON.stringify({ contact: contactName, text: msg, channel: "sparring_sim" }),
          });
          if (box) {
            box.innerHTML += `<div class="sparring-msg sys">🛡️ ${escapeHtml(data.ackMessage || data.error || "已处理")}</div>`;
            box.scrollTop = box.scrollHeight;
          }
        } else {
          const { data } = await apiJson("/api/sparring/chat", {
            method: "POST",
            body: JSON.stringify({ message: msg, contactName, personaId }),
          });
          const sc = (data.autoScore && data.autoScore.overallScore !== undefined) ? ` [${data.autoScore.overallScore}分 · ${data.autoScore.stars || 3}★]` : "";
          const tid = data.turnId;
          const starsHtml = tid ? `<div class="star-rating-row" style="margin-top:4px;">${[1, 2, 3, 4, 5].map((n) => `<button type="button" class="star-btn" onclick="rateTurnInline(${Number(tid)}, ${n})">${n}★</button>`).join("")}</div>` : "";
          if (box) {
            box.innerHTML += `<div class="sparring-msg self"><strong>AI${escapeHtml(sc)}：</strong>${escapeHtml(data.replyText || data.error || "")}${starsHtml}</div>`;
            box.scrollTop = box.scrollHeight;
          }
        }
        await loadSparringWorkspace(false);
      } catch (err) {
        if (box) box.innerHTML += `<div class="sparring-msg sys">执行出错: ${escapeHtml(err.message || err)}</div>`;
      }
    }

    async function runSparringRegressionSuite() {
      const btn = document.getElementById("sparringRegressionBtn");
      const box = document.getElementById("simRegressionBox");
      if (btn) btn.disabled = true;
      try {
        const { data } = await apiJson("/api/sparring/regression", { method: "POST", body: JSON.stringify({ limit: 20 }) });
        if (box) {
          box.hidden = false;
          const cases = data.results || [];
          box.innerHTML = `<div style="border:1px solid var(--border);border-radius:9px;padding:9px;background:var(--surface-soft);font-size:12.5px;">
            <strong>回归测试结果：${escapeHtml(data.passedCases || 0)} / ${escapeHtml(data.totalCases || 0)} 通过（通过率 ${escapeHtml(data.passRate ?? 100)}%）</strong>
            ${cases.length ? `<ul style="margin:6px 0 0;padding-left:18px;">${cases.map((c) => `<li>${c.passed ? "✅" : "❌"} [${escapeHtml(c.overallScore)}分] ${escapeHtml(c.incomingText)} → ${escapeHtml(c.generatedReply)}</li>`).join("")}</ul>` : '<div style="color:var(--text-muted);margin-top:4px;">暂无历史低分或 # 纠偏用例。</div>'}
          </div>`;
        }
        showToast(`回归测试完成：通过率 ${data.passRate ?? 100}%`);
      } catch (err) {
        showToast("回归测试失败: " + (err.message || err));
      } finally {
        if (btn) btn.disabled = false;
      }
    }
  </script>
</body>
</html>
"""


def render_web_console_html() -> str:
    """Return the self-contained Web Control Console HTML page."""
    return WEB_CONSOLE_HTML


MOBILE_REMOTE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
  <title>WeChat Bot · 手机遥控台</title>
  <style>
    :root { --bg:#f4f7f5; --card:#ffffff; --text:#18211d; --muted:#5f6f67; --pine:#1b5e3c; --border:#dce5df; --danger:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; background:var(--bg); color:var(--text); }
    .phone-wrap { max-width:460px; margin:0 auto; padding:14px 14px 28px; display:flex; flex-direction:column; gap:12px; }
    .hdr { display:flex; align-items:center; justify-content:space-between; }
    .hdr h1 { margin:0; font-size:17px; display:flex; align-items:center; gap:7px; }
    .badge { display:inline-flex; align-items:center; gap:5px; font-size:12px; padding:3px 10px; border-radius:999px; background:#e6f4ec; color:var(--pine); font-weight:600; }
    .badge.off { background:#eef1ef; color:var(--muted); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:12px 14px; }
    .card h2 { margin:0 0 8px; font-size:13.5px; color:var(--muted); font-weight:600; }
    .kpi-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; text-align:center; }
    .kpi { background:#f8faf9; border:1px solid var(--border); border-radius:10px; padding:8px 6px; }
    .kpi strong { display:block; font-size:18px; color:var(--pine); }
    .kpi span { font-size:11px; color:var(--muted); }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
    button, .link-btn { cursor:pointer; border-radius:10px; padding:9px 12px; font-size:13px; font-weight:600; border:1px solid var(--border); background:#fff; color:var(--text); text-decoration:none; text-align:center; flex:1; }
    button.primary { background:var(--pine); color:#fff; border-color:var(--pine); }
    button.danger { background:#fff5f4; color:var(--danger); border-color:#f3c6c2; }
    ul { margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:7px; }
    li { font-size:12.5px; line-height:1.45; padding:7px 9px; border-radius:9px; background:#f8faf9; border:1px solid var(--border); }
    .sub { font-size:11.5px; color:var(--muted); }
  </style>
</head>
<body>
  <main class="phone-wrap">
    <div class="hdr">
      <h1>📱 WeChat Bot 遥控台</h1>
      <span id="mHostingBadge" class="badge off">检测中</span>
    </div>
    <section class="card">
      <h2>1 · 运行状态与远程开停（识流伴侣模式）</h2>
      <div class="kpi-grid">
        <div class="kpi"><strong id="mSpeed">—</strong><span>当前档位</span></div>
        <div class="kpi"><strong id="mKbCount">—</strong><span>SOP 知识库</span></div>
        <div class="kpi"><strong id="mEvoCount">—</strong><span>自学习进化</span></div>
      </div>
      <div class="actions">
        <button type="button" class="primary" id="mEnableBtn" onclick="remoteHosting(true)">🚀 开启托管</button>
        <button type="button" class="danger" id="mPauseBtn" onclick="remoteHosting(false)">⏸ 紧急暂停</button>
        <button type="button" onclick="refreshMobile()">🔄 刷新</button>
      </div>
      <p class="sub" id="mStatusMsg" style="margin:8px 0 0;">托管仍在桌面端本地账号内执行，手机端只做远程掌控。</p>
    </section>
    <section class="card">
      <h2>2 · 人工介入待办 &amp; 反思盲区</h2>
      <ul id="mReflectList"><li class="sub">暂无待人工核对项</li></ul>
      <div class="actions"><a class="link-btn" href="/workbench" target="_top">📋 前往待办审阅台</a><a class="link-btn" href="/" target="_top">💻 返回桌面工作台</a></div>
    </section>
    <section class="card">
      <h2>3 · 白名单托管会话</h2>
      <ul id="mThreadsList"><li class="sub">读取中…</li></ul>
    </section>
  </main>
  <script>
    let LAST_TARGETS = ["安晓心", "心安", "openbot"];
    const esc = s => String(s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    async function refreshMobile() {
      try {
        const [dRes, hRes] = await Promise.all([
          fetch("/api/diagnostics").then(r => r.json()),
          fetch("/api/workos/harness").then(r => r.json()).catch(() => ({}))
        ]);
        const h = dRes.hosting || {};
        if (Array.isArray(h.targets) && h.targets.length) LAST_TARGETS = h.targets;
        const badge = document.getElementById("mHostingBadge");
        badge.textContent = h.running ? "🟢 托管运行中" : "⚪ 已暂停";
        badge.className = "badge" + (h.running ? "" : " off");
        const gov = hRes.governance || {};
        const ev = hRes.evaluation || {};
        document.getElementById("mSpeed").textContent = gov.speedMode === "deep" ? "🔬 深思" : "⚡ 极速";
        document.getElementById("mKbCount").textContent = String(ev.knowledgeEntriesCount ?? dRes.knowledgeEntries ?? "-");
        document.getElementById("mEvoCount").textContent = String((hRes.evolution && hRes.evolution.totalCount) ?? 0);

        const refs = (hRes.reflection && hRes.reflection.items) || [];
        const rList = document.getElementById("mReflectList");
        rList.innerHTML = refs.length
          ? refs.slice(0, 5).map(r => `<li><strong>${esc(r.target)}</strong>：${esc(r.incomingText)}<div class="sub">${esc(r.suggestion || "")}</div></li>`).join("")
          : `<li class="sub">当前无未命中盲区，回复策略稳定。</li>`;

        const tList = document.getElementById("mThreadsList");
        tList.innerHTML = LAST_TARGETS.map(t => `<li>💬 ${esc(t)}<div class="sub">白名单受控会话</div></li>`).join("");
      } catch (e) {
        document.getElementById("mStatusMsg").textContent = "连接失败：" + (e.message || e);
      }
    }
    async function remoteHosting(enable) {
      const res = await fetch("/api/hosting", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ action: enable ? "enable" : "disable", targets: LAST_TARGETS, disable_replies: !enable })
      }).then(r => r.json());
      document.getElementById("mStatusMsg").textContent = res.ok
        ? (enable ? "🚀 已开启白名单托管" : "⏸ 已紧急暂停托管")
        : ("操作失败：" + (res.error || "unknown"));
      await refreshMobile();
    }
    refreshMobile();
  </script>
</body>
</html>
"""


def render_mobile_remote_html() -> str:
    """Return the Thiflow-inspired responsive mobile companion remote console page."""
    return MOBILE_REMOTE_HTML
