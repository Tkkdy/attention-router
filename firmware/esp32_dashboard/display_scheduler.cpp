// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "display_scheduler.h"

#include "pages.h"
#include "runtime_config.h"

namespace {

constexpr unsigned long DISPLAY_MAX_COALESCE_MS = 10000UL;

unsigned long earlierDeadline(unsigned long now, unsigned long first,
                              unsigned long second) {
  return static_cast<int32_t>(first - now) <= static_cast<int32_t>(second - now)
             ? first
             : second;
}

}  // namespace

void DisplayScheduler::submit(const Scene& scene, RefreshPriority priority) {
  const unsigned long now = millis();

  // The latest desired scene is already on the panel. Any queued intermediate
  // scene is obsolete and must be cancelled rather than rendered later.
  if (hasRenderedScene_ && scenesVisiblyEqual(renderedScene_, scene)) {
    if (hasPendingScene_) {
      hasPendingScene_ = false;
      Serial.println("Pending refresh cancelled; rendered scene is desired again");
    } else {
      Serial.println("Visible scene unchanged; skip E-Ink refresh");
    }
    return;
  }

  // Equal content still needs an urgency upgrade. This is important when an
  // alert becomes urgent while an identical normal refresh is coalescing.
  if (hasPendingScene_ && scenesVisiblyEqual(pendingScene_, scene)) {
    if (priority == RefreshPriority::Urgent &&
        static_cast<int32_t>(now - renderDueAt_) < 0) {
      renderDueAt_ = now;
    }
    return;
  }

  const bool replacingPending = hasPendingScene_;
  pendingScene_ = scene;
  hasPendingScene_ = true;
  if (!replacingPending) {
    pendingSince_ = now;
  }

  if (priority == RefreshPriority::Urgent) {
    renderDueAt_ = now;
    return;
  }

  const unsigned long coalesced = now + DISPLAY_COALESCE_MS;
  const unsigned long latest = pendingSince_ + DISPLAY_MAX_COALESCE_MS;
  renderDueAt_ = earlierDeadline(now, coalesced, latest);
}

void DisplayScheduler::force(const Scene& scene) {
  pendingScene_ = scene;
  hasPendingScene_ = true;
  pendingSince_ = millis();
  renderDueAt_ = pendingSince_;
}

void DisplayScheduler::tick(unsigned long now) {
  if (!hasPendingScene_ || static_cast<int32_t>(now - renderDueAt_) < 0) {
    return;
  }

  Serial.print("Rendering ");
  Serial.println(pageName(pendingScene_.page));
  renderPage(pendingScene_);
  renderedScene_ = pendingScene_;
  hasRenderedScene_ = true;
  hasPendingScene_ = false;
  Serial.println("Refresh complete");
}
