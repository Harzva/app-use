---
name: app-use-meta-builder
description: "Meta-RPA Generalization Skill for macOS: turn ANY unseen desktop app into a parameterized SOP workflow + portable SKILL.md via WeChat Bot Universal App-Use Engine (AXUIElement + Vision OCR + Archetype Inference + Self-Healing + Multi-Window Parallel Watch)."
---

# App-Use Meta Builder — 通用未知新 App RPA 元能力技能

当用户要求 **“帮我把某个新 App 做成可复用 RPA / 自动化流程 / SOP / Skill”**、**“泛化到一个没见过的新桌面应用”** 或 **“并行监控多个桌面应用窗口”** 时，按本指南直接调用本地 **WeChat Bot App-Use Engine**（默认 HTTP `http://127.0.0.1:18788` 与 MCP 工具）端到端完成，禁止对每个新 App 写死专用坐标脚本。

## 为什么这套方案能泛化未知 App（且支持多窗口并发）
- **Window-Scoped 精准视野**：通过 macOS `CGWindowID` + `AXUIElement(pid)` 锁定单个目标应用窗口，避免全屏截图冗余噪声和网页 Sandbox 限制（原生桌面 App 如微信、企微、词典、Figma、终端均可直控）。
- **多因子语义+空间+拓扑定位 (`SemanticElementGrounder`)**：融合双语同义词/CJK bigram、`identifier/role`、分辨率无关归一化坐标与邻域参照物 `neighborTexts`，窗口缩放或轻微改版仍可自愈锚定。
- **并发与安全性清晰分层**：多窗口只读巡检/OCR/等待/LLM 规划可在后台线程真并行（`--no-activate`）；仅前台键鼠输入/剪切板由 `ForegroundHIDLease` 微租约原子串行护栏保护。

## 标准 4 步元工作流（Zero-Hardcoding Generalization）

### Phase 1 — 探测目标 App 与拓扑原型（只读无侵入）
- MCP：`app_use_list_apps` → 找到目标应用的 `bundleID` / `appPath`。
- HTTP：`POST http://127.0.0.1:18788/api/app-use/inspect`（返回 `archetype`、`uiState.stateHash`、`modalStatus`、`axControls`、`ocrElements`）。
- 若检测到 `modalStatus.kind == "auth_or_risk_gate"`（登录扫码/密码/支付/不可逆确认），先停下让用户人工处理。

### Phase 2 — 一键泛化生成并自动评分 + 打包为独立 Skill
- **推荐一键元工具（MCP `app_use_generalize_app` 或 `POST /api/app-use/generalize`）**：
```json
{
  "goal": "唤醒目标 App，完成关键操作并回读验收结果",
  "bundle_id": "com.example.TargetApp",
  "agent_id": "magpie:group/omini-balanced",
  "mode": "auto",
  "dry_run_verify": true,
  "export_skill": true,
  "launch_if_needed": true
}
```
- 若流程长或页面动态多跳，用 **`app_use_explore_and_build`**（Observe→Think→Act→Verify 多轮自主探索 + 状态环防死循环）。
- 若界面操作难以用文字说清，调用 **`app_use_record_demo`** 让人类示范操作一次后自动编译成带 `{{变量}}` 的 SOP。

### Phase 3 — Dry-Run 校验、实机联跑与跨应用流水线
1. 先检查返回的 `readiness`（`score` / `grade`）与 `dryRunVerification.ok`。
2. 实机执行必须显式带 `confirm_run: true`：
   - 单应用执行：`app_use_run_workflow`（建议开启 `self_heal: true`；关键读数步骤可设 `waitUntilChanged: true`、`waitUntilStable: true` 与 `captureAs: "var_name"`）。
   - 跨应用联动：`app_use_run_pipeline`（自动把上一阶段采集的 `{{var_name}}` 注入下一款 App）。

### Phase 4 — 多窗口并行关注、风控分级双通道 & 状态图谱复用
- 查询应用反风控分级策略：`app_use_risk_profile`（`GET /api/app-use/risk-profile?bundle_id=...`）：
  - **高风控社交/金融 App**（微信、企微、钉钉、飞书、小红书、抖音等 `high_risk_social`）：硬隔离禁止无焦点后台 AX 写入，强制 `foreground_human_paced`（`ForegroundHIDLease` 前台真实焦点 + 随机拟真节奏抖动），严防非前景注入异常事件触发风控。
  - **安全原生/办公 App**（计算器、文本编辑、词典、Finder 等 `safe_native`）：默认开启 `headless_ax_first`，优先通过无焦点 `AXPress` / `AXSetValue` 直调实现**不抢鼠标、不占剪贴板、零焦点切换真并发**，不支持或校验不通过时自动平滑降级为 `ForegroundHIDLease`。
- 并行观察多个窗口最新文本与弹窗阻断：`app_use_watch_parallel`（或 `POST /api/app-use/watch-parallel`）。
- 并发调度多套流程：`app_use_run_parallel`（支持 `dispatch_mode`: `auto` / `headless_ax_first` / `foreground_hid_only`）。
- 实时多窗口并发泳道监控：`app_use_concurrency_status`（`GET /api/app-use/concurrency-status`）。
- 查看跨运行沉淀下来的页面迁移先验：`app_use_state_graph`（`GET /api/app-use/state-graph`）。

## 安全红线（必须严格遵守）
1. 任何未经用户确认的高风险动作（外发消息、支付、删除、提交表单）必须在关键步骤保留 `pause_for_human`。
2. 实机运行始终尊重 `HumanActivityGuard`；用户键鼠活跃时立即让路。
3. 导出 Skill 与截图存证统一存放在 `/Volumes/SanDisk/Builds/WeChatBot/`，不写内盘垃圾缓存。
