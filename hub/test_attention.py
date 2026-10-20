# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""SIMULATED deterministic contract checks; never evidence of Grok/ESP32 delivery."""
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from app import app as deployed_app
from router_api import create_router_app
from attention import AttentionService, EventInput, TodoSync, AckInput, Conflict
from hub_models import ContextOverride


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.service = AttentionService(self.directory)

    def event(self, id="one", **changes):
        return EventInput(**{"id": id, "revision": 1, "title": "TEST", "message": "Action needed",
                            "kind": "reminder", "authorization": "user_reminder", **changes})

    def test_atomic_migration_keeps_json_and_restarts(self):
        path = self.directory / "tasks.json"
        original = json.dumps({"tasks": [{"id": "old", "title": "Keep", "status": "pending"}]})
        path.write_text(original)
        self.service.publish(self.event())
        self.service.acknowledge("one", AckInput(revision=1, command_id="ack"))
        again = AttentionService(self.directory)
        self.assertEqual(again.tasks()[0]["id"], "old")
        self.assertEqual(again.overview()["events"][0]["status"], "acknowledged")
        self.assertEqual(path.read_text(), original)
        trace = again.trace("one")
        self.assertTrue(any(a["stage"] == "USER_ACKNOWLEDGED" for a in trace["actions"]))
        self.assertTrue(any(d["trigger"] == "startup" for d in trace["decisions"]))

    def test_invalid_migration_is_atomic(self):
        path = self.directory / "tasks.json"
        path.write_text('{"tasks":null}')
        with self.assertRaises(ValueError):
            self.service.overview()
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.directory / "attention.sqlite3")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0)
        self.assertEqual(path.read_text(), '{"tasks":null}')

    def test_routes_have_distinct_actions_and_queue_reevaluates(self):
        self.service.publish(self.event())
        self.service.publish(self.event("queued", starts_at="2099-01-01T00:00:00Z"))
        self.service.publish(self.event("news", kind="news", authorization="none", priority=9))
        self.service.publish(self.event("expired", expires_at="2000-01-01T00:00:00Z"))
        routes = {e["id"]: e["route"] for e in self.service.overview()["events"]}
        self.assertEqual(routes, {"one": "NOW", "queued": "QUEUE", "news": "DIGEST", "expired": "DROP"})
        for id, stage in [("one", "SCENE_REQUESTED"), ("queued", "QUEUED"), ("news", "DIGEST_SAVED"), ("expired", "ATTENTION_WITHDRAWN")]:
            self.assertIn(stage, [a["stage"] for a in self.service.trace(id)["actions"]])
        self.service.publish(self.event("queued", revision=2))
        self.service.acknowledge("one", AckInput(revision=1, command_id="ack"))
        self.assertEqual(self.service.scene()["interrupt"]["id"], "queued")

    def test_work_context_queues_waited_result_until_context_changes(self):
        self.service.set_context(ContextOverride(mode="CODING"))
        self.service.publish(self.event(kind="agent_result", authorization="awaited_result"))
        self.assertEqual(self.service.scene()["page"], "workspace")
        self.service.set_context(ContextOverride(mode="IDLE"))
        self.assertEqual(self.service.scene()["interrupt"]["id"], "one")

    def test_ack_idempotency_versions_and_todos_unchanged(self):
        self.service.sync_todos(TodoSync(revision=1, command_id="todo", tasks=[{"id": "a", "title": "First"}]))
        self.service.publish(self.event())
        command = AckInput(revision=1, command_id="ack")
        first = self.service.acknowledge("one", command)
        self.assertEqual(self.service.acknowledge("one", command), first)
        self.service.publish(self.event(revision=2, message="New version"))
        # A replayed successful ACK returns its original result without mutating v2.
        self.assertEqual(self.service.acknowledge("one", command), first)
        with self.assertRaises(Conflict):
            self.service.acknowledge("one", AckInput(revision=1, command_id="old"))
        self.assertEqual(self.service.scene()["interrupt"]["revision"], 2)
        self.assertEqual(self.service.tasks()[0]["status"], "pending")

    def test_duplicate_and_out_of_order_event_revisions(self):
        first = self.service.publish(self.event())
        self.assertEqual(self.service.publish(self.event()), first)
        with self.assertRaises(Conflict):
            self.service.publish(self.event(message="different"))
        self.service.publish(self.event(revision=2))
        with self.assertRaises(Conflict):
            self.service.publish(self.event())

    def test_unread_does_not_timeout_and_cancellation_is_not_ack(self):
        self.service.publish(self.event(starts_at="2000-01-01T00:00:00Z"))
        self.assertEqual(self.service.scene()["page"], "interrupt")
        self.service.acknowledge("one", AckInput(revision=1, command_id="cancel"), cancel=True)
        event = self.service.trace("one")["event"]
        self.assertIsNone(event["ack_at"])
        self.assertEqual(self.service.scene()["page"], "home")

    def test_order_missing_empty_and_stale_todo_snapshots(self):
        items = [{"id": "z", "title": "User first"}, {"id": "a", "title": "User second"}]
        self.service.sync_todos(TodoSync(revision=2, command_id="two", tasks=items))
        self.service.sync_todos(TodoSync(revision=3, command_id="missing"))
        self.assertEqual([t["id"] for t in self.service.tasks()], ["z", "a"])
        with self.assertRaises(Conflict):
            self.service.sync_todos(TodoSync(revision=1, command_id="stale", tasks=[]))
        self.service.sync_todos(TodoSync(revision=3, command_id="empty", tasks=[]))
        self.assertEqual(AttentionService(self.directory).tasks(), [])

    def test_absent_legacy_todo_source_never_clears_device_cache(self):
        self.assertNotIn("todos", self.service.scene())
        self.service.sync_todos(TodoSync(revision=1, command_id="omitted"))
        self.assertNotIn("todos", self.service.scene())
        self.service.sync_todos(TodoSync(revision=1, command_id="explicit", tasks=[]))
        self.assertEqual(self.service.scene()["todos"], [])
        self.assertEqual(AttentionService(self.directory).scene()["todos"], [])

    def test_hidden_todo_tail_does_not_change_scene_version(self):
        items = [{"id": str(i), "title": f"Task {i}"} for i in range(4)]
        self.service.sync_todos(TodoSync(revision=1, command_id="one", tasks=items))
        version = self.service.scene()["version"]
        items[3]["title"] = "Hidden updated"
        self.service.sync_todos(TodoSync(revision=2, command_id="two", tasks=items))
        self.assertEqual(self.service.scene()["version"], version)

    def test_unknown_sources_stale_data_and_no_device_claim(self):
        overview = self.service.overview()
        self.assertEqual(overview["codex"]["status"], "UNKNOWN")
        self.assertEqual(overview["grok_bot"], "UNKNOWN")
        self.assertFalse(overview["desired_scene"]["stale"])  # Disabled optional providers do not invalidate local content.
        self.assertIsNone(overview["desired_scene"]["codex"]["quota_5h_remaining"])
        self.service.publish(self.event())
        self.assertFalse(self.service.scene()["stale"])  # A newly published user reminder is fresh.
        self.service.served(self.service.scene())
        self.assertEqual(self.service.overview()["device"]["display_complete"], "UNKNOWN")
        self.assertIn("HTTP_RESPONSE_PREPARED", [a["stage"] for a in self.service.trace("one")["actions"]])

    def test_api_auth_validation_ack_and_trace(self):
        application = create_router_app(self.directory, start_monitor=False, api_token="test-only-token")
        with TestClient(application) as client:
            self.assertEqual(client.post("/api/events", json=self.event().model_dump(mode="json")).status_code, 401)
            client.headers["Authorization"] = "Bearer test-only-token"
            self.assertEqual(client.post("/api/events", json=self.event().model_dump(mode="json")).status_code, 201)
            self.assertEqual(client.get("/scene").json()["page"], "interrupt")
            self.assertEqual(client.post("/api/events/one/ack", json={"revision": 1, "command_id": "ack"}).status_code, 200)
            self.assertEqual(client.get("/scene").json()["page"], "home")
            self.assertEqual(client.get("/api/events/one").json()["event"]["status"], "acknowledged")
            invalid = self.event("two").model_dump(mode="json") | {"shell": "anything"}
            self.assertEqual(client.post("/api/events", json=invalid).status_code, 422)
            self.assertEqual(client.post("/api/todos/sync", json={"revision": 1, "command_id": "null", "tasks": None}).status_code, 422)

    def test_console_session_and_csrf_boundary(self):
        application = create_router_app(self.directory, start_monitor=False)
        with TestClient(application, base_url="http://localhost", client=("127.0.0.1", 1234)) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/overview").status_code, 200)
            payload = self.event().model_dump(mode="json")
            self.assertEqual(client.post("/api/events", json=payload).status_code, 403)
            headers = {"X-Hub-Action": "1", "Origin": "http://localhost"}
            self.assertEqual(client.post("/api/events", headers=headers, json=payload).status_code, 201)
            self.assertEqual(client.get("/", headers={"host": "evil.example"}).status_code, 401)

    def test_transaction_rollback_keeps_event_and_trace_consistent(self):
        from unittest.mock import patch
        with patch.object(self.service, "_reevaluate", side_effect=RuntimeError("fault")):
            with self.assertRaises(RuntimeError):
                self.service.publish(self.event())
        self.assertEqual(self.service.overview()["events"], [])


if __name__ == "__main__":
    unittest.main()
