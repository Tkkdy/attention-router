# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Transactional SQLite state; legacy JSON remains an untouched rollback source."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import time


class RouterStore:
    def __init__(self, directory: Path, defaults: dict, *, diagnostics=None) -> None:
        self.path = directory / "attention.sqlite3"
        self.defaults = defaults
        self.lock = threading.RLock()
        self.local = threading.local()
        self.diagnostics = diagnostics

    def _initialize(self, db: sqlite3.Connection) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError(f"Unsupported Attention database version: {version}")
        if version:
            return
        # Validate all input before creating any schema or importing any document.
        documents = {}
        for name, default in self.defaults.items():
            path = self.path.parent / f"{name}.json"
            value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else deepcopy(default)
            if not isinstance(value, dict):
                raise ValueError(f"{path.name} must contain an object")
            if name == "tasks" and not isinstance(value.get("tasks", []), list):
                raise ValueError("tasks.json tasks must contain a list")
            if name == "tasks":
                value["snapshot_known"] = path.exists() and "tasks" in value
            documents[name] = {**deepcopy(default), **value}
        db.execute("CREATE TABLE documents (name TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE events (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, sequence INTEGER NOT NULL UNIQUE, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE actions (id INTEGER PRIMARY KEY, event_id TEXT, revision INTEGER, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE commands (key TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL)")
        for name, value in documents.items():
            db.execute("INSERT INTO documents VALUES (?, ?)", (name, json.dumps(value, ensure_ascii=False)))
        db.execute("PRAGMA user_version=1")

    @contextmanager
    def transaction(self):
        if getattr(self.local, "db", None) is not None:
            with self.lock:
                yield self.local.db
            return
        with self._connection(read_only=False) as db:
            yield db

    @contextmanager
    def observation(self):
        """Read an initialized database without allowing diagnostic writes."""
        if getattr(self.local, "db", None) is not None:
            raise RuntimeError("observation requires an independent read boundary")
        with self._connection(read_only=True) as db:
            yield db

    @contextmanager
    def _connection(self, *, read_only):
        # Instrument the existing outer boundary only. Nested reads/writes still
        # use the same thread-local connection, including query-only observations.
        started = time.perf_counter()
        phases = {key: 0.0 for key in ("python_lock_wait_ms", "connect_ms",
                  "sqlite_begin_ms", "initialize_ms", "body_ms", "commit_ms", "cleanup_ms")}
        db = None
        outcome = "error"
        self.lock.acquire()
        phases["python_lock_wait_ms"] = (time.perf_counter() - started) * 1000
        try:
            phase = time.perf_counter()
            try:
                if read_only:
                    db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                         timeout=10, isolation_level=None)
                else:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
                db.row_factory = sqlite3.Row
                self.local.db = db
            finally:
                phases["connect_ms"] = (time.perf_counter() - phase) * 1000
            phase = time.perf_counter()
            try:
                if read_only:
                    db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN" if read_only else "BEGIN IMMEDIATE")
            finally:
                phases["sqlite_begin_ms"] = (time.perf_counter() - phase) * 1000
            if not read_only:
                phase = time.perf_counter()
                try:
                    self._initialize(db)
                finally:
                    phases["initialize_ms"] = (time.perf_counter() - phase) * 1000
            phase = time.perf_counter()
            try:
                yield db
            finally:
                phases["body_ms"] = (time.perf_counter() - phase) * 1000
            if not read_only:
                phase = time.perf_counter()
                try:
                    db.commit()
                finally:
                    phases["commit_ms"] = (time.perf_counter() - phase) * 1000
            outcome = "ok"
        finally:
            phase = time.perf_counter()
            try:
                if db is not None:
                    try:
                        if read_only or outcome != "ok":
                            db.rollback()
                    finally:
                        db.close()
            finally:
                self.local.db = None
                self.lock.release()
                phases["cleanup_ms"] = (time.perf_counter() - phase) * 1000
                if self.diagnostics is not None:
                    # Release this boundary's lock acquisition before diagnostic IO.
                    self.diagnostics.record("observation" if read_only else "transaction",
                        (time.perf_counter() - started) * 1000, outcome=outcome, **phases)

    def read(self, name: str) -> dict:
        with self.transaction() as db:
            row = db.execute("SELECT payload FROM documents WHERE name=?", (name,)).fetchone()
            return json.loads(row[0]) if row else deepcopy(self.defaults.get(name, {}))

    def write(self, name: str, value: dict) -> None:
        with self.transaction() as db:
            db.execute("INSERT INTO documents VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                       (name, json.dumps(value, ensure_ascii=False)))


class DocumentStore:
    """Keep the existing DashboardService/monitor storage contract."""
    def __init__(self, database: RouterStore, name: str) -> None:
        self.database, self.name = database, name

    def read(self) -> dict:
        return self.database.read(self.name)

    def write(self, value: dict) -> None:
        self.database.write(self.name, value)
