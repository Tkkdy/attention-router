// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

struct RadarSample {
  RadarStatus status = RadarStatus::Unknown;
  char runDate[11]{};
  char detail[LONG_TEXT_LENGTH]{};
};

class RadarAdapter {
 public:
  void begin(unsigned long now);
  bool tick(unsigned long now, bool standalone, bool internetOnline,
            bool clockReady);
  const RadarSample& sample() const { return sample_; }
  bool verified() const { return verified_; }

 private:
  bool fetch(const char* today);

  RadarSample sample_{};
  unsigned long lastAttemptAt_ = 0;
  bool hasAttempted_ = false;
  bool wasStandalone_ = false;
  bool wasInternetOnline_ = false;
  bool verified_ = false;
};
