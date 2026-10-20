# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Read-only runtime observations. File existence alone is never liveness."""
import time
from datetime import datetime, timezone

class RuntimeView:
    def __init__(self, probe=None):
        self.probe = probe
        self.cached, self.checked = {}, 0

    def view(self, context, delivery, monitor_enabled=True):
        now = time.monotonic()
        if self.probe and now-self.checked > 5:
            try:
                self.cached = self.probe()
            except Exception:
                self.cached = {}
            self.checked = now
        checked_at = datetime.now(timezone.utc).isoformat()
        device_age = None
        try:
            device_age = (datetime.now(timezone.utc)-datetime.fromisoformat(delivery["last_device_request_at"])).total_seconds()
        except (KeyError, ValueError, TypeError): pass
        return {"personal_hub": {"status": "Running", "heartbeat": checked_at, "source": "successful overview response"},
            "context_monitor": {"status": context.get("monitor_status", "Stale") if monitor_enabled else "Stopped", "last_sample": context.get("sampled_at"), "last_successful_sample": context.get("last_successful_sample"), "error_category": context.get("error_category")},
            "deepseek": self.cached.get("deepseek", {"status": "Unknown", "endpoint": None, "ui_url": None, "reason": "No verified runtime endpoint", "last_activity": None}),
            "grokbot": self.cached.get("grokbot", {"status": "Unknown", "reason": "No client-specific heartbeat", "last_activity": None}),
            "esp32": {"source": "LAN scene request with device capability marker; not authenticated device identity", "checked_at": checked_at, "age_seconds": round(device_age, 1) if device_age is not None else None, "fresh_for_seconds": 45, "display_complete": "Unknown", "status": "Online" if device_age is not None and 0 <= device_age < 45 else "Unknown", "last_scene_request": delivery.get("last_device_request_at"),
                "device_requested_version": delivery.get("device_requested_version"),
                "device_requested_version_meaning": "Scene version Hub prepared for the latest device request; not confirmed received or displayed",
                "reason": "Recent LAN device-protocol request indicates reachability, not display completion; Standalone requires device evidence"},
            "display": {"status": "NOT_IMPLEMENTED", "received_scene": "UNKNOWN", "display_complete": "UNKNOWN", "pending_refresh": "UNKNOWN",
                "reason": "Device display receipt protocol not implemented"},
            "claims": {"personal_hub": "Hub responded to this overview request", "context_monitor": "Foreground sampler freshness only",
                "deepseek": "Managed process / local UI reachability; business_connection stays Unknown",
                "grokbot": "Recent successful Gateway operation within fresh_for_seconds; not a persistent heartbeat",
                "esp32": "Recent LAN /scene request with device capability marker; not authenticated identity", "display": "Unknown; no receipt"}}
