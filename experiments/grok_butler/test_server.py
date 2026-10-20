# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Local simulated-client acceptance; never real GrokBot evidence."""
import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import uvicorn
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hub'))
from butler_gateway import create_butler_app
from butler_models import Command
from todo_core import TodoCore, ButlerError
from hub.grok_butler_adapter import GrokButlerAdapter
from hub.grok_capabilities import actions_for, gateway_actions
from experiments.grok_butler.server import create_app

ORIGIN = 'http://127.0.0.1:3103'
CALLBACK = 'https://fixture.example/callback'


class D3Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='grok-d3-')
        self.addCleanup(directory.cleanup)
        self.core = TodoCore(Path(directory.name) / 'todo-shadow.sqlite3')
        self.grok_key, self.ds_key, self.owner = [secrets.token_urlsafe(32) for _ in range(3)]
        self.resolutions = []
        self.resolved = {'action': 'request_clarification', 'arguments': {'question': 'Which item?', 'intent_summary': 'ambiguous'}}
        def resolver(value):
            self.resolutions.append(value)
            return self.resolved
        self.gateway_app = create_butler_app(self.core, {self.grok_key: 'grok', self.ds_key: 'deepseek'}, resolver,
            action_permissions={'grok': gateway_actions('butler:write')})
        self.gateway = self.gateway_app.state.gateway
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.gateway_app, access_log=False, log_level='critical'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        def stop():
            server.should_exit = True
            thread.join(10)
            listener.close()
        self.addCleanup(stop)
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(server.started)
        self.adapter = GrokButlerAdapter(f'http://127.0.0.1:{port}', self.grok_key)
        self.addCleanup(self.adapter.close)
        self.now = [time.time()]

    def facade(self, scope='butler:write', *, tibo_enabled=False, interrupt_enabled=False):
        app = create_app(ORIGIN, self.adapter, owner_code=self.owner, scope=scope, clock=lambda: self.now[0], tibo_enabled=tibo_enabled, interrupt_enabled=interrupt_enabled)
        client = TestClient(app, base_url=ORIGIN)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return app, client

    def authorize(self, client, scope):
        registered = client.post('/register', json={'redirect_uris': [CALLBACK], 'scope': scope})
        self.assertEqual(registered.status_code, 201)
        client_id = registered.json()['client_id']
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        page = client.get('/authorize', params={'client_id': client_id, 'redirect_uri': CALLBACK,
            'scope': scope, 'response_type': 'code', 'code_challenge_method': 'S256', 'code_challenge': challenge})
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(self.owner, page.text)
        ticket = re.search('name="ticket" value="([^"]+)"', page.text)[1]
        bad = client.post('/consent', data={'ticket': ticket, 'decision': 'allow'}, headers={'Origin': ORIGIN})
        self.assertEqual(bad.status_code, 403)
        response = client.post('/consent', data={'ticket': ticket, 'decision': 'allow', 'owner_code': self.owner},
                               headers={'Origin': ORIGIN}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        code = parse_qs(urlsplit(response.headers['location']).query)['code'][0]
        token = client.post('/token', data={'client_id': client_id, 'redirect_uri': CALLBACK,
            'code': code, 'code_verifier': verifier, 'grant_type': 'authorization_code'})
        self.assertEqual(token.status_code, 200)
        self.assertEqual(token.json()['scope'], scope)
        return token.json()['access_token']

    def rpc(self, client, token, method, params=None):
        headers = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}, headers=headers)

    def call(self, client, token, name, request_id, arguments, revision=None):
        inputs = {'request_id': request_id, 'arguments': arguments}
        if revision is not None:
            inputs['expected_revision'] = revision
        return self.rpc(client, token, 'tools/call', {'name': name, 'arguments': inputs}).json()['result']

    def test_tibo_opt_in_discovery_and_read_scope_boundary(self):
        from hub.grok_capabilities import TIBO_ACTIONS
        _, client = self.facade(tibo_enabled=True)
        token = self.authorize(client, 'butler:write')
        names = {t['name'] for t in self.rpc(client, token, 'tools/list').json()['result']['tools']}
        self.assertEqual(names, actions_for('butler:write') | TIBO_ACTIONS)
        _, readonly = self.facade('butler:read', tibo_enabled=True)
        read_token = self.authorize(readonly, 'butler:read')
        names = {t['name'] for t in self.rpc(readonly, read_token, 'tools/list').json()['result']['tools']}
        self.assertEqual(names, actions_for('butler:read'))

    def test_read_gate_owner_pairing_and_scope_separation(self):
        app, client = self.facade('butler:read')
        self.assertEqual(self.rpc(client, None, 'tools/list').status_code, 401)
        self.assertEqual(client.post('/register', json={'redirect_uris': [CALLBACK], 'scope': 'ping'}).status_code, 400)
        token = self.authorize(client, 'butler:read')
        names = {t['name'] for t in self.rpc(client, token, 'tools/list').json()['result']['tools']}
        self.assertEqual(names, actions_for('butler:read'))
        self.assertEqual(self.call(client, token, 'get_context', 'read', {})['structuredContent']['result']['revision'], 0)
        self.assertTrue(self.call(client, token, 'create_todo', 'no-write', {'title': 'denied'}, 0)['isError'])
        self.assertEqual(self.core.snapshot()['revision'], 0)
        other = create_app(ORIGIN, self.adapter, owner_code=self.owner, scope='butler:read')
        with TestClient(other, base_url=ORIGIN) as unrelated:
            self.assertEqual(self.rpc(unrelated, token, 'tools/list').status_code, 401)
        self.assertNotIn(self.owner, json.dumps(app.state.observations.events))
        self.assertNotIn(token, json.dumps(app.state.observations.events))
        self.now[0] += 601
        self.assertEqual(self.rpc(client, token, 'tools/list').status_code, 401)

    def test_shared_core_write_retry_cross_provider_and_conflict(self):
        app, client = self.facade()
        token = self.authorize(client, 'butler:write')
        names = {t['name'] for t in self.rpc(client, token, 'tools/list').json()['result']['tools']}
        self.assertEqual(names, actions_for('butler:write'))
        self.assertFalse(names & {'delete_todo', 'ack_interrupt', 'publish_attention_event', 'get_dashboard_state'})
        created = self.call(client, token, 'create_todo', 'grok-create', {'title': 'D3 shared test'}, 0)
        self.assertFalse(created['isError'], created)
        todo = created['structuredContent']['result']['todos'][0]['todo_id']
        retry = self.call(client, token, 'create_todo', 'grok-create', {'title': 'D3 shared test'}, 0)
        self.assertEqual(retry['structuredContent'], created['structuredContent'])
        self.assertEqual(self.core.snapshot()['revision'], 1)
        self.assertFalse(self.resolutions, 'structured calls must never invoke Resolver')
        deepseek = Command(source='deepseek', request_id='ds-done', action='complete_todo',
                           expected_revision=1, arguments={'todo_id': todo})
        self.gateway.execute(deepseek, principal='deepseek')
        conflict = self.call(client, token, 'update_todo', 'stale', {'todo_id': todo, 'title': 'wrong'}, 1)
        self.assertEqual(conflict['structuredContent']['status'], 'conflict')
        state = self.call(client, token, 'list_todos', 'read-done', {})['structuredContent']['result']
        self.assertEqual(state['todos'][0]['status'], 'done')
        self.assertEqual(state['todos'][0]['updated_by'], 'deepseek')
        self.assertEqual(TodoCore(self.core.path).snapshot(), state)

    def test_raw_original_preserved_and_resolver_cannot_escape_allowlist(self):
        _, client = self.facade()
        token = self.authorize(client, 'butler:write')
        original = '把昨天那个弄一下，别猜是哪个。'
        self.resolved = {'action': 'publish_attention_event', 'arguments': {}}
        self.call(client, token, 'resolve_intent', 'raw-invalid', {'original_user_message': original}, 0)
        self.assertEqual(self.resolutions[-1]['original_user_message'], original)
        self.assertEqual(self.core.snapshot()['revision'], 0)
        # Valid destructive resolution must also be denied before Core mutation.
        self.resolved = {'action': 'delete_todo', 'arguments': {'todo_id': 'anything'}}
        reply = self.call(client, token, 'resolve_intent', 'raw-forbidden', {'original_user_message': original}, 0)
        self.assertEqual(reply['structuredContent']['status'], 'action_forbidden')
        self.assertEqual(self.core.snapshot()['revision'], 0)
        self.resolved = {'action': 'request_clarification',
                         'arguments': {'question': 'Which item?', 'intent_summary': 'ambiguous'}}
        reply = self.call(client, token, 'resolve_intent', 'raw-clarify', {'original_user_message': original}, 0)
        self.assertFalse(reply['isError'], reply)
        state = self.core.snapshot()
        self.assertEqual(state['context']['pending_question'], 'Which item?')
        self.assertEqual(state['todos'], [])
        self.assertEqual(self.resolutions[-1]['original_user_message'], original)

    def test_mcp_interrupt_reaches_hub_and_ack_replay_does_not_revive(self):
        import httpx
        from router_api import create_router_app
        from interrupt_gateway import InterruptGatewayPort, PreviewInterruptHub
        from hub.grok_capabilities import INTERRUPT_ACTIONS
        from experiments.grok_butler.server import verify_tool_discovery
        key = 'synthetic-hub-' + 'H' * 32
        app = create_router_app(self.core.path.parent/'hub', start_monitor=False,
                                environment='developer-preview', api_token=key)
        hub = TestClient(app, base_url='http://127.0.0.1:8765')
        self.addCleanup(hub.close)
        def forward(request):
            response = hub.request(request.method, request.url.path,
                                   content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        self.gateway.interrupt_port = InterruptGatewayPort(
            lambda: PreviewInterruptHub('http://127.0.0.1:8765', key,
                                        transport=httpx.MockTransport(forward)))
        self.gateway.action_permissions['grok'] = gateway_actions('butler:write') | INTERRUPT_ACTIONS
        facade, client = self.facade(interrupt_enabled=True)
        token = self.authorize(client, 'butler:write')
        names = {item['name'] for item in self.rpc(client, token, 'tools/list').json()['result']['tools']}
        self.assertIn('show_interrupt', names)
        self.assertEqual(set(verify_tool_discovery(facade, interrupt_enabled=True)), names)
        before = self.core.snapshot()
        text = {'title': 'Synthetic result', 'message': 'Please review the result'}
        reply = self.call(client, token, 'show_interrupt', 'interrupt-same-id', text, 0)
        self.assertFalse(reply['isError'], reply)
        result = reply['structuredContent']['result']
        self.assertEqual(result['route'], 'NOW')
        self.assertEqual(result['device_delivery'], 'UNKNOWN')
        self.assertEqual(hub.get('/scene').json()['page'], 'interrupt')
        headers = {'Authorization': 'Bearer ' + key}
        overview = hub.get('/api/overview', headers=headers).json()
        event = next(item for item in overview['events'] if item['id'] == result['event_id'])
        self.assertEqual(event['provenance'], 'AGENT')
        self.assertEqual(overview['desired_scene']['page'], 'interrupt')
        ack = hub.post('/api/events/' + result['event_id'] + '/ack',
            json={'revision': 1, 'command_id': 'synthetic-manual-ack'}, headers=headers)
        self.assertEqual(ack.status_code, 200)
        replay = self.call(client, token, 'show_interrupt', 'interrupt-same-id', text, 0)
        self.assertEqual(replay['structuredContent']['result']['event_status'], 'acknowledged')
        self.assertNotEqual(hub.get('/scene').json()['page'], 'interrupt')
        conflict = self.call(client, token, 'show_interrupt', 'interrupt-same-id',
                             {**text, 'message': 'Changed payload'}, 0)
        self.assertEqual(conflict['structuredContent']['status'], 'conflict')
        self.assertEqual(before, self.core.snapshot())

    def test_invalid_envelope_and_direct_gateway_policy(self):
        _, client = self.facade()
        token = self.authorize(client, 'butler:write')
        for revision in [None, True, '0', -1]:
            result = self.call(client, token, 'create_todo', 'invalid', {'title': 'no'}, revision)
            self.assertTrue(result['isError'])
        self.assertEqual(self.core.snapshot()['revision'], 0)
        with self.assertRaises(ButlerError) as error:
            self.gateway.execute(Command(source='grok', request_id='delete', action='delete_todo',
                expected_revision=0, arguments={'todo_id': 'anything'}), principal='grok')
        self.assertEqual(error.exception.code, 'action_forbidden')


class InterruptCapabilityTests(unittest.TestCase):
    def test_explicit_write_opt_in_only(self):
        from unittest.mock import patch
        import experiments.grok_butler.server as facade
        for scope, enabled, visible in [('butler:write', True, True), ('butler:write', False, False), ('butler:read', True, False)]:
            captured = {}
            original = facade.MCPServer
            def capture(**kwargs):
                captured.update(kwargs)
                return original(**kwargs)
            with patch.object(facade, 'MCPServer', capture):
                app = facade.create_app(ORIGIN, object(), owner_code='synthetic-owner-code-12345678901234567890', scope=scope, interrupt_enabled=enabled)
            self.assertEqual('show_interrupt' in {tool.name for tool in captured['tools']}, visible)
            import asyncio
            actual = asyncio.run(app.state.mcp_server.list_tools())
            self.assertEqual('show_interrupt' in {tool.name for tool in actual}, visible)
            from experiments.grok_butler.server import verify_tool_discovery
            self.assertEqual(set(verify_tool_discovery(app, interrupt_enabled=visible)),
                             {tool.name for tool in actual})
            with self.assertRaises(ValueError):
                verify_tool_discovery(app, interrupt_enabled=not visible)



if __name__ == '__main__':
    unittest.main()
