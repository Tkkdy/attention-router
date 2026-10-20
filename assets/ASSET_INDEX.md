<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# 展示素材 / Asset provenance

| 文件 / asset | 真实性、来源及处理 / provenance | 授权 / status |
| --- | --- | --- |
| `console-demo.png` | 2026-10-19，由本候选未修改的真实Console代码在Chrome headless中渲染。仅新建loopback隔离Hub、合成任务和提醒，monitor=false、浏览器UTC、无真实设备和外部集成。不是mock界面或概念图。 / Actual Console rendered against an isolated synthetic-data Hub. | 原创UI与本轮截图 Copyright (c) 2026 Tkkdy，MIT；不包含第三方字体文件。 |
| `architecture.mmd` | 从Hub/API/固件和可选适配源码整理的可维护架构图；虚线是实验集成，不代表已完成安装验收。 / Source-grounded diagram; dashed links are experimental. | Copyright (c) 2026 Tkkdy，MIT。 |
| 硬件实拍 / hardware photo | 当前缺少可安全公开的产品实拍。已找到旧原板照片，但含真实任务短ID与私人背景且不证明本候选身份，故未导入。 / Existing private photo excluded. | MISSING；不以AI图、渲染或Console预览代替真实照片。 |

Console截图中的 `SYNTHETIC-DEMO`、短实例ID和UTC时间来自临时隔离运行，任务 `Review demo task` 与提醒 `Preview reminder` 来自仓库示例，不属于个人事项。截图捕获在ACK之前；同次真实浏览器检查随后确认ACK成功且Todo未变化。设备、显示回执、额度等保持UNKNOWN，监控Stopped如实显示，没有修图伪造已连接状态。

PNG逐块检查只有IHDR/IDAT/IEND，没有EXIF、文本、GPS、创建软件或时间元数据；没有执行图像生成或视觉改造。保留截图原像素，来源及哈希在私有审查证据中可追溯。

## 待补素材 / Missing asset

以后在获批的安全硬件安排下，提供一张经典ESP32与指定墨水屏/转接板的真实照片：仅显示合成示例，不含个人任务、账号、Wi-Fi、域名、位置线索或私人背景；移除EXIF/GPS，并确认照片可按项目许可使用。照片展示不等于最终候选真机验收，通过记录仍须独立核对。本轮不要求操作原板来拍照。

The existing image documents a private historical device, not the exact public firmware. A future authorized photo should show only synthetic data, have clear reuse rights, and contain no private identifiers or location metadata. The owner approved source publication without a hardware photo; photography remains outstanding and is not marked complete.
