// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <iostream>
#include <unordered_map>
#include <vector>
#include "../firmware/esp32_dashboard/internet_monitor.h"
#include "../firmware/esp32_dashboard/scene_composer.h"
#include "../firmware/esp32_dashboard/scene_cache.h"
FakeSerial Serial; unsigned long fakeNow = 0;
int probeCalls = 0, probeStatus = 503;
std::unordered_map<std::string, std::vector<unsigned char>> fakeNvs;
int fakeNvsWrites = 0;
int main() {
 InternetMonitor probe; probe.begin(0); probe.tick(0,true);
#ifdef TEST_ENABLED_PROBE
 probe.tick(60000,true);probe.tick(120000,true);
 assert(probe.state()==LinkState::Offline && probeCalls==3);
 probeStatus=204;probe.tick(180000,true);
 assert(probe.state()==LinkState::Online);
 probe.tick(180001,false);assert(probe.state()==LinkState::Offline);
#else
 assert(probe.state()==LinkState::Unknown && probeCalls==0);
 probe.tick(1,false);assert(probe.state()==LinkState::Unknown);
#endif
 HubSceneData hub;makeDefaultHubScene(hub);hub.stale=false;
 RuntimeState r;r.authority=Authority::Hub;r.hubState=LinkState::Online;
 for (Page page : {Page::Home,Page::Workspace,Page::Interrupt}) {
  hub.page=page;
  for (LinkState wan : {LinkState::Unknown,LinkState::Offline}) {
   r.internetState=wan;const Scene scene=composeScene(hub,r);assert(!scene.stale);
   if (!scene.stale) saveLastSceneIfChanged(scene); // Same gate as submitComposedScene.
   Scene loaded;assert(loadLastScene(loaded));assert(loaded.page==page);
  }
 }
 hub.page=Page::Home;r.weatherEnabled=true;
 assert(composeScene(hub,r).stale); // Enabled weather failure remains visible.
 r.standaloneWeatherFresh=true;assert(!composeScene(hub,r).stale);
 hub.stale=true;assert(composeScene(hub,r).stale);hub.stale=false;
 r.hubState=LinkState::Offline;assert(composeScene(hub,r).stale);
 r.authority=Authority::Standalone;const Scene lost=composeScene(hub,r);
 assert(lost.stale && lost.page==Page::Home);
 r.authority=Authority::Hub;r.hubState=LinkState::Online;assert(!composeScene(hub,r).stale);
 std::cout<<"Optional providers, fresh local pages, cache gate, enabled failure, Hub loss/recovery passed (host fakes).\n";
}
