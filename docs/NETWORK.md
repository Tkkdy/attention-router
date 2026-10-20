# 网络部署边界

| 模式 | 连接 | 鉴权与范围 |
| --- | --- | --- |
| 完全本机 | 浏览器 → 127.0.0.1:8765 | 首次打开首页建立 HttpOnly / SameSite Cookie；写请求需同源 Origin 和 X-Hub-Action |
| 同一局域网 | ESP32 → 指定私有网卡:8765 | GET /scene 与 /health 无鉴权；仅适合可信 LAN，Scene 含任务信息 |
| 本地 Agent | Agent → loopback Hub API | 启动时通过 `--api-token-prompt` 输入自己的 32+ 字符令牌；不配置则没有 Bearer 入口 |
| LAN + 有效 Bearer | LAN → 已绑定网卡的管理 API | 正确令牌可读写 API，也可读取 Console HTML；不是匿名绕过。令牌不强制限于本机，明文 HTTP 不保护它 |
| LAN + 无效/无令牌 | LAN → Console / 管理 API | 401；不能获取本机浏览器会话。GET /scene、/health 仍匿名可读 |
| 公网远程 | Bot → HTTPS → Tunnel → 专用 OAuth/MCP → 本地 Gateway | 高级实验路径，本候选不提供可直接复用的运行部署；不可把 Hub 当 Tunnel 目标 |

默认只绑定 127.0.0.1。添加 device_host 后只额外绑定指定 RFC1918 地址，不监听 0.0.0.0。
Uvicorn 入口禁用代理头信任，避免简单伪造转发客户端地址；这不使管理接口适合公网。
本机浏览器的 Cookie 登录仍要求 loopback 客户端与 localhost/127.0.0.1/::1 主机名；写操作须同源。Bearer 请求走独立凭据路径，不套用浏览器同源校验。
LAN 不提供加密和设备身份认证，其他 LAN 客户端也可能读取 Scene；公开访客 Wi-Fi 不符合本地部署假设。

可选部署包含两条独立链：GrokBot → 域名 → Tunnel → 独立鉴权服务 → Gateway / Todo Core；ESP32 → 局域网 Hub。它们不是 ESP32 直接访问 Bot，也不是必须购买域名才能用设备。

远程接入前必须具备：自己的域名/HTTPS 和 Bot 账号、专用 OAuth Authorization Code + PKCE 服务、正确的 resource/audience/scope 校验、MCP 工具白名单、独立 Gateway 凭据、来源隔离、撤销/审计机制。只有专用鉴权适配器可以成为 Tunnel origin。不能转发 Hub Console、Todo 数据库、旧 V0 管理 API、调试端口或整个主机。OAuth callback 成功不能证明客户端工具调用成功。

本包保留局部 MCP/OAuth 库供研究，不包含私人 runtime/controller、自动启动任务、Tunnel 凭据或生产 Todo 迁移脚本。完整远程安装与真实 GrokBot 验收不在 Preview 支持承诺中，不能用源码存在代替部署成功。

默认不启用模型调用。Tibo 需要用户在 Console 主动开启，访问 codex-resets.com / nextreset.ai；数据来自社区。Radar 默认空地址，仅在用户自行配置进程 ATTENTION_RADAR_URL 后才访问该源，日期语义仍使用 UTC+8。固件天气、NTP、互联网探测、Radar 均在模板中留空；需要时自行填写自己的服务，可能产生外网请求和位置披露。
