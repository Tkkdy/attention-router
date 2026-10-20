# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Durable pre-send adapter, not a scheduler. No Todo mutation or live sender.

The caller supplies an authoritative, timezone-aware scheduled occurrence (never
retry time). An uncertain external send is held for reconciliation, not retried.
Keep this ledger across restarts AND Todo rollback. Do not restore an older ledger.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


class DefinitelyNotSent(Exception):
    """Transport can prove no external delivery occurred; safe to retry."""


def occurrence_utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('scheduled occurrence must include an explicit timezone')
    return parsed.astimezone(timezone.utc).isoformat()


def now():
    return datetime.now(timezone.utc).isoformat()


class DeliveryLedger:
    def __init__(self, path):
        self.path = Path(path)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
                routine_id TEXT NOT NULL, scheduled_occurrence TEXT NOT NULL,
                todo_id TEXT, delivery_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, diagnostic TEXT, attempts INTEGER NOT NULL,
                updated_at TEXT NOT NULL, sent_at TEXT, failed_at TEXT,
                PRIMARY KEY (routine_id, scheduled_occurrence))''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, routine_id, occurrence):
        with self.connection() as db:
            row = db.execute('SELECT * FROM deliveries WHERE routine_id=? AND scheduled_occurrence=?',
                             (routine_id, occurrence_utc(occurrence))).fetchone()
            return dict(row) if row else None

    def claim(self, binding, occurrence):
        routine = binding['legacy_reminder']
        if not isinstance(routine, str) or not routine.strip():
            raise ValueError('stable routine_id required')
        occurrence = occurrence_utc(occurrence)
        todo = binding.get('new_todo_id')
        key = hashlib.sha256(json.dumps([routine, occurrence, todo], ensure_ascii=False).encode()).hexdigest()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM deliveries WHERE routine_id=? AND scheduled_occurrence=?',
                             (routine, occurrence)).fetchone()
            if row:
                if row['todo_id'] != todo:
                    return False, {**dict(row), 'diagnostic': 'binding_changed_requires_review'}
                if row['status'] not in ('degraded_retry', 'failed_retry'):
                    return False, dict(row)
                db.execute("UPDATE deliveries SET status='dispatching', attempts=attempts+1, updated_at=? WHERE delivery_key=?",
                           (now(), row['delivery_key']))
            else:
                db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,1,?,NULL,NULL)',
                           (routine, occurrence, todo, key, 'dispatching', None, now()))
        return True, self.get(routine, occurrence)

    def finish(self, key, status, diagnostic):
        stamp = now()
        with self.connection() as db:
            updated = db.execute('''UPDATE deliveries SET status=?, diagnostic=?, updated_at=?,
                sent_at=CASE WHEN ?='sent' THEN ? ELSE sent_at END,
                failed_at=CASE WHEN ? IN ('degraded_retry','failed_retry','unknown') THEN ? ELSE failed_at END
                WHERE delivery_key=? AND status='dispatching' ''',
                (status, diagnostic, stamp, status, stamp, status, stamp, key))
            if updated.rowcount != 1:
                raise RuntimeError('delivery claim lost')


class ReminderDelivery:
    def __init__(self, gate, ledger, sender):
        self.gate, self.ledger, self.sender = gate, ledger, sender

    def deliver(self, binding, scheduled_occurrence):
        claimed, row = self.ledger.claim(binding, scheduled_occurrence)
        if not claimed:
            return row
        key = row['delivery_key']
        # The durable reservation precedes lookup so concurrent workers cannot send.
        # A crash leaves dispatching: no lease expiry or automatic resend.
        try:
            decision = self.gate.evaluate(binding, row['scheduled_occurrence'])
        except Exception:
            decision = {'send_allowed': False, 'reason': 'status_unavailable'}
        if not decision['send_allowed']:
            status = 'degraded_retry' if decision['reason'] == 'status_unavailable' else 'suppressed'
            self.ledger.finish(key, status, decision['reason'])
        else:
            try:
                # Sender must return only after an acknowledged delivery. No Todo writes.
                receipt = self.sender(routine_id=row['routine_id'],
                    scheduled_occurrence=row['scheduled_occurrence'], todo_id=row['todo_id'], delivery_key=key)
                if receipt is not True:
                    raise RuntimeError('delivery not acknowledged')
            except DefinitelyNotSent:
                self.ledger.finish(key, 'failed_retry', 'transport_proved_not_sent')
            except Exception:
                self.ledger.finish(key, 'unknown', 'external_outcome_requires_reconciliation')
            else:
                self.ledger.finish(key, 'sent', 'acknowledged')
        return self.ledger.get(row['routine_id'], row['scheduled_occurrence'])
