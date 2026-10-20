# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Milestone 4 Personal Dashboard Hub."""

from __future__ import annotations

import asyncio
from async_worker import run_worker
import hashlib
import json
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from context_monitor import ContextDetector, read_foreground
from radar_client import fetch_radar
from storage import JsonStore

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / ".build" / "preview-data"

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "visible_hash": "",
    "context": "IDLE",
    "foreground": {"process": "", "title": "", "idle_seconds": 0},
    "codex": {"quota_5h_remaining": 100, "quota_total_remaining": 100, "updated_at": None},
    "radar": {"status": "SUCCESS", "updated_at": None, "detail": None, "stale": True},
}
DEFAULT_TASKS: dict[str, Any] = {"tasks": []}

DEVICE_TODO_TITLE_MAX = 33
DEVICE_LONG_TEXT_MAX = 47
MIN_DELIVERABLE_INTERRUPT_SECONDS = 35  # 30 s Hub poll + 2 s coalesce + margin


def _device_ascii(value: str, field_name: str) -> str:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be ASCII for the current panel font") from error
    return value


def _fit_device_identifier(value: str) -> str:
    value = _device_ascii(value, "identifier")
    if len(value) <= DEVICE_LONG_TEXT_MAX:
        return value
    return value[: DEVICE_LONG_TEXT_MAX - 3] + "..."


class QuotaUpdate(BaseModel):
    quota_5h_remaining: int = Field(ge=0, le=100)
    quota_total_remaining: int = Field(ge=0, le=100)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=DEVICE_TODO_TITLE_MAX)
    due: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    source: str = "manual"
    source_ref: str | None = None
    ttl: int | None = Field(default=None, ge=0)
    escalation: str | None = None
    namespace: Literal["personal_ops", "project", "reminder"] = "personal_ops"

    @field_validator("title")
    @classmethod
    def title_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must contain text")
        return _device_ascii(value, "title")


class TaskPatch(BaseModel):
    status: Literal["done", "cancelled"]


class InterruptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=DEVICE_LONG_TEXT_MAX)
    message: str = Field(min_length=1, max_length=DEVICE_LONG_TEXT_MAX)
    detail: str = Field(default="", max_length=DEVICE_LONG_TEXT_MAX)
    type: str = Field(default="alert", max_length=30)
    priority: int = Field(default=5, ge=0, le=9)
    behavior: Literal["auto", "until_change", "repeatable"] = "auto"
    duration_seconds: int = Field(default=60, ge=1, le=3600)
    repeat_seconds: int = Field(default=300, ge=2, le=86400)
    starts_at: datetime | None = None
    source: str = Field(default="manual", max_length=40)
    source_ref: str | None = Field(default=None, max_length=80)

    @field_validator("title", "message", "detail")
    @classmethod
    def interrupt_text_must_contain_text(cls, value: str, info: ValidationInfo) -> str:
        value = value.strip()
        if not value and info.field_name in {"title", "message"}:
            raise ValueError("value must contain text")
        if not value:
            return value
        return _device_ascii(value, "interrupt text")

    @model_validator(mode="after")
    def repeat_window_must_fit_cycle(self) -> "InterruptCreate":
        if self.behavior in {"auto", "repeatable"} and self.duration_seconds < MIN_DELIVERABLE_INTERRUPT_SECONDS:
            raise ValueError(
                f"duration_seconds must be at least {MIN_DELIVERABLE_INTERRUPT_SECONDS} "
                "for the device polling/display cadence"
            )
        if self.behavior == "repeatable" and self.duration_seconds >= self.repeat_seconds:
            raise ValueError("repeat_seconds must be greater than duration_seconds")
        return self


class InterruptPatch(BaseModel):
    status: Literal["resolved", "cancelled"]


class ReminderCreate(BaseModel):
    message: str = Field(min_length=1, max_length=DEVICE_LONG_TEXT_MAX)
    delay_seconds: int | None = Field(default=None, ge=1, le=604800)
    due_at: datetime | None = None
    priority: int = Field(default=7, ge=0, le=9)
    behavior: Literal["auto", "repeatable"] = "repeatable"
    duration_seconds: int = Field(default=60, ge=1, le=3600)
    repeat_seconds: int = Field(default=300, ge=2, le=86400)

    @field_validator("message")
    @classmethod
    def reminder_message_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain text")
        return _device_ascii(value, "reminder message")

    @model_validator(mode="after")
    def validate_schedule(self) -> "ReminderCreate":
        if (self.delay_seconds is None) == (self.due_at is None):
            raise ValueError("provide exactly one of delay_seconds or due_at")
        if self.duration_seconds < MIN_DELIVERABLE_INTERRUPT_SECONDS:
            raise ValueError(
                f"duration_seconds must be at least {MIN_DELIVERABLE_INTERRUPT_SECONDS} "
                "for the device polling/display cadence"
            )
        if self.behavior == "repeatable" and self.duration_seconds >= self.repeat_seconds:
            raise ValueError("repeat_seconds must be greater than duration_seconds")
        return self


class StateEvent(BaseModel):
    source: str = Field(default="codex", min_length=1, max_length=40)
    task_id: str = Field(min_length=1, max_length=80)
    state: Literal["RUNNING", "DONE", "WAITING_FOR_USER"]

    @field_validator("source", "task_id")
    @classmethod
    def identifiers_are_device_safe(cls, value: str) -> str:
        return _device_ascii(value, "state-event identifier")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DashboardService:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.state_store = JsonStore(data_dir / "state.json", DEFAULT_STATE)
        self.task_store = JsonStore(data_dir / "tasks.json", DEFAULT_TASKS)
        self.context_detector = ContextDetector()
        self._lock = threading.RLock()

    def state(self) -> dict[str, Any]:
        return self.state_store.read()

    def tasks(self) -> list[dict[str, Any]]:
        return list(self.task_store.read().get("tasks", []))

    @staticmethod
    def _quota_bucket(value: int) -> int:
        return max(0, min(100, value // 5 * 5))

    def _visible_scene(self, state: dict[str, Any]) -> dict[str, Any]:
        radar = state["radar"]
        candidates = self._active_interrupts(state)
        if radar["status"] == "FAILED":
            candidates.append(
                {
                    "id": "radar_failed",
                    "type": "alert",
                    "title": "MORNING RADAR",
                    "message": "FAILED",
                    "detail": radar.get("detail") or "Check pipeline",
                    "priority": 9,
                    "behavior": "until_change",
                    "starts_at": "9999-12-31T23:59:59+00:00",
                    "stale": bool(radar.get("stale", True)),
                }
            )
        if candidates:
            selected = max(candidates, key=lambda event: (event["priority"], event["starts_at"]))
            return {
                "page": "interrupt",
                "interrupt": {
                    key: selected[key]
                    for key in ("id", "type", "title", "message", "detail", "priority", "behavior")
                },
                # Freshness belongs to the data represented by this scene. Local
                # agent/reminder events are current; Radar failures carry Radar freshness.
                "stale": bool(selected.get("stale", False)),
            }
        pending = [task for task in self.tasks() if task.get("status") == "pending"][:3]
        quota = state["codex"]
        return {
            "page": "workspace",
            "context": state["context"],
            "codex": {
                "quota_5h_remaining": self._quota_bucket(quota["quota_5h_remaining"]),
                "quota_total_remaining": self._quota_bucket(quota["quota_total_remaining"]),
            },
            "radar": {"status": radar["status"].lower()},
            "todos": [{"id": task["id"], "title": task["title"], "done": False} for task in pending],
            "stale": bool(radar.get("stale", True)),
        }

    @staticmethod
    def _active_interrupts(state: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        active: list[dict[str, Any]] = []
        for event in state.get("interrupts", []):
            if event.get("status") != "active":
                continue
            try:
                starts_at = as_utc(datetime.fromisoformat(event["starts_at"]))
            except (KeyError, TypeError, ValueError):
                continue
            if now < starts_at:
                continue
            elapsed = (now - starts_at).total_seconds()
            behavior = event.get("behavior")
            if behavior == "until_change":
                active.append(event)
            elif behavior == "auto" and elapsed < event["duration_seconds"]:
                active.append(event)
            elif behavior == "repeatable" and elapsed % event["repeat_seconds"] < event["duration_seconds"]:
                active.append(event)
        return active

    def scene(self) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            visible = self._visible_scene(state)
            digest = hashlib.sha256(
                json.dumps(visible, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            if digest != state.get("visible_hash"):
                state["version"] = int(state.get("version", 0)) + 1
                state["visible_hash"] = digest
                self.state_store.write(state)
            return {"version": state["version"], **visible}

    def update_quota(self, update: QuotaUpdate) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            state["codex"] = {**update.model_dump(), "updated_at": utc_now()}
            self.state_store.write(state)
            return state["codex"]

    def create_task(self, request: TaskCreate) -> dict[str, Any]:
        record = {
            "id": f"task_{uuid4().hex[:10]}",
            "title": request.title,
            "status": "pending",
            "created_at": utc_now(),
            **request.model_dump(exclude={"title"}),
        }
        with self._lock:
            document = self.task_store.read()
            document.setdefault("tasks", []).append(record)
            self.task_store.write(document)
        return record

    def patch_task(self, task_id: str, request: TaskPatch) -> dict[str, Any]:
        with self._lock:
            document = self.task_store.read()
            for task in document.setdefault("tasks", []):
                if task.get("id") == task_id:
                    task["status"] = request.status
                    task["updated_at"] = utc_now()
                    self.task_store.write(document)
                    return task
        raise KeyError(task_id)

    @staticmethod
    def _interrupt_record(request: InterruptCreate, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        starts_at = as_utc(request.starts_at) if request.starts_at else now
        return {
            "id": f"event_{uuid4().hex[:10]}",
            **request.model_dump(mode="json", exclude={"starts_at"}),
            "starts_at": starts_at.isoformat(timespec="seconds"),
            "created_at": now.isoformat(timespec="seconds"),
            "status": "active",
            "stale": False,
        }

    @staticmethod
    def _agent_ref(source: str, task_id: str) -> str:
        encoded = json.dumps([source, task_id], ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
        return f"agent:{digest}"

    def create_interrupt(self, request: InterruptCreate) -> dict[str, Any]:
        record = self._interrupt_record(request)
        with self._lock:
            state = self.state()
            state.setdefault("interrupts", []).append(record)
            self.state_store.write(state)
        return record

    def patch_interrupt(self, event_id: str, request: InterruptPatch) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            for event in state.setdefault("interrupts", []):
                if event.get("id") == event_id:
                    event["status"] = request.status
                    event["resolved_at"] = utc_now()
                    self.state_store.write(state)
                    return event
        raise KeyError(event_id)

    def create_reminder(self, request: ReminderCreate) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        starts_at = (
            now + timedelta(seconds=request.delay_seconds)
            if request.delay_seconds is not None
            else as_utc(request.due_at)
        )
        interrupt = InterruptCreate(
            title="REMINDER",
            message=request.message,
            detail="Scheduled reminder",
            type="reminder",
            priority=request.priority,
            behavior=request.behavior,
            duration_seconds=request.duration_seconds,
            repeat_seconds=request.repeat_seconds,
            starts_at=starts_at,
            source="reminder",
        )
        return self.create_interrupt(interrupt)

    def handle_state_event(self, request: StateEvent) -> dict[str, Any]:
        key = self._agent_ref(request.source, request.task_id)
        # V0 used an ambiguous delimiter key. Migrate it only when the pair is
        # unambiguous, so upgrades can repair old partial commits safely.
        legacy_key = (
            f"{request.source}:{request.task_id}"
            if ":" not in request.source and ":" not in request.task_id
            else None
        )
        title = _fit_device_identifier(request.source.upper())
        detail = _fit_device_identifier(request.task_id)

        interrupt_request: InterruptCreate | None = None
        if request.state == "DONE":
            interrupt_request = InterruptCreate(
                title=title,
                message="TASK COMPLETE",
                detail=detail,
                priority=7,
                behavior="auto",
                source=request.source,
                source_ref=key,
            )
        elif request.state == "WAITING_FOR_USER":
            interrupt_request = InterruptCreate(
                title=title,
                message="WAITING FOR YOU",
                detail=detail,
                priority=9,
                behavior="until_change",
                source=request.source,
                source_ref=key,
            )

        # All derived data is validated above. State and event lifecycle now commit
        # under one lock and one state-store write, preventing partial/racing transitions.
        now = datetime.now(timezone.utc)
        created = self._interrupt_record(interrupt_request, now) if interrupt_request else None
        with self._lock:
            state = self.state()
            agent_states = state.setdefault("agent_states", {})
            existing = agent_states.get(key)
            migrated = False
            if existing is None and legacy_key is not None and legacy_key in agent_states:
                existing = agent_states.pop(legacy_key)
                migrated = True
            previous = existing.get("state") if isinstance(existing, dict) else existing

            matching_refs = {key}
            if legacy_key is not None:
                matching_refs.add(legacy_key)
            active_matching = [
                event
                for event in state.setdefault("interrupts", [])
                if event.get("source_ref") in matching_refs and event.get("status") == "active"
            ]

            if previous == request.state:
                # Repair the exact F2 legacy failure mode: a WAITING state can
                # exist without its until-change alert after the old partial commit.
                if request.state == "WAITING_FOR_USER" and not active_matching and created is not None:
                    agent_states[key] = {
                        "source": request.source,
                        "task_id": request.task_id,
                        "state": request.state,
                        "updated_at": now.isoformat(timespec="seconds"),
                    }
                    state["interrupts"].append(created)
                    self.state_store.write(state)
                    return {
                        "changed": True,
                        "repaired": True,
                        "previous": previous,
                        "state": request.state,
                        "interrupt": created,
                    }
                if migrated:
                    agent_states[key] = {
                        "source": request.source,
                        "task_id": request.task_id,
                        "state": request.state,
                        "updated_at": now.isoformat(timespec="seconds"),
                    }
                    # Move any unambiguous active legacy event to the new identity.
                    for event in active_matching:
                        event["source_ref"] = key
                    self.state_store.write(state)
                return {"changed": False, "previous": previous, "state": request.state}

            agent_states[key] = {
                "source": request.source,
                "task_id": request.task_id,
                "state": request.state,
                "updated_at": now.isoformat(timespec="seconds"),
            }
            for event in state["interrupts"]:
                if event.get("source_ref") in matching_refs and event.get("status") == "active":
                    event["status"] = "resolved"
                    event["resolved_at"] = now.isoformat(timespec="seconds")
            if created is not None:
                state["interrupts"].append(created)
            self.state_store.write(state)

        return {
            "changed": True,
            "previous": previous,
            "state": request.state,
            "interrupt": created,
        }

    async def sample_context(self) -> None:
        sample = await asyncio.to_thread(read_foreground)
        with self._lock:
            state = self.state()
            state["context"] = self.context_detector.update(sample)
            state["foreground"] = {
                "process": sample.process,
                "title": sample.title,
                "idle_seconds": round(sample.idle_seconds, 1),
            }
            self.state_store.write(state)

    def radar_configured(self) -> bool:
        from radar_client import RADAR_URL
        return bool(RADAR_URL)

    async def refresh_radar(self) -> None:
        await run_worker(self._refresh_radar_sync)

    def _refresh_radar_sync(self) -> None:
        try:
            result = fetch_radar()
        except (OSError, ValueError, json.JSONDecodeError):
            result = None
        with self._lock:
            state = self.state()
            if result is None:
                # Preserve the last validated sample as fallback, but explicitly
                # mark it stale when transport or source validation fails.
                state.setdefault("radar", {})["stale"] = True
            else:
                state["radar"] = {
                    "status": result.status,
                    "run_date": result.run_date,
                    "updated_at": result.updated_at,
                    "detail": result.detail,
                    "stale": False,
                }
            self.state_store.write(state)


async def monitor(service: DashboardService) -> None:
    radar_due = 0.0
    loop = asyncio.get_running_loop()
    while True:
        try:
            await service.sample_context()
        except Exception as error:  # Context is optional and must not starve other sources.
            print(f"Hub context monitor warning: {error}")

        if loop.time() >= radar_due:
            try:
                await service.refresh_radar()
            except Exception as error:  # Keep the Hub alive if a provider path fails.
                print(f"Hub Radar monitor warning: {error}")
            finally:
                radar_due = loop.time() + 300
        await asyncio.sleep(5)


def create_app(data_dir: Path = DATA_DIR, start_monitor: bool = True) -> FastAPI:
    service = DashboardService(data_dir)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(monitor(service)) if start_monitor else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application = FastAPI(title="ESP32 Personal Dashboard Hub", version="0.2.0", lifespan=lifespan)
    application.state.dashboard = service

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/scene")
    def scene() -> dict[str, Any]:
        return service.scene()

    @application.get("/state")
    def state() -> dict[str, Any]:
        return {**service.state(), "tasks": service.tasks()}

    @application.post("/codex/quota")
    def update_quota(update: QuotaUpdate) -> dict[str, Any]:
        return service.update_quota(update)

    @application.post("/tasks", status_code=201)
    def create_task(request: TaskCreate) -> dict[str, Any]:
        return service.create_task(request)

    @application.patch("/tasks/{task_id}")
    def patch_task(task_id: str, request: TaskPatch) -> dict[str, Any]:
        try:
            return service.patch_task(task_id, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="task not found") from error

    @application.post("/interrupt", status_code=201)
    def create_interrupt(request: InterruptCreate) -> dict[str, Any]:
        return service.create_interrupt(request)

    @application.patch("/interrupts/{event_id}")
    def patch_interrupt(event_id: str, request: InterruptPatch) -> dict[str, Any]:
        try:
            return service.patch_interrupt(event_id, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="interrupt not found") from error

    @application.post("/reminders", status_code=201)
    def create_reminder(request: ReminderCreate) -> dict[str, Any]:
        return service.create_reminder(request)

    @application.post("/state-events")
    def state_event(request: StateEvent) -> dict[str, Any]:
        return service.handle_state_event(request)

    return application


# Preserve the V0 service/factory for regression evidence and adapter reuse.
# The deployed entrypoint now uses the transactional Router and authenticated console.
from router_api import create_router_app

app = create_router_app()
