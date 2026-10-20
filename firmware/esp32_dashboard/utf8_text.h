// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Copy whole UTF-8 code points only. Display truncation never changes Todo Core.
inline void copyUtf8(char* target, size_t capacity, const char* source) {
  if (!capacity) return;
  size_t used = 0;
  while (*source) {
    const uint8_t lead = static_cast<uint8_t>(*source);
    const size_t width = lead < 0x80 ? 1 : lead < 0xe0 ? 2 : lead < 0xf0 ? 3 : 4;
    size_t valid = 1;
    while (valid < width && source[valid] &&
           (static_cast<uint8_t>(source[valid]) & 0xc0) == 0x80) ++valid;
    if (valid != width || used + width >= capacity) break;
    memcpy(target + used, source, width);
    used += width;
    source += width;
  }
  target[used] = '\0';
}

inline void removeLastUtf8(char* value) {
  size_t length = strlen(value);
  if (!length) return;
  do { --length; } while (length && (static_cast<uint8_t>(value[length]) & 0xc0) == 0x80);
  value[length] = '\0';
}
