// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "../firmware/esp32_dashboard/display_scheduler.h"
#include "../firmware/esp32_dashboard/pages.h"
#include "../firmware/esp32_dashboard/scene.h"

FakeSerial Serial;
unsigned long fakeNow = 0;
std::vector<std::string> drawCalls;
int hardwareRefreshes = 0;

std::vector<std::string> drawing(const Scene& scene) {
  drawCalls.clear();
  renderPage(scene);
  return drawCalls;
}

void assertInvisibleMutation(const Scene& first, const Scene& second) {
  assert(drawing(first) == drawing(second));
  assert(scenesVisiblyEqual(first, second));
  assert(!scenesPersistentlyEqual(first, second));
}

int main() {
  Scene a;
  a.stale = false;
  a.todoCount = 1;
  strlcpy(a.todos[0].id, "one", sizeof(a.todos[0].id));
  strlcpy(a.todos[0].title, "Task", sizeof(a.todos[0].title));

  Scene bitmap = a;
  bitmap.utf8.present[0] = true;
  bitmap.utf8.pixels[0][0] = 0x80;
  Scene sameBitmap = bitmap;
  strlcpy(sameBitmap.todos[0].title, "Hidden ASCII fallback", sizeof(sameBitmap.todos[0].title));
  assert(drawing(bitmap) == drawing(sameBitmap));
  assert(scenesVisiblyEqual(bitmap, sameBitmap));
  sameBitmap.utf8.pixels[0][0] = 0x40;
  assert(drawing(bitmap) != drawing(sameBitmap));
  assert(!scenesVisiblyEqual(bitmap, sameBitmap));

  Scene b = a;
  strlcpy(b.context, "IDLE", sizeof(b.context));
  assertInvisibleMutation(a, b);

  b = a;
  strlcpy(b.todos[0].id, "two", sizeof(b.todos[0].id));
  assertInvisibleMutation(a, b);

  a.page = Page::Workspace;
  b = a;
  strlcpy(b.context, "IDLE", sizeof(b.context));
  assertInvisibleMutation(a, b);
  b = a;
  b.temperature = 100;
  assertInvisibleMutation(a, b);

  a.page = Page::Interrupt;
  b = a;
  b.quota5hRemaining = 50;
  assertInvisibleMutation(a, b);
  b = a;
  b.todoCount = 0;
  assertInvisibleMutation(a, b);
  b = a;
  strlcpy(b.interruptMessage, "OTHER", sizeof(b.interruptMessage));
  assert(drawing(a) != drawing(b));
  assert(!scenesVisiblyEqual(a, b));

  // A -> pending B -> A must cancel the obsolete B rather than redraw A.
  fakeNow = 0;
  hardwareRefreshes = 0;
  DisplayScheduler scheduler;
  a = Scene{};
  a.stale = false;
  a.page = Page::Workspace;
  a.quota5hRemaining = 70;
  a.details.showFiveHour = true;
  scheduler.force(a);
  scheduler.tick(fakeNow);
  assert(hardwareRefreshes == 1);
  fakeNow = 100;
  b = a;
  b.quota5hRemaining = 60;
  scheduler.submit(b);
  fakeNow = 200;
  scheduler.submit(a);
  fakeNow = 2200;
  scheduler.tick(fakeNow);
  assert(hardwareRefreshes == 1);

  // Equal urgent content must promote the already-pending normal refresh.
  fakeNow = 0;
  hardwareRefreshes = 0;
  DisplayScheduler urgent;
  urgent.force(a);
  urgent.tick(fakeNow);
  assert(hardwareRefreshes == 1);
  fakeNow = 100;
  urgent.submit(b, RefreshPriority::Normal);
  fakeNow = 200;
  urgent.submit(b, RefreshPriority::Urgent);
  urgent.tick(fakeNow);
  assert(hardwareRefreshes == 2);

  // The generated WAITING FOR YOU message must be fitted below size 5.
  Scene interrupt;
  interrupt.page = Page::Interrupt;
  interrupt.stale = false;
  strlcpy(interrupt.interruptTitle, "CODEX", sizeof(interrupt.interruptTitle));
  strlcpy(interrupt.interruptMessage, "WAITING FOR YOU", sizeof(interrupt.interruptMessage));
  strlcpy(interrupt.interruptDetail, "dashboard", sizeof(interrupt.interruptDetail));
  const auto calls = drawing(interrupt);
  size_t messageIndex = calls.size();
  for (size_t index = 0; index < calls.size(); ++index) {
    if (calls[index] == "print:WAITING FOR YOU") {
      messageIndex = index;
      break;
    }
  }
  assert(messageIndex < calls.size());
  bool fittedCursorSeen = false;
  for (size_t index = messageIndex; index-- > 0;) {
    if (calls[index].rfind("setCursor:", 0) == 0) {
      fittedCursorSeen = calls[index] == "setCursor:20:176";
      break;
    }
  }
  assert(fittedCursorSeen);

  Scene unknown;
  unknown.page = Page::Workspace;
  const auto unknownCalls = drawing(unknown);
  bool sawUnknown = false;
  for (const auto& call : unknownCalls) if (call == "print:UNKNOWN") sawUnknown = true;
  assert(sawUnknown);

  Scene detail = unknown;
  strlcpy(detail.details.project, "Attention Router", sizeof(detail.details.project));
  strlcpy(detail.details.currentItem, "Review", sizeof(detail.details.currentItem));
  strlcpy(detail.details.suggestion, "An independent suggestion", sizeof(detail.details.suggestion));
  detail.details.todoRemaining = 2;
  detail.details.simulated = true;
  const auto details = drawing(detail);
  for (const auto* value : {"print:Attention Router", "print:Review", "print:An independent suggestion", "print:SIMULATED", "print:+2 MORE IN HUB"}) {
    bool found = false;
    for (const auto& call : details) if (call == value) found = true;
    assert(found);
  }
  assert(!scenesVisiblyEqual(unknown, detail));
  Scene hiddenRadar = detail;
  hiddenRadar.radarStatus = RadarStatus::Failed;
  assertInvisibleMutation(detail, hiddenRadar);
  Scene hiddenQuota = detail;
  hiddenQuota.quota5hRemaining = 1;
  assertInvisibleMutation(detail, hiddenQuota);
  for (const auto& call : drawing(hiddenQuota)) assert(call.find("CODEX 5H") == std::string::npos);
  hiddenQuota.details.showFiveHour = true;
  assert(!scenesVisiblyEqual(detail, hiddenQuota));

  Scene tibo;
  tibo.page = Page::Tibo;
  tibo.stale = false;
  tibo.tibo.p24 = 12;
  tibo.tibo.p48 = 24;
  tibo.tibo.p72 = 38;
  strlcpy(tibo.tibo.status, "FRESH", sizeof(tibo.tibo.status));
  strlcpy(tibo.tibo.forecastStatus, "FRESH", sizeof(tibo.tibo.forecastStatus));
  bool sawTibo = false, sawChance = false;
  for (const auto& call : drawing(tibo)) {
    if (call == "print:TIBO RESET WATCH") sawTibo = true;
    if (call == "print:12%") sawChance = true;
  }
  assert(sawTibo && sawChance);
  Scene other = tibo;
  other.temperature = 31;
  assert(scenesVisiblyEqual(tibo, other));
  other.tibo.p24 = -1;
  assert(!scenesVisiblyEqual(tibo, other));
  Scene originalHome;
  other = originalHome;
  other.tibo.p24 = 90;
  assert(scenesVisiblyEqual(originalHome, other));
  assert(scenesPersistentlyEqual(originalHome, other));  // Runtime-only Tibo is not in NVS.

  std::cout << "Display contract passed: page projection, persistence equality, scheduler reversion/urgency, fitted interrupt text\n";
}
