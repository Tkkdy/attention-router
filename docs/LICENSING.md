# 分组件许可与版权

本候选已根据所有者的明确授权填写正式许可：**Copyright (c) 2026 Tkkdy**，限有权授权的项目原创贡献。MIT 与 GPLv3 均允许商业使用，但必须遵守各自条件。版权授权不等于该候选已经公开发布或已完成硬件验收。

## 文件范围

| 文件范围 | 许可及例外 |
| --- | --- |
| `hub/**`（含 Web Console）、`examples/**`、`experiments/oauth_spike/**` 的项目原创部分 | MIT |
| 根目录 Python/PowerShell 工具、`tests/**` 的独立原创测试与替身 | MIT；测试链接 GPL 固件的组合测试程序仍需遵守适用 GPL 条件 |
| README、`docs/**`、示例配置、requirements、`.gitignore`、项目清单的原创内容 | MIT；引用、第三方内容及许可正文保留原条件 |
| `firmware/esp32_dashboard/**` 原创代码/配置示例 | GPL-3.0-only；见 [固件说明](../firmware/LICENSING.md) |
| `firmware/esp32_dashboard/weather_ca.h` | 原创包装按 GPL-3.0-only，嵌入的公共 ISRG Root X1 证书保持原样，不声称自有版权或重新授权 |
| `integrations/deepseek_bot/fork-wiring.patch` | Apache-2.0：上游上下文与本项目修改共同保持此许可，不覆盖为 MIT |
| `integrations/deepseek_bot/` 其余独立原创适配文件 | MIT；UPSTREAM-LICENSE/NOTICE 除外 |
| `licenses/**`、`firmware/LICENSE`、UPSTREAM-LICENSE/NOTICE | 原许可文本/通知原样保留，不适用项目原创内容的 MIT 默认项 |

根 [LICENSE](../LICENSE) 定义范围并附完整 MIT 授权，[licenses/MIT.txt](../licenses/MIT.txt) 单独保留该正文。固件 GPLv3 完整正文在 [firmware/LICENSE](../firmware/LICENSE)，与原有 [GxEPD2 GPL 文本](../licenses/GxEPD2-GPL-3.0.txt) 字节一致。这里没有“全仓库 MIT”或“MIT OR GPL”授权。

## SPDX 与来源

源码许可头及 [LICENSE_MAP.json](../LICENSE_MAP.json) 文件级清单用于表达上述文件范围，不能覆盖文件已有的第三方通知。公开证书、上游补丁和许可正文须按例外处理。`tests/parser_fakes/ArduinoJson.h` 是使用 json-c 的独立测试适配替身，依赖名称不代表复制上游 ArduinoJson 实现。

`pages.cpp` 确实实例化 GxEPD2 三色驱动，驱动参与最终固件。GxEPD2 1.6.9 的 GPL Version 3 已核实；关键文件没有额外明确的 or-later 授权，本项目原创固件因此明确采用 GPL-3.0-only。Hub 独立进程通过 HTTP 与设备交换数据，不链接该驱动。

第三方依赖、公共证书、主机字体和未来二进制发行边界见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。不捆绑依赖不等于未来可以忽略依赖许可；本次仅源码准备，不宣称 SDK 全组件/二进制合规已完成。

参考：[MIT 官方文本](https://opensource.org/license/mit)、[GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)、[GxEPD2 1.6.9](https://github.com/ZinggJM/GxEPD2/tree/1.6.9)。
