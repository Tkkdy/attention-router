# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Read authenticated Codex app-server limits without model turns or auth changes."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_limits(executable, timeout=20):
    executable = Path(executable)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("An existing absolute Codex executable is required")
    # A fresh, bounded read-only session avoids an orphan reader on cancellation.
    messages = [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {
            "name": "attention_hub", "title": "Attention Hub quota collector", "version": "1.0-m3"}}},
        {"method": "initialized", "params": {}},
        {"id": 2, "method": "account/rateLimits/read", "params": {}},
    ]
    process = subprocess.Popen([str(executable), "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", cwd=str(executable.parent),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Keep stdin open until the response: closing it early can cancel the request.
    import queue
    import threading
    import time
    replies = queue.Queue()
    def read():
        for line in process.stdout:
            try:
                replies.put(json.loads(line))
            except ValueError:
                pass
    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
    deadline = time.monotonic() + timeout
    try:
        send(messages[0])
        while time.monotonic() < deadline:
            try:
                reply = replies.get(timeout=min(0.5, max(0.01, deadline-time.monotonic())))
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError("Codex source exited")
                continue
            if reply.get("id") == 1:
                if "error" in reply:
                    raise RuntimeError("Codex initialization failed")
                send(messages[1])
                send(messages[2])
            elif reply.get("id") == 2:
                result = reply.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Codex quota read failed")
                return sanitize_limits(result)
        raise TimeoutError("Codex quota read timed out")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        worker.join(timeout=1)
        process.stdin.close()
        process.stdout.close()


def sanitize_limits(result):
    buckets = result.get("rateLimitsByLimitId") or {}
    bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    bucket = bucket or result.get("rateLimits")
    if not isinstance(bucket, dict):
        raise ValueError("Codex quota bucket unavailable")
    windows = []
    for name in ("primary", "secondary"):
        window = bucket.get(name)
        if not isinstance(window, dict) or window.get("windowDurationMins") not in (300, 10080):
            continue
        used = window.get("usedPercent")
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
            continue
        windows.append({key: window.get(key) for key in ("windowDurationMins", "usedPercent", "resetsAt")})
    return {"source": "codex_app_server", "planType": bucket.get("planType"), "windows": windows}


class QuotaCollector:
    def __init__(self, service, executable=None, *, reader=None, interval=120):
        self.service = service
        self.reader = reader or (lambda: read_limits(executable))
        self.interval = max(60, interval)
        self.failures = 0

    def sample(self):
        attempt = timestamp()
        try:
            sample = self.reader()
            success = timestamp()
        except Exception as error:
            self.failures += 1
            with self.service.db.transaction() as db:
                state = self.service.state_store.read()
                sample = state.setdefault("codex", {})
                sample.update(collection="DEGRADED", last_attempt_at=attempt,
                    last_error=type(error).__name__, consecutive_failures=self.failures)
                self.service.state_store.write(state)
                self.service._action(db, None, "QUOTA_SAMPLE_FAILED", attempted_at=attempt,
                    error=type(error).__name__, consecutive_failures=self.failures)
        else:
            self.failures = 0
            with self.service.db.transaction() as db:
                state = self.service.state_store.read()
                state["codex"] = {**sample, "updated_at": success, "last_success_at": success,
                    "last_attempt_at": attempt, "collection": "AUTOMATIC", "consecutive_failures": 0}
                self.service.state_store.write(state)
                self.service._action(db, None, "QUOTA_SAMPLE_SUCCEEDED", sampled_at=success,
                    windows=[w["windowDurationMins"] for w in sample["windows"]])
        return min(1800, self.interval * 2 ** min(self.failures, 4))

    async def run(self):
        while True:
            delay = await asyncio.to_thread(self.sample)
            await asyncio.sleep(delay)
