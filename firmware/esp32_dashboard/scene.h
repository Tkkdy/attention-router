// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <Arduino.h>

enum class Page : uint8_t {
  Home,
  Workspace,
  Interrupt,
  Tibo,
};

enum class LinkState : uint8_t {
  Unknown,
  Online,
  Offline,
};

enum class Authority : uint8_t {
  Hub,
  Standalone,
};

enum class RadarStatus : uint8_t {
  Unknown,
  Success,
  Failed,
};

constexpr uint8_t MAX_TODOS = 3;
constexpr size_t TODO_TITLE_LENGTH = 34;
constexpr size_t SHORT_TEXT_LENGTH = 24;
constexpr size_t LONG_TEXT_LENGTH = 48;

struct Todo {
  char id[SHORT_TEXT_LENGTH]{};
  char title[TODO_TITLE_LENGTH]{};
  bool done = false;
};

struct PageDetails {
  char project[LONG_TEXT_LENGTH] = "UNKNOWN";
  char currentItem[TODO_TITLE_LENGTH] = "UNKNOWN";
  char suggestion[LONG_TEXT_LENGTH] = "NONE / UNKNOWN";
  char radarDate[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char quotaObserved[SHORT_TEXT_LENGTH] = "UNKNOWN";
  bool radarFresh = false;
  bool weatherFresh = false;
  bool simulated = false;
  bool showFiveHour = false;
  uint16_t todoRemaining = 0;
};

// Runtime-only extension: keep SceneCore/PageDetails and the V3 NVS layout unchanged.
struct TiboDetails {
  char status[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char kind[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char announcedAt[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char pending[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char forecastStatus[SHORT_TEXT_LENGTH] = "OFF";
  int p24 = -1;
  int p48 = -1;
  int p72 = -1;
};

// Optional UTF-8 display extension. Legacy persisted layouts stay unchanged.
constexpr size_t UTF8_TITLE_LENGTH = 192;
constexpr size_t TITLE_BITMAP_WIDTH = 344;
constexpr size_t TITLE_BITMAP_HEIGHT = 18;
constexpr size_t TITLE_BITMAP_BYTES = TITLE_BITMAP_WIDTH / 8 * TITLE_BITMAP_HEIGHT;
struct Utf8Titles {
  uint8_t pixels[MAX_TODOS + 1][TITLE_BITMAP_BYTES]{};
  bool present[MAX_TODOS + 1]{};
  char todos[MAX_TODOS][UTF8_TITLE_LENGTH]{};
  char current[UTF8_TITLE_LENGTH]{};
};

// Parsed Hub payload. Device-local link state never belongs in this type.
struct HubSceneData {
  uint32_t version = 0;
  Page page = Page::Home;
  char date[SHORT_TEXT_LENGTH] = "DATE UNKNOWN";
  int temperature = 0;
  bool weatherAvailable = false;
  char condition[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char context[SHORT_TEXT_LENGTH] = "UNKNOWN";
  int quota5hRemaining = -1;
  int quotaTotalRemaining = -1;
  RadarStatus radarStatus = RadarStatus::Unknown;
  Todo todos[MAX_TODOS]{};
  uint8_t todoCount = 0;
  // True only when the most recently accepted Hub payload explicitly carried
  // an authoritative todos array. Missing and empty are different semantics.
  bool todosPresent = false;
  bool stale = true;
  char interruptTitle[LONG_TEXT_LENGTH] = "MORNING RADAR";
  char interruptMessage[LONG_TEXT_LENGTH] = "FAILED";
  char interruptDetail[LONG_TEXT_LENGTH] = "Check pipeline.";
  PageDetails details;
  TiboDetails tibo;
  Utf8Titles utf8;
};

// Final render model. Only SceneComposer should choose between Hub and device data.
// Preserve this V0.2 layout for reading existing NVS records unchanged.
struct SceneCore {
  uint32_t sourceVersion = 0;
  Authority authority = Authority::Standalone;
  LinkState hubState = LinkState::Unknown;
  LinkState internetState = LinkState::Unknown;
  Page page = Page::Home;
  char date[SHORT_TEXT_LENGTH] = "DATE UNKNOWN";
  int temperature = 0;
  bool weatherAvailable = false;
  char condition[SHORT_TEXT_LENGTH] = "UNKNOWN";
  char context[SHORT_TEXT_LENGTH] = "CODING";
  int quota5hRemaining = -1;
  int quotaTotalRemaining = -1;
  RadarStatus radarStatus = RadarStatus::Unknown;
  Todo todos[MAX_TODOS]{};
  uint8_t todoCount = 0;
  bool stale = true;
  char interruptTitle[LONG_TEXT_LENGTH] = "MORNING RADAR";
  char interruptMessage[LONG_TEXT_LENGTH] = "FAILED";
  char interruptDetail[LONG_TEXT_LENGTH] = "Check pipeline.";
};

struct Scene : SceneCore {
  PageDetails details;
  TiboDetails tibo;
  Utf8Titles utf8;
};

void makeDefaultHubScene(HubSceneData& scene);
void makeDefaultScene(Scene& scene);
bool scenesVisiblyEqual(const Scene& left, const Scene& right);
bool scenesPersistentlyEqual(const Scene& left, const Scene& right);
const char* radarStatusText(RadarStatus status);
const char* linkStateText(LinkState state);
