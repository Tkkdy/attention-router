// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include <ArduinoJson.h>
#include <HTTPClient.h>

#include "hub_client.h"
#include "utf8_text.h"

#if __has_include("private_config.h")
#include "private_config.h"
#endif

namespace {

// Override with a private build flag later, for example:
// -DDASHBOARD_HUB_URL=\"http://192.168.x.x:8000\"
#ifndef DASHBOARD_HUB_URL
#define DASHBOARD_HUB_URL ""
#endif

constexpr char HUB_URL[] = DASHBOARD_HUB_URL;

int hexDigit(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

bool parseTitleBitmap(JsonVariantConst value, Utf8Titles& titles, uint8_t index) {
  titles.present[index] = false;
  memset(titles.pixels[index], 0, TITLE_BITMAP_BYTES);
  if (value.isNull()) return true;
  if (!value.is<const char*>()) return false;
  const char* hex = value.as<const char*>();
  if (!hex || strlen(hex) != TITLE_BITMAP_BYTES * 2) return false;
  for (size_t i = 0; i < TITLE_BITMAP_BYTES; ++i) {
    const int a = hexDigit(hex[i * 2]), b = hexDigit(hex[i * 2 + 1]);
    if (a < 0 || b < 0) return false;
    titles.pixels[index][i] = (a << 4) | b;
  }
  titles.present[index] = true;
  return true;
}

bool copyOptionalJsonString(JsonVariantConst value, char* destination,
                            size_t destinationSize) {
  if (value.isNull()) {
    return true;
  }
  if (!value.is<const char*>()) {
    return false;
  }
  const char* source = value.as<const char*>();
  if (source == nullptr) {
    return false;
  }
  copyUtf8(destination, destinationSize, source);
  return true;
}

bool copyRequiredJsonString(JsonVariantConst value, char* destination,
                            size_t destinationSize) {
  return !value.isNull() && copyOptionalJsonString(value, destination, destinationSize);
}

bool parsePage(const char* value, Page& page) {
  if (value == nullptr) {
    return false;
  }
  if (strcmp(value, "home") == 0) {
    page = Page::Home;
  } else if (strcmp(value, "workspace") == 0) {
    page = Page::Workspace;
  } else if (strcmp(value, "interrupt") == 0) {
    page = Page::Interrupt;
  } else if (strcmp(value, "tibo") == 0) {
    page = Page::Tibo;
  } else {
    return false;
  }
  return true;
}

bool parseRadarStatus(const char* value, RadarStatus& status) {
  if (value == nullptr) {
    return false;
  }
  if (strcasecmp(value, "success") == 0) {
    status = RadarStatus::Success;
    return true;
  }
  if (strcasecmp(value, "failed") == 0) {
    status = RadarStatus::Failed;
    return true;
  }
  if (strcasecmp(value, "unknown") == 0) {
    status = RadarStatus::Unknown;
    return true;
  }
  return false;
}

bool parseOptionalInt(JsonVariantConst value, int& destination, int minimum,
                      int maximum) {
  if (value.isNull()) {
    return true;
  }
  if (!value.is<int>()) {
    return false;
  }
  const int parsed = value.as<int>();
  if (parsed < minimum || parsed > maximum) {
    return false;
  }
  destination = parsed;
  return true;
}

}  // namespace

bool parseHubScenePayload(const String& payload, HubSceneData& scene) {
  JsonDocument document;
  const DeserializationError error = deserializeJson(document, payload);
  if (error) {
    Serial.print("Scene JSON error: ");
    Serial.println(error.c_str());
    return false;
  }

  if (!document["page"].is<const char*>()) {
    Serial.println("Scene JSON page must be a string");
    return false;
  }

  HubSceneData parsed = scene;
  if (!document["protocol_version"].isNull() &&
      (!document["protocol_version"].is<int>() ||
       (document["protocol_version"].as<int>() < 1 || document["protocol_version"].as<int>() > 3))) {
    Serial.println("Unsupported scene protocol version");
    return false;
  }
  // Protocol v2 null means unknown, never retain a misleading cached percentage.
  if (document["protocol_version"].is<int>() &&
      document["protocol_version"].as<int>() >= 2) {
    if (document["codex"]["quota_5h_remaining"].isNull()) parsed.quota5hRemaining = -1;
    if (document["codex"]["quota_total_remaining"].isNull()) parsed.quotaTotalRemaining = -1;
  }
  if (document["protocol_version"].as<int>() == 3) {
    parsed.details = PageDetails{};
    parsed.utf8.current[0] = 0;
    if (!parseTitleBitmap(document["workspace"]["title_bitmap"], parsed.utf8, MAX_TODOS)) return false;
    if (!copyOptionalJsonString(document["workspace"]["display_title"], parsed.utf8.current, sizeof(parsed.utf8.current))) return false;
    // A v3 omission is conservative: never resurrect a cached five-hour row.
    if (!document["codex"]["show_5h"].isNull()) {
      if (!document["codex"]["show_5h"].is<bool>()) return false;
      parsed.details.showFiveHour = document["codex"]["show_5h"].as<bool>();
    }
    if (!copyOptionalJsonString(document["workspace"]["project"], parsed.details.project, sizeof(parsed.details.project)) ||
        !copyOptionalJsonString(document["workspace"]["current_item"], parsed.details.currentItem, sizeof(parsed.details.currentItem)) ||
        !copyOptionalJsonString(document["workspace"]["suggestion"], parsed.details.suggestion, sizeof(parsed.details.suggestion)) ||
        !copyOptionalJsonString(document["radar"]["run_date"], parsed.details.radarDate, sizeof(parsed.details.radarDate)) ||
        !copyOptionalJsonString(document["codex"]["observed_at"], parsed.details.quotaObserved, sizeof(parsed.details.quotaObserved))) return false;
    if (!document["radar"]["fresh"].isNull()) {
      if (!document["radar"]["fresh"].is<bool>()) return false;
      parsed.details.radarFresh = document["radar"]["fresh"].as<bool>();
    }
    if (!document["simulated"].isNull()) {
      if (!document["simulated"].is<bool>()) return false;
      parsed.details.simulated = document["simulated"].as<bool>();
    }
    if (!document["todo_remaining"].isNull()) {
      if (!document["todo_remaining"].is<uint16_t>()) return false;
      parsed.details.todoRemaining = document["todo_remaining"].as<uint16_t>();
    }
  } else parsed.details.showFiveHour = true;
  const char* pageName = document["page"].as<const char*>();
  if (!parsePage(pageName, parsed.page)) {
    Serial.println("Scene JSON has an unsupported page");
    return false;
  }

  if (!document["version"].isNull()) {
    if (!document["version"].is<uint32_t>()) {
      Serial.println("Scene JSON version must be an unsigned integer");
      return false;
    }
    parsed.version = document["version"].as<uint32_t>();
  }

  if (!copyOptionalJsonString(document["date"], parsed.date, sizeof(parsed.date)) ||
      !copyOptionalJsonString(document["weather"]["condition"], parsed.condition,
                              sizeof(parsed.condition)) ||
      !copyOptionalJsonString(document["context"], parsed.context,
                              sizeof(parsed.context))) {
    Serial.println("Scene JSON contains a non-string text field");
    return false;
  }

  if (!document["weather"]["temperature"].isNull()) {
    if (!document["weather"]["temperature"].is<int>()) {
      Serial.println("Scene weather temperature must be an integer");
      return false;
    }
    parsed.temperature = document["weather"]["temperature"].as<int>();
    parsed.weatherAvailable = true;
  }
  if (!document["weather"]["condition"].isNull()) {
    parsed.weatherAvailable = true;
  }

  if (!parseOptionalInt(document["codex"]["quota_5h_remaining"],
                        parsed.quota5hRemaining, 0, 100) ||
      !parseOptionalInt(document["codex"]["quota_total_remaining"],
                        parsed.quotaTotalRemaining, 0, 100)) {
    Serial.println("Scene quota must be an integer from 0 to 100");
    return false;
  }

  if (!document["radar"]["status"].isNull()) {
    if (!document["radar"]["status"].is<const char*>() ||
        !parseRadarStatus(document["radar"]["status"].as<const char*>(),
                          parsed.radarStatus)) {
      Serial.println("Scene JSON has an unsupported radar status");
      return false;
    }
  }

  // Freshness is part of the scene envelope. Older/malformed payloads must
  // never become fresh by omission.
  if (document["stale"].isNull()) {
    parsed.stale = true;
  } else if (!document["stale"].is<bool>()) {
    Serial.println("Scene stale must be a boolean");
    return false;
  } else {
    parsed.stale = document["stale"].as<bool>();
  }

  parsed.todosPresent = !document["todos"].isNull();
  if (parsed.todosPresent) {
    if (!document["todos"].is<JsonArrayConst>()) {
      Serial.println("Scene todos must be an array");
      return false;
    }
    Todo parsedTodos[MAX_TODOS]{};
    memset(parsed.utf8.todos, 0, sizeof(parsed.utf8.todos));
    memset(parsed.utf8.pixels, 0, MAX_TODOS * TITLE_BITMAP_BYTES);
    memset(parsed.utf8.present, 0, MAX_TODOS * sizeof(bool));
    uint8_t parsedTodoCount = 0;
    for (JsonVariantConst item : document["todos"].as<JsonArrayConst>()) {
      if (parsedTodoCount >= MAX_TODOS) {
        break;
      }
      if (!item.is<JsonObjectConst>()) {
        Serial.println("Scene todo entries must be objects");
        return false;
      }
      Todo& todo = parsedTodos[parsedTodoCount];
      if (!parseTitleBitmap(item["title_bitmap"], parsed.utf8, parsedTodoCount)) return false;
      if (!copyOptionalJsonString(item["display_title"], parsed.utf8.todos[parsedTodoCount], UTF8_TITLE_LENGTH)) return false;
      if (!copyRequiredJsonString(item["title"], todo.title, sizeof(todo.title)) ||
          !copyOptionalJsonString(item["id"], todo.id, sizeof(todo.id))) {
        Serial.println("Scene todo text fields must be strings");
        return false;
      }
      if (!item["done"].isNull() && !item["done"].is<bool>()) {
        Serial.println("Scene todo done must be a boolean");
        return false;
      }
      todo.done = item["done"].isNull() ? false : item["done"].as<bool>();
      ++parsedTodoCount;
    }
    memcpy(parsed.todos, parsedTodos, sizeof(parsed.todos));
    parsed.todoCount = parsedTodoCount;
  }

  if (parsed.page == Page::Interrupt) {
    if (!document["interrupt"].is<JsonObjectConst>() ||
        !copyRequiredJsonString(document["interrupt"]["title"], parsed.interruptTitle,
                                sizeof(parsed.interruptTitle)) ||
        !copyRequiredJsonString(document["interrupt"]["message"], parsed.interruptMessage,
                                sizeof(parsed.interruptMessage)) ||
        !copyOptionalJsonString(document["interrupt"]["detail"], parsed.interruptDetail,
                                sizeof(parsed.interruptDetail))) {
      Serial.println("Interrupt payload contains invalid text fields");
      return false;
    }
  }

  parsed.tibo = TiboDetails{};
  if (parsed.page == Page::Tibo) {
    if (document["protocol_version"].as<int>() != 3 || !document["tibo"].is<JsonObjectConst>()) return false;
    auto field = [&](const char* key, char* target, size_t capacity) {
      JsonVariantConst value = document["tibo"][key];
      if (!value.is<const char*>()) return false;
      const char* str = value.as<const char*>();
      if (strlen(str) >= capacity) return false;
      for (const char* p = str; *p; ++p) if (*p < 32 || *p > 126) return false;
      strlcpy(target, str, capacity);
      return true;
    };
    if (!field("status", parsed.tibo.status, sizeof(parsed.tibo.status)) ||
        !field("kind", parsed.tibo.kind, sizeof(parsed.tibo.kind)) ||
        !field("announced_at", parsed.tibo.announcedAt, sizeof(parsed.tibo.announcedAt)) ||
        !field("pending", parsed.tibo.pending, sizeof(parsed.tibo.pending)) ||
        !field("forecast_status", parsed.tibo.forecastStatus, sizeof(parsed.tibo.forecastStatus))) return false;
    if (!parseOptionalInt(document["tibo"]["p24"], parsed.tibo.p24, 0, 100) ||
        !parseOptionalInt(document["tibo"]["p48"], parsed.tibo.p48, 0, 100) ||
        !parseOptionalInt(document["tibo"]["p72"], parsed.tibo.p72, 0, 100)) return false;
    if (strcmp(parsed.tibo.forecastStatus, "FRESH") != 0) {
      parsed.tibo.p24 = parsed.tibo.p48 = parsed.tibo.p72 = -1;
    }
  }

  // Commit only after the complete candidate validates.
  scene = parsed;
  return true;
}

bool isHubConfigured() {
  return HUB_URL[0] != '\0';
}

HubFetchResult fetchHubScene(HubSceneData& scene) {
  if (!isHubConfigured()) {
    return {HubFetchStatus::NotConfigured, 0};
  }

  HTTPClient http;
  const String endpoint = String(HUB_URL) + "/scene?capabilities=tibo-v1,bitmap-titles-v1";
  http.setConnectTimeout(3000);
  http.setTimeout(5000);
  if (!http.begin(endpoint)) {
    Serial.println("Could not open Hub connection");
    return {HubFetchStatus::ConnectionFailed, 0};
  }

  const int statusCode = http.GET();
  if (statusCode != HTTP_CODE_OK) {
    Serial.print("Hub /scene failed: ");
    Serial.println(statusCode);
    http.end();
    return {HubFetchStatus::HttpError, statusCode};
  }

  const String payload = http.getString();
  http.end();
  if (!parseHubScenePayload(payload, scene)) {
    return {HubFetchStatus::InvalidPayload, statusCode};
  }
  return {HubFetchStatus::Success, statusCode};
}
