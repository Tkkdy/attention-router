// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Adafruit_GFX.h>
#include <Arduino.h>
#include <SPI.h>

#include "config.h"

// Four-color values passed to Adafruit_GFX drawing methods.
// The controller stores each pixel as: 00=black, 01=white, 10=yellow, 11=red.
constexpr uint16_t EPD_BLACK  = 0x0000;
constexpr uint16_t EPD_WHITE  = 0xFFFF;
constexpr uint16_t EPD_YELLOW = 0xFFE0;
constexpr uint16_t EPD_RED    = 0xF800;

class GDEM042F52Display : public Adafruit_GFX {
 public:
  static constexpr uint16_t PANEL_WIDTH = 400;
  static constexpr uint16_t PANEL_HEIGHT = 300;
  static constexpr size_t FRAME_BYTES =
      (static_cast<size_t>(PANEL_WIDTH) * PANEL_HEIGHT) / 4;

  GDEM042F52Display();

  // Configures the ESP32-S3 GPIO and SPI bus. Does not refresh the panel.
  bool begin();

  // Sends the current 2-bpp framebuffer to the JD79668 and performs a full refresh.
  // Returns false if the controller does not become ready before a timeout.
  bool update();

  void drawPixel(int16_t x, int16_t y, uint16_t color) override;

 private:
  uint8_t frame_[FRAME_BYTES];
  bool begun_ = false;

  static uint8_t colorCode(uint16_t color);
  static void writeCommand(uint8_t command);
  static void writeData(uint8_t data);
  static bool waitUntilReady(const char* phase, uint32_t timeoutMs);
  static bool initializePanel();
  static bool sleepPanel();
};
