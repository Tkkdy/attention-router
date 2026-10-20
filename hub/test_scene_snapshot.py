# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Canonical Scene snapshot, runtime naming and authority metadata contracts."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

from fastapi.testclient import TestClient

from router_api import create_router_app

H = {"Authorization": "Bearer t"}
ESP = "tibo-v1,bitmap-titles-v1"


def dump(directory):
    db = sqlite3.connect(Path(directory) / "attention.sqlite3")
    try:
        return {t: db.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                for t in ("documents", "events", "decisions", "actions", "commands")}
    finally:
        db.close()


class SceneSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = create_router_app(self.dir, start_monitor=False, api_token="t")

    def tearDown(self):
        self.tmp.cleanup()

    def device(self):
        return TestClient(self.app, client=("192.168.1.50", 5000))

    def test_unavailable_before_any_publish_and_no_preview_fallback(self):
        with TestClient(self.app) as c:
            r = c.get("/api/scene/snapshot", headers=H).json()
            self.assertEqual(r["status"], "unavailable")
            self.assertEqual(r["reason"], "no_snapshot_published_for_profile")
            self.assertIsNone(r["snapshot"])
            self.assertEqual(r["profile"], "bitmap-titles-v1,tibo-v1")

    def test_requires_console_auth(self):
        with TestClient(self.app, client=("192.168.1.50", 5000)) as c:
            self.assertEqual(c.get("/api/scene/snapshot").status_code, 401)

    def test_device_response_equals_snapshot_and_read_has_no_side_effects(self):
        with self.device() as d, TestClient(self.app) as c:
            served = d.get("/scene", params={"capabilities": ESP}).json()
            before = dump(self.dir)
            r1 = c.get("/api/scene/snapshot", params={"capabilities": ESP}, headers=H).json()
            r2 = c.get("/api/scene/snapshot", params={"capabilities": "bitmap-titles-v1,tibo-v1,unknown-x"}, headers=H).json()
            self.assertEqual(dump(self.dir), before)  # no projection/route/delivery/action change
            self.assertEqual(r1["status"], "available")
            snap = r1["snapshot"]
            self.assertEqual(snap["scene"], served)
            self.assertEqual(snap["scene_version"], served["version"])
            self.assertEqual(snap["requester"], "lan_device_capability_marker")
            self.assertNotIn("preview_only", snap["scene"])
            for field in ("profile", "kind", "status", "reason", "snapshot"):
                self.assertEqual(r2[field], r1[field])  # normalized capabilities
            for response in (r1, r2):
                self.assertIsNotNone(datetime.fromisoformat(response["read_at"]).utcoffset())

    def test_profiles_are_isolated_and_snapshot_id_distinct_from_version(self):
        with self.device() as d, TestClient(self.app) as c:
            d.get("/scene", params={"capabilities": ESP})
            self.assertEqual(c.get("/api/scene/snapshot", params={"capabilities": "tibo-v1"}, headers=H).json()["status"], "unavailable")
            self.assertEqual(c.get("/api/scene/snapshot", params={"capabilities": ""}, headers=H).json()["profile"], "base")
            plain = d.get("/scene").json()
            base = c.get("/api/scene/snapshot", params={"capabilities": ""}, headers=H).json()["snapshot"]
            self.assertEqual(base["scene"], plain)
            self.assertEqual(base["requester"], "local_or_unmarked_request")
            first = c.get("/api/scene/snapshot", headers=H).json()["snapshot"]
            d.get("/scene", params={"capabilities": ESP})
            second = c.get("/api/scene/snapshot", headers=H).json()["snapshot"]
            self.assertEqual(first["scene_version"], second["scene_version"])
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertGreaterEqual(second["published_at"], first["published_at"])

    def test_overview_preview_contract_unchanged_and_does_not_publish(self):
        with TestClient(self.app) as c:
            o = c.get("/api/overview", headers=H).json()
            self.assertTrue(o["desired_scene"]["preview_only"])
            self.assertFalse(o["authority"]["desired_scene"]["canonical"])
            self.assertEqual(c.get("/api/scene/snapshot", headers=H).json()["status"], "unavailable")

    def test_runtime_naming_fields(self):
        with self.device() as d, TestClient(self.app) as c:
            r = c.get("/api/overview", headers=H).json()["runtime"]
            self.assertIsNone(r["esp32"]["device_requested_version"])
            self.assertEqual(r["display"]["status"], "NOT_IMPLEMENTED")
            served = d.get("/scene", params={"capabilities": ESP}).json()
            r = c.get("/api/overview", headers=H).json()["runtime"]
            self.assertEqual(r["esp32"]["device_requested_version"], served["version"])
            self.assertEqual(r["esp32"]["status"], "Online")
            self.assertEqual(r["display"]["display_complete"], "UNKNOWN")
            self.assertIn("not confirmed", r["esp32"]["device_requested_version_meaning"])
            self.assertEqual(r["deepseek"]["status"], "Unknown")
            self.assertEqual(set(r["claims"]), {"personal_hub", "context_monitor", "deepseek", "grokbot", "esp32", "display"})


if __name__ == "__main__":
    unittest.main()


class SnapshotProvenanceTests(unittest.TestCase):
    setUp = SceneSnapshotTests.setUp
    tearDown = SceneSnapshotTests.tearDown
    device = SceneSnapshotTests.device

    def test_provenance_comes_from_the_publishing_state(self):
        action = {**H, "X-Hub-Action": "1", "Origin": "http://testserver"}
        with TestClient(self.app) as c:
            c.post("/api/workspace/sync", headers=action, json={"revision": 1, "command_id": "w1", "project": "P",
                   "current_item": {"id": "cur-1", "title": "Item"}, "provenance": "SIMULATED"}).raise_for_status()
            c.post("/api/context", headers=action, json={"mode": "CODING"}).raise_for_status()
            served = self.device().get("/scene?capabilities=tibo-v1").json()
            # Later input change must not leak into the stored snapshot metadata.
            c.post("/api/workspace/sync", headers=action, json={"revision": 2, "command_id": "w2",
                   "current_item": {"id": "cur-2", "title": "Other"}, "provenance": "USER"}).raise_for_status()
            snap = c.get("/api/scene/snapshot?capabilities=tibo-v1", headers=H).json()
        s = snap["snapshot"]
        self.assertEqual(s["scene"], served)
        self.assertEqual(s["scene"]["workspace"]["current_item"], "Item")
        self.assertEqual(s["provenance"]["current_item_ref"]["id"], "cur-1")
        self.assertEqual(s["provenance"]["current_item_ref"]["id_kind"], "hub_workspace_current_item_id")
        self.assertEqual(s["provenance"]["workspace"]["provenance"], "SIMULATED")
        self.assertEqual(s["provenance"]["todos"]["todo_core_authority"], "UNKNOWN")
        self.assertNotIn("projected_from", s["provenance"])
        self.assertNotEqual(snap["read_at"], None)
