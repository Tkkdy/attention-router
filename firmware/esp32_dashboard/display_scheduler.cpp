// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: GPL-3.0-only
#include "display_scheduler.h"

#include "pages.h"
#include "runtime_config.h"

namespace {

constexpr unsigned long DISPLAY_MAX_COALESCE_MS = 10000UL;
constexpr unsigned long DISPLAY_RETRY_INITIAL_MS = 30000UL;
constexpr unsigned long DISPLAY_RETRY_MAX_MS = 300000UL;

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
  // An explicit manual redraw may bypass the automatic retry cooldown.
  consecutiveFailures_ = 0;
}

void DisplayScheduler::tick(unsigned long now) {
  if (!hasPendingScene_ || static_cast<int32_t>(now - renderDueAt_) < 0) {
    return;
  }
  // New data and urgency upgrades must not cause a tight failure/retry loop.
  if (consecutiveFailures_ &&
      static_cast<int32_t>(now - retryNotBefore_) < 0) {
    return;
  }

  Serial.print("Rendering ");
  Serial.println(pageName(pendingScene_.page));
  if (!renderPage(pendingScene_)) {
    // A failed refresh may have changed the physical panel partially. Even the
    // previous successful scene can no longer be assumed to be on the screen.
    hasRenderedScene_ = false;
    if (consecutiveFailures_ < 5) ++consecutiveFailures_;
    unsigned long retryDelay = DISPLAY_RETRY_INITIAL_MS << (consecutiveFailures_ - 1);
    if (retryDelay > DISPLAY_RETRY_MAX_MS) retryDelay = DISPLAY_RETRY_MAX_MS;
    // Measure from completion, since renderPage() can block for a BUSY timeout.
    retryNotBefore_ = millis() + retryDelay;
    renderDueAt_ = retryNotBefore_;
    Serial.print("Refresh failed; scene pending, retry in ");
    Serial.print(retryDelay);
    Serial.println(" ms");
    return;
  }
  renderedScene_ = pendingScene_;
  hasRenderedScene_ = true;
  hasPendingScene_ = false;
  consecutiveFailures_ = 0;
  Serial.println("Refresh complete");
}
