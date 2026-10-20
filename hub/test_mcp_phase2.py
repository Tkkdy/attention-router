# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Phase 2 Hub capability contracts; fixtures are isolated, never live state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from attention import AttentionService, Conflict, TodoSync
from hub_models import TodoUpsert, CurrentItemSet, WorkspaceSync, ContextOverride
from router_api import create_router_app


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.service = AttentionService(self.path)

    def todo(self, request_id="create", expected_revision=0, title="Check MCP", **kwargs):
        return TodoUpsert(request_id=request_id, expected_revision=expected_revision, title=title, **kwargs)

    def current(self, request_id="current", expected_revision=0, title="Work on MCP", **kwargs):
        return CurrentItemSet(request_id=request_id, expected_revision=expected_revision, title=title, **kwargs)

    def audit(self):
        return [a for a in self.service.overview()["recent_actions"] if a["stage"] == "MCP_CAPABILITY_APPLIED"]

    def test_replay_restart_identity_status_and_single_audit(self):
        first = self.service.upsert_todo(self.todo(status="done"))
        identifier = first["todo"]["id"]
        self.assertLessEqual(len(identifier), 23)
        updated = self.service.upsert_todo(self.todo("update", 1, "Check Grok MCP", todo_id=identifier))
        self.assertEqual(updated["todo"]["status"], "done")
        restarted = AttentionService(self.path)
        self.assertEqual(restarted.upsert_todo(self.todo(status="done")), first)
        self.assertEqual(len(restarted.tasks()), 1)
        self.assertEqual(restarted.tasks()[0]["title"], "Check Grok MCP")
        self.assertEqual(restarted.task_store.read()["revision"], 2)
        actions = self.audit()
        self.assertEqual(len(actions), 2)
        self.assertEqual({a["request_id"] for a in actions}, {"create", "update"})
        self.assertTrue(all(a["provenance"] == "MCP" and a["actor"] == "MCP_CLIENT" for a in actions))
        with self.assertRaises(Conflict):
            restarted.upsert_todo(self.todo(title="Changed payload"))
        with self.assertRaises(Conflict):
            restarted.set_current_item(self.current(request_id="create"))
        self.assertEqual(len(self.audit()), 2)

    def test_current_replay_preserves_user_project_suggestions_and_context(self):
        self.service.sync_workspace(WorkspaceSync(revision=1, command_id="user-work", project="Demo",
            suggestions=[{"id": "s", "text": "Optional advice"}], provenance="USER"))
        before = self.service.overview()
        request = self.current(expected_revision=1)
        first = self.service.set_current_item(request)
        self.assertEqual(self.service.set_current_item(request), first)
        after = self.service.overview()
        self.assertEqual(after["workspace"]["revision"], 2)
        self.assertEqual(after["workspace"]["project"], "Demo")
        self.assertEqual(after["workspace"]["suggestions"], before["workspace"]["suggestions"])
        self.assertEqual(after["context"], before["context"])
        self.assertEqual(after["events"], before["events"])
        self.assertEqual(after["delivery"], before["delivery"])
        self.assertEqual(after["desired_scene"]["page"], before["desired_scene"]["page"])
        self.assertEqual(after["workspace"]["current_item"]["provenance"], "MCP")
        self.assertEqual(after["workspace"]["last_mutation"]["actor"], "MCP_CLIENT")
        self.assertEqual(len(self.audit()), 1)
        # A user update between read and MCP write must win over stale intent.
        self.service.sync_workspace(WorkspaceSync(revision=3, command_id="user-new", project="New project", provenance="USER"))
        with self.assertRaises(Conflict):
            self.service.set_current_item(self.current("stale", 2))
        self.assertEqual(self.service.db.read("workspace")["project"], "New project")
        self.assertEqual(len(self.audit()), 1)

    def test_concurrent_writers_use_existing_transaction_and_snapshot_revision(self):
        self.service.tasks()  # Initialize the normal schema before starting threads.
        peers = [AttentionService(self.path), AttentionService(self.path)]
        def attempt(index):
            try:
                return peers[index].upsert_todo(self.todo(f"parallel-{index}"))
            except Conflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, [0, 1]))
        self.assertEqual(outcomes.count("conflict"), 1)
        self.assertEqual(len(self.service.tasks()), 1)
        self.assertEqual(self.service.task_store.read()["revision"], 1)
        self.assertEqual(len(self.audit()), 1)

    def test_legacy_snapshot_and_preview_mixed_provenance(self):
        self.service.sync_todos(TodoSync(revision=1, command_id="seed", tasks=[
            {"id": str(i), "title": f"Task {i}"} for i in range(5)]))
        old = self.service.overview()
        self.assertEqual(len(old["todos"]["tasks"]), 5)
        self.assertEqual(len(old["desired_scene"]["todos"]), 3)
        self.assertEqual(old["desired_scene"]["todo_remaining"], 2)
        self.service.upsert_todo(self.todo("rename", 1, "Rename task", todo_id="4"))
        after = self.service.overview()
        self.assertEqual(len(after["todos"]["tasks"]), 5)
        self.assertEqual(len(after["desired_scene"]["todos"]), 3)
        self.assertEqual(after["desired_scene"]["todo_remaining"], 2)
        self.assertTrue(after["desired_scene"]["simulated"])
        self.assertEqual(after["todos"]["tasks"][0]["provenance"], "SIMULATED")
        self.assertEqual(after["todos"]["tasks"][4]["provenance"], "MCP")
        self.service.sync_workspace(WorkspaceSync(revision=1, command_id="seed-work", project="Test",
            suggestions=[{"id": "s", "text": "Simulated advice"}]))
        self.service.set_current_item(self.current(expected_revision=1))
        self.service.set_context(ContextOverride(mode="CODING"))
        self.assertTrue(self.service.scene()["simulated"])
        self.service.sync_workspace(WorkspaceSync(revision=3, command_id="user-work", project="Real",
                                                 suggestions=[], provenance="USER"))
        self.assertEqual(self.service.db.read("workspace")["field_provenance"]["project"], "USER")
        # Legacy full snapshot remains available, including its normal validation.
        self.service.sync_todos(TodoSync(revision=3, command_id="user-todos", tasks=[{"id": "user", "title": "Keep"}], provenance="USER"))
        self.assertFalse(self.service.scene()["simulated"])

    def test_api_auth_validation_not_found_and_atomic_rollback(self):
        app = create_router_app(self.path, start_monitor=False)
        service = app.state.dashboard
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 1234)) as client:
            payload = self.todo().model_dump()
            endpoint = "/api/mcp/todos/upsert"
            self.assertEqual(client.post(endpoint, json=payload).status_code, 401)
            client.get("/")
            self.assertEqual(client.post(endpoint, json=payload).status_code, 403)
            client.headers.update({"X-Hub-Action": "1", "Origin": "http://127.0.0.1"})
            for extra in ({"provenance": "USER"}, {"actor": "GROKBOT"}, {"tasks": []}, {"revision": 999}):
                result = client.post(endpoint, json={**payload, **extra})
                self.assertEqual(result.status_code, 422)
                self.assertEqual(result.json()["status"], "validation_error")
                self.assertNotIn("input", str(result.json()))
            missing = client.post(endpoint, json={**payload, "todo_id": "missing"})
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["status"], "not_found")
            # Audit failure must roll back business state AND the idempotency ledger.
            with patch.object(service, "_action", side_effect=RuntimeError("secret SQLite path")):
                failed = client.post(endpoint, json=payload)
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.json()["status"], "internal_error")
            self.assertNotIn("secret", str(failed.json()))
            self.assertEqual(service.tasks(), [])
            result = client.post(endpoint, json=payload)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(client.post(endpoint, json=payload).json(), result.json())
            self.assertEqual(len(service.tasks()), 1)
            with service.db.transaction() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM commands").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
