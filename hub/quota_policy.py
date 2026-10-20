# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""One local account's display preferences; independent of polling and firmware."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class QuotaPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_plan: Literal["pro", "plus", "unknown"] | None = None
    # null restores the plan preset; absence preserves the existing override.
    five_hour_override: bool | None = None

    @model_validator(mode="after")
    def valid_plan(self):
        if "manual_plan" in self.model_fields_set and self.manual_plan is None:
            raise ValueError("manual_plan must be pro, plus or unknown")
        return self


def display_policy(preferences: dict, sample: dict, *, default_plan="pro") -> dict:
    # This user's Pro plan was explicitly confirmed; no missing-window inference.
    trusted = sample.get("source") == "codex_app_server"
    native_plan = sample.get("planType") if trusted else None
    recognized = native_plan if native_plan in {"pro", "plus"} else None
    plan = recognized or preferences.get("manual_plan", default_plan)
    source = "VERIFIED_PROVIDER" if recognized else "USER_SELECTED" if "manual_plan" in preferences else "USER_CONFIRMED" if default_plan != "unknown" else "UNKNOWN"
    override = preferences.get("five_hour_override")
    preset = False if plan == "pro" else True if plan == "plus" else None
    enabled = override if override is not None else preset
    support = sample.get("window_support", {}).get("300") if trusted and isinstance(sample.get("window_support"), dict) else None
    applicability = "NOT_APPLICABLE" if support is False else "APPLICABLE" if support is True else "UNKNOWN"
    raw_windows = sample.get("windows", [])
    if applicability == "UNKNOWN" and trusted and isinstance(raw_windows, list) and any(isinstance(w, dict) and w.get("windowDurationMins") == 300 for w in raw_windows):
        applicability = "APPLICABLE"
    if override is False:
        reason = "USER_DISABLED"
    elif applicability == "NOT_APPLICABLE":
        reason = "PLAN_NOT_APPLICABLE"
    elif enabled is False:
        reason = "PLAN_PRESET_DISABLED"
    elif enabled is None:
        reason = "PLAN_UNKNOWN"
    else:
        reason = "ENABLED"
    visible = reason == "ENABLED"
    return {"plan": plan, "plan_source": source, "preset_enabled": preset,
            "five_hour_override": override, "five_hour": {"visible": visible, "reason": reason, "applicability": applicability,
            "alerts_enabled": visible and applicability != "NOT_APPLICABLE"}, "seven_day": {"visible": True}}
