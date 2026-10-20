// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include <Arduino.h>
#include <SPI.h>
#include <ctype.h>

#include "config.h"
#include "connectivity_manager.h"
#include "display_scheduler.h"
#include "internet_monitor.h"
#include "ntp_clock.h"
#include "pages.h"
#include "radar_adapter.h"
#include "scene.h"
#include "scene_cache.h"
#include "scene_composer.h"
#include "todo_cache.h"
#include "wifi_manager.h"
#include "weather_adapter.h"

// Scene bitmap buffers and atomic cache comparisons need a bounded larger loop stack.
SET_LOOP_TASK_STACK_SIZE(32768);

// Use a serial terminal at 115200 baud to switch pages during development:
// H = Home, W = Workspace, I = Interrupt, R = redraw, ? = help.
HubSceneData hubScene;
ConnectivityManager connectivity;
InternetMonitor internetMonitor;
NtpClock ntpClock;
WeatherAdapter weatherAdapter;
RadarAdapter radarAdapter;
DisplayScheduler displayScheduler;
Scene cachedStandaloneHome;
bool hasCachedStandaloneHome = false;

void printHelp() {
  Serial.println("Commands: H=HOME, W=WORKSPACE, I=INTERRUPT, R=REDRAW, ?=HELP");
}

RuntimeState runtimeState() {
  RuntimeState state;
  state.authority = connectivity.authority();
  state.hubState = connectivity.hubState();
  state.internetState = connectivity.internetState();
  state.standaloneDateVerified = ntpClock.hasLocalDate();
  state.hasStandaloneDate = state.standaloneDateVerified || hasCachedStandaloneHome;
  if (state.hasStandaloneDate) {
    strlcpy(state.standaloneDate,
            state.standaloneDateVerified ? ntpClock.localDate()
                                         : cachedStandaloneHome.date,
            sizeof(state.standaloneDate));
  }
  state.weatherEnabled = weatherAdapter.configured();
  state.hasStandaloneWeather = weatherAdapter.sample().available ||
      (hasCachedStandaloneHome && cachedStandaloneHome.weatherAvailable);
  state.standaloneWeatherFresh = weatherAdapter.fresh(millis());
  if (state.hasStandaloneWeather) {
    const bool liveWeather = weatherAdapter.sample().available;
    state.standaloneTemperature = liveWeather
        ? weatherAdapter.sample().temperature : cachedStandaloneHome.temperature;
    strlcpy(state.standaloneCondition,
            liveWeather ? weatherAdapter.sample().condition
                        : cachedStandaloneHome.condition,
            sizeof(state.standaloneCondition));
  }
  state.standaloneRadarVerified = radarAdapter.verified();
  state.standaloneRadarStatus = state.standaloneRadarVerified
      ? radarAdapter.sample().status
      : hasCachedStandaloneHome ? cachedStandaloneHome.radarStatus
                                : RadarStatus::Unknown;
  strlcpy(state.standaloneRadarDetail,
          state.standaloneRadarVerified ? radarAdapter.sample().detail
                                       : cachedStandaloneHome.interruptDetail,
          sizeof(state.standaloneRadarDetail));
  strlcpy(state.standaloneRadarDate,
          state.standaloneRadarVerified ? radarAdapter.sample().runDate : cachedStandaloneHome.details.radarDate,
          sizeof(state.standaloneRadarDate));
  return state;
}

void submitComposedScene(RefreshPriority priority = RefreshPriority::Normal) {
  const Scene scene = composeScene(hubScene, runtimeState());
  displayScheduler.submit(scene, priority);
  if (!scene.stale) saveLastSceneIfChanged(scene);
  if (scene.authority == Authority::Standalone && scene.page == Page::Home &&
      (ntpClock.hasLocalDate() || weatherAdapter.sample().available ||
       radarAdapter.sample().status != RadarStatus::Unknown)) {
    if (saveStandaloneHomeIfChanged(scene)) {
      cachedStandaloneHome = scene;
      hasCachedStandaloneHome = true;
    }
  }
}

void showManualPage(Page page) {
  Scene manualScene = displayScheduler.currentScene();
  manualScene.page = page;
  displayScheduler.force(manualScene);
  displayScheduler.tick(millis());
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(toupper(Serial.read()));
    switch (command) {
      case 'H': showManualPage(Page::Home); break;
      case 'W': showManualPage(Page::Workspace); break;
      case 'I': showManualPage(Page::Interrupt); break;
      case 'R':
        displayScheduler.force(displayScheduler.currentScene());
        displayScheduler.tick(millis());
        break;
      case '?': printHelp(); break;
      case '\r':
      case '\n':
      case ' ':
        break;
      default:
        Serial.print("Unknown command: ");
        Serial.println(command);
        printHelp();
        break;
    }
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);
  Serial.println();
  Serial.println("ESP32 Personal Dashboard - Milestone 3 / Phase 1");

  // Verified panel bus wiring. Keep in sync with config.h.
  SPI.begin(PIN_SCK, -1, PIN_MOSI, PIN_CS);
  initDisplay();

  makeDefaultHubScene(hubScene);
  loadTodoCache(hubScene.todos, hubScene.todoCount);
  hasCachedStandaloneHome = loadStandaloneHome(cachedStandaloneHome);
  connectivity.begin(millis());
  internetMonitor.begin(millis());
  ntpClock.begin(millis());
  weatherAdapter.begin(millis());
  radarAdapter.begin(millis());
  Scene restored;
  if (loadLastScene(restored)) {
    Serial.println("Restored last scene from NVS; marking STALE");
    // A persisted overlay is not evidence that the source event is still valid.
    // Keep the cache intact; Router will reevaluate after Hub recovery.
    restored.page = Page::Home;
    // Match cached UTF-8 labels by stable device ID, never by row position.
    for (uint8_t i = 0; i < hubScene.todoCount; ++i)
      for (uint8_t j = 0; j < restored.todoCount; ++j)
        if (strcmp(hubScene.todos[i].id, restored.todos[j].id) == 0 &&
            strcmp(hubScene.todos[i].title, restored.todos[j].title) == 0)
          {
            strlcpy(hubScene.utf8.todos[i], restored.utf8.todos[j], UTF8_TITLE_LENGTH);
            memcpy(hubScene.utf8.pixels[i], restored.utf8.pixels[j], TITLE_BITMAP_BYTES);
            hubScene.utf8.present[i] = restored.utf8.present[j];
          }
    displayScheduler.force(restored);
  } else {
    submitComposedScene(RefreshPriority::Urgent);
  }
  displayScheduler.tick(millis());

  beginNetwork();
  printHelp();
}

void loop() {
  handleSerialCommands();

  const unsigned long now = millis();
  const bool networkReady = ensureNetwork();
  const bool internetChanged = internetMonitor.tick(now, networkReady);
  if (internetChanged) {
    connectivity.setInternetState(internetMonitor.state());
  }
  const bool localDateChanged =
      ntpClock.tick(now, connectivity.internetState() == LinkState::Online);
  const ConnectivityEvent event = connectivity.tick(now, networkReady, hubScene);
  const bool weatherChanged = weatherAdapter.tick(
      now, connectivity.authority() == Authority::Standalone || hubScene.page == Page::Home,
      connectivity.internetState() == LinkState::Online,
      ntpClock.hasLocalDate());
  const RadarStatus previousRadarStatus = radarAdapter.sample().status;
  const bool radarChanged = radarAdapter.tick(
      now, connectivity.authority() == Authority::Standalone,
      connectivity.internetState() == LinkState::Online,
      ntpClock.hasLocalDate());
  if (event.hubSceneUpdated && connectivity.authority() == Authority::Hub &&
      hubScene.todosPresent) {
    saveTodoCacheIfChanged(hubScene.todos, hubScene.todoCount);
  }
  if (internetChanged || event.sceneMayHaveChanged() ||
      ((localDateChanged || weatherChanged || radarChanged) &&
       (connectivity.authority() == Authority::Standalone || hubScene.page == Page::Home))) {
    const bool newlyFailed = radarChanged &&
        previousRadarStatus != RadarStatus::Failed &&
        radarAdapter.sample().status == RadarStatus::Failed &&
        connectivity.authority() == Authority::Standalone;
    const bool hubInterrupt = event.hubSceneUpdated &&
        connectivity.authority() == Authority::Hub &&
        hubScene.page == Page::Interrupt;
    submitComposedScene((newlyFailed || hubInterrupt) ? RefreshPriority::Urgent
                                                      : RefreshPriority::Normal);
  }

  displayScheduler.tick(now);
}
