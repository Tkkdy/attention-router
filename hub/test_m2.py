# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""SIMULATED M2 behavior evidence, not a physical display or Grok acceptance."""
from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from attention import AttentionService, EventInput, TodoSync, AckInput, Conflict
from context_monitor import ForegroundSample, foreground_application
from hub_models import ContextOverride, WorkspaceSync, quota_view
from mcp_readonly import HubReader
from router_api import create_router_app
from work_context import WorkContext
from quota_policy import QuotaPreferences, display_policy


class M2Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.service = AttentionService(Path(temporary.name))

    def test_foreground_duration_brief_browser_unknown_gap(self):
        detector = WorkContext(enter_seconds=300, exit_seconds=125)
        sample = ForegroundSample("Codex.exe", "not retained", 0)
        for seconds in range(0, 300, 5):
            self.assertEqual(detector.update(sample, now=seconds)["automatic"], "IDLE")
        self.assertEqual(detector.update(sample, now=300)["automatic"], "CODING")
        browser = ForegroundSample("chrome.exe", "", 0)
        for seconds in range(305, 425, 5):
            self.assertEqual(detector.update(browser, now=seconds)["automatic"], "CODING")
        self.assertEqual(detector.update(browser, now=425)["automatic"], "IDLE")
        self.assertEqual(detector.update(None, now=430)["automatic"], "UNKNOWN")
        evidence = detector.update(sample, now=900)
        self.assertEqual(evidence["continuous_seconds"], 0)
        self.assertFalse(evidence["project_inferred"])
        self.assertEqual(evidence["unknown_reason"], "sample_gap")

    def test_current_codex_package_not_generic_chatgpt(self):
        self.assertEqual(foreground_application(r"C:\Program Files\WindowsApps\OpenAI.Codex_1.0_x64\app\ChatGPT.exe"), "codex_desktop")
        self.assertIsNone(foreground_application(r"C:\Program Files\ChatGPT\ChatGPT.exe"))
        detector = WorkContext(enter_seconds=5)
        sample = ForegroundSample("ChatGPT.exe", "", 0, "codex_desktop")
        detector.update(sample, now=0)
        self.assertEqual(detector.update(sample, now=5)["automatic"], "CODING")

    def test_user_override_and_monitor_failure(self):
        self.service.set_context(ContextOverride(mode="CODING"))
        with patch("attention.read_foreground", side_effect=OSError()):
            asyncio.run(self.service.sample_context())
        state = self.service.context()
        self.assertEqual(state["effective"], "CODING")
        self.assertEqual(state["automatic"], "UNKNOWN")
        self.assertEqual(state["unknown_reason"], "SAMPLER_INTERNAL_ERROR")
        self.assertEqual(self.service.set_context(ContextOverride(mode="AUTO"))["effective"], "UNKNOWN")
        self.assertNotIn("title", self.service.context())

    def test_expired_override_and_stale_sample_are_unknown(self):
        self.service.record_context({"automatic": "CODING", "reason": "test"}, provenance="SIMULATED")
        self.assertEqual(self.service.context()["effective"], "CODING")
        sample = self.service.db.read("context_evidence")
        sample["observed_at"] = "2000-01-01T00:00:00+00:00"
        self.service.db.write("context_evidence", sample)
        self.service.set_context(ContextOverride(mode="CODING", expires_at="2000-01-01T00:00:00Z"))
        self.assertEqual(self.service.context()["effective"], "UNKNOWN")

    def test_workspace_partial_order_suggestion_independent(self):
        tasks = [{"id": str(i), "title": f"Task {i}"} for i in range(5)]
        self.service.sync_todos(TodoSync(revision=1, command_id="todos", tasks=tasks))
        self.service.set_context(ContextOverride(mode="CODING"))
        self.service.sync_workspace(WorkspaceSync(revision=1, command_id="work", project="Demo", current_item={"id": "0", "title": "Task 0"}, suggestions=[{"id": "s", "text": "Optional advice"}]))
        scene = self.service.scene()
        self.assertEqual([t["id"] for t in scene["todos"]], ["1", "2", "3"])
        self.assertEqual(scene["todo_remaining"], 1)
        self.assertTrue(scene["simulated"])
        self.service.sync_workspace(WorkspaceSync(revision=2, command_id="suggest", suggestions=[]))
        self.assertEqual(self.service.db.read("workspace")["current_item"]["id"], "0")
        self.assertEqual([t["id"] for t in self.service.tasks()], ["0", "1", "2", "3", "4"])
        self.service.sync_workspace(WorkspaceSync(revision=3, command_id="clear", project=None))
        self.assertEqual(self.service.scene()["workspace"]["project"], "UNKNOWN")
        with self.assertRaises(Conflict):
            self.service.sync_workspace(WorkspaceSync(revision=2, command_id="stale", project="Old"))

    def test_workspace_idempotency_validation_and_rollback(self):
        request = WorkspaceSync(revision=1, command_id="work", project="Demo")
        first = self.service.sync_workspace(request)
        self.assertEqual(self.service.sync_workspace(request), first)
        with self.assertRaises(Conflict):
            self.service.sync_workspace(WorkspaceSync(revision=1, command_id="other", project="Different"))
        with patch.object(self.service, "_action", side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):
                self.service.sync_workspace(WorkspaceSync(revision=2, command_id="failure", project="Lost"))
        self.assertEqual(self.service.db.read("workspace")["project"], "Demo")
        with self.assertRaises(ValueError):
            WorkspaceSync(revision=3, command_id="invalid", suggestions=None)

    def test_page_projection_suppresses_hidden_updates(self):
        home = self.service.scene()["version"]
        self.service.sync_workspace(WorkspaceSync(revision=1, command_id="work", project="Hidden"))
        self.assertEqual(self.service.scene()["version"], home)
        self.service.publish(EventInput(id="alert", revision=1, title="Attention", message="Test", kind="reminder", authorization="user_reminder"))
        overlay = self.service.scene()["version"]
        self.service.sync_todos(TodoSync(revision=1, command_id="todos", tasks=[{"id": "a", "title": "Hidden"}]))
        self.service.set_context(ContextOverride(mode="CODING"))
        self.assertEqual(self.service.scene()["version"], overlay)
        self.service.acknowledge("alert", AckInput(revision=1, command_id="ack"))
        self.assertEqual(self.service.scene()["page"], "workspace")

    def test_queue_cancel_expire_and_context_reevaluation(self):
        self.service.set_context(ContextOverride(mode="QUIET"))
        self.service.publish(EventInput(id="wait", revision=1, title="Ready", message="Test", kind="agent_result", authorization="awaited_result"))
        self.assertEqual(self.service.trace("wait")["event"]["route"], "QUEUE")
        self.service.acknowledge("wait", AckInput(revision=1, command_id="cancel"), cancel=True)
        self.service.set_context(ContextOverride(mode="IDLE"))
        self.assertEqual(self.service.trace("wait")["event"]["route"], "DROP")
        self.assertIsNone(self.service.trace("wait")["event"]["ack_at"])
        self.service.publish(EventInput(id="expired", revision=1, title="Old", message="Test", kind="reminder", authorization="user_reminder", expires_at="2000-01-01T00:00:00Z"))
        self.assertEqual(self.service.scene()["page"], "home")
        self.assertEqual(self.service.trace("expired")["event"]["reason"], "expired_without_ack")

    def test_suggestion_expiry_and_radar_day_label(self):
        self.service.set_context(ContextOverride(mode="CODING"))
        self.service.sync_workspace(WorkspaceSync(revision=1, command_id="advice", suggestions=[{"id": "old", "text": "Expired", "expires_at": "2000-01-01T00:00:00Z"}]))
        self.assertEqual(self.service.scene()["workspace"]["suggestion"], "NONE / UNKNOWN")
        state = self.service.state_store.read()
        state["radar"] = {"status": "SUCCESS", "run_date": "2000-01-01", "updated_at": "2000-01-01T00:00:00Z", "stale": False}
        self.service.state_store.write(state)
        scene = self.service.scene()
        self.assertFalse(scene["radar"]["fresh"])
        self.assertEqual(scene["radar"]["run_date"], "2000-01-01")

    def test_quota_windows_snapshot_staleness_independent(self):
        now = datetime.now(timezone.utc)
        sample = {"source": "codex_app_server", "updated_at": now.isoformat(), "windows": [{"windowDurationMins": 10080, "usedPercent": 5, "resetsAt": now.timestamp() + 1000}]}
        view = quota_view(sample, now)
        self.assertEqual(view["collection"], "SNAPSHOT_ONLY")
        self.assertEqual(view["windows"][0]["status"], "UNKNOWN")
        self.assertEqual(view["windows"][1]["remaining_percent"], 95)
        self.assertEqual(quota_view(sample, now + timedelta(seconds=301))["windows"][1]["status"], "STALE")
        state = self.service.state_store.read()
        state["codex"] = sample
        self.service.state_store.write(state)
        self.assertIsNone(self.service.scene()["codex"]["quota_5h_remaining"])
        self.assertEqual(self.service.scene()["codex"]["quota_total_remaining"], 95)

    def test_new_api_uses_business_services_and_auth(self):
        app = create_router_app(self.service.db.path.parent, start_monitor=False, api_token="test-token")
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/context", json={"mode": "CODING"}).status_code, 401)
            client.headers["Authorization"] = "Bearer test-token"
            self.assertEqual(client.post("/api/context", json={"mode": "CODING"}).json()["effective"], "CODING")
            self.assertEqual(client.post("/api/workspace/sync", json={"revision": 1, "command_id": "w", "project": "Demo"}).status_code, 200)
            self.assertEqual(client.get("/api/overview").json()["desired_scene"]["workspace"]["project"], "Demo")

    def test_mcp_local_reader_and_failure(self):
        with self.assertRaises(ValueError):
            HubReader("https://external.example")
        reader = HubReader()
        with patch("urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = OSError("private diagnostics")
            result = reader()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "hub_unreachable")
        self.assertNotIn("private diagnostics", str(result))

    def test_quota_plus_pro_presets_and_trusted_plan_precedence(self):
        self.assertFalse(display_policy({}, {}, default_plan="pro")["five_hour"]["visible"])
        self.assertTrue(display_policy({}, {}, default_plan="plus")["five_hour"]["visible"])
        native = {"source": "codex_app_server", "planType": "plus", "windows": []}
        policy = display_policy({"manual_plan": "pro"}, native)
        self.assertEqual(policy["plan"], "plus")
        self.assertEqual(policy["plan_source"], "VERIFIED_PROVIDER")
        self.assertTrue(policy["five_hour"]["visible"])

    def test_quota_override_persists_restart_and_provider_poll(self):
        self.service.set_quota_preferences(QuotaPreferences(five_hour_override=True))
        restored = AttentionService(self.service.db.path.parent)
        self.assertTrue(restored.scene()["codex"]["show_5h"])
        state = restored.state_store.read()
        state["codex"] = {"source": "codex_app_server", "planType": "pro", "windows": []}
        restored.state_store.write(state)
        self.assertTrue(restored.scene()["codex"]["show_5h"])
        restored.set_quota_preferences(QuotaPreferences(five_hour_override=False))
        policy = restored.state()["codex"]["display_policy"]
        self.assertEqual(policy["five_hour"]["reason"], "USER_DISABLED")
        restored.set_quota_preferences(QuotaPreferences(five_hour_override=None))
        self.assertEqual(restored.state()["codex"]["display_policy"]["five_hour"]["reason"], "PLAN_PRESET_DISABLED")

    def test_quota_unknown_missing_is_not_plan_detection(self):
        native = {"source": "codex_app_server", "windows": []}
        policy = display_policy({}, native, default_plan="unknown")
        self.assertEqual(policy["plan"], "unknown")
        self.assertEqual(policy["five_hour"]["reason"], "PLAN_UNKNOWN")
        self.service.set_quota_preferences(QuotaPreferences(manual_plan="plus"))
        scene = self.service.scene()
        self.assertTrue(scene["codex"]["show_5h"])
        self.assertIsNone(scene["codex"]["quota_5h_remaining"])
        self.assertIsNone(scene["codex"]["quota_total_remaining"])

    def test_quota_disabled_hidden_updates_do_not_refresh_or_alert(self):
        self.service.set_context(ContextOverride(mode="CODING"))
        now = datetime.now(timezone.utc)
        raw = {"source": "codex_app_server", "updated_at": now.isoformat(), "planType": "pro",
               "windows": [{"windowDurationMins": 300, "usedPercent": 1}, {"windowDurationMins": 10080, "usedPercent": 13}]}
        state = self.service.state_store.read()
        state["codex"] = raw
        self.service.state_store.write(state)
        before = self.service.scene()
        raw["windows"][0]["usedPercent"] = 99
        raw["updated_at"] = (now + timedelta(seconds=1)).isoformat()
        self.service.state_store.write(state)
        # A genuine later poll, without sleeping or faking actual acceptance.
        with patch("attention.datetime") as clock:
            clock.now.return_value = now + timedelta(seconds=2)
            clock.fromisoformat.side_effect = datetime.fromisoformat
            after = self.service.scene()
        self.assertEqual(before["version"], after["version"])
        self.assertFalse(after["codex"]["show_5h"])
        self.assertEqual(after["codex"]["quota_total_remaining"], 87)
        self.assertEqual(self.service.overview()["events"], [])
        self.assertFalse(self.service.state()["codex"]["display_policy"]["five_hour"]["alerts_enabled"])
        raw["updated_at"] = now.isoformat()
        raw["windows"][1]["usedPercent"] = 20
        self.service.state_store.write(state)
        self.assertEqual(self.service.scene()["codex"]["quota_total_remaining"], 80)
        self.assertGreater(self.service.scene()["version"], before["version"])

    def test_quota_not_applicable_distinct_from_disabled_or_missing(self):
        sample = {"source": "codex_app_server", "planType": "plus", "window_support": {"300": False}}
        policy = display_policy({"five_hour_override": True}, sample)
        self.assertFalse(policy["five_hour"]["visible"])
        self.assertEqual(policy["five_hour"]["reason"], "PLAN_NOT_APPLICABLE")
        self.assertEqual(policy["five_hour"]["applicability"], "NOT_APPLICABLE")
        self.assertTrue(policy["seven_day"]["visible"])

    def test_quota_settings_api_authenticated(self):
        app = create_router_app(self.service.db.path.parent, start_monitor=False, api_token="test")
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/codex/preferences", json={"five_hour_override": True}).status_code, 401)
            client.headers["Authorization"] = "Bearer test"
            response = client.post("/api/codex/preferences", json={"five_hour_override": True})
            self.assertTrue(response.json()["five_hour"]["visible"])
            self.assertTrue(client.get("/scene").json()["codex"]["show_5h"])


if __name__ == "__main__":
    unittest.main()
