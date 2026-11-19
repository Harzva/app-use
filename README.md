# App-Use Studio

[![Version](https://img.shields.io/badge/version-v2.9.0-black?style=flat-square)](https://github.com/Harzva/app-use)
[![Website](https://img.shields.io/badge/pages-harzva.github.io%2Fapp--use-black?style=flat-square)](https://harzva.github.io/app-use/)
[![Platform](https://img.shields.io/badge/platform-macOS%2014%2B%20Apple%20Silicon-black?style=flat-square)](https://github.com/Harzva/app-use)
[![Runtime](https://img.shields.io/badge/python-3.9%2B%20stdlib%20zero--dep-black?style=flat-square)](https://github.com/Harzva/app-use)

> **Completing the Agent Action Trilogy: `Browser-Use` → `Computer-Use` → `App-Use`.**
>
> **App-Use Studio**（原 `WeChat Bot` 演进而来）是一个专为 macOS 设计的**窗口级桌面 App-Use 与 Meta-RPA 元能力引擎**——不依赖浏览器 DOM，也不用全屏截图瞎猜，直接锁定目标应用窗口的 `AXUIElement` + `Apple Vision OCR` 双通道感知，实现**安全原生 App 后台无焦点真并发**与**高风控社交客户端（微信、企微、钉钉、飞书、小红书、抖音等）硬隔离防封调度**。

🌐 **项目主页 (GitHub Pages)**: [https://harzva.github.io/app-use/](https://harzva.github.io/app-use/)
📦 **GitHub 仓库**: [https://github.com/Harzva/app-use](https://github.com/Harzva/app-use)（原 `Harzva/wechat-bot` 仓库平滑升级更名）

---

## 为什么需要独立的 Window-Scoped App-Use？

| 对比维度 | Browser-Use | 传统 Computer-Use | **App-Use Studio (`v2.9.0`)** |
| :--- | :--- | :--- | :--- |
| **覆盖软件范围** | 仅限浏览器网页 DOM | 全桌面截图，易受无关弹窗/多屏干扰 | **精确锁定 `bundleID + windowID`**，覆盖微信/钉钉/飞书/小红书与任意本地原生 App |
| **控件定位精度** | 依赖 HTML DOM（原生客户端无 DOM） | 全屏纯视觉像素点击，窗口一移动即偏移 | **5 信号语义锚点**（`identifier` / 中英双语词法 / `role` / 相对坐标 / 邻域文本）+ 自动重试自愈 |
| **并发与焦点冲突** | 仅网页多 Tab 可并发 | 单系统指针，并发即抢焦点互相打架 | **双通道分层并发**：只读监控 (`--no-activate`) 与安全原生 `AXPress`/`AXSetValue` 真并发；前景操作走 `ForegroundHIDLease` |
| **反封号安全策略** | 受限于站点反爬 | 默认盲点键鼠 | **三级反风控护栏引擎**：硬屏蔽高风控社交 App 后台静默写注入，强制前台拟真节奏防封 |

---

## 核心技术架构（`v2.9.0`）

### 1. 5 大未知 App 泛化与并发算法（`wechat_control/app_use_meta_algo.py`）
无需对每个新 App 硬编码脚本，接通任意 Agent 即可快速把未知桌面 App 编译为可复用 SOP + 便携式 `SKILL.md`：
1. **`SemanticElementGrounder`**：中英双语 UI 同义词表 + CJK bigram 词法匹配 + 高斯空间距离 + 相邻参照物校验与抗 UI 漂移锚点包。
2. **UI 状态摘要、弹窗识别与 6 大拓扑原型 (`AppUIStateGraph`)**：自动归类 `list_detail_master`、`document_editor`、`chat_agent_surface`、`keypad_or_tool`、`form_workbench`、`canvas_or_opaque`，持续沉淀跨运行状态转移边 (`stateHash` 图谱)。
3. **轨迹压缩与 A–F 可上线度评分 (`score_workflow_readiness`)**：自动去重冗余激活与死点击，对工作流给出 0–100 分上线就绪评估。
4. **失败分类学定向自愈 (`classify_step_failure`)**：区分弹窗阻断、权限/登录门禁、焦距丢失与要素漂移，关键门禁自动触发 `pause_for_human` 等待人工确认。
5. **多窗口并发保护 (`ForegroundHIDLease`)**：保证需要动用真鼠标/剪贴板的前景临界区严格互斥，其余观察、等态与 AI 规划全并发。

### 2. 无焦点后台 AX 直调双通道 + 平滑降级（`v2.9.0`）
在原生 Swift 驱动 `native/wechat_vision_ax.swift` 新增：
- **`app-use-ax-action`**：在后台通过 `AXUIElementPerformAction(AXPress)` 触发按钮，**零激活、零鼠标移动、零剪贴板触碰**。
- **`app-use-ax-set-value`**：写入前检查 `AXUIElementIsAttributeSettable(..., kAXValue)` 与 `AXConfirm` 支持度，写后立即读回验证；若遇到自绘/WebView 控件不支持后台直写，自动标记原因并平滑降级至 `ForegroundHIDLease` 前台真实执行。

### 3. 三级反风控保护分级（`classify_app_risk_tier` + `AntiRiskPacer`）
- **🔴 `high_risk_social`（微信 / 企微 / 钉钉 / 飞书 / 小红书 / 抖音 / 支付宝 / 金融类）**：
  - **`allowHeadlessAxWrite = false` 硬隔离**：即便外部调用显式传入 `headless_ax_first`，调度器也会自动拦截后台注入（`riskGuardEnforced = true`）；
  - 写操作强制走 `ForegroundHIDLease` 前台真实焦点 + `350 ms` 最小动作冷却 + `260–780 ms` 随机人类节奏抖动；后台只读观察限制为 `0.5 Hz`。
- **🟡 `moderate_agent_or_web`（ChatGPT / Chrome / Electron 等）**：支持无焦点 AX 直调优先，失败自动平滑降级前台，带 `90–240 ms` 轻节流。
- **🟢 `safe_native`（TextEdit / Calculator / Dictionary / Finder 等本地原生工具）**：零封号风险，默认 `headless_ax_first` 零抢焦点并发执行。

### 4. Bot Studio + Codex MCP + 全局 Meta Skill 三位一体协同
- **标准 stdio MCP (`wechat-bot serve-mcp`)**：暴露 **`69` 个 MCP 工具**（含 **`16` 个 `app_use_*` 工具**），可直接注册至 Codex / Bot Studio / Antigravity。
- **原生 DSH 插件 (`dsh.plugin.json`)**：内置 `20` 个 DSH 工具与 `5` 大工作台面板（含 `app_use_generalization_panel`），支持 `dsh2codex` 编译生成 4-Tab 工作台与独立静态页。
- **全局 Meta Skill (`skills/app-use-meta-builder/SKILL.md`)**：安装后任何 Agent 对话一句 *“帮我把 XXX 新 App 做成可复用 RPA Skill”* 即可端到端跑通。
- **保留全部微信全生态能力**：好友智能托管、多窗并发巡检、Soul 性格与好友记忆、SalesCRM 15 维营销漏斗、公众号/服务号/视频号导出及原生 VoIP 语音协同。

---

## 实机验收基准与工程证据

以下数据均为在本机（macOS 14+ Apple Silicon）真机实测所得，非估算值：
- **全量单元测试**：`174 / 174` 全部通过（覆盖元算法、双通道无焦点 AX、三级风控硬拦截、MCP/HTTP 接口、DSH `dsh2codex` 编排与侧栏 UI）。
- **真机“零抢焦点 + 零碰剪贴板”多窗并发实测**：在刻意将系统焦点留在 `Finder`、剪贴板写入哨兵字符串的前提下，后台同时并发操作 `TextEdit`（`AXSetValue`）与 `Calculator`（`AXPress` `AllClear` + `9`）：
  - 前台全程保持 `com.apple.finder`，剪贴板哨兵保持原样未改；
  - `jobCount = 2` / `succeededCount = 2`，实测并行加速比 **`1.86x`**，`hidLeaseStats.totalAcquisitions = 0`，`headlessSharePct = 100.0%`。
- **3 窗口并行无焦点观察 (`watch_windows_parallel`)**：同时观察 `Calculator`、`微信`、`TextEdit`，`3/3` 成功，耗时 `476.4 ms`，加速比 **`1.77x`**。
- **未知 App 泛化实测 (`com.apple.Dictionary`)**：无模板前提下自动识别为 `list_detail_master`，生成含语义+邻域锚点包的 7 步工作流并导出独立可调用 `SKILL.md`。

---

## 5 分钟快速开始

### 1. 克隆与构建（macOS 14+ Apple Silicon + Xcode CLI + Python 3.9+）

```bash
git clone https://github.com/Harzva/app-use.git
cd app-use
./bin/build-standalone-app
open "/Users/$(whoami)/Applications/WeChat Bot.app"
```

> **提示**：为了平滑保留本机 macOS **辅助功能（Accessibility）、系统事件控制与屏幕录制** TCC 授权与本地叶证书签名，底层 `.app` 包标识 `CFBundleIdentifier` 继续沿用 `com.openbot.wechat-bot`，无需重设权限。

### 2. 启动控制台、CLI 与 MCP Server

```bash
# 环境与权限自检
./bin/wechat-bot doctor

# 打开 Web 控制台（含 App-Use 流程工厂与多窗口并发泳道监控）
./bin/wechat-bot console --host 127.0.0.1 --port 18788

# 以 stdio JSON-RPC 2.0 MCP Server 启动（69 工具 / 16 个 app_use_*）
./bin/wechat-bot serve-mcp
```

### 3. 接入 Codex / Bot Studio（`config.toml` 示例）

在 `~/.codex/config.toml` 中添加：

```toml
[mcp_servers.wechat-app-use]
command = "/Users/<your-user>/Applications/WeChat Bot.app/Contents/Resources/bin/wechat-bot"
args = ["serve-mcp"]

[mcp_servers.wechat-app-use.env]
HOME = "/Users/<your-user>"
WECHAT_BOT_DATA_DIR = "/Users/<your-user>/Library/Application Support/WeChatBot"
```

---

## 目录结构

- `wechat_control/app_use_meta_algo.py`：5 大 Meta-RPA 泛化算法、三级风控引擎、`AntiRiskPacer`、`ConcurrencyLaneTracker`
- `wechat_control/app_use_studio.py`：App 盘点、泛化流编译、双通道执行器、多窗并发调度与 Meta Skill 安装器
- `wechat_control/{engine,mcp_server,cli,web_console,botstudio_bridge,auth_gate}.py`：核心引擎、69 工具 MCP Server、HTTP 控制台与 Bot Studio 桥接
- `native/wechat_vision_ax.swift` & `native/wechat_studio_app.swift`：原生 macOS AXUIElement + Vision OCR + 无焦点 AX 直调 + WKWebView 宿主外壳
- `skills/app-use-meta-builder/SKILL.md`：通用未知新 App RPA 元能力技能文档
- `dsh.plugin.json`：Bot Studio 原生 DSH 插件声明（20 Tools / 5 Panels）
- `docs/index.html`：项目 GitHub Pages 文档页（[https://harzva.github.io/app-use/](https://harzva.github.io/app-use/)）
- `tests/`：174 项自动化单元测试套件
