<!-- SPDX-FileCopyrightText: 2026 Tkkdy -->
<!-- SPDX-License-Identifier: MIT -->
# 展示素材 / Asset provenance

| 文件 / asset | 真实性、来源及处理 / provenance | 授权 / status |
| --- | --- | --- |
| `console-demo.png` | 2026-10-19，由本候选未修改的真实Console代码在Chrome headless中渲染。仅新建loopback隔离Hub、合成任务和提醒，monitor=false、浏览器UTC、无真实设备和外部集成。不是mock界面或概念图。 / Actual Console rendered against an isolated synthetic-data Hub. | 原创UI与本轮截图 Copyright (c) 2026 Tkkdy，MIT；不包含第三方字体文件。 |
| `architecture.mmd` | 从Hub/API/固件和可选适配源码整理的可维护架构图；虚线是实验集成，不代表已完成安装验收。 / Source-grounded diagram; dashed links are experimental. | Copyright (c) 2026 Tkkdy，MIT。 |
| `hardware-overview.jpg` | 用户于 2026-10-20 提供；ESP32、转接板与 Home 屏幕实拍。 / Owner-supplied physical prototype photo. | 用户明确要求用于 GitHub README 展示；不作为精确公开固件验收。 |
| `device-workspace.jpg` | 同批 Workspace 实拍，保留 SIMULATED、STALE 与原型文字重叠。 / Workspace photo; labels and layout artifacts retained. | 同上 / Same display authorization. |
| `device-interrupt.jpg` | 同批 Interrupt 实拍；ASCII 文案与 Hub Web ACK 提示。 / Interrupt photo with manual Web ACK prompt. | 同上；不证明实体按钮或完整 ACK 闭环。 |
| `device-tibo.jpg` | 同批 Tibo 实拍；SIMULATED、时间、概率及背景网页原样保留。 / Tibo photo, historical demo values. | 同上；非当前消息或官方额度保证。 |
| `grok-bot-concept.png` | 用户提供的 Grok Bot 概念演示图；非产品截图，绘制/生成方式未核实。 / Owner-supplied concept; creation method unverified. | 用户要求展示；不推断第三方标识授权、合作关系或素材整体 MIT 许可。 |

Console截图中的 `SYNTHETIC-DEMO`、短实例ID和UTC时间来自临时隔离运行，任务 `Review demo task` 与提醒 `Preview reminder` 来自仓库示例，不属于个人事项。截图捕获在ACK之前；同次真实浏览器检查随后确认ACK成功且Todo未变化。设备、显示回执、额度等保持UNKNOWN，监控Stopped如实显示，没有修图伪造已连接状态。

PNG逐块检查只有IHDR/IDAT/IEND，没有EXIF、文本、GPS、创建软件或时间元数据；没有执行图像生成或视觉改造。保留截图原像素，来源及哈希在私有审查证据中可追溯。

## 本次素材处理 / Supplied images (2026-10-20)

仅选择四张互补实拍和一张概念图；其余重复照片未复制进仓库。原始附件未修改。JPEG 副本仅移除 EXIF/XMP、IPTC 与注释段，PNG 副本仅移除 EXIF、文本与时间块；不重编码、不裁剪、不改变像素，保留 ICC 颜色配置。照片中的个人任务、公开账号名及背景来自用户明确提供并要求展示的画面；未附带私人配置、数据库、日志或固件。

Four complementary hardware photos and one concept illustration were selected. Original attachments are untouched. Published copies remove metadata without re-encoding or altering pixels; ICC profiles are retained. Supplied screen content is shown under the owner's explicit README request. No private runtime files are included.

照片证明实物及所拍页面存在，不证明运行固件对应公开提交，不覆盖 NVS/断电恢复、长期稳定性或端到端验收。概念图中的多源整合与完成状态不代表已实现能力。素材展示许可不自动扩大为对照片、概念图或其中第三方标识的独立再许可；代码许可范围仍以项目许可文件为准。

Photos document the physical prototype and captured pages, not an identified public firmware build or complete hardware acceptance. Concept integrations and completion states are aspirational. Display authorization does not establish separate sublicensing rights for supplied artwork or third-party marks; code licensing is unchanged.
