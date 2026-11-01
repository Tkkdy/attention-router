// SPDX-FileCopyrightText: 2026 flowersea123
// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>
#include "../firmware/esp32_dashboard/display_scheduler.h"
#include "../firmware/esp32_dashboard/pages.h"


TestSerial Serial;
uint32_t clockMs = 0, renderDuration = 0;
int calls = 0;
bool renderResult = false;
Scene attempted;
unsigned long millis() { return clockMs; }
bool renderPage(const Scene& scene) {
  ++calls; attempted = scene; clockMs += renderDuration; return renderResult;
}
const char* pageName(Page) { return "TEST"; }
void tick(DisplayScheduler& scheduler, uint32_t time) {
  clockMs = time; scheduler.tick(clockMs);
}
void reset() {
  clockMs = 0; calls = 0; renderDuration = 0; renderResult = false;
  Serial.output.clear();
}

int main() {
  Scene home, work;
  work.page = Page::Workspace;
  // The original bug: a failed first render must remain retryable, and an
  // urgent identical submission must not bypass cooldown after a long timeout.
  reset();
  DisplayScheduler first;
  first.submit(home, RefreshPriority::Urgent);
  renderDuration = 75000;
  first.tick(0);
  assert(calls == 1 && !first.hasRenderedScene());
  assert(Serial.output.find("Refresh complete") == std::string::npos);
  first.submit(home, RefreshPriority::Urgent);
  tick(first, 104999); assert(calls == 1);
  renderDuration = 0; renderResult = true;
  tick(first, 105000); assert(calls == 2 && first.hasRenderedScene());
  assert(Serial.output.find("Refresh complete") != std::string::npos);
  first.submit(home); tick(first, 200000); assert(calls == 2);

  // Latest content replaces a failed pending scene, without bypassing backoff.
  reset();
  DisplayScheduler replace;
  replace.force(home); replace.tick(clockMs);
  clockMs = 100; replace.submit(work, RefreshPriority::Urgent);
  tick(replace, 29999); assert(calls == 1);
  renderResult = true;
  tick(replace, 30000); assert(calls == 2 && attempted.page == Page::Workspace);

  // A later failed refresh invalidates the previous physical-screen assumption.
  reset(); renderResult = true;
  DisplayScheduler partial;
  partial.force(home); partial.tick(clockMs);
  renderResult = false;
  partial.force(work); partial.tick(clockMs);
  assert(!partial.hasRenderedScene());
  assert(partial.currentScene().page == Page::Workspace);
  partial.submit(home, RefreshPriority::Urgent);
  renderResult = true;
  tick(partial, 30000); assert(calls == 3 && attempted.page == Page::Home);

  // A manual request can explicitly retry before the automatic deadline.
  reset();
  DisplayScheduler manual;
  manual.force(work); manual.tick(clockMs);
  clockMs = 1; renderResult = true;
  manual.force(manual.currentScene()); manual.tick(clockMs);
  assert(calls == 2 && manual.hasRenderedScene());

  // Bounded backoff remains capped on persistent failure.
  reset();
  DisplayScheduler capped;
  capped.force(home); capped.tick(clockMs);
  const uint32_t waits[] = {30000, 60000, 120000, 240000, 300000, 300000};
  for (uint32_t wait : waits) {
    const auto completedAt = clockMs;
    const int before = calls;
    tick(capped, completedAt + wait - 1); assert(calls == before);
    tick(capped, completedAt + wait); assert(calls == before + 1);
  }

  // millis() wrapping must not trigger an immediate retry or lose the pending one.
  reset(); clockMs = 0xfffffff0U;
  DisplayScheduler wrap;
  wrap.force(home); wrap.tick(clockMs);
  tick(wrap, static_cast<uint32_t>(0xfffffff0U + 29999U)); assert(calls == 1);
  renderResult = true;
  tick(wrap, static_cast<uint32_t>(0xfffffff0U + 30000U)); assert(calls == 2);

  // Preserve normal coalescing, urgency upgrades, and cancellation behavior.
  reset(); renderResult = true;
  DisplayScheduler normal;
  normal.submit(home); tick(normal, 1999); assert(calls == 0);
  tick(normal, 2000); assert(calls == 1);
  clockMs = 2100; normal.submit(work);
  normal.submit(home); tick(normal, 5000); assert(calls == 1);
  normal.submit(work); normal.submit(work, RefreshPriority::Urgent);
  normal.tick(clockMs); assert(calls == 2);
  std::cout << "PASS: 7 scheduler regression scenarios\n";
}
