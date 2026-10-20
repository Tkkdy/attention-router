// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "internet_monitor.h"

#include <HTTPClient.h>

#if __has_include("private_config.h")
#include "private_config.h"
#endif
#include "runtime_config.h"

#ifndef DASHBOARD_INTERNET_CHECK_URL
#define DASHBOARD_INTERNET_CHECK_URL ""
#endif
#ifndef DASHBOARD_INTERNET_CHECK_STATUS
#define DASHBOARD_INTERNET_CHECK_STATUS 0
#endif
#ifndef DASHBOARD_INTERNET_CHECK_LOCATION
#define DASHBOARD_INTERNET_CHECK_LOCATION ""
#endif

namespace {

bool elapsed(unsigned long now, unsigned long since, unsigned long interval) {
  return static_cast<unsigned long>(now - since) >= interval;
}

}  // namespace

void InternetMonitor::begin(unsigned long now) {
  state_ = LinkState::Unknown;
  lastProbeAt_ = now;
  hasProbed_ = false;
  consecutiveFailures_ = 0;
}

bool InternetMonitor::tick(unsigned long now, bool networkReady) {
  if (!networkReady || DASHBOARD_INTERNET_CHECK_URL[0] == '\0') {
    const LinkState previous = state_;
    hasProbed_ = false;
    consecutiveFailures_ = 0;
    setState(DASHBOARD_INTERNET_CHECK_URL[0] == '\0' ? LinkState::Unknown : LinkState::Offline);
    return previous != state_;
  }
  if (hasProbed_ && !elapsed(now, lastProbeAt_, INTERNET_PROBE_INTERVAL_MS)) {
    return false;
  }

  hasProbed_ = true;
  lastProbeAt_ = now;
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(5000);
  const char* responseHeaders[] = {"Location"};
  http.collectHeaders(responseHeaders, 1);
  const bool opened = http.begin(DASHBOARD_INTERNET_CHECK_URL);
  const int statusCode = opened ? http.GET() : 0;
  const String redirectLocation = opened ? http.header("Location") : String();
  if (opened) {
    http.end();
  }
  Serial.print("Internet probe HTTP: ");
  Serial.println(statusCode);
  if (statusCode < 0) {
    Serial.print("Internet probe error: ");
    Serial.println(http.errorToString(statusCode));
  }

  const LinkState previous = state_;
  if (statusCode == DASHBOARD_INTERNET_CHECK_STATUS &&
      redirectLocation == DASHBOARD_INTERNET_CHECK_LOCATION) {
    consecutiveFailures_ = 0;
    setState(LinkState::Online);
  } else {
    if (consecutiveFailures_ < 3) {
      ++consecutiveFailures_;
    }
    if (consecutiveFailures_ >= 3) {
      setState(LinkState::Offline);
    }
  }
  return previous != state_;
}

void InternetMonitor::setState(LinkState state) {
  if (state_ == state) {
    return;
  }
  state_ = state;
  Serial.print('[');
  Serial.print(millis());
  Serial.print("] Internet probe: ");
  Serial.println(linkStateText(state_));
}
