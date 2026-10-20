// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once

#include "Arduino.h"
#include <json-c/json.h>
#include <cstdint>
#include <type_traits>
#include <limits>

struct JsonObjectConst {};
struct DeserializationError;
class JsonVariantConst;

class JsonArrayConst {
 public:
  explicit JsonArrayConst(json_object* value = nullptr) : value_(value) {}

  class iterator {
   public:
    iterator(json_object* array, size_t index) : array_(array), index_(index) {}
    JsonVariantConst operator*() const;
    iterator& operator++() { ++index_; return *this; }
    bool operator!=(const iterator& other) const {
      return array_ != other.array_ || index_ != other.index_;
    }
   private:
    json_object* array_;
    size_t index_;
  };

  iterator begin() const { return iterator(value_, 0); }
  iterator end() const {
    return iterator(value_, value_ && json_object_is_type(value_, json_type_array)
                                ? json_object_array_length(value_) : 0);
  }

 private:
  json_object* value_;
};

class JsonVariantConst {
 public:
  explicit JsonVariantConst(json_object* value = nullptr) : value_(value) {}

  JsonVariantConst operator[](const char* key) const {
    if (!value_ || !json_object_is_type(value_, json_type_object)) return JsonVariantConst();
    json_object* child = nullptr;
    return json_object_object_get_ex(value_, key, &child) ? JsonVariantConst(child)
                                                          : JsonVariantConst();
  }

  bool isNull() const {
    return value_ == nullptr || json_object_is_type(value_, json_type_null);
  }

  template <typename T>
  bool is() const {
    if constexpr (std::is_same_v<T, const char*>) {
      return value_ && json_object_is_type(value_, json_type_string);
    } else if constexpr (std::is_same_v<T, bool>) {
      return value_ && json_object_is_type(value_, json_type_boolean);
    } else if constexpr (std::is_same_v<T, int>) {
      return value_ && json_object_is_type(value_, json_type_int);
    } else if constexpr ((std::is_same_v<T, uint16_t> || std::is_same_v<T, uint32_t>)) {
      return value_ && json_object_is_type(value_, json_type_int) &&
             json_object_get_int64(value_) >= 0 &&
             json_object_get_int64(value_) <= std::numeric_limits<T>::max();
    } else if constexpr (std::is_same_v<T, JsonArrayConst>) {
      return value_ && json_object_is_type(value_, json_type_array);
    } else if constexpr (std::is_same_v<T, JsonObjectConst>) {
      return value_ && json_object_is_type(value_, json_type_object);
    } else {
      return false;
    }
  }

  template <typename T>
  T as() const {
    if constexpr (std::is_same_v<T, const char*>) {
      return is<const char*>() ? json_object_get_string(value_) : nullptr;
    } else if constexpr (std::is_same_v<T, bool>) {
      return is<bool>() ? json_object_get_boolean(value_) != 0 : false;
    } else if constexpr (std::is_same_v<T, int>) {
      return is<int>() ? json_object_get_int(value_) : 0;
    } else if constexpr ((std::is_same_v<T, uint16_t> || std::is_same_v<T, uint32_t>)) {
      return is<uint32_t>() ? static_cast<T>(json_object_get_int64(value_)) : 0;
    } else if constexpr (std::is_same_v<T, JsonArrayConst>) {
      return JsonArrayConst(is<JsonArrayConst>() ? value_ : nullptr);
    } else {
      return T{};
    }
  }

 private:
  json_object* value_;
};

inline JsonVariantConst JsonArrayConst::iterator::operator*() const {
  if (!array_ || !json_object_is_type(array_, json_type_array)) return JsonVariantConst();
  return JsonVariantConst(json_object_array_get_idx(array_, index_));
}

class JsonDocument {
 public:
  JsonDocument() = default;
  ~JsonDocument() { if (root_) json_object_put(root_); }
  JsonDocument(const JsonDocument&) = delete;
  JsonDocument& operator=(const JsonDocument&) = delete;

  JsonVariantConst operator[](const char* key) const {
    return JsonVariantConst(root_)[key];
  }

 private:
  json_object* root_ = nullptr;
  friend struct DeserializationError;
  friend DeserializationError deserializeJson(JsonDocument&, const String&);
};

struct DeserializationError {
  bool failed = false;
  const char* message = "";
  explicit operator bool() const { return failed; }
  const char* c_str() const { return message; }
};

inline DeserializationError deserializeJson(JsonDocument& document, const String& payload) {
  if (document.root_) {
    json_object_put(document.root_);
    document.root_ = nullptr;
  }
  json_tokener* tokener = json_tokener_new();
  json_object* parsed = json_tokener_parse_ex(tokener, payload.c_str(), payload.size());
  const json_tokener_error error = json_tokener_get_error(tokener);
  if (error != json_tokener_success || parsed == nullptr) {
    const char* description = json_tokener_error_desc(error);
    json_tokener_free(tokener);
    if (parsed) json_object_put(parsed);
    return {true, description};
  }
  json_tokener_free(tokener);
  document.root_ = parsed;
  return {};
}
