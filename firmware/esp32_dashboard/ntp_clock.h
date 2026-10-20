// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Arduino.h>

class NtpClock {
 public:
  void begin(unsigned long now);
  bool tick(unsigned long now, bool internetAvailable);

  bool hasLocalDate() const { return hasLocalDate_; }
  const char* localDate() const { return localDate_; }

 private:
  bool updateLocalDate();

  bool configured_ = false;
  bool wasInternetAvailable_ = false;
  bool hasLocalDate_ = false;
  unsigned long lastCheckAt_ = 0;
  char localDate_[24]{};
};
