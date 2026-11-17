# `@dsh-market/wechat-ecosystem` — 微信全生态独立软件 + 原生 DSH 插件 + Bot Studio 集成平台 (`v2.0.0`)

独立可运行、也可无缝作为原生 **DSH 插件 (`openbot.dsh-plugin/1`)** 接入 **Bot Studio (`dsh2codex`)** 的 macOS 微信全生态私域、知识库、文章/视频号归档与数字分身工作台（`v2.0.0`），内置 **Bot Studio Fail-Closed 授权门禁**与防抢鼠标物理停避护栏。

---

## 三种独立 / 集成使用形态

### 1. 独立桌面软件（Standalone macOS App + Web Console + CLI）
无需依赖 Bot Studio 宿主即可独立运行：
- **原生 macOS 应用**：`dist/WeChat Ecosystem Studio.app`（`native/wechat_studio_app.swift` 编译，Cocoa + WKWebView 原生外壳，自动拉起本地 `18788` 服务）：
  ```bash
  ./bin/build-standalone-app
  open "dist/WeChat Ecosystem Studio.app"
  ./bin/wechat-bot launch-app --verify-headless
  ```
- **独立网页控制端（Web Console）**：`./bin/wechat-bot console --host 127.0.0.1 --port 18788` -> `http://127.0.0.1:18788/`
- **统一 CLI 入口**：`./bin/wechat-bot <command>`（`doctor` / `inspect-live` / `export-article` / `export-account` / `export-channels` / `soul-profile` / `benchmark` / `botstudio-bridge`）

### 2. 原生 DSH 插件（`openbot.dsh-plugin/1`）
符合 DSH 市场与 Agent Plugin Catalog 规范：
- `dsh.plugin.json`（`schema: "openbot.dsh-plugin/1"`，`id: "dsh-plugin-wechat-ecosystem"`，`packageName: "@dsh-market/wechat-ecosystem"`，8 个标准化 Tools、3 个 Workbench Panels、1 个 Vertical Task）
- `market/dsh-agent-plugin-catalog-entry.json`（`schema: "openbot.agent-plugin-catalog/1"`）

### 3. Bot Studio (`dsh2codex`) 工作台集成（4-Tab 页面 + MCP + HTTP）
通过 `/Volumes/SanDisk/OpenBot/dsh2codex-workbench/src` 一键将 `dsh.plugin.json` 编译为 Bot Studio 可加载资产：
```bash
./bin/wechat-bot botstudio-bridge --compile-dsh --export-bundle
```
生成资产清单：
- `market/wechat-rpa-control.preset.json`（`openbot.codex-workbench-preset/1`）
- `market/wechat-rpa-control.plugin.json`（`openbot.codex-workbench-plugin/1`，含 `overview` / `console` / `workflows` / `page_spec` 4-Tab 页面）
- `dist/botstudio-pages/wechat-ecosystem/{index.html,agent.md,agent.json,plugin.json,llms.txt}`（同时通过 HTTP `/botstudio-page/` 提供访问）
- `logs/botstudio_integration_bundle.json`（含 `mcpServers` stdio 配置、DSH 清单与授权状态）

---

## 核心能力矩阵

1. **安全可控微信 RPA (`wx4py-macos` + `wechat-mac-rpa` + `WeChatBridge`)**：AXUIElement 控件定位、macOS `Vision` (`zh-Hans`) 2x OCR、**3x 长度读回熔断**、120 秒防重锁、群白名单、拟人抖动与 JSONL 审计。
2. **标准 UI 协议 + 物理防抢鼠标 (`HumanActivityGuard` + `WeChatUIProtocolNavigator`)**：标准化 `wechat.ui-protocol/1` 视图/控件 Schema；检测到用户键鼠活动立即停避冷却（30s~90s），且遇到 `com.apple.SecurityAgent` 等系统鉴权弹窗绝对只读停机。
3. **内容导出（单篇 + 服务号/公众号批量 + 视频号视频）**：
   - `export-article`：导出微信文章为 Markdown 并本地保存全部图片素材。
   - `export-account`：枚举并批量归档公众号/服务号历史文章（限流防抖 + SHA 去重 + SSRF 域名白名单）。
   - `export-channels`：抓取/导出微信视频号列表与媒体。
4. **本我性格 & 好友记忆 (`SoulMemoryProfiler`)**：基于聊天记录与 `WeChatBridge` 归档生成号主本我性格（`ENTJ`）与好友多维画像、MBTI 推定及长期事实/偏好/共同记忆存储。
5. **多供应商模型枢纽 (`MagpieProviderHub`) & FTS5 知识库**：支持 Magpie Hub、OpenAI 兼容供应商接入与联系人专属模型/人格绑定。
6. **MCP + HTTP 开放接口 & Kimi 基准评测**：22+ 单元测试与 9 模块 100 分自动化评测（`./bin/wechat-bot benchmark --run --with-tests`）。

---

## 插件授权与常用命令

```bash
export PYTHONPATH=/Volumes/SanDisk/OpenBot/wechat-rpa-control-20261115

# 1. 环境、权限与授权自检
./bin/wechat-bot doctor
./bin/wechat-bot auth-grant          # 开启 Bot Studio Fail-Closed 授权（--read-only 只读；auth-revoke 撤权）

# 2. 启动独立网页控制端 / 原生 macOS 软件 / MCP Server
./bin/wechat-bot console --host 127.0.0.1 --port 18788
./bin/wechat-bot serve-mcp
./bin/wechat-bot launch-app --verify-headless

# 3. 编译 DSH -> Bot Studio 集成包并跑全量 Benchmark
./bin/wechat-bot botstudio-bridge --compile-dsh --export-bundle
./bin/wechat-bot benchmark --run --with-tests
```

---

## 仓库目录结构

- `dsh.plugin.json` / `market/dsh-agent-plugin-catalog-entry.json`：原生 DSH 插件与目录清单
- `market/wechat-rpa-control.preset.json` / `market/wechat-rpa-control.plugin.json`：`dsh2codex` 4-Tab 工作台构建产物
- `native/wechat_studio_app.swift` -> `bin/wechat-studio-app` / `dist/WeChat Ecosystem Studio.app`：独立原生 macOS 软件
- `native/wechat_vision_ax.swift` -> `bin/wechat-vision-ax`：Apple AX + Vision OCR + HID 空闲探测原生驱动
- `wechat_control/botstudio_bridge.py`：独立形态、DSH 清单校验与 `dsh2codex` 编译器桥接
- `wechat_control/{engine,mcp_server,cli,web_console,auth_gate}.py`：核心控制引擎、MCP/HTTP 服务与 Web 控制端
- `wechat_control/{article_exporter,soul_memory_profiler,ui_schema,human_activity_guard,magpie_provider_hub,benchmark_suite}.py`：文章/视频号导出、Soul 记忆画像、UI 协议、防抢鼠标、Magpie 枢纽与基准测试
- `tests/test_wechat_control.py`：全链路单元测试套件（23 项）
