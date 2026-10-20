# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Morning Radar public-status adapter with explicit freshness validation."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import os
RADAR_URL = os.environ.get("ATTENTION_RADAR_URL", "")
SINGAPORE_TZ = timezone(timedelta(hours=8))
DEVICE_DETAIL_MAX = 47


@dataclass(frozen=True)
class RadarResult:
    status: str
    run_date: str
    updated_at: str | None
    detail: str | None


def _optional_string(payload: dict[str, Any], key: str, *, max_length: int | None = None) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Radar {key} must be a string or null")
    if max_length is not None and len(value.encode("ascii", errors="strict")) > max_length:
        raise ValueError(f"Radar {key} exceeds device text capacity")
    if max_length is not None:
        try:
            value.encode("ascii")
        except UnicodeEncodeError as error:
            raise ValueError(f"Radar {key} must be ASCII for the current panel font") from error
    return value


def fetch_radar(
    url: str = RADAR_URL,
    timeout: float = 8,
    *,
    now: datetime | None = None,
) -> RadarResult:
    if not url:
        raise ValueError("Optional Radar source is not configured")
    separator = "&" if urllib.parse.urlsplit(url).query else "?"
    cache_key = int(time.time() // 300)
    request = urllib.request.Request(
        f"{url}{separator}poll={cache_key}", headers={"User-Agent": "ESP32-Dashboard-Hub/0.2"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Radar response must be a JSON object")

    raw_status = payload.get("status")
    if not isinstance(raw_status, str):
        raise ValueError("Radar status must be a string")
    status = raw_status.upper()
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError("Radar status must be SUCCESS or FAILED")

    run_date = payload.get("run_date")
    if not isinstance(run_date, str):
        raise ValueError("Radar run_date must be a string")
    current = (now or datetime.now(timezone.utc)).astimezone(SINGAPORE_TZ).date().isoformat()
    if run_date != current:
        raise ValueError(f"Radar run_date must match current Singapore date {current}")

    updated_at = _optional_string(payload, "updated_at")
    detail = _optional_string(payload, "detail", max_length=DEVICE_DETAIL_MAX)
    return RadarResult(status, run_date, updated_at, detail)
