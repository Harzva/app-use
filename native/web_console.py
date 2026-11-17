"""YoBot / wechat-rpa-bot-skill inspired Web Control Console HTML & UI renderer."""

from __future__ import annotations

import json
from typing import Any, Dict


WEB_CONSOLE_HTML = r"""<!DOCTYPE html>
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

    input[type="text"], input[type="search"], input[type="password"], input[type="url"], select, textarea {
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
      z-index: 1000;
      opacity: 0;
      pointer-events: none;
      transform: translateY(10px);
      transition: all 0.2s ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    /* ===== WeChat Bot v2.4.0 · Astryx × Uncodixfy × Modern Web Guidance ===== */
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

    /* Fixed 216px Sidebar + Clean Main Canvas */
    .container {
      max-width: 1400px !important;
      margin: 0 auto !important;
      padding: 0 !important;
      display: grid !important;
      grid-template-columns: 216px minmax(0, 1fr);
      min-height: 100vh;
      align-items: stretch;
    }

    nav.tabs {
      grid-column: 1;
      grid-row: 1 / span 16;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
      display: flex !important;
      flex-direction: column !important;
      flex-wrap: nowrap !important;
      gap: 4px !important;
      padding: 14px 10px !important;
      background: var(--surface) !important;
      border-right: 1px solid var(--border) !important;
      border-radius: 0 !important;
      box-shadow: none !important;
      margin: 0 !important;
    }

    .nav-brand {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 4px 8px 10px;
      font-size: 14px;
      font-weight: 600;
      letter-spacing: -0.01em;
      color: var(--text);
    }

    .nav-dot {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--ok);
      flex-shrink: 0;
    }

    .nav-cta {
      width: 100%;
      margin-bottom: 10px;
      padding: 7px 10px;
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
      width: 100% !important;
      text-align: left !important;
      justify-content: flex-start !important;
      padding: 7px 10px !important;
      border-radius: var(--radius-sm) !important;
      font-size: 13px !important;
      font-weight: 500 !important;
      background: transparent !important;
      color: var(--text-secondary) !important;
      border: 1px solid transparent !important;
      box-shadow: none !important;
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
      margin-top: auto;
      padding-top: 8px;
      border-top: 1px solid var(--border);
    }
    .nav-more summary {
      cursor: pointer;
      list-style: none;
      padding: 7px 10px;
      font-size: 12.5px;
      font-weight: 500;
      color: var(--text-muted);
      border-radius: var(--radius-sm);
    }
    .nav-more summary:hover { color: var(--text); background: var(--surface-soft); }
    .nav-more[open] summary { color: var(--text); margin-bottom: 4px; }

    .container > :not(nav.tabs) {
      grid-column: 2;
      min-width: 0;
    }

    /* Compact Single-Row Quiet Header */
    .topbar {
      display: flex !important;
      align-items: center !important;
      justify-content: space-between !important;
      gap: 12px !important;
      padding: 8px 20px !important;
      min-height: 44px;
      background: var(--surface) !important;
      border: none !important;
      border-bottom: 1px solid var(--border) !important;
      border-radius: 0 !important;
      box-shadow: none !important;
      margin: 0 !important;
    }

    .tb-left {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      flex-wrap: wrap;
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
      padding: 18px 22px 32px !important;
      max-width: 1080px;
    }
    #tab-monitor.tab-panel {
      max-width: none;
      padding: 14px 18px 22px !important;
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
      border-radius: 12px; padding: 14px; max-height: 340px; overflow-y: auto;
      display: flex; flex-direction: column; gap: 10px;
    }
    .bubble-row { display: flex; }
    .bubble-row.self { justify-content: flex-end; }
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
      background: var(--surface-soft);
      border: 1px solid var(--border);
      border-left: 3px solid var(--primary);
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .hosting-status { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .hosting-badge {
      font-size: 14px; font-weight: 600;
      padding: 4px 12px; border-radius: 999px;
      background: var(--surface-soft); border: 1px solid var(--border);
      color: var(--text-secondary);
    }
    .hosting-badge.on { background: #dcfce7; border-color: #86efac; color: #166534; }
    .hosting-meta { color: var(--text-secondary); font-size: 12px; }
    .hosting-actions { display: flex; gap: 10px; flex-wrap: wrap; }
    .hosting-btn { font-size: 14px !important; padding: 8px 20px !important; font-weight: 600 !important; }
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
      .container { grid-template-columns: 1fr !important; }
      nav.tabs {
        grid-column: 1 !important;
        grid-row: auto !important;
        position: static !important;
        height: auto !important;
        flex-direction: row !important;
        flex-wrap: wrap !important;
        border-right: none !important;
        border-bottom: 1px solid var(--border) !important;
        padding: 8px 10px !important;
      }
      .nav-brand, .nav-cta, .nav-more { width: 100%; margin: 2px 0; }
      nav.tabs .tab-btn { width: auto !important; flex: 1 1 auto; text-align: center !important; }
      .container > :not(nav.tabs) { grid-column: 1 !important; }
      .chat-workspace { grid-template-columns: 1fr; }
      .chat-thread-list { max-height: 220px; }
      .chat-context-bar { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 520px) {
      .topbar { padding: 8px 10px !important; }
      .tb-pipeline { font-size: 11.5px; }
      .tab-panel { padding: 10px 10px 24px !important; }
      .chat-context-bar { grid-template-columns: 1fr; }
      .chat-incoming-wrap textarea { max-width: 100%; }
    }

    /* Shared workspace: a compact header, quiet surfaces and a dedicated statistics view. */
    .container { grid-template-rows: auto auto 1fr; min-height: 100dvh; }
    nav.tabs { grid-row: 1 / span 3; height: 100dvh; }
    .topbar { grid-row: 1; }
    .auth-banner { grid-row: 2; }
    .tab-panel { grid-row: 3; }
    .tb-left { flex: 1; }
    .tb-pipeline { min-width: 0; }
    .topbar .status-pills { display: none !important; }
    .nav-more { margin-top: 10px; }
    .chat-workspace { container: conversation / inline-size; grid-template-columns: minmax(165px, 220px) minmax(0, 1fr); }
    .chat-thread-list { display: block; padding: 0; max-height: calc(100dvh - 78px); }
    .chat-thread-list > summary, .reply-settings > summary {
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      padding: 9px 12px;
    }
    .chat-thread-list[open] > summary { border-bottom: 1px solid var(--border); }
    #monitorEventsList { padding: 4px 6px; }
    .chat-main-pane { width: 100%; min-width: 0; max-width: none; gap: 10px; }
    .conversation-recipient { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 10px; }
    .conversation-recipient label, .chat-field-label { font-size: 13px; font-weight: 600; }
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
      color: var(--text); font-size: 13px; white-space: nowrap;
    }
    .topbar-more > summary::-webkit-details-marker { display: none; }
    .topbar-more[open] > .more-popover {
      display: grid; position: absolute; inset: calc(100% + 6px) 0 auto auto;
      gap: 2px; z-index: 20; width: min(240px, calc(100vw - 28px));
    }

    @container conversation (max-width: 510px) {
      .chat-context-bar { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
      .composer-actions { width: 100%; }
      .composer-actions button { flex: 1; }
    }
    @media (max-width: 900px) {
      .container { grid-template-rows: auto auto auto 1fr; }
      nav.tabs {
        grid-row: 2 !important; display: grid !important;
        grid-template-columns: auto auto auto minmax(0, 1fr); align-items: start;
        padding: 5px 10px !important; gap: 4px !important;
      }
      .auth-banner { grid-row: 3; }
      .tab-panel { grid-row: 4; }
      nav.tabs .nav-brand, nav.tabs .nav-cta { display: none; }
      nav.tabs > .tab-btn, .nav-more summary { padding: 5px 7px !important; white-space: nowrap; }
      .nav-more { margin: 0; padding: 0; border: 0; }
      .nav-more[open] { grid-column: 1 / -1; }
      .nav-more[open] .tab-btn { display: inline-flex; }
      nav.tabs .tab-btn { max-width: 100%; }
      .nav-more summary { text-align: end; }
      .tb-pipeline .desktop-detail { display: none; }
      .tb-right .seg-group, #tfTakeoverBtn { display: none; }
      .chat-workspace { grid-template-columns: minmax(0, 1fr); gap: 10px; }
      .chat-thread-list[open] { max-height: min(240px, 35dvh); }
      #tab-monitor.tab-panel { padding: 10px 12px 18px !important; }
    }
    @media (max-width: 390px) {
      .topbar .btn-outline { padding-inline: 6px; }
      nav.tabs { grid-template-columns: auto auto auto minmax(0, 1fr); gap: 2px !important; }
      nav.tabs > .tab-btn { padding-inline: 5px !important; }
      .stats-time-row { grid-template-columns: minmax(0, 130px) minmax(16px, 1fr) auto; }
    }
    /* Daily workspace: one quiet action surface and a separate list of recent conversations. */
    :root {
      --work-rail: #f7f7f4;
      --work-selection: #e9f0eb;
      --work-pine: #27593f;
      --work-on-pine: #ffffff;
      --work-muted: #535c55;
      --work-divider: #dce2da;
      --work-alert: #874022;
      --work-focus: #326649;
    }
    html[data-theme="dark"] {
      color-scheme: dark;
      --work-rail: #1b201d;
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
    nav.tabs .workspace-link { display: block; text-decoration: none; }
    nav.tabs .tab-btn.active { background: var(--work-selection) !important; }
    nav.tabs .nav-dot { background: var(--work-pine); }
    nav.tabs > :is(button,a), .nav-more > summary { min-block-size: 36px; }
    nav.tabs .tab-btn:focus-visible,
    .topbar :is(summary,button):focus-visible,
    #tab-monitor :is(button,summary,input,textarea,select):focus-visible {
      outline: 2px solid var(--work-focus) !important;
      outline-offset: 2px;
    }
    .topbar-more[open] > .more-popover { box-shadow: 0 3px 10px rgb(0 0 0 / 12%); }
    .topbar-more > summary { display: flex; align-items: center; min-block-size: 30px; }
    .home-connection { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--work-muted); }
    .home-connection::before {
      content: ""; inline-size: 7px; block-size: 7px; flex: none;
      border: 1px solid currentColor; border-radius: 50%;
    }
    .home-connection[data-state="ready"] { color: var(--work-pine); }
    .home-connection[data-state="ready"]::before { background: currentColor; }
    .home-connection[data-state="limited"] { color: var(--work-alert); }
    #tab-monitor.tab-panel { padding: 20px 24px 24px !important; }
    #tab-monitor .chat-workspace {
      grid-template-columns: minmax(165px, 222px) minmax(0, 660px);
      gap: 20px;
    }
    .home-conversations { min-inline-size: 0; }
    #tab-monitor .chat-thread-list {
      background: var(--work-rail);
      border: 1px solid var(--work-divider);
      border-radius: 8px;
    }
    #tab-monitor .chat-thread-list > summary { padding-block: 11px; }
    #tab-monitor .chat-thread-list[open] > summary { border-color: var(--work-divider); }
    .conversation-count { margin-inline-start: 4px; color: var(--work-muted); font-weight: 400; font-variant-numeric: tabular-nums; }
    .home-empty { margin: 0; padding: 10px 7px; color: var(--work-muted); font-size: 13px; overflow-wrap: anywhere; }
    #tab-monitor .chat-list-head {
      display: grid; gap: 2px; justify-items: start;
      padding: 7px 10px 10px; border: 0; border-top: 1px solid var(--work-divider);
    }
    #tab-monitor .chat-list-head button { min-height: 29px; color: var(--work-muted) !important; }
    #tab-monitor .chat-thread-row + .chat-thread-row { border-block-start: 1px solid var(--work-divider) !important; }
    #tab-monitor .chat-thread-row { border-radius: 5px !important; min-height: 47px; }
    #tab-monitor .chat-thread-row[aria-pressed="true"] { background: var(--work-selection) !important; color: var(--work-pine) !important; }
    #tab-monitor .chat-row-top { inline-size: 100%; min-inline-size: 0; }
    #tab-monitor .chat-row-top > span:first-child,
    #tab-monitor .chat-row-snippet { min-inline-size: 0; max-inline-size: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    #tab-monitor .chat-row-meta { flex: none; color: var(--work-muted); font-variant-numeric: tabular-nums; }
    #tab-monitor .chat-row-snippet, #tab-monitor .chat-feedback { color: var(--work-muted); }
    #tab-monitor .chat-main-pane { gap: 12px; }
    .conversation-heading { margin: 0; font-size: 22px; line-height: 1.3; font-weight: 650; }
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
      padding: 8px 10px !important;
      inline-size: 100%;
      max-inline-size: 100%;
      min-inline-size: 0;
    }
    #tab-monitor :is(#previewIncoming,#sendText) { min-block-size: 76px; resize: vertical; }
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
        grid-template-columns: repeat(4, minmax(0,1fr)) max-content;
        padding-inline: 12px !important;
      }
      nav.tabs > :is(.tab-btn, .nav-more) { min-inline-size: 0; max-width: 100%; }
      nav.tabs > .tab-btn { white-space: nowrap; min-block-size: 36px; }
      nav.tabs .nav-more[open] { grid-column: 1 / -1; }
      nav.tabs .nav-more > summary { display: flex; justify-content: center; align-items: center; }
      nav.tabs .nav-more[open] > summary { justify-content: start; }
      #tab-monitor.tab-panel { padding: 14px 14px 20px !important; }
      #tab-monitor .chat-workspace { grid-template-columns: minmax(0,1fr); gap: 12px; }
      #tab-monitor .chat-thread-list:not([open]) > summary { min-block-size: 39px; }
    }
    @media (max-width: 430px) {
      #tab-monitor .chat-context-bar, #tab-monitor .chat-tools-drawer .grid-2 { grid-template-columns: minmax(0,1fr); }
    }

  </style>
</head>
<body>
  <div class="container">
    <header class="topbar">
      <div class="tb-left">
        <div class="home-connection" id="homeConnection" role="status" data-state="loading">正在连接工作台</div>
        <button type="button" id="homeRetry" class="btn-outline sm" onclick="loadOverview(true)" hidden>重连</button>
      </div>
      <div class="tb-right">
        <details class="topbar-more" id="topbarMore">
          <summary>窗口设置</summary>
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

    <div id="formStatusAnnouncer" role="status" aria-live="polite" class="visually-hidden"></div>

    <!-- Fail-Closed Auth Banner -->
    <div id="authBanner" class="auth-banner">
      <div>
        <strong>工作台访问权限未开启</strong>
        <div style="font-size:12.5px; margin-top:2px;" id="authBannerMsg">开启授权后可读会话与本地统计。</div>
      </div>
      <button type="button" class="primary" onclick="grantAllAuth()">恢复访问授权</button>
    </div>

    <nav class="tabs" aria-label="工作区">
      <div class="nav-brand">
        <span class="nav-dot" aria-hidden="true"></span>
        <span>WeChat Bot</span>
      </div>
      <button type="button" class="tab-btn active" aria-current="page" data-tab="monitor" onclick="switchTab('monitor')">对话</button>
      <a id="reviewWorkbenchLink" class="tab-btn workspace-link" href="/workbench">待办审阅</a>
      <button type="button" class="tab-btn" data-tab="care" onclick="switchTab('care')">联系人</button>
      <button type="button" class="tab-btn" data-tab="stats" onclick="switchTab('stats')">统计</button>
      <details class="nav-more">
        <summary>更多功能</summary>
        <button type="button" class="tab-btn" data-tab="salescrm" onclick="switchTab('salescrm')">客户跟进 CRM</button>
        <button type="button" class="tab-btn" data-tab="knowledge" onclick="switchTab('knowledge')">知识库与话术</button>
        <button type="button" class="tab-btn" data-tab="articles" onclick="switchTab('articles')">文章与视频导出</button>
        <button type="button" class="tab-btn" data-tab="soul" onclick="switchTab('soul')">本我与记忆</button>
        <button type="button" class="tab-btn" data-tab="models" onclick="switchTab('models')">模型路由</button>
        <button type="button" class="tab-btn" data-tab="uiprotocol" onclick="switchTab('uiprotocol')">防抢鼠标守卫</button>
        <button type="button" class="tab-btn" data-tab="open" onclick="switchTab('open')">独立包与外部接入</button>
      </details>
    </nav>

    <!-- 启动授权弹窗（影刀式）：缺权限时自动弹出 -->
    <div class="perm-overlay" id="permOverlay" role="dialog" aria-modal="true" aria-labelledby="permModalTitle">
      <div class="perm-modal">
        <h2 id="permModalTitle">需要授权以下权限才能正常使用 WeChat Bot</h2>
        <p class="perm-sub">自动化读取与回复微信消息依赖这三项 macOS 权限，缺一不可</p>
        <details class="hosting-picker" style="margin:0 12px 8px;">
          <summary style="font-size:12px;color:#888;">为什么之前授权过，现在又要授权？</summary>
          <div style="font-size:12px;color:#666;line-height:1.6;padding:6px 4px;">
            App 每次更新后代码签名会变化，macOS 会把它视为<b>新的应用</b>，旧授权随之失效——这是系统安全机制，不是 bug。<br>
            正确做法：打开系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制，先把列表里的<b>旧 WeChat Bot 条目「−」删除</b>，再点「+」重新添加当前安装的 WeChat Bot。
          </div>
        </details>
        <div class="perm-steps" id="permModalSteps"></div>
        <div id="permWizard"></div>
        <div class="perm-items perm-modal-items" id="permModalItems"></div>
        <div class="perm-modal-actions">
          <a id="permModalOpenSettings" class="btn-solid" href="x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" style="text-decoration:none;">⚙️ 打开系统设置去授权</a>
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

    <!-- Tab 2 (Default Chat-First Home): Live Chat & AI Copilot -->
    <section id="tab-monitor" class="tab-panel active">
      <details class="hosting-panel perm-panel" id="permPanel" open>
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
        <div class="hosting-status">
          <span id="hostingBadge" class="hosting-badge off">⚪ 托管未开启</span>
          <span id="hostingMeta" class="hosting-meta">加载中…</span>
        </div>
        <div class="hosting-actions">
          <button type="button" id="hostingEnableBtn" class="btn-solid hosting-btn" onclick="applyHosting(true)">🚀 一键托管</button>
          <button type="button" id="hostingDisableBtn" class="btn-outline" onclick="applyHosting(false)">⏹ 停止托管</button>
          <button type="button" id="llmFixBtn" class="btn-outline" onclick="relaunchLlmGateway()" hidden>🔧 启动 Magpie（修复 LLM 网关）</button>
          <button type="button" id="diagBtn" class="btn-outline" onclick="loadDiagnostics(true)">🩺 健康诊断</button>
        </div>
        <details class="hosting-picker">
          <summary>选择托管好友 <span id="hostingCheckedCount" class="conversation-count"></span></summary>
          <div class="hosting-toolbar">
            <button type="button" class="link-btn" onclick="hostingSelectAll(true)">全选</button>
            <button type="button" class="link-btn" onclick="hostingSelectAll(false)">清空</button>
            <button type="button" class="link-btn" onclick="refreshHostingFriends()">刷新好友列表</button>
            <span class="hosting-hint">勾选即托管对象；未绑定过的好友开启托管时会自动创建绑定。</span>
          </div>
          <ul class="hosting-friend-list" id="hostingFriendList"><li class="hosting-empty">正在读取好友列表…</li></ul>
        </details>
      </div>
      <div class="chat-workspace">
        <aside class="home-conversations" aria-label="最近会话">
          <details class="chat-thread-list" id="conversationThreads" open>
            <summary>最近会话 <span id="conversationCount" class="conversation-count"></span></summary>
            <div id="monitorEventsList"><p class="home-empty">正在读取最近会话…</p></div>
            <div class="chat-list-head">
              <button type="button" class="link-btn" onclick="triggerWatchOnce(false)" aria-describedby="watchPreviewHint">巡检已绑定会话</button>
              <p id="watchPreviewHint" class="chat-feedback">可能切换微信会话，只生成草稿，不发送。</p>
            </div>
            <div id="watchRunReceipt" style="display:none;"></div>
          </details>
        </aside>

        <main class="chat-main-pane" aria-labelledby="conversationHeading">
          <h1 id="conversationHeading" class="conversation-heading">对话</h1>
          <div class="conversation-recipient">
            <label for="previewTarget">回复对象</label>
            <input type="text" id="previewTarget" placeholder="选择最近会话，或输入会话名称" oninput="syncChatRecipient(this.value)" />
          </div>

          <div class="chat-stream-card">
            <div class="chat-bubble-wrap">
              <div class="chat-bubble-head">💬 聊天记录 <span id="chatStreamTarget" class="conversation-count"></span>
                <span class="hosting-hint">生成草稿自动针对最新来信</span>
              </div>
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
            <label for="sendText" class="chat-field-label">回复草稿</label>
            <textarea id="sendText" placeholder="输入回复，或生成草稿后修改"></textarea>
            <div class="chat-composer-bar">
              <div class="composer-actions">
                <button type="button" id="generateDraftBtn" class="btn-solid" onclick="runReplyPreview()">生成草稿</button>
                <button type="button" id="saveDraftBtn" class="btn-outline" aria-describedby="saveDraftHint" onclick="saveConversationDraft()">加入待办</button>
                <button type="button" id="sendActionLabel" class="btn-outline" onclick="executeSafeSend()" aria-describedby="sendModeHint">模拟检查</button>
              </div>
              <p class="chat-feedback" id="saveDraftHint">手动加入待办后可继续编辑，不会发送。</p>
              <div class="saved-draft-feedback">
                <p id="savedDraftStatus" role="status"></p>
                <a id="openSavedTask" href="/workbench" hidden>查看待办</a>
              </div>
              <p class="chat-feedback" id="sendModeHint">模拟检查不会写入微信。</p>
              <p class="draft-status" id="draftStatus" role="status" hidden></p>
            </div>
            <div id="replyPreviewResult" class="chat-ai-answer" hidden></div>
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
          <button class="sm accent" onclick="syncOpenBotKb()">🔄 同步 OpenBot SQLite 知识库</button>
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
              <h2 class="section-title">独立桌面软件与网页控制端 (`v2.4.0`)</h2>
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
            <div class="panel-title">📊 15 维定量特征雷达 (<span id="crmSelectedNameBadge">未选择</span>)</div>
            <div class="panel-meta">源自 vendor/salescrm 15 维特征引擎与置信度计算</div>
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
  </div>

  <div id="toast" class="toast"></div>

  <script>
    let STATE = null;
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

    function switchTab(tab) {
      ACTIVE_TAB = tab;
      document.getElementById("toast")?.classList.remove("show");
      document.querySelectorAll(".tab-btn").forEach((b) => {
        const active = b.dataset.tab === tab;
        b.classList.toggle("active", active);
        if (active) b.setAttribute("aria-current", "page");
        else b.removeAttribute("aria-current");
      });
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.toggle("active", p.id === "tab-" + tab);
      });
      const more = document.querySelector(".nav-more");
      if (more) more.open = ["soul", "models", "uiprotocol", "open", "salescrm", "knowledge", "articles"].includes(tab);
      if (tab === "stats") loadBackgroundObservation();
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

    /* ---------- 首页「一键托管好友」 ---------- */
    const HOSTING_STATE = { hosting: null, friends: [], checked: new Set() };

    async function loadHosting() {
      try {
        const { status, data } = await apiJson("/api/hosting");
        if (status !== 200 || !data.ok) return;
        HOSTING_STATE.hosting = data.hosting || {};
        HOSTING_STATE.friends = data.friends || [];
        renderHosting();
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

    function renderHosting() {
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
        cb.checked = HOSTING_STATE.checked.has(f.target) || Boolean(f.autoReplyEnabled);
        cb.addEventListener("change", () => {
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
      const targets = [...HOSTING_STATE.checked];
      if (enable && targets.length === 0) {
        showToast("请先在「选择托管好友」里勾选要托管的好友");
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
        if (data.hosting) HOSTING_STATE.hosting = data.hosting;
        showToast(enable
          ? "已开启托管：" + targets.length + " 位好友 · 机器人真发送回复"
          : "已停止托管" + (targets.length ? "，并关闭所选好友的自动回复" : ""));
        HOSTING_STATE.checked = new Set();
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
      "1. 点上方「打开系统设置 · 隐私与安全性」；",
      "2. 辅助功能 / 屏幕录制 两个面板里，把 <b>WeChat Bot</b> 加进去并打开开关（若列表里有旧条目，先「−」删除再加新的——旧授权对新版本无效）；",
      "3. 授权后点「🔄 重新检查」，无需重启应用。",
    ];

    const PERM_PANE_BY_ID = { accessibility: "Privacy_Accessibility", post_event: "Privacy_Accessibility", screen_capture: "Privacy_ScreenCapture" };

    /* ---------- 分步授权向导：一次聚焦一个权限，点击去授权，回来自动检测并进入下一项 ---------- */
    const PERM_WIZARD = { active: false, timer: null, stepId: null, items: [] };

    function stopWizardPolling() {
      PERM_WIZARD.active = false;
      if (PERM_WIZARD.timer) { clearInterval(PERM_WIZARD.timer); PERM_WIZARD.timer = null; }
    }

    function renderPermWizard() {
      const wizardEl = document.getElementById("permWizard");
      if (!wizardEl) return;
      const items = PERM_WIZARD.items || [];
      const pending = items.filter(p => !p.granted);
      if (!pending.length) {
        wizardEl.innerHTML = "<p class=\"hosting-empty\">三项权限全部就绪 ✅</p>";
        return;
      }
      const current = pending[0];
      PERM_WIZARD.stepId = current.id;
      const doneCount = items.length - pending.length;
      const pane = PERM_PANE_BY_ID[current.id] || "Privacy_Accessibility";
      const deepLink = "x-apple.systempreferences:com.apple.preference.security?" + pane;
      wizardEl.innerHTML = `
        <div style="text-align:center;padding:6px 8px 2px;">
          <div style="font-size:13px;color:#888;margin-bottom:6px;">第 <b>${doneCount + 1}</b> 步 / 共 ${items.length} 步 · 当前授权项</div>
          <div style="font-size:20px;font-weight:700;margin-bottom:4px;">${current.name}</div>
          <div style="font-size:13px;color:#666;margin-bottom:14px;">${current.purpose}</div>
          <a class="btn-solid" href="${deepLink}" style="display:inline-block;padding:12px 28px;font-size:15px;text-decoration:none;cursor:pointer;">🔑 去授权「${current.name}」</a>
          <div style="font-size:12px;color:#999;margin-top:12px;">在系统设置中打开开关后回到这里——我会自动检测并进入下一步（每 2 秒检查一次）</div>
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
            const stillPending = (data.items || []).filter(p => !p.granted);
            if (!stillPending.length) {
              stopWizardPolling();
              hidePermModal();
              showToast("🎉 三项权限全部就绪，机器人功能全部可用！");
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

        // 弹窗步骤条：✅已授权 / ⚠未授权
        const steps = document.getElementById("permModalSteps");
        const modalItems = document.getElementById("permModalItems");
        if (steps && modalItems) {
          steps.innerHTML = data.items.map((p, i) =>
            `<span class="perm-step ${p.granted ? "done" : "todo"}"><span class="dot">${p.granted ? "✓" : i + 1}</span>${p.name}</span>`
          ).join('<span class="perm-arrow">≫</span>');
          modalItems.innerHTML = data.items.filter((p) => !p.granted).map((p) => `
            <div class="perm-item">
              <div class="perm-item-head">⚠️ ${p.name}
                <span class="perm-badge denied">未授权</span>
              </div>
              <div class="perm-purpose">${p.purpose}</div>
            </div>
          `).join("") || `<p class="hosting-empty">三项权限全部就绪。</p>`;
          const firstDenied = data.items.find((p) => !p.granted);
          const link = document.getElementById("permModalOpenSettings");
          if (link && firstDenied) link.href = "x-apple.systempreferences:com.apple.preference.security?" + (PERM_PANE_BY_ID[firstDenied.id] || "Privacy_Accessibility");
        }

        itemsEl.innerHTML = data.items.map((p) => {
          const pane = PERM_PANE_BY_ID[p.id] || "Privacy_Accessibility";
          const deepLink = `x-apple.systempreferences:com.apple.preference.security?${pane}`;
          return `
          <div class="perm-item">
            <div class="perm-item-head">${p.granted ? "✅" : "⚠️"} ${p.name}
              <span class="perm-badge ${p.granted ? "granted" : "denied"}">${p.granted ? "已授权" : "未授权"}</span>
            </div>
            <div class="perm-purpose">${p.purpose}</div>
            ${p.granted ? "" : `<div class="perm-guide">
              <a class="btn-outline sm" href="${deepLink}" style="text-decoration:none;">⚙️ 一键打开「${p.name}」授权面板</a>
              <div style="margin-top:6px;">${PERM_GUIDE_STEPS.join("<br>")}</div>
            </div>`}
          </div>`;
        }).join("");
        if (data.allGranted) {
          panel.classList.remove("warn");
          panel.classList.add("ok");
          panel.open = false;
          summary.textContent = "✅ 系统权限就绪（辅助功能 / 系统事件 / 屏幕录制）";
          document.getElementById("permHint").textContent = "微信" + (data.wechatRunning ? "运行中 (PID " + data.wechatPid + ")" : "未运行——自动回复需要微信保持打开");
          hidePermModal();
        } else {
          panel.classList.remove("ok");
          panel.classList.add("warn");
          panel.open = true;
          const denied = data.items.filter((p) => !p.granted).map((p) => p.name).join(" / ");
          summary.textContent = "🔐 系统权限未就绪：缺 " + denied + " ——机器人会“睁眼瞎”";
          document.getElementById("permHint").textContent = "授权后点「重新检查」即可生效。";
          if (!window.PERM_MODAL_DISMISSED) {
            showPermModal();
            PERM_WIZARD.items = data.items || [];
            renderPermWizard(); // 分步向导：聚焦第一个未授权项，点击去授权，回来自动检测
          }
        }
        if (notify) showToast(data.allGranted ? "✅ 权限全部就绪，机器人功能全部可用" : "仍有权限未授权，按步骤操作后重新检查");
      } catch (err) {
        panel.classList.add("warn");
        panel.open = true;
        itemsEl.innerHTML = `<p class="hosting-empty">权限检查失败: ${err.message}</p>`;
        if (!window.PERM_MODAL_DISMISSED) showPermModal();
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

        return `
          <article class="contact-card ${cardCls}" data-contact-key="${rawTargetEnc}">
            <div class="contact-top">
              <div>
                <div class="contact-name">
                  <span>${titleEsc}</span>
                  ${careBadge}
                  ${p.bound ? `<span class="pill ok">已绑定</span>` : ""}
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

    function selectChatThread(encTarget, encIncoming) {
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
      if (compactConversation.matches) document.getElementById("conversationThreads").open = false;
      renderChatStream(target);
    }

    // 微信式气泡流：渲染当前会话的往来记录（peer 左 / self 右 / 时间居中 / OCR 低置信标注）
    function renderChatStream(target) {
      const stream = document.getElementById("chatBubbleStream");
      const headTarget = document.getElementById("chatStreamTarget");
      if (!stream) return;
      const norm = String(target || "").toLowerCase();
      const thread = Object.values(STATE?.recentThreads || {}).find((t) => (t.target || "").toLowerCase() === norm);
      const msgs = (thread && thread.messages) || [];
      if (headTarget) headTarget.textContent = target ? "· " + target : "";
      if (!msgs.length) {
        stream.replaceChildren();
        const sep = document.createElement("div");
        sep.className = "bubble-sep";
        sep.textContent = "暂往来记录——对方发消息后会自动出现在这里";
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
        const bubble = document.createElement("div");
        bubble.className = "bubble " + (m.direction === "self" ? "self" : "peer") + (i === lastPeerIdx ? " latest" : "") + (m.direction === "self" && m.source === "hosting" ? " hosted" : "");
        bubble.textContent = m.text;
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
      for (const profile of (STATE?.analytics?.profiles || []).slice(0, 12)) {
        const target = (profile.target || profile.matchedTitle || "").trim();
        if (!target) continue;
        if (!conversations.has(target)) conversations.set(target, {title: target, incoming: "", time: "", sortTs: 0});
        conversations.get(target).title = profile.matchedTitle || target;
      }
      // 历史来信兜底：事件流里没有 incomingText 的会话，从联系人历史（含导入+实时回写）取最近一条客户来信
      const inboundByTarget = {};
      for (const lb of Object.values(STATE?.latestInbound || {})) {
        if (lb && lb.target) inboundByTarget[lb.target] = lb;
      }
      for (const [target, conversation] of conversations) {
        const lb = inboundByTarget[target];
        if (lb) {
          const lbStamp = new Date(lb.sortAt || "");
          if (Number.isFinite(lbStamp.getTime()) && lbStamp.getTime() > (conversation.sortTs || 0)) conversation.sortTs = lbStamp.getTime();
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
        return `
          <button type="button" class="chat-thread-row ${selected ? "active" : ""}" aria-pressed="${selected}" data-target="${escapeHtml(target)}" onclick="selectChatThread('${encArg(target)}', '${encArg(entry.incoming)}')">
            <span class="chat-row-top"><span>${escapeHtml(entry.title)}</span>${takenOver ? `<span class="pill danger">🤚 人工接管中</span>` : ""}${limitedPill}<span class="chat-row-meta">${escapeHtml(entry.time)}</span></span>
            <span class="chat-row-snippet">${escapeHtml(entry.incoming || "暂无来信 · 对方发消息后会自动记录")}</span>
            ${resumeBtn}
          </button>`;
      }).join("");
      if (focused) [...container.querySelectorAll(".chat-thread-row")]
        .find(row => row.dataset.target === focused)?.focus({preventScroll:true});
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
        ({ data } = await apiJson("/api/reply-preview", {
          method: "POST",
          body: JSON.stringify({ target, incoming_text, persona_override, model_id, use_llm }),
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
      const sendBox = document.getElementById("sendText");
      const edited = revision !== draftRevision || originalDraft !== draftInput.value;
      if (!edited) sendBox.value = data.replyText;
      const refs = data.basis?.documentRefs || data.matchedEntries || [];
      const personaLabel = data.persona?.name || "默认人格";
      const personaMeta = data.persona?.mbti ? `${personaLabel} · ${data.persona.mbti}` : personaLabel;
      const modelMeta = data.generationMode === "llm_magpie"
        ? `${data.modelUsed || "Magpie"} · ${data.latencyMs ?? "-"}ms`
        : "知识库规则匹配";
      el.innerHTML = `
        <div>
          ${edited ? `<div class="draft-suggestion"><strong>新建议</strong><p>${escapeHtml(data.replyText)}</p></div>` : ""}
          <details class="chat-thinking-details">
            <summary>草稿依据 · ${escapeHtml(personaMeta)} · ${escapeHtml(modelMeta)} · 引用 ${data.matchedCount ?? refs.length ?? 0} 条</summary>
            ${refs.length ? `<ul style="margin:8px 0 0; padding-left:18px;">${refs.map((r) => `<li>${escapeHtml(r.title)}</li>`).join("")}</ul>` : `<div style="margin-top:6px;">无额外知识条目命中。</div>`}
          </details>
        </div>
      `;
      setDraftStatus(edited ? "已保留手工修改，新建议显示在下方。" : "草稿已填入，可继续编辑。");
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
        await loadOverview();
      } catch (err) {
        setDraftStatus("没有收到操作回执。请核对微信后再决定是否重试。", "error");
      } finally {
        sendInFlight = false;
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
              const enc = encodeURIComponent(it.displayName || it.personId || "");
              return `
                <div class="field-box" style="padding:8px 10px; margin-bottom:8px; border-left:3px solid ${it.isDue ? "var(--special)" : "var(--primary)"};">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong>${it.isDue ? "🔴 已到期" : "🟢 待跟进"} · ${escapeHtml(it.displayName || "")} (${escapeHtml(it.stage || "")})</strong>
                    <span style="font-size:12px; color:var(--text-muted);">${escapeHtml(it.followUpBeijing || "")} CST</span>
                  </div>
                  <div style="font-size:12px; color:var(--text-secondary); margin:4px 0;">${escapeHtml(it.note || "暂无备注")}${it.isDue ? ` · 已逾期 ${it.overdueMinutes || 0} 分钟` : ""}</div>
                  <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
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
    document.addEventListener("click", event => {
      if (!moreActions.contains(event.target) || event.target.closest(".menu-item")) moreActions.open = false;
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && moreActions.open) {
        moreActions.open = false;
        moreActions.querySelector("summary").focus();
      }
    });
    document.getElementById("sendText").addEventListener("input", () => { draftRevision++; });
    syncSendModeLabel();
    renderSalesCrmTab();
    loadOverview();
    loadPermissions();
    loadBackgroundObservation();
    setInterval(loadBackgroundObservation, 5000);
    document.addEventListener("visibilitychange", loadBackgroundObservation);
    updateSaveDraftButton();
    window.addEventListener("hashchange", resumeSavedDraft);
    resumeSavedDraft();
    const linkedTab = location.hash.slice(1);
    if (["care", "monitor", "stats", "articles", "uiprotocol", "knowledge", "soul", "salescrm", "models", "open"].includes(linkedTab)) {
      switchTab(linkedTab);
    }
  </script>
</body>
</html>
"""


def render_web_console_html() -> str:
    """Return the self-contained Web Control Console HTML page."""
    return WEB_CONSOLE_HTML
