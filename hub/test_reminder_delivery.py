# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from reminder_compatibility import ReminderCompletionGate
from reminder_delivery import DeliveryLedger, ReminderDelivery, DefinitelyNotSent


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'delivery.sqlite3'
        self.binding = {'status': 'MAPPED', 'legacy_reminder': 'routine', 'new_todo_id': 'todo'}
        self.slot = '2026-10-14T08:00:00+08:00'
        self.state = {'revision': 8, 'todos': [{'todo_id': 'todo', 'status': 'pending'}]}
        self.gate = ReminderCompletionGate(lambda: {'ok': True, 'result': self.state})
        self.sent = []

    def sender(self, **args):
        self.sent.append(args)
        return True

    def adapter(self, gate=None, sender=None):
        return ReminderDelivery(gate or self.gate, DeliveryLedger(self.path), sender or self.sender)

    def test_restart_timezone_alias_and_remapping_do_not_repeat_send(self):
        result = self.adapter().deliver(self.binding, self.slot)
        self.assertEqual(result['status'], 'sent')
        self.assertTrue(result['sent_at'])
        self.adapter().deliver(self.binding, '2026-10-14T00:00:00Z')
        changed = self.adapter().deliver({**self.binding, 'new_todo_id': 'different'}, self.slot)
        self.assertEqual(changed['diagnostic'], 'binding_changed_requires_review')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.state['revision'], 8)
        self.assertEqual(self.state['todos'][0]['status'], 'pending')

    def test_concurrent_workers_have_one_sender(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(**args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test timeout')
            return self.sender(**args)
        first, second = self.adapter(sender=blocking), self.adapter()
        with ThreadPoolExecutor(2) as executor:
            future = executor.submit(first.deliver, self.binding, self.slot)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(second.deliver(self.binding, self.slot)['status'], 'dispatching')
            finally:
                release.set()
            self.assertEqual(future.result()['status'], 'sent')
        self.assertEqual(len(self.sent), 1)

    def test_core_outage_retry_rechecks_done(self):
        unavailable = ReminderCompletionGate(lambda: {'ok': False})
        result = self.adapter(gate=unavailable).deliver(self.binding, self.slot)
        self.assertEqual(result['status'], 'degraded_retry')
        self.assertTrue(result['failed_at'])
        self.state['todos'][0]['status'] = 'done'
        self.assertEqual(self.adapter().deliver(self.binding, self.slot)['status'], 'suppressed')
        self.assertEqual(self.sent, [])

    def test_missing_cancelled_unresolved_and_naive_time_fail_closed(self):
        for n, status in enumerate(('done', 'cancelled', 'missing')):
            self.state['todos'] = [] if status == 'missing' else [{'todo_id': 'todo', 'status': status}]
            row = self.adapter().deliver({**self.binding, 'legacy_reminder': str(n)}, self.slot)
            self.assertEqual(row['status'], 'suppressed')
            if status == 'missing':
                self.assertEqual(row['diagnostic'], 'missing_or_ambiguous_todo')
        row = self.adapter().deliver({**self.binding, 'status': 'NEEDS_USER_DECISION'}, self.slot)
        self.assertEqual(row['diagnostic'], 'unresolved_binding')
        with self.assertRaises(ValueError):
            self.adapter().deliver(self.binding, '2026-10-14T08:00:00')
        self.assertEqual(self.sent, [])

    def test_known_not_sent_retries_but_unknown_outcome_never_resends(self):
        def failed(**args):
            raise DefinitelyNotSent()
        self.assertEqual(self.adapter(sender=failed).deliver(self.binding, self.slot)['status'], 'failed_retry')
        self.assertEqual(self.adapter().deliver(self.binding, self.slot)['status'], 'sent')
        def uncertain(**args):
            self.sender(**args)
            raise TimeoutError('may have been delivered')
        other = {**self.binding, 'legacy_reminder': 'uncertain'}
        self.assertEqual(self.adapter(sender=uncertain).deliver(other, self.slot)['status'], 'unknown')
        self.adapter().deliver(other, self.slot)
        self.assertEqual(len(self.sent), 2)

    def test_process_crash_after_send_before_commit_holds_on_restart(self):
        def crash(**args):
            self.sender(**args)
            raise SystemExit('simulate process death before sent commit')
        with self.assertRaises(SystemExit):
            self.adapter(sender=crash).deliver(self.binding, self.slot)
        row = self.adapter().deliver(self.binding, self.slot)
        self.assertEqual(row['status'], 'dispatching')
        self.assertEqual(len(self.sent), 1)
