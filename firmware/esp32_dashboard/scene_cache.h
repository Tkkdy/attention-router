// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: GPL-3.0-only
#pragma once

#include "scene.h"

bool loadLastScene(Scene& scene);
bool loadStandaloneHome(Scene& scene);
bool saveLastSceneIfChanged(const Scene& scene);
bool saveStandaloneHomeIfChanged(const Scene& scene);
