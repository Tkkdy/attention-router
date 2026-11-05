// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>
#include <vector>
#include "../firmware/esp32_dashboard/gdem042f52_display.h"

TestSerial Serial;
TestSPI SPI;
uint32_t clockMs = 0, readyAt = 0;
int levels[256]{}, modes[256]{};
bool stuckLow = false, transaction = false;
uint8_t command = 0;
std::vector<uint8_t> commands, image;
unsigned long millis() { return clockMs; }
void delay(unsigned long ms) { clockMs += ms; }
void pinMode(uint8_t pin, int mode) { modes[pin] = mode; }
void digitalWrite(uint8_t pin, int level) { levels[pin] = level; }
int digitalRead(uint8_t pin) {
  if (pin == PIN_BUSY) return stuckLow || clockMs < readyAt ? LOW : HIGH;
  return levels[pin];
}
void TestSPI::begin(int sck, int miso, int mosi, int cs) {
  assert(sck == 18 && miso == -1 && mosi == 13 && cs == 5);
}
void TestSPI::beginTransaction(SPISettings) { assert(!transaction); transaction = true; }
void TestSPI::endTransaction() { assert(transaction); transaction = false; }
uint8_t TestSPI::transfer(uint8_t data) {
  assert(transaction && levels[PIN_CS] == LOW);
  if (levels[PIN_DC] == LOW) {
    command = data; commands.push_back(data);
    if (data == 0x04 || data == 0x12 || data == 0x02) readyAt = clockMs + 20;
  } else if (command == 0x10) image.push_back(data);
  return 0;
}
int main() {
  static_assert(PIN_MOSI == 13, "JD79668 profile uses ESP32-S3 MOSI GPIO13");
  GDEM042F52Display panel;
  assert(!panel.update());
  assert(commands.empty());
  panel.begin(); assert(modes[PIN_BUSY] == INPUT);
  const uint16_t colors[] = {EPD_BLACK, EPD_WHITE, EPD_YELLOW, EPD_RED};
  for (int y = 0; y < 300; ++y)
    for (int x = 0; x < 400; ++x) panel.drawPixel(x, y, colors[x / 100]);
  // Out-of-bounds pixels cannot corrupt neighboring framebuffer bytes.
  panel.drawPixel(-1, 0, EPD_RED); panel.drawPixel(400, 299, EPD_BLACK);
  assert(panel.update() && !transaction);
  const std::vector<uint8_t> expected = {
    0x4d,0x00,0x06,0x30,0x50,0x61,0xae,0xb0,0xbd,0xbe,0xe9,
    0x04,0x10,0x12,0x02,0x07
  };
  assert(commands == expected && image.size() == 30000);
  for (int i = 0; i < 30000; ++i) {
    const uint8_t bytes[] = {0x00, 0x55, 0xaa, 0xff};
    assert(image[i] == bytes[(i % 100) / 25]);
  }
  assert(clockMs == 170);  // Reset + three simulated 20 ms BUSY waits.
  commands.clear(); image.clear(); Serial.output.clear();
  stuckLow = true;
  const auto startedAt = clockMs;
  assert(!panel.update() && !transaction);
  assert(clockMs - startedAt == 75110);
  assert(image.empty() && commands.back() == 0x02);
  assert(Serial.output.find("timeout during power-on") != std::string::npos);
  assert(Serial.output.find("timeout during power-off") != std::string::npos);
  // A later retry resets and initializes again rather than remaining latched failed.
  stuckLow = false; commands.clear();
  assert(panel.update());
  assert(commands == expected);
  std::cout << "PASS: driver command order, 30000 color bytes, BUSY waits/timeouts, retry\n";
}
