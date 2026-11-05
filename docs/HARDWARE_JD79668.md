<!-- SPDX-FileCopyrightText: 2026 flowersea123 -->
<!-- SPDX-License-Identifier: MIT -->
# ESP32-S3 + JD79668 (experimental)

可选配置：ESP32-S3-WROOM-1 开发板 + GDEM042F52/JD79668 四色屏，
400 x 300，黑/白/黄/红。原经典 ESP32 + GDEY042Z98 保持默认。

| 屏幕转接板信号 | ESP32-S3 GPIO |
| --- | --- |
| BUSY | 4 |
| CS | 5 |
| RES / RST | 16 |
| D/C | 17 |
| SCL / SCK | 18 |
| SDI / MOSI | 13 |
| GND | 共地 / common ground |
| VCC | 按已确认的转接板规格 / per adapter specification |

GPIO 为 3.3 V 逻辑；SPI 无 MISO。确认屏幕、转接板与 FPC 接触方向，硬件操作前断电。

**Arduino IDE：** 在 `firmware/esp32_dashboard/config.h` 的 `#ifndef` 下，
将默认值改为 `#define DASHBOARD_PANEL DASHBOARD_PANEL_GDEM042F52`，
选择 **ESP32S3 Dev Module**，编译 `esp32_dashboard.ino`。

**CLI：** 沿用 [Windows 安装](WINDOWS.md) 的 `$cli`、`$cfg`：

```powershell
powershell -NoProfile -File .\compile_firmware.ps1 -ArduinoCli $cli -ConfigFile $cfg -HardwareProfile esp32s3-gdem042f52
```

新配置依赖 Adafruit GFX、BusIO 和 ArduinoJson；原配置仍需 GxEPD2。
仅完整刷新、rotation 0；现有页面保持黑/白/红配色，绘图接口另支持黄色。
本地移植版已由所有者确认显示正常；本 PR 最终版本未刷写验收。

## English

Optional ESP32-S3-WROOM-1 + GDEM042F52/JD79668, 400 x 300, black/white/yellow/red.
The classic ESP32/GDEY042Z98 profile remains the default. Use the wiring above,
3.3 V GPIO logic and an adapter supply confirmed from its specification. Check
FPC contacts and power off before hardware changes.

In Arduino IDE set the fallback `DASHBOARD_PANEL` definition in `config.h` to
`DASHBOARD_PANEL_GDEM042F52` and select **ESP32S3 Dev Module**. Alternatively run
the command above; the script only compiles. Dependencies are Adafruit GFX,
BusIO and ArduinoJson; the default profile additionally needs GxEPD2.
Full refresh and rotation 0 only. Existing pages retain black/white/red; yellow
is available to drawing code. The owner confirmed a prior local port displays;
the final PR version has not been flashed or physically accepted.
