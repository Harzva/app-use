# WeChat Bot — macOS 微信智能客服机器人

[![Release](https://img.shields.io/github/v/release/Harzva/wechat-bot?include_prereleases)](https://github.com/Harzva/wechat-bot/releases)
[![License](https://img.shields.io/badge/license-proprietary-red)]()
[![Platform](https://img.shields.io/badge/platform-macOS%2014%2B%20Apple%20Silicon-black)]()

> 一键托管微信好友，AI 自动回复（知识库 + 历史记忆 + 人设），转人工一键协同。

## ✨ 功能

- 🚀 **一键托管好友**：勾选联系人 → 机器人自动回复他们的消息（45 秒轮询 · 真发送 · 重启自恢复）
- 🧠 **智能回复**：FTS5 知识库检索 + Soul 记忆 + 人设 + LLM（Magpie 网关 / DeepSeek / GLM）
- 🤚 **转人工协同**：客户发「转人工」自动停答接管；接管期间草稿自动进待办审阅台，一键恢复 AI
- 🔗 **多媒体理解**：链接自动深读网页 / 图片 2x Vision OCR / 视频抓帧摘要——回复引用真实内容
- 🛡️ **防封频控**：每小时/每日限额 · 人工操作自动让路 · 贝塞尔拟人鼠标轨迹 · 3x 读回熔断
- 📥 **历史导入**：微信聊天记录导出 zip/txt 一键导入，历史注入回复上下文
- 🖥 **微信式气泡流 UI**：实时刷新 · 谁发的（👤人工/🤖托管）一目了然 · OCR 低置信标注

## 🚀 5 分钟上手

### 1. 构建（需 Xcode Command Line Tools + Python 3.10+）

```bash
git clone https://github.com/Harzva/wechat-bot.git
cd wechat-bot
./bin/build-standalone-app     # 编译 Swift + 打包 + 自动安装到 ~/Applications
open -a "WeChat Bot"
```

### 2. 授权（首次启动自动弹窗引导）

启动后按弹窗指引，在 **系统设置 → 隐私与安全性** 依次授权：
- 辅助功能（读取微信窗口）
- 系统事件控制（模拟键盘发送）
- 屏幕录制（Vision OCR 识别消息）

> 提示：若列表里有旧条目，先「−」删除再重新添加（旧授权对新版本无效）。授权后回控制台点「🔄 重新检查」。

### 3. 配置 LLM（可选，不配则用知识库模板回复）

编辑 `config/model_providers.json`，填入你的模型网关：

```json
{
  "gatewayUrl": "http://127.0.0.1:3425",
  "activeModelId": "auto/deepseek-v4.1-flash",
  "llmReplyEnabled": true
}
```

### 4. 一键托管

控制台首页 → 「选择托管好友」→ 勾选 → **🚀 一键托管**
之后这些好友发消息，AI 自动回复；发「转人工」随时切换人工。

## 📖 架构

```
微信窗口（AX + Vision OCR 轮询）
  → 消息识别（文本/链接深读/图片OCR/视频抓帧）
  → 生成回复（知识库 + Soul记忆 + 人设 + LLM）
  → AX 模拟键盘发送（3x 读回校验 · 120s防重 · 拟人延迟）
```

旧版架构文档见 [README-arch-old.md](README-arch-old.md)。

## 📄 License

本项目源码仅供学习交流。使用请遵守微信使用规范，控制操作频率，勿用于骚扰行为。
