// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "weather_adapter.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <math.h>

#if __has_include("private_config.h")
#include "private_config.h"
#endif
#include "weather_ca.h"

#ifndef DASHBOARD_WEATHER_LATITUDE
#define DASHBOARD_WEATHER_LATITUDE ""
#endif
#ifndef DASHBOARD_WEATHER_LONGITUDE
#define DASHBOARD_WEATHER_LONGITUDE ""
#endif

bool WeatherAdapter::configured() const {
  return DASHBOARD_WEATHER_LATITUDE[0] != '\0' && DASHBOARD_WEATHER_LONGITUDE[0] != '\0';
}

namespace {

constexpr unsigned long RETRY_MS[] = {60000UL, 300000UL, 900000UL, 1800000UL};
constexpr unsigned long WEATHER_REFRESH_INTERVAL_MS = 2UL * 60UL * 60UL * 1000UL;
constexpr unsigned long WEATHER_MAX_AGE_MS = 4UL * 60UL * 60UL * 1000UL;

bool elapsed(unsigned long now, unsigned long since, unsigned long interval) {
  return static_cast<unsigned long>(now - since) >= interval;
}

const char* conditionForCode(int code) {
  if (code >= 0 && code <= 1) return "CLEAR";
  if (code >= 2 && code <= 3) return "CLOUDY";
  if (code == 45 || code == 48) return "FOG";
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return "RAIN";
  if ((code >= 71 && code <= 77) || code == 85 || code == 86) return "SNOW";
  if (code >= 95 && code <= 99) return "STORM";
  return nullptr;
}

}  // namespace

void WeatherAdapter::begin(unsigned long now) {
  sample_ = WeatherSample{};
  lastAttemptAt_ = now;
  failures_ = 0;
  wasStandalone_ = false;
  wasInternetOnline_ = false;
  wasFresh_ = false;
  verified_ = false;
  hasAttempted_ = false;
}

bool WeatherAdapter::fresh(unsigned long now) const {
  return sample_.available && verified_ &&
         !elapsed(now, sample_.receivedAt, WEATHER_MAX_AGE_MS + 1UL);
}

bool WeatherAdapter::tick(unsigned long now, bool standalone,
                          bool internetOnline, bool clockReady) {
  const bool enteredStandalone = standalone && !wasStandalone_;
  const bool internetRecovered = internetOnline && !wasInternetOnline_;
  wasStandalone_ = standalone;
  wasInternetOnline_ = internetOnline;
  if (!internetOnline) verified_ = false;
  bool changed = false;
  if (!standalone) {
    failures_ = 0;  // Hub owns the page; cancel any pending native retry.
  }

  if (standalone && internetOnline && clockReady &&
      DASHBOARD_WEATHER_LATITUDE[0] != '\0' &&
      DASHBOARD_WEATHER_LONGITUDE[0] != '\0') {
    const bool missingOrDue = !sample_.available || !verified_ ||
        elapsed(now, sample_.receivedAt, WEATHER_REFRESH_INTERVAL_MS);
    const bool due = !hasAttempted_ ||
        (failures_ == 0 && missingOrDue) ||
        (enteredStandalone && missingOrDue) ||
        (internetRecovered && missingOrDue) ||
        (failures_ != 0 && elapsed(now, lastAttemptAt_,
             RETRY_MS[(failures_ - 1U) < 4U ? failures_ - 1U : 3U]));
    if (due) {
      lastAttemptAt_ = now;
      hasAttempted_ = true;
      if (fetch(now)) {
        failures_ = 0;
        changed = true;
      } else {
        if (failures_ < 4) ++failures_;
      }
    }
  }

  const bool freshNow = fresh(now);
  changed = changed || freshNow != wasFresh_;
  wasFresh_ = freshNow;
  return changed;
}

bool WeatherAdapter::fetch(unsigned long now) {
  const String url = String("https://api.open-meteo.com/v1/forecast?latitude=") +
      DASHBOARD_WEATHER_LATITUDE + "&longitude=" +
      DASHBOARD_WEATHER_LONGITUDE +
      "&current=temperature_2m,weather_code&temperature_unit=celsius&timezone=auto";

  WiFiClientSecure client;
  client.setCACert(WEATHER_ROOT_CA);
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(8000);
  if (!http.begin(client, url)) {
    Serial.println("Weather request could not start");
    return false;
  }
  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    Serial.print("Weather HTTP: ");
    Serial.println(status);
    http.end();
    return false;
  }

  JsonDocument document;
  // HTTPClient decodes chunked responses in getString(); its raw stream does not.
  const String payload = http.getString();
  http.end();
  const DeserializationError error = deserializeJson(document, payload);
  if (error) {
    Serial.print("Weather JSON error: ");
    Serial.println(error.c_str());
    return false;
  }
  if (!document["current"]["temperature_2m"].is<float>() ||
      !document["current"]["weather_code"].is<int>()) {
    Serial.println("Weather JSON missing current values");
    return false;
  }
  const float temperature = document["current"]["temperature_2m"].as<float>();
  const int code = document["current"]["weather_code"].as<int>();
  const char* condition = conditionForCode(code);
  if (!isfinite(temperature) || temperature < -100.0f ||
      temperature > 100.0f || condition == nullptr) {
    Serial.println("Weather values out of range");
    return false;
  }

  sample_.temperature = static_cast<int>(lroundf(temperature));
  strlcpy(sample_.condition, condition, sizeof(sample_.condition));
  sample_.receivedAt = now;
  sample_.available = true;
  verified_ = true;
  Serial.print("Weather updated: ");
  Serial.print(sample_.temperature);
  Serial.print(" C ");
  Serial.println(sample_.condition);
  return true;
}
