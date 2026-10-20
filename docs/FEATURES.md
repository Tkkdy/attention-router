# 功能、边界与 Roadmap / Features, boundaries, and roadmap

[中文首页](../README.md) · [English home](../README_EN.md)

本表以候选源码为准，`Implemented` 不代表最终硬件验收已经完成。`Experimental` 表示已有可调用代码或适配器，但存在独立环境、账号、配置或端到端验收缺口。`Planned` 尚未实现。基础 Hub 不使用 LLM，也不要求任何 Bot/模型订阅。

This matrix describes the candidate code. `Implemented` does not mean final hardware acceptance is complete. `Experimental` denotes existing callable code or adapters with deployment, account, configuration, or acceptance limitations. `Planned` means not implemented. The base Hub uses no LLM and requires no Bot/model subscription.

## 基础能力 / Core capabilities

| 功能 / Feature | 状态 / Status | 实际行为与边界 / Actual behavior and limits |
| --- | --- | --- |
| Home / Workspace / Interrupt | Implemented | 空闲、工作及提醒页；Router 与可选详情页生命周期选择最终页面。Home, work, and alert views; routing and optional detail lifecycles choose the final page. |
| Today / Todo / Current / Next | Implemented | Home 取存储顺序中的前 3 个 pending；不按今天或 due date 筛选。Next 先按 ID 排除 Current。Home shows the first three pending tasks in stored order, not tasks due today; Next excludes Current by ID. |
| Windows foreground context | Implemented | Windows 前台信号与工作会话阈值、手动覆盖；不探测通用 Agent 生命周期。Windows signals, session thresholds, and overrides; no general Agent lifecycle detection. |
| NOW / QUEUE / DIGEST / DROP | Implemented | 确定性授权/时间/上下文规则；最多一个 NOW，DIGEST 不是 LLM 摘要，DROP 不代表删除任务。Deterministic authorization/time/context rules; at most one NOW; DIGEST is not an LLM summary and DROP does not mean deleting a Todo. |
| Web Console / ACK | Implemented | 查看路由、来源、状态；ACK 确认事件，不能替代 complete Todo。Inspect routes, provenance, and state; ACK acknowledges an event rather than completing its Todo. |
| Authenticated HTTP / LAN Scene | Implemented | 本机 Console 与 Agent API、LAN 匿名 Scene/health；有效 Bearer 可在已绑定 LAN 调管理 API。Local Console/Agent API and anonymous LAN Scene/health; valid Bearer tokens authorize management on a bound LAN listener too. |
| Disconnection / STALE | Implemented, hardware closure pending | 约 90 秒降级、稳定 45 秒恢复；最终精确固件待安全验收，NVS 中文离线恢复有限制。About 90 seconds to fallback and 45 stable seconds to recover; exact final firmware awaits acceptance and offline Chinese titles have limitations. |
| Partial Chinese title rendering | Implemented, limited | Hub 用合法本机字体生成 Todo/Current 位图；不捆绑字体，不是所有字段 Unicode 化。Hub generates Todo/Current bitmaps using an available licensed host font; fonts are not bundled and not every field supports Unicode. |
| Slow diagnostics / serialized workers | Implemented | 采样/Tibo/Radar 工作线程、取消后排空、有限脱敏慢日志；不保证长事务或过载永不超时。Worker execution, draining on cancellation, bounded redacted slow logs; long transactions or overload can still time out. |

核心源码证据 / Core code: `hub/attention.py`, `hub/context_monitor.py`, `hub/router_api.py`, `hub/slow_diagnostics.py`, `hub/console.html`, `firmware/esp32_dashboard/`。

### Today 和路由的精确语义 / Exact Today and routing semantics

Todo 的 `pending/done/cancelled` 与事件的 `NOW/QUEUE/DIGEST/DROP` 是两类状态，不能混用。Home 的 TODAY 是标题，不是日历筛选器；到期不会自动把任务标完成。Current 是明确写入的事项，标题相同不等于 ID 相同；过期的 Workspace suggestion 不再显示。部分日期显示/来源验证采用 UTC+8。

Todo status (`pending/done/cancelled`) and event route (`NOW/QUEUE/DIGEST/DROP`) are separate. TODAY is a section name, not a calendar filter. Elapsing time never completes a Todo. Current is explicitly supplied; matching titles do not imply matching IDs. Expired workspace suggestions are not displayed. Some date display/provider checks use UTC+8.

| 顺序 / Order | 规则 / Rule |
| --- | --- |
| 1 | 非 active 或已过期事件 → DROP。Inactive or expired events → DROP. |
| 2 | starts_at 尚未到 → QUEUE。Future starts_at → QUEUE. |
| 3 | Tibo Reset 没有已授权隔离测试策略 → QUEUE。Tibo reset without its isolated test authorization → QUEUE. |
| 4 | user_reminder / current_blocker → NOW 候选。Explicit reminder/current-blocker authorization → NOW candidate. |
| 5 | awaited_result 在 CODING/QUIET 时 QUEUE，否则 NOW 候选。Awaited result → QUEUE during CODING/QUIET, otherwise NOW candidate. |
| 6 | 其他 → DIGEST；多个 NOW 候选再择一，其余排队。Otherwise → DIGEST; selection keeps one NOW and queues other candidates. |

来源 / Sources: `Router.decide()`, `AttentionService.scene()` and event reevaluation in `hub/attention.py`。这套规则不自动读取 ChatGPT 网页是否生成结束。These rules do not observe ChatGPT web completion.

## 实验能力完整矩阵 / Complete experimental matrix

| 功能 / Feature | 已有可调用内容 / Existing callable capability | 启用、依赖与费用 / Enablement, dependencies, costs | 未完成与隐私边界 / Limits and privacy |
| --- | --- | --- | --- |
| GrokBot integration | Gateway 接受 source=grok；读取 Todo/Current/context、受权写入、建议/事件及确认。Gateway accepts source=grok with reads, authorized writes, suggestions/events, and acknowledgements. | 自有客户端/账号、独立 Gateway 凭据及权限，远程模式另需 HTTPS/OAuth。账号、模型、域名/托管可能收费。Caller-owned client/account, separate Gateway credentials and permissions; remote use needs HTTPS/OAuth. Account/model/hosting costs may apply. | 不是发行包内置 Bot；没有干净环境完整安装闭环，不复用私人控制器。Not a bundled Bot; no accepted clean end-to-end installer or private controller reuse. |
| DeepSeekBot / DS Bot adapter | `integrations/deepseek_bot/` 含 Gateway client、工具注册、UX 合约与 fork 接线补丁。Gateway client, tool registration, UX contracts, and fork wiring patch. | 外部 DS Bot/Harness、其依赖与网页构建、自有 Bot 与 token/allowlist；模型费用由所选服务决定。External DS Bot/Harness, their builds/dependencies, caller Bot and credentials; provider costs apply. | 上游全项目及运行环境未打包，非一键安装；patch 仍为 Apache-2.0。Upstream applications/runtime are not bundled; not one-click; patch retains Apache-2.0. |
| Local MCP adapter | `get_hub_state`, `upsert_todo`, `set_current_item`；文件名 `mcp_readonly.py` 不代表只读。Read Hub state and policy-controlled Todo/Current writes despite the historical filename. | `hub/requirements_mcp.txt`、本地鉴权脚本、Windows DPAPI、访问模式/限时写授权；自身不调用 LLM，客户端模型可能收费。Extra MCP dependencies, local auth, Windows DPAPI, read/write policy; adapter makes no LLM call, client may incur model costs. | 不具备日程/reminder创建能力，不直接用作公网 OAuth；不把第三方客户端连接成功视为已验收。No Todo due-time/reminder scheduling through these tools; not a public OAuth server; client acceptance remains separate. |
| OAuth / remote MCP | `experiments/oauth_spike/` 内 Authorization Code + PKCE、resource/scope 等协议实现供适配。Authorization Code + PKCE and resource/scope protocol support for integration. | 自己部署的 HTTPS 域名、Tunnel 与专用鉴权服务、回调注册及客户端能力；运营费用自理。Own HTTPS/domain/Tunnel, dedicated auth deployment, callback registration and compatible client; operational costs are separate. | 包内库不是完整部署器；不得直接 Tunnel Hub、Gateway 或数据库，OAuth callback 成功不等于工具调用闭环。Libraries are not a deployment; never expose Hub/Gateway/database directly, and callback success is not tool acceptance. |
| Todo Core / shadow Gateway | `run_butler_shadow.py`、`/v1/butler/commands`；增改/完成/删除/排序、Current、澄清、建议，修订与幂等约束。Isolated Todo CRUD/completion/reordering, Current, clarification, suggestions, revisions and idempotency. | 隔离 SQLite、来源不同的自有 token；默认解析器关闭；结构化调用不需要模型。Separate SQLite and source-specific credentials; resolver off by default; structured calls need no model. | 与基础 Hub Todo 是不同数据域；不自动迁移/合并真实任务。Separate from base Hub Todos; no automatic production migration or merge. |
| Hub bridge / projection / reminder delivery | `butler_bridge.py`, `butler_todo_projection.py`, `reminder_delivery.py` 将明确授权的隔离事项/提醒投影，查询/确认事件。Explicit isolated task/event projection, reminder delivery and event acknowledgement. | 显式启用隔离 Hub bridge 与来源权限；remind_at 与 due_at 分开。Explicit isolated bridge and source permissions; remind_at is separate from due_at. | 不证明生产 Todo 迁移成功，不提供设备显示完成回执；没有桥接时不应声称设备同步。No production-migration or display-complete proof; no automatic device sync without a bridge. |
| Natural-language Resolver | `resolve_intent` 将原始输入+业务快照解析成受校验的 execute/clarify/noop；拒绝猜测提醒时间。Validated execute/clarify/noop from original input and business state; no invented reminder time. | `--deepseek` 和 DEEPSEEK_API_KEY/MODEL/BASE_URL；仅接受官方 HTTPS DeepSeek 主机，真实 API 可能计费。Explicit opt-in with caller configuration; official DeepSeek HTTPS endpoint only; online calls may be billed. | 用户消息、任务快照/待澄清信息会发送给服务商；不是离线本地模型，不支持只改 URL 切 Ollama/vLLM。Relevant user/business content leaves the machine; not local inference or an arbitrary compatible endpoint. |
| Codex quota collector | `QuotaCollector` 读取 app-server `account/rateLimits/read`，保留时间窗/来源/新鲜度；不发起模型回合或兑换 reset。Reads quota snapshots with provenance/freshness; no model turn or reset redemption. | 调用 `create_router_app(..., codex_executable=...)` 的集成入口，合法绝对路径且已登录本机 Codex；`run_preview.py` 不启用，配置文件不接受该字段。Requires an explicitly supplied authenticated local executable; not enabled or configurable in the basic launcher. | 账号权限/套餐由服务商决定；额度不是 Agent 忙闲或任务完成信号，也非对全部模型可用性的保证。Account access is provider-controlled; quota is not task activity/completion or universal model availability. |
| Quota display policy | 手动套餐与 5h 显示覆盖、7d/5h 快照可见策略。Manual plan/5h display override and snapshot presentation. | Console preferences；无额度采样时仍为 UNKNOWN，手动套餐不改变真实账户。Console preferences; unknown stays unknown without a sample, and a manual plan never changes the account. | 显示设置不是额度赠送、购买或准确预测。Presentation is not a purchase, reset, or guaranteed prediction. |
| Tibo Reset / forecast / detail | 社区状态与可选预测、Console 控制、详情页及隔离注意力测试动作。Community status/forecast, Console controls, detail page and isolated attention-test actions. | 默认 enabled=false、forecast_enabled=false；启用后约 300 秒轮询 codex-resets.com / nextreset.ai；可用性及条款由第三方决定。Off by default; optional external polling about every 300 seconds; third-party availability/terms apply. | 非官方权益保证；自动策略未配置，不能承诺重置或默认打断；没有凭据不代表永久免费。No entitlement/reset guarantee or default automatic interrupt; lack of a key is not a perpetual free-use promise. |
| Hub Radar | 按配置 URL 取 Radar 状态并写入 Hub；日期新鲜度使用 UTC+8。Fetches configured Radar state into Hub with UTC+8 date freshness. | 用户显式配置进程 ATTENTION_RADAR_URL；基础为空，无外部采集来源；来源服务费用/认证由用户安排。Explicit process configuration; empty by default; provider cost/auth is separate. | 是状态适配器，不是本包实现完整 AI 新闻生产；独立于设备 Internet Probe。Status adapter, not a bundled AI-news pipeline; independent of device Internet Probe. |
| Device Radar | 固件原生 Radar 读取与 Standalone 展示。Native firmware Radar acquisition/display in Standalone. | 配置 Radar URL、有效日期、成功 Internet Probe，仅 Standalone 获取；外部服务自备。Configured URL, valid date, successful Internet Probe; fetched only in Standalone. | LAN Hub 可达不满足外网条件；外部状态可能 stale/unknown。LAN Hub access is not the Internet prerequisite; external data may be stale/unknown. |
| Weather | 固件 Open-Meteo HTTPS 适配器。Firmware Open-Meteo HTTPS adapter. | 经纬度、有效日期、Internet Probe 成功；Standalone/Hub Home 获取；调用会向服务商披露位置，使用条款需自行核对。Coordinates, valid date, successful probe; Standalone/Hub Home; location leaves the device, provider terms apply. | 不承诺所有商业场景可无偿使用第三方服务；不因“无API key”推断收费政策。No blanket free-commercial-service promise from a keyless API. |
| NTP / Internet Probe | 显式地址的连通性探测及时间同步门槛。Explicit reachability probe and time-sync prerequisites. | Probe URL、预期状态码/Location；NTP另需时区与两个服务器。Probe URL/status/Location; NTP additionally needs timezone and two servers. | 空 Probe URL → Internet UNKNOWN，不启动新同步/天气/Radar获取；成功也不保证 DNS/时间/其他来源成功。Empty probe leaves Internet UNKNOWN and prevents new acquisition; probe success does not guarantee other providers. |

所有实验项均需调用者明确启用或配置；并非只复制配置就能承诺端到端成功。第三方账户、托管和服务的价格/条款会变化，本表不引用固定价格或免费额度。安装边界见 [AGENTS](AGENTS.md)、[WINDOWS](WINDOWS.md) 和 [NETWORK](NETWORK.md)。

All experimental paths require explicit caller configuration or integration; configuration alone is not an end-to-end guarantee. Provider/account/hosting prices and terms may change; this document promises no fixed price or free allowance. See the linked setup and network guides; some are currently Chinese.

## 有限 Roadmap / Bounded roadmap

以下全部 **Planned**，没有发布日期；本轮不实现。All items below are **Planned**, without promised dates or implementation in this release preparation.

- ChatGPT 网页回答结束提醒 / ChatGPT web-response completion alerts.
- Codex 工作完成、待批准、待验收提醒 / Codex completion, approval-needed and acceptance-needed alerts.
- Agent Inbox 待验收看板 / Agent Inbox for work awaiting acceptance.
- 更广泛的个人上下文来源与 Personal Agent 注意力管家 / Broader personal context and a Personal Agent attention assistant.
- Seeed XIAO ESP32S3 等更多硬件适配 / Additional hardware including Seeed XIAO ESP32S3; not launch compatibility.

NVS 中文离线标题根因调查是后续已知问题，不等于上述新功能已实现，也不要求无限扩大首发门槛。所有者批准先发布源码，最终候选有限核心硬件验收仍待补；不能以延期 NVS 调查为由宣称硬件已通过。

Offline Chinese-title diagnosis remains a follow-up known issue. It is neither a delivered new feature nor an unlimited launch gate. The owner approved source publication while safe, bounded core hardware acceptance of the exact final candidate remains outstanding.
