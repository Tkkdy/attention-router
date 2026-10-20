// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

struct RuntimeState {
  Authority authority = Authority::Standalone;
  LinkState hubState = LinkState::Unknown;
  LinkState internetState = LinkState::Unknown;
  bool hasStandaloneDate = false;
  bool standaloneDateVerified = false;
  char standaloneDate[SHORT_TEXT_LENGTH]{};
  bool weatherEnabled = false;
  bool hasStandaloneWeather = false;
  bool standaloneWeatherFresh = false;
  int standaloneTemperature = 0;
  char standaloneCondition[SHORT_TEXT_LENGTH]{};
  RadarStatus standaloneRadarStatus = RadarStatus::Unknown;
  bool standaloneRadarVerified = false;
  char standaloneRadarDetail[LONG_TEXT_LENGTH]{};
  char standaloneRadarDate[SHORT_TEXT_LENGTH] = "UNKNOWN";
};

Scene composeScene(const HubSceneData& hubScene, const RuntimeState& runtime);
