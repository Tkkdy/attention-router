# 第三方许可与来源说明

本候选只含项目源码。第三方包、SDK、依赖运行时和字体文件没有随源码包分发；它们由用户另行安装，保持上游许可。本表是本次指定版本/已检查组件的说明，不是所有可选集成、SDK 子组件和未来二进制的全量许可证审计。

## 随源码保留的第三方材料

- `integrations/deepseek_bot/fork-wiring.patch` 含 DS Bot 上游上下文。上游署名为 **Copyright 2026 FeiZhuLulu and the DS Bot contributors**；本项目修改 Copyright (c) 2026 Tkkdy，按 Apache-2.0 保持。完整原许可和通知在同目录 `UPSTREAM-LICENSE`、`UPSTREAM-NOTICE`，原样保留。NOTICE 内提到 DeepSeek Harness 的 MIT 通知也保留；NOTICE 的上游项目描述不是 Attention Router 全仓库来源声明。
- `firmware/esp32_dashboard/weather_ca.h` 含公共 **ISRG Root X1** 信任锚，DER SHA-256 为 `96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6`。来源为 [ISRG / Let's Encrypt 官方证书页](https://letsencrypt.org/certificates/)。证书不是私钥或个人凭据；保持原始证书字节，不将第三方证书声称为 Tkkdy 原创，不对证书另行添加 MIT/GPL 授权。[ISRG CP/CPS v5.5 §9.5](https://letsencrypt.org/documents/isrg-cp-cps-v5.5/#95-intellectual-property-rights) 明确允许非独占、免版税地完整复制和分发证书。清单中的 `LicenseRef-ISRG-Public-Certificate` 标识这一上游证书分发条件，不代表本项目另创授权，也不是标准 SPDX 短标识。项目原创包装代码为 GPL-3.0-only。
- `licenses/` 和 `firmware/LICENSE` 内许可正文依其原有允许复制条件保留，不将其版权改为 Tkkdy。

## 固件与主机测试依赖（不捆绑代码）

| 组件 | 指定版本 | 核实的许可 / 注意事项 |
| --- | --- | --- |
| [GxEPD2](https://github.com/ZinggJM/GxEPD2/blob/1.6.9/LICENSE) | 1.6.9 | GPL Version 3；关键文件 or-later 未独立证实。完整正文见 `licenses/GxEPD2-GPL-3.0.txt`。作者 Jean-Marc Zingg；源码注明 Good Display 示例来源。 |
| [Adafruit GFX](https://github.com/adafruit/Adafruit-GFX-Library/blob/1.12.6/license.txt) | 1.12.6 | BSD-2-Clause，Copyright (c) 2012 Adafruit Industries；正文 `licenses/Adafruit-GFX-BSD-2-Clause.txt`。 |
| [Adafruit BusIO](https://github.com/adafruit/Adafruit_BusIO/blob/1.17.4/LICENSE) | 1.17.4 | **MIT**，Copyright (c) 2017 Adafruit Industries；正文 `licenses/Adafruit-BusIO-MIT.txt`。不能与 GFX 一并写作 BSD。 |
| [ArduinoJson](https://github.com/bblanchon/ArduinoJson/blob/v7.4.2/LICENSE.txt) | 7.4.2 | MIT，Copyright 2014–2025 Benoit BLANCHON；正文 `licenses/ArduinoJson-MIT.txt`。 |
| [ESP32 Arduino Core](https://github.com/espressif/arduino-esp32/tree/3.3.1) | 3.3.1 | 所检查 core 文件含 LGPL-2.1-or-later 授权；ESP-IDF、预编译组件与工具具有各自许可，不能把整套 SDK 视为单一 LGPL。 |
| [json-c](https://github.com/json-c/json-c/blob/json-c-0.18-20240915/COPYING) | 0.18 | MIT；仅备用主机测试依赖。 |

固件使用 Adafruit GFX 的默认文本绘制；本项目没有包含 `Fonts/FreeSans*.h` 等外部字体头，也没有打包 GNU FreeFont 或其他字体文件。未来更换字体或捆绑图形库时应重新核对对应字体许可。

## Python 锁定依赖

以下来自已安装且版本与 `requirements.lock.txt` 完全一致的发行包 METADATA（2026-10-18 核对）。依赖通过包管理器安装；许可证、版权和所带二进制组件的通知应以各包分发内容为准，不能用项目 MIT 取代。Pillow 的 MIT-CMU 与项目 MIT 不是同一文本。

| 包 | 版本 | 元数据许可 |
| --- | --- | --- |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.136.3 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| pillow | 12.0.0 | MIT-CMU |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| starlette | 1.8.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.5 | Apache-2.0 |
| uvicorn | 0.49.0 | BSD-3-Clause |

`tzdata` 包元数据为 Apache-2.0；其 IANA 时区数据按相应上游数据说明处理。上述元数据是包级识别，不代表每个 wheel 内附带的所有 native 库均同许可。Python、Arduino CLI、编译器及可选 MCP/Bot/Harness 运行时未捆绑，保持各自上游许可；本表不声称列全这些可选运行时的传递依赖。

一手资料：[FastAPI](https://github.com/fastapi/fastapi)、[Uvicorn](https://github.com/Kludex/uvicorn)、[HTTPX](https://github.com/encode/httpx)、[Pillow 12.0.0 许可](https://github.com/python-pillow/Pillow/blob/12.0.0/LICENSE)、[tzdata](https://github.com/python/tzdata)。

## 中文字体与外部服务

Hub 使用用户合法安装的 Microsoft YaHei 系统字体生成任务标题位图；仓库不分发字体文件，也不授予字体本身的再分发权。字体不可用时走已说明的 ASCII 降级。自有程序允许商业使用，不等于任意第三方字体、天气/Radar/Bot 数据或服务均可无条件商用；使用者应遵守所用来源的授权与条款。

## 后续二进制发行

若未来提供固件 `.bin`、整机、预装环境或容器，应重新固定实际组合依赖、保留其通知，并提供适用的 GPL/LGPL 对应源码、修改及构建/安装材料。当前是源码发行准备，没有将这一后续核查冒充完成。
