# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Restricted authenticated MCP contracts using unittest and real localhost HTTP."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from io import BytesIO
import json
from pathlib import Path
import socket
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from mcp_readonly import HubReader, NoRedirect, create_server, failure
from mcp_auth import BearerAuth, CredentialError, load_credential, provision_credential
from mcp_policy import DEFAULTS, atomic_write, control
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(process, url):
    deadline = time.monotonic() + 15
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Test server exited before readiness")
        try:
            with opener.open(url, timeout=.2):
                return
        except urllib.error.HTTPError:
            return  # /mcp GET may be 405 in stateless mode, but transport is ready.
        except (OSError, urllib.error.URLError):
            time.sleep(.05)
    raise AssertionError("Test server readiness timed out")


@contextmanager
def process(command, url, captured_logs=None):
    child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE if captured_logs is not None else subprocess.DEVNULL,
                             stderr=subprocess.STDOUT if captured_logs is not None else subprocess.DEVNULL)
    try:
        wait_ready(child, url)
        yield child
    finally:
        if child.poll() is None:
            child.terminate()
        output, _ = child.communicate(timeout=10)
        if captured_logs is not None: captured_logs.append(output or b"")



@asynccontextmanager
async def authenticated_client(endpoint, token):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    import httpx2
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False) as http:
        async with Client(streamable_http_client(endpoint, http_client=http)) as client:
            yield client


def assert_anonymous_http_rejected(test, endpoint):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    requests = [("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "auth-test", "version": "1"}}),
                ("tools/list", {}),
                ("tools/call", {"name": "upsert_todo", "arguments": {
                    "request_id": "must-not-write", "expected_revision": 0, "title": "Must not create"}}),
                ("tools/call", {"name": "set_current_item", "arguments": {
                    "request_id": "must-not-set", "expected_revision": 0, "title": "Must not set"}})]
    for authorization in (None, "Bearer " + secrets.token_urlsafe(32)):
        for method, params in requests:
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            if authorization is not None:
                headers["Authorization"] = authorization
            request = urllib.request.Request(endpoint, data=json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), headers=headers)
            with test.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(request, timeout=5)
            test.assertEqual(caught.exception.code, 401)
            test.assertEqual(json.load(caught.exception)["error"]["data"]["code"],
                             "auth_required" if authorization is None else "invalid_token")


class MCPAuthTests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.calls = 0

        async def underlying(scope, receive, send):
            self.calls += 1
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        from starlette.testclient import TestClient
        self.client = TestClient(BearerAuth(underlying, self.token))

    def test_missing_credential_rejected_before_dispatch(self):
        for method in ("GET", "POST", "DELETE", "HEAD", "OPTIONS"):
            result = self.client.request(method, "/mcp", content=b"invalid body")
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.headers["cache-control"], "no-store")
        self.assertEqual(self.calls, 0)

    def test_wrong_malformed_and_duplicate_credentials_rejected_before_dispatch(self):
        for authorization in ("Bearer " + secrets.token_urlsafe(32), "Basic anything", "Bearer",
                              "Bearer " + self.token + " ", "Bearer  " + self.token):
            result = self.client.post("/mcp", headers={"Authorization": authorization}, content=b"invalid")
            self.assertEqual(result.status_code, 401)
        duplicate = self.client.post("/mcp", headers=[("Authorization", "Bearer " + self.token),
                                                       ("Authorization", "Bearer " + self.token)])
        self.assertEqual(duplicate.status_code, 401)
        self.assertEqual(self.calls, 0)

    def test_correct_credential_permits_dispatch(self):
        result = self.client.post("/mcp", headers={"Authorization": "Bearer " + self.token})
        self.assertEqual(result.status_code, 204)
        self.assertEqual(self.calls, 1)

    @unittest.skipUnless(sys.platform == "win32", "CurrentUser DPAPI requires Windows")
    def test_dpapi_storage_and_fail_closed_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "token.dpapi"
            provision_credential(credential)
            token = load_credential(credential)
            self.assertEqual(len(token), 43)
            self.assertTrue(token.encode() not in credential.read_bytes())
            provision_credential(credential)
            self.assertTrue(load_credential(credential) == token)
            for file in (Path(directory) / "missing.dpapi", Path(directory) / "corrupt.dpapi"):
                if file.name == "corrupt.dpapi":
                    file.write_bytes(b"invalid ciphertext")
                with self.assertRaises(CredentialError):
                    load_credential(file)
                child = subprocess.run([sys.executable, "-B", str(ROOT / "hub/mcp_readonly.py"),
                                        "--port", str(free_port()), "--credential-file", str(file)],
                                       cwd=ROOT, capture_output=True, timeout=10)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn(b"service remains closed", child.stderr)
                self.assertNotIn(b"Traceback", child.stderr)
                self.assertTrue(token.encode() not in child.stdout + child.stderr)


class HubReaderTests(unittest.TestCase):
    def test_localhost_only_and_no_redirects(self):
        for url in ("https://127.0.0.1", "http://example.com", "http://127.0.0.1/x",
                    "http://user:secret@localhost", "http://localhost?x=1", "http://localhost#x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                HubReader(url)
        self.assertEqual(HubReader("http://localhost:8000").url, "http://127.0.0.1:8000")
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, None, None, None, None)

    def test_timeout_and_http_errors_are_sanitized(self):
        failures = [
            (TimeoutError("secret path"), "timeout"),
            (urllib.error.URLError(TimeoutError("secret path")), "timeout"),
            (urllib.error.URLError("secret path"), "hub_unreachable"),
            (urllib.error.HTTPError("http://localhost", 401, "secret", {}, None), "hub_http_error"),
        ]
        for error, code in failures:
            with self.subTest(code=code), patch("urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = error
                result = HubReader()()
                self.assertEqual(result["status"], code)
                self.assertFalse(result["ok"])
                self.assertNotIn("secret", json.dumps(result))

    def test_write_transport_failures_and_fixed_request_boundary(self):
        payload = {"request_id": "transport-test", "expected_revision": 0, "title": "Check MCP"}
        failures = [
            (TimeoutError("secret cookie/path"), "timeout"),
            (urllib.error.HTTPError("http://localhost", 409, "secret SQLite", {}, BytesIO(b'secret')), "conflict"),
            (urllib.error.HTTPError("http://localhost", 500, "secret SQLite", {}, BytesIO(b'secret')), "internal_error"),
        ]
        for name in ("upsert_todo", "set_current_item"):
            for error, code in failures:
                with self.subTest(tool=name, code=code), patch("urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = [BytesIO(b'console'), error]
                    reader = HubReader()
                    result = getattr(reader, name)(payload)
                    self.assertEqual(result["status"], code)
                    self.assertFalse(result["ok"])
                    self.assertNotIn("secret", str(result))
                    request = opener.return_value.open.call_args.args[0]
                    self.assertEqual(request.get_method(), "POST")
                    self.assertEqual(request.get_header("Origin"), reader.url)
                    self.assertEqual(request.get_header("X-hub-action"), "1")
                    self.assertEqual(json.loads(request.data), payload)
                    self.assertTrue(request.full_url.startswith(reader.url + "/api/mcp/"))

    def test_missing_fields_and_invalid_json_preserve_safe_partial_state(self):
        for payload, code in (({"hub": "READY", "workspace": {}}, "partial_state"),
                              ([], "invalid_state"), ("bad json", "invalid_state")):
            raw = payload if isinstance(payload, str) else json.dumps(payload)
            with self.subTest(code=code), patch("urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = [
                    BytesIO(b'{"status":"ok"}'), BytesIO(b'console'), BytesIO(raw.encode()),
                ]
                result = HubReader()()
                self.assertEqual(result["status"], code)
                if code == "partial_state":
                    self.assertEqual(result["state"]["hub"], "READY")
                    self.assertIn("desired_scene", result["error"]["missing_fields"])


class MCPHTTPTests(unittest.TestCase):
    def test_tool_errors_preserve_structure_and_hide_diagnostics(self):
        async def exercise():
            for code in ("timeout", "partial_state"):
                payload = failure(code)
                result = await create_server(lambda: payload).call_tool("get_hub_state", {})
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content, payload)
            def broken():
                raise RuntimeError("secret internal path")
            result = await create_server(broken).call_tool("get_hub_state", {})
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content["status"], "internal_error")
            self.assertNotIn("secret", str(result))
        asyncio.run(exercise())

    def test_discovery_call_hub_stop_and_recovery(self):
        # SDK client, independent gateway process, actual Hub HTTP business API.
        hub_port, mcp_port = free_port(), free_port()
        while mcp_port == hub_port:
            mcp_port = free_port()
        hub_url, endpoint = f"http://127.0.0.1:{hub_port}", f"http://127.0.0.1:{mcp_port}/mcp"
        with tempfile.TemporaryDirectory() as directory:
            credential = Path(directory) / "token.dpapi"
            provision_credential(credential)
            token = load_credential(credential)
            policy_file = Path(directory) / "policy.json"
            initial_policy = deepcopy(DEFAULTS)
            initial_policy["rate_limits"] = {name: 1000 for name in initial_policy["rate_limits"]}
            atomic_write(policy_file, initial_policy)
            audit_file = Path(directory) / "security.jsonl"
            hub_command = [sys.executable, "-B", "-c",
                "import sys; from pathlib import Path; sys.path.insert(0, 'hub'); "
                "from router_api import create_router_app; import uvicorn; "
                "uvicorn.run(create_router_app(Path(sys.argv[1]),start_monitor=False,environment='mcp-http-test'),"
                "host='127.0.0.1',port=int(sys.argv[2]),log_level='error')", directory, str(hub_port)]
            with process([sys.executable, "-B", str(ROOT / "hub/mcp_readonly.py"),
                          "--hub-url", hub_url, "--port", str(mcp_port), "--timeout", "5",
                          "--credential-file", str(credential), "--policy-file", str(policy_file),
                          "--audit-file", str(audit_file)], endpoint) as gateway:
                control("arm-write", policy_file, "120")
                async def exercise():
                    async with authenticated_client(endpoint, token) as client:
                        listed = await client.list_tools()
                        self.assertEqual([tool.name for tool in listed.tools], ["get_hub_state", "upsert_todo", "set_current_item"])
                        tool = listed.tools[0]
                        self.assertTrue(tool.annotations.read_only_hint)
                        self.assertFalse(tool.annotations.destructive_hint)
                        self.assertEqual(tool.input_schema["properties"], {})
                        self.assertFalse(tool.input_schema["additionalProperties"])
                        self.assertEqual((await client.list_resources()).resources, [])
                        self.assertEqual((await client.list_prompts()).prompts, [])
                        offline = await client.call_tool("get_hub_state", {})
                        self.assertTrue(offline.is_error)
                        self.assertEqual(offline.structured_content["status"], "hub_unreachable")
                        with process(hub_command, hub_url + "/health"):
                            online = await client.call_tool("get_hub_state", {})
                            self.assertFalse(online.is_error)
                            payload = online.structured_content
                            self.assertEqual(json.loads(online.content[0].text), payload)
                            self.assertTrue(payload["ok"])
                            self.assertEqual(payload["health"]["status"], "ok")
                            state = payload["state"]
                            assert_anonymous_http_rejected(self, endpoint)
                            unchanged = (await client.call_tool("get_hub_state", {})).structured_content["state"]
                            self.assertEqual(unchanged["todos"], state["todos"])
                            self.assertEqual(unchanged["workspace"], state["workspace"])
                            self.assertEqual(state["environment"], "mcp-http-test")
                            self.assertEqual(state["hub"], "READY")
                            self.assertEqual(state["device"]["received_scene"], "UNKNOWN")
                            self.assertTrue(state["request_id"].startswith("mcp-"))
                            self.assertIn(state["desired_scene"]["page"], ("home", "workspace", "interrupt"))
                            self.assertIn("stale", state["desired_scene"])
                            self.assertNotIn("recent_actions", state)
                            # No device delivery request, no Todo/event/command writes.
                            self.assertEqual(state["delivery"], {})
                            self.assertEqual(state["todos"]["tasks"], [])
                            rejected = await client.call_tool("get_hub_state", {"url": "http://example.com"})
                            self.assertTrue(rejected.is_error)
                            self.assertEqual(rejected.structured_content["status"], "validation_error")
                            self.assertIn("rendered_preview", payload["semantics"]["todo_lists"])
                            self.assertEqual(payload["semantics"]["grok_bot"]["scope"], "legacy_placeholder")
                            create_args = {"request_id": "http-create", "expected_revision": 0,
                                           "title": "Check MCP schema"}
                            created = await client.call_tool("upsert_todo", create_args)
                            self.assertFalse(created.is_error)
                            original = created.structured_content["result"]
                            todo_id = original["todo"]["id"]
                            self.assertEqual(original["todo"]["provenance"], "MCP")
                            self.assertEqual(original["todo"]["actor"], "MCP_CLIENT")
                            replay = await client.call_tool("upsert_todo", create_args)
                            self.assertEqual(replay.structured_content, created.structured_content)
                            updated = await client.call_tool("upsert_todo", {
                                "request_id": "http-update", "expected_revision": 1,
                                "todo_id": todo_id, "title": "Check Grok MCP schema", "status": "done"})
                            self.assertFalse(updated.is_error)
                            self.assertEqual(updated.structured_content["result"]["revision"], 2)
                            missing = await client.call_tool("upsert_todo", {
                                "request_id": "http-missing", "expected_revision": 2,
                                "todo_id": "missing", "title": "Missing Todo"})
                            self.assertEqual(missing.structured_content["status"], "not_found")
                            stale = await client.call_tool("upsert_todo", {
                                "request_id": "http-stale", "expected_revision": 0,
                                "todo_id": todo_id, "title": "Do not overwrite"})
                            self.assertEqual(stale.structured_content["status"], "conflict")
                            for change in ({"title": ""}, {"title": "非 ASCII"}, {"title": "X" * 34},
                                           {"status": "deleted"}, {"actor": "USER"}, {"tasks": []},
                                           {"expected_revision": "2"}, {"due": "15:00"}):
                                invalid = await client.call_tool("upsert_todo", {**create_args, **change})
                                self.assertTrue(invalid.is_error)
                                self.assertEqual(invalid.structured_content["status"], "validation_error")
                            current_args = {"request_id": "http-current", "expected_revision": 0,
                                            "title": "Work on MCP", "project": "Demo"}
                            current = await client.call_tool("set_current_item", current_args)
                            self.assertFalse(current.is_error)
                            self.assertEqual(current.structured_content["result"]["current_item"]["provenance"], "MCP")
                            again = await client.call_tool("set_current_item", current_args)
                            self.assertEqual(again.structured_content, current.structured_content)
                            current_conflict = await client.call_tool("set_current_item", {
                                **current_args, "request_id": "http-current-stale", "title": "Old intent"})
                            self.assertEqual(current_conflict.structured_content["status"], "conflict")
                            for extra in ({"revision": 100}, {"provenance": "USER"}, {"id": "override"},
                                          {"suggestions": []}, {"title": " "}):
                                invalid = await client.call_tool("set_current_item", {**current_args, **extra})
                                self.assertEqual(invalid.structured_content["status"], "validation_error")
                            after = (await client.call_tool("get_hub_state", {})).structured_content["state"]
                            self.assertEqual(after["todos"]["revision"], 2)
                            self.assertEqual(len(after["todos"]["tasks"]), 1)
                            self.assertEqual(after["todos"]["tasks"][0]["title"], "Check Grok MCP schema")
                            self.assertEqual(after["todos"]["tasks"][0]["status"], "done")
                            self.assertEqual(after["workspace"]["revision"], 1)
                            self.assertEqual(after["workspace"]["current_item"]["title"], "Work on MCP")
                            self.assertEqual(after["workspace"]["project"], "Demo")
                            self.assertEqual(after["context"], state["context"])
                            self.assertEqual(after["desired_scene"]["page"], state["desired_scene"]["page"])
                            self.assertEqual(after["delivery"], {})
                        for name, args in (("upsert_todo", create_args), ("set_current_item", current_args)):
                            offline_write = await client.call_tool(name, args)
                            self.assertTrue(offline_write.is_error)
                            self.assertEqual(offline_write.structured_content["status"], "hub_unreachable")
                        stopped = await client.call_tool("get_hub_state", {})
                        self.assertTrue(stopped.is_error)
                        self.assertEqual(stopped.structured_content["status"], "hub_unreachable")
                        self.assertIsNone(gateway.poll())
                        self.assertEqual([t.name for t in (await client.list_tools()).tools], ["get_hub_state", "upsert_todo", "set_current_item"])
                        with process(hub_command, hub_url + "/health"):
                            recovered = await client.call_tool("get_hub_state", {})
                            self.assertTrue(recovered.structured_content["ok"])
                            replay = await client.call_tool("upsert_todo", create_args)
                            self.assertEqual(replay.structured_content, created.structured_content)
                            replay_current = await client.call_tool("set_current_item", current_args)
                            self.assertEqual(replay_current.structured_content, current.structured_content)
                            persisted = (await client.call_tool("get_hub_state", {})).structured_content["state"]
                            self.assertEqual(len(persisted["todos"]["tasks"]), 1)
                            self.assertEqual(persisted["todos"]["revision"], 2)
                            self.assertEqual(persisted["workspace"]["revision"], 1)
                asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
