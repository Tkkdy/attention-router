// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "connectivity_manager.h"

#include "hub_client.h"
#include "runtime_config.h"

namespace {

bool elapsed(unsigned long now, unsigned long since, unsigned long interval) {
  return static_cast<unsigned long>(now - since) >= interval;
}

}  // namespace

void ConnectivityManager::begin(unsigned long now) {
  hubMode_ = HubMode::BootProbing;
  internetState_ = LinkState::Unknown;
  lastHubAttemptAt_ = now;
  lastHubSuccessAt_ = now;
  recoveryStartedAt_ = now;
  hasAttemptedHub_ = false;
  hasHubSuccess_ = false;
  makeDefaultHubScene(recoveryCandidate_);
  Serial.print('[');
  Serial.print(now);
  Serial.println("] Hub mode: BOOT_PROBING");
}

ConnectivityEvent ConnectivityManager::tick(
    unsigned long now, bool networkReady, HubSceneData& authoritativeScene) {
  ConnectivityEvent event;

  if (hubMode_ == HubMode::HubGrace && hasHubSuccess_ &&
      elapsed(now, lastHubSuccessAt_, HUB_OFFLINE_TIMEOUT_MS)) {
    transitionTo(HubMode::Standalone);
    event.stateChanged = true;
  }

  if (!hubPollDue(now)) {
    return event;
  }
  markAttempt(now);

  HubSceneData received = hubMode_ == HubMode::HubRecovering
                              ? recoveryCandidate_
                              : authoritativeScene;
  HubFetchResult result;
  if (networkReady && isHubConfigured()) {
    result = fetchHubScene(received);
  } else {
    result.status = isHubConfigured() ? HubFetchStatus::ConnectionFailed
                                      : HubFetchStatus::NotConfigured;
  }

  if (result.ok()) {
    lastHubSuccessAt_ = now;
    hasHubSuccess_ = true;

    switch (hubMode_) {
      case HubMode::BootProbing:
      case HubMode::HubPrimary:
      case HubMode::HubGrace:
        authoritativeScene = received;
        event.hubSceneUpdated = true;
        if (hubMode_ != HubMode::HubPrimary) {
          transitionTo(HubMode::HubPrimary);
          event.stateChanged = true;
        }
        break;

      case HubMode::Standalone:
        recoveryCandidate_ = received;
        recoveryStartedAt_ = now;
        transitionTo(HubMode::HubRecovering);
        event.stateChanged = true;
        break;

      case HubMode::HubRecovering:
        recoveryCandidate_ = received;
        if (elapsed(now, recoveryStartedAt_, HUB_RECOVERY_STABLE_MS)) {
          authoritativeScene = recoveryCandidate_;
          transitionTo(HubMode::HubPrimary);
          event.stateChanged = true;
          event.hubSceneUpdated = true;
          event.hubTookControl = true;
          Serial.print('[');
          Serial.print(now);
          Serial.println("] Hub stable for 45 seconds; Hub scene took control");
        }
        break;
    }
    return event;
  }

  switch (hubMode_) {
    case HubMode::BootProbing:
      transitionTo(HubMode::Standalone);
      event.stateChanged = true;
      break;
    case HubMode::HubPrimary:
      transitionTo(HubMode::HubGrace);
      event.stateChanged = true;
      break;
    case HubMode::HubRecovering:
      transitionTo(HubMode::Standalone);
      event.stateChanged = true;
      Serial.print('[');
      Serial.print(now);
      Serial.println("] Hub recovery failed; stability timer reset");
      break;
    case HubMode::HubGrace:
    case HubMode::Standalone:
      break;
  }

  if (hubMode_ == HubMode::HubGrace && hasHubSuccess_ &&
      elapsed(now, lastHubSuccessAt_, HUB_OFFLINE_TIMEOUT_MS)) {
    transitionTo(HubMode::Standalone);
    event.stateChanged = true;
  }
  return event;
}

Authority ConnectivityManager::authority() const {
  switch (hubMode_) {
    case HubMode::BootProbing:
    case HubMode::Standalone:
    case HubMode::HubRecovering:
      return Authority::Standalone;
    case HubMode::HubPrimary:
    case HubMode::HubGrace:
      return Authority::Hub;
  }
  return Authority::Standalone;
}

LinkState ConnectivityManager::hubState() const {
  switch (hubMode_) {
    case HubMode::BootProbing: return LinkState::Unknown;
    case HubMode::HubPrimary: return LinkState::Online;
    case HubMode::HubGrace: return LinkState::Unknown;
    case HubMode::Standalone:
    case HubMode::HubRecovering: return LinkState::Offline;
  }
  return LinkState::Unknown;
}

void ConnectivityManager::setInternetState(LinkState state) {
  if (internetState_ == state) {
    return;
  }
  internetState_ = state;
  Serial.print('[');
  Serial.print(millis());
  Serial.print("] Internet state: ");
  Serial.println(linkStateText(state));
}

bool ConnectivityManager::hubPollDue(unsigned long now) const {
  if (!hasAttemptedHub_) {
    return true;
  }
  const unsigned long interval = hubMode_ == HubMode::HubRecovering
                                     ? HUB_RECOVERY_POLL_INTERVAL_MS
                                     : HUB_POLL_INTERVAL_MS;
  return elapsed(now, lastHubAttemptAt_, interval);
}

void ConnectivityManager::markAttempt(unsigned long now) {
  hasAttemptedHub_ = true;
  lastHubAttemptAt_ = now;
}

void ConnectivityManager::transitionTo(HubMode mode) {
  if (hubMode_ == mode) {
    return;
  }
  hubMode_ = mode;
  Serial.print('[');
  Serial.print(millis());
  Serial.print("] Hub mode: ");
  Serial.println(hubModeName(mode));
}

const char* hubModeName(HubMode mode) {
  switch (mode) {
    case HubMode::BootProbing: return "BOOT_PROBING";
    case HubMode::HubPrimary: return "HUB_PRIMARY";
    case HubMode::HubGrace: return "HUB_GRACE";
    case HubMode::Standalone: return "STANDALONE";
    case HubMode::HubRecovering: return "HUB_RECOVERING";
  }
  return "UNKNOWN";
}
