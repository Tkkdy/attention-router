# Attention Router

**中文** | [English](README_EN.md)

Attention Router 是本地优先的桌面注意力路由器。Windows Hub 保存任务、工作上下文和提醒；Agent 通过鉴权 HTTP 接入；Web Console 提供查看与确认；ESP32 墨水屏定期拉取 Hub 的 Scene。也可只用 Console，无需硬件或模型订阅。路由使用确定性规则，不调用 LLM。

![真实 Console，合成数据](assets/console-demo.png)

截图不代表硬件显示验收。[素材说明](assets/ASSET_INDEX.md)。

## 核心能力

| 能力 | 行为 |
| --- | --- |
| Home / Workspace | 有序 Todo、Current、Next；Windows 工作信号及手动覆盖 |
| Interrupt | 授权事件经 NOW / QUEUE / DIGEST / DROP 路由；手动 ACK 不完成 Todo |
| Console / Agent HTTP | 查看来源、Scene 和新鲜度；带修订冲突及幂等控制的任务与提醒接口 |
| Tibo（实验） | 社区 Reset/预测；60 秒手动详情，默认关闭的阈值自动页 |
| AI 自主 Interrupt（实验） | 用户明确授予长期权限后，AI 决定时机与文案；仍走 Router 和手动 ACK |

Home 的 TODAY 取前 3 个 pending Todo，不是日期筛选。DIGEST 是分类存储，未实现自动摘要。show_interrupt 复用 Interrupt 页面，没有独立的 Interact 页面。

## Windows 快速安装

在全新源码目录打开 PowerShell，安装 Python 3.13 后运行：

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe hub\run_preview.py --api-token-prompt
~~~

私密输入自己生成的 32+ 字符 ASCII 无空白随机 Token。打开 <http://127.0.0.1:8765/>。默认仅监听本机，数据保存在 .build/preview-data/；Ctrl+C 停止，重启需重新输入 Token。仅使用新数据目录。

另开终端运行无需模型的示例 Agent，输入相同 Token：

~~~powershell
.\.venv\Scripts\python.exe examples\agent_http_demo.py
~~~

示例创建合成 Todo、用其真实 ID 设置 Current、发布授权提醒，并验证 ACK 不完成 Todo。重试保留原请求；409 重读后停止，不覆盖冲突。[Agent HTTP 教程](docs/AGENTS.md#agent-http-quickstart) · [Windows 安装与排查](docs/WINDOWS.md)。

## Tibo 与 AI Interrupt

**Tibo：** Console 中开启数据采集和概率预测，保存后开启自动重置页。仅新鲜的未来 **24 小时概率严格大于阈值（默认 70%）** 才首次触发；之后保持到手动关闭，概率下降不自动关闭，旧数据标 STALE。关闭会清除保持状态和手动详情，恢复正常路由页面；活动提醒始终优先。重新开启可再次触发。60 秒手动详情保留；设备需支持 tibo-v1。社区预测不保证重置或个人额度。

**AI：** 独立 Gateway 必须显式指定 --allow-autonomous-interrupts，并私密输入 Hub Token 和不同的来源绑定 Gateway Token。show_interrupt 仅接受 1–47 字符可打印英文 ASCII 标题/消息。事件来源标记为 AGENT，用户授予的是长期打断权限，没有授权不能冒充用户提醒。默认不开放权限。[启用、调用、重试与关闭](docs/AGENTS.md#autonomous-interrupt)。

GrokBot、DeepSeekBot、MCP/OAuth、Todo Core 投影、Codex 额度、Radar 与天气是可选实验集成。DeepSeekBot 已含适配器，完整独立聊天网页安装尚未验收；基础 HTTP 不依赖它。[集成边界](docs/AGENTS.md) · [功能矩阵](docs/FEATURES.md)。通用 Agent 生命周期、执行完成感知、实体 ACK 按钮尚未实现。

## 硬件、安全与限制

- 目标：经典 ESP32（4 MB Flash）+ **GDEY042Z98 4.2 英寸、400×300 黑白红、SSD1683** 及匹配转接板；其他同尺寸屏不可直接替换，ESP32S3 未支持。[接线、电压与构建](docs/HARDWARE.md)。
- 仅发布源码，无预编译固件。精确公开固件的实屏、NVS/断电恢复与完整硬件验收尚未完成；部分中文依赖合法安装的本机字体，离线标题可能降级为 ASCII。
- 使用可信 LAN，禁止直接公开 Hub/Gateway/数据库。Bearer 权限较大，明文 HTTP 不保护 Token；匿名 Scene 也可能含任务信息。[网络边界](docs/NETWORK.md)。
- Scene 成功仅代表响应已准备，设备显示为 UNKNOWN。默认约 30 秒拉取，不适合紧急安全提醒。
- 仅支持新数据目录，两项旧 JSON 迁移失败保留；公开版 STALE、线程、取消与缓存修复均保留。[限制](docs/LIMITATIONS.md) · [验证](docs/VALIDATION.md) · [CI](docs/CI.md)。

v0.1.0 Tag/Release 保留；main 可包含后续源码维护。操作硬件前确认目标与完整备份；构建产物可能含 Wi-Fi 凭据，禁止提交私人配置、数据库、日志和个人固件。

## 贡献与许可

[贡献](CONTRIBUTING.md) · [English installation](docs/INSTALL_EN.md) · [第三方通知](THIRD_PARTY_NOTICES.md) · [许可范围](docs/LICENSING.md)

Copyright © 2026 Tkkdy。独立原创 Hub、Console、工具采用 **MIT**；原创 ESP32 固件采用 **GPL-3.0-only**，第三方保留各自条款。均允许商业使用，根目录 MIT 不覆盖固件 GPL 范围。
