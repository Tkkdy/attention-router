// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <ctime>
#include <string>

// Synthetic endpoints make the host test runnable from a clean checkout.
#if !__has_include("../../firmware/esp32_dashboard/private_config.h")
#define DASHBOARD_WEATHER_LATITUDE "1"
#define DASHBOARD_WEATHER_LONGITUDE "1"
#define DASHBOARD_RADAR_URL "https://example.test/status.json"
#endif

class String : public std::string {
 public:
  using std::string::string;
  String(const std::string& value) : std::string(value) {}
  String(unsigned long value) : std::string(std::to_string(value)) {}
};

inline size_t strlcpy(char* destination, const char* source, size_t size) {
  const size_t length = std::strlen(source);
  if (size) {
    const size_t copied = length < size - 1 ? length : size - 1;
    std::memcpy(destination, source, copied);
    destination[copied] = '\0';
  }
  return length;
}

extern unsigned long fakeNow;
inline unsigned long millis() { return fakeNow; }

struct FakeSerial {
  template <typename T> void print(const T&) {}
  template <typename T> void println(const T&) {}
};
extern FakeSerial Serial;

#ifdef _WIN32
inline tm* gmtime_r(const time_t* input, tm* result) {
  return gmtime_s(result, input) == 0 ? result : nullptr;
}
#endif
