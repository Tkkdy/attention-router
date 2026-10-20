// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

enum class HubFetchStatus : uint8_t {
  Success,
  NotConfigured,
  ConnectionFailed,
  HttpError,
  InvalidPayload,
};

struct HubFetchResult {
  HubFetchStatus status = HubFetchStatus::ConnectionFailed;
  int httpStatus = 0;

  bool ok() const { return status == HubFetchStatus::Success; }
};

bool parseHubScenePayload(const String& payload, HubSceneData& scene);
bool isHubConfigured();
HubFetchResult fetchHubScene(HubSceneData& scene);
