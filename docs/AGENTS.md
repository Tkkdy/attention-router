# 可选 Agent 与模型集成

<a id="agent-http-quickstart"></a>
## 基础 Agent HTTP 上手 / Basic Agent HTTP quickstart

使用全新解压/检出目录，按 [Windows 安装](WINDOWS.md) 安装基础锁定依赖。无需设备、Bot、OAuth、Tunnel 或模型。先确认 8765 未被其他服务使用；示例保留端口 8000，不连接该端口。示例仅接受 `http://127.0.0.1:PORT`（1024–65535，排除 8000），禁用代理且不跟随重定向。

**终端 A（源码根目录）：**

```powershell
.\.venv\Scripts\python.exe hub\run_preview.py --api-token-prompt
```

在不回显的本地提示中输入自己生成的 **32+ 字符 ASCII 无空白随机 Token**。不要将凭据放入命令行、源码、URL、截图或聊天。基础配置默认本机 8765；不要复制私人数据库。Hub 重启后需再次私密输入同一个 Token；该启动入口不保存凭据。

**终端 B（同一目录）：**

```powershell
.\.venv\Scripts\python.exe examples\agent_http_demo.py
```

输入相同 Token。运行示例即授权它在这个全新预览中创建一条**合成提醒**，不是授权 Agent 自行打断真实工作。打开 <http://127.0.0.1:8765/> 查看：

1. 脚本先检查 `/health` 的 `developer-preview` 环境，再使用 Bearer GET `/api/overview` 读取 Todo/Workspace revision。
2. 通过现有 `/api/mcp/todos/upsert` 增加合成 Todo，用同一请求重放确认未重复创建。Todo 保留接口已有的 `MCP` 来源元数据；标题标明 Synthetic，不宣称真实用户任务。
3. 通过 `/api/workspace/sync` 将 Current 关联到返回的**真实 Todo ID**，不使用同名任务冒充关联；不清空其他任务。
4. 通过 `/api/events` 发布 `provenance=SIMULATED`、`authorization=user_reminder` 的合成提醒。Console 可显示 Interrupt 和提醒的 ACK。
5. 在 Console 点 ACK 后回终端 B 按回车，或直接回车由脚本 ACK。脚本重放相同 ACK，再读取状态，确认 Todo 仍是 pending。

任务与提醒会留在该预览的数据目录，便于查看；脚本不自动删除数据。每次重新启动示例会创建新的演示身份。网络错误最多做 3 次原请求尝试，始终保持相同 body、request_id/command_id 和 revision。若仍失败，写入可能已成功，先检查 Console，**不要盲目重新运行**。409 时脚本重读当前修订号、报告冲突并停止，不修改 revision 强行覆盖；人工判断后的新意图才使用新 ID。示例不会更改工作上下文或自动配置任何可选采集源。

原 `examples/local_demo.py` 是无需 Bearer 的同源 Cookie 示例，继续保留；此处仅补充独立 Agent 的 Bearer、重试与冲突路径。Hub 权限模型没有变化。`/health` 和 `/api/overview` 的 `release_version` 表示产品版本；旧 `version` 标识及 Scene 修订号保持原义。

### English entry

Use a fresh source checkout and install the base locked dependencies from the [English installation guide](INSTALL_EN.md). In terminal A run `python hub/run_preview.py --api-token-prompt`; privately enter your own random 32+ character ASCII token without whitespace. In terminal B run `python examples/agent_http_demo.py` and enter the same token without echo. Do not put it in arguments, source, URLs or chat. If changing ports, configure only your own fresh Hub as documented and pass `--url http://127.0.0.1:PORT` to the example; port 8000 is always refused.

Open the Console at <http://127.0.0.1:8765/> to inspect the synthetic Todo, Current linked by its returned ID, and explicitly authorized synthetic reminder. Click ACK there and press Enter in terminal B, or press Enter to let the script ACK. The script verifies ACK replay and that the Todo remains pending. This requires no device, Bot, OAuth, Tunnel, account or paid model. The script disables proxies and redirects and refuses non-preview Hubs before sending a Bearer token. It does not enable optional sources.

Transport failures retry the exact request up to three total attempts. A 409 reads current revisions and stops without overwriting; decide on a new intent before using a new ID. Each new script invocation creates a new demo identity, so inspect the Console after an uncertain failure before rerunning. Data remains in the fresh preview for inspection. The existing Cookie-based `local_demo.py` remains available. The launcher does not store the token; enter it again after restarting your own preview Hub.

Run `python -B examples/test_agent_http_demo.py` for isolated real-HTTP checks with fresh temporary data and an ephemeral loopback listener. The three existing limited CI commands remain documented in [CI.md](CI.md); these checks do not prove hardware or a full Bot integration.

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


<a id="autonomous-interrupt"></a>
## AI 自主 Interrupt / Autonomous Interrupt（Experimental）

实际能力名为 show_interrupt，复用已有 Interrupt 页面。它不创建新 Todo、不自动 ACK，也没有独立 Interact 页面。基础 Agent HTTP 不需要启动这个 Gateway。

1. 按上面的终端 A 命令运行新的预览 Hub（默认 8765），私密输入自己的 Hub Token。
2. 另开终端，明确授予一个 provider 长期打断权限：

~~~powershell
.\.venv\Scripts\python.exe hub\run_interrupt_gateway.py --provider deepseek --allow-autonomous-interrupts
~~~

依次私密输入 Hub Token 和**不同的** 32+ 字符 Gateway Token。监听仅为 127.0.0.1:3102；端口占用时改用 --port，不能停止其他服务。--hub-url 可指定自己的预览 loopback 端口；拒绝 8000、外网、URL 凭据及非 developer-preview Hub。权限只包含 show_interrupt；默认拒绝 Todo、配置和 ACK 等其他写入。未明确授予能力的 Gateway 调用返回 403。

3. 自己的 Agent 持有 Gateway Token，向 POST /v1/butler/commands 发送 Bearer 请求。例如在第三个 PowerShell 终端进行一次合成调用：

~~~powershell
$secret = Read-Host "Provider Gateway token" -AsSecureString
$token = [System.Net.NetworkCredential]::new("", $secret).Password
$body = @{
  source = "deepseek"
  action = "show_interrupt"
  request_id = "synthetic-interrupt-001"
  expected_revision = 0
  arguments = @{title = "Review ready"; message = "Please review the result"}
} | ConvertTo-Json -Depth 4
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:3102/v1/butler/commands -Headers @{Authorization = "Bearer $token"} -ContentType "application/json" -Body $body
Remove-Variable token, secret
~~~

同一 Token 只能代表启动时绑定的 provider；grok 使用 --provider grok 和 source=grok。标题/消息各 1–47 个可打印英文 ASCII 字符。expected_revision 是保留的命令信封字段；此事件操作不修改 Todo 修订。AI 适配器入口为 GrokButlerAdapter 的 show_interrupt 和 DeepSeek 注册工具 butler_show_interrupt；外部 Bot 仍须自行安装并显式限制工具能力。

4. 打开 Hub Console 查看事件、路由与 Scene。来源为 AGENT，detail 标明 Delegated AI 和 provider；authorization=user_reminder 表示用户在启动时授予的长期打断权限，不表示用户逐条编写提醒。模型不能传入或更改授权/来源字段。停止 Gateway（其终端 Ctrl+C）即可撤销后续调用能力；已存在事件在 Console 手动 ACK 或取消，恢复正常页面，Todo 保持不变。

Hub 仍通过现有 Router、队列和优先级决定展示。device_delivery=UNKNOWN，accepted 不表示 ESP32 已显示。request_id 与 source 形成稳定事件身份、revision=1；网络不确定时仅重试完全相同 ID 和内容，改变内容返回 409。已 ACK 的旧 ID 重放不会重新弹出，真正的新意图才使用新 ID。不要无限制造新 ID 重复打断。

English: Start a fresh preview Hub with --api-token-prompt, then run the Gateway command above with an explicit standing owner grant. Enter distinct Hub/provider tokens privately. Only show_interrupt is permitted, bound to the selected provider. Send the JSON envelope above with that Gateway Bearer token; printable ASCII title/message are limited to 47 characters each. AGENT provenance records origin while user_reminder records the owner's standing grant. Inspect and manually ACK/cancel in the Console. Stop the Gateway to revoke further calls; existing events remain until handled. Retry identical IDs/text only; 409 stops, and an acknowledged ID cannot revive an interrupt. This does not install a Bot/chat UI or prove physical display.

## DeepSeekBot（Experimental）

本包包含自有 Gateway 客户端、工具注册和 prompt 合约；第三方 patch 的原始 Apache-2.0 LICENSE/NOTICE 单独保留。完整 DS Bot/Harness、node_modules、网页构建产物和私人会话均未打包。

外部项目：[DS Bot](https://github.com/FeiZhuLulu/DeepSeek-Bot)、[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)。已审阅的 DS Bot 基线为 `d56c5850847b828dbc93e232fefcb81a94f80c89`，Harness 为 `5badb15009ae1756c3afe0ae0cef1faafc290ccc`；适配器仍需要额外模块接线，不能当作官方原版能力。

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

### 可选 Interrupt MCP facade / Optional Interrupt MCP facade

公开源码现包含 experiments/grok_butler/server.py。它复用现有 OAuth 协议库和 Gateway，补齐 show_interrupt 的 MCP 工具发现，不包含域名、Tunnel、私人服务管理或持久化授权数据库。

先在独立环境安装已有可选依赖 hub/requirements_mcp.txt，并用该环境启动以下三个终端。若此前已安装，无需重复安装：

~~~powershell
py -3.13 -m venv .build/mcp-python
.\.build\mcp-python\Scripts\python.exe -m pip install -r hub/requirements_mcp.txt
~~~

1. Hub：用该 Python 运行 hub/run_preview.py --api-token-prompt，私密输入 Hub Token。
2. Gateway：用该 Python 运行 hub/run_interrupt_gateway.py --provider grok --allow-autonomous-interrupts，私密输入 Hub Token 与不同的 Grok Gateway Token。
3. MCP facade：

~~~powershell
.\.build\mcp-python\Scripts\python.exe -B -m experiments.grok_butler.server --scope butler:write --allow-autonomous-interrupts
~~~

私密输入终端 2 的 Grok Gateway Token，再输入自己另行生成的 32+ 字符随机 owner pairing code。默认仅监听 127.0.0.1:3103，客户端入口为 http://127.0.0.1:3103/mcp。OAuth 同意页由本人填写 pairing code，不要将其贴到聊天、源码或命令行。默认 scope=butler:read 且不开放 Interrupt；只有 write scope 与显式能力开关同时满足，show_interrupt 才进入实际工具清单。Gateway 还会独立检查来源和能力。

启动时直接读取 SDK 的实际 tools/list，并校验 show_interrupt 是否符合开关；缺失或意外暴露时拒绝启动。服务器版本为 d3-interrupt-1。启动清单是服务端证据；客户端须在完成 OAuth 后再次调用 tools/list，确认出现 show_interrupt，才能算客户端发现成功。已有连接器可能需要重新连接并重新授权；不要根据源码配置假定客户端已经刷新。

随后调用 show_interrupt，遵循本页前述 ID/重试/ASCII/ACK 约束。此示例 Gateway 只授予 Interrupt，facade scope 中的其他工具仍可能由 Gateway 返回 action_forbidden，不会因此自动获得 Todo 权限。Hub 接受事件不代表 ESP32 实屏完成。停止 facade/Gateway 会撤销后续访问；已有事件在 Console 处理。这里的 OAuth 状态仅在内存中，重启后需要重新授权。

English: Install the existing optional MCP requirements in a separate environment, then run the three terminals above with synthetic/fresh Hub data. Use distinct Hub/Gateway/pairing secrets, entered privately. The facade defaults to read-only; write scope plus the explicit Interrupt flag is required. It verifies the actual SDK tool registry before listening. An OAuth client must independently discover show_interrupt through tools/list; a startup list does not prove client discovery. This sample Gateway grants only Interrupt, so unrelated Todo tools remain denied. OAuth state is ephemeral. External Grok client, public HTTPS/Tunnel deployment and physical display are not accepted by these synthetic tests.

验证命令：python -B ci/run_mcp.py（需使用安装了可选 MCP 依赖的 Python）。7 项隔离测试包含 OAuth/权限、实际工具发现、MCP → Gateway → Hub → Scene、手动 ACK 后重放与 409 冲突。无真实模型或私人服务参与。

公网 OAuth 还需补齐独立服务部署、自己的 HTTPS/Tunnel origin、回调注册与客户端验收；包内 OAuth 库并不组成已验收的远程安装器。未准备好这些步骤前，只使用本地 HTTP 集成，绝不将 Hub 端口直接公开。

## Tibo 与 Codex

Tibo 为可关闭的社区 Reset/预测数据页；自动策略默认关闭，未来 24 小时新鲜概率严格大于默认 70% 后保持到手动关闭，不承诺未来重置。Codex 用量采集需要可用的本机 Codex app-server；本次启动入口默认不启用。前台应用检测只表示工作上下文信号，不能证明 Agent 在执行、完成或等待用户，也不能自动识别项目与任务。
