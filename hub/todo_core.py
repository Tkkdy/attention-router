# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Shadow-only Todo service. One SQLite transaction owns state, context and retry audit.

No import from the live Hub, no implicit migration, no authority switch.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from butler_models import Command, READS

class ButlerError(Exception):
    def __init__(self, code, status=409, revision=None):
        super().__init__(code)
        self.code, self.status, self.revision = code, status, revision

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def with_stats(state):
    """Statistics belong to this exact revision, including cached retry responses.

    Total includes cancelled items; pending/done count only their named statuses.
    Derived fields are not a second persisted source of truth.
    """
    todos = state['todos']
    return {**state, 'stats': {'total': len(todos),
        'pending': sum(t['status'] == 'pending' for t in todos),
        'done': sum(t['status'] == 'done' for t in todos)}}

def initial_state():
    return {'authority': 'shadow', 'revision': 0, 'todos': [], 'current_item_id': None, 'suggestions': [],
            'context': {'active_topic': None, 'current_item_id': None,
                        'last_touched_todo_ids': [], 'last_action': None,
                        'last_user_intent_summary': None, 'pending_question': None,
                        'pending_question_target': None, 'updated_by': None,
                        'updated_at': None, 'context_revision': 0}}

class TodoCore:
    def __init__(self, path: Path, *, rehearsal_root=None):
        self.path = Path(path).resolve()
        production = Path(__file__).resolve().parent / 'data'
        rehearsal = False
        if rehearsal_root is not None:
            root = Path(rehearsal_root).resolve()
            allowed = Path(__file__).resolve().parents[1] / '.build/production-profile-rehearsals'
            rehearsal = (root.is_relative_to(allowed.resolve()) and root != allowed.resolve()
                         and self.path == root / 'canonical/todo.sqlite3'
                         and (root / 'rehearsal-only.json').is_file())
            if not rehearsal:
                raise ValueError('explicit production-profile rehearsal root required')
        if (not rehearsal and self.path.name != 'todo-shadow.sqlite3') or self.path.is_relative_to(production):
            raise ValueError('explicit isolated todo-shadow.sqlite3 path required')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version == 0 and not tables:
                db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                db.execute('CREATE TABLE operations (source TEXT, request_id TEXT, fingerprint TEXT NOT NULL, action TEXT NOT NULL, revision INTEGER NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(source, request_id))')
                db.execute('INSERT INTO state VALUES (1, ?)', (encoded(initial_state()),))
                db.execute('PRAGMA user_version=1')
            elif version != 1 or tables != {'state', 'operations'}:
                raise ValueError('not a supported Todo shadow database')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _state(db):
        return json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])

    def snapshot(self):
        with self.transaction() as db:
            return with_stats(self._state(db))

    @staticmethod
    def _fingerprint(command):
        return hashlib.sha256(encoded(command.model_dump()).encode()).hexdigest()

    def _retry(self, db, command):
        row = db.execute('SELECT fingerprint,response FROM operations WHERE source=? AND request_id=?',
                         (command.source, command.request_id)).fetchone()
        if row:
            if row[0] != self._fingerprint(command):
                raise ButlerError('idempotency_conflict')
            return with_stats(json.loads(row[1]))
        return None

    def retry(self, command):
        with self.transaction() as db:
            return self._retry(db, command)

    def execute(self, command: Command, *, audit_command=None, semantic=None):
        # Provider/auth decisions belong to the Gateway; every mutation still validates here.
        command = Command.model_validate(command.model_dump())
        audit_command = audit_command or command
        if command.action == 'resolve_intent':
            raise ButlerError('unresolved_intent', 422)
        with self.transaction() as db:
            previous = self._retry(db, audit_command)
            if previous is not None:
                return previous
            state = self._state(db)
            if command.action in READS:
                result = {**state, 'semantic': semantic} if semantic else state
                if audit_command.action == 'resolve_intent':
                    if audit_command.expected_revision != state['revision']:
                        raise ButlerError('conflict', revision=state['revision'])
                    self._record(db, audit_command, command.action, result)
                return with_stats(result)
            if command.expected_revision != state['revision']:
                raise ButlerError('conflict', revision=state['revision'])
            revision = state['revision'] + 1
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            args, action = command.arguments, command.action
            todos, context = state['todos'], state['context']
            def target(todo_id):
                item = next((t for t in todos if t['todo_id'] == todo_id), None)
                if item is None:
                    raise ButlerError('todo_not_found', 404)
                return item
            touched = []
            if action == 'create_todo':
                item = dict(todo_id=uuid4().hex, title=args['title'], status='pending', position=len(todos),
                            due_at=args.get('due_at'), remind_at=args.get('remind_at'), created_at=now, updated_at=now,
                            revision=revision, updated_by=command.source)
                todos.append(item)
                touched = [item['todo_id']]
            elif action in {'update_todo', 'complete_todo', 'delete_todo'}:
                item = target(args['todo_id'])
                touched = [item['todo_id']]
                if action == 'delete_todo':
                    todos.remove(item)
                    if state['current_item_id'] == item['todo_id']:
                        state['current_item_id'] = None
                else:
                    item.update({'status': 'done'} if action == 'complete_todo' else
                                {k: v for k, v in args.items() if k != 'todo_id'})
                    item.update(updated_at=now, revision=revision, updated_by=command.source)
                if context['pending_question_target'] == item['todo_id']:
                    context.update(pending_question=None, pending_question_target=None)
            elif action == 'reorder_todos':
                ids = args['todo_ids']
                if len(ids) != len(todos) or set(ids) != {t['todo_id'] for t in todos}:
                    raise ButlerError('invalid_reorder', 422)
                todos[:] = [target(todo_id) for todo_id in ids]
                touched = ids
            elif action == 'set_current_item':
                if args['todo_id'] is not None:
                    target(args['todo_id'])
                    touched = [args['todo_id']]
                state['current_item_id'] = args['todo_id']
            elif action == 'set_pending_question':
                if args['target_todo_id'] is not None:
                    target(args['target_todo_id'])
                    touched = [args['target_todo_id']]
                context.update(pending_question=args['question'], pending_question_target=args['target_todo_id'])
            elif action == 'request_clarification':
                if args.get('target_todo_id') is not None:
                    target(args['target_todo_id'])
                context.update(pending_question=args['question'],
                               pending_question_target=args.get('target_todo_id'),
                               pending_intent_summary=args.get('intent_summary', ''))
            elif action == 'publish_suggestion':
                # Suggestions are a separate read model, never interpreted as Todo commands.
                suggestions = state.setdefault('suggestions', [])
                suggestions.append({'id': uuid4().hex, 'text': args['text'],
                                    'expires_at': args.get('expires_at'), 'created_at': now,
                                    'source': command.source, 'device_text': args.get('device_text')})
                state['suggestions'] = suggestions[-20:]
            elif action == 'publish_attention_event':
                authorization, starts_at = 'none', None
                if args.get('todo_id'):
                    todo = target(args['todo_id'])
                if args.get('kind', 'service') == 'reminder':
                    todo = target(args.get('todo_id'))
                    if todo['status'] != 'pending' or not todo.get('remind_at'):
                        raise ButlerError('explicit_timed_reminder_required', 422)
                    authorization, starts_at = 'user_reminder', todo['remind_at']
                event_id = 'butler-' + hashlib.sha256((command.source + ':' + command.request_id).encode()).hexdigest()[:40]
                state.setdefault('attention_events', []).append({
                    'id': event_id, 'revision': 1, 'title': args['title'], 'message': args['message'],
                    'kind': args.get('kind', 'service'), 'authorization': authorization,
                    'starts_at': starts_at, 'provenance': 'SIMULATED',
                    'todo_id': args.get('todo_id'), 'cancelled': False})
            elif action == 'ack_interrupt':
                event = next((e for e in state.get('attention_events', []) if e['id'] == args['event_id']), None)
                if event is None:
                    raise ButlerError('event_not_found', 404)
                if event.get('cancelled'):
                    raise ButlerError('event_cancelled')
                if event['revision'] != args['event_revision']:
                    raise ButlerError('event_revision_conflict')
                state.setdefault('interrupt_acks', []).append({
                    'event_id': event['id'], 'revision': event['revision'],
                    'command_id': 'butler-ack-' + hashlib.sha256((command.source + ':' + command.request_id).encode()).hexdigest()})
            else:
                raise ButlerError('unsupported_action', 422)
            if audit_command.action == 'resolve_intent' and action not in {'request_clarification', 'publish_suggestion'}:
                context.update(pending_question=None, pending_question_target=None, pending_intent_summary='')
            # A reminder never outlives its source Todo's explicit reminder authorization.
            for event in state.get('attention_events', []):
                if event['kind'] != 'reminder':
                    continue
                item = next((t for t in todos if t['todo_id'] == event.get('todo_id')), None)
                if item is None or item['status'] != 'pending' or not item.get('remind_at'):
                    event['cancelled'] = True
                elif item['remind_at'] != event['starts_at'] or event.get('cancelled'):
                    event.update(starts_at=item['remind_at'], revision=event['revision'] + 1, cancelled=False)
            for position, item in enumerate(todos):
                if item['position'] != position:
                    item.update(position=position, revision=revision, updated_at=now, updated_by=command.source)
            context.update(active_topic='todos', current_item_id=state['current_item_id'],
                           last_touched_todo_ids=touched, last_action=action,
                           # Only a bounded business summary; never persist raw conversation/hints.
                           last_user_intent_summary=action, updated_by=command.source,
                           updated_at=now, context_revision=context['context_revision'] + 1)
            state['revision'] = revision
            db.execute('UPDATE state SET payload=? WHERE id=1', (encoded(state),))
            result = {**state, 'semantic': semantic} if semantic else state
            self._record(db, audit_command, action, result)
            return with_stats(result)

    def _record(self, db, command, action, result):
        db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?)',
                   (command.source, command.request_id, self._fingerprint(command), action,
                    result['revision'], encoded(result), datetime.now(timezone.utc).isoformat()))

    def record_noop(self, command, semantic):
        with self.transaction() as db:
            previous = self._retry(db, command)
            if previous is not None:
                return previous
            state = self._state(db)
            if command.expected_revision != state['revision']:
                raise ButlerError('conflict', revision=state['revision'])
            result = {**state, 'semantic': semantic}
            self._record(db, command, 'semantic_noop', result)
            return with_stats(result)

    def import_shadow(self, snapshot, *, request_id):
        """Explicit local export import into an unused shadow store; not a public tool."""
        from pydantic import TypeAdapter
        from butler_models import Identifier
        from todo_shadow import ShadowSnapshot
        request_id = TypeAdapter(Identifier).validate_python(request_id)
        snapshot = ShadowSnapshot.model_validate(snapshot)
        fingerprint = hashlib.sha256(encoded(snapshot.model_dump()).encode()).hexdigest()
        with self.transaction() as db:
            previous = db.execute('SELECT fingerprint,response FROM operations WHERE source=? AND request_id=?',
                                  ('shadow_import', request_id)).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise ButlerError('idempotency_conflict')
                return with_stats(json.loads(previous[1]))
            state = self._state(db)
            if state['revision'] != 0 or state['todos']:
                raise ButlerError('shadow_store_not_empty')
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            state.update(revision=1, todos=[{**item.model_dump(), 'revision': 1, 'updated_by': 'grok_export'}
                                          for item in snapshot.todos], current_item_id=snapshot.current_item_id)
            state['context'].update(active_topic='todos', current_item_id=snapshot.current_item_id,
                                    last_action='shadow_import', updated_by='grok_export', updated_at=now,
                                    context_revision=1)
            db.execute('UPDATE state SET payload=? WHERE id=1', (encoded(state),))
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?)',
                       ('shadow_import', request_id, fingerprint, 'shadow_import', 1, encoded(state), now))
            return with_stats(state)
