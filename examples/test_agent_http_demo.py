# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Run real loopback HTTP tests in a disposable copy, never the private Hub."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]


class AgentHTTPTests(unittest.TestCase):
    def setUp(self):
        import secrets
        import uvicorn
        from router_api import create_router_app
        from agent_http_demo import HubClient
        self.temp = tempfile.TemporaryDirectory(prefix='agent-http-data-')
        self.addCleanup(self.temp.cleanup)
        self.token = secrets.token_urlsafe(32)  # Synthetic per-test credential, never printed.
        self.app = create_router_app(Path(self.temp.name), start_monitor=False,
                                     api_token=self.token, environment='developer-preview')
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(128)
        self.addCleanup(self.sock.close)
        self.origin = 'http://127.0.0.1:' + str(self.sock.getsockname()[1])
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='critical', access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [self.sock]}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        deadline = time.monotonic() + 5
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.server.started)
        self.client = HubClient(self.origin, self.token)

    def stop_server(self):
        self.server.should_exit = True
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def test_credentials_and_legacy_release_versions(self):
        from agent_http_demo import HubClient, DemoError
        self.client.check_preview()
        self.assertEqual(self.client.overview()['release_version'], '0.1.0')
        health = self.client.call('/health', authenticated=False)
        self.assertEqual(health['release_version'], '0.1.0')
        self.assertEqual(health['version'], '1.0-m3')
        self.assertEqual(self.app.version, '1.0-m2')
        self.assertEqual(self.client.overview()['desired_scene']['protocol_version'], 3)
        with self.assertRaisesRegex(DemoError, '401'):
            HubClient(self.origin, 'synthetic-wrong-token-' + 'x'*32).overview()

    def test_todo_current_reminder_ack_and_replays(self):
        from agent_http_demo import create_demo, acknowledge_demo
        demo = create_demo(self.client)
        before = self.client.overview()
        self.assertEqual(len(before['todos']['tasks']), 1)
        self.assertEqual(before['todos']['revision'], 1)
        self.assertEqual(before['workspace']['current_item']['id'], demo['todo_id'])
        event = next(e for e in before['events'] if e['id'] == demo['event_id'])
        self.assertEqual(event['provenance'], 'SIMULATED')
        self.assertEqual(event['authorization'], 'user_reminder')
        self.assertEqual(event['route'], 'NOW')
        self.assertEqual(before['desired_scene']['page'], 'interrupt')
        self.assertEqual(acknowledge_demo(self.client, demo)['status'], 'acknowledged')
        after = self.client.overview()
        self.assertEqual(after['todos'], before['todos'])
        self.assertNotEqual(after['desired_scene']['page'], 'interrupt')
        self.assertEqual(acknowledge_demo(self.client, demo)['status'], 'acknowledged')

    def test_cli_keeps_credentials_hidden(self):
        from agent_http_demo import main
        import io
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['agent_http_demo.py', '--url', self.origin]), \
                patch('getpass.getpass', return_value=self.token), \
                patch('builtins.input', return_value=''), \
                patch('sys.stdout', output), patch('sys.stderr', errors):
            self.assertEqual(main(), 0)
        self.assertNotIn(self.token, output.getvalue() + errors.getvalue())
        self.assertIn('Todo remains pending', output.getvalue())

    def test_revision_conflict_stops_without_overwrite(self):
        from agent_http_demo import RevisionConflict
        initial = {'request_id': 'first', 'expected_revision': 0, 'title': 'First task'}
        self.client.call('/api/mcp/todos/upsert', initial)
        with self.assertRaisesRegex(RevisionConflict, 'todos=1'):
            self.client.call('/api/mcp/todos/upsert', {**initial, 'request_id': 'stale', 'title': 'Stale task'})
        self.assertEqual(len(self.client.overview()['todos']['tasks']), 1)
        self.client.call('/api/workspace/sync', {'command_id': 'workspace-first', 'revision': 1, 'project': 'First'})
        with self.assertRaisesRegex(RevisionConflict, 'workspace=1'):
            self.client.call('/api/workspace/sync', {'command_id': 'workspace-stale', 'revision': 1, 'project': 'Stale'})
        self.assertEqual(self.client.overview()['workspace']['project'], 'First')

    def test_same_id_changed_payload_is_not_retried(self):
        from agent_http_demo import RevisionConflict
        command = {'request_id': 'immutable', 'expected_revision': 0, 'title': 'First'}
        self.client.call('/api/mcp/todos/upsert', command)
        with self.assertRaises(RevisionConflict):
            self.client.call('/api/mcp/todos/upsert', {**command, 'title': 'Changed'})
        self.assertEqual(self.client.overview()['todos']['tasks'][0]['title'], 'First')

    def test_lost_success_response_retries_identical_write(self):
        original = self.client._opener.open
        requests = []
        def lose_response(request, **kwargs):
            requests.append((request.full_url, request.data))
            response = original(request, **kwargs)
            if len(requests) == 1:
                response.close()
                raise URLError('synthetic lost success response')
            return response
        with patch.object(self.client._opener, 'open', side_effect=lose_response):
            self.client.call('/api/mcp/todos/upsert', {
                'request_id': 'lost-response', 'expected_revision': 0, 'title': 'Exactly once'})
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(len(self.client.overview()['todos']['tasks']), 1)

    def test_destination_and_redirect_guards(self):
        from agent_http_demo import local_origin, DemoError, NoRedirect
        for address in ('http://127.0.0.1:8000', 'http://localhost:8765', 'https://127.0.0.1:8765',
                        'http://192.168.1.1:8765', 'http://127.0.0.1:8765/api',
                        'http://user:password@127.0.0.1:8765', 'http://127.0.0.1:8765?x=1'):
            with self.assertRaises(DemoError):
                local_origin(address)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.invalid/'))
        with patch.object(self.client, 'call', return_value={'environment': 'other'}) as call:
            with self.assertRaises(DemoError):
                self.client.check_preview()
            call.assert_called_once_with('/health', authenticated=False)


def main():
    if sys.argv[1:] == ['--worker']:
        # Deny external business traffic even if an unexpected worker starts.
        original = socket.socket.connect
        def loopback_only(sock, address):
            if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] == 8000:
                raise AssertionError('Only isolated loopback connections are permitted')
            return original(sock, address)
        with patch.object(socket.socket, 'connect', loopback_only):
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AgentHTTPTests))
        return 0 if result.wasSuccessful() else 1
    with tempfile.TemporaryDirectory(prefix='attention-agent-http-') as directory:
        temp = Path(directory)
        hub = temp/'hub'
        hub.mkdir()
        for source in (ROOT/'hub').iterdir():
            if source.is_file() and (source.suffix == '.py' or source.name == 'console.html'):
                shutil.copyfile(source, hub/source.name)
        for name in ('agent_http_demo.py', 'test_agent_http_demo.py'):
            shutil.copyfile(ROOT/'examples'/name, temp/name)
        keep = {'PATH', 'SYSTEMROOT', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env.update(TEMP=str(temp), TMP=str(temp), USERPROFILE=str(temp), HOME=str(temp),
                   APPDATA=str(temp/'appdata'), LOCALAPPDATA=str(temp/'localappdata'),
                   WINDIR=str(temp/'no-fonts'), PYTHONPATH=str(hub), PYTHONNOUSERSITE='1',
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', ATTENTION_RADAR_URL='')
        return subprocess.run([sys.executable, '-B', str(temp/'test_agent_http_demo.py'), '--worker'],
                              cwd=temp, env=env, timeout=60).returncode


if __name__ == '__main__':
    raise SystemExit(main())
