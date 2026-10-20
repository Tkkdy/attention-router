// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

// The cache stores only the Hub-owned Todo subset. A missing or invalid cache
// is represented by an empty list, never by a UI-facing error state.
bool loadTodoCache(Todo (&todos)[MAX_TODOS], uint8_t& todoCount);
bool saveTodoCacheIfChanged(const Todo (&todos)[MAX_TODOS], uint8_t todoCount);
