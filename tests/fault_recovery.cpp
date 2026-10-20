// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstdio>
#include <ctime>
#include <iostream>

#include "../firmware/esp32_dashboard/display_scheduler.h"
#include "../firmware/esp32_dashboard/radar_adapter.h"
#include "../firmware/esp32_dashboard/scene_composer.h"
#include "../firmware/esp32_dashboard/weather_adapter.h"

FakeSerial Serial;
unsigned long fakeNow = 0;
int fakeWeatherStatus = 200;
int fakeRadarStatus = 200;
int fakeWeatherCalls = 0;
int fakeRadarCalls = 0;
std::string fakeRadarRunDate;
std::string fakeRadarDetail = "Check radar pipeline.";
std::string fakeRadarPayloadStatus = "SUCCESS";
int renderCount = 0;

const char* pageName(Page) { return "HOME"; }
void renderPage(const Scene&) { ++renderCount; }

Scene home(const HubSceneData& hub, const WeatherAdapter& weather,
           const RadarAdapter& radar, LinkState internet, const Scene* cached) {
  RuntimeState runtime;
  runtime.authority = Authority::Standalone;
  runtime.internetState = internet;
  runtime.hasStandaloneDate = true;
  runtime.standaloneDateVerified = true;
  strlcpy(runtime.standaloneDate, "SEP 28  *  MON", sizeof(runtime.standaloneDate));
  runtime.hasStandaloneWeather = weather.sample().available;
  runtime.standaloneWeatherFresh = weather.fresh(fakeNow);
  runtime.standaloneTemperature = weather.sample().temperature;
  strlcpy(runtime.standaloneCondition, weather.sample().condition,
          sizeof(runtime.standaloneCondition));
  runtime.standaloneRadarVerified = radar.verified();
  runtime.standaloneRadarStatus = radar.verified()
      ? radar.sample().status : cached ? cached->radarStatus : RadarStatus::Unknown;
  return composeScene(hub, runtime);
}

void show(DisplayScheduler& scheduler, const Scene& scene) {
  scheduler.submit(scene);
  scheduler.tick(fakeNow + 2000);
}

int main() {
  const time_t singaporeNow = time(nullptr) + 8 * 60 * 60;
  const tm* calendar = gmtime(&singaporeNow);
  char date[11]{};
  assert(calendar && strftime(date, sizeof(date), "%Y-%m-%d", calendar) == 10);
  fakeRadarRunDate = date;

  HubSceneData hub;
  makeDefaultHubScene(hub);
  WeatherAdapter weather;
  RadarAdapter radar;
  DisplayScheduler scheduler;
  weather.begin(0);
  radar.begin(0);

  // Online + fresh: one HOME render.
  assert(weather.tick(fakeNow, true, true, true));
  assert(radar.tick(fakeNow, true, true, true));
  Scene cached = home(hub, weather, radar, LinkState::Online, nullptr);
  assert(!cached.stale && cached.page == Page::Home);
  show(scheduler, cached);
  assert(renderCount == 1);

  // Internet unavailable: retain content, show STALE once.
  fakeNow = 60000;
  weather.tick(fakeNow, true, false, true);
  radar.tick(fakeNow, true, false, true);
  Scene offline = home(hub, weather, radar, LinkState::Offline, &cached);
  assert(offline.stale && offline.weatherAvailable);
  assert(offline.temperature == cached.temperature);
  assert(offline.radarStatus == cached.radarStatus);
  show(scheduler, offline);
  assert(renderCount == 2);

  // Internet returns; both immediate requests fail. Connectivity alone cannot clear STALE.
  fakeNow = 120000;
  fakeWeatherStatus = -1;
  fakeRadarStatus = -1;
  weather.tick(fakeNow, true, true, true);
  radar.tick(fakeNow, true, true, true);
  assert(fakeWeatherCalls == 2 && fakeRadarCalls == 2);
  Scene unverified = home(hub, weather, radar, LinkState::Online, &cached);
  assert(unverified.stale);
  show(scheduler, unverified);
  assert(renderCount == 2);

  // Weather recovers first; its now-visible freshness label changes once.
  fakeNow = 180000;
  fakeWeatherStatus = 200;
  weather.tick(fakeNow, true, true, true);
  radar.tick(fakeNow, true, true, true);
  assert(fakeWeatherCalls == 3 && fakeRadarCalls == 2);
  Scene partlyFresh = home(hub, weather, radar, LinkState::Online, &cached);
  assert(partlyFresh.stale);
  show(scheduler, partlyFresh);
  assert(renderCount == 3);

  // Radar's bounded retry succeeds. The unchanged data clears only STALE.
  fakeNow = 420000;
  fakeRadarStatus = 200;
  weather.tick(fakeNow, true, true, true);
  radar.tick(fakeNow, true, true, true);
  assert(fakeRadarCalls == 3 && radar.verified());
  Scene recovered = home(hub, weather, radar, LinkState::Online, &cached);
  assert(!recovered.stale);
  assert(recovered.temperature == cached.temperature);
  assert(recovered.radarStatus == cached.radarStatus);
  show(scheduler, recovered);
  assert(renderCount == 4);
  show(scheduler, recovered);
  assert(renderCount == 4);

  // An unread Hub overlay and even a verified Radar failure cannot defeat HOME
  // after the existing authority manager switches to Standalone.
  hub.page = Page::Interrupt;
  hub.todoCount = 1;
  strlcpy(hub.todos[0].title, "Keep user task", sizeof(hub.todos[0].title));
  RuntimeState unavailable;
  unavailable.authority = Authority::Standalone;
  unavailable.hubState = LinkState::Offline;
  unavailable.standaloneRadarVerified = true;
  unavailable.standaloneRadarStatus = RadarStatus::Failed;
  const Scene dismissed = composeScene(hub, unavailable);
  assert(dismissed.page == Page::Home && dismissed.todoCount == 1);
  assert(hub.page == Page::Interrupt);  // No acknowledgement or source mutation.

  hub.page = Page::Home;
  RuntimeState online;
  online.authority = Authority::Hub;
  online.hubState = LinkState::Online;
  online.hasStandaloneWeather = true;
  online.standaloneWeatherFresh = true;
  online.standaloneTemperature = 26;
  strlcpy(online.standaloneCondition, "CLEAR", sizeof(online.standaloneCondition));
  const Scene hubHome = composeScene(hub, online);
  assert(hubHome.temperature == 26 && hubHome.weatherAvailable && hubHome.details.weatherFresh);

  // Hub-owned Tibo freshness is independent of the ESP32 WAN probe.
  hub.page = Page::Tibo;
  hub.stale = false;
  hub.tibo.p24 = 12;
  strlcpy(hub.tibo.forecastStatus, "FRESH", sizeof(hub.tibo.forecastStatus));
  online.internetState = LinkState::Offline;
  const Scene lanTibo = composeScene(hub, online);
  assert(!lanTibo.stale && lanTibo.tibo.p24 == 12);
  assert(strcmp(lanTibo.tibo.forecastStatus, "FRESH") == 0);
  online.hubState = LinkState::Offline;
  const Scene lostTibo = composeScene(hub, online);
  assert(lostTibo.stale && lostTibo.tibo.p24 == -1);
  assert(strcmp(lostTibo.tibo.forecastStatus, "STALE") == 0);
  assert(composeScene(hub, unavailable).page == Page::Home);

  std::cout << "Fault recovery passed: cached HOME, STALE, immediate retry, "
               "validated recovery, no redundant refresh\n";
}
