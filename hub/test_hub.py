# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import DashboardService, create_app
from context_monitor import ContextDetector, ForegroundSample
from storage import JsonStore


class HubTests(unittest.TestCase):
    def test_context_hysteresis(self) -> None:
        detector = ContextDetector(enter_seconds=300, exit_seconds=120)
        code = ForegroundSample("Code.exe", "dashboard", 0)
        browser = ForegroundSample("chrome.exe", "docs", 0)
        self.assertEqual(detector.update(code, now=0), "IDLE")
        self.assertEqual(detector.update(code, now=299), "IDLE")
        self.assertEqual(detector.update(code, now=300), "CODING")
        self.assertEqual(detector.update(browser, now=350), "CODING")
        self.assertEqual(detector.update(browser, now=469), "CODING")
        self.assertEqual(detector.update(browser, now=470), "IDLE")

    def test_json_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            store = JsonStore(path / "state.json", {"answer": 0})
            self.assertEqual(store.read(), {"answer": 0})
            store.write({"answer": 42})
            self.assertEqual(store.read(), {"answer": 42})
            self.assertFalse((path / "state.json.tmp").exists())

    def test_workspace_api_and_visible_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                first = client.get("/scene").json()
                self.assertEqual(first["page"], "workspace")
                task = client.post(
                    "/tasks", json={"title": "Review PR", "namespace": "project"}
                ).json()
                self.assertEqual(client.post("/tasks", json={"title": "   "}).status_code, 422)
                second = client.get("/scene").json()
                self.assertEqual(second["version"], first["version"] + 1)
                self.assertEqual(second["todos"][0]["title"], "Review PR")

                client.post(
                    "/codex/quota",
                    json={"quota_5h_remaining": 99, "quota_total_remaining": 99},
                )
                first_bucket = client.get("/scene").json()
                self.assertEqual(first_bucket["version"], second["version"] + 1)
                client.post(
                    "/codex/quota",
                    json={"quota_5h_remaining": 98, "quota_total_remaining": 98},
                )
                same_bucket = client.get("/scene").json()
                self.assertEqual(same_bucket["version"], first_bucket["version"])

                client.post(
                    "/codex/quota",
                    json={"quota_5h_remaining": 73, "quota_total_remaining": 84},
                )
                changed_bucket = client.get("/scene").json()
                self.assertEqual(changed_bucket["version"], first_bucket["version"] + 1)
                self.assertEqual(
                    changed_bucket["codex"],
                    {"quota_5h_remaining": 70, "quota_total_remaining": 80},
                )

                response = client.patch(f"/tasks/{task['id']}", json={"status": "done"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get("/scene").json()["todos"], [])

    def test_radar_failed_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), start_monitor=False)
            service = app.state.dashboard
            state = service.state()
            state["radar"] = {
                "status": "FAILED",
                "updated_at": None,
                "detail": None,
                "stale": False,
            }
            service.state_store.write(state)
            with TestClient(app) as client:
                scene = client.get("/scene").json()
            self.assertEqual(scene["page"], "interrupt")
            self.assertEqual(scene["interrupt"]["priority"], 9)
            self.assertEqual(scene["interrupt"]["behavior"], "until_change")

    def test_interrupt_priority_resolution_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                low = client.post(
                    "/interrupt",
                    json={
                        "title": "CODEX",
                        "message": "TASK COMPLETE",
                        "priority": 5,
                        "behavior": "until_change",
                    },
                ).json()
                high = client.post(
                    "/interrupt",
                    json={
                        "title": "CODEX",
                        "message": "WAITING FOR YOU",
                        "priority": 9,
                        "behavior": "until_change",
                    },
                ).json()
                selected = client.get("/scene").json()
                self.assertEqual(selected["interrupt"]["id"], high["id"])

                client.patch(f"/interrupts/{high['id']}", json={"status": "resolved"})
                self.assertEqual(client.get("/scene").json()["interrupt"]["id"], low["id"])
                client.patch(f"/interrupts/{low['id']}", json={"status": "resolved"})
                self.assertEqual(client.get("/scene").json()["page"], "workspace")

    def test_auto_and_repeatable_lifecycle(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        auto = {
            "id": "auto",
            "status": "active",
            "starts_at": start.isoformat(),
            "behavior": "auto",
            "duration_seconds": 60,
            "repeat_seconds": 300,
        }
        repeatable = {
            "id": "repeat",
            "status": "active",
            "starts_at": start.isoformat(),
            "behavior": "repeatable",
            "duration_seconds": 60,
            "repeat_seconds": 300,
        }
        state = {"interrupts": [auto, repeatable]}
        self.assertEqual(len(DashboardService._active_interrupts(state, start)), 2)
        self.assertEqual(DashboardService._active_interrupts(state, start + timedelta(seconds=61)), [])
        repeated = DashboardService._active_interrupts(state, start + timedelta(seconds=301))
        self.assertEqual([event["id"] for event in repeated], ["repeat"])

    def test_reminder_and_state_event_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                reminder = client.post(
                    "/reminders",
                    json={
                        "message": "Pick up delivery",
                        "delay_seconds": 120,
                        "behavior": "repeatable",
                        "duration_seconds": 35,
                        "repeat_seconds": 90,
                    },
                )
                self.assertEqual(reminder.status_code, 201)
                self.assertEqual(reminder.json()["type"], "reminder")

                waiting = client.post(
                    "/state-events",
                    json={"task_id": "dashboard", "state": "WAITING_FOR_USER"},
                ).json()
                self.assertTrue(waiting["changed"])
                waiting_id = waiting["interrupt"]["id"]
                self.assertEqual(client.get("/scene").json()["interrupt"]["id"], waiting_id)

                duplicate = client.post(
                    "/state-events",
                    json={"task_id": "dashboard", "state": "WAITING_FOR_USER"},
                ).json()
                self.assertFalse(duplicate["changed"])

                running = client.post(
                    "/state-events", json={"task_id": "dashboard", "state": "RUNNING"}
                ).json()
                self.assertTrue(running["changed"])
                state = client.get("/state").json()
                resolved = next(event for event in state["interrupts"] if event["id"] == waiting_id)
                self.assertEqual(resolved["status"], "resolved")

                done = client.post(
                    "/state-events", json={"task_id": "dashboard", "state": "DONE"}
                ).json()
                self.assertEqual(done["interrupt"]["message"], "TASK COMPLETE")
                self.assertEqual(done["interrupt"]["behavior"], "auto")

                waiting_again = client.post(
                    "/state-events",
                    json={"task_id": "dashboard", "state": "WAITING_FOR_USER"},
                ).json()
                done_directly = client.post(
                    "/state-events", json={"task_id": "dashboard", "state": "DONE"}
                ).json()
                state = client.get("/state").json()
                old_waiting = next(
                    event
                    for event in state["interrupts"]
                    if event["id"] == waiting_again["interrupt"]["id"]
                )
                self.assertEqual(old_waiting["status"], "resolved")
                self.assertEqual(
                    client.get("/scene").json()["interrupt"]["id"],
                    done_directly["interrupt"]["id"],
                )

    def test_legacy_partial_waiting_state_repairs_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), start_monitor=False)
            service = app.state.dashboard
            task_id = "x" * 75
            state = service.state()
            state["agent_states"] = {f"codex:{task_id}": "WAITING_FOR_USER"}
            service.state_store.write(state)

            with TestClient(app) as client:
                repaired = client.post(
                    "/state-events",
                    json={"source": "codex", "task_id": task_id, "state": "WAITING_FOR_USER"},
                ).json()
                self.assertTrue(repaired["changed"])
                self.assertTrue(repaired["repaired"])
                self.assertEqual(client.get("/scene").json()["interrupt"]["id"], repaired["interrupt"]["id"])
                stored = client.get("/state").json()
                self.assertNotIn(f"codex:{task_id}", stored["agent_states"])
                self.assertIn(service._agent_ref("codex", task_id), stored["agent_states"])

    def test_legacy_waiting_event_resolves_on_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), start_monitor=False)
            service = app.state.dashboard
            state = service.state()
            state["agent_states"] = {"codex:dashboard": "WAITING_FOR_USER"}
            state["interrupts"] = [{
                "id": "legacy",
                "title": "CODEX",
                "message": "WAITING FOR YOU",
                "detail": "dashboard",
                "type": "alert",
                "priority": 9,
                "behavior": "until_change",
                "duration_seconds": 60,
                "repeat_seconds": 300,
                "starts_at": "2026-09-28T00:00:00+00:00",
                "created_at": "2026-09-28T00:00:00+00:00",
                "source": "codex",
                "source_ref": "codex:dashboard",
                "status": "active",
                "stale": False,
            }]
            service.state_store.write(state)
            with TestClient(app) as client:
                changed = client.post(
                    "/state-events",
                    json={"source": "codex", "task_id": "dashboard", "state": "RUNNING"},
                ).json()
                self.assertTrue(changed["changed"])
                stored = client.get("/state").json()
                event = next(event for event in stored["interrupts"] if event["id"] == "legacy")
                self.assertEqual(event["status"], "resolved")

    def test_concurrent_agent_transition_state_and_event_remain_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DashboardService(Path(directory))
            for index in range(25):
                task_id = f"race-{index}"
                from app import StateEvent
                waiting = StateEvent(task_id=task_id, state="WAITING_FOR_USER")
                running = StateEvent(task_id=task_id, state="RUNNING")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(service.handle_state_event, waiting),
                        pool.submit(service.handle_state_event, running),
                    ]
                    for future in futures:
                        future.result()

                key = service._agent_ref("codex", task_id)
                state = service.state()
                final = state["agent_states"][key]["state"]
                active = [
                    event
                    for event in state.get("interrupts", [])
                    if event.get("source_ref") == key and event.get("status") == "active"
                ]
                if final == "WAITING_FOR_USER":
                    self.assertEqual(len(active), 1)
                    self.assertEqual(active[0]["message"], "WAITING FOR YOU")
                else:
                    self.assertEqual(final, "RUNNING")
                    self.assertEqual(active, [])

    def test_short_alert_windows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                response = client.post(
                    "/interrupt",
                    json={
                        "title": "TEST",
                        "message": "TOO SHORT",
                        "behavior": "auto",
                        "duration_seconds": 1,
                    },
                )
                self.assertEqual(response.status_code, 422)
                accepted = client.post(
                    "/interrupt",
                    json={
                        "title": "TEST",
                        "message": "DELIVERABLE",
                        "behavior": "auto",
                        "duration_seconds": 35,
                    },
                )
                self.assertEqual(accepted.status_code, 201)

    def test_long_agent_identifier_commits_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                task_id = "x" * 75
                response = client.post(
                    "/state-events",
                    json={"source": "codex", "task_id": task_id, "state": "WAITING_FOR_USER"},
                )
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertTrue(body["changed"])
                self.assertLessEqual(len(body["interrupt"]["source_ref"]), 80)
                self.assertLessEqual(len(body["interrupt"]["detail"]), 47)
                self.assertEqual(client.get("/scene").json()["interrupt"]["id"], body["interrupt"]["id"])

                retry = client.post(
                    "/state-events",
                    json={"source": "codex", "task_id": task_id, "state": "WAITING_FOR_USER"},
                ).json()
                self.assertFalse(retry["changed"])

    def test_agent_identifier_pairs_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory), start_monitor=False)) as client:
                first = client.post(
                    "/state-events",
                    json={"source": "a:b", "task_id": "c", "state": "WAITING_FOR_USER"},
                ).json()
                second = client.post(
                    "/state-events",
                    json={"source": "a", "task_id": "b:c", "state": "WAITING_FOR_USER"},
                ).json()
                self.assertTrue(first["changed"])
                self.assertTrue(second["changed"])
                self.assertNotEqual(first["interrupt"]["source_ref"], second["interrupt"]["source_ref"])
                self.assertEqual(len(client.get("/state").json()["agent_states"]), 2)

    def test_stale_radar_interrupt_preserves_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), start_monitor=False)
            service = app.state.dashboard
            state = service.state()
            state["radar"] = {
                "status": "FAILED",
                "run_date": "2000-01-01",
                "updated_at": None,
                "detail": "Old failure",
                "stale": True,
            }
            service.state_store.write(state)
            with TestClient(app) as client:
                scene = client.get("/scene").json()
            self.assertEqual(scene["page"], "interrupt")
            self.assertTrue(scene["stale"])


if __name__ == "__main__":
    unittest.main()
