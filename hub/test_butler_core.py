# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Real isolated SQLite/Gateway acceptance; resolvers and HTTP clients are simulated.

No live Hub import, production database, provider call, or authority cutover.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from butler_models import Command
from butler_gateway import ButlerGateway, create_butler_app
from todo_core import ButlerError, TodoCore
from todo_shadow import ShadowSnapshot, parity


class ButlerCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='butler-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'todo-shadow.sqlite3'
        self.core = TodoCore(self.path)
        self.gateway = ButlerGateway(self.core)
        self.sequence = 0

    def command(self, action, arguments=None, *, source='grok', revision=None, request_id=None):
        self.sequence += 1
        return Command(source=source, request_id=request_id or f'test-{self.sequence}',
                       expected_revision=self.core.snapshot()['revision'] if revision is None else revision,
                       action=action, arguments=arguments or {})

    def execute(self, action, arguments=None, **kwargs):
        command = self.command(action, arguments, **kwargs)
        return self.gateway.execute(command, principal=command.source)

    def create(self, title='Software engineering'):
        return self.execute('create_todo', {'title': title})['todos'][-1]['todo_id']

    def test_authoritative_stats_revision_retry_and_restart(self):
        self.assertEqual(self.execute('get_context')['stats'], {'total': 0, 'pending': 0, 'done': 0})
        create = self.command('create_todo', {'title': 'Same title'}, request_id='stats-create')
        first = self.gateway.execute(create, principal='grok')
        first_id = first['todos'][0]['todo_id']
        second_id = self.create('Same title')
        self.execute('complete_todo', {'todo_id': first_id})
        self.execute('update_todo', {'todo_id': second_id, 'status': 'cancelled'})
        current = self.execute('list_todos')
        self.assertEqual(current['stats'], {'total': 2, 'pending': 0, 'done': 1})
        retry = self.gateway.execute(create, principal='grok')
        self.assertEqual(retry['revision'], first['revision'])
        self.assertEqual(retry['stats'], {'total': 1, 'pending': 1, 'done': 0})
        self.assertEqual(TodoCore(self.path).snapshot()['stats'], current['stats'])
        self.execute('delete_todo', {'todo_id': second_id})
        self.assertEqual(self.core.snapshot()['stats'], {'total': 1, 'pending': 0, 'done': 1})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertNotIn('"stats"', db.execute('SELECT payload FROM state').fetchone()[0])

    def assert_error(self, code, callback):
        with self.assertRaises(ButlerError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_crud_stable_identity_source_timestamps_and_audit(self):
        todo_id = self.create()
        created = self.core.snapshot()['todos'][0]
        result = self.execute('update_todo', {'todo_id': todo_id, 'title': 'Course demo',
                                            'due_at': '2026-10-12T12:00:00+00:00'}, source='deepseek')
        updated = result['todos'][0]
        self.assertEqual(updated['todo_id'], todo_id)
        self.assertEqual(updated['created_at'], created['created_at'])
        self.assertGreaterEqual(updated['updated_at'], created['updated_at'])
        self.assertEqual((updated['title'], updated['updated_by'], updated['revision']),
                         ('Course demo', 'deepseek', 2))
        self.assertEqual(self.execute('list_todos')['todos'], result['todos'])
        self.assertEqual(self.execute('complete_todo', {'todo_id': todo_id})['todos'][0]['status'], 'done')
        self.assertEqual(self.execute('delete_todo', {'todo_id': todo_id})['todos'], [])
        with closing(sqlite3.connect(self.path)) as db:
            audit = db.execute('SELECT source,action,revision FROM operations ORDER BY revision').fetchall()
        self.assertEqual(audit, [('grok', 'create_todo', 1), ('deepseek', 'update_todo', 2),
                                 ('grok', 'complete_todo', 3), ('grok', 'delete_todo', 4)])
        self.assertEqual(self.core.snapshot()['authority'], 'shadow')

    def test_reorder_and_current_item_are_explicit_persistent_state(self):
        first, second = self.create('A'), self.create('B')
        state = self.execute('reorder_todos', {'todo_ids': [second, first]})
        self.assertEqual([(t['todo_id'], t['position']) for t in state['todos']], [(second, 0), (first, 1)])
        self.execute('set_current_item', {'todo_id': first})
        restored = TodoCore(self.path).snapshot()
        self.assertEqual(restored['current_item_id'], first)
        self.assertEqual(restored['context']['current_item_id'], first)
        self.assertEqual(self.execute('get_current_item')['current_item_id'], first)
        cleared = self.execute('set_current_item', {'todo_id': None})
        self.assertIsNone(cleared['current_item_id'])
        self.assertEqual([t['todo_id'] for t in cleared['todos']], [second, first])

    def test_delete_current_and_pending_target_clears_dangling_references(self):
        todo_id = self.create()
        self.execute('set_current_item', {'todo_id': todo_id})
        self.execute('set_pending_question', {'question': 'Finished?', 'target_todo_id': todo_id})
        result = self.execute('delete_todo', {'todo_id': todo_id})
        for field in ['current_item_id', 'pending_question', 'pending_question_target']:
            self.assertIsNone(result['context'][field])
        self.assertIsNone(result['current_item_id'])

    def test_stale_revision_rejected_without_state_change(self):
        todo_id = self.create()
        before = self.core.snapshot()
        error = self.assert_error('conflict', lambda: self.execute('complete_todo', {'todo_id': todo_id}, revision=0))
        self.assertEqual((error.status, error.revision), (409, 1))
        self.assertEqual(self.core.snapshot(), before)

    def test_invalid_reorder_and_unknown_target_do_not_partially_write(self):
        first, second = self.create('A'), self.create('B')
        before = self.core.snapshot()
        for ids in [[first], [first, first], [first, 'missing']]:
            self.assert_error('invalid_reorder', lambda: self.execute('reorder_todos', {'todo_ids': ids}))
        self.assert_error('todo_not_found', lambda: self.execute('set_current_item', {'todo_id': 'missing'}))
        self.assertEqual(self.core.snapshot(), before)

    def test_idempotent_retry_and_payload_mismatch_survive_restart(self):
        command = self.command('create_todo', {'title': 'Only once'}, request_id='stable-request')
        original = self.gateway.execute(command, principal='grok')
        self.create('Later write')
        restored = ButlerGateway(TodoCore(self.path))
        self.assertEqual(restored.execute(command, principal='grok'), original)
        self.assertEqual(len(restored.core.snapshot()['todos']), 2)
        changed = command.model_copy(update={'arguments': {'title': 'Different payload'}})
        self.assert_error('idempotency_conflict', lambda: restored.execute(changed, principal='grok'))
        self.assertEqual(restored.core.snapshot()['revision'], 2)

    def test_two_independent_services_same_revision_one_wins(self):
        gateways = [ButlerGateway(TodoCore(self.path)), ButlerGateway(TodoCore(self.path))]
        barrier = threading.Barrier(2)
        commands = [self.command('create_todo', {'title': source}, source=source, revision=0)
                    for source in ['grok', 'deepseek']]

        def run(index):
            barrier.wait(timeout=5)
            try:
                return gateways[index].execute(commands[index], principal=commands[index].source)
            except ButlerError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        failures = [r for r in results if isinstance(r, ButlerError)]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, 'conflict')
        self.assertEqual(failures[0].revision, 1)
        self.assertEqual(len(self.core.snapshot()['todos']), 1)

    def test_pending_question_cross_entry_and_business_context_restart(self):
        todo_id = self.create()
        self.execute('set_pending_question', {'question': '这个任务完成了吗？', 'target_todo_id': todo_id})
        seen = []

        def resolver(envelope):
            seen.append(envelope)
            return {'action': 'complete_todo', 'arguments': {'todo_id': envelope['state']['context']['pending_question_target']}}

        deepseek = ButlerGateway(TodoCore(self.path), resolver)
        command = self.command('resolve_intent', {'original_user_message': '完成了。', 'source_hint': 'non-authoritative'},
                               source='deepseek')
        result = deepseek.execute(command, principal='deepseek')
        self.assertEqual(seen[0]['original_user_message'], '完成了。')
        self.assertEqual(seen[0]['state']['context']['pending_question_target'], todo_id)
        self.assertEqual(result['todos'][0]['status'], 'done')
        self.assertEqual(result['context']['updated_by'], 'deepseek')
        self.assertIsNone(result['context']['pending_question'])
        self.assertEqual(TodoCore(self.path).snapshot(), result)
        self.assertNotIn('完成了。', str(result['context']))
        self.assertEqual(result['context']['context_revision'], 3)

    def test_natural_language_read_resolves_without_mutating_business_state(self):
        self.create('Read naturally')
        before = self.core.snapshot()
        gateway = ButlerGateway(self.core, lambda _: {'action': 'list_todos', 'arguments': {}})
        command = self.command('resolve_intent', {'original_user_message': '列出我的待办'})
        self.assertEqual(gateway.execute(command, principal='grok'), before)
        self.assertEqual(self.core.snapshot(), before)

    def test_structured_actions_bypass_missing_or_failing_resolver(self):
        def resolver(_):
            self.fail('Structured action must never call a resolver')

        for injected in [None, resolver]:
            gateway = ButlerGateway(self.core, injected)
            command = self.command('create_todo', {'title': 'Direct action'})
            self.assertEqual(gateway.execute(command, principal='grok')['todos'][-1]['title'], 'Direct action')
        command = self.command('resolve_intent', {'original_user_message': 'move it'})
        self.assert_error('semantic_resolver_unavailable', lambda: self.gateway.execute(command, principal='grok'))

    def test_resolver_timeout_is_redacted_and_no_write_occurs(self):
        def unavailable(_):
            raise RuntimeError('secret-provider-response')

        before = self.core.snapshot()
        command = self.command('resolve_intent', {'original_user_message': 'Create something'})
        error = self.assert_error('semantic_resolver_unavailable',
                                  lambda: ButlerGateway(self.core, unavailable).execute(command, principal='grok'))
        self.assertNotIn('secret-provider-response', str(error))
        self.assertEqual(self.core.snapshot(), before)

    def test_resolver_output_has_no_authority_to_override_source_or_schema(self):
        invalid = [
            {'action': 'create_todo', 'arguments': {'title': 'Injected'}, 'source': 'deepseek'},
            {'action': 'create_todo', 'arguments': {'title': 'Injected'}, 'expected_revision': 99},
            {'action': 'shell', 'arguments': {'command': 'anything'}},
            {'action': 'create_todo', 'arguments': {'title': 'Injected', 'unknown': True}},
            {'action': 'resolve_intent', 'arguments': {'original_user_message': 'loop'}},
        ]
        command = self.command('resolve_intent', {'original_user_message': 'Please help'})
        for resolution in invalid:
            with self.subTest(resolution=resolution):
                gateway = ButlerGateway(self.core, lambda _, value=resolution: value)
                self.assert_error('invalid_resolution', lambda: gateway.execute(command, principal='grok'))
        self.assertEqual(self.core.snapshot()['revision'], 0)

    def test_resolver_finish_rechecks_revision_after_other_entry_write(self):
        todo_id = self.create()

        def racing_resolver(_):
            other = ButlerGateway(TodoCore(self.path))
            update = self.command('update_todo', {'todo_id': todo_id, 'title': 'Newer edit'}, source='deepseek')
            other.execute(update, principal='deepseek')
            return {'action': 'complete_todo', 'arguments': {'todo_id': todo_id}}

        command = self.command('resolve_intent', {'original_user_message': 'Complete it'})
        gateway = ButlerGateway(self.core, racing_resolver)
        self.assert_error('conflict', lambda: gateway.execute(command, principal='grok'))
        item = self.core.snapshot()['todos'][0]
        self.assertEqual((item['title'], item['status'], item['updated_by']), ('Newer edit', 'pending', 'deepseek'))

    def test_semantic_retry_survives_restart_without_second_resolution(self):
        calls = []

        def resolver(envelope):
            calls.append(envelope)
            return {'action': 'create_todo', 'arguments': {'title': 'Resolved once'}}

        command = self.command('resolve_intent', {'original_user_message': 'remember the demo'})
        result = ButlerGateway(self.core, resolver).execute(command, principal='grok')
        restarted = ButlerGateway(TodoCore(self.path))
        self.assertEqual(restarted.execute(command, principal='grok'), result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(restarted.core.snapshot()['todos']), 1)

    def test_schema_rejects_missing_revision_unknown_fields_and_blank_title(self):
        base = {'source': 'grok', 'request_id': 'bad', 'action': 'create_todo', 'arguments': {'title': 'A'}}
        bad = [base, dict(base, expected_revision=True), dict(base, expected_revision='0'),
               dict(base, expected_revision=0, privileged=True),
               dict(base, expected_revision=0, arguments={'title': '   '})]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                Command.model_validate(payload)

    def test_authentication_and_source_spoofing_fail_before_mutation(self):
        tokens = {'g' * 32: 'grok', 'd' * 32: 'deepseek'}
        app = create_butler_app(self.core, tokens)
        payload = self.command('create_todo', {'title': 'Denied'}, source='deepseek').model_dump()
        with TestClient(app) as client:
            self.assertEqual(client.post('/v1/butler/commands', json=payload).status_code, 401)
            denied = client.post('/v1/butler/commands', json=payload, headers={'Authorization': 'Bearer ' + 'g' * 32})
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json()['error']['code'], 'source_forbidden')
            self.assertEqual(self.core.snapshot()['revision'], 0)
            accepted = client.post('/v1/butler/commands', json=payload, headers={'Authorization': 'Bearer ' + 'd' * 32})
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()['result']['todos'][0]['updated_by'], 'deepseek')
        with self.assertRaises(ValueError):
            create_butler_app(self.core, {'short-token': 'grok'})

    def test_gateway_does_not_open_production_database_paths(self):
        production = Path(__file__).resolve().parent / 'data' / 'todo-shadow.sqlite3'
        with patch('todo_core.sqlite3.connect') as connect:
            for path in [production, Path(self.temp.name) / 'hub.sqlite3']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    TodoCore(path)
            connect.assert_not_called()

    @staticmethod
    def export_fixture():
        # Synthetic contract fixture: never evidence of parity with real Grok data.
        return {'todos': [
            {'todo_id': 'export-A', 'title': '课程展示', 'status': 'pending', 'position': 0,
             'due_at': '2026-10-12T12:00:00+00:00', 'created_at': '2026-10-10T09:00:00+00:00',
             'updated_at': '2026-10-11T09:00:00+00:00'},
            {'todo_id': 'export-B', 'title': 'Prepare demo', 'status': 'done', 'position': 1},
        ], 'current_item_id': 'export-A'}

    def test_shadow_import_preserves_fixture_parity_and_restart_retry(self):
        fixture = self.export_fixture()
        before = deepcopy(fixture)
        snapshot = ShadowSnapshot.model_validate(fixture)
        result = self.core.import_shadow(snapshot, request_id='fixture-import')
        report = parity(snapshot, result)
        self.assertEqual(report, {'match': True, 'differences': [], 'authority': 'shadow', 'canonical_cutover': False})
        self.assertEqual(result['todos'][1]['created_at'], None)
        self.assertEqual(result['todos'][0]['updated_by'], 'grok_export')
        self.assertEqual(result['context']['current_item_id'], 'export-A')
        self.assertEqual(TodoCore(self.path).import_shadow(fixture, request_id='fixture-import'), result)
        self.assertEqual(fixture, before)
        changed = deepcopy(fixture)
        changed['todos'][0]['title'] = 'Changed export'
        self.assert_error('idempotency_conflict', lambda: self.core.import_shadow(changed, request_id='fixture-import'))
        self.assertEqual(self.core.snapshot(), result)

    def test_shadow_import_rejects_used_store_even_after_all_todos_deleted(self):
        todo_id = self.create()
        self.execute('delete_todo', {'todo_id': todo_id})
        before = self.core.snapshot()
        self.assertEqual(before['todos'], [])
        self.assert_error('shadow_store_not_empty',
                          lambda: self.core.import_shadow(self.export_fixture(), request_id='later-import'))
        self.assertEqual(self.core.snapshot(), before)

    def test_shadow_parity_reports_all_dimensions_without_repair(self):
        snapshot = ShadowSnapshot.model_validate(self.export_fixture())
        state = self.core.import_shadow(snapshot, request_id='parity-fixture')
        changed = deepcopy(state)
        changed['todos'].pop()
        changed['todos'][0].update(title='changed', status='done', position=1, due_at=None,
                                   created_at=None, updated_at=None)
        changed['current_item_id'] = None
        before = deepcopy(changed)
        report = parity(snapshot, changed)
        self.assertFalse(report['match'])
        self.assertEqual({d['field'] for d in report['differences']},
                         {'count', 'todo_id', 'title', 'status', 'position', 'due_at',
                          'created_at', 'updated_at', 'current_item_id'})
        self.assertFalse(report['canonical_cutover'])
        self.assertEqual(changed, before)
        self.assertEqual(self.core.snapshot(), state)

    def test_shadow_export_rejects_duplicate_ids_order_gaps_and_dangling_current(self):
        duplicate, gap, dangling = [self.export_fixture() for _ in range(3)]
        duplicate['todos'][1]['todo_id'] = 'export-A'
        gap['todos'][1]['position'] = 3
        dangling['current_item_id'] = 'missing'
        for invalid in [duplicate, gap, dangling]:
            with self.subTest(snapshot=invalid), self.assertRaises(ValidationError):
                self.core.import_shadow(invalid, request_id='invalid-import')
        self.assertEqual(self.core.snapshot()['revision'], 0)


if __name__ == '__main__':
    unittest.main()

