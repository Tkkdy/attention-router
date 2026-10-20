# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""M2 business inputs. Field omission is distinct from explicit clearing."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CurrentItem(StrictInput):
    display_title: str | None = Field(default=None, max_length=63)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,23}$")
    title: str = Field(min_length=1, max_length=33)

    @field_validator("title")
    @classmethod
    def device_title(cls, value):
        if not value.strip() or not value.isascii():
            raise ValueError("current panel requires non-blank ASCII text")
        return value


class Suggestion(StrictInput):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    text: str = Field(min_length=1, max_length=47)
    expires_at: datetime | None = None

    @field_validator("text")
    @classmethod
    def device_text(cls, value):
        if not value.strip() or not value.isascii():
            raise ValueError("current panel requires non-blank ASCII text")
        return value

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("timestamp requires timezone")
        return value


class WorkspaceSync(StrictInput):
    revision: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=100)
    project: str | None = Field(default=None, max_length=47)
    current_item: CurrentItem | None = None
    suggestions: list[Suggestion] | None = Field(default=None, max_length=20)
    provenance: Literal["SIMULATED", "USER"] = "SIMULATED"

    @field_validator("project")
    @classmethod
    def device_text(cls, value):
        if value is not None and (not value.strip() or not value.isascii()):
            raise ValueError("project must be non-blank ASCII or null to clear")
        return value

    @model_validator(mode="after")
    def validate_suggestions(self):
        if "suggestions" in self.model_fields_set and self.suggestions is None:
            raise ValueError("omit suggestions to preserve; [] clears")
        if self.suggestions and len({s.id for s in self.suggestions}) != len(self.suggestions):
            raise ValueError("suggestion IDs must be unique")
        return self


class ContextOverride(StrictInput):
    mode: Literal["AUTO", "CODING", "IDLE", "QUIET"]
    expires_at: datetime | None = None
    provenance: Literal["USER", "SIMULATED"] = "USER"

    @field_validator("expires_at")
    @classmethod
    def aware(cls, value):
        if value and value.tzinfo is None:
            raise ValueError("timestamp requires timezone")
        return value


# Phase 2 capability inputs: immutable identity/source metadata belongs to Hub.
MCPRequestID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
ExpectedRevision = Annotated[int, Field(ge=0, strict=True)]
DeviceTitle = Annotated[str, Field(min_length=1, max_length=33, pattern=r"^[ -~]+$"),
                        AfterValidator(CurrentItem.device_title)]
DeviceProject = Annotated[str, Field(min_length=1, max_length=47, pattern=r"^[ -~]+$"),
                          AfterValidator(WorkspaceSync.device_text)]
TodoID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,23}$")]
TodoStatus = Literal["pending", "done", "cancelled"]


class TodoUpsert(StrictInput):
    request_id: MCPRequestID
    expected_revision: ExpectedRevision
    title: DeviceTitle
    todo_id: TodoID | None = None
    # Null/omitted preserves status on update; creates default to pending.
    status: TodoStatus | None = None


class CurrentItemSet(StrictInput):
    request_id: MCPRequestID
    expected_revision: ExpectedRevision
    title: DeviceTitle
    # Null/omitted preserves project, never clears it.
    project: DeviceProject | None = None


def quota_view(sample: dict, now: datetime) -> dict:
    """Display real windows independently; a stored sample is never labelled live."""
    metadata = {key: sample[key] for key in ("last_attempt_at", "last_success_at", "last_error", "consecutive_failures") if key in sample}
    result = {"status": "UNKNOWN", "collection": sample.get("collection", "NOT_CONNECTED"), "windows": [], "updated_at": None, **metadata}
    if sample.get("source") not in {"codex_app_server", "SIMULATED"} or not sample.get("updated_at"):
        return result
    try:
        observed = datetime.fromisoformat(sample["updated_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or observed > now:
            return result
        raw = sample["windows"]
        if not isinstance(raw, list) or any(not isinstance(w, dict) for w in raw):
            return result
        for duration in (300, 10080):
            window = next((w for w in raw if w.get("windowDurationMins") == duration), None)
            remaining = None
            if window and isinstance(window.get("usedPercent"), (int, float)) and not isinstance(window["usedPercent"], bool) and 0 <= window["usedPercent"] <= 100:
                remaining = 100 - window["usedPercent"]
            stale = (now - observed).total_seconds() > 300 or sample.get("collection") == "DEGRADED"
            if window and isinstance(window.get("resetsAt"), (int, float)) and now.timestamp() >= window["resetsAt"]:
                stale = True
            result["windows"].append({"window_minutes": duration, "remaining_percent": remaining,
                "status": "UNKNOWN" if remaining is None else "STALE" if stale else "SNAPSHOT",
                "sampled_at": sample.get("last_attempt_at", sample["updated_at"]),
                "last_success_at": sample["updated_at"] if remaining is not None else None,
                "resets_at": window.get("resetsAt") if window else None})
        result.update(status="STALE" if sample.get("collection") == "DEGRADED" else "SNAPSHOT", collection=sample.get("collection", "SNAPSHOT_ONLY"), updated_at=sample["updated_at"], source=sample["source"])
    except (ValueError, TypeError, KeyError):
        return {"status": "UNKNOWN", "collection": "NOT_CONNECTED", "windows": [], "updated_at": None}
    return result
