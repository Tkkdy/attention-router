// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Arduino.h>

#include "scene.h"

enum class HubMode : uint8_t {
  BootProbing,
  HubPrimary,
  HubGrace,
  Standalone,
  HubRecovering,
};

struct ConnectivityEvent {
  bool stateChanged = false;
  bool hubSceneUpdated = false;
  bool hubTookControl = false;

  bool sceneMayHaveChanged() const {
    return stateChanged || hubSceneUpdated || hubTookControl;
  }
};

class ConnectivityManager {
 public:
  void begin(unsigned long now);
  ConnectivityEvent tick(unsigned long now, bool networkReady,
                         HubSceneData& authoritativeScene);

  HubMode hubMode() const { return hubMode_; }
  Authority authority() const;
  LinkState hubState() const;
  LinkState internetState() const { return internetState_; }
  void setInternetState(LinkState state);

 private:
  bool hubPollDue(unsigned long now) const;
  void markAttempt(unsigned long now);
  void transitionTo(HubMode mode);

  HubMode hubMode_ = HubMode::BootProbing;
  LinkState internetState_ = LinkState::Unknown;
  HubSceneData recoveryCandidate_{};
  unsigned long lastHubAttemptAt_ = 0;
  unsigned long lastHubSuccessAt_ = 0;
  unsigned long recoveryStartedAt_ = 0;
  bool hasAttemptedHub_ = false;
  bool hasHubSuccess_ = false;
};

const char* hubModeName(HubMode mode);
