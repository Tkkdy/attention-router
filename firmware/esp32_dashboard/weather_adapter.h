// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

struct WeatherSample {
  bool available = false;
  int temperature = 0;
  char condition[SHORT_TEXT_LENGTH] = "UNKNOWN";
  unsigned long receivedAt = 0;
};

class WeatherAdapter {
 public:
  bool configured() const;
  void begin(unsigned long now);
  bool tick(unsigned long now, bool standalone, bool internetOnline,
            bool clockReady);
  const WeatherSample& sample() const { return sample_; }
  bool fresh(unsigned long now) const;

 private:
  WeatherSample sample_{};
  unsigned long lastAttemptAt_ = 0;
  uint8_t failures_ = 0;
  bool wasStandalone_ = false;
  bool wasInternetOnline_ = false;
  bool wasFresh_ = false;
  bool verified_ = false;
  bool hasAttempted_ = false;
  bool fetch(unsigned long now);
};
