// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once

#include "Arduino.h"
#include <type_traits>

extern std::string fakeRadarRunDate;
extern std::string fakeRadarDetail;
extern std::string fakeRadarPayloadStatus;

struct JsonValue {
  std::string path;
  JsonValue operator[](const char* key) const { return {path + "/" + key}; }
  bool isNull() const { return false; }
  template <typename T> bool is() const { return true; }
  template <typename T> T as() const {
    if constexpr (std::is_same_v<T, const char*>) {
      if (path == "/run_date") return fakeRadarRunDate.c_str();
      if (path == "/status") return fakeRadarPayloadStatus.c_str();
      if (path == "/detail") return fakeRadarDetail.c_str();
      return "Check radar pipeline.";
    } else if constexpr (std::is_floating_point_v<T>) {
      return static_cast<T>(28.0);
    } else {
      return static_cast<T>(0);
    }
  }
  const char* operator|(const char* fallback) const { return fallback; }
};
struct JsonDocument {
  JsonValue operator[](const char* key) const { return {std::string("/") + key}; }
};
struct DeserializationError {
  explicit operator bool() const { return false; }
  const char* c_str() const { return ""; }
};
inline DeserializationError deserializeJson(JsonDocument&, const String&) { return {}; }
