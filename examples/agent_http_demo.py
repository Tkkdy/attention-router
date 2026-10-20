# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Synthetic Agent -> Hub demo. Loopback only; no model, device or Bot required."""
import argparse
import getpass
from http.client import HTTPException
import json
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


class DemoError(Exception):
    """Safe public error: never includes credentials or response bodies."""


class RevisionConflict(DemoError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a Bearer token to another origin.


def local_origin(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port or 80
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or not 1024 <= port <= 65535 or port == 8000):
            raise ValueError
    except ValueError:
        raise DemoError('Use http://127.0.0.1:PORT (1024-65535, excluding private port 8000).') from None
    return f'http://127.0.0.1:{port}'


class HubClient:
    def __init__(self, origin, token):
        self.origin = local_origin(origin)
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise DemoError('Token must be 32+ ASCII characters with no whitespace.')
        self._token = token
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, path, data=None, *, authenticated=True):
        if not path.startswith('/api/') and path != '/health':
            raise DemoError('Unsupported demo API path.')
        body = json.dumps(data).encode('utf-8') if data is not None else None
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self._token
        # Repeat the exact bytes/IDs/revisions after a lost response, never a new intent.
        for attempt in range(3):
            request = Request(self.origin + path, data=body, headers=headers)
            try:
                with self._opener.open(request, timeout=5) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 409:
                    latest = self.overview()
                    raise RevisionConflict(
                        'HTTP 409: stopped without overwrite; current revisions: '
                        f"todos={latest['todos'].get('revision', 0)}, "
                        f"workspace={latest['workspace'].get('revision', 0)}. "
                        'Inspect the Console before creating a new intent/request ID.') from None
                if error.code in (401, 403):
                    raise DemoError(f'HTTP {error.code}: authentication/permission denied; check the local token.') from None
                raise DemoError(f'HTTP {error.code}: request rejected; inspect the isolated Hub.') from None
            except (URLError, TimeoutError, socket.timeout, ConnectionError, HTTPException):
                if attempt == 2:
                    raise DemoError('Connection failed after identical retries. Inspect the Console before rerunning; a write may have succeeded.') from None
            except (ValueError, UnicodeError):
                raise DemoError('Hub returned an invalid JSON response.') from None

    def check_preview(self):
        health = self.call('/health', authenticated=False)
        if health.get('environment') != 'developer-preview':
            raise DemoError('Refusing a non-preview Hub. Start a fresh hub/run_preview.py instance.')

    def overview(self):
        return self.call('/api/overview')


def create_demo(client):
    client.check_preview()
    overview = client.overview()
    identity = uuid4().hex[:12]
    command = {'request_id': 'http-todo-' + identity,
               'expected_revision': overview['todos'].get('revision', 0),
               'title': 'Synthetic Agent demo task'}
    created = client.call('/api/mcp/todos/upsert', command)
    # Deliberate replay demonstrates the Hub ledger does not create a second Todo.
    if client.call('/api/mcp/todos/upsert', command) != created:
        raise DemoError('Unexpected idempotency result.')
    todo = created['result']['todo']
    overview = client.overview()
    client.call('/api/workspace/sync', {
        'command_id': 'http-current-' + identity,
        'revision': overview['workspace'].get('revision', 0) + 1,
        'project': 'Synthetic HTTP demo',
        'current_item': {'id': todo['id'], 'title': todo['title']},
        'provenance': 'SIMULATED'})
    event_id = 'http-reminder-' + identity
    client.call('/api/events', {
        'id': event_id, 'revision': 1, 'kind': 'reminder',
        'authorization': 'user_reminder', 'provenance': 'SIMULATED',
        'title': 'Synthetic Agent reminder',
        'message': 'Review demo; ACK leaves the Todo pending.'})
    return {'todo_id': todo['id'], 'event_id': event_id}


def acknowledge_demo(client, demo):
    command = {'revision': 1, 'command_id': 'ack-' + demo['event_id']}
    path = '/api/events/' + demo['event_id'] + '/ack'
    acknowledged = client.call(path, command)
    if client.call(path, command) != acknowledged:
        raise DemoError('Unexpected ACK replay result.')
    overview = client.overview()
    todo = next((t for t in overview['todos'].get('tasks', []) if t['id'] == demo['todo_id']), None)
    if todo is None or todo.get('status') != 'pending':
        raise DemoError('Demo Todo is no longer pending; inspect concurrent changes in the Console.')
    return acknowledged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    try:
        origin = local_origin(args.url)
        print('This demo creates a synthetic Todo, Current and explicitly authorized reminder in your fresh preview Hub.')
        print('No model calls. Use a new installation, not an existing task database.')
        client = HubClient(origin, getpass.getpass('Hub Bearer token (hidden): '))
        demo = create_demo(client)
        print('Created Todo ' + demo['todo_id'] + ' and reminder ' + demo['event_id'] + '.')
        print('Open ' + origin + '/ to inspect Todo, Current and reminder. Todo creation replayed without duplication.')
        input('Click ACK in the Console, then press Enter; or press Enter to let this script ACK the demo reminder: ')
        acknowledge_demo(client, demo)
        print('ACK and identical replay succeeded. The Todo remains pending; completion is a separate action.')
        return 0
    except (DemoError, EOFError, KeyboardInterrupt) as error:
        print(str(error) if isinstance(error, DemoError) else 'Demo interrupted; inspect the Console before rerunning.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
