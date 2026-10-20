# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Local-only S1 policy control, tool registry, limiter and secret-free security audit."""
import argparse
from collections import deque
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / ".build" / "mcp-auth" / "policy.json"
DEFAULT_AUDIT = ROOT / ".build" / "mcp-auth" / "security-audit.jsonl"
PRINCIPAL = "grokbot_remote"
SCOPES = ("state:read", "todo:write", "workspace:write")

@dataclass(frozen=True)
class ToolPolicy:
    name: str
    required_scope: str
    risk: str
    is_write: bool
    rate_limit_key: str

TOOL_POLICIES = {
    "get_hub_state": ToolPolicy("get_hub_state", "state:read", "read", False, "get_hub_state"),
    "upsert_todo": ToolPolicy("upsert_todo", "todo:write", "low_write", True, "upsert_todo"),
    "set_current_item": ToolPolicy("set_current_item", "workspace:write", "low_write", True, "set_current_item"),
}
DEFAULT_LIMITS = {"principal": 60, "get_hub_state": 30, "upsert_todo": 5, "set_current_item": 5}
DEFAULTS = {"version": 1, "base_mode": "READ_ONLY", "write_armed_until": None,
            "principal": PRINCIPAL, "scopes": list(SCOPES), "rate_limits": DEFAULT_LIMITS}
CURRENT_CALL = ContextVar("mcp_authorized_call", default=None)

class PolicyError(ValueError):
    pass

class Denied(ValueError):
    def __init__(self, code, status=403, retry_after=None):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(code)

def utc_now():
    return datetime.now(timezone.utc)

def utc_text(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def parse_utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PolicyError("UTC timestamp required")
    result = datetime.fromisoformat(value[:-1] + "+00:00")
    return result.astimezone(timezone.utc)

def validate_policy(raw, now=None):
    now = now or utc_now()
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise PolicyError("Policy structure invalid")
    if type(raw["version"]) is not int or raw["version"] != 1 or raw["base_mode"] not in ("OFF", "READ_ONLY"):
        raise PolicyError("Policy version/mode invalid")
    if raw["principal"] != PRINCIPAL or not isinstance(raw["scopes"], list):
        raise PolicyError("Principal invalid")
    if any(not isinstance(s, str) or s not in SCOPES for s in raw["scopes"]) or len(set(raw["scopes"])) != len(raw["scopes"]):
        raise PolicyError("Scopes invalid")
    limits = raw["rate_limits"]
    if not isinstance(limits, dict) or set(limits) != set(DEFAULT_LIMITS) or any(type(n) is not int or not 1 <= n <= 100000 for n in limits.values()):
        raise PolicyError("Rate limits invalid")
    until = raw["write_armed_until"]
    if until is not None:
        expiry = parse_utc(until)
        if raw["base_mode"] != "READ_ONLY" or expiry > now + timedelta(hours=24):
            raise PolicyError("Write lease invalid")
    return raw

def read_policy(path=DEFAULT_POLICY, now=None):
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            content = file.read(16385)
        if len(content) > 16384:
            raise PolicyError("Policy too large")
        return validate_policy(json.loads(content), now)
    except Exception:
        raise PolicyError("Local policy unavailable; remote access is disabled.") from None

def atomic_write(path, raw):
    validate_policy(raw)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".policy-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(raw, file, indent=2); file.write("\n"); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)  # Only our exact temporary file, never user data.

def control(action, path=DEFAULT_POLICY, minutes=None, now=None):
    now = now or utc_now()
    if action == "status":
        return AccessPolicy(path).snapshot(now)
    if action == "arm-write":
        if not isinstance(minutes, str) or not re.fullmatch(r"[0-9]+", minutes) or len(minutes) > 4 or not 1 <= int(minutes) <= 1440:
            raise PolicyError("Minutes must be an integer from 1 through 1440.")
        raw = read_policy(path, now)
        raw.update(base_mode="READ_ONLY", write_armed_until=utc_text(now + timedelta(minutes=int(minutes))))
    elif action in ("off", "read-only"):
        try:
            raw = read_policy(path, now)
        except PolicyError:
            raw = deepcopy(DEFAULTS)
        raw.update(base_mode="OFF" if action == "off" else "READ_ONLY", write_armed_until=None)
    else:
        raise PolicyError("Unknown local action")
    atomic_write(path, raw)
    return AccessPolicy(path).snapshot(now)

class AccessPolicy:
    def __init__(self, path=DEFAULT_POLICY):
        self.path = Path(path)

    def start(self):
        raw = read_policy(self.path)
        if raw["write_armed_until"] is not None:
            raw["write_armed_until"] = None
            atomic_write(self.path, raw)

    def snapshot(self, now=None):
        now = now or utc_now(); raw = read_policy(self.path, now)
        until = raw["write_armed_until"]
        armed = raw["base_mode"] == "READ_ONLY" and until is not None and parse_utc(until) > now
        return {"mode": "WRITE_ARMED" if armed else raw["base_mode"], "writes_armed": armed,
                "write_armed_until": until if armed else None, "principal": raw["principal"],
                "scopes": raw["scopes"], "rate_limits": raw["rate_limits"]}

class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock, self.buckets, self.lock = clock, {}, RLock()

    def consume(self, principal, tool, limits):
        with self.lock:
            now = self.clock(); keys = [(principal, "principal")]
            if tool is not None:
                keys.append((principal, tool))
            buckets = []
            for key in keys:
                queue = self.buckets.setdefault(key, deque())
                while queue and queue[0] <= now - 60:
                    queue.popleft()
                buckets.append((key, queue))
            retries = [math.ceil(queue[0] + 60 - now) for key, queue in buckets if len(queue) >= limits[key[1]]]
            if retries:
                raise Denied("rate_limited", 429, max(1, max(retries)))
            for key, queue in buckets:
                queue.append(now)

class SecurityAudit:
    def __init__(self, path=DEFAULT_AUDIT):
        self.path, self.lock = Path(path), RLock()

    def write(self, *, principal=None, tool=None, request_id=None, authentication="not_checked",
              authorization="denied", mode=None, code="internal_error", object_id=None, latency_ms=0):
        # Whitelist fields and identifiers; never log headers, arguments or exception strings.
        identifier = lambda s: s if isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", s) else None
        event = {"timestamp": utc_text(utc_now()), "principal": principal if principal == PRINCIPAL else None,
                 "tool": tool if tool in TOOL_POLICIES else None, "request_id": identifier(request_id),
                 "authentication": authentication, "authorization": authorization,
                 "remote_access_mode": mode if mode in ("OFF", "READ_ONLY", "WRITE_ARMED") else None,
                 "result_code": code, "object_id": identifier(object_id), "latency_ms": round(latency_ms, 3)}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event) + "\n")

def validate_registry(names):
    names = list(names)
    if len(names) != len(set(names)) or set(names) != set(TOOL_POLICIES):
        raise PolicyError("Public tool registry must exactly match the three S1 policies.")

def authorize(snapshot, tool):
    policy = TOOL_POLICIES.get(tool)
    if policy is None or policy.required_scope not in snapshot["scopes"]:
        raise Denied("insufficient_scope")
    if snapshot["mode"] == "OFF":
        raise Denied("remote_access_disabled")
    if policy.is_write and snapshot["mode"] != "WRITE_ARMED":
        raise Denied("remote_write_not_armed")
    return policy

class SecurityBoundary:
    def __init__(self, app, policy, audit, limiter=None):
        self.app, self.policy, self.audit = app, policy, audit
        self.limiter = limiter or RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send); return
        from mcp_auth import http_error
        started = time.monotonic(); snapshot = None; tool = None; request_id = None; rpc_id = None
        try:
            try:
                snapshot = self.policy.snapshot()
            except PolicyError:
                raise Denied("remote_access_disabled") from None
            if snapshot["mode"] == "OFF":
                raise Denied("remote_access_disabled")
            body = b""
            if scope["method"] == "POST":
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    body += event.get("body", b"")
                    if len(body) > 1048576:
                        raise Denied("validation_error", 400)
                    if not event.get("more_body", False): break
                try:
                    message = json.loads(body)
                    if not isinstance(message, dict): raise ValueError()
                except (ValueError, UnicodeError):
                    raise Denied("validation_error", 400) from None
                rpc_id = message.get("id")
                if not isinstance(rpc_id, (str, int)) or isinstance(rpc_id, bool): rpc_id = None
                if message.get("method") == "tools/call":
                    params = message.get("params", {})
                    if not isinstance(params, dict): raise Denied("validation_error", 400)
                    tool = params.get("name")
                    if not isinstance(tool, str): raise Denied("insufficient_scope")
                    arguments = params.get("arguments", {})
                    if isinstance(arguments, dict): request_id = arguments.get("request_id")
                    authorize(snapshot, tool)
            self.limiter.consume(snapshot["principal"], tool, snapshot["rate_limits"])
            self.audit.write(principal=PRINCIPAL, tool=tool, request_id=request_id, authentication="success",
                             authorization="allowed", mode=snapshot["mode"], code="accepted")
        except Denied as error:
            try:
                self.audit.write(principal=PRINCIPAL, tool=tool, request_id=request_id, authentication="success",
                                 mode=(snapshot or {}).get("mode"), code=error.code,
                                 latency_ms=(time.monotonic()-started)*1000)
            except Exception:
                logging.getLogger(__name__).error("Security audit unavailable; request denied.")
            await http_error(send, error.code, error.status, rpc_id, error.retry_after)
            return
        except Exception:
            await http_error(send, "internal_error", 500, rpc_id)
            return
        state = {"snapshot": snapshot, "tool": tool}
        handle = CURRENT_CALL.set(state); response_body = bytearray(); status = 500
        async def replay():
            nonlocal body
            if body is not None:
                event = {"type": "http.request", "body": body, "more_body": False}; body = None
                return event
            return await receive()
        async def capture(event):
            nonlocal status
            if event["type"] == "http.response.start": status = event["status"]
            elif event["type"] == "http.response.body" and len(response_body) < 1048576:
                response_body.extend(event.get("body", b""))
            await send(event)
        code = "internal_error"; object_id = None
        try:
            await self.app(scope, replay if scope["method"] == "POST" else receive, capture)
            code = "ok" if status < 400 else "validation_error"
            try:
                result = json.loads(response_body).get("result", {}).get("structuredContent", {})
                code = result.get("status", code)
                object_id = result.get("result", {}).get("object_id")
            except (ValueError, AttributeError): pass
        finally:
            CURRENT_CALL.reset(handle)
            try:
                self.audit.write(principal=PRINCIPAL, tool=tool, request_id=request_id, authentication="success",
                                 authorization="allowed", mode=snapshot["mode"], code=code, object_id=object_id,
                                 latency_ms=(time.monotonic()-started)*1000)
            except Exception:
                logging.getLogger(__name__).error("Security audit unavailable; further allowed requests will fail closed.")

def public_access():
    state = CURRENT_CALL.get()
    if state is None: return None
    return {k:v for k,v in state["snapshot"].items() if k != "rate_limits"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "off", "read-only", "arm-write"))
    parser.add_argument("--policy-file", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--minutes", default="120")
    args = parser.parse_args()
    try:
        print(json.dumps(control(args.action, args.policy_file, args.minutes), indent=2))
    except PolicyError:
        print(json.dumps({"ok":False, "status":"remote_access_disabled", "message":"Local policy unavailable or arguments invalid; remote access remains closed."}))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
