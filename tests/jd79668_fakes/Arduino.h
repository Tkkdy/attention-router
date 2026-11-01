// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <sstream>
#include <string>
#include <utility>
constexpr int LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1;
unsigned long millis();
void delay(unsigned long);
int digitalRead(uint8_t);
void digitalWrite(uint8_t, int);
void pinMode(uint8_t, int);
struct TestSerial {
  std::string output;
  template<class T> void print(T value) {
    std::ostringstream stream; stream << value; output += stream.str();
  }
  template<class T> void println(T value) { print(value); output += '\n'; }
  template<class... T> void printf(const char* format, T... values) {
    char buffer[512]; std::snprintf(buffer, sizeof(buffer), format, values...);
    output += buffer;
  }
};
extern TestSerial Serial;
