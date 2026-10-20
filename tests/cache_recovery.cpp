// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstring>
#include <iostream>
#include <unordered_map>
#include <vector>
#include <cstddef>

#include "../firmware/esp32_dashboard/scene_cache.h"

FakeSerial Serial;
std::unordered_map<std::string, std::vector<unsigned char>> fakeNvs;
int fakeNvsWrites = 0;

int main() {
  Scene restored;
  assert(!loadLastScene(restored));

  Scene home;
  makeDefaultScene(home);
  home.page = Page::Home;
  home.authority = Authority::Standalone;
  home.stale = false;
  strlcpy(home.date, "SEP 28  *  MON", sizeof(home.date));
  home.weatherAvailable = true;
  home.temperature = 28;
  home.radarStatus = RadarStatus::Success;
  assert(saveStandaloneHomeIfChanged(home));
  assert(saveLastSceneIfChanged(home));
  assert(fakeNvsWrites == 2);
  assert(saveStandaloneHomeIfChanged(home));
  assert(saveLastSceneIfChanged(home));
  assert(fakeNvsWrites == 2);

  // Hidden fields are intentionally ignored by display equality but must still
  // update the persisted record when the raw cache model changes.
  Scene chinese = home;
  chinese.todoCount = 1;
  chinese.utf8.present[0] = true;
  chinese.utf8.pixels[0][0] = 0x80;
  strlcpy(chinese.todos[0].id, "one", sizeof(chinese.todos[0].id));
  strlcpy(chinese.utf8.todos[0], "中文待办", UTF8_TITLE_LENGTH);
  assert(saveLastSceneIfChanged(chinese));
  assert(loadLastScene(restored));
  assert(strcmp(restored.utf8.todos[0], "中文待办") == 0);
  assert(restored.utf8.present[0] && restored.utf8.pixels[0][0] == 0x80);
  Scene renamed = chinese;
  renamed.utf8.pixels[0][0] = 0x40;
  strlcpy(renamed.utf8.todos[0], "改名待办", UTF8_TITLE_LENGTH);
  assert(!scenesVisiblyEqual(chinese, renamed));
  assert(!scenesPersistentlyEqual(chinese, renamed));
  --fakeNvsWrites; // Additional Unicode fixture is independent of legacy counts.

  Scene hiddenChange = home;
  strlcpy(hiddenChange.context, "IDLE", sizeof(hiddenChange.context));
  assert(scenesVisiblyEqual(home, hiddenChange));
  assert(!scenesPersistentlyEqual(home, hiddenChange));
  assert(saveStandaloneHomeIfChanged(hiddenChange));
  assert(fakeNvsWrites == 3);

  assert(loadStandaloneHome(restored));
  assert(std::strcmp(restored.context, "IDLE") == 0);
  assert(restored.stale && restored.temperature == 28);

  Scene workspace = home;
  workspace.page = Page::Workspace;
  workspace.authority = Authority::Hub;
  strlcpy(workspace.context, "CODING", sizeof(workspace.context));
  workspace.quota5hRemaining = 70;
  assert(saveLastSceneIfChanged(workspace));
  assert(loadLastScene(restored));
  assert(restored.page == Page::Workspace && restored.stale);
  assert(loadStandaloneHome(restored));
  assert(restored.page == Page::Home && restored.authority == Authority::Standalone);

  Scene interrupt = workspace;
  interrupt.page = Page::Interrupt;
  strlcpy(interrupt.interruptMessage, "FAILED", sizeof(interrupt.interruptMessage));
  assert(saveLastSceneIfChanged(interrupt));
  assert(loadLastScene(restored));
  assert(restored.page == Page::Interrupt && restored.stale);

  const auto beforeTibo = fakeNvs["scene_cache/last_v4"];
  Scene tibo = interrupt;
  tibo.page = Page::Tibo;
  tibo.tibo.p24 = 90;
  assert(!saveLastSceneIfChanged(tibo));
  assert(fakeNvs["scene_cache/last_v4"] == beforeTibo);
  assert(loadLastScene(restored) && restored.page == Page::Interrupt);

  fakeNvs["scene_cache/last_v4"].back() ^= 1;
  assert(!loadLastScene(restored));
  assert(loadStandaloneHome(restored));
  // A byte-for-byte V3 record still loads and is never overwritten.
  struct V3Record { uint32_t magic; uint16_t version; uint16_t reserved;
    SceneCore scene; PageDetails details; uint32_t checksum; } v3{};
  v3.magic = 0x53434E45UL; v3.version = 3; v3.scene = home; v3.details = home.details;
  v3.checksum = 2166136261UL;
  const auto* oldBytes = reinterpret_cast<const unsigned char*>(&v3);
  for (size_t i = 0; i < offsetof(V3Record, checksum); ++i) {
    v3.checksum ^= oldBytes[i]; v3.checksum *= 16777619UL;
  }
  fakeNvs["scene_cache/last_v3"] = {oldBytes, oldBytes + sizeof(v3)};
  assert(loadLastScene(restored) && restored.utf8.todos[0][0] == 0);
  const auto oldV3 = fakeNvs["scene_cache/last_v3"];
  assert(saveLastSceneIfChanged(restored));
  assert(fakeNvs["scene_cache/last_v3"] == oldV3);
  fakeNvs.erase("scene_cache/last_v3");
  fakeNvs.erase("scene_cache/last_v4");
  // A byte-for-byte V0.2 layout remains readable without changing its NVS key.
  struct LegacyRecord { uint32_t magic; uint16_t version; uint16_t reserved; SceneCore scene; uint32_t checksum; } legacy{};
  legacy.magic = 0x53434E45UL;
  legacy.version = 2;
  legacy.scene = static_cast<const SceneCore&>(home);
  legacy.checksum = 2166136261UL;
  const auto* bytes = reinterpret_cast<const unsigned char*>(&legacy);
  for (size_t i = 0; i < offsetof(LegacyRecord, checksum); ++i) {
    legacy.checksum ^= bytes[i]; legacy.checksum *= 16777619UL;
  }
  fakeNvs["scene_cache/last"] = {bytes, bytes + sizeof(legacy)};
  const auto original = fakeNvs["scene_cache/last"];
  assert(loadLastScene(restored));
  assert(restored.stale && restored.temperature == home.temperature);
  assert(std::strcmp(restored.details.radarDate, "UNKNOWN") == 0);
  assert(saveLastSceneIfChanged(restored));
  assert(fakeNvs["scene_cache/last"] == original);
  std::cout << "Scene cache passed: Home, Workspace, Interrupt, "
               "write suppression, checksum rejection\n";
}
