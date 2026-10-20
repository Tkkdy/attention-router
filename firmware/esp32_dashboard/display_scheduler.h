// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

enum class RefreshPriority : uint8_t {
  Normal,
  Urgent,
};

class DisplayScheduler {
 public:
  void submit(const Scene& scene, RefreshPriority priority = RefreshPriority::Normal);
  void force(const Scene& scene);
  void tick(unsigned long now);

  const Scene& currentScene() const { return renderedScene_; }
  bool hasRenderedScene() const { return hasRenderedScene_; }

 private:
  Scene pendingScene_{};
  Scene renderedScene_{};
  unsigned long renderDueAt_ = 0;
  unsigned long pendingSince_ = 0;
  bool hasPendingScene_ = false;
  bool hasRenderedScene_ = false;
};
