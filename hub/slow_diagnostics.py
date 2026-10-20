# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Bounded, content-free slow-operation evidence independent of global logging."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading


operation_id = ContextVar("slow_operation_id", default=None)


class SlowDiagnostics:
    def __init__(self, path: Path, *, threshold_ms=1000):
        self.path = path
        self.threshold_ms = threshold_ms
        self.lock = threading.Lock()
        self.write_failures = 0
        self.last_error = None

    def record(self, kind, elapsed_ms, **fields):
        if elapsed_ms < self.threshold_ms:
            return
        entry = {"at": datetime.now(timezone.utc).isoformat(),
                 "kind": kind if kind in {"request", "context_sample", "transaction", "observation"} else "other",
                 "elapsed_ms": round(elapsed_ms, 3)}
        correlation = operation_id.get()
        if correlation is not None:
            entry["operation_id"] = correlation
        if "outcome" in fields:
            entry["outcome"] = "ok" if fields["outcome"] == "ok" else "error"
        for key in ("sample_ms", "transaction_ms", "python_lock_wait_ms", "connect_ms",
                    "sqlite_begin_ms", "initialize_ms", "body_ms", "commit_ms", "cleanup_ms"):
            if key in fields:
                entry[key] = round(fields[key], 3)
        if "status" in fields:
            entry["status"] = int(fields["status"])
        if "path" in fields:
            path = fields["path"]
            entry["path"] = path if path in {"/health", "/scene", "/api/overview", "/"} else "other"
        with self.lock:
            handler = None
            failure = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(self.path, maxBytes=262144, backupCount=2,
                                              encoding="utf-8", delay=True)
                record = logging.LogRecord("hub.slow", logging.WARNING, "", 0,
                    json.dumps(entry, ensure_ascii=True), (), None)
                # Direct handler use deliberately bypasses logging.disable() and stdout.
                if handler.shouldRollover(record):
                    handler.doRollover()
                # StreamHandler.emit swallows IO errors; write directly so failures count.
                if handler.stream is None:
                    handler.stream = handler._open()
                handler.stream.write(handler.format(record) + "\n")
                handler.flush()
            except Exception as error:
                failure = error
            finally:
                if handler:
                    try:
                        handler.close()
                    except Exception as error:
                        failure = failure or error
            if failure is not None:
                self.write_failures += 1
                self.last_error = type(failure).__name__
            else:
                self.last_error = None
