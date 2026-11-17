# 微信工作台：其他智能体如何记录进度

独立预览包附带只读 stdio MCP。它只提供 `wechat_workbench_progress`，返回候选模式、待办状态计数、采纳/暂缓次数、是否允许发送。它不返回联系人、来信、回复正文、配置或凭据，不提供写入或发送工具。

注册时，命令为 `/usr/bin/python3`，参数为 `-B -m wechat_control.recommendation_preview progress-mcp <预览资料目录>`。给进程设置 `PYTHONPATH=<独立预览 .app 的 Contents/Resources>`。该 MCP 只作为手动接入选项交付，不改现有 Bot Studio 或 Codex 的 MCP 注册。

- 从独立预览 App 正常打开时：资料目录为 `~/Library/Application Support/WeChat Workbench Recommendation Preview`，在客户端配置中请展开为绝对路径。
- 重放验证记录时：使用相应闪迪构建目录中的 `native/ui-data`。首次启动前返回 `available:false`，不会创建资料库。

报告可按 `mode`、`tasksByStatus`、`draftsAdopted`、`deferred`、`sendEnabled` 记录。运行计数不代表 OpenSpec 发布进度；发布任务以变更目录下的 `tasks.md` 和对应验收证据为准。
