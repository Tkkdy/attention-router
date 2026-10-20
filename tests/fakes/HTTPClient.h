// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once

#include "Arduino.h"
#include "WiFiClientSecure.h"

constexpr int HTTP_CODE_OK = 200;
extern int fakeWeatherStatus;
extern int fakeRadarStatus;
extern int fakeWeatherCalls;
extern int fakeRadarCalls;

struct HTTPClient {
  bool weather = false;
  void setConnectTimeout(int) {}
  void setTimeout(int) {}
  bool begin(const String& url) {
    weather = url.find("open-meteo") != std::string::npos;
    return true;
  }
  bool begin(WiFiClientSecure&, const String& url) {
    weather = url.find("open-meteo") != std::string::npos;
    return true;
  }
  int GET() {
    if (weather) {
      ++fakeWeatherCalls;
      return fakeWeatherStatus;
    }
    ++fakeRadarCalls;
    return fakeRadarStatus;
  }
  String getString() { return weather ? String("weather") : String("radar"); }
  void end() {}
};
