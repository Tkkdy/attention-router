// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include <Network.h>
#include <WiFi.h>

#include "wifi_manager.h"

#if __has_include("private_config.h")
#include "private_config.h"
#endif

namespace {

// Set these through build flags or a private local header later. Empty defaults
// keep this public repository free of credentials and preserve offline HOME.
#ifndef DASHBOARD_WIFI_SSID
#define DASHBOARD_WIFI_SSID ""
#endif

#ifndef DASHBOARD_WIFI_PASSWORD
#define DASHBOARD_WIFI_PASSWORD ""
#endif

constexpr char WIFI_SSID[] = DASHBOARD_WIFI_SSID;
constexpr char WIFI_PASSWORD[] = DASHBOARD_WIFI_PASSWORD;
constexpr unsigned long RETRY_INTERVAL_MS = 10000;
unsigned long lastAttemptAt = 0;
bool connectionReported = false;
int lastReportedStatus = -1;

}  // namespace

bool isNetworkConfigured() {
  return WIFI_SSID[0] != '\0';
}

bool beginNetwork() {
  if (!isNetworkConfigured()) {
    Serial.println("Wi-Fi not configured; keeping static HOME page");
    return false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastAttemptAt = millis();
  Serial.println("Connecting to configured Wi-Fi");
  return true;
}

bool ensureNetwork() {
  if (!isNetworkConfigured()) {
    return false;
  }
  const wl_status_t status = WiFi.status();
  if (static_cast<int>(status) != lastReportedStatus) {
    Serial.print("Wi-Fi status: ");
    Serial.println(static_cast<int>(status));
    lastReportedStatus = static_cast<int>(status);
  }
  if (status == WL_CONNECTED) {
    if (!connectionReported) {
      Serial.print("Wi-Fi connected, IP: ");
      Serial.println(WiFi.localIP());
      connectionReported = true;
    }
    return true;
  }

  connectionReported = false;
  if (status == WL_IDLE_STATUS) {
    return false;
  }

  if (millis() - lastAttemptAt >= RETRY_INTERVAL_MS) {
    WiFi.reconnect();
    lastAttemptAt = millis();
    Serial.print("Retrying Wi-Fi connection, status: ");
    Serial.println(static_cast<int>(status));
  }
  return false;
}
