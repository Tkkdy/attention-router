# 已知限制

v0.1.0 为源码发布。基础范围：Windows 本机 Hub/Console、受鉴权本地 HTTP 集成、指定屏幕的 Scene 显示代码、任务/当前事项、上下文规则、提醒与 Web ACK、断连缓存逻辑。最终候选精确固件的真机验收尚未完成，不能把源码存在或软件测试通过写成硬件能力已通过。

Experimental：DeepSeekBot、GrokBot/OAuth/Tunnel、Todo Core 桥接、Tibo、Codex 用量采集、Radar/天气等外部源。默认不需要它们即可使用基础设备。

未完成：通用 Agent 执行状态感知、自动理解所有项目、经过验收的本地开源权重模型、跨平台桌面采集、通用屏幕适配、实体按钮 ACK、完整独立 Bot 安装器、设备收到/显示完成的回执协议。

`GET /scene` 表示 Hub 准备并发布投影，不证明 ESP32 收到或屏幕已经显示；Console 的 preview 与 canonical snapshot 也有区别。无设备协议的字段应保持 UNKNOWN。

固件默认 30 秒轮询，90 秒判定 Hub 断连，恢复有稳定窗口；墨水屏需要刷新时间，不是实时推送/高频动画。此 Preview 不适合紧急安全提醒。

中文仅通过部分标题位图扩展支持，其他消息字段仍受 ASCII/长度限制；模板/示例使用英文以便稳定复现。日期的部分适配器仍固定 UTC+8，不表示全面时区本地化。

数据库为新安装创建，不支持从私人现有数据直接导入。旧 JSON 迁移测试存在两项已知基线失败，见 VALIDATION；不在本次开源整理中重构迁移。

## 离线中文缓存

Todo Cache 保存 ID、ASCII 备用标题和完成状态，不保存中文位图；中文恢复依赖有效 Last Scene 位图及匹配 ID/标题。全页 STALE 时跳过 Last Scene 保存，Standalone Home 使用独立缓存。离线冷启动可能显示 ASCII 短编号，联网后可重新获得标题；不保证断电后中文无损恢复。NVS 写入可靠性和精确固件实屏仍未验收，主机 fake NVS 测试不能替代真机证据。

未配置 Radar/天气/互联网探测不会单独令新鲜的 Hub 本地任务或提醒全页 STALE；字段仍显示 UNKNOWN。已启用的 Home Radar/天气失败仍标旧；Hub 失联仍回退并标旧。WAN 探测与 LAN Hub 健康分别显示，WAN Offline 不代表本地任务已过期。无独立来源的 Standalone 页面仍无法证明新鲜。

设备端可选外网前置条件：`DASHBOARD_INTERNET_CHECK_URL` 留空时 Internet 为 UNKNOWN，NTP 不启动同步、天气/Radar 不发起获取；只填 NTP/经纬度/Radar 地址不够。需配置探测 URL、预期状态码及 Location，并在串口确认 Internet probe: ON（Online）；NTP 另需时区和两个服务器，天气/Radar 另需有效日期及各自配置。天气获取限 Standalone 或 Hub Home，设备原生 Radar 获取限 Standalone。此前已启动的 SNTP/既有时间不等于重新完成外网验证。本限制不阻断本地 Hub 任务/提醒路径；Hub 端 Radar 不受该设备探测变量直接控制。操作见 [Windows 安装与启动](WINDOWS.md)。

Windows 缺少可用微软雅黑时启动/设备请求会给出警告，英文 ASCII 标题继续显示；中文字形不绘制，设备使用任务的 ASCII 备用标题。网页业务文本保留，不能把此降级描述成中文显示通过。

版权署名为 2026 Tkkdy；MIT/GPL 范围及第三方许可见 [许可说明](LICENSING.md)。转接板型号/供电仍需按实物确认；官方构建与真机状态见 [验证记录](VALIDATION.md)。许可确认不等于硬件验收。


## 发布范围

v0.1.0 是源码 Release，无预编译固件。main 包含后续维护；软件通过不替代精确公开固件的显示、ACK、断连恢复与断电缓存硬件验收。
