// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "scene.h"

#include <string.h>

namespace {

bool todoVisibleEqual(const Todo& left, const Todo& right) {
  return strcmp(left.title, right.title) == 0 && left.done == right.done;
}

bool todosVisiblyEqual(const Scene& left, const Scene& right) {
  if (left.todoCount != right.todoCount) {
    return false;
  }
  for (uint8_t index = 0; index < left.todoCount; ++index) {
    if (left.utf8.present[index] != right.utf8.present[index] ||
        (left.utf8.present[index]
          ? (left.todos[index].done != right.todos[index].done ||
             memcmp(left.utf8.pixels[index], right.utf8.pixels[index], TITLE_BITMAP_BYTES) != 0)
          : !todoVisibleEqual(left.todos[index], right.todos[index]))) {
      return false;
    }
  }
  return true;
}

bool todosPersistentlyEqual(const Scene& left, const Scene& right) {
  if (left.todoCount != right.todoCount) {
    return false;
  }
  for (uint8_t index = 0; index < left.todoCount; ++index) {
    const Todo& leftTodo = left.todos[index];
    const Todo& rightTodo = right.todos[index];
    if (memcmp(left.utf8.pixels[index], right.utf8.pixels[index], TITLE_BITMAP_BYTES) != 0 ||
        left.utf8.present[index] != right.utf8.present[index] ||
        strcmp(left.utf8.todos[index], right.utf8.todos[index]) != 0 ||
        strcmp(leftTodo.id, rightTodo.id) != 0 ||
        strcmp(leftTodo.title, rightTodo.title) != 0 ||
        leftTodo.done != rightTodo.done) {
      return false;
    }
  }
  return true;
}

}  // namespace

void makeDefaultHubScene(HubSceneData& scene) {
  scene = HubSceneData{};
  scene.version = 1;
  scene.page = Page::Home;
}

void makeDefaultScene(Scene& scene) {
  scene = Scene{};
}

bool scenesVisiblyEqual(const Scene& left, const Scene& right) {
  if (left.page != right.page || left.stale != right.stale || left.details.simulated != right.details.simulated) {
    return false;
  }

  switch (left.page) {
    case Page::Home:
      return strcmp(left.date, right.date) == 0 &&
             left.temperature == right.temperature &&
             left.weatherAvailable == right.weatherAvailable &&
             strcmp(left.condition, right.condition) == 0 &&
             left.radarStatus == right.radarStatus &&
             strcmp(left.details.radarDate, right.details.radarDate) == 0 &&
             left.details.radarFresh == right.details.radarFresh &&
             left.details.weatherFresh == right.details.weatherFresh &&
             left.details.todoRemaining == right.details.todoRemaining &&
             todosVisiblyEqual(left, right);
    case Page::Workspace:
      return left.details.showFiveHour == right.details.showFiveHour &&
             (!left.details.showFiveHour || left.quota5hRemaining == right.quota5hRemaining) &&
             left.quotaTotalRemaining == right.quotaTotalRemaining &&
             strcmp(left.details.project, right.details.project) == 0 &&
             (left.utf8.present[MAX_TODOS] || strcmp(left.details.currentItem, right.details.currentItem) == 0) &&
             left.utf8.present[MAX_TODOS] == right.utf8.present[MAX_TODOS] &&
             memcmp(left.utf8.pixels[MAX_TODOS], right.utf8.pixels[MAX_TODOS], TITLE_BITMAP_BYTES) == 0 &&
             strcmp(left.details.suggestion, right.details.suggestion) == 0 &&
             strcmp(left.details.quotaObserved, right.details.quotaObserved) == 0 &&
             left.details.todoRemaining == right.details.todoRemaining &&
             todosVisiblyEqual(left, right);
    case Page::Tibo:
      return strcmp(left.tibo.status, right.tibo.status) == 0 &&
             strcmp(left.tibo.kind, right.tibo.kind) == 0 &&
             strcmp(left.tibo.announcedAt, right.tibo.announcedAt) == 0 &&
             strcmp(left.tibo.pending, right.tibo.pending) == 0 &&
             strcmp(left.tibo.forecastStatus, right.tibo.forecastStatus) == 0 &&
             left.tibo.p24 == right.tibo.p24 && left.tibo.p48 == right.tibo.p48 && left.tibo.p72 == right.tibo.p72;
    case Page::Interrupt:
      return strcmp(left.interruptTitle, right.interruptTitle) == 0 &&
             strcmp(left.interruptMessage, right.interruptMessage) == 0 &&
             strcmp(left.interruptDetail, right.interruptDetail) == 0;
  }
  return false;
}

bool scenesPersistentlyEqual(const Scene& left, const Scene& right) {
  return left.sourceVersion == right.sourceVersion &&
         left.authority == right.authority &&
         left.hubState == right.hubState &&
         left.internetState == right.internetState &&
         left.page == right.page &&
         strcmp(left.date, right.date) == 0 &&
         left.temperature == right.temperature &&
         left.weatherAvailable == right.weatherAvailable &&
         strcmp(left.condition, right.condition) == 0 &&
         strcmp(left.context, right.context) == 0 &&
         left.quota5hRemaining == right.quota5hRemaining &&
         left.quotaTotalRemaining == right.quotaTotalRemaining &&
         left.radarStatus == right.radarStatus &&
         left.stale == right.stale &&
         strcmp(left.interruptTitle, right.interruptTitle) == 0 &&
         strcmp(left.interruptMessage, right.interruptMessage) == 0 &&
         strcmp(left.interruptDetail, right.interruptDetail) == 0 &&
         strcmp(left.details.project, right.details.project) == 0 &&
         strcmp(left.details.currentItem, right.details.currentItem) == 0 &&
             strcmp(left.utf8.current, right.utf8.current) == 0 &&
             left.utf8.present[MAX_TODOS] == right.utf8.present[MAX_TODOS] &&
             memcmp(left.utf8.pixels[MAX_TODOS], right.utf8.pixels[MAX_TODOS], TITLE_BITMAP_BYTES) == 0 &&
         strcmp(left.details.suggestion, right.details.suggestion) == 0 &&
         strcmp(left.details.radarDate, right.details.radarDate) == 0 &&
         strcmp(left.details.quotaObserved, right.details.quotaObserved) == 0 &&
         left.details.radarFresh == right.details.radarFresh &&
         left.details.weatherFresh == right.details.weatherFresh &&
         left.details.simulated == right.details.simulated &&
         left.details.showFiveHour == right.details.showFiveHour &&
         left.details.todoRemaining == right.details.todoRemaining &&
         todosPersistentlyEqual(left, right);
}

const char* radarStatusText(RadarStatus status) {
  switch (status) {
    case RadarStatus::Success: return "SUCCESS";
    case RadarStatus::Failed: return "FAILED";
    case RadarStatus::Unknown: return "UNKNOWN";
  }
  return "UNKNOWN";
}

const char* linkStateText(LinkState state) {
  switch (state) {
    case LinkState::Online: return "ON";
    case LinkState::Offline: return "OFF";
    case LinkState::Unknown: return "--";
  }
  return "--";
}
