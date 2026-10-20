// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "radar_adapter.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <string.h>
#include <time.h>

#if __has_include("private_config.h")
#include "private_config.h"
#endif
#include "weather_ca.h"

#ifndef DASHBOARD_RADAR_URL
#define DASHBOARD_RADAR_URL ""
#endif

namespace {

constexpr unsigned long RADAR_POLL_INTERVAL_MS = 5UL * 60UL * 1000UL;

bool elapsed(unsigned long now, unsigned long since, unsigned long interval) {
  return static_cast<unsigned long>(now - since) >= interval;
}

bool singaporeDate(char (&date)[11]) {
  const time_t now = time(nullptr);
  if (now < 1704067200) return false;
  const time_t singaporeNow = now + 8 * 60 * 60;
  tm calendar{};
  if (gmtime_r(&singaporeNow, &calendar) == nullptr) return false;
  return strftime(date, sizeof(date), "%Y-%m-%d", &calendar) == 10;
}

}  // namespace

void RadarAdapter::begin(unsigned long now) {
  sample_ = RadarSample{};
  lastAttemptAt_ = now;
  hasAttempted_ = false;
  wasStandalone_ = false;
  wasInternetOnline_ = false;
  verified_ = false;
}

bool RadarAdapter::tick(unsigned long now, bool standalone, bool internetOnline,
                        bool clockReady) {
  const bool enteredStandalone = standalone && !wasStandalone_;
  const bool internetRecovered = internetOnline && !wasInternetOnline_;
  wasStandalone_ = standalone;
  wasInternetOnline_ = internetOnline;
  const bool verificationLost = verified_ && !internetOnline;
  if (!internetOnline) verified_ = false;
  if (!clockReady) return false;

  char today[11]{};
  if (!singaporeDate(today)) return false;
  bool changed = verificationLost;
  if (sample_.status != RadarStatus::Unknown &&
      strcmp(sample_.runDate, today) != 0) {
    sample_ = RadarSample{};
    verified_ = false;
    changed = true;
  }

  if (!standalone || !internetOnline || DASHBOARD_RADAR_URL[0] == '\0') {
    return changed;
  }
  if (!hasAttempted_ || elapsed(now, lastAttemptAt_, RADAR_POLL_INTERVAL_MS) ||
      ((enteredStandalone || internetRecovered) && !verified_)) {
    lastAttemptAt_ = now;
    hasAttempted_ = true;
    changed = fetch(today) || changed;
  }
  return changed;
}

bool RadarAdapter::fetch(const char* today) {
  WiFiClientSecure client;
  client.setCACert(WEATHER_ROOT_CA);  // GitHub Pages chains to ISRG Root X1.
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(8000);
  String requestUrl = DASHBOARD_RADAR_URL;
  requestUrl += strchr(DASHBOARD_RADAR_URL, '?') == nullptr ? "?poll=" : "&poll=";
  requestUrl += String(static_cast<unsigned long>(time(nullptr) / 300));
  if (!http.begin(client, requestUrl)) {
    Serial.println("Radar request could not start");
    return false;
  }
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.print("Radar HTTP: ");
    Serial.println(code);
    http.end();
    return false;
  }
  const String payload = http.getString();
  http.end();
  JsonDocument document;
  const DeserializationError error = deserializeJson(document, payload);
  if (error) {
    Serial.print("Radar JSON error: ");
    Serial.println(error.c_str());
    return false;
  }
  if (!document["run_date"].is<const char*>() ||
      !document["status"].is<const char*>()) {
    Serial.println("Radar result is missing or mis-typed run_date/status");
    return false;
  }
  const char* runDate = document["run_date"].as<const char*>();
  const char* statusText = document["status"].as<const char*>();
  const char* detail = "Check radar pipeline.";
  if (!document["detail"].isNull()) {
    if (!document["detail"].is<const char*>()) {
      Serial.println("Radar detail must be a string");
      return false;
    }
    detail = document["detail"].as<const char*>();
    if (detail == nullptr) {
      Serial.println("Radar detail conversion failed");
      return false;
    }
  }
  if (strlen(runDate) != 10) {
    Serial.print("Radar run_date has invalid length: ");
    Serial.println(runDate);
    return false;
  }
  if (strcmp(runDate, today) != 0) {
    Serial.print("Radar date mismatch; expected ");
    Serial.print(today);
    Serial.print(", received ");
    Serial.println(runDate);
    return false;
  }
  RadarStatus status = RadarStatus::Unknown;
  if (strcmp(statusText, "SUCCESS") == 0) {
    status = RadarStatus::Success;
  } else if (strcmp(statusText, "FAILED") == 0) {
    status = RadarStatus::Failed;
  } else {
    Serial.println("Radar result has unsupported status");
    return false;
  }
  const bool changed = !verified_ || sample_.status != status ||
      strcmp(sample_.runDate, runDate) != 0 ||
      strcmp(sample_.detail, detail) != 0;
  verified_ = true;
  sample_.status = status;
  strlcpy(sample_.runDate, runDate, sizeof(sample_.runDate));
  strlcpy(sample_.detail, detail, sizeof(sample_.detail));
  if (!changed) {
    return false;
  }
  Serial.print("Radar updated: ");
  Serial.print(runDate);
  Serial.print(" ");
  Serial.println(statusText);
  return true;
}
