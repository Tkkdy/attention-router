// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
#pragma once

#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

extern std::unordered_map<std::string, std::vector<unsigned char>> fakeNvs;
extern int fakeNvsWrites;

struct Preferences {
  std::string nameSpace;
  bool readonly = true;
  bool begin(const char* name, bool readOnly) {
    nameSpace = name;
    readonly = readOnly;
    return true;
  }
  void end() {}
  std::string storageKey(const char* key) const { return nameSpace + "/" + key; }
  size_t getBytesLength(const char* key) const {
    auto found = fakeNvs.find(storageKey(key));
    return found == fakeNvs.end() ? 0 : found->second.size();
  }
  size_t getBytes(const char* key, void* destination, size_t length) const {
    auto found = fakeNvs.find(storageKey(key));
    if (found == fakeNvs.end() || found->second.size() != length) return 0;
    std::memcpy(destination, found->second.data(), length);
    return length;
  }
  size_t putBytes(const char* key, const void* source, size_t length) {
    if (readonly) return 0;
    const auto* bytes = static_cast<const unsigned char*>(source);
    fakeNvs[storageKey(key)] = std::vector<unsigned char>(bytes, bytes + length);
    ++fakeNvsWrites;
    return length;
  }
};
