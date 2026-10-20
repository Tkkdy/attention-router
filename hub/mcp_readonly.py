# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Phase 2 restricted MCP gateway. Run as a separate Streamable HTTP process."""
import argparse
import http.cookiejar
import json
import math
from pathlib import Path
import socket
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit


# Only state already supplied by the Hub business API; no raw logs or storage.
STATE_FIELDS = (
    "environment", "instance_id", "request_id", "hub", "grok_bot", "context",
    "context_evidence", "workspace", "todos", "codex", "radar", "weather",
    "desired_scene", "device", "delivery",
)
REQUIRED_FIELDS = {
    "hub": str, "workspace": dict, "todos": dict, "radar": dict,
    "desired_scene": dict, "device": dict,
}
ERROR_MESSAGES = {
    "hub_unreachable": "Local Hub is unavailable. Start the Hub and retry.",
    "timeout": "Local Hub request timed out. Retry writes with identical request_id and arguments.",
    "hub_http_error": "Local Hub rejected the state request.",
    "invalid_state": "Local Hub returned an invalid state response.",
    "partial_state": "Some Hub state fields are unavailable.",
    "internal_error": "Hub operation failed. Retry writes with identical request_id and arguments.",
    "validation_error": "Input does not match the supported capability schema.",
    "not_found": "The requested Todo does not exist.",
    "auth_required": "Bearer credential required.",
    "invalid_token": "Bearer credential rejected.",
    "insufficient_scope": "Principal lacks the capability scope or tool policy.",
    "remote_access_disabled": "Remote access is disabled by local policy.",
    "remote_write_not_armed": "Remote writes are not armed locally.",
    "rate_limited": "Remote capability rate limit reached.",
    "conflict": "Revision is stale or request_id was reused with different arguments. Read Hub state before a new request.",
}


STATE_SEMANTICS = {
    "todo_lists": {
        "full_state": "state.todos.tasks is the full ordered Todo snapshot, including completed/cancelled items.",
        "rendered_preview": "state.desired_scene.todos is the ESP32 desired page preview, normally at most 3 eligible pending items; workspace excludes the current item by ID. It may be absent when the source is unknown.",
        "remaining": "state.desired_scene.todo_remaining counts eligible pending items beyond the preview, not all Todos.",
    },
    "grok_bot": {
        "scope": "legacy_placeholder",
        "description": "state.grok_bot is a hardcoded Hub placeholder. Hub tracks neither Grok agent registration nor external Remote MCP connector sessions; NOT_CONNECTED is not MCP connection evidence.",
        "remote_mcp_session": "NOT_OBSERVED_BY_HUB",
    },
    "write_revisions": {
        "upsert_todo": "Use state.todos.revision, or 0 when absent. Revision covers the whole Todo snapshot.",
        "set_current_item": "Use state.workspace.revision, or 0 when absent. Revision covers the whole workspace.",
    },
    "provenance": "MCP indicates the capability entrypoint; MCP_CLIENT is not a verified GrokBot or human identity. Snapshot provenance records its latest writer; per-item/field provenance retains mixed origins.",
}


def failure(code: str, *, health=None, state=None, missing_fields=None) -> dict:
    result = {"ok": False, "status": code,
              "error": {"code": code, "message": ERROR_MESSAGES[code]},
              "health": health, "state": state}
    if missing_fields is not None:
        result["error"]["missing_fields"] = missing_fields
    if state is not None:
        result["semantics"] = STATE_SEMANTICS
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Hub redirect rejected")


class HubReader:
    def __init__(self, url="http://127.0.0.1:8000", timeout=5):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("Hub URL must be a local HTTP origin")
        port = parsed.port or 80
        if not 1 <= port <= 65535 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Hub port and timeout must be positive")
        # Resolve localhost to a literal loopback; never rely on DNS for the Hub.
        host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
        self.url = f"http://{host}:{port}"
        self.timeout = timeout

    def __call__(self):
        health = None
        # A fresh cookie jar per call handles Hub restarts and concurrent clients.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        try:
            with opener.open(self.url + "/health", timeout=self.timeout) as response:
                raw_health = json.load(response)
            if not isinstance(raw_health, dict):
                return failure("invalid_state")
            health = {k: raw_health[k] for k in ("status", "version", "environment", "instance_id")
                      if k in raw_health}
            # Existing localhost console boundary; no credentials are read or saved.
            with opener.open(self.url + "/", timeout=self.timeout) as response:
                response.read()
            request = urllib.request.Request(self.url + "/api/overview", headers={
                "X-Hub-Request-ID": "mcp-" + uuid.uuid4().hex,
            })
            with opener.open(request, timeout=self.timeout) as response:
                raw = json.load(response)
            if not isinstance(raw, dict):
                return failure("invalid_state", health=health)
            state = {key: raw[key] for key in STATE_FIELDS if key in raw}
            missing = [key for key, kind in REQUIRED_FIELDS.items()
                       if not isinstance(state.get(key), kind)]
            scene = state.get("desired_scene")
            if isinstance(scene, dict):
                missing += ["desired_scene." + key for key in ("page", "stale") if key not in scene]
            if "status" not in health:
                missing.append("health.status")
            if missing:
                return failure("partial_state", health=health, state=state, missing_fields=missing)
            return {"ok": True, "status": "ok", "error": None, "health": health, "state": state,
                    "semantics": STATE_SEMANTICS}
        except urllib.error.HTTPError:
            return failure("hub_http_error", health=health)
        except (TimeoutError, socket.timeout):
            return failure("timeout", health=health)
        except urllib.error.URLError as error:
            code = "timeout" if isinstance(error.reason, TimeoutError) else "hub_unreachable"
            return failure(code, health=health)
        except (ValueError, UnicodeError):
            return failure("invalid_state", health=health)
        except OSError:
            return failure("hub_unreachable", health=health)
        except Exception:
            # Never return exception text, traceback, local paths or credentials.
            return failure("internal_error", health=health)


    def _write(self, path, payload):
        from mcp_policy import public_access
        access = public_access()
        # Path is selected by the two named methods below, never by an Agent.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        try:
            with opener.open(self.url + "/", timeout=self.timeout) as response:
                response.read()
            request = urllib.request.Request(self.url + path, method="POST",
                data=json.dumps(payload).encode("utf-8"), headers={
                    "Content-Type": "application/json", "X-Hub-Action": "1", "Origin": self.url,
                    **({"X-MCP-Principal": access["principal"]} if access else {}),
                })
            with opener.open(request, timeout=self.timeout) as response:
                result = json.load(response)
            if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("result"), dict):
                return failure("invalid_state")
            return {"ok": True, "status": "ok", "error": None, "result": result["result"]}
        except urllib.error.HTTPError as error:
            code = {400: "validation_error", 422: "validation_error", 404: "not_found",
                    409: "conflict", 500: "internal_error", 503: "hub_unreachable"}.get(error.code, "hub_http_error")
            return failure(code)
        except (TimeoutError, socket.timeout):
            return failure("timeout")
        except urllib.error.URLError as error:
            return failure("timeout" if isinstance(error.reason, TimeoutError) else "hub_unreachable")
        except (ValueError, UnicodeError):
            return failure("invalid_state")
        except OSError:
            return failure("hub_unreachable")
        except Exception:
            return failure("internal_error")

    def upsert_todo(self, payload):
        return self._write("/api/mcp/todos/upsert", payload)

    def set_current_item(self, payload):
        return self._write("/api/mcp/workspace/current-item", payload)


def create_server(reader=None, *, enforce_policy=False):
    from mcp_policy import TOOL_POLICIES, CURRENT_CALL, validate_registry, public_access
    from mcp.server import MCPServer
    from mcp_types import CallToolResult, TextContent, ToolAnnotations
    from mcp.server.mcpserver.tools import Tool
    from mcp.server.mcpserver.exceptions import ToolError
    from pydantic import ValidationError
    from hub_models import (TodoUpsert, CurrentItemSet, MCPRequestID, ExpectedRevision,
                            DeviceTitle, DeviceProject, TodoID, TodoStatus)

    gateway = reader if isinstance(reader, HubReader) else HubReader()
    read = reader if reader is not None else gateway

    def reply(payload):
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
                              structured_content=payload, is_error=not payload["ok"])

    class CapabilityServer(MCPServer):
        def add_tool(self, fn, name=None, **kwargs):
            if (name or fn.__name__) not in TOOL_POLICIES:
                raise ValueError("Tool has no public policy")
            return super().add_tool(fn, name=name, **kwargs)

        async def list_tools(self):
            tools = await super().list_tools()
            validate_registry(t.name for t in tools)
            return tools

        async def call_tool(self, name, arguments, context=None):
            if name not in TOOL_POLICIES:
                return reply(failure("insufficient_scope"))
            if enforce_policy:
                authorized = CURRENT_CALL.get()
                if authorized is None or authorized["tool"] != name:
                    return reply(failure("insufficient_scope"))
            try:
                return await super().call_tool(name, arguments, context)
            except ToolError as error:
                code = "validation_error" if isinstance(error.__cause__, ValidationError) else "internal_error"
                return reply(failure(code))
            except Exception:
                return reply(failure("internal_error"))

    def get_hub_state() -> CallToolResult:
        """Read full Hub state and ESP32 desired preview. See semantics; UNKNOWN and legacy grok_bot are not connection evidence."""
        try:
            payload = read()
            access = public_access()
            if access is not None: payload = {**payload, "remote_access": access}
            return reply(payload)
        except Exception:
            return reply(failure("internal_error"))

    def upsert_todo(request_id: MCPRequestID, expected_revision: ExpectedRevision,
                    title: DeviceTitle, todo_id: TodoID | None = None,
                    status: TodoStatus | None = None) -> CallToolResult:
        """Create without todo_id; update an existing Todo with todo_id. Read state.todos.revision (absent=0) first. Null status preserves existing status or defaults a new Todo to pending. No due time/reminder scheduling. Title must fit the ASCII panel. Retry identical request_id and arguments; use a new request_id for a new intent."""
        try:
            command = TodoUpsert(request_id=request_id, expected_revision=expected_revision,
                                 title=title, todo_id=todo_id, status=status)
            return reply(gateway.upsert_todo(command.model_dump(mode="json")))
        except ValidationError:
            return reply(failure("validation_error"))
        except Exception:
            return reply(failure("internal_error"))

    def set_current_item(request_id: MCPRequestID, expected_revision: ExpectedRevision,
                         title: DeviceTitle, project: DeviceProject | None = None) -> CallToolResult:
        """Set a workspace current item with a Hub-generated identity. Read state.workspace.revision (absent=0) first. Null/omitted project preserves it. Does not change context, force Scene, link a Todo by title, or write suggestions. Retry identical request_id and arguments; use a new request_id for a new intent."""
        try:
            command = CurrentItemSet(request_id=request_id, expected_revision=expected_revision,
                                     title=title, project=project)
            return reply(gateway.set_current_item(command.model_dump(mode="json")))
        except ValidationError:
            return reply(failure("validation_error"))
        except Exception:
            return reply(failure("internal_error"))

    tools = []
    for function, readonly in ((get_hub_state, True), (upsert_todo, False), (set_current_item, False)):
        tool = Tool.from_function(function, annotations=ToolAnnotations(
            read_only_hint=readonly, destructive_hint=False, idempotent_hint=True, open_world_hint=False,
        ))
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
        tools.append(tool)
    validate_registry(tool.name for tool in tools)
    return CapabilityServer("attention-hub-readonly", version="phase2-s1", subscriptions=False,
        instructions=("Attention Hub: get_hub_state, upsert_todo and set_current_item only. "
                      "Hub is the source of truth. Read revisions before writes; preserve request_id/arguments on retries. "
                      "MCP_CLIENT is not authenticated remote identity. No Interrupt/device/command capabilities."),
        tools=tools)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub-url", "--url", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=3001)
    parser.add_argument("--timeout", type=float, default=5)
    from mcp_auth import DEFAULT_CREDENTIAL, CredentialError, load_credential
    parser.add_argument("--credential-file", type=Path, default=DEFAULT_CREDENTIAL)
    from mcp_policy import DEFAULT_POLICY, DEFAULT_AUDIT, AccessPolicy, SecurityAudit, SecurityBoundary, PolicyError
    parser.add_argument("--policy-file", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--audit-file", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        reader = HubReader(args.hub_url, args.timeout)
    except ValueError:
        parser.error("Hub URL must be a local HTTP origin with a valid port and positive timeout")
    try:
        token = load_credential(args.credential_file)
    except CredentialError:
        parser.exit(1, "MCP credential unavailable; service remains closed. Run setup_mcp_auth.ps1 as the same Windows user.\n")
    policy = AccessPolicy(args.policy_file)
    try:
        policy.start()
    except (PolicyError, OSError):
        parser.exit(1, "MCP policy unavailable; service remains closed. Use remote_mcp_access.ps1 locally.\n")
    import uvicorn
    from mcp_auth import BearerAuth
    # Keep SDK transport/lifespan and Host/Origin protection; authenticate outermost.
    sdk_app = create_server(reader, enforce_policy=True).streamable_http_app(
        host="127.0.0.1", streamable_http_path="/mcp", stateless_http=True, json_response=True)
    audit = SecurityAudit(args.audit_file)
    app = BearerAuth(SecurityBoundary(sdk_app, policy, audit), token, audit=audit)
    del token
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
