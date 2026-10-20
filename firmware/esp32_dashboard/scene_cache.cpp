// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "scene_cache.h"

#include <Preferences.h>
#include <stddef.h>
#include <string.h>

namespace {
constexpr char NVS_NAMESPACE[] = "scene_cache";
constexpr char LAST_KEY[] = "last_v4";
constexpr char HOME_KEY[] = "home_v4";
constexpr uint32_t CACHE_MAGIC = 0x53434E45UL;
constexpr uint16_t CACHE_VERSION = 3;

struct CacheRecord {
  uint32_t magic;
  uint16_t version;
  uint16_t reserved;
  SceneCore scene;
  PageDetails details;
  uint32_t checksum;
};

struct Utf8CacheRecord {
  CacheRecord base;
  Utf8Titles utf8;
  uint32_t checksum;
};

struct LegacyCacheRecord {
  uint32_t magic;
  uint16_t version;
  uint16_t reserved;
  SceneCore scene;
  uint32_t checksum;
};

uint32_t checksum(const uint8_t* bytes, size_t length) {
  uint32_t value = 2166136261UL;
  for (size_t index = 0; index < length; ++index) {
    value ^= bytes[index];
    value *= 16777619UL;
  }
  return value;
}

bool terminated(const char* value, size_t length) {
  return memchr(value, '\0', length) != nullptr;
}

bool valid(const CacheRecord& record) {
  if (record.magic != CACHE_MAGIC ||
      record.version != CACHE_VERSION ||
      record.scene.page > Page::Interrupt ||
      record.scene.authority > Authority::Standalone ||
      record.scene.radarStatus > RadarStatus::Failed ||
      record.scene.todoCount > MAX_TODOS ||
      checksum(reinterpret_cast<const uint8_t*>(&record),
               offsetof(CacheRecord, checksum)) != record.checksum) {
    return false;
  }
  const SceneCore& scene = record.scene;
  if (!terminated(scene.date, sizeof(scene.date)) ||
      !terminated(scene.condition, sizeof(scene.condition)) ||
      !terminated(scene.context, sizeof(scene.context)) ||
      !terminated(scene.interruptTitle, sizeof(scene.interruptTitle)) ||
      !terminated(scene.interruptMessage, sizeof(scene.interruptMessage)) ||
      !terminated(scene.interruptDetail, sizeof(scene.interruptDetail)) ||
      !terminated(record.details.project, sizeof(record.details.project)) ||
      !terminated(record.details.currentItem, sizeof(record.details.currentItem)) ||
      !terminated(record.details.suggestion, sizeof(record.details.suggestion)) ||
      !terminated(record.details.radarDate, sizeof(record.details.radarDate)) ||
      !terminated(record.details.quotaObserved, sizeof(record.details.quotaObserved))) {
    return false;
  }
  for (uint8_t index = 0; index < scene.todoCount; ++index) {
    if (!terminated(scene.todos[index].id, sizeof(scene.todos[index].id)) ||
        !terminated(scene.todos[index].title, sizeof(scene.todos[index].title))) {
      return false;
    }
  }
  return true;
}

CacheRecord makeRecord(const Scene& scene) {
  CacheRecord record{};
  record.magic = CACHE_MAGIC;
  record.version = CACHE_VERSION;
  record.scene = scene;
  record.details = scene.details;
  record.scene.stale = false;  // Recalculate freshness after reboot.
  record.checksum = checksum(reinterpret_cast<const uint8_t*>(&record),
                             offsetof(CacheRecord, checksum));
  return record;
}

Scene sceneOf(const CacheRecord& record) {
  Scene scene;
  static_cast<SceneCore&>(scene) = record.scene;
  scene.details = record.details;
  return scene;
}

bool loadV3(const char* key, Scene& scene) {
  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, true)) return false;
  CacheRecord record{};
  const bool read = preferences.getBytesLength(key) == sizeof(record) &&
      preferences.getBytes(key, &record, sizeof(record)) == sizeof(record);
  preferences.end();
  if (!read || !valid(record)) return false;
  scene = sceneOf(record);
  scene.stale = true;
  scene.details.weatherFresh = scene.details.radarFresh = false;
  return true;
}

bool loadLegacy(const char* key, Scene& scene) {
  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, true)) return false;
  LegacyCacheRecord legacy{};
  const bool read = preferences.getBytesLength(key) == sizeof(legacy) &&
      preferences.getBytes(key, &legacy, sizeof(legacy)) == sizeof(legacy);
  preferences.end();
  if (!read || legacy.magic != CACHE_MAGIC || (legacy.version != 1 && legacy.version != 2) ||
      checksum(reinterpret_cast<const uint8_t*>(&legacy), offsetof(LegacyCacheRecord, checksum)) != legacy.checksum) return false;
  Scene upgraded;
  static_cast<SceneCore&>(upgraded) = legacy.scene;
  const CacheRecord checked = makeRecord(upgraded);
  if (!valid(checked)) return false;
  scene = upgraded;
  scene.stale = true;
  return true;
}

bool validUtf8(const Utf8CacheRecord& record) {
  if (!valid(record.base) || checksum(reinterpret_cast<const uint8_t*>(&record),
      offsetof(Utf8CacheRecord, checksum)) != record.checksum ||
      !terminated(record.utf8.current, UTF8_TITLE_LENGTH)) return false;
  for (uint8_t i = 0; i < MAX_TODOS; ++i)
    if (!terminated(record.utf8.todos[i], UTF8_TITLE_LENGTH)) return false;
  return true;
}

Scene sceneOf(const Utf8CacheRecord& record) {
  Scene scene = sceneOf(record.base);
  scene.utf8 = record.utf8;
  return scene;
}

bool load(const char* key, Scene& scene) {
  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, true)) return false;
  Utf8CacheRecord record{};
  const bool read = preferences.getBytesLength(key) == sizeof(record) &&
      preferences.getBytes(key, &record, sizeof(record)) == sizeof(record);
  preferences.end();
  if (!read || !validUtf8(record)) return false;
  scene = sceneOf(record);
  scene.stale = true;
  scene.details.weatherFresh = scene.details.radarFresh = false;
  return true;
}

bool save(const char* key, const Scene& scene) {
  Utf8CacheRecord next{};
  next.base = makeRecord(scene);
  next.utf8 = scene.utf8;
  next.checksum = checksum(reinterpret_cast<const uint8_t*>(&next), offsetof(Utf8CacheRecord, checksum));
  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, false)) return false;
  Utf8CacheRecord current{};
  const bool unchanged = preferences.getBytesLength(key) == sizeof(current) &&
      preferences.getBytes(key, &current, sizeof(current)) == sizeof(current) &&
      validUtf8(current) && scenesPersistentlyEqual(sceneOf(current), sceneOf(next));
  if (unchanged) { preferences.end(); return true; }
  const bool written = preferences.putBytes(key, &next, sizeof(next)) == sizeof(next);
  preferences.end();
  if (!written) Serial.println("Scene cache write failed");
  return written;
}
}  // namespace

bool loadLastScene(Scene& scene) { return load(LAST_KEY, scene) || loadV3("last_v3", scene) || loadLegacy("last", scene); }
bool loadStandaloneHome(Scene& scene) { return load(HOME_KEY, scene) || loadV3("home_v3", scene) || loadLegacy("home", scene); }
bool saveLastSceneIfChanged(const Scene& scene) {
  if (scene.page == Page::Tibo) return false;  // Keep the last ordinary scene and V3 cache intact.
  return save(LAST_KEY, scene);
}
bool saveStandaloneHomeIfChanged(const Scene& scene) {
  return scene.authority == Authority::Standalone && scene.page == Page::Home &&
         save(HOME_KEY, scene);
}
