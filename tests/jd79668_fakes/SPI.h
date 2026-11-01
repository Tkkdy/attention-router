// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: MIT
#pragma once
#include <Arduino.h>
constexpr int MSBFIRST = 1, SPI_MODE0 = 0;
struct SPISettings {
  SPISettings(uint32_t, int, int) {}
};
struct TestSPI {
  void begin(int, int, int, int);
  void beginTransaction(SPISettings);
  uint8_t transfer(uint8_t);
  void endTransaction();
};
extern TestSPI SPI;
