// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstring>
#include <iostream>

#include "../firmware/esp32_dashboard/hub_client.h"

FakeSerial Serial;
unsigned long fakeNow = 0;
int fakeWeatherStatus = 200;
int fakeRadarStatus = 200;
int fakeWeatherCalls = 0;
int fakeRadarCalls = 0;

int main() {
  HubSceneData scene;
  makeDefaultHubScene(scene);
  scene.todoCount = 1;
  strlcpy(scene.todos[0].id, "task_1", sizeof(scene.todos[0].id));
  strlcpy(scene.todos[0].title, "Preserve me", sizeof(scene.todos[0].title));

  const String interrupt = R"({
    "version": 2,
    "page": "interrupt",
    "interrupt": {"title":"CODEX","message":"WAITING FOR YOU","detail":"task_1"},
    "stale": true
  })";
  assert(parseHubScenePayload(interrupt, scene));
  assert(scene.page == Page::Interrupt);
  assert(scene.todoCount == 1);
  assert(std::strcmp(scene.todos[0].title, "Preserve me") == 0);
  assert(!scene.todosPresent);
  assert(scene.stale);

  const String clearTodos = R"({
    "version": 3,
    "page": "workspace",
    "context": "CODING",
    "codex": {"quota_5h_remaining":70,"quota_total_remaining":80},
    "radar": {"status":"success"},
    "todos": [],
    "stale": false
  })";
  assert(parseHubScenePayload(clearTodos, scene));
  assert(scene.page == Page::Workspace);
  assert(scene.todosPresent);
  assert(scene.todoCount == 0);
  assert(!scene.stale);

  HubSceneData before = scene;
  const String wrongType = R"({
    "version": 4,
    "page": "interrupt",
    "interrupt": {"title":"RADAR","message":"FAILED","detail":42},
    "stale": false
  })";
  assert(!parseHubScenePayload(wrongType, scene));
  assert(scene.version == before.version);
  assert(scene.page == before.page);
  assert(scene.todoCount == before.todoCount);

  const String wrongStale = R"({
    "version": 4,
    "page": "interrupt",
    "interrupt": {"title":"RADAR","message":"FAILED","detail":"bad"},
    "stale": "false"
  })";
  assert(!parseHubScenePayload(wrongStale, scene));
  assert(scene.version == before.version);

  const String unknown = R"({"protocol_version":2,"version":5,"page":"workspace",
    "codex":{"quota_5h_remaining":null,"quota_total_remaining":null},
    "radar":{"status":"unknown"},"stale":true})";
  assert(parseHubScenePayload(unknown, scene));
  assert(scene.quota5hRemaining == -1 && scene.quotaTotalRemaining == -1);
  assert(scene.radarStatus == RadarStatus::Unknown);
  assert(!parseHubScenePayload(R"({"protocol_version":99,"page":"home"})", scene));
  assert(scene.version == 5);
  assert(parseHubScenePayload(R"({"protocol_version":3,"version":6,"page":"workspace",
    "workspace":{"project":"Attention Router","current_item":"Review","suggestion":"Consider a break"},
    "codex":{"quota_5h_remaining":null,"quota_total_remaining":95,"observed_at":"2026-10-10T04:00:00"},
    "radar":{"status":"success","run_date":"2026-10-09","fresh":false},
    "simulated":true,"todo_remaining":4,"stale":true})", scene));
  assert(std::strcmp(scene.details.project, "Attention Router") == 0);
  assert(std::strcmp(scene.details.radarDate, "2026-10-09") == 0);
  assert(!scene.details.radarFresh && scene.details.simulated && scene.details.todoRemaining == 4);
  assert(scene.quota5hRemaining == -1 && scene.quotaTotalRemaining == 95);
  assert(!parseHubScenePayload(R"({"protocol_version":3,"page":"workspace","workspace":{"project":23}})", scene));
  assert(scene.version == 6);
  scene.details.showFiveHour = true;
  assert(parseHubScenePayload(R"({"protocol_version":3,"page":"workspace","codex":{"show_5h":false}})", scene));
  assert(!scene.details.showFiveHour);

  assert(parseHubScenePayload(R"({"protocol_version":3,"page":"tibo","stale":false,
    "tibo":{"status":"FRESH","kind":"BANKED","announced_at":"2026-10-11T04:00:00",
    "pending":"NO ANNOUNCEMENT","forecast_status":"FRESH","p24":12,"p48":24,"p72":38}})", scene));
  assert(scene.page == Page::Tibo && scene.tibo.p24 == 12);
  assert(!parseHubScenePayload(R"({"protocol_version":3,"page":"tibo","tibo":{"p24":150}})", scene));
  assert(scene.tibo.p24 == 12);
  assert(parseHubScenePayload(R"({"protocol_version":3,"page":"tibo","stale":true,
    "tibo":{"status":"STALE","kind":"BANKED","announced_at":"2026-10-11T04:00:00",
    "pending":"UNKNOWN","forecast_status":"STALE","p24":12,"p48":24,"p72":38}})", scene));
  assert(scene.tibo.p24 == -1);
  assert(parseHubScenePayload(R"({"protocol_version":3,"page":"home"})", scene));
  assert(scene.tibo.p24 == -1);

  for (const char* value : {"0", "65535"}) {
    assert(parseHubScenePayload(String("{\"protocol_version\":3,\"page\":\"home\",\"todo_remaining\":") + value + "}", scene));
  }
  assert(scene.details.todoRemaining == 65535);
  for (const char* value : {"-1", "65536", "1.5", "true", "\"4\""}) {
    assert(!parseHubScenePayload(String("{\"protocol_version\":3,\"page\":\"home\",\"todo_remaining\":") + value + "}", scene));
    assert(scene.details.todoRemaining == 65535);
  }
  std::cout << "Hub parser passed: absent-vs-empty Todos, stale envelope, atomic invalid-payload rejection\n";
}
