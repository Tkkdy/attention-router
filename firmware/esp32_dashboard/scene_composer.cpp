// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "scene_composer.h"

#include <string.h>

namespace {

void copyText(char* destination, size_t destinationSize, const char* source) {
  strlcpy(destination, source, destinationSize);
}

void copyTodos(const HubSceneData& source, Scene& target) {
  target.utf8 = source.utf8;
  target.todoCount = source.todoCount > MAX_TODOS ? MAX_TODOS : source.todoCount;
  for (uint8_t index = 0; index < target.todoCount; ++index) {
    target.todos[index] = source.todos[index];
  }
}

}  // namespace

Scene composeScene(const HubSceneData& hubScene, const RuntimeState& runtime) {
  Scene scene;
  makeDefaultScene(scene);
  scene.authority = runtime.authority;
  scene.hubState = runtime.hubState;
  scene.internetState = runtime.internetState;

  if (runtime.authority == Authority::Standalone) {
    scene.page = Page::Home;
    copyTodos(hubScene, scene);
    if (runtime.hasStandaloneDate) {
      copyText(scene.date, sizeof(scene.date), runtime.standaloneDate);
    }
    if (runtime.hasStandaloneWeather) {
      scene.temperature = runtime.standaloneTemperature;
      scene.weatherAvailable = true;
      copyText(scene.condition, sizeof(scene.condition), runtime.standaloneCondition);
    }
    scene.radarStatus = runtime.standaloneRadarStatus;
    scene.details = hubScene.details;
    copyText(scene.details.radarDate, sizeof(scene.details.radarDate), runtime.standaloneRadarDate);
    scene.details.radarFresh = runtime.standaloneRadarVerified;
    scene.details.weatherFresh = runtime.standaloneWeatherFresh;
    // Hub loss always returns HOME. Provider failures never grant an interrupt.
    // Cached Todos are a normal fallback. Missing date, weather or today's
    // Radar result are the fields that make this standalone scene stale.
    scene.stale = runtime.hubState == LinkState::Offline ||
                  runtime.internetState != LinkState::Online ||
                  !runtime.standaloneDateVerified ||
                  !runtime.standaloneWeatherFresh ||
                  !runtime.standaloneRadarVerified;
    return scene;
  }

  scene.sourceVersion = hubScene.version;
  scene.page = hubScene.page;
  copyText(scene.date, sizeof(scene.date), hubScene.date);
  scene.temperature = hubScene.temperature;
  scene.weatherAvailable = hubScene.weatherAvailable;
  copyText(scene.condition, sizeof(scene.condition), hubScene.condition);
  copyText(scene.context, sizeof(scene.context), hubScene.context);
  scene.quota5hRemaining = hubScene.quota5hRemaining;
  scene.quotaTotalRemaining = hubScene.quotaTotalRemaining;
  scene.radarStatus = hubScene.radarStatus;
  scene.details = hubScene.details;
  scene.tibo = hubScene.tibo;
  // Tibo is collected by Hub; the device WAN probe cannot invalidate a fresh LAN sample.
  if (runtime.hubState != LinkState::Online) {
    scene.tibo.p24 = scene.tibo.p48 = scene.tibo.p72 = -1;
    strlcpy(scene.tibo.forecastStatus, "STALE", sizeof(scene.tibo.forecastStatus));
  }
  copyTodos(hubScene, scene);
  // WAN health is reported separately; fresh LAN tasks and reminders remain usable.
  scene.stale = hubScene.stale || runtime.hubState != LinkState::Online;
  copyText(scene.interruptTitle, sizeof(scene.interruptTitle), hubScene.interruptTitle);
  copyText(scene.interruptMessage, sizeof(scene.interruptMessage), hubScene.interruptMessage);
  copyText(scene.interruptDetail, sizeof(scene.interruptDetail), hubScene.interruptDetail);
  // Weather and local clock keep their existing device adapters under Hub HOME.
  if (scene.page == Page::Home) {
    if (runtime.standaloneDateVerified) copyText(scene.date, sizeof(scene.date), runtime.standaloneDate);
    if (runtime.hasStandaloneWeather) {
      scene.temperature = runtime.standaloneTemperature;
      scene.weatherAvailable = true;
      copyText(scene.condition, sizeof(scene.condition), runtime.standaloneCondition);
    }
    scene.details.weatherFresh = runtime.standaloneWeatherFresh;
    scene.stale = scene.stale || (runtime.weatherEnabled && !runtime.standaloneWeatherFresh);
  }
  return scene;
}
