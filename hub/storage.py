# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Small atomic JSON storage used by the V0 Hub."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: Path, default: dict[str, Any]) -> None:
        self.path = path
        self.default = default

    def read(self) -> dict[str, Any]:
        try:
            with self.path.open(encoding="utf-8") as source:
                value = json.load(source)
        except FileNotFoundError:
            return deepcopy(self.default)
        if not isinstance(value, dict):
            raise ValueError(f"{self.path.name} must contain a JSON object")
        return value

    def write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self.path)
