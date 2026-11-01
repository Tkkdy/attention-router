// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: MIT
#pragma once
#include <Arduino.h>
class Adafruit_GFX {
 public:
  Adafruit_GFX(int16_t, int16_t) {}
  virtual void drawPixel(int16_t, int16_t, uint16_t) = 0;
  void setRotation(uint8_t) {}
};
