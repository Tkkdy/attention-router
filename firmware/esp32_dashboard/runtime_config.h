// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Arduino.h>

constexpr unsigned long HUB_POLL_INTERVAL_MS = 30000UL;
constexpr unsigned long HUB_OFFLINE_TIMEOUT_MS = 90000UL;
constexpr unsigned long HUB_RECOVERY_POLL_INTERVAL_MS = 15000UL;
constexpr unsigned long HUB_RECOVERY_STABLE_MS = 45000UL;
constexpr unsigned long DISPLAY_COALESCE_MS = 2000UL;
constexpr unsigned long INTERNET_PROBE_INTERVAL_MS = 60000UL;
constexpr unsigned long NTP_CHECK_INTERVAL_MS = 60000UL;
