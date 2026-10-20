# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Synthetic provider -> Gateway -> real Router tests, fresh temporary data only."""
from pathlib import Path
import tempfile
import unittest
import httpx
from fastapi.testclient import TestClient
from butler_gateway import create_butler_app
from grok_capabilities import gateway_actions, INTERRUPT_ACTIONS
from grok_butler_adapter import GrokButlerAdapter
from interrupt_gateway import InterruptGatewayPort
from butler_todo_projection import ProjectionHub
from router_api import create_router_app
from todo_core import TodoCore

class InterruptTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.core = TodoCore(root / 'todo-shadow.sqlite3')
        self.hub_app = create_router_app(root / 'hub', start_monitor=False, environment='attention-m3-isolated')
        self.hub = TestClient(self.hub_app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 50123))
        self.addCleanup(self.hub.close)
        self.requests = []
        def forward(request):
            self.requests.append((request.method, request.url.path))
            response = self.hub.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))
        self.port = InterruptGatewayPort(lambda: ProjectionHub(transport=httpx.MockTransport(forward)))
        self.keys = {'G' * 32: 'grok', 'D' * 32: 'deepseek'}
        permissions = gateway_actions('butler:write') | INTERRUPT_ACTIONS
        self.app = create_butler_app(self.core, self.keys,
            action_permissions={'grok': permissions, 'deepseek': permissions}, interrupt_port=self.port)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def send(self, source='grok', request_id='one', title='Take a break', message='Stretch for a minute', token=None):
        body = dict(source=source, action='show_interrupt', request_id=request_id,
                    expected_revision=0, arguments=dict(title=title, message=message))
        key = token if token is not None else ('G' if source == 'grok' else 'D') * 32
        return self.client.post('/v1/butler/commands', json=body, headers={'Authorization': 'Bearer ' + key})

    def test_both_providers_route_interrupt_without_todo_changes(self):
        before = self.core.snapshot()
        for source in ('grok', 'deepseek'):
            response = self.send(source)
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()['result']
            self.assertEqual(value['route'], 'NOW' if source == 'grok' else 'QUEUE')
            self.assertEqual(value['device_delivery'], 'UNKNOWN')
            self.assertEqual(self.hub.get('/scene').json()['page'], 'interrupt')
        self.assertEqual(before, self.core.snapshot())
        writes = [path for method, path in self.requests if method == 'POST']
        self.assertEqual(writes, ['/api/events', '/api/events'])

    def test_retry_survives_port_restart_and_does_not_revive_acked_event(self):
        value = self.send().json()['result']
        self.app.state.gateway.interrupt_port = self.port.__class__(self.port.hub_factory)
        self.assertEqual(self.send().json()['result'], value)
        self.hub.get('/')
        response = self.hub.post('/api/events/' + value['event_id'] + '/ack',
            json={'revision': 1, 'command_id': 'manual-ack'},
            headers={'Origin': 'http://127.0.0.1:8000', 'X-Hub-Action': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.hub.get('/scene').json()['page'], 'interrupt')
        replay = self.send().json()['result']
        self.assertEqual(replay['event_status'], 'acknowledged')
        self.assertNotEqual(self.hub.get('/scene').json()['page'], 'interrupt')
        self.assertEqual(self.send(message='Different text').status_code, 409)

    def test_source_identity_and_credentials(self):
        self.assertEqual(self.send(token='wrong').status_code, 401)
        self.assertEqual(self.send(source='deepseek', token='G' * 32).status_code, 403)
        grok = self.send().json()['result']['event_id']
        ds = self.send('deepseek').json()['result']['event_id']
        self.assertNotEqual(grok, ds)
        self.assertLessEqual(len(self.send(request_id='x' * 80).json()['result']['event_id']), 64)

    def test_ascii_schema_and_closed_permissions(self):
        for invalid in ('中文', ' ', 'x' * 48, 'hello\nworld'):
            self.assertEqual(self.send(title=invalid).status_code, 422)
        self.app.state.gateway.action_permissions['grok'] = gateway_actions('butler:read')
        self.assertEqual(self.send().status_code, 403)
        self.app.state.gateway.action_permissions['grok'] = INTERRUPT_ACTIONS
        self.app.state.gateway.interrupt_port = None
        self.assertEqual(self.send().status_code, 503)

    def test_explicit_grant_console_attribution_and_legacy_scene(self):
        self.app.state.gateway.action_permissions.clear()
        self.assertEqual(self.send().status_code, 403)
        self.app.state.gateway.action_permissions['grok'] = INTERRUPT_ACTIONS
        result = self.send().json()['result']
        self.hub.get('/')
        view = self.hub.get('/api/overview').json()
        event = next(e for e in view['events'] if e['id'] == result['event_id'])
        self.assertEqual(event['provenance'], 'AGENT')
        self.assertEqual(event['detail'], 'Delegated AI: grok')
        # Existing interrupt Scene, no new page/capability requirement for old clients.
        scene = self.hub.get('/scene').json()
        self.assertEqual(scene['page'], 'interrupt')
        self.assertEqual(scene['interrupt']['id'], result['event_id'])
        self.assertEqual(view['desired_scene']['page'], 'interrupt')

    def test_public_preview_target_and_environment_guards(self):
        from interrupt_gateway import PreviewInterruptHub
        for target in ('http://127.0.0.1:8000', 'https://127.0.0.1:8765',
                       'http://localhost:8765', 'http://192.168.1.2:8765',
                       'http://user:pass@127.0.0.1:8765', 'http://127.0.0.1:8765/path'):
            with self.assertRaises(ValueError):
                PreviewInterruptHub(target, 'T' * 32)
        seen = []
        def other(request):
            seen.append(request)
            return httpx.Response(200, json={'environment': 'other'})
        target = PreviewInterruptHub('http://127.0.0.1:8765', 'T' * 32,
                                     transport=httpx.MockTransport(other))
        self.addCleanup(target.close)
        with self.assertRaises(ValueError):
            target._request('POST', '/api/events', {})
        self.assertEqual(len(seen), 1)
        self.assertNotIn('authorization', seen[0].headers)
        app = create_router_app(self.core.path.parent / 'preview', start_monitor=False,
                                environment='developer-preview', api_token='T' * 32)
        client = TestClient(app, base_url='http://127.0.0.1:8765')
        self.addCleanup(client.close)
        def forward(request):
            r = client.request(request.method, request.url.path, content=request.content,
                               headers=dict(request.headers))
            return httpx.Response(r.status_code, content=r.content, headers=dict(r.headers))
        self.app.state.gateway.interrupt_port = InterruptGatewayPort(
            lambda: PreviewInterruptHub('http://127.0.0.1:8765', 'T' * 32,
                                        transport=httpx.MockTransport(forward)))
        result = self.send().json()['result']
        self.assertEqual(result['route'], 'NOW')
        self.assertEqual(client.get('/scene').json()['page'], 'interrupt')

    def test_grok_adapter_uses_dedicated_action(self):
        def forward(request):
            response = self.client.post('/v1/butler/commands', content=request.content, headers=dict(request.headers))
            return httpx.Response(response.status_code, json=response.json())
        adapter = GrokButlerAdapter('http://127.0.0.1:3102', 'G' * 32, transport=httpx.MockTransport(forward))
        self.addCleanup(adapter.close)
        response = adapter.call_tool('show_interrupt', {'request_id': 'adapter', 'expected_revision': 0,
            'arguments': {'title': 'Ready', 'message': 'Please check the result'}})
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['result']['route'], 'NOW')

if __name__ == '__main__':
    unittest.main()
