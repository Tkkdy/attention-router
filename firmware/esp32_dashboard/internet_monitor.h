// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Arduino.h>

#include "scene.h"

class InternetMonitor {
 public:
  void begin(unsigned long now);
  bool tick(unsigned long now, bool networkReady);

  LinkState state() const { return state_; }

 private:
  void setState(LinkState state);

  LinkState state_ = LinkState::Unknown;
  unsigned long lastProbeAt_ = 0;
  bool hasProbed_ = false;
  uint8_t consecutiveFailures_ = 0;
};
