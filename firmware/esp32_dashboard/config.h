// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

// Hardware configuration verified with the 4.2 inch GDEY042Z98 panel.
// Do not change these values without new hardware evidence.
constexpr uint8_t PIN_BUSY = 4;
constexpr uint8_t PIN_CS = 5;
constexpr uint8_t PIN_RST = 16;
constexpr uint8_t PIN_DC = 17;
constexpr uint8_t PIN_SCK = 18;
constexpr uint8_t PIN_MOSI = 23;

constexpr uint32_t SERIAL_BAUD = 115200;
