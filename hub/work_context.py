# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Privacy-limited work sessions. Titles are classified in memory, never retained."""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator
from context_monitor import ForegroundSample, SAMPLE_ERRORS

class WorkSessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enter_seconds: float = Field(default=120, gt=0)
    continuation_seconds: float = Field(default=600, gt=0)
    exit_seconds: float = Field(default=900, gt=0)
    idle_seconds: float = Field(default=900, gt=0)
    max_sample_gap: float = Field(default=15, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.continuation_seconds > self.exit_seconds:
            raise ValueError("continuation must not exceed session expiry")
        return self


def classify(sample):
    process = sample.process.casefold()
    if sample.application == "codex_desktop" or process == "codex.exe":
        return "Codex", "strong"
    if process in {"grok bot.exe", "grokbot.exe"}:
        return "GrokBot", "strong"
    if process in {"deepseek bot.exe", "deepseek-bot.exe"}:
        return "DeepSeek Bot", "strong"
    if process in {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe"}:
        # Only an explicit app/site marker. No conversation title is saved.
        if sample.site_marker == "chatgpt_web":
            return "ChatGPT Web", "strong"
        title = sample.title.casefold()
        if re.search(r"(?:^|[|–—-]\s*)chatgpt(?:$|\s*[-–—|])", title) or title.startswith("chatgpt -"):
            return "ChatGPT Web", "strong"
        if re.search(r"(?:^|[|–—-]\s*)deepseek bot(?:$|\s*[-–—|])", title):
            return "DeepSeek Bot", "strong"
        return "Browser", "continuation"
    return sample.process, "continuation"


class WorkContext:
    def __init__(self, enter_seconds=120, exit_seconds=900, max_sample_gap=15, *, config=None):
        self.config = config or WorkSessionConfig(enter_seconds=enter_seconds, exit_seconds=exit_seconds,
            continuation_seconds=min(600, exit_seconds), max_sample_gap=max_sample_gap)
        self.enter_seconds, self.exit_seconds = self.config.enter_seconds, self.config.exit_seconds
        self.max_sample_gap = self.config.max_sample_gap
        self.state = "UNKNOWN"
        self.candidate_since = self.last_sample = self.last_strong = None
        self.session_id = self.started_at = self.started_clock = None
        self.last_strong_at = self.last_strong_app = None
        self.last_successful_sample = None

    def update(self, sample: ForegroundSample | None, *, now=None, error=None, sampled_at=None):
        now = time.monotonic() if now is None else now
        sampled_at = sampled_at or datetime.now(timezone.utc).isoformat()
        gap = self.last_sample is not None and now - self.last_sample > self.max_sample_gap
        self.last_sample = now
        unknown = "sample_gap" if gap else None
        valid = sample is not None and bool(sample.process)
        error_category = None if valid else (error if error in SAMPLE_ERRORS else "FOREGROUND_UNAVAILABLE" if not error else "SAMPLER_INTERNAL_ERROR")
        if gap or not valid:
            # Incomplete observation breaks entry evidence, not an established session.
            self.candidate_since = None
        if valid:
            self.last_successful_sample = sampled_at
        age = now - self.last_strong if self.last_strong is not None else None
        expired = bool(self.session_id and age is not None and age >= self.exit_seconds)
        if expired:
            self.session_id = self.started_at = self.started_clock = None
            self.candidate_since = None
        app, category = classify(sample) if valid else (None, "unknown")
        if not valid:
            unknown = error_category
            if self.session_id:
                self.state, reason = "CODING", "sampling_degraded_session_retained"
            elif expired:
                self.state, reason = "IDLE", "no_strong_signal_timeout"
            else:
                self.state, reason = "UNKNOWN", "foreground_unavailable"
        elif sample.idle_seconds >= self.config.idle_seconds:
            self.state, reason = "IDLE", "windows_idle"
            self.candidate_since = self.session_id = self.started_at = self.started_clock = None
        elif category == "strong":
            self.last_strong, self.last_strong_at, self.last_strong_app = now, sampled_at, app
            if self.candidate_since is None:
                self.candidate_since = now
            if self.session_id or now - self.candidate_since >= self.enter_seconds:
                if not self.session_id:
                    self.session_id, self.started_at, self.started_clock = uuid4().hex, sampled_at, now
                self.state, reason = "CODING", "active_work_session"
            else:
                self.state, reason = "IDLE", "entry_threshold_pending"
        else:
            self.candidate_since = None
            age = now - self.last_strong if self.last_strong is not None else None
            if self.session_id and age is not None and age < self.exit_seconds:
                self.state = "CODING"
                reason = "session_continuation" if age <= self.config.continuation_seconds else "session_grace_period"
            else:
                self.state = "IDLE"
                reason = "no_strong_signal_timeout" if expired else "no_work_session"
                self.session_id = self.started_at = self.started_clock = None
        return {"automatic": self.state, "reason": reason, "transition_reason": reason,
            "unknown_reason": unknown, "error_category": error_category,
            "last_successful_sample": self.last_successful_sample, "foreground_process": sample.process if sample else None,
            "application": sample.application if sample else None,
            "idle_seconds": round(sample.idle_seconds, 1) if sample else None,
            "continuous_seconds": round(now-self.candidate_since, 1) if self.candidate_since is not None else 0,
            "enter_seconds": self.enter_seconds, "exit_seconds": self.exit_seconds, "project_inferred": False,
            "session_state": "ACTIVE" if self.session_id else ("UNKNOWN" if self.state == "UNKNOWN" else "INACTIVE"),
            "session_id": self.session_id, "work_session_started_at": self.started_at,
            "work_session_seconds": round(now-self.started_clock, 1) if self.started_clock is not None else 0,
            "last_strong_work_signal": {"app": self.last_strong_app, "at": self.last_strong_at,
                "age_seconds": round(now-self.last_strong, 1) if self.last_strong is not None else None},
            "current_foreground_app": app, "current_app_category": category,
            "manual_override": "AUTO", "sampled_at": sampled_at}
