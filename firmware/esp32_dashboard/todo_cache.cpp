// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#include "todo_cache.h"

#include <Preferences.h>
#include <stddef.h>
#include <string.h>

namespace {

constexpr char NVS_NAMESPACE[] = "todo_cache";
constexpr char NVS_KEY[] = "record";
constexpr uint32_t CACHE_MAGIC = 0x544F444FUL;  // TODO
constexpr uint16_t CACHE_VERSION = 1;

struct CachedTodo {
  char id[SHORT_TEXT_LENGTH];
  char title[TODO_TITLE_LENGTH];
  uint8_t done;
};

struct TodoCacheRecord {
  uint32_t magic;
  uint16_t version;
  uint8_t count;
  uint8_t reserved;
  CachedTodo todos[MAX_TODOS];
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

bool hasTerminator(const char* text, size_t length) {
  return memchr(text, '\0', length) != nullptr;
}

bool isValid(const TodoCacheRecord& record) {
  if (record.magic != CACHE_MAGIC || record.version != CACHE_VERSION ||
      record.count > MAX_TODOS) {
    return false;
  }
  if (checksum(reinterpret_cast<const uint8_t*>(&record),
               offsetof(TodoCacheRecord, checksum)) != record.checksum) {
    return false;
  }
  for (uint8_t index = 0; index < record.count; ++index) {
    const CachedTodo& todo = record.todos[index];
    if (!hasTerminator(todo.id, sizeof(todo.id)) ||
        !hasTerminator(todo.title, sizeof(todo.title)) ||
        todo.title[0] == '\0' || todo.done > 1) {
      return false;
    }
  }
  return true;
}

TodoCacheRecord makeRecord(const Todo (&todos)[MAX_TODOS], uint8_t todoCount) {
  TodoCacheRecord record{};
  record.magic = CACHE_MAGIC;
  record.version = CACHE_VERSION;
  record.count = todoCount > MAX_TODOS ? MAX_TODOS : todoCount;
  for (uint8_t index = 0; index < record.count; ++index) {
    strlcpy(record.todos[index].id, todos[index].id,
            sizeof(record.todos[index].id));
    strlcpy(record.todos[index].title, todos[index].title,
            sizeof(record.todos[index].title));
    record.todos[index].done = todos[index].done ? 1 : 0;
  }
  record.checksum = checksum(reinterpret_cast<const uint8_t*>(&record),
                             offsetof(TodoCacheRecord, checksum));
  return record;
}

bool sameTodos(const TodoCacheRecord& left, const TodoCacheRecord& right) {
  return left.count == right.count &&
         memcmp(left.todos, right.todos, sizeof(left.todos)) == 0;
}

}  // namespace

bool loadTodoCache(Todo (&todos)[MAX_TODOS], uint8_t& todoCount) {
  todoCount = 0;
  memset(todos, 0, sizeof(todos));

  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, true)) {
    Serial.println("Todo cache unavailable");
    return false;
  }
  if (preferences.getBytesLength(NVS_KEY) != sizeof(TodoCacheRecord)) {
    preferences.end();
    return false;
  }

  TodoCacheRecord record{};
  const size_t read = preferences.getBytes(NVS_KEY, &record, sizeof(record));
  preferences.end();
  if (read != sizeof(record) || !isValid(record)) {
    Serial.println("Todo cache ignored: invalid record");
    return false;
  }

  todoCount = record.count;
  for (uint8_t index = 0; index < todoCount; ++index) {
    strlcpy(todos[index].id, record.todos[index].id, sizeof(todos[index].id));
    strlcpy(todos[index].title, record.todos[index].title,
            sizeof(todos[index].title));
    todos[index].done = record.todos[index].done == 1;
  }
  Serial.print("Todo cache restored: ");
  Serial.println(todoCount);
  return true;
}

bool saveTodoCacheIfChanged(const Todo (&todos)[MAX_TODOS], uint8_t todoCount) {
  const TodoCacheRecord next = makeRecord(todos, todoCount);
  Preferences preferences;
  if (!preferences.begin(NVS_NAMESPACE, false)) {
    Serial.println("Todo cache unavailable");
    return false;
  }

  TodoCacheRecord current{};
  const bool hasValidCurrent =
      preferences.getBytesLength(NVS_KEY) == sizeof(current) &&
      preferences.getBytes(NVS_KEY, &current, sizeof(current)) == sizeof(current) &&
      isValid(current);
  if (hasValidCurrent && sameTodos(current, next)) {
    preferences.end();
    Serial.print("Todo cache unchanged; skip NVS write: ");
    Serial.println(next.count);
    return true;
  }

  const size_t written = preferences.putBytes(NVS_KEY, &next, sizeof(next));
  preferences.end();
  if (written != sizeof(next)) {
    Serial.println("Todo cache write failed");
    return false;
  }
  Serial.print("Todo cache updated: ");
  Serial.println(next.count);
  return true;
}
