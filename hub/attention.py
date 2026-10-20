# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Deterministic attention routing over the existing Hub adapters and Scene protocol."""
from __future__ import annotations

import asyncio
import threading
import time
from async_worker import run_worker
from slow_diagnostics import SlowDiagnostics, operation_id
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from context_monitor import read_foreground, SamplingError
from work_context import WorkContext, WorkSessionConfig
from hub_models import ContextOverride, WorkspaceSync, CurrentItem, TodoUpsert, CurrentItemSet, quota_view
from quota_policy import QuotaPreferences, display_policy
from radar_client import SINGAPORE_TZ
from router_store import DocumentStore, RouterStore


def _device_ascii(value: str, field: str) -> str:
    if not value.isascii():
        raise ValueError(f"{field} must be ASCII for the current panel font")
    return value


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Conflict(ValueError):
    pass


class CapabilityError(ValueError):
    """Safe, enumerated business failure; no diagnostic text crosses the API."""
    def __init__(self, code: str, status_code: int):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventInput(Input):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=47)
    message: str = Field(min_length=1, max_length=47)
    detail: str = Field(default="", max_length=47)
    kind: Literal["reminder", "blocker", "agent_result", "suggestion", "news", "service", "tibo_reset"]
    # Explicit authorization from the authenticated user; priority alone grants nothing.
    authorization: Literal["none", "user_reminder", "current_blocker", "awaited_result"] = "none"
    priority: int = Field(default=5, ge=0, le=9)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    provenance: Literal["SIMULATED", "USER"] = "SIMULATED"

    @field_validator("title", "message", "detail")
    @classmethod
    def device_text(cls, value: str) -> str:
        return _device_ascii(value, "event text")

    @field_validator("starts_at", "expires_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps require a timezone")
        return value

    @model_validator(mode="after")
    def validate_event(self):
        if not self.title.strip() or not self.message.strip():
            raise ValueError("event title and message cannot be blank")
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValueError("expires_at must be after starts_at")
        expected = {"user_reminder": "reminder", "current_blocker": "blocker", "awaited_result": "agent_result"}
        if self.authorization != "none" and expected[self.authorization] != self.kind:
            raise ValueError("authorization does not match event kind")
        return self


class AckInput(Input):
    revision: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=100)


class TodoItem(Input):
    display_title: str | None = Field(default=None, max_length=63)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,23}$")
    title: str = Field(min_length=1, max_length=33)
    status: Literal["pending", "done", "cancelled"] = "pending"

    @field_validator("title")
    @classmethod
    def device_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return _device_ascii(value, "Todo title")


class TodoSync(Input):
    revision: int = Field(ge=1)
    command_id: str = Field(min_length=1, max_length=100)
    tasks: list[TodoItem] | None = Field(default=None, max_length=500)
    provenance: Literal["SIMULATED", "USER"] = "SIMULATED"

    @model_validator(mode="after")
    def unique_items(self):
        if "tasks" in self.model_fields_set and self.tasks is None:
            raise ValueError("omit tasks to preserve; [] explicitly clears; null is invalid")
        if self.tasks is not None and len({task.id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Todo IDs must be unique")
        return self


class Router:
    version = "attention-m2.0"

    def decide(self, event: dict, context: str, now: datetime) -> tuple[str, str]:
        if event["status"] != "active":
            return "DROP", event["status"]
        if event.get("expires_at") and now >= datetime.fromisoformat(event["expires_at"]):
            return "DROP", "expired_without_ack"
        if event.get("starts_at") and now < datetime.fromisoformat(event["starts_at"]):
            return "QUEUE", "not_due"
        if event["kind"] == "tibo_reset":
            return ("NOW", "isolated_tibo_test") if event.get("tibo_test_authorized") else ("QUEUE", "tibo_policy_unconfigured")
        if event["authorization"] in {"user_reminder", "current_blocker"}:
            return "NOW", "explicit_interrupt_authorization"
        if event["authorization"] == "awaited_result":
            return ("QUEUE", "work_context") if context in {"CODING", "QUIET"} else ("NOW", "awaited_result_ready")
        return "DIGEST", "no_interrupt_authorization"


AUTHORITY = {
    # Provenance/authority metadata for each overview block; display-only, not business logic.
    "todos": {"authority": "Hub tasks document (Todo Core semantics: revision + command_id)", "mutability": "explicit sync/upsert only"},
    "workspace": {"authority": "Hub workspace document", "provenance_field": "provenance / field_provenance"},
    "events": {"authority": "Router (AttentionService._reevaluate)", "route_source": "backend decision; browser must not recompute"},
    "context_evidence": {"authority": "WorkContext state machine + explicit override", "provenance_field": "provenance"},
    "codex": {"authority": "QuotaCollector sample via quota_view", "provenance_field": "source / collection"},
    "radar": {"authority": "Radar adapter state", "provenance_field": "status / stale"},
    "desired_scene": {"authority": "AttentionService.scene(persist=False, tibo_supported=True, utf8_supported=False)",
                      "kind": "read_only_compute_preview", "canonical": False,
                      "note": "Not the published canonical snapshot; see GET /api/scene/snapshot"},
    "delivery": {"authority": "served() on GET /scene", "meaning": "HTTP response prepared; not device receipt"},
    "device": {"authority": "none", "meaning": "No device receipt protocol; all fields UNKNOWN"},
}


class AttentionService:
    def __init__(self, data_dir: Path, *, enter_seconds=120, exit_seconds=900, default_plan="pro"):
        from app import DashboardService, DEFAULT_STATE, DEFAULT_TASKS
        self.diagnostics = SlowDiagnostics(data_dir / "slow-diagnostics.jsonl")
        self.db = RouterStore(data_dir, {"state": DEFAULT_STATE, "tasks": DEFAULT_TASKS}, diagnostics=self.diagnostics)
        self._sample_gate = asyncio.Lock()
        self._sample_lock = threading.RLock()
        self.state_store = DocumentStore(self.db, "state")
        self.task_store = DocumentStore(self.db, "tasks")
        self._lock = self.db.lock
        self.context_detector = WorkContext(config=WorkSessionConfig(**self.db.read("work_session_config"))) if self.db.read("work_session_config") else WorkContext(enter_seconds, exit_seconds)
        self.adapters = DashboardService(data_dir)
        self.adapters.state_store = self.state_store
        self.adapters.task_store = self.task_store
        self.adapters._lock = self._lock
        self.router = Router()
        self._started = False
        self.default_plan = default_plan
        from tibo import TiboModule
        self.tibo = TiboModule(self.db)
        from tibo_attention import TiboLifecycle
        self.tibo_lifecycle = TiboLifecycle(self)

    def state(self) -> dict:
        state = self.state_store.read()
        raw_quota = state.get("codex", {})
        state["codex"] = quota_view(raw_quota, datetime.now(timezone.utc))
        state["codex"]["display_policy"] = display_policy(self.db.read("quota_preferences"), raw_quota, default_plan=self.default_plan)
        state["context"] = self.context()["effective"]
        radar = state.setdefault("radar", {})
        today = datetime.now(timezone.utc).astimezone(SINGAPORE_TZ).date().isoformat()
        if radar.get("run_date") != today or not radar.get("updated_at"):
            radar["stale"] = True
        if not radar.get("updated_at"):
            radar["status"] = "UNKNOWN"
        return state

    def tasks(self) -> list[dict]:
        return self.task_store.read().get("tasks", [])

    def set_quota_preferences(self, request: QuotaPreferences) -> dict:
        with self.db.transaction() as db:
            preferences = self.db.read("quota_preferences")
            preferences.update(request.model_dump(exclude_unset=True))
            self.db.write("quota_preferences", preferences)
            policy = self.state()["codex"]["display_policy"]
            self._action(db, None, "QUOTA_DISPLAY_CHANGED", policy=policy)
            return policy

    async def sample_context(self) -> None:
        # Hold the gate until the actual worker finishes, including cancellation.
        async with self._sample_gate:
            await run_worker(self._sample_context_sync)

    def _sample_context_sync(self) -> None:
        token = operation_id.set(uuid4().hex)
        started = time.perf_counter()
        sampled = None
        outcome = "error"
        try:
            with self._sample_lock:
                try:
                    evidence = self.context_detector.update(read_foreground(read_title=True))
                except Exception as error:
                    evidence = self.context_detector.update(None, error=error.category if isinstance(error, SamplingError) else "SAMPLER_INTERNAL_ERROR")
                sampled = time.perf_counter()
                self.record_context(evidence)
                outcome = "ok"
        finally:
            finished = time.perf_counter()
            self.diagnostics.record("context_sample", (finished - started) * 1000,
                sample_ms=((sampled or finished) - started) * 1000,
                transaction_ms=(finished - (sampled or finished)) * 1000, outcome=outcome)
            operation_id.reset(token)

    def configure_context(self, command: WorkSessionConfig) -> dict:
        # Same lock order as sampling: detector first, then database. No async
        # handler takes this lock; replacing the detector cannot split a sample.
        with self._sample_lock:
            self.db.write("work_session_config", command.model_dump())
            self.context_detector = WorkContext(config=command)
        return command.model_dump()

    def record_context(self, evidence: dict, *, provenance="WINDOWS_FOREGROUND") -> None:
        with self.db.transaction() as db:
            before = self.context()
            self.db.write("context_evidence", {**evidence, "observed_at": stamp(), "provenance": provenance})
            after = self.context()
            if (before["effective"], before.get("reason")) != (after["effective"], after.get("reason")):
                self._action(db, None, "CONTEXT_CHANGED", before=before["effective"], **after)
            self._reevaluate(db, "foreground_sample")

    def context(self) -> dict:
        evidence = self.db.read("context_evidence")
        override = self.db.read("context_override")
        now = datetime.now(timezone.utc)
        fresh = False
        if evidence.get("observed_at"):
            age = (now - datetime.fromisoformat(evidence["observed_at"])).total_seconds()
            fresh = 0 <= age <= self.context_detector.max_sample_gap
        result = {**evidence, "effective": evidence.get("automatic", "UNKNOWN") if fresh else "UNKNOWN"}
        if not fresh:
            result.update(reason="foreground_sample_stale" if evidence else "no_foreground_sample",
                          unknown_reason="monitor_not_observed_or_unavailable")
        if override.get("mode", "AUTO") != "AUTO" and (not override.get("expires_at") or now < datetime.fromisoformat(override["expires_at"])):
            result.update(effective=override["mode"], reason="simulated_user_state" if override.get("provenance") == "SIMULATED" else "explicit_user_state")
        result["override"] = override
        result["manual_override"] = override.get("mode", "AUTO")
        result["page"] = "WORKSPACE" if result["effective"] in {"CODING", "QUIET"} else "HOME"
        result["monitor_status"] = ("Degraded" if evidence.get("error_category") else "Active") if fresh else "Stale"
        return result

    def set_context(self, request: ContextOverride) -> dict:
        with self.db.transaction() as db:
            self.db.write("context_override", {**request.model_dump(mode="json"), "updated_at": stamp()})
            self._action(db, None, "USER_CONTEXT_CHANGED", **self.context())
            self._reevaluate(db, "user_context")
            return self.context()

    def sync_workspace(self, request: WorkspaceSync) -> dict:
        patch = request.model_dump(mode="json", exclude_unset=True, exclude={"command_id"})
        command = {"op": "workspace_sync", **patch}
        with self.db.transaction() as db:
            previous = self._command(db, request.command_id, command)
            if previous is not None:
                return previous
            document = self.db.read("workspace")
            revision = document.get("revision", 0)
            if request.revision < revision or (request.revision == revision and patch != document.get("last_patch")):
                raise Conflict("stale or conflicting workspace revision")
            if request.revision > revision:
                if "field_provenance" in document:
                    for field in ("project", "current_item", "suggestions"):
                        if field in patch:
                            document["field_provenance"][field] = request.provenance
                document.update(patch)
                document.update(last_patch=patch, provenance=request.provenance, updated_at=stamp())
                self.db.write("workspace", document)
                self._action(db, None, "WORKSPACE_SYNCED", revision=request.revision, provenance=request.provenance)
            db.execute("INSERT INTO commands VALUES(?,?,?)", (request.command_id, encode(command), encode(document)))
            return document

    def _capability_write(self, request, operation, document_name, apply, principal=None):
        # Existing Hub command ledger and transaction protect retries and races.
        command = {"op": operation, **request.model_dump(mode="json")}
        key = "mcp:" + request.request_id
        with self.db.transaction() as db:
            previous = self._command(db, key, command)
            if previous is not None:
                return previous  # Replay before revision check; no repeated audit/write.
            document = self.db.read(document_name)
            revision = document.get("revision", 0)
            if request.expected_revision != revision:
                raise Conflict("stale capability revision")
            observed_at = stamp()
            source = {"provenance": "MCP", "actor": "MCP_CLIENT",
                      "capability": operation, "request_id": request.request_id,
                      "updated_at": observed_at}
            if principal == "grokbot_remote":
                source["principal"] = principal
            result = apply(document, source)
            document.update(revision=revision + 1, provenance="MCP", updated_at=observed_at,
                            last_mutation=source)
            self.db.write(document_name, document)
            self._action(db, None, "MCP_CAPABILITY_APPLIED", **source,
                         revision=revision + 1, object_id=result.get("object_id"))
            result = {"request_id": request.request_id, "revision": revision + 1, **result}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (key, encode(command), encode(result)))
            return result

    def upsert_todo(self, request: TodoUpsert, *, principal=None) -> dict:
        def apply(document, source):
            tasks = document.setdefault("tasks", [])
            previous = next((t for t in tasks if t["id"] == request.todo_id), None)
            if request.todo_id is not None and previous is None:
                raise CapabilityError("not_found", 404)
            if previous is None and len(tasks) >= 500:
                raise CapabilityError("validation_error", 422)
            # Preserve legacy fields and origin of untouched records; no bulk replace.
            for task in tasks:
                if document.get("provenance"):
                    task.setdefault("provenance", document["provenance"])
            identifier = previous["id"] if previous else "todo-" + uuid4().hex[:18]
            status = request.status if request.status is not None else (previous.get("status", "pending") if previous else "pending")
            validated = TodoItem(id=identifier, title=request.title, status=status)
            record = {**(previous or {}), **validated.model_dump(), **source}
            if previous is None:
                record["created_at"] = source["updated_at"]
                tasks.append(record)
            else:
                tasks[tasks.index(previous)] = record
            document["snapshot_known"] = True
            return {"todo": record, "object_id": identifier}
        return self._capability_write(request, "upsert_todo", "tasks", apply, principal)

    def set_current_item(self, request: CurrentItemSet, *, principal=None) -> dict:
        def apply(document, source):
            # Source tracking is per field when MCP patches a mixed-origin workspace.
            origins = document.setdefault("field_provenance", {})
            for field in ("project", "current_item", "suggestions"):
                if field in document:
                    origins.setdefault(field, document.get("provenance", "UNKNOWN"))
            item = CurrentItem(id="item-" + uuid4().hex[:18], title=request.title)
            document["current_item"] = {**item.model_dump(), **source}
            origins["current_item"] = "MCP"
            if request.project is not None:
                document["project"] = request.project
                origins["project"] = "MCP"
            # Only current item and optional project; no context/Scene/suggestion writes.
            return {"current_item": document["current_item"], "project": document.get("project"),
                    "object_id": item.id}
        return self._capability_write(request, "set_current_item", "workspace", apply, principal)

    async def refresh_radar(self) -> None:
        await self.adapters.refresh_radar()

    def _events(self, db) -> list[dict]:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM events ORDER BY sequence")]

    def _save_event(self, db, event: dict) -> None:
        db.execute("INSERT INTO events VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload",
                   (event["id"], event["revision"], event["sequence"], encode(event)))

    def _action(self, db, event: dict | None, stage: str, **details) -> None:
        payload = {"stage": stage, "at": stamp(), **details}
        db.execute("INSERT INTO actions(event_id, revision, payload) VALUES (?, ?, ?)",
                   (event["id"] if event else None, event["revision"] if event else None, encode(payload)))

    def _startup(self, db) -> None:
        if self._started:
            return
        # Reevaluate persisted inputs; never restore a saved interrupt screenshot.
        # _started is set after commit by the public transaction caller.
        self._action(db, None, "HUB_STARTED", device_state="UNKNOWN")

    def _reevaluate(self, db, trigger: str, *, persist=True) -> list[dict]:
        state = self.state()
        context = state.get("context", "UNKNOWN")
        events = self._events(db)
        now = datetime.now(timezone.utc)
        candidates = []
        planned = {}
        for event in events:
            route, reason = self.router.decide(event, context, now)
            planned[event["id"]] = (route, reason)
            if route == "NOW":
                candidates.append(event)
        # Explicit authorization first, urgency next, stable arrival order last.
        ranks = {"current_blocker": 2, "user_reminder": 2, "awaited_result": 1, "none": 0}
        chosen = max(candidates, key=lambda e: (ranks[e["authorization"]], e["priority"], -e["sequence"]), default=None)
        for event in events:
            route, reason = planned[event["id"]]
            if route == "NOW" and event is not chosen:
                route, reason = "QUEUE", "another_event_selected"
            key = encode([event["revision"], context, route, reason, self.router.version])
            if not persist:
                event.update(route=route, reason=reason)
                continue
            if event.get("decision_key") != key or trigger == "startup":
                decision = {"at": stamp(), "context": context, "context_evidence": self.context(), "route": route, "reason": reason,
                            "rule_version": self.router.version, "trigger": trigger,
                            "input": {k: event.get(k) for k in ("id", "revision", "title", "message", "detail", "kind", "authorization", "priority", "status", "starts_at", "expires_at", "provenance")}}
                db.execute("INSERT INTO decisions(event_id,revision,payload) VALUES(?,?,?)", (event["id"], event["revision"], encode(decision)))
                event.update(route=route, reason=reason, decision_key=key)
                self._save_event(db, event)
                self._action(db, event, {"NOW": "SCENE_REQUESTED", "QUEUE": "QUEUED", "DIGEST": "DIGEST_SAVED", "DROP": "ATTENTION_WITHDRAWN"}[route], reason=reason)
        return events

    def reevaluate(self) -> None:
        with self.db.transaction() as db:
            self._startup(db)
            self._reevaluate(db, "startup" if not self._started else "context_or_time")
        self._started = True

    def publish(self, request: EventInput) -> dict:
        payload = request.model_dump(mode="json")
        with self.db.transaction() as db:
            events = self._events(db)
            previous = next((e for e in events if e["id"] == request.id), None)
            if previous:
                if request.revision < previous["revision"]:
                    raise Conflict("stale event revision")
                if request.revision == previous["revision"]:
                    if previous["input"] != payload:
                        raise Conflict("same revision with different content")
                    return previous
            sequence = previous["sequence"] if previous else max((e["sequence"] for e in events), default=0) + 1
            event = {**payload, "input": payload, "sequence": sequence, "status": "active", "received_at": stamp(), "ack_at": None}
            self._save_event(db, event)
            self._action(db, event, "RECEIVED", provenance=request.provenance)
            self._reevaluate(db, "event_received")
            return next(e for e in self._events(db) if e["id"] == request.id)

    def _command(self, db, key: str, request: dict):
        row = db.execute("SELECT request,response FROM commands WHERE key=?", (key,)).fetchone()
        if row:
            if row[0] != encode(request):
                raise Conflict("command_id reused with different input")
            return json.loads(row[1])
        return None

    def acknowledge(self, event_id: str, request: AckInput, *, cancel: bool = False) -> dict:
        command = {"op": "cancel" if cancel else "ack", "id": event_id, "revision": request.revision}
        with self.db.transaction() as db:
            previous = self._command(db, request.command_id, command)
            if previous is not None:
                return previous
            event = next((e for e in self._events(db) if e["id"] == event_id), None)
            if event is None:
                raise KeyError(event_id)
            if event["revision"] != request.revision:
                raise Conflict("stale ACK cannot close a newer event")
            target = "cancelled" if cancel else "acknowledged"
            if event["status"] not in ("active", target):
                raise Conflict("event already withdrawn with a different outcome")
            if event["status"] == "active":
                if event["kind"] == "tibo_reset" and not cancel:
                    self.db.write("tibo_detail", {})
                event["status"] = target
                event["ack_at" if not cancel else "cancelled_at"] = stamp()
                self._save_event(db, event)
                self._action(db, event, "USER_ACKNOWLEDGED" if not cancel else "SOURCE_CANCELLED")
                self._reevaluate(db, command["op"])
            result = {"id": event_id, "revision": request.revision, "status": target}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (request.command_id, encode(command), encode(result)))
            return result

    def sync_todos(self, request: TodoSync) -> dict:
        command = {"op": "todo_sync", **request.model_dump(mode="json", exclude_unset=True, exclude={"command_id"})}
        with self.db.transaction() as db:
            previous = self._command(db, request.command_id, command)
            if previous is not None:
                return previous
            document = self.task_store.read()
            if request.tasks is not None:
                items = [item.model_dump() for item in request.tasks]
                revision = document.get("revision", 0)
                if request.revision < revision or (request.revision == revision and items != document.get("tasks")):
                    raise Conflict("stale or conflicting Todo revision")
                if request.revision > revision:
                    document.update(tasks=items, revision=request.revision, updated_at=stamp(), snapshot_known=True, provenance=request.provenance)
                    self.task_store.write(document)
                    self._action(db, None, "TODO_SNAPSHOT_SAVED", revision=request.revision)
            result = {"revision": document.get("revision", 0), "tasks": document.get("tasks", [])}
            db.execute("INSERT INTO commands VALUES(?,?,?)", (request.command_id, encode(command), encode(result)))
            return result

    def scene(self, *, tibo_supported: bool = False, utf8_supported: bool = False, persist=True) -> dict:
        with self.db.transaction() as db:
            if persist:
                self._startup(db)
            events = self._reevaluate(db, "startup" if not self._started else "scene_requested", persist=persist)
            state = self.state()
            active = next((e for e in events if e.get("route") == "NOW"), None)
            pending = [{"id": t["id"], "title": t["title"], **({"display_title": t["display_title"]} if utf8_supported and t.get("display_title") else {}), "done": False} for t in self.tasks() if t.get("status") == "pending"]
            workspace = self.db.read("workspace")
            current = workspace.get("current_item")
            next_items = [t for t in pending if not current or t["id"] != current["id"]]
            now = datetime.now(timezone.utc)
            suggestions = [s for s in workspace.get("suggestions", []) if not s.get("expires_at") or now < datetime.fromisoformat(s["expires_at"])]
            windows = {w["window_minutes"]: w for w in state["codex"]["windows"]}
            five_visible = state["codex"]["display_policy"]["five_hour"]["visible"]
            def quota(duration):
                window = windows.get(duration, {})
                value = window.get("remaining_percent")
                return int(value) if value is not None and window.get("status") == "SNAPSHOT" else None
            quota_signature = encode([five_visible, quota(300) if five_visible else None, quota(10080)])
            quota_projection = self.db.read("quota_projection")
            if quota_projection.get("signature") != quota_signature:
                has_value = quota(10080) is not None or (five_visible and quota(300) is not None)
                quota_projection = {"signature": quota_signature, "observed_at": (state["codex"].get("updated_at") or "UNKNOWN")[:19] if has_value else "UNKNOWN"}
                if persist:
                    self.db.write("quota_projection", quota_projection)
            radar = state["radar"]
            page = "workspace" if state.get("context") in {"CODING", "QUIET"} else "home"
            todos = next_items[:3] if page == "workspace" else pending[:3]
            visible = {"page": page,
                       "context": state.get("context", "UNKNOWN"),
                       "date": now.astimezone(SINGAPORE_TZ).strftime("%Y-%m-%d"),
                       "weather": {"status": "UNKNOWN", "source": "device_adapter"},
                       "workspace": {"project": workspace.get("project") or "UNKNOWN", "current_item": current["title"] if current else "UNKNOWN",
                                     "suggestion": suggestions[0]["text"] if suggestions else "NONE / UNKNOWN"},
                       "codex": {"show_5h": five_visible, "quota_5h_remaining": quota(300) if five_visible else None, "quota_total_remaining": quota(10080),
                                 "observed_at": quota_projection["observed_at"],
                                 "collection": state["codex"]["collection"]},
                       "radar": {"status": radar.get("status", "UNKNOWN").lower(), "run_date": radar.get("run_date") or "UNKNOWN", "fresh": not radar.get("stale", True)},
                       "simulated": (self.task_store.read().get("provenance") == "SIMULATED" or
                                     any(t.get("provenance") == "SIMULATED" for t in self.tasks()) or
                                     (page == "workspace" and (workspace.get("provenance") == "SIMULATED" or
                                      "SIMULATED" in workspace.get("field_provenance", {}).values())) or state["codex"].get("source") == "SIMULATED"),
                       "stale": bool(page == "home" and self.adapters.radar_configured() and radar.get("stale", True)), "protocol_version": 3}
            if utf8_supported and current and current.get("display_title"):
                visible["workspace"]["display_title"] = current["display_title"]
            if utf8_supported:
                from device_text import title_bitmap
                for item in todos:
                    bitmap = title_bitmap(item.get('display_title') or item['title'])
                    if bitmap is not None:
                        item['title_bitmap'] = bitmap
                if current:
                    bitmap = title_bitmap(current.get('display_title') or current['title'])
                    if bitmap is not None:
                        visible['workspace']['title_bitmap'] = bitmap
            if self.task_store.read().get("snapshot_known", False):
                visible["todos"] = todos
                visible["todo_remaining"] = max(0, len(next_items if page == "workspace" else pending) - len(todos))
            if active:
                visible.update(page="interrupt", interrupt={"id": active["id"], "revision": active["revision"],
                    "type": active["kind"], "title": active["title"], "message": active["message"],
                    "detail": active["detail"], "priority": active["priority"], "behavior": "until_change"})
                visible["stale"] = False  # A current interrupt is independent of optional Home providers.
                visible["simulated"] = active["provenance"] == "SIMULATED"
            automatic = self.tibo_lifecycle.automatic(persist=persist) if tibo_supported else None
            detail = self.tibo_lifecycle.detail()
            tibo_event = active and active["kind"] == "tibo_reset"
            if tibo_supported and (tibo_event or (detail and not active)):
                data = self.tibo_lifecycle.display_data(active["tibo_snapshot"] if tibo_event else detail)
                visible.update(page="tibo", tibo=data, tibo_mode="attention" if tibo_event else "detail",
                               attention_required=bool(tibo_event), acknowledgment="unacknowledged" if tibo_event else "not_required")
                visible["stale"] = data["status"] != "FRESH"
            if tibo_supported and not active and not detail and automatic is not None:
                visible.update(page="tibo", tibo=automatic, tibo_mode="automatic",
                               attention_required=False, acknowledgment="not_required", simulated=False)
                visible["stale"] = automatic["status"] != "FRESH" or automatic["forecast_status"] != "FRESH"
            if tibo_supported and not active and not detail and automatic is None and not self.db.read("tibo_lifecycle").get("enabled"):
                prefs = self.tibo.preferences()
                if prefs["enabled"] and prefs["show_page"]:
                    visible.update(page="tibo", tibo=self.tibo.device(), simulated=False)
                    visible["stale"] = visible["tibo"]["status"] != "FRESH"
            # Hash only rendered fields. Identity/revisions remain in the payload,
            # but hidden sync changes must not request an ink refresh.
            projection_fields = {k: visible[k] for k in ("page", "stale", "simulated")}
            if visible["page"] == "tibo":
                projection_fields["tibo"] = visible["tibo"]
            elif active:
                projection_fields["interrupt"] = {k: active[k] for k in ("title", "message", "detail")}
            else:
                projection_fields["todos"] = [{"done": t["done"], **({"title_bitmap": t["title_bitmap"]} if "title_bitmap" in t else {"title": t["title"]})} for t in todos] if "todos" in visible else None
                projection_fields["todo_remaining"] = visible.get("todo_remaining")
                if page == "home":
                    projection_fields.update(date=visible["date"], radar=visible["radar"])
                else:
                    projection_fields.update(workspace=visible["workspace"], codex={k: v for k, v in visible["codex"].items() if k != "collection"})
            if 'workspace' in projection_fields and 'title_bitmap' in projection_fields['workspace']:
                projection_fields['workspace'] = {k: v for k, v in projection_fields['workspace'].items()
                                                  if k not in {'current_item', 'display_title'}}
            digest = hashlib.sha256(encode(projection_fields).encode()).hexdigest()
            projection_key = ("projection_tibo" if tibo_supported else "projection") + ("_utf8" if utf8_supported else "")
            projection = self.db.read(projection_key)
            if digest != projection.get("hash"):
                projection = {"hash": digest, "version": max(state.get("version", 0), projection.get("version", 0)) + 1}
                if persist:
                    self.db.write(projection_key, projection)
                    self._action(db, active, "DESIRED_SCENE_SAVED", scene_version=projection["version"], page=visible["page"])
            scene = {"version": projection["version"], **visible}
            if not persist:
                scene["preview_only"] = True
        if persist:
            self._started = True
        return scene

    def served(self, scene: dict, *, device_request=False) -> None:
        with self.db.transaction() as db:
            delivery = self.db.read("delivery")
            if delivery.get("last_offered_version") != scene["version"]:
                self._action(db, scene.get("interrupt"), "HTTP_RESPONSE_PREPARED", scene_version=scene["version"], device_received="UNKNOWN")
            self.db.write("delivery", {**delivery, "last_offered_version": scene["version"], "last_request_at": stamp(),
                **({"last_device_request_at": stamp(), "device_requested_version": scene["version"]} if device_request else {})})

    KNOWN_CAPABILITIES = ("bitmap-titles-v1", "tibo-v1")

    @classmethod
    def scene_profile(cls, capabilities: str) -> str:
        """Normalize a capability query to the profile that changes Scene output."""
        found = sorted({c.strip() for c in (capabilities or "").split(",")} & set(cls.KNOWN_CAPABILITIES))
        return ",".join(found) or "base"

    def serve_scene(self, capabilities: str, *, device_request: bool) -> dict:
        """The device-facing commit path: generate, mark served and publish the
        canonical snapshot in one transaction so the response and stored copy match."""
        profile = self.scene_profile(capabilities)
        flags = set(profile.split(","))
        with self.db.transaction():
            result = self.scene(tibo_supported="tibo-v1" in flags, utf8_supported="bitmap-titles-v1" in flags)
            self.served(result, device_request=device_request)
            workspace = self.db.read("workspace")
            task_doc = self.task_store.read()
            current = workspace.get("current_item") or None
            provenance = {
                # Read in the same transaction that produced `scene`; UNKNOWN when not recorded.
                "scope": {"profile": profile, "data": "this Hub data_dir (environment label: see overview.environment)"},
                "workspace": {"provenance": workspace.get("provenance") or "UNKNOWN",
                              "field_provenance": workspace.get("field_provenance") or {},
                              "updated_at": workspace.get("updated_at") or "UNKNOWN"},
                "todos": {"authority": "Hub tasks document (display copy as seen by Scene)",
                          "provenance": task_doc.get("provenance") or "UNKNOWN",
                          "revision": task_doc.get("revision"),
                          "todo_core_authority": "UNKNOWN"},
                "current_item_ref": ({"id": current.get("id"),
                                      "id_kind": "hub_workspace_current_item_id",
                                      "note": "Hub workspace ID; not verified as a Todo Core ID"}
                                     if current else None),
            }
            self.db.write("scene_snapshot:" + profile, {
                "provenance": provenance,
                "snapshot_id": uuid4().hex, "profile": profile, "published_at": stamp(),
                "scene_version": result["version"],
                "source": "GET /scene commit path (AttentionService.scene persist=True)",
                "requester": "lan_device_capability_marker" if device_request else "local_or_unmarked_request",
                "scene": result})
        return result

    def scene_snapshot(self, capabilities: str) -> dict:
        """Strictly read-only: never generates, commits or records a request."""
        profile = self.scene_profile(capabilities)
        base = {"profile": profile, "kind": "canonical_snapshot", "read_at": stamp(),
                "meaning": "Latest Scene published on the /scene commit path for this profile; "
                           "not proof of device receipt or display; inputs may have changed since published_at"}
        if not self.db.path.exists():
            return {**base, "status": "unavailable", "reason": "database_not_initialized", "snapshot": None}
        with self.db.observation():
            stored = self.db.read("scene_snapshot:" + profile)
        if not stored.get("scene"):
            return {**base, "status": "unavailable", "reason": "no_snapshot_published_for_profile", "snapshot": None}
        return {**base, "status": "available", "reason": None, "snapshot": stored}

    def overview(self) -> dict:
        with self.db.observation() as db:
            scene = self.scene(tibo_supported=True, persist=False)
            state = self.state()
            events = self._reevaluate(db, "overview", persist=False)
            return {"hub": "READY", "grok_bot": "UNKNOWN", "context": state.get("context", "UNKNOWN"),
                    "tibo_lifecycle": self.tibo_lifecycle.view(),
                    "context_evidence": self.context(), "workspace": self.db.read("workspace"),
                    "codex": state["codex"], "radar": state["radar"], "weather": {"status": "UNKNOWN", "source": "device_adapter"},
                    "todos": self.task_store.read(), "events": events, "desired_scene": scene,
                    "delivery": self.db.read("delivery"),
                    "device": {"received_scene": "UNKNOWN", "display_complete": "UNKNOWN", "pending_refresh": "UNKNOWN"},
                    "recent_actions": [{"id": row[0], "event_id": row[1], **json.loads(row[2])} for row in db.execute("SELECT id,event_id,payload FROM actions ORDER BY id DESC LIMIT 40")],
                    "legacy_interrupts_pending_review": len(state.get("interrupts", [])),
                    "authority": AUTHORITY}

    def trace(self, event_id: str) -> dict:
        with self.db.transaction() as db:
            event = next((e for e in self._events(db) if e["id"] == event_id), None)
            if event is None:
                raise KeyError(event_id)
            result = {"event": event}
            for table in ("decisions", "actions"):
                result[table] = [{"id": row[0], "revision": row[1], **json.loads(row[2])} for row in
                    db.execute(f"SELECT id,revision,payload FROM {table} WHERE event_id=? ORDER BY id", (event_id,))]
            return result
