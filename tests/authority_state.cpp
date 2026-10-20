// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>

#include "../firmware/esp32_dashboard/connectivity_manager.h"
#include "../firmware/esp32_dashboard/hub_client.h"

FakeSerial Serial;
unsigned long fakeNow = 0;
HubSceneData incoming;
bool hubWorks = true;

bool isHubConfigured() { return true; }
HubFetchResult fetchHubScene(HubSceneData& scene) {
  if (!hubWorks) return {HubFetchStatus::ConnectionFailed, 0};
  scene = incoming;
  return {HubFetchStatus::Success, 200};
}

int main() {
  ConnectivityManager manager;
  HubSceneData owned;
  makeDefaultHubScene(owned);
  incoming = owned;
  incoming.version = 10;
  manager.begin(0);

  fakeNow = 0;
  manager.tick(fakeNow, true, owned);
  assert(manager.authority() == Authority::Hub && owned.version == 10);

  hubWorks = false;
  fakeNow = 30000;
  manager.tick(fakeNow, true, owned);
  assert(manager.hubMode() == HubMode::HubGrace);
  fakeNow = 89999;
  manager.tick(fakeNow, true, owned);
  assert(manager.authority() == Authority::Hub);
  fakeNow = 90000;
  manager.tick(fakeNow, true, owned);
  assert(manager.authority() == Authority::Standalone);

  hubWorks = true;
  incoming.version = 20;
  fakeNow = 120000;
  manager.tick(fakeNow, true, owned);
  assert(manager.hubMode() == HubMode::HubRecovering && owned.version == 10);
  fakeNow = 135000;
  manager.tick(fakeNow, true, owned);
  assert(owned.version == 10);

  hubWorks = false;
  fakeNow = 150000;
  manager.tick(fakeNow, true, owned);
  assert(manager.hubMode() == HubMode::Standalone);

  hubWorks = true;
  fakeNow = 180000;
  manager.tick(fakeNow, true, owned);
  fakeNow = 195000;
  manager.tick(fakeNow, true, owned);
  fakeNow = 210000;
  manager.tick(fakeNow, true, owned);
  assert(manager.authority() == Authority::Standalone && owned.version == 10);
  fakeNow = 225000;
  const auto event = manager.tick(fakeNow, true, owned);
  assert(event.hubTookControl);
  assert(manager.authority() == Authority::Hub && owned.version == 20);

  std::cout << "Authority state passed: 90s failover, 45s recovery, candidate isolation/reset\n";
}
