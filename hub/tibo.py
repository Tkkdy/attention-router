# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Optional public reset feeds. No account data; no network on request paths."""
from __future__ import annotations

import asyncio
from async_worker import run_worker
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, StrictBool

URLS = {"events": "https://codex-resets.com/api/v1/status",
        "forecast": "https://nextreset.ai/api/forecast"}
POLL_SECONDS = 300
MAX_BYTES = 512 * 1024


def now_utc():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result.astimezone(timezone.utc)


def iso(value):
    return value.isoformat(timespec="seconds")


def source_url(value):
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("missing source link")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"x.com", "twitter.com"} or parsed.username or parsed.password:
        raise ValueError("invalid source link")
    return value


def parse_events(payload, now):
    generated = timestamp(payload["meta"]["generated_at"])
    if generated > now + timedelta(minutes=2) or now - generated > timedelta(minutes=15):
        raise ValueError("stale event feed")
    data = payload["data"]
    if not isinstance(data, dict) or "latest_reset" not in data or "scheduled_reset" not in data:
        raise ValueError("missing event fields")
    latest = data["latest_reset"]
    record = None
    if latest is not None:
        announced = timestamp(latest["announced_at"])
        if announced > now + timedelta(minutes=2):
            raise ValueError("future completed record")
        kind = latest["reset_type"]
        if kind not in {"regular", "banked"}:
            raise ValueError("unknown reset kind")
        record = {"announced_at": iso(announced), "kind": kind,
                  "source_url": source_url(latest["source"]["url"])}
    pending = data["scheduled_reset"]
    pending_url = None
    if pending is not None:
        if not isinstance(pending, dict):
            raise ValueError("invalid pending record")
        pending_url = source_url(pending["source"]["url"])
    return {"generated_at": iso(generated), "expires_at": iso(generated + timedelta(minutes=15)),
            "latest": record, "pending": pending is not None, "pending_url": pending_url}


def parse_forecast(payload, now):
    generated, expires = timestamp(payload["asOf"]), timestamp(payload["expiresAt"])
    if generated > now + timedelta(minutes=2) or generated >= expires or expires <= now:
        raise ValueError("expired forecast")
    if now - generated > timedelta(minutes=15) or expires - generated > timedelta(hours=1):
        raise ValueError("invalid forecast window")
    if type(payload.get("degraded")) is not bool or payload["degraded"]:
        raise ValueError("degraded forecast")
    if payload["checks"]["history"].get("ok") is not True:
        raise ValueError("unverified forecast history")
    chances = {}
    for window in payload["windows"]:
        hours, chance = window["hours"], window["probability"]
        if type(hours) is not int or hours not in {24, 48, 72} or str(hours) in chances:
            raise ValueError("invalid horizon")
        if type(chance) not in (int, float) or not math.isfinite(chance) or not 0 <= chance <= 1:
            raise ValueError("invalid probability")
        chances[str(hours)] = round(chance * 100)
    if set(chances) != {"24", "48", "72"} or not chances["24"] <= chances["48"] <= chances["72"]:
        raise ValueError("incomplete forecast")
    version = payload.get("version")
    if not isinstance(version, str) or not version or len(version) > 50:
        raise ValueError("invalid model version")
    return {"generated_at": iso(generated), "expires_at": iso(expires),
            "probabilities": chances, "model": version}


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ESP32-Dashboard-Hub/0.3",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as response:
        if response.status != 200 or "application/json" not in response.headers.get("Content-Type", ""):
            raise ValueError("expected JSON response")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("response too large")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("expected object")
    return data


class TiboPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    forecast_enabled: StrictBool = False
    show_page: StrictBool = False


class TiboModule:
    def __init__(self, db, *, reader=fetch_json, clock=now_utc):
        self.db, self.reader, self.clock = db, reader, clock

    def preferences(self):
        return {"enabled": False, "forecast_enabled": False, "show_page": False,
                "generation": 0, **self.db.read("tibo_preferences")}

    def configure(self, command):
        with self.db.transaction():
            old = self.preferences()
            new = {**old, **command.model_dump()}
            if not new["enabled"]:
                new["show_page"] = False
            if any(old[key] != new[key] for key in ("enabled", "forecast_enabled")):
                new["generation"] += 1
            self.db.write("tibo_preferences", new)
        return self.view()

    @staticmethod
    def active(prefs, source):
        return prefs["enabled"] and (source == "events" or prefs["forecast_enabled"])

    def sample(self, source):
        prefs = self.preferences()
        if not self.active(prefs, source):
            return POLL_SECONDS
        now = self.clock()
        old = self.db.read("tibo_" + source)
        retry_at = old.get("retry_at")
        if retry_at and timestamp(retry_at) > now:
            return max(1, int((timestamp(retry_at) - now).total_seconds()))
        delay = POLL_SECONDS
        try:
            data = self.reader(URLS[source])
            parser = parse_events if source == "events" else parse_forecast
            sample = parser(data, self.clock())
            record = {"sample": sample, "last_success_at": iso(self.clock()), "error": None,
                      "failures": 0, "generation": prefs["generation"]}
        except Exception as error:
            failures = min(old.get("failures", 0) + 1, 6)
            delay = min(POLL_SECONDS * 2 ** failures, 3600)
            if isinstance(error, urllib.error.HTTPError) and error.code in (429, 503):
                retry = error.headers.get("Retry-After", "") if error.headers else ""
                try:
                    delay = max(delay, int(retry))
                except ValueError:
                    try:
                        delay = max(delay, int((parsedate_to_datetime(retry) - now).total_seconds()))
                    except (ValueError, TypeError, OverflowError):
                        pass
            # Keep the last valid event for reference, but never expose failed/expired probabilities as current.
            record = {**old, "error": type(error).__name__, "failures": failures}
        record["last_attempt_at"] = iso(now)
        record["retry_at"] = iso(self.clock() + timedelta(seconds=delay))
        with self.db.transaction():
            current = self.preferences()
            if current["generation"] == prefs["generation"] and self.active(current, source):
                self.db.write("tibo_" + source, record)
        return delay

    def view(self):
        prefs, now = self.preferences(), self.clock()
        result = {"preferences": {k: prefs[k] for k in ("enabled", "forecast_enabled", "show_page")}}
        for source in URLS:
            record = self.db.read("tibo_" + source)
            sample = record.get("sample")
            fresh = bool(sample and not record.get("error") and record.get("generation") == prefs["generation"]
                         and timestamp(sample["expires_at"]) > now)
            status = "OFF" if not self.active(prefs, source) else "FRESH" if fresh else "STALE" if sample else "UNKNOWN"
            result[source] = {"status": status, "sample": sample,
                              "last_success_at": record.get("last_success_at"), "error": record.get("error")}
            if source == "forecast" and status != "FRESH":
                result[source]["sample"] = None
        return result

    def device(self):
        view = self.view()
        events, forecast = view["events"], view["forecast"]
        sample = events["sample"] or {}
        latest = sample.get("latest") or {}
        chances = (forecast["sample"] or {}).get("probabilities", {})
        return {"status": events["status"], "kind": latest.get("kind", "UNKNOWN").upper(),
                "announced_at": latest.get("announced_at", "UNKNOWN")[:19],
                "pending": ("ANNOUNCED" if sample.get("pending") else "NO ANNOUNCEMENT") if events["status"] == "FRESH" else "UNKNOWN",
                "forecast_status": forecast["status"],
                "p24": chances.get("24"), "p48": chances.get("48"), "p72": chances.get("72")}

    async def _run_source(self, source):
        # Each provider has its own worker; slow requests cannot block context, Scene or the other feed.
        while True:
            try:
                # sample() already checks preferences before any provider IO.
                # Include that DB read in the worker even when Tibo is disabled.
                await run_worker(self.sample, source)
            except Exception:
                # Storage/provider failure is isolated to this optional feature.
                pass
            await asyncio.sleep(5)

    async def run(self):
        await asyncio.gather(*(self._run_source(source) for source in URLS))
