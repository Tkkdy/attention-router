// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: GPL-3.0-only
//
// Port of the Good Display GDEM042F52 Arduino sample to ESP32-S3.
// Controller: JD79668. Panel: 400 x 300, four colors, 2 bits per pixel.
//
// The vendor sample's A14/A15/A16/A17 pin assignments have deliberately
// been replaced with the explicit GPIO assignments in config.h.

#include "gdem042f52_display.h"

#include <string.h>

#if DASHBOARD_PANEL == DASHBOARD_PANEL_GDEM042F52
namespace {
constexpr uint32_t EPD_SPI_FREQUENCY = 10000000UL;
constexpr uint32_t EPD_BUSY_TIMEOUT_MS = 60000UL;
constexpr uint32_t EPD_POWER_OFF_TIMEOUT_MS = 15000UL;
}

GDEM042F52Display::GDEM042F52Display()
    : Adafruit_GFX(PANEL_WIDTH, PANEL_HEIGHT) {
  memset(frame_, 0x55, sizeof(frame_));  // 01 01 01 01 = all white
}

bool GDEM042F52Display::begin() {
  pinMode(PIN_BUSY, INPUT);
  pinMode(PIN_RST, OUTPUT);
  pinMode(PIN_DC, OUTPUT);
  pinMode(PIN_CS, OUTPUT);

  digitalWrite(PIN_CS, HIGH);
  digitalWrite(PIN_DC, HIGH);
  digitalWrite(PIN_RST, HIGH);

  // JD79668 uses write-only SPI: SCK + MOSI, no MISO.
  SPI.begin(PIN_SCK, -1, PIN_MOSI, PIN_CS);
  setRotation(0);
  begun_ = true;
  return true;
}

uint8_t GDEM042F52Display::colorCode(uint16_t color) {
  if (color == EPD_BLACK) return 0x00;
  if (color == EPD_YELLOW) return 0x02;
  if (color == EPD_RED) return 0x03;
  return 0x01;  // white (also the safe fallback for unrecognized colors)
}

void GDEM042F52Display::drawPixel(int16_t x, int16_t y, uint16_t color) {
  // The dashboard uses physical rotation 0.
  if (x < 0 || y < 0 || x >= PANEL_WIDTH || y >= PANEL_HEIGHT) return;

  const size_t pixelIndex =
      static_cast<size_t>(y) * PANEL_WIDTH + static_cast<uint16_t>(x);
  const uint8_t shift = static_cast<uint8_t>(6 - ((pixelIndex & 0x03U) * 2U));
  const uint8_t mask = static_cast<uint8_t>(0x03U << shift);
  const uint8_t code = colorCode(color);
  frame_[pixelIndex >> 2] = static_cast<uint8_t>(
      (frame_[pixelIndex >> 2] & static_cast<uint8_t>(~mask)) |
      static_cast<uint8_t>(code << shift));
}

void GDEM042F52Display::writeCommand(uint8_t command) {
  digitalWrite(PIN_CS, LOW);
  digitalWrite(PIN_DC, LOW);
  SPI.transfer(command);
  digitalWrite(PIN_CS, HIGH);
}

void GDEM042F52Display::writeData(uint8_t data) {
  digitalWrite(PIN_CS, LOW);
  digitalWrite(PIN_DC, HIGH);
  SPI.transfer(data);
  digitalWrite(PIN_CS, HIGH);
}

bool GDEM042F52Display::waitUntilReady(const char* phase,
                                      uint32_t timeoutMs) {
  const uint32_t startedAt = millis();
  while (digitalRead(PIN_BUSY) == LOW) {
    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - startedAt) >= timeoutMs) {
      Serial.printf("[EPD] BUSY timeout during %s after %lu ms; GPIO%u=LOW\n",
                    phase, static_cast<unsigned long>(now - startedAt), PIN_BUSY);
      return false;
    }
    delay(1);
  }
  return true;
}

bool GDEM042F52Display::initializePanel() {
  // Full-refresh initialization sequence from the supplied Good Display sample.
  delay(20);
  digitalWrite(PIN_RST, LOW);
  delay(40);
  digitalWrite(PIN_RST, HIGH);
  delay(50);

  writeCommand(0x4D);
  writeData(0x78);

  writeCommand(0x00);  // PSR
  writeData(0x0F);
  writeData(0x29);

  writeCommand(0x06);  // BTST
  writeData(0x0D);
  writeData(0x12);
  writeData(0x24);
  writeData(0x25);
  writeData(0x12);
  writeData(0x29);
  writeData(0x10);

  writeCommand(0x30);  // frame rate / waveform
  writeData(0x08);

  writeCommand(0x50);  // CDI, white border
  writeData(0x37);

  writeCommand(0x61);  // 400 x 300 resolution
  writeData(PANEL_WIDTH / 256);
  writeData(PANEL_WIDTH % 256);
  writeData(PANEL_HEIGHT / 256);
  writeData(PANEL_HEIGHT % 256);

  writeCommand(0xAE);
  writeData(0xCF);

  writeCommand(0xB0);
  writeData(0x13);

  writeCommand(0xBD);
  writeData(0x07);

  writeCommand(0xBE);
  writeData(0xFE);

  writeCommand(0xE9);
  writeData(0x01);

  writeCommand(0x04);  // power on
  return waitUntilReady("power-on", EPD_BUSY_TIMEOUT_MS);
}

bool GDEM042F52Display::sleepPanel() {
  writeCommand(0x02);  // power off
  writeData(0x00);
  const bool poweredOff =
      waitUntilReady("power-off", EPD_POWER_OFF_TIMEOUT_MS);

  if (poweredOff) {
    writeCommand(0x07);  // deep sleep only after power-off is confirmed
    writeData(0xA5);
  }
  return poweredOff;
}

bool GDEM042F52Display::update() {
  if (!begun_) {
    Serial.println("JD79668 update requested before display.begin()");
    return false;
  }

  SPI.beginTransaction(
      SPISettings(EPD_SPI_FREQUENCY, MSBFIRST, SPI_MODE0));

  bool ok = initializePanel();
  if (ok) {
    writeCommand(0x10);  // image RAM
    for (size_t i = 0; i < FRAME_BYTES; ++i) {
      writeData(frame_[i]);
    }

    writeCommand(0x12);  // display refresh
    writeData(0x00);
    ok = waitUntilReady("display refresh", EPD_BUSY_TIMEOUT_MS);
  }

  // The vendor sample explicitly powers down and enters deep sleep after updates.
  // Also attempt power-off after an error, but do not report it as a refresh.
  const bool slept = sleepPanel();
  SPI.endTransaction();

  return ok && slept;
}
#endif
