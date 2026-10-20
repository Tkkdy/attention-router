# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Tibo manual details and persistent, opt-in probability page lifecycle."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

class TiboAttentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    automatic_enabled: bool = False
    threshold_percent: int = Field(default=70, ge=0, le=100)
    detail_seconds: int = Field(default=60, ge=10, le=600)

class TiboLifecycle:
    def __init__(self, service):
        self.service, self.db = service, service.db

    def policy(self):
        return TiboAttentionPolicy(**self.db.read("tibo_attention_policy"))

    def configure(self, policy):
        with self.db.transaction():
            self.db.write("tibo_attention_policy", policy.model_dump())
            self.db.write("tibo_lifecycle", {"enabled": True})
            if not policy.automatic_enabled:
                self.db.write("tibo_automatic", {})
                self.db.write("tibo_detail", {})
        return policy.model_dump()

    def automatic(self, *, persist=True):
        policy = self.policy()
        prefs = self.service.tibo.preferences()
        if not policy.automatic_enabled or not prefs["enabled"] or not prefs["forecast_enabled"]:
            return None
        state = self.db.read("tibo_automatic")
        data = self.service.tibo.device()
        # Only fresh 24-hour forecasts can trigger; later drops/expiry do not dismiss.
        if not state.get("active"):
            chance = data["p24"]
            if data["forecast_status"] != "FRESH" or chance is None or chance <= policy.threshold_percent:
                return None
            if persist:
                self.db.write("tibo_automatic", {"active": True})
        return data

    def snapshot(self):
        view=self.service.tibo.view()
        return {"data": self.service.tibo.device(), "sources": {name: {
            "generated_at": (view[name].get("sample") or {}).get("generated_at"),
            "expires_at": (view[name].get("sample") or {}).get("expires_at")}
            for name in ("events", "forecast")}}

    def display_data(self, snapshot):
        data=dict(snapshot["data"])
        now=datetime.now(timezone.utc)
        current=self.service.tibo.view()
        for name, field in (("events", "status"), ("forecast", "forecast_status")):
            expiry=snapshot.get("sources", {}).get(name, {}).get("expires_at")
            expired=not expiry or now >= datetime.fromisoformat(expiry)
            if expired or current[name]["status"] != "FRESH":
                data[field]="STALE" if expired and data[field]=="FRESH" else current[name]["status"]
                if name=="forecast": data.update(p24=None,p48=None,p72=None)
                else: data["pending"]="UNKNOWN"
        return data

    def show(self, request_id):
        from attention import encode, stamp
        with self.db.transaction() as db:
            command = {"op": "show_tibo_page"}
            cached = self.service._command(db, "tibo:" + request_id, command)
            if cached is not None:
                return cached
            result = {"mode": "detail", "request_id": request_id, "requested_at": stamp(),
                "expires_at": (datetime.now(timezone.utc)+timedelta(seconds=self.policy().detail_seconds)).isoformat(),
                "ack_required": False, **self.snapshot()}
            self.db.write("tibo_detail", result)
            self.db.write("tibo_lifecycle", {"enabled": True})
            self.service._action(db, None, "TIBO_DETAIL_REQUESTED", request_id=request_id)
            db.execute("INSERT INTO commands VALUES(?,?,?)", ("tibo:"+request_id, encode(command), encode(result)))
            return result

    def test_event(self):
        from attention import EventInput
        event = EventInput(id="tibo-test-"+uuid4().hex[:16], revision=1, kind="tibo_reset",
            title="Tibo test attention", message="Explicit acknowledgment required", provenance="SIMULATED",
            expires_at=datetime.now(timezone.utc)+timedelta(minutes=30))
        with self.db.transaction() as db:
            result = self.service.publish(event)
            result["tibo_test_authorized"] = True
            result["tibo_snapshot"] = self.snapshot()
            result["attention_required"] = True
            self.service._save_event(db, result)
            self.db.write("tibo_lifecycle", {"enabled": True})
            self.service._reevaluate(db, "isolated_tibo_test")
            return self.service.trace(event.id)["event"]

    def acknowledge(self, event_id, revision, request_id):
        from attention import AckInput, Conflict
        with self.db.transaction():
            if self.service.trace(event_id)["event"]["kind"] != "tibo_reset":
                raise Conflict("not a Tibo attention event")
            result = self.service.acknowledge(event_id, AckInput(revision=revision, command_id="tibo:"+request_id))
            return result

    def detail(self):
        value = self.db.read("tibo_detail")
        if value and datetime.now(timezone.utc) < datetime.fromisoformat(value["expires_at"]):
            return value
        return None

    def view(self):
        with self.db.transaction() as db:
            events = []
            for event in self.service._events(db):
                if event["kind"] != "tibo_reset":
                    continue
                trace = self.service.trace(event["id"])
                actions = trace["actions"]
                events.append({"id": event["id"], "revision": event["revision"],
                    "attention_required": event.get("attention_required", False) and not event.get("ack_at") and event["status"] == "active",
                    "acknowledgment": "acknowledged" if event.get("ack_at") else "unacknowledged",
                    "received": event["received_at"], "routed": trace["decisions"][-1] if trace["decisions"] else "unknown",
                    "display_requested": next((a["at"] for a in reversed(actions) if a["stage"]=="DESIRED_SCENE_SAVED"), "unknown"),
                    "device_displayed": "unknown", "user_acknowledged": event.get("ack_at") or "unknown"})
            return {"policy": self.policy().model_dump(), "automatic_strategy": "p24_threshold_until_disabled",
                    "automatic_active": bool(self.db.read("tibo_automatic").get("active")),
                    "detail": self.detail(), "events": events}
