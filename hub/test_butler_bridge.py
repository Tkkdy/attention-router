# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Isolated Core -> existing Router/Scene bridge contract tests (no model/device)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from attention import AttentionService
from butler_bridge import ButlerHubBridge
from butler_gateway import ButlerGateway
from butler_models import Command
from hub_models import WorkspaceSync
from todo_core import ButlerError, TodoCore

ROOT = Path(__file__).resolve().parents[1]


class ButlerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='bridge-test-', dir=ROOT / '.build')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = TodoCore(self.root / 'todo-shadow.sqlite3')
        self.bridge_path = self.root / 'butler-attention-shadow'
        self.bridge = ButlerHubBridge(self.bridge_path)
        self.gateway = ButlerGateway(self.core, bridge=self.bridge)
        self.serial = 0

    def command(self, action, arguments=None, **overrides):
        self.serial += 1
        return Command.model_validate(dict(source='deepseek', request_id=f'test-{self.serial}',
            expected_revision=self.core.snapshot()['revision'], action=action,
            arguments=arguments or {}, **overrides))

    def run_command(self, action, arguments=None):
        return self.gateway.execute(self.command(action, arguments), principal='deepseek')

    def create(self, **fields):
        return self.run_command('create_todo', {'title': 'Test Todo', **fields})['todos'][-1]['todo_id']

    def event(self, **fields):
        return self.run_command('publish_attention_event',
            {'title': 'One thing', 'message': 'Please check this', **fields})

    def test_suggestion_preserves_core_todos_order_current_and_hub_current(self):
        first = self.create(title='First')
        second = self.create(title='Second')
        self.run_command('reorder_todos', {'todo_ids': [second, first]})
        self.run_command('set_current_item', {'todo_id': first})
        self.bridge.service.sync_workspace(WorkspaceSync(revision=1, command_id='seed-current',
            current_item={'id': 'legacy-current', 'title': 'Existing current'}))
        before = self.core.snapshot()
        hub_current = deepcopy(self.bridge.service.db.read('workspace')['current_item'])
        result = self.run_command('publish_suggestion', {'text': 'Consider taking a short break'})
        self.assertEqual(result['bridge']['status'], 'projected')
        self.assertEqual(result['todos'], before['todos'])
        self.assertEqual(result['current_item_id'], before['current_item_id'])
        workspace = self.bridge.service.db.read('workspace')
        self.assertEqual(workspace['current_item'], hub_current)
        self.assertEqual(workspace['suggestions'][0]['text'], 'Consider taking a short break')
        with self.assertRaises(ValidationError):
            self.command('publish_suggestion', {'text': 'Advice', 'todo_ids': [first, second]})

    def test_non_ascii_suggestion_explicitly_unprojected_then_device_text_supported(self):
        result = self.run_command('publish_suggestion', {'text': '\u53ef\u4ee5\u7a0d\u5fae\u4f11\u606f\u4e00\u4e0b'})
        self.assertEqual(result['suggestions'][0]['text'], '\u53ef\u4ee5\u7a0d\u5fae\u4f11\u606f\u4e00\u4e0b')
        self.assertEqual(result['bridge']['unprojected_suggestions'], [{
            'id': result['suggestions'][0]['id'], 'reason': 'explicit_ascii_device_text_required'}])
        self.assertEqual(self.bridge.service.db.read('workspace')['suggestions'], [])
        result = self.run_command('publish_suggestion', {'text': '\u53ef\u4ee5\u4f11\u606f', 'device_text': 'A short break may help'})
        self.assertEqual(self.bridge.service.db.read('workspace')['suggestions'][0]['text'], 'A short break may help')
        self.assertEqual(result['suggestions'][-1]['text'], '\u53ef\u4ee5\u4f11\u606f')
        with self.assertRaises(ValidationError):
            self.command('publish_suggestion', {'text': 'Advice', 'device_text': '\u4f11\u606f'})

    def test_reminder_requires_explicit_time_and_future_routes_queue(self):
        todo = self.create()
        before = self.core.snapshot()
        with self.assertRaises(ButlerError) as caught:
            self.event(kind='reminder', todo_id=todo)
        self.assertEqual(caught.exception.code, 'explicit_timed_reminder_required')
        self.assertEqual(self.core.snapshot(), before)
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.run_command('update_todo', {'todo_id': todo, 'remind_at': when})
        result = self.event(kind='reminder', todo_id=todo)
        event = self.bridge.service.trace(result['attention_events'][-1]['id'])['event']
        self.assertEqual(event['authorization'], 'user_reminder')
        self.assertEqual(datetime.fromisoformat(event['starts_at']), datetime.fromisoformat(when))
        self.assertEqual((event['route'], event['reason']), ('QUEUE', 'not_due'))

    def test_reminder_follows_changed_time_and_completion_cancels_without_ack(self):
        todo = self.create(remind_at='2000-01-01T00:00:00Z')
        result = self.event(kind='reminder', todo_id=todo)
        event_id = result['attention_events'][-1]['id']
        self.assertEqual(self.bridge.service.scene()['page'], 'interrupt')
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        changed = self.run_command('update_todo', {'todo_id': todo, 'remind_at': future})
        self.assertEqual(changed['bridge']['status'], 'projected')
        event = self.bridge.service.trace(event_id)['event']
        self.assertEqual(event['revision'], 2)
        self.assertEqual(event['route'], 'QUEUE')
        self.assertEqual(datetime.fromisoformat(event['starts_at']), datetime.fromisoformat(future))
        with self.assertRaises(ButlerError) as caught:
            self.run_command('ack_interrupt', {'event_id': event_id, 'event_revision': 1})
        self.assertEqual(caught.exception.code, 'event_revision_conflict')
        completed = self.run_command('complete_todo', {'todo_id': todo})
        self.assertEqual(completed['bridge']['status'], 'projected')
        event = self.bridge.service.trace(event_id)['event']
        self.assertEqual(event['status'], 'cancelled')
        self.assertIsNone(event['ack_at'])
        self.assertEqual(event['route'], 'DROP')
        restarted = ButlerHubBridge(self.bridge_path)
        self.assertEqual(restarted.project(self.core.snapshot())['status'], 'projected')
        self.assertEqual(restarted.service.trace(event_id)['event']['status'], 'cancelled')

    def test_event_cannot_self_assign_authorization_or_provenance(self):
        for field, value in [('authorization', 'user_reminder'), ('provenance', 'USER'),
                             ('starts_at', '2000-01-01T00:00:00Z')]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.command('publish_attention_event', {'title': 'A', 'message': 'B', field: value})
        result = self.event(kind='agent_result')
        event = self.bridge.service.trace(result['attention_events'][-1]['id'])['event']
        self.assertEqual((event['authorization'], event['route']), ('none', 'DIGEST'))

    def test_ack_preserves_todo_and_rejects_wrong_revision_and_replays_after_restart(self):
        todo = self.create(remind_at='2000-01-01T00:00:00Z')
        result = self.event(kind='reminder', todo_id=todo)
        event_id = result['attention_events'][-1]['id']
        self.assertEqual(self.bridge.service.scene()['page'], 'interrupt')
        before = deepcopy(result['todos'])
        with self.assertRaises(ButlerError) as caught:
            self.run_command('ack_interrupt', {'event_id': event_id, 'event_revision': 2})
        self.assertEqual(caught.exception.code, 'event_revision_conflict')
        command = self.command('ack_interrupt', {'event_id': event_id, 'event_revision': 1})
        acked = self.gateway.execute(command, principal='deepseek')
        self.assertEqual(acked['todos'], before)
        self.assertEqual(acked['todos'][0]['status'], 'pending')
        again_core = TodoCore(self.core.path)
        again_bridge = ButlerHubBridge(self.bridge_path)
        again = ButlerGateway(again_core, bridge=again_bridge).execute(command, principal='deepseek')
        self.assertEqual(again['revision'], acked['revision'])
        self.assertEqual(len(again['interrupt_acks']), 1)
        self.assertEqual(again_bridge.service.trace(event_id)['event']['status'], 'acknowledged')
        actions = again_bridge.service.trace(event_id)['actions']
        self.assertEqual(sum(a['stage'] == 'USER_ACKNOWLEDGED' for a in actions), 1)
        self.assertNotEqual(again_bridge.service.scene()['page'], 'interrupt')

    def test_projection_failure_retries_without_duplicate_events_or_suggestions(self):
        suggestion = self.command('publish_suggestion', {'text': 'One suggestion'})
        with patch.object(self.bridge.service, 'sync_workspace', side_effect=RuntimeError('injected')):
            pending = self.gateway.execute(suggestion, principal='deepseek')
        self.assertEqual(pending['bridge']['status'], 'projection_pending')
        recovered = self.gateway.execute(suggestion, principal='deepseek')
        self.assertEqual(recovered['bridge']['status'], 'projected')
        self.assertEqual(len(self.core.snapshot()['suggestions']), 1)
        self.assertEqual(len(self.bridge.service.db.read('workspace')['suggestions']), 1)
        command = self.command('publish_attention_event', {'title': 'A', 'message': 'B'})
        with patch.object(self.bridge.service, 'publish', side_effect=RuntimeError('injected')):
            pending = self.gateway.execute(command, principal='deepseek')
        self.assertEqual(pending['bridge']['status'], 'projection_pending')
        result = self.gateway.execute(command, principal='deepseek')
        event_id = result['attention_events'][0]['id']
        self.assertEqual(result['bridge']['status'], 'projected')
        self.gateway.execute(command, principal='deepseek')
        self.assertEqual(len(self.core.snapshot()['attention_events']), 1)
        self.assertEqual(len(self.bridge.service.overview()['events']), 1)
        self.assertEqual(sum(a['stage'] == 'RECEIVED' for a in self.bridge.service.trace(event_id)['actions']), 1)

    def test_dashboard_uses_core_authority_and_keeps_device_unknown(self):
        todo = self.create(title='Core only')
        self.run_command('set_current_item', {'todo_id': todo})
        view = self.run_command('get_dashboard_state')['dashboard']
        self.assertEqual(view['todos']['authority'], 'shadow')
        self.assertEqual(view['todos']['tasks'], self.core.snapshot()['todos'])
        self.assertEqual(view['todos']['current_item_id'], todo)
        self.assertEqual(set(view['device'].values()), {'UNKNOWN'})
        self.assertEqual(view['todo_scene_projection'], 'not_configured')
        self.assertEqual(view['data_scope'], 'isolated_shadow')

    def test_bridge_rejects_paths_outside_shadow_and_unavailable_gateway(self):
        for path in [ROOT / 'hub' / 'data', ROOT / 'butler-attention-shadow', self.root / 'wrong-name']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                ButlerHubBridge(path)
        with self.assertRaises(ButlerError) as caught:
            ButlerGateway(self.core).execute(self.command('get_dashboard_state'), principal='deepseek')
        self.assertEqual(caught.exception.code, 'bridge_unavailable')


if __name__ == '__main__':
    unittest.main()
