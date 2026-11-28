# App-Use Studio (`v3.2.0`)

[![Version](https://img.shields.io/badge/version-v3.2.0-black?style=flat-square)](https://github.com/Harzva/app-use/releases/tag/v3.2.0)
[![User Guide](https://img.shields.io/badge/guide-零黑话用户手册-black?style=flat-square)](https://harzva.github.io/app-use/user-guide.html)
[![Website](https://img.shields.io/badge/pages-harzva.github.io%2Fapp--use-black?style=flat-square)](https://harzva.github.io/app-use/)
[![Platform](https://img.shields.io/badge/platform-macOS%2014%2B%20Apple%20Silicon-black?style=flat-square)](https://github.com/Harzva/app-use)
[![Runtime](https://img.shields.io/badge/python-3.9%2B%20stdlib%20zero--dep-black?style=flat-square)](https://github.com/Harzva/app-use)

> **Completing the Agent Action Trilogy: `Browser-Use` → `Computer-Use` → `App-Use`.**
>
> **App-Use Studio**（`WeChat Bot.app` v3.2.0）是一个专为 macOS 设计的**窗口级桌面 App-Use 与 Meta-RPA 元能力引擎**。在 `v3.0.0` 零配置（Zero-FDE）客户自助闭环基础上，**`v3.2.0` 正式推出「AI 对话建流程与一句话改流程」**：只需像聊天一样说出需求，即可泛化扩展飞书、钉钉、企业微信、抖音、小红书等跨软件业务流程，内置 Shadow 预览卡安全护栏、多步连续撤销与微信 `#建流程` / `#改流程` 多轮遥控；底层继续由目标窗口 `AXUIElement` + `Apple Vision OCR` 双通道感知驱动，兼顾安全原生 App 后台无焦点真并发与高风控社交客户端防封隔离。

📖 **零黑话用户手册（网页版）**: [https://harzva.github.io/app-use/user-guide.html](https://harzva.github.io/app-use/user-guide.html)（含安装权限指引、4 步向导、可复制 `#` 指令速查表、AI 对话建流程/改流程与 10 大常见问题排查）  
⬇️ **v3.2.0 macOS 安装包下载**: [https://github.com/Harzva/app-use/releases/tag/v3.2.0](https://github.com/Harzva/app-use/releases/tag/v3.2.0)  
🛠️ **开发者架构文档**: [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md)（v3 架构、SQLite Schema、HTTP/MCP/CLI 全接口参考）  
🌐 **项目主页 (GitHub Pages)**: [https://harzva.github.io/app-use/](https://harzva.github.io/app-use/)  
📦 **GitHub 仓库**: [https://github.com/Harzva/app-use](https://github.com/Harzva/app-use)（原 `Harzva/wechat-bot` 仓库平滑升级更名）

---

## v3.2.0 AI 对话建流程与一句话改流程亮点

- **多轮对话式建流程 · 跨软件多渠道泛化**：无需写脚本、也不用一次想清细节，在「AI 场景自建与自动调试工坊」输入模糊想法（如 *“帮我搞个飞书同步”* 或 *“把钉钉客户提取微信号加微信”*），系统自动以 1–3 道通俗选择题理清来源软件（飞书 / 钉钉 / 企业微信 / 抖音 / 小红书）、客户备注前缀与确认门禁，一键生成跨应用步骤卡并自动调试。
- **Shadow 预览卡安全护栏**：默认在影子调试模式下真实读取界面与抽取逻辑，并在右侧时间线输出结构化 **Shadow 预览卡片**（拟添加微信号、备注、打招呼话术、CRM 标签）与高清截图存证，自动拦截高风险外发消息与加好友动作，杜绝误发误加。
- **一句话改流程 · 自动回归与多步连续撤销**：建好流程后可用自然语言一句话微调（改备注前缀、加老客户/空号跳过分支、给 CRM 加标签、改打招呼语、加人工确认门禁），每次改动自动保存版本快照（`v1 → v2 → ...`）、执行安全体检并重跑回归验证，支持多步连续撤销回滚，并自动拦截“删除最后验收校验或强制门禁”的危险修改。
- **微信 `#建流程` / `#改流程` 多轮遥控**：在已标记为「🧪 测试好友」的微信小号或「文件传输助手」中直接发 `#建流程` / `#改流程` 即可多轮续接建流程、修改现有流程或 `#改流程 撤销` 回退，普通外部客户发 `#` 严格隔离拦截。

## v3.0.0 零配置客户自助闭环基础能力

- **4 步开箱初始化 & 内置聊天归档解析（零 FDE / 无需额外 WeChatBridge）**：首次打开即引导配置身份、业务简介、L1 `general_sales` 通用私域销售包与测试小号；内置微信活跃高价值会话自动发现（自动过滤公众号/系统号/测试号）以及本地 `.zip` / `*聊天记录*.txt` 导出包解析与跨会话号主推断，无需额外安装第三方插件。
- **离线词汇挖掘、PII 自动脱敏与高风险草稿门禁**：导入前自动脱敏手机号、身份证号、邮箱、微信号与详细地址；通过多气泡归并、离线 n-gram/PMI 词汇挖掘与 L1×L2 话术合成提炼专属知识库，凡命中价格、折扣、退款、交付承诺的条目强制进入 `draft` 审阅发布门禁。
- **测试小号沙盒 + `#` 指令当场纠偏 + 1–5★ 双轨评分闭环**：支持测试好友三层隔离与模拟客户压测窗口；仅授权管理员/测试好友可执行 `#` / `＃` 纠偏指令（防外泄防注入），结合 5 维自动体检（`autoScore`）、1–5★ 人工权重闭环（`[0.35, 1.45]`）、金牌范例库与「一键回归验证」持续提分。
- **干净客户构建 (`WECHAT_CLEAN_CUSTOMER_BUILD=1`)**：通过 `customer_build.marker` 彻底剥离开发态种子数据，外置运行态数据至 `~/Library/Application Support/WeChatBot/`，覆盖安装保留用户配置与历史资产，延续本地叶证书签名以保持 macOS TCC 权限不掉线。

---

## 为什么需要独立的 Window-Scoped App-Use？

| 对比维度 | Browser-Use | 传统 Computer-Use | **App-Use Studio (`v3.2.0`)** |
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
- **自动化测试套件**：全库共 **296 项自动化测试**（涵盖 **v3.2.0 对话建流程与一句话改流程专项测试**与 **31 项 v3.0 零配置自训练与督导闭环专项测试**），覆盖多渠道跨软件泛化、Shadow 预览卡护栏、多步连续撤销、微信 `#建流程`/`#改流程` 遥控、租户隔离、PII 脱敏、离线词矿、风险门禁、`#` 指令安全闭环、1–5★ 双轨评分、元算法、无焦点 AX 与 DSH 编排。
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
- `wechat_control/{tenant_profile,corpus_discovery,playbook_trainer,supervisor_eval}.py`：v3.0.0 零 FDE 租户模式、语料自动发现、PII 脱敏、离线词汇挖掘、风险门禁、`#` 指令沙盒与 1–5★ 双轨评分闭环
- `config_templates/sales_packs/general_sales.json`：L1 通用私域与顾问式销售 9 阶段策略包
- `docs/user-guide.html` & `docs/USER_GUIDE.md`：零工程黑话网页版/Markdown 用户操作手册（[在线阅读](https://harzva.github.io/app-use/user-guide.html)）
- `docs/DEVELOPER_GUIDE.md`：v3 开发者架构、SQLite Schema 与 HTTP/MCP/CLI 接口文档
- `docs/index.html`：项目 GitHub Pages 文档页（[https://harzva.github.io/app-use/](https://harzva.github.io/app-use/)）
- `tests/`：296 项自动化单元测试套件（含 `test_workflow_chat_v32.py` 对话建流程/改流程测试及 `test_38_*` / `test_39_*` / `test_40_*` 专项测试）
