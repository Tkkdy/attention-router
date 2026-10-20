# 可选 Agent 与模型集成

## 不依赖 Bot 的最小接入（Preview）

Hub、Console、路由规则、ESP32 显示和 Web ACK 不需要 GrokBot、DeepSeek 或任何模型订阅。任务/事件可由用户或自有脚本产生，路由本身不调用 LLM。

启动时使用 `python hub/run_preview.py --api-token-prompt`，在私密提示中输入自己生成且至少 32 字符的随机凭据；同一 token 由自己的 Agent 安全持有，不写入 URL、Git 或命令行。重启时输入相同 token 可供既有 Agent 继续使用；普通浏览器仍用本机 Cookie。

建议始终用 loopback 调用。若额外绑定 LAN 网卡，正确 Bearer 在 LAN 也有效；它不受本机浏览器会话限制，明文 LAN 会泄露凭据，详见 NETWORK。

HTTP 请求头为 `Authorization: Bearer <自己的凭据>`，先 GET `/api/overview` 读取 `todos.revision` 和 `workspace.revision`（不存在时为 0）：

```json
POST /api/mcp/todos/upsert
{"request_id":"my-agent-001","expected_revision":0,"title":"Review a pull request"}
```

```json
POST /api/mcp/workspace/current-item
{"request_id":"my-agent-002","expected_revision":0,"title":"Review a pull request","project":"My project"}
```

以上两次独立写入会创建不同身份，即使标题相同。若 Current 应引用已有 Todo，请使用 `/api/workspace/sync` 的 current_item 并传入 upsert 返回的真实 Todo ID；完整示例见 local_demo.py。

示例 revision=0 只适用于尚未写入的文档，必须以读取结果为准。409 表示冲突，应重读并重新判断，不能盲目覆盖；网络重试保留同一个 request_id 与相同参数，新意图使用新 ID。

用户已授权的提醒使用 POST `/api/events`：

```json
{"id":"my-reminder-001","revision":1,"kind":"reminder","authorization":"user_reminder","title":"Review request","message":"Please review the result","provenance":"USER"}
```

未得到用户提醒授权时不能标 `user_reminder`。ACK 使用 `/api/events/{id}/ack`，请求为 `{"revision":1,"command_id":"ack-001"}`；它只确认事件。不要伪装任务完成。`examples/local_demo.py` 提供同源本机示例。

## DeepSeekBot（Experimental）

本包包含自有 Gateway 客户端、工具注册和 prompt 合约；第三方 patch 的原始 Apache-2.0 LICENSE/NOTICE 单独保留。完整 DS Bot/Harness、node_modules、网页构建产物和私人会话均未打包。

外部项目：[DS Bot](https://github.com/FeiZhuLulu/DeepSeek-Bot)、[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。本机核对的 DS Bot 基线为 `d56c5850847b828dbc93e232fefcb81a94f80c89`，Harness 为 `5badb15009ae1756c3afe0ae0cef1faafc290ccc`；DS Bot 工作树还带有本地模块接线修改，不能当作官方原版能力。

尚缺闭环：干净 checkout → 安装 Harness/DS Bot → 应用适配器/补丁 → 构建两层网页 → 创建自己的 Bot → 配置独立 Gateway token/allowlist → 连接新 Hub → 实际验收。当前没有可承诺成功的独立一键安装路径，不提供私人启动器充数。

保留的 `hub/run_butler_shadow.py` 可运行隔离 Gateway；`--deepseek` 通过语义解析器使用官方在线 API。调用者需自行提供 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`、`DEEPSEEK_BASE_URL`（默认 https://api.deepseek.com）以及不同来源的 `BUTLER_DEEPSEEK_TOKEN` / `BUTLER_GROK_TOKEN`。不要把密钥写入源码；这些变量由调用者在自己的会话/秘密管理工具中提供。本次没有读取或更改你的环境变量。

语义解析器只接受官方 DeepSeek HTTPS 主机，模型名不硬编码为免费模型。在线 API 通常按服务商规则计费，查看 [官方定价](https://api-docs.deepseek.com/quick_start/pricing)，本候选未发起真实调用。DeepSeek 名称、外部开源客户端或本地测试不表示实际运行了开源权重。当前未实现并验收 Ollama/vLLM/本地模型路径，不能只改 URL 宣称支持。

Gateway 默认使用本目录隔离 `.build` 数据；其独立 Todo Core 与基础 Hub Todo 文档是不同数据域，不能假设启动 Gateway 就会自动同步设备。桥接/投影功能仍为实验态，不进行生产 Todo 迁移。普通用户优先使用上面的 Hub HTTP API。

## GrokBot / MCP / OAuth（Experimental）

不要求用户使用作者的 GrokBot。需要自己的 Bot 客户端/账号及平台允许的 MCP 功能。基础本地 MCP 适配器 `hub/mcp_readonly.py` 的名字是历史命名，实际还包含受策略控制的 Todo/current-item 写入；不能当作纯只读服务。

本地 MCP 需要额外安装 `hub/requirements_mcp.txt`（完整实验依赖快照，非最小启动必需）。以下为从源码审阅得到的实验安装路径，本次未安装该扩展环境或验收客户端；只在自己的全新候选目录操作：

```powershell
py -3.13 -m venv .build/mcp-python
.\.build\mcp-python\Scripts\python.exe -m pip install -r hub/requirements_mcp.txt
powershell -NoProfile -File .\setup_mcp_auth.ps1
powershell -NoProfile -File .\remote_mcp_access.ps1 read-only
powershell -NoProfile -File .\start_mcp.ps1 -HubUrl http://127.0.0.1:8765 -Port 18766
```

DPAPI 凭据和访问策略均留在本目录 `.build/mcp-auth`，只能由创建它的 Windows 用户使用。客户端凭据由所有者通过 `setup_mcp_auth.ps1 -ShowForManualEntry` 的本地界面手工填入安全字段，不能贴到聊天或 URL。默认不开写权限；需要时由本人使用 `remote_mcp_access.ps1 arm-write -Minutes 30`，结束后用 `off` 关闭。这里的 Bearer 适配器不是公网 OAuth 服务；不要把 18766 或 8765 直接接公网。

公网 OAuth 还需补齐独立服务部署、自己的 HTTPS/Tunnel origin、回调注册与客户端验收；包内 OAuth 库并不组成已验收的远程安装器。未准备好这些步骤前，只使用本地 HTTP 集成，绝不将 Hub 端口直接公开。

## Tibo 与 Codex

Tibo 为可关闭的社区 Reset/预测数据页，自动注意力策略尚未配置，不承诺未来重置。Codex 用量采集需要可用的本机 Codex app-server；本次启动入口默认不启用。前台应用检测只表示工作上下文信号，不能证明 Agent 在执行、完成或等待用户，也不能自动识别项目与任务。
