# ESP32 固件许可

Copyright (c) 2026 Tkkdy，限本项目原创部分。

`esp32_dashboard/` 中本项目有权授权的原创程序、头文件和配置示例采用 **SPDX-License-Identifier: GPL-3.0-only**，可依 GNU General Public License version 3 使用、修改和分发。完整许可见 [LICENSE](LICENSE)。商业使用允许；分发修改版或组合固件时须履行 GPLv3 的相应义务。本声明不是 MIT/GPL 二选一授权。

`esp32_dashboard/weather_ca.h` 内公共 ISRG Root X1 证书保持原样，不声称其为 Tkkdy 原创或将证书重新授权为 GPL。包装代码的项目原创部分仍按 GPL-3.0-only；该第三方数据例外详见 [第三方说明](../THIRD_PARTY_NOTICES.md)。

## 实际组合关系

`pages.cpp` 引用 `GxEPD2_3C.h` 并实例化 `GxEPD2_3C<GxEPD2_420c_GDEY042Z98, ...>`。GxEPD2 驱动代码参与 Arduino 固件编译、链接，属于实际组合，不能把生成的程序称作纯 MIT 固件。

已核对 GxEPD2 **1.6.9** 标签和用于构建的安装副本：LICENSE、library.properties、三色模板及对应驱动头/源文件五项哈希一致。上游 LICENSE 是 GPL Version 3；这些关键源文件没有独立明确的 “or any later version” 授权。GPL 正文末尾的授权示例不是某一源文件的额外授权，因此记录为 **上游 GPLv3 已确认，or-later 未另行证实**；本项目原创固件明确选择 GPL-3.0-only，与已确认的版本 3 组合。

一手资料：[GxEPD2 1.6.9 LICENSE](https://github.com/ZinggJM/GxEPD2/blob/1.6.9/LICENSE)、[模板](https://github.com/ZinggJM/GxEPD2/blob/1.6.9/src/GxEPD2_3C.h)、[GDEY042Z98 驱动](https://github.com/ZinggJM/GxEPD2/blob/1.6.9/src/gdey3c/GxEPD2_420c_GDEY042Z98.h)。上游作者与来源通知保持其原有形式。

## 本次与未来发行边界

本次提供项目源码，不附 `.bin`、第三方库、ESP32 SDK 或字体文件。用户按 [Windows 构建说明](../docs/WINDOWS.md) 安装指定依赖。Hub 是独立 HTTP 进程，不链接 GxEPD2；其独立原创部分按 MIT 授权。

未来若分发固件二进制、镜像或整机，需要针对实际组合核对全部组件许可，并满足 GPLv3 对应源码、修改通知、构建/安装材料以及适用的安装信息要求；ESP32 SDK 内不同组件不可一概称为 LGPL 或 GPL。本次没有作出二进制发行合规已完成的承诺。
