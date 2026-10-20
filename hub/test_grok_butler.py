# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Isolated Grok adapter contract tests; these are not real Grok client evidence."""
import json
from pathlib import Path
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest

import uvicorn
sys.path.insert(0, str(Path(__file__).resolve().parent))
from butler_gateway import create_butler_app
from todo_core import TodoCore

import httpx

try:
    from .grok_butler_adapter import GrokButlerAdapter, tool_definitions
except ImportError:
    from grok_butler_adapter import GrokButlerAdapter, tool_definitions


class GrokAdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.reply = {'ok': True, 'status': 'ok', 'result': {'authority': 'shadow', 'revision': 0}, 'error': None}
        self.status = 200
        def send(request):
            self.calls.append(request)
            return httpx.Response(self.status, json=self.reply)
        self.adapter = GrokButlerAdapter('http://127.0.0.1:8311', 'ephemeral-test-only', transport=httpx.MockTransport(send))
        self.addCleanup(self.adapter.close)

    def test_structured_call_binds_source_and_revision(self):
        command = {'request_id': 'grok-1', 'expected_revision': 4, 'arguments': {'todo_id': 'todo-a'}}
        self.assertTrue(self.adapter.call_tool('complete_todo', command)['ok'])
        request = self.calls[0]
        self.assertEqual(str(request.url), 'http://127.0.0.1:8311/v1/butler/commands')
        self.assertEqual(request.headers['Authorization'], 'Bearer ephemeral-test-only')
        self.assertEqual(json.loads(request.content), dict(command, source='grok', action='complete_todo'))

    def test_raw_intent_is_not_rewritten(self):
        original = '把昨天那个软件工程的事情提前一点'
        arguments = {'original_user_message': original, 'source_hint': 'possibly reorder', 'conversation_ref': 'opaque-1'}
        self.adapter.call_tool('resolve_intent', {'request_id': 'intent-1', 'expected_revision': 7, 'arguments': arguments})
        self.assertEqual(json.loads(self.calls[0].content)['arguments'], arguments)

    def test_unknown_capabilities_and_source_spoofing_never_forwarded(self):
        for name in ['sql', 'shell', 'filesystem', 'set_scene', 'control_device']:
            self.assertEqual(self.adapter.call_tool(name, {})['status'], 'unknown_tool')
        self.assertEqual(self.adapter.call_tool('list_todos', {'request_id': 'r', 'source': 'deepseek', 'arguments': {}})['status'], 'validation_error')
        self.assertFalse(self.calls)

    def test_schema_envelope_rejects_blind_write(self):
        for values in [None, True, -1, '4']:
            result = self.adapter.call_tool('complete_todo', {'request_id': 'r', 'expected_revision': values, 'arguments': {'todo_id': 'a'}})
            self.assertEqual(result['status'], 'validation_error')
        self.assertEqual(self.adapter.call_tool('complete_todo', {'request_id': 'r', 'arguments': {'todo_id': 'a'}})['status'], 'validation_error')
        self.assertFalse(self.calls)

    def test_conflict_is_returned_without_automatic_retry_or_overwrite(self):
        self.status = 409
        self.reply = {'ok': False, 'status': 'conflict', 'result': {'revision': 5}, 'error': {'code': 'conflict'}}
        result = self.adapter.call_tool('complete_todo', {'request_id': 'r', 'expected_revision': 4, 'arguments': {'todo_id': 'a'}})
        self.assertEqual(result, self.reply)
        self.assertEqual(len(self.calls), 1)

    def test_redirect_cannot_forward_credentials(self):
        calls = []
        def redirect(request):
            calls.append(request)
            return httpx.Response(307, headers={'Location': 'https://outside.example/steal'})
        adapter = GrokButlerAdapter('http://localhost:8311', 'ephemeral-test-only', transport=httpx.MockTransport(redirect))
        self.addCleanup(adapter.close)
        self.assertEqual(adapter.call_tool('list_todos', {'request_id': 'r', 'arguments': {}})['status'], 'gateway_redirect_rejected')
        self.assertEqual(len(calls), 1)

    def test_gateway_error_never_returns_exception_secret(self):
        def fail(request):
            raise httpx.ConnectError('ephemeral-test-only/private-content', request=request)
        adapter = GrokButlerAdapter('http://localhost:8311', 'ephemeral-test-only', transport=httpx.MockTransport(fail))
        self.addCleanup(adapter.close)
        result = adapter.call_tool('list_todos', {'request_id': 'r', 'arguments': {}})
        self.assertEqual(result['status'], 'gateway_unavailable')
        self.assertNotIn('ephemeral-test-only', str(result))

    def test_gateway_response_is_validated(self):
        self.reply = {'private_debug': 'unsafe'}
        self.assertEqual(self.adapter.call_tool('list_todos', {'request_id': 'r', 'arguments': {}})['status'], 'gateway_invalid_response')

    def test_endpoint_is_loopback_shadow_only(self):
        for origin in ['https://outside.example', 'http://127.0.0.1:8000', 'http://127.0.0.1:3001',
                       'http://127.0.0.1:3101', 'http://user:pass@localhost:8311',
                       'http://localhost:8311/path', 'http://localhost:8311?token=secret']:
            with self.assertRaises(ValueError):
                GrokButlerAdapter(origin, 'ephemeral-test-only')

    def test_registry_contains_narrow_schema_only(self):
        definitions = tool_definitions()
        names = {tool['name'] for tool in definitions}
        self.assertEqual(len(names), 19)
        self.assertTrue({"show_tibo_page", "get_tibo_attention", "ack_tibo_attention"} <= names)
        self.assertIn('publish_suggestion', names)
        self.assertNotIn('request_clarification', names)
        self.assertIn('resolve_intent', names)
        self.assertIn('set_pending_question', names)
        self.assertFalse({'shell', 'sql', 'set_scene'} & names)
        for definition in definitions:
            self.assertFalse(definition['inputSchema']['additionalProperties'])
            if not definition['annotations']['readOnlyHint']:
                self.assertIn('expected_revision', definition['inputSchema']['required'])
        definitions[0]['inputSchema']['properties']['request_id']['type'] = 'number'
        self.assertEqual(tool_definitions()[0]['inputSchema']['properties']['request_id']['type'], 'string')


class GrokGatewayHTTPTests(unittest.TestCase):
    def test_two_provider_shadow_http_conflict_and_no_resolver(self):
        """Real HTTP + SQLite, simulated provider clients and ephemeral auth only."""
        with tempfile.TemporaryDirectory(prefix='grok-butler-') as directory:
            core = TodoCore(Path(directory) / 'todo-shadow.sqlite3')
            grok_token, deepseek_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            app = create_butler_app(core, {grok_token: 'grok', deepseek_token: 'deepseek'})
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started, 'isolated server did not start')
                origin = f'http://127.0.0.1:{port}'
                grok = GrokButlerAdapter(origin, grok_token)
                try:
                    created = grok.call_tool('create_todo', {'request_id': 'grok-create', 'expected_revision': 0,
                                                           'arguments': {'title': 'Shared shadow task'}})
                    self.assertTrue(created['ok'], created)
                    todo_id = created['result']['todos'][0]['todo_id']
                    self.assertEqual(created['result']['authority'], 'shadow')
                    # The resolver is absent, so explicit commands must still work.
                    unavailable = grok.call_tool('resolve_intent', {'request_id': 'grok-intent', 'expected_revision': 1,
                        'arguments': {'original_user_message': 'Finish that task'}})
                    self.assertEqual(unavailable['status'], 'semantic_resolver_unavailable')
                    with httpx.Client(base_url=origin, trust_env=False) as deepseek:
                        def command(source, token, action, request_id, arguments, revision=None):
                            payload = {'source': source, 'request_id': request_id, 'action': action, 'arguments': arguments}
                            if revision is not None:
                                payload['expected_revision'] = revision
                            return deepseek.post('/v1/butler/commands', json=payload,
                                                 headers={'Authorization': 'Bearer ' + token})
                        listed = command('deepseek', deepseek_token, 'list_todos', 'ds-read', {}).json()
                        self.assertEqual(listed['result']['todos'][0]['todo_id'], todo_id)
                        complete = command('deepseek', deepseek_token, 'complete_todo', 'ds-complete', {'todo_id': todo_id}, 1)
                        self.assertEqual(complete.status_code, 200)
                        self.assertEqual(command('deepseek', grok_token, 'list_todos', 'spoof', {}).status_code, 403)
                    stale = grok.call_tool('update_todo', {'request_id': 'grok-stale', 'expected_revision': 1,
                                                         'arguments': {'todo_id': todo_id, 'title': 'Lost update'}})
                    self.assertEqual(stale['status'], 'conflict')
                    current = grok.call_tool('list_todos', {'request_id': 'grok-read', 'arguments': {}})
                    self.assertEqual(current['result']['todos'][0]['status'], 'done')
                    self.assertEqual(current['result']['todos'][0]['title'], 'Shared shadow task')
                    self.assertEqual(current['result']['todos'][0]['updated_by'], 'deepseek')
                    self.assertEqual(current['result']['revision'], 2)
                    self.assertEqual(TodoCore(Path(directory) / 'todo-shadow.sqlite3').snapshot(), current['result'])
                finally:
                    grok.close()
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                listener.close()
                self.assertFalse(thread.is_alive(), 'isolated server failed to stop')

if __name__ == '__main__':
    unittest.main()

