# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Local console and narrow authenticated business endpoints for Attention Router."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import ipaddress
from pathlib import Path
import secrets
import re
import uuid
import time
from slow_diagnostics import operation_id

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

from attention import AckInput, AttentionService, CapabilityError, Conflict, EventInput, TodoSync
from hub_models import WorkspaceSync, ContextOverride, TodoUpsert, CurrentItemSet
from quota_policy import QuotaPreferences
from tibo import TiboPreferences
from tibo_attention import TiboAttentionPolicy
from work_context import WorkSessionConfig, WorkContext
from pydantic import BaseModel, ConfigDict, Field


RELEASE_VERSION = "0.1.0"


class ShowTibo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


def create_router_app(data_dir: Path | None = None, *, start_monitor: bool = True,
                      api_token: str | None = None, enter_seconds: float = 120, exit_seconds: float = 900,
                      environment: str = "UNSPECIFIED", codex_executable: str | None = None, runtime_probe=None) -> FastAPI:
    service = AttentionService(data_dir or Path(__file__).resolve().parents[1] / ".build" / "preview-data", enter_seconds=enter_seconds, exit_seconds=exit_seconds)
    from runtime_view import RuntimeView
    runtime_view = RuntimeView(runtime_probe)
    console_token = secrets.token_urlsafe(32)
    instance_id = uuid.uuid4().hex

    @asynccontextmanager
    async def lifespan(application):
        from app import monitor
        service.reevaluate()
        task = asyncio.create_task(monitor(service)) if start_monitor else None
        tibo_task = asyncio.create_task(service.tibo.run()) if start_monitor else None
        quota_task = None
        if codex_executable:
            from quota_collector import QuotaCollector
            quota_task = asyncio.create_task(QuotaCollector(service, codex_executable).run())
        try:
            yield
        finally:
            if tibo_task:
                tibo_task.cancel()
                with suppress(asyncio.CancelledError):
                    await tibo_task
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if quota_task:
                quota_task.cancel()
                with suppress(asyncio.CancelledError):
                    await quota_task

    application = FastAPI(title="Attention Router Hub", version="1.0-m2", lifespan=lifespan,
                          docs_url=None, redoc_url=None, openapi_url=None)
    application.state.dashboard = service

    @application.middleware("http")
    async def slow_request(request: Request, call_next):
        token = operation_id.set(uuid.uuid4().hex)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            try:
                if elapsed >= service.diagnostics.threshold_ms:
                    await asyncio.to_thread(service.diagnostics.record, "request", elapsed,
                                            path=request.url.path, status=status)
            finally:
                operation_id.reset(token)

    def local(request: Request) -> bool:
        try:
            return bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
        except ValueError:
            return False

    @application.middleware("http")
    async def boundary(request: Request, call_next):
        path = request.url.path
        # Device has read-only access to the Scene projection. No arbitrary local
        # browser origins or LAN clients may bootstrap a console session.
        public = request.method == "GET" and path in {"/health", "/scene"}
        if not public:
            bearer = request.headers.get("authorization", "")
            api_ok = bool(api_token and secrets.compare_digest(bearer, "Bearer " + api_token))
            browser_ok = (local(request) and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
                          and secrets.compare_digest(request.cookies.get("hub_session", ""), console_token))
            bootstrap = path == "/" and request.method == "GET" and local(request) and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
            if not (api_ok or browser_ok or bootstrap):
                return JSONResponse({"detail": "authenticated local console or configured API token required"}, status_code=401)
            if request.method not in {"GET", "HEAD"} and not api_ok:
                if request.headers.get("x-hub-action") != "1" or request.headers.get("origin") != str(request.base_url).rstrip("/"):
                    return JSONResponse({"detail": "same-origin action required"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @application.exception_handler(Conflict)
    async def conflict(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @application.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": "event not found"}, status_code=404)

    @application.exception_handler(CapabilityError)
    async def capability_failure(request, error):
        return JSONResponse({"ok": False, "status": error.code,
                             "error": {"code": error.code}, "result": None}, status_code=error.status_code)

    @application.exception_handler(RequestValidationError)
    async def capability_validation(request, error):
        if request.url.path in {"/api/mcp/todos/upsert", "/api/mcp/workspace/current-item"}:
            return JSONResponse({"ok": False, "status": "validation_error",
                                 "error": {"code": "validation_error"}, "result": None}, status_code=422)
        return await request_validation_exception_handler(request, error)

    def capability_call(action):
        try:
            result = action()
            return {"ok": True, "status": "ok", "error": None, "result": result}
        except CapabilityError:
            raise
        except Conflict:
            raise CapabilityError("conflict", 409) from None
        except Exception:
            raise CapabilityError("internal_error", 500) from None

    @application.post("/api/mcp/todos/upsert")
    def upsert_todo(command: TodoUpsert, request: Request):
        principal = "grokbot_remote" if request.headers.get("x-mcp-principal") == "grokbot_remote" else None
        return capability_call(lambda: service.upsert_todo(command, principal=principal))

    @application.post("/api/mcp/workspace/current-item")
    def set_current_item(command: CurrentItemSet, request: Request):
        principal = "grokbot_remote" if request.headers.get("x-mcp-principal") == "grokbot_remote" else None
        return capability_call(lambda: service.set_current_item(command, principal=principal))

    @application.get("/health")
    def health():
        return {"status": "ok", "version": "1.0-m3", "release_version": RELEASE_VERSION, "environment": environment, "instance_id": instance_id}

    @application.get("/scene")
    def scene(request: Request, capabilities: str = ""):
        return service.serve_scene(capabilities, device_request=bool(
            request.client and not local(request) and "tibo-v1" in capabilities.split(",")))

    @application.get("/api/scene/snapshot")
    def scene_snapshot(capabilities: str = "tibo-v1,bitmap-titles-v1"):
        # Console-authenticated, read-only; defaults to the current ESP32 profile.
        return service.scene_snapshot(capabilities)

    @application.get("/api/overview")
    def overview(request: Request):
        request_id = request.headers.get("x-hub-request-id", "")
        if request_id and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            with service.db.transaction() as db:
                service._action(db, None, "MCP_READ_RECEIVED", request_id=request_id,
                    environment=environment, instance_id=instance_id)
        snapshot = service.overview()
        return {**snapshot, "release_version": RELEASE_VERSION, "runtime": runtime_view.view(snapshot["context_evidence"], snapshot["delivery"], start_monitor), "environment": environment, "instance_id": instance_id,
                "request_id": request_id if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id) else None}

    @application.get("/api/events/{event_id}")
    def trace(event_id: str):
        return service.trace(event_id)

    @application.post("/api/events", status_code=201)
    def publish(event: EventInput):
        return service.publish(event)

    @application.post("/api/events/{event_id}/ack")
    def ack(event_id: str, command: AckInput):
        return service.acknowledge(event_id, command)

    @application.post("/api/events/{event_id}/cancel")
    def cancel(event_id: str, command: AckInput):
        return service.acknowledge(event_id, command, cancel=True)

    @application.post("/api/todos/sync")
    def sync(command: TodoSync):
        return service.sync_todos(command)

    @application.post("/api/radar/sync")
    async def radar_sync():
        await service.refresh_radar()
        return service.state()["radar"]

    @application.post("/api/workspace/sync")
    def workspace(command: WorkspaceSync):
        return service.sync_workspace(command)

    @application.post("/api/context")
    def context(command: ContextOverride):
        return service.set_context(command)

    @application.post("/api/codex/preferences")
    def quota_preferences(command: QuotaPreferences):
        return service.set_quota_preferences(command)

    @application.get("/api/context/config")
    def context_config():
        return service.context_detector.config.model_dump()

    @application.post("/api/context/config")
    def configure_context(command: WorkSessionConfig):
        return service.configure_context(command)

    @application.post("/api/tibo/show")
    def show_tibo(command: ShowTibo):
        return service.tibo_lifecycle.show(command.request_id)

    @application.get("/api/tibo/lifecycle")
    def tibo_lifecycle():
        service.reevaluate()
        return service.tibo_lifecycle.view()

    @application.post("/api/tibo/attention-policy")
    def tibo_policy(command: TiboAttentionPolicy):
        return service.tibo_lifecycle.configure(command)

    @application.post("/api/tibo/test-event")
    def tibo_test():
        if environment != "attention-m3-isolated":
            raise HTTPException(403, "isolated runtime required")
        return service.tibo_lifecycle.test_event()

    @application.post("/api/tibo/events/{event_id}/ack")
    def tibo_ack(event_id: str, command: AckInput):
        return service.tibo_lifecycle.acknowledge(event_id, command.revision, command.command_id)

    @application.get("/api/tibo")
    def tibo_status():
        return service.tibo.view()

    @application.post("/api/tibo/preferences")
    def tibo_preferences(command: TiboPreferences):
        return service.tibo.configure(command)

    @application.get("/", response_class=HTMLResponse)
    def console():
        response = HTMLResponse((Path(__file__).parent / "console.html").read_text(encoding="utf-8"))
        response.set_cookie("hub_session", console_token, httponly=True, samesite="strict")
        return response

    return application
