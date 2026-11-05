// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

// Keep the original classic ESP32 + three-color panel as the default.
// Arduino IDE: change the default below to DASHBOARD_PANEL_GDEM042F52 for
// ESP32S3 Dev Module + JD79668. CLI builds can use -DDASHBOARD_PANEL=2.
#define DASHBOARD_PANEL_GDEY042Z98 1
#define DASHBOARD_PANEL_GDEM042F52 2
#ifndef DASHBOARD_PANEL
#define DASHBOARD_PANEL DASHBOARD_PANEL_GDEY042Z98
#endif
#if DASHBOARD_PANEL != DASHBOARD_PANEL_GDEY042Z98 && \
    DASHBOARD_PANEL != DASHBOARD_PANEL_GDEM042F52
#error "Unknown DASHBOARD_PANEL; use GDEY042Z98 (1) or GDEM042F52 (2)"
#endif

// Both profiles use write-only SPI with 3.3 V GPIO logic.
constexpr uint8_t PIN_BUSY = 4;
constexpr uint8_t PIN_CS = 5;
constexpr uint8_t PIN_RST = 16;
constexpr uint8_t PIN_DC = 17;
constexpr uint8_t PIN_SCK = 18;
#if DASHBOARD_PANEL == DASHBOARD_PANEL_GDEM042F52
constexpr uint8_t PIN_MOSI = 13;
#else
constexpr uint8_t PIN_MOSI = 23;
#endif

constexpr uint32_t SERIAL_BAUD = 115200;
