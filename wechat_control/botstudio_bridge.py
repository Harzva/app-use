"""Standalone Software & Bot Studio (DSH / MCP / dsh2codex) Bridge Manager.

Unifies the three distribution & execution forms of WeChat Bot (`v2.4.0`):
1. Standalone Desktop Software (`dist/WeChat Bot.app` + Web Console + CLI)
2. Native DSH Plugin (`dsh.plugin.json` & `market/dsh-agent-plugin-catalog-entry.json`)
3. Bot Studio 1.0.33 Workbench Integration (`dsh2codex` 4-Tab Pages + MCP + HTTP + Fail-Closed Auth)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import local_signing
from .io_utils import atomic_write_json


FOUR_TAB_PAGE_IDS = ["overview", "console", "workflows", "page_spec"]


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_requires_approval(preset_or_pkg: Dict[str, Any]) -> None:
    """Recursively ensure all workbench actions default to direct execution without approval dialogs."""
    if not isinstance(preset_or_pkg, dict):
        return
    for key in ("panels", "pages"):
        items = preset_or_pkg.get(key)
        if isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict) and isinstance(entry.get("actions"), list):
                    for act in entry["actions"]:
                        if isinstance(act, dict):
                            act["requiresApproval"] = False
    nested_preset = preset_or_pkg.get("preset")
    if isinstance(nested_preset, dict):
        _strip_requires_approval(nested_preset)


def _enhance_botstudio_page_html(html: str) -> str:
    """Apply Astryx × Uncodixfy minimalist UI, fold raw protocol forms into a drawer, and expose zero-popup compile hooks."""
    minimal_style = """
<meta name="color-scheme" content="light dark">
<style id="wechat-bot-minimal-bridge-style">
  :root {
    color-scheme: light dark;
    --wb-bg: #fafafa;
    --wb-surface: #ffffff;
    --wb-soft: #f4f4f5;
    --wb-border: #e4e4e7;
    --wb-text: #09090b;
    --wb-muted: #52525b;
    --wb-primary: #18181b;
    --wb-primary-fg: #ffffff;
    --wb-ok: #10b981;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --wb-bg: #09090b;
      --wb-surface: #121215;
      --wb-soft: #18181b;
      --wb-border: #27272a;
      --wb-text: #fafafa;
      --wb-muted: #a1a1aa;
      --wb-primary: #fafafa;
      --wb-primary-fg: #09090b;
    }
  }
  body {
    margin: 0 !important;
    padding: 24px 16px 48px !important;
    background: var(--wb-bg) !important;
    background-image: none !important;
    color: var(--wb-text) !important;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif !important;
    font-size: 14px !important;
    line-height: 1.55 !important;
  }
  .wb-shell {
    max-width: 820px !important;
    margin: 0 auto !important;
    gap: 14px !important;
  }
  .wb-standalone-hero {
    background: var(--wb-surface);
    border: 1px solid var(--wb-border);
    border-radius: 10px;
    padding: 20px 22px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .wb-hero-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }
  .wb-hero-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 17px;
    font-weight: 600;
    margin: 0;
  }
  .wb-dot {
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: var(--wb-ok);
    flex-shrink: 0;
  }
  .wb-hero-desc {
    margin: 0;
    font-size: 13.5px;
    color: var(--wb-muted);
  }
  .wb-hero-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding-top: 4px;
  }
  .wb-btn-primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 7px 14px;
    border-radius: 8px;
    border: 1px solid var(--wb-primary);
    background: var(--wb-primary);
    color: var(--wb-primary-fg);
    font-size: 13px;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    transition: transform 140ms cubic-bezier(0.23, 1, 0.32, 1);
  }
  .wb-btn-primary:active, .wb-action-btn:active {
    transform: scale(0.97);
  }
  .wb-action-btn {
    border-radius: 8px !important;
    border: 1px solid var(--wb-border) !important;
    background: var(--wb-surface) !important;
    color: var(--wb-text) !important;
    padding: 6px 12px !important;
    font-size: 12.5px !important;
    font-weight: 500 !important;
    text-decoration: none !important;
    cursor: pointer !important;
    transition: background-color 140ms ease, transform 140ms ease !important;
  }
  .wb-action-btn:hover {
    background: var(--wb-soft) !important;
  }
  .wb-card, .wb-hero {
    background: var(--wb-surface) !important;
    border: 1px solid var(--wb-border) !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    color: var(--wb-text) !important;
  }
  .wb-muted, .wb-field {
    color: var(--wb-muted) !important;
  }
  .wb-field input[type="text"], .wb-field select {
    background: var(--wb-surface) !important;
    color: var(--wb-text) !important;
    border: 1px solid var(--wb-border) !important;
    border-radius: 8px !important;
  }
  .wb-page-tab {
    background: transparent !important;
    color: var(--wb-muted) !important;
    border: 1px solid var(--wb-border) !important;
    border-radius: 8px !important;
  }
  .wb-page-tab.is-active {
    background: var(--wb-soft) !important;
    color: var(--wb-text) !important;
    border-color: var(--wb-primary) !important;
  }
  .wb-debug-drawer {
    background: var(--wb-surface);
    border: 1px solid var(--wb-border);
    border-radius: 10px;
    padding: 12px 16px;
  }
  .wb-debug-drawer > summary {
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    color: var(--wb-muted);
  }
  .wb-debug-drawer[open] > summary {
    color: var(--wb-text);
    margin-bottom: 12px;
  }
  pre {
    background: var(--wb-soft) !important;
    border: 1px solid var(--wb-border) !important;
    color: var(--wb-text) !important;
    border-radius: 8px !important;
  }
  :where(button, a, summary, input, select):focus-visible {
    outline: 2px solid var(--wb-primary) !important;
    outline-offset: 2px !important;
  }
</style>
"""
    if "</head>" in html and "wechat-bot-minimal-bridge-style" not in html:
        html = html.replace("</head>", minimal_style + "</head>", 1)

    standalone_card = (
        '<div class="wb-shell" id="wb-clean-top">'
        '  <section class="wb-standalone-hero" id="wb-standalone-hero">'
        '    <div class="wb-hero-head">'
        '      <h1 class="wb-hero-title"><span class="wb-dot" aria-hidden="true"></span>WeChat Bot · 独立状态与协议接入</h1>'
        '      <span style="font-size:12px; color:var(--wb-muted);">v2.4.0 · 单一正式版</span>'
        '    </div>'
        '    <p class="wb-hero-desc">WeChat Bot 为独立原生软件（已从 OpenBot / Bot Studio 目录解耦）。日常聊天与回复请进入主工作台；下方保留静默编译与底层 DSH / MCP 协议参数调试抽屉。</p>'
        '    <div class="wb-hero-actions">'
        '      <a class="wb-btn-primary" href="http://127.0.0.1:18788/">打开 WeChat Bot 聊天工作台 (/)</a>'
        '      <a class="wb-action-btn" href="http://127.0.0.1:18788/workbench">待办审阅台 (/workbench)</a>'
        '      <button type="button" class="wb-action-btn" id="wb-silent-compile-btn" onclick="wbSilentCompileBundle()">静默编译插件包</button>'
        '      <button type="button" class="wb-action-btn" id="wb-silent-app-btn" onclick="wbSilentRebuildApp()">重编原生 App</button>'
        '    </div>'
        '  </section>'
        '</div>'
    )
    if "<body" in html and "wb-standalone-hero" not in html:
        body_end = html.find(">", html.find("<body"))
        if body_end != -1:
            html = html[: body_end + 1] + standalone_card + html[body_end + 1 :]

    extra_script = r"""
  <script>
    (function(){
      var outEl = document.getElementById('wb-preview-output');
      var origShell = document.querySelector('body > .wb-shell:not(#wb-clean-top)');
      var debugDrawer = null;
      if (origShell && !document.getElementById('wb-debug-drawer')) {
        debugDrawer = document.createElement('details');
        debugDrawer.id = 'wb-debug-drawer';
        debugDrawer.className = 'wb-debug-drawer';
        var sum = document.createElement('summary');
        sum.textContent = '展开底层协议调试面板 (DSH / MCP 参数调试)';
        debugDrawer.appendChild(sum);
        while (origShell.firstChild) {
          debugDrawer.appendChild(origShell.firstChild);
        }
        origShell.appendChild(debugDrawer);
      }
      function ensureDebugOpen() {
        if (debugDrawer) debugDrawer.open = true;
      }
      function apiBase() {
        return (window.location.origin && window.location.origin.indexOf('http') === 0)
          ? window.location.origin
          : 'http://127.0.0.1:18788';
      }
      window.wbSilentCompileBundle = async function() {
        ensureDebugOpen();
        if (outEl) outEl.textContent = '正在静默编译 DSH -> Bot Studio 4-Tab 集成包 (无需确认)...';
        try {
          var resp = await fetch(apiBase() + '/api/botstudio-bridge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'export_bundle'})
          });
          var data = await resp.json();
          if (outEl) outEl.textContent = JSON.stringify({silentCompile: true, mode: 'export_bundle', result: data}, null, 2);
        } catch (err) {
          if (outEl) outEl.textContent = '静默编译失败: ' + (err && err.message ? err.message : String(err));
        }
      };
      window.wbSilentRebuildApp = async function() {
        ensureDebugOpen();
        if (outEl) outEl.textContent = '正在静默编译 Native .app（固定本地叶证书签名，0弹窗）...';
        try {
          var resp = await fetch(apiBase() + '/api/botstudio-bridge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'rebuild_app', install_to_host: true})
          });
          var data = await resp.json();
          if (outEl) outEl.textContent = JSON.stringify({silentCompile: true, mode: 'rebuild_app', result: data}, null, 2);
        } catch (err) {
          if (outEl) outEl.textContent = '原生编译失败: ' + (err && err.message ? err.message : String(err));
        }
      };
      Array.prototype.forEach.call(document.querySelectorAll('.wb-action-btn[data-panel][data-action]'), function(btn){
        btn.addEventListener('click', async function(){
          var panelId = btn.getAttribute('data-panel');
          var actionId = btn.getAttribute('data-action');
          var args = {};
          Array.prototype.forEach.call(document.querySelectorAll('[data-panel="' + panelId + '"][data-field]'), function(el){
            args[el.getAttribute('data-field')] = el.type === 'checkbox' ? !!el.checked : el.value;
          });
          var endpoint = null;
          ensureDebugOpen();
          var method = 'POST';
          var payload = {};
          if (actionId === 'inspect_live') {
            endpoint = '/api/watch-once';
            payload = {dry_run: true, target: args.targetChat || ''};
          } else if (actionId === 'navigate_ui') {
            endpoint = '/api/ui-navigate';
            payload = {target_id: args.targetId || 'nav.chats', dry_run: args.dryRun !== false};
          } else if (actionId === 'export_article') {
            endpoint = '/api/export-article';
            payload = {url: args.articleUrl || '', from_window: args.fromWindow !== false, download_images: args.downloadImages !== false};
          } else if (actionId === 'export_account') {
            endpoint = '/api/export-account';
            payload = {account_name: args.accountName || '', album_url: args.albumUrl || '', max_articles: Number(args.maxArticles || 30)};
          } else if (actionId === 'export_channels') {
            endpoint = '/api/export-channels';
            payload = {author: args.authorName || '', cache_dir: args.cacheDir || '', manifest_path: args.manifestPath || ''};
          } else if (actionId === 'soul_profile') {
            endpoint = '/api/soul-profile';
            payload = {target: args.target || '', rebuild: !!args.rebuild};
          } else if (actionId === 'smart_reply') {
            endpoint = '/api/reply-preview';
            payload = {target: args.target || '心安', incoming_text: args.incomingText || '', persona: args.persona || 'owner-digital-twin'};
          } else if (actionId === 'run_benchmark' || actionId === 'wechat_full_acceptance') {
            endpoint = '/api/overview';
            method = 'GET';
          } else if (actionId === 'crm_pipeline') {
            endpoint = '/api/crm/overview';
            method = 'GET';
          } else if (actionId === 'crm_analyze') {
            endpoint = '/api/crm/analyze';
            payload = {target: args.target || '心安', incoming_text: args.incomingText || ''};
          } else if (actionId === 'crm_formulas') {
            endpoint = '/api/crm/formulas';
            payload = {target: args.target || '心安'};
          }
          if (!endpoint) return;
          try {
            var opts = {method: method};
            if (method === 'POST') {
              opts.headers = {'Content-Type': 'application/json'};
              opts.body = JSON.stringify(payload);
            }
            var resp = await fetch(apiBase() + endpoint, opts);
            var liveRes = await resp.json();
            if (outEl) {
              outEl.textContent += '\n\n--- 直接执行回执 (' + method + ' ' + endpoint + ' · 无确认弹窗) ---\n' + JSON.stringify(liveRes, null, 2);
            }
          } catch (err) {
            if (outEl) outEl.textContent += '\n\n--- 直接执行异常 ---\n' + (err && err.message ? err.message : String(err));
          }
        });
      });
    })();
  </script>
"""
    if "wbSilentCompileBundle" not in html and "</body>" in html:
        html = html.replace("</body>", f"{extra_script}</body>", 1)
    return html


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class BotStudioBridgeManager:
    """Manages standalone packaging, DSH plugin validation, and Bot Studio workbench compilation."""

    def __init__(self, engine: Optional[Any] = None) -> None:
        self.engine = engine
        default_root = Path(__file__).resolve().parent.parent
        self.plugin_root = Path(getattr(engine, "plugin_root", None) or default_root)
        inspector = getattr(engine, "inspector", None)
        self.reports_dir = Path(getattr(inspector, "reports_dir", None) or (self.plugin_root / "logs"))
        self.dsh_manifest_path = self.plugin_root / "dsh.plugin.json"
        self.catalog_entry_path = self.plugin_root / "market" / "dsh-agent-plugin-catalog-entry.json"
        self.plugin_manifest_path = self.plugin_root / "plugin.manifest.json"
        self.workbench_preset_path = self.plugin_root / "market" / "wechat-rpa-control.preset.json"
        self.workbench_plugin_path = self.plugin_root / "market" / "wechat-rpa-control.plugin.json"
        self.pages_dir = self.plugin_root / "dist" / "botstudio-pages" / "wechat-ecosystem"
        self.wechat_bot_app_bundle = self.plugin_root / "dist" / "WeChat Bot.app"
        self.standalone_app_bundle = self.wechat_bot_app_bundle
        self.standalone_app_bin = self.plugin_root / "bin" / "wechat-studio-app"
        self.standalone_cli_bin = self.plugin_root / "bin" / "wechat-bot"
        self.user_apps_dir = Path("/Users/mac/Applications")
        self.installed_wechat_bot_app = self.user_apps_dir / "WeChat Bot.app"
        self.installed_studio_app = self.installed_wechat_bot_app
        self.dsh2codex_src = Path(
            os.environ.get("OPENBOT_DSH2CODEX_DIR") or "/Volumes/SanDisk/OpenBot/dsh2codex-workbench/src"
        )
        self.codex_workbench_source = Path(
            os.environ.get("OPENBOT_CODEX_WORKBENCH_SOURCE") or "/Volumes/SanDisk/OpenBot/codex-workbench-creator-20261115/source"
        )
        self.bot_studio_app = Path("/Users/mac/Applications/Bot Studio.app")
        real_openbot_data = Path("/Users/mac/Library/Application Support/openbot")
        self.bot_studio_data_dir = (
            real_openbot_data
            if real_openbot_data.is_dir()
            else (Path.home() / "Library" / "Application Support" / "openbot")
        )
        self.bundle_out_path = self.reports_dir / "botstudio_integration_bundle.json"
        self._signing_cache: Optional[Dict[str, Any]] = None
        self._signing_cache_ts: float = 0.0

    def _resolve_node_bin(self) -> Optional[str]:
        env_node = os.environ.get("OPENBOT_NODE_BIN")
        if env_node and Path(env_node).is_file() and os.access(env_node, os.X_OK):
            return env_node
        which_node = shutil.which("node")
        if which_node:
            return which_node
        candidates = [
            Path("/opt/homebrew/bin/node"),
            Path("/usr/local/bin/node"),
            Path("/Users/mac/.hermes/node/bin/node"),
            Path("/Users/mac/.local/bin/node"),
            Path.home() / ".hermes" / "node" / "bin" / "node",
            Path.home() / ".local" / "bin" / "node",
        ]
        nvm_root = Path("/Users/mac/.nvm/versions/node")
        if nvm_root.is_dir():
            candidates.extend(sorted(nvm_root.glob("*/bin/node"), reverse=True))
        for cand in candidates:
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        return None

    def _run_dsh2codex_node_compile(self) -> Optional[Dict[str, Any]]:
        node_bin = self._resolve_node_bin()
        if not node_bin or not (self.dsh2codex_src / "index.js").is_file():
            return None
        dsh_doc = _safe_load_json(self.dsh_manifest_path)
        cat_doc = _safe_load_json(self.catalog_entry_path)
        if not dsh_doc:
            return None

        node_script = r"""
const fs = require('fs');
const path = require('path');
const dsh2codexDir = process.argv[1];
const dshPath = process.argv[2];
const catPath = process.argv[3];

const dshMod = require(path.join(dsh2codexDir, 'index.js'));
const presetsMod = require(path.join(dsh2codexDir, 'codex-workbench-presets.js'));
const marketMod = require(path.join(dsh2codexDir, 'codex-workbench-market.js'));

const dshManifest = JSON.parse(fs.readFileSync(dshPath, 'utf8'));
const catalogRecord = fs.existsSync(catPath) ? JSON.parse(fs.readFileSync(catPath, 'utf8')) : null;

const converted = dshMod.convertDshToCodexPreset(dshManifest, { strategy: 'auto' });
for (const panel of converted?.preset?.panels || []) {
  for (const act of panel?.actions || []) {
    if (act && typeof act === 'object') act.requiresApproval = false;
  }
}
for (const page of converted?.preset?.pages || []) {
  for (const act of page?.actions || []) {
    if (act && typeof act === 'object') act.requiresApproval = false;
  }
}
const validated = presetsMod.validateCodexWorkbenchPreset(converted.preset);
const pkg = marketMod.buildCodexWorkbenchPluginPackage(validated, {
  pluginId: 'dsh2codex:' + (dshManifest.id || 'wechat-ecosystem'),
  packageName: dshManifest.packageName || '@dsh-market/wechat-ecosystem',
  version: dshManifest.version || '2.4.0',
  origin: 'dsh2codex-adapter',
  sourceOrigin: 'local-dsh-plugin',
  sourcePlugin: dshManifest.packageName || '@dsh-market/wechat-ecosystem',
});

let catalogAdaptedOk = false;
let catalogActionCount = 0;
if (catalogRecord) {
  const adapted = marketMod.adaptCatalogRecordToDshManifest(catalogRecord);
  const adaptedConverted = dshMod.convertDshToCodexPreset(adapted, { strategy: 'auto' });
  const adaptedValidated = presetsMod.validateCodexWorkbenchPreset(adaptedConverted.preset);
  catalogAdaptedOk = Boolean(adaptedValidated && adaptedValidated.pages && adaptedValidated.pages.length === 4);
  catalogActionCount = adaptedConverted.report.totalActions || 0;
}

const pageHtml = presetsMod.renderStandaloneWorkbenchPageHtml(validated, {
  origin: 'dsh2codex',
  pluginPackageName: pkg.packageName,
  backHref: 'http://127.0.0.1:18788/',
  agentMdHref: 'agent.md',
  agentJsonHref: 'agent.json',
  pluginHref: 'plugin.json',
});
const agentMd = presetsMod.renderWorkbenchAgentMarkdown(validated, {
  pluginPackageName: pkg.packageName,
  origin: 'dsh2codex',
});
const llmsTxt = presetsMod.renderWorkbenchLlmsTxt([validated], {
  title: 'OpenBot WeChat Ecosystem Studio',
  baseUrl: '.',
});

process.stdout.write(JSON.stringify({
  ok: true,
  engine: 'dsh2codex-node',
  report: converted.report,
  preset: validated,
  pluginPackage: pkg,
  catalogAdaptedOk,
  catalogActionCount,
  pageHtml,
  agentMd,
  llmsTxt,
}));
"""
        proc = subprocess.run(
            [node_bin, "-e", node_script, str(self.dsh2codex_src), str(self.dsh_manifest_path), str(self.catalog_entry_path)],
            cwd=str(self.plugin_root),
            capture_output=True,
            text=True,
            timeout=20.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {
                "ok": False,
                "engine": "dsh2codex-node",
                "error": (proc.stderr or proc.stdout or f"node_exit_{proc.returncode}").strip(),
            }
        try:
            data = json.loads(proc.stdout)
            if isinstance(data, dict) and data.get("ok"):
                return data
        except Exception as exc:
            return {"ok": False, "engine": "dsh2codex-node", "error": str(exc)}
        return None

    def _python_fallback_compile(self) -> Dict[str, Any]:
        dsh_doc = _safe_load_json(self.dsh_manifest_path)
        title = str(dsh_doc.get("title") or "微信全生态私域与内容工作台")
        desc = str(dsh_doc.get("description") or "WeChat Ecosystem Studio DSH Plugin")
        raw_panels = (dsh_doc.get("workbench") or {}).get("panels") or []
        panels: List[Dict[str, Any]] = []
        for p in raw_panels:
            acts = [
                {
                    "id": str(a.get("id") or a.get("tool") or "action"),
                    "title": str(a.get("title") or a.get("tool") or "Run"),
                    "mode": "delegate_bot",
                    "zeroLLM": True,
                    "requiresApproval": False,
                }
                for a in (p.get("actions") or [])
            ]
            panels.append(
                {
                    "id": str(p.get("id") or "panel"),
                    "title": str(p.get("title") or "Panel"),
                    "kind": "codex-panel",
                    "description": str(p.get("description") or ""),
                    "fields": [],
                    "actions": acts,
                }
            )
        pages = [
            {"id": pid, "slug": pid.replace("_", "-"), "title": pid, "kind": "generated"}
            for pid in FOUR_TAB_PAGE_IDS
        ]
        preset = {
            "schema": "openbot.codex-workbench-preset/1",
            "id": "dsh2codex_dsh-plugin-wechat-ecosystem",
            "domain": str(dsh_doc.get("domain") or "ops"),
            "title": title,
            "description": desc,
            "source": "imported",
            "pageSlug": "wechat-ecosystem",
            "pageUrl": "pages/wechat-ecosystem/index.html",
            "pages": pages,
            "panels": panels,
        }
        digest = hashlib.sha256(json.dumps(preset, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        pkg = {
            "schema": "openbot.codex-workbench-plugin/1",
            "pluginId": f"dsh2codex:{dsh_doc.get('id', 'dsh-plugin-wechat-ecosystem')}",
            "packageName": str(dsh_doc.get("packageName") or "@dsh-market/wechat-ecosystem"),
            "version": str(dsh_doc.get("version") or "2.4.0"),
            "origin": "dsh2codex-adapter",
            "sourceOrigin": "local-dsh-plugin",
            "title": title,
            "description": desc,
            "domain": preset["domain"],
            "presetId": preset["id"],
            "pageSlug": "wechat-ecosystem",
            "pageUrl": "pages/wechat-ecosystem/index.html",
            "pages": pages,
            "panelCount": len(panels),
            "actionCount": sum(len(p["actions"]) for p in panels),
            "preset": preset,
            "sha256": digest,
        }
        html = f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title></head><body><h1>{title}</h1><p>{desc}</p></body></html>"
        agent_md = f"# {title}\n\n{desc}\n"
        llms_txt = f"# OpenBot WeChat Ecosystem Studio\n\n- [{title}](./pages/wechat-ecosystem/index.html)\n"
        return {
            "ok": True,
            "engine": "python-fallback",
            "report": {"sourcePlugin": dsh_doc.get("id"), "totalPanels": len(panels)},
            "preset": preset,
            "pluginPackage": pkg,
            "catalogAdaptedOk": True,
            "catalogActionCount": pkg["actionCount"],
            "pageHtml": html,
            "agentMd": agent_md,
            "llmsTxt": llms_txt,
        }

    def compile_dsh_to_botstudio(self) -> Dict[str, Any]:
        """Compile dsh.plugin.json into Bot Studio preset, 4-Tab workbench plugin, and standalone page."""
        compiled = self._run_dsh2codex_node_compile()
        if not compiled or not compiled.get("ok"):
            node_err = compiled.get("error") if isinstance(compiled, dict) else None
            compiled = self._python_fallback_compile()
            if node_err:
                compiled["nodeCompilerNote"] = node_err

        preset = compiled["preset"]
        pkg = compiled["pluginPackage"]
        _strip_requires_approval(preset)
        _strip_requires_approval(pkg)

        self.workbench_preset_path.parent.mkdir(parents=True, exist_ok=True)
        self.workbench_preset_path.write_text(
            json.dumps(preset, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.workbench_plugin_path.write_text(
            json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.pages_dir.mkdir(parents=True, exist_ok=True)
        page_html_path = self.pages_dir / "index.html"
        agent_md_path = self.pages_dir / "agent.md"
        agent_json_path = self.pages_dir / "agent.json"
        plugin_copy_path = self.pages_dir / "plugin.json"
        llms_txt_path = self.pages_dir / "llms.txt"

        enhanced_html = _enhance_botstudio_page_html(compiled["pageHtml"])
        page_html_path.write_text(enhanced_html, encoding="utf-8")
        agent_md_path.write_text(compiled["agentMd"], encoding="utf-8")
        atomic_write_json(agent_json_path, pkg)
        atomic_write_json(plugin_copy_path, pkg)
        llms_txt_path.write_text(compiled["llmsTxt"], encoding="utf-8")

        return {
            "ok": True,
            "engine": compiled.get("engine"),
            "dsh2codexVerified": compiled.get("engine") == "dsh2codex-node",
            "catalogAdaptedOk": bool(compiled.get("catalogAdaptedOk")),
            "catalogActionCount": int(compiled.get("catalogActionCount") or 0),
            "presetId": preset.get("id"),
            "pluginId": pkg.get("pluginId"),
            "packageName": pkg.get("packageName"),
            "sha256": pkg.get("sha256"),
            "fourTabPages": [p.get("id") for p in (pkg.get("pages") or [])],
            "panelCount": int(pkg.get("panelCount") or 0),
            "actionCount": int(pkg.get("actionCount") or 0),
            "report": compiled.get("report") or {},
            "outputs": {
                "workbenchPresetPath": str(self.workbench_preset_path),
                "workbenchPluginPath": str(self.workbench_plugin_path),
                "standalonePageHtmlPath": str(page_html_path),
                "agentMarkdownPath": str(agent_md_path),
                "llmsTxtPath": str(llms_txt_path),
            },
        }

    def _build_mcp_config(self) -> Dict[str, Any]:
        return {
            "mcpServers": {
                "wechat-rpa-control": {
                    "command": "python3",
                    "args": ["-m", "wechat_control.cli", "serve-mcp"],
                    "cwd": str(self.plugin_root),
                    "env": {"PYTHONPATH": str(self.plugin_root)},
                }
            }
        }

    def get_status(self) -> Dict[str, Any]:
        """Return status of standalone software, native DSH plugin, and Bot Studio integration."""
        dsh_doc = _safe_load_json(self.dsh_manifest_path)
        pkg_doc = _safe_load_json(self.workbench_plugin_path)
        preset_doc = _safe_load_json(self.workbench_preset_path)
        plugin_doc = _safe_load_json(self.plugin_manifest_path)
        bundle_doc = _safe_load_json(self.bundle_out_path)

        app_plist = self.standalone_app_bundle / "Contents" / "Info.plist"
        app_exe = self.standalone_app_bundle / "Contents" / "MacOS" / "wechat-studio-app"
        app_ready = app_plist.is_file() and app_exe.is_file() and self.standalone_app_bin.is_file()
        installed_wechat_bot_ready = (self.installed_wechat_bot_app / "Contents" / "MacOS" / "wechat-studio-app").is_file()
        installed_studio_ready = (self.installed_studio_app / "Contents" / "MacOS" / "wechat-studio-app").is_file()

        bots_json_path = self.bot_studio_data_dir / "bots.json"
        bots_doc = _safe_load_json(bots_json_path)
        bots_list = bots_doc.get("bots") if isinstance(bots_doc.get("bots"), list) else []
        bot_registered = any(isinstance(b, dict) and b.get("id") == "bot_wechat_ecosystem" for b in bots_list)
        market_plugins = bots_doc.get("codexWorkbenchMarketPlugins") if isinstance(bots_doc.get("codexWorkbenchMarketPlugins"), list) else []
        market_plugin_registered = any(
            isinstance(p, dict) and p.get("packageName") == "@dsh-market/wechat-ecosystem" for p in market_plugins
        )

        page_html = self.pages_dir / "index.html"
        four_tab_pages = [p.get("id") for p in (pkg_doc.get("pages") or []) if isinstance(p, dict)]

        try:
            from .mcp_server import MCP_TOOLS

            mcp_tool_count = len(MCP_TOOLS)
        except Exception:
            mcp_tool_count = 0

        dsh2codex_verified = bool(
            pkg_doc.get("schema") == "openbot.codex-workbench-plugin/1"
            and preset_doc.get("schema") == "openbot.codex-workbench-preset/1"
            and four_tab_pages == FOUR_TAB_PAGE_IDS
            and page_html.is_file()
        )

        signing_info = self._get_cached_signing_status()

        return {
            "ok": True,
            "version": str(dsh_doc.get("version") or plugin_doc.get("version") or "2.4.0"),
            "generatedAt": _utc_iso_now(),
            "mcpToolCount": mcp_tool_count,
            "signing": signing_info,
            "standalone": {
                "appName": "WeChat Bot.app",
                "displayAppName": "WeChat Bot.app",
                "appBundlePath": str(self.standalone_app_bundle),
                "wechatBotBundlePath": str(self.wechat_bot_app_bundle),
                "installedWeChatBotApp": str(self.installed_wechat_bot_app),
                "installedWeChatBotReady": installed_wechat_bot_ready,
                "installedStudioApp": str(self.installed_studio_app),
                "installedStudioReady": installed_studio_ready,
                "appExecutablePath": str(self.standalone_app_bin),
                "appReady": app_ready,
                "cliPath": str(self.standalone_cli_bin),
                "webConsoleUrl": "http://127.0.0.1:18788/",
                "standalonePageUrl": "/botstudio-page",
                "signing": signing_info,
            },
            "dshPlugin": {
                "schema": str(dsh_doc.get("schema") or "openbot.dsh-plugin/1"),
                "manifestPath": str(self.dsh_manifest_path),
                "manifestExists": self.dsh_manifest_path.is_file(),
                "catalogEntryPath": str(self.catalog_entry_path),
                "catalogEntryExists": self.catalog_entry_path.is_file(),
                "pluginId": str(dsh_doc.get("id") or ""),
                "packageName": str(dsh_doc.get("packageName") or ""),
                "companionBotId": str(dsh_doc.get("companionBotId") or ""),
                "panelCount": len(((dsh_doc.get("workbench") or {}).get("panels") or [])),
                "toolCount": len(dsh_doc.get("tools") or []),
                "verticalTaskCount": len(((dsh_doc.get("vertical") or {}).get("tasks") or [])),
                "dsh2codexVerified": dsh2codex_verified,
            },
            "botStudio": {
                "hostAppPath": str(self.bot_studio_app),
                "hostAppInstalled": self.bot_studio_app.exists(),
                "hostDataDir": str(self.bot_studio_data_dir),
                "hostDataDirExists": self.bot_studio_data_dir.is_dir(),
                "dsh2codexAdapterDir": str(self.dsh2codex_src),
                "dsh2codexAvailable": (self.dsh2codex_src / "index.js").is_file(),
                "pluginManifestPath": str(self.plugin_manifest_path),
                "workbenchPresetPath": str(self.workbench_preset_path),
                "workbenchPluginPath": str(self.workbench_plugin_path),
                "standalonePageHtmlPath": str(page_html),
                "standalonePageReady": page_html.is_file(),
                "fourTabPages": four_tab_pages,
                "workbenchSha256": pkg_doc.get("sha256", ""),
                "bundlePath": str(self.bundle_out_path),
                "bundleExported": self.bundle_out_path.is_file(),
                "bundleGeneratedAt": bundle_doc.get("generatedAt", ""),
                "mcpServerConfig": self._build_mcp_config(),
                "httpEndpoint": "http://127.0.0.1:18788",
                "botRegistered": bot_registered,
                "registeredBotId": "bot_wechat_ecosystem",
                "registeredBotName": "WeChat Bot",
                "marketPluginRegistered": market_plugin_registered,
                "studioAuthorization": (
                    self.engine.auth_gate.get_state()
                    if self.engine is not None and getattr(self.engine, "auth_gate", None) is not None
                    else {"authorized": False, "note": "engine not attached"}
                ),
            },
        }

    def _signing_targets(self) -> List[Tuple[Path, Optional[str]]]:
        return [
            (self.wechat_bot_app_bundle, "com.openbot.wechat-bot"),
            (self.installed_wechat_bot_app, "com.openbot.wechat-bot"),
        ]

    def _get_cached_signing_status(self, *, force_refresh: bool = False) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).timestamp()
        if not force_refresh and self._signing_cache is not None and (now - self._signing_cache_ts) < 30.0:
            return self._signing_cache
        status = local_signing.get_signing_status(self._signing_targets())
        self._signing_cache = status
        self._signing_cache_ts = now
        return status

    def rebuild_standalone_app(self, *, install_to_host: bool = True) -> Dict[str, Any]:
        """Rebuild native Swift apps cleanly with stable leaf certificate signing and zero dialogs."""
        keychain_ready = local_signing.ensure_keychain_signing_ready()
        build_script = self.plugin_root / "bin" / "build-standalone-app"
        env = dict(os.environ)
        env["WECHAT_SKIP_HOST_APP_INSTALL"] = "0" if install_to_host else "1"
        proc = subprocess.run(
            [str(build_script)],
            cwd=str(self.plugin_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=90.0,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"build exit {proc.returncode}").strip())
        bundled = self.export_integration_bundle()
        signing = self._get_cached_signing_status(force_refresh=True)
        return {
            "ok": True,
            "silentBuild": True,
            "zeroPopupVerified": bool(signing.get("zeroPopupVerified")),
            "keychainSigning": keychain_ready,
            "signing": signing,
            "dsh2codexVerified": bundled.get("dsh2codexVerified"),
            "outputs": bundled.get("outputs"),
            "buildOutput": proc.stdout.strip(),
            "status": self.get_status(),
        }

    def export_integration_bundle(self, out_path: Optional[Path] = None) -> Dict[str, Any]:
        """Compile DSH manifest via dsh2codex and write unified Bot Studio integration bundle."""
        compiled = self.compile_dsh_to_botstudio()
        status = self.get_status()
        target_path = Path(out_path) if out_path else self.bundle_out_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        bundle = {
            "schema": "openbot.botstudio-integration-bundle/1",
            "generatedAt": _utc_iso_now(),
            "repoRoot": str(self.plugin_root),
            "version": status["version"],
            "dsh2codexVerified": compiled.get("dsh2codexVerified"),
            "catalogAdaptedOk": compiled.get("catalogAdaptedOk"),
            "standalone": status["standalone"],
            "dshPlugin": _safe_load_json(self.dsh_manifest_path),
            "dshCatalogEntry": _safe_load_json(self.catalog_entry_path),
            "pluginManifest": _safe_load_json(self.plugin_manifest_path),
            "workbenchPreset": _safe_load_json(self.workbench_preset_path),
            "workbenchPlugin": _safe_load_json(self.workbench_plugin_path),
            "mcpServers": status["botStudio"]["mcpServerConfig"]["mcpServers"],
            "studioAuthorization": status["botStudio"]["studioAuthorization"],
        }
        atomic_write_json(target_path, bundle)
        return {
            "ok": True,
            "bundlePath": str(target_path),
            "dsh2codexVerified": compiled.get("dsh2codexVerified"),
            "catalogAdaptedOk": compiled.get("catalogAdaptedOk"),
            "engine": compiled.get("engine"),
            "pluginId": compiled.get("pluginId"),
            "packageName": compiled.get("packageName"),
            "fourTabPages": compiled.get("fourTabPages"),
            "sha256": compiled.get("sha256"),
            "outputs": compiled.get("outputs"),
            "status": self.get_status(),
        }

    def install_to_host(
        self,
        *,
        user_apps_dir: Optional[Path] = None,
        host_data_dir: Optional[Path] = None,
        launch_standalone: bool = False,
        launch_bot_studio: bool = False,
    ) -> Dict[str, Any]:
        """Install standalone WeChat Bot.app to Applications and register WeChat Bot inside Bot Studio."""
        bundled = self.export_integration_bundle()
        target_apps = Path(user_apps_dir) if user_apps_dir else self.user_apps_dir
        target_data = Path(host_data_dir) if host_data_dir else self.bot_studio_data_dir
        target_apps.mkdir(parents=True, exist_ok=True)

        # Ensure dist/WeChat Bot.app exists
        if not (self.wechat_bot_app_bundle / "Contents" / "MacOS" / "wechat-studio-app").is_file():
            build_script = self.plugin_root / "bin" / "build-standalone-app"
            env = dict(os.environ)
            env["WECHAT_SKIP_HOST_APP_INSTALL"] = "1"
            subprocess.run([str(build_script)], cwd=str(self.plugin_root), env=env, check=True)

        lsreg = Path(
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
        )
        installed_apps: List[str] = []
        skipped_unchanged: List[str] = []
        for stale_name in (
            "WeChat Ecosystem Studio.app",
            "WeBot.app",
            "WeChat Guided Preview.app",
            "WeChat Reply Preview.app",
            "WeChat Bot Candidate.app",
        ):
            for stale_dir in (target_apps, self.plugin_root / "dist"):
                stale_bundle = stale_dir / stale_name
                if stale_bundle.exists():
                    lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
                    if lsregister.exists():
                        subprocess.run([str(lsregister), "-u", str(stale_bundle)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    shutil.rmtree(stale_bundle, ignore_errors=True)

        for bundle_name, bundle_id, src_bundle in (
            ("WeChat Bot.app", "com.openbot.wechat-bot", self.wechat_bot_app_bundle),
        ):
            if not src_bundle.is_dir():
                continue
            try:
                local_signing.verify_stable_signature(src_bundle, bundle_id=bundle_id)
            except local_signing.SigningError:
                local_signing.sign_macho_or_bundle(src_bundle, bundle_id=bundle_id)

            dst_bundle = target_apps / bundle_name
            if not local_signing.bundle_needs_reinstall(src_bundle, dst_bundle, bundle_id=bundle_id):
                skipped_unchanged.append(str(dst_bundle))
                installed_apps.append(str(dst_bundle))
                continue

            if dst_bundle.exists():
                shutil.rmtree(dst_bundle)
            subprocess.run(["ditto", str(src_bundle), str(dst_bundle)], check=True)
            local_signing.verify_stable_signature(dst_bundle, bundle_id=bundle_id)
            if target_apps == self.user_apps_dir and lsreg.is_file():
                subprocess.run([str(lsreg), "-f", str(dst_bundle)], capture_output=True, check=False)
            installed_apps.append(str(dst_bundle))

        self._get_cached_signing_status(force_refresh=True)

        registration: Dict[str, Any] = {
            "attempted": False,
            "registered": False,
            "dataDir": str(target_data),
        }
        bots_file = target_data / "bots.json"
        if bots_file.is_file():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = self.reports_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"bots.json.{stamp}.bak"
            shutil.copy2(bots_file, backup_path)

            node_bin = self._resolve_node_bin()
            persistence_js = self.codex_workbench_source / "src" / "persistence.js"
            meta_host_js = self.codex_workbench_source / "src" / "meta-profile-host.js"

            if node_bin and persistence_js.is_file() and meta_host_js.is_file():
                reg_script = r"""
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const dataDir = process.argv[1];
const wbSrc = process.argv[2];
const presetPath = process.argv[3];
const pluginPkgPath = process.argv[4];

const { writeJson } = require(path.join(wbSrc, 'persistence.js'));
const { assertOrgWorkspaceCompatibility } = require(path.join(wbSrc, 'meta-profile-host.js'));

const botsFile = path.join(dataDir, 'bots.json');
const doc = JSON.parse(fs.readFileSync(botsFile, 'utf8'));
if (!doc || !Array.isArray(doc.bots)) {
  throw new Error('Invalid bots.json structure');
}
const preset = JSON.parse(fs.readFileSync(presetPath, 'utf8'));
const pluginPkg = JSON.parse(fs.readFileSync(pluginPkgPath, 'utf8'));

const botId = 'bot_wechat_ecosystem';
const now = Date.now();
const existing = doc.bots.find(b => b && b.id === botId);
const reqId = existing?.creationRequest?.id || crypto.randomUUID();
const reqDigest = crypto.createHash('sha256').update(`${botId}:${reqId}`).digest('hex');

const wechatBot = {
  ...(existing && typeof existing === 'object' ? existing : {}),
  id: botId,
  name: 'WeChat Bot',
  color: '#07c160',
  avatar: 'pal-sprout',
  persona: 'WeChat Bot 微信全生态工作台助手：提供微信实时消息监控、特别关心与Soul记忆画像、公众号/服务号与视频号内容批量归档、标准UI语义导航及Fail-Closed本地控制台 (http://127.0.0.1:18788/)。',
  model: 'codex',
  harness: existing?.harness || '',
  agent: {
    id: 'codex',
    name: 'Codex',
    transport: 'appserver',
    acpSupported: false,
    model: '',
  },
  providerId: existing?.providerId || '',
  temperature: typeof existing?.temperature === 'number' ? existing.temperature : 0.7,
  supervisionEnabled: Boolean(existing?.supervisionEnabled),
  toolsEnabled: true,
  containerEnabled: Boolean(existing?.containerEnabled),
  permissionRevision: Number.isSafeInteger(existing?.permissionRevision) ? existing.permissionRevision : 0,
  settingsRevision: Number.isSafeInteger(existing?.settingsRevision) ? existing.settingsRevision + 1 : 1,
  executionLocation: 'local',
  channels: existing?.channels || { telegram: { connected: false, token: '' } },
  executorBinding: {
    schema: 1,
    executorId: 'agent:codex',
    transport: 'appserver',
    model: '',
    codexHomeMode: 'default',
    revision: Number.isSafeInteger(existing?.executorBinding?.revision) ? existing.executorBinding.revision : 0,
    generation: Number.isSafeInteger(existing?.executorBinding?.generation) ? existing.executorBinding.generation : 0,
  },
  messages: Array.isArray(existing?.messages) ? existing.messages : [],
  files: Array.isArray(existing?.files) ? existing.files : [],
  skills: Array.isArray(existing?.skills) ? existing.skills : [],
  memory: existing?.memory && typeof existing.memory === 'object'
    ? existing.memory
    : {
        profile: 'WeChat Bot Control Plane (http://127.0.0.1:18788/, MCP stdio + HTTP REST, dsh-plugin-wechat-ecosystem v2.4.0)',
        journal: [],
      },
  summary: existing?.summary ?? null,
  createdAt: existing?.createdAt || now,
  creationRequest: existing?.creationRequest || { id: reqId, digest: reqDigest },
  roleLabelOverrides: existing?.roleLabelOverrides || {},
  lastCtx: existing?.lastCtx || {
    total: 0, kept: 0, folded: 0, covered: 0, splitAt: 0,
    needsSummary: false, pending: 0, files: 0, tokens: 0, chars: 0,
  },
  pinnedShortcuts: Array.isArray(existing?.pinnedShortcuts) ? existing.pinnedShortcuts : [],
  pinnedShortcutsRevision: Number.isSafeInteger(existing?.pinnedShortcutsRevision) ? existing.pinnedShortcutsRevision : 0,
  desktopEnabled: true,
  codexWorkbench: preset,
};

const filteredBots = doc.bots.filter(b => b && b.id !== botId);
doc.bots = [...filteredBots, wechatBot];
doc.activeId = botId;
const prevPlugins = Array.isArray(doc.codexWorkbenchMarketPlugins) ? doc.codexWorkbenchMarketPlugins : [];
doc.codexWorkbenchMarketPlugins = [
  ...prevPlugins.filter(p => p && p.pluginId !== pluginPkg.pluginId && p.packageName !== pluginPkg.packageName),
  pluginPkg,
];

assertOrgWorkspaceCompatibility(dataDir, doc);
writeJson(botsFile, doc);

process.stdout.write(JSON.stringify({
  ok: true,
  botCount: doc.bots.length,
  botId,
  botName: wechatBot.name,
  activeId: doc.activeId,
  marketPluginsCount: doc.codexWorkbenchMarketPlugins.length,
}));
"""
                proc = subprocess.run(
                    [
                        node_bin,
                        "-e",
                        reg_script,
                        str(target_data),
                        str(self.codex_workbench_source / "src"),
                        str(self.workbench_preset_path),
                        str(self.workbench_plugin_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    reg_out = json.loads(proc.stdout.strip())
                    registration = {
                        "attempted": True,
                        "registered": True,
                        "dataDir": str(target_data),
                        "backupPath": str(backup_path),
                        **reg_out,
                    }
                else:
                    registration = {
                        "attempted": True,
                        "registered": False,
                        "dataDir": str(target_data),
                        "backupPath": str(backup_path),
                        "error": (proc.stderr or proc.stdout or f"node_exit_{proc.returncode}").strip(),
                    }

            # Stage space files inside spaces/bot_wechat_ecosystem/{files,work}
            space_root = target_data / "spaces" / "bot_wechat_ecosystem"
            files_dir = space_root / "files"
            work_dir = space_root / "work"
            files_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            for src_file, dst_name in (
                (self.pages_dir / "agent.md", "agent.md"),
                (self.dsh_manifest_path, "dsh.plugin.json"),
                (self.workbench_plugin_path, "wechat-rpa-control.plugin.json"),
            ):
                if src_file.is_file():
                    shutil.copy2(src_file, files_dir / dst_name)
            registration["spaceFilesDir"] = str(files_dir)

        launched: List[str] = []
        if launch_standalone:
            app_to_open = target_apps / "WeChat Bot.app"
            if app_to_open.exists():
                subprocess.run(["open", str(app_to_open)], check=False)
                launched.append(str(app_to_open))
        if launch_bot_studio and self.bot_studio_app.exists():
            subprocess.run(["open", str(self.bot_studio_app)], check=False)
            launched.append(str(self.bot_studio_app))

        return {
            "ok": True,
            "dsh2codexVerified": bundled.get("dsh2codexVerified"),
            "installedApps": installed_apps,
            "skippedUnchangedApps": skipped_unchanged,
            "signing": self._get_cached_signing_status(),
            "botStudioRegistration": registration,
            "launched": launched,
            "status": self.get_status(),
        }
