// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "ntp_clock.h"

#include <ctype.h>
#include <time.h>
#include <string.h>

#if __has_include("private_config.h")
#include "private_config.h"
#endif
#include "runtime_config.h"

#ifndef DASHBOARD_TIMEZONE
#define DASHBOARD_TIMEZONE ""
#endif
#ifndef DASHBOARD_NTP_SERVER_1
#define DASHBOARD_NTP_SERVER_1 ""
#endif
#ifndef DASHBOARD_NTP_SERVER_2
#define DASHBOARD_NTP_SERVER_2 ""
#endif

namespace {

bool elapsed(unsigned long now, unsigned long since, unsigned long interval) {
  return static_cast<unsigned long>(now - since) >= interval;
}

}  // namespace

void NtpClock::begin(unsigned long now) {
  configured_ = false;
  wasInternetAvailable_ = false;
  hasLocalDate_ = false;
  lastCheckAt_ = now;
  localDate_[0] = '\0';
}

bool NtpClock::tick(unsigned long now, bool internetAvailable) {
  if (DASHBOARD_TIMEZONE[0] == '\0' || DASHBOARD_NTP_SERVER_1[0] == '\0' ||
      DASHBOARD_NTP_SERVER_2[0] == '\0') {
    return false;
  }
  const bool internetRecovered = internetAvailable && !wasInternetAvailable_;
  wasInternetAvailable_ = internetAvailable;
  if (!internetRecovered && !elapsed(now, lastCheckAt_, NTP_CHECK_INTERVAL_MS)) {
    return false;
  }
  lastCheckAt_ = now;
  if (internetAvailable && (!configured_ || internetRecovered)) {
    configTzTime(DASHBOARD_TIMEZONE, DASHBOARD_NTP_SERVER_1,
                 DASHBOARD_NTP_SERVER_2);
    configured_ = true;
    Serial.println("SNTP sync started");
  }
  if (!configured_) {
    return false;
  }
  return updateLocalDate();
}

bool NtpClock::updateLocalDate() {
  tm localTime{};
  if (!getLocalTime(&localTime, 10) || localTime.tm_year + 1900 < 2024) {
    return false;
  }

  char formatted[sizeof(localDate_)];
  if (strftime(formatted, sizeof(formatted), "%b %d  *  %a", &localTime) == 0) {
    return false;
  }
  for (char* character = formatted; *character != '\0'; ++character) {
    *character = static_cast<char>(toupper(static_cast<unsigned char>(*character)));
  }
  if (hasLocalDate_ && strcmp(localDate_, formatted) == 0) {
    return false;
  }

  strlcpy(localDate_, formatted, sizeof(localDate_));
  hasLocalDate_ = true;
  Serial.print("SNTP date: ");
  Serial.println(localDate_);
  return true;
}
