# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""User-delegated AI Interrupt; event-only access to the verified local Hub.

Standing permission is granted by runtime wiring, never by model-supplied flags.
Todo/Core, settings, Tibo lifecycle and device commands are outside this port.
"""
import hashlib
import httpx
from attention import EventInput
from butler_todo_projection import ProjectionHub
from todo_core import ButlerError

class InterruptGatewayPort:
    def __init__(self, hub_factory=ProjectionHub):
        self.hub_factory = hub_factory

    def __call__(self, command):
        if command.action != 'show_interrupt':
            raise ButlerError('action_forbidden', 403)
        identity = hashlib.sha256((command.source + ':' + command.request_id).encode()).hexdigest()[:40]
        event = EventInput(id='agent-interrupt-' + identity, revision=1,
            title=command.arguments['title'], message=command.arguments['message'],
            detail='Delegated AI: ' + command.source, kind='reminder',
            # user_reminder represents the owner's standing grant; origin stays AGENT.
            authorization='user_reminder', provenance='AGENT')
        hub = self.hub_factory()
        try:
            published = hub._request('POST', '/api/events', event.model_dump(mode='json'))
            return {'event_id': published['id'], 'event_revision': published['revision'],
                    'event_status': published['status'], 'route': published.get('route'),
                    'device_delivery': 'UNKNOWN', 'acknowledgment': 'manual',
                    'instruction': 'Hub accepted the event. Do not claim physical display or user acknowledgment.'}
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                raise ButlerError('conflict', 409) from None
            raise ButlerError('interrupt_unavailable', 503) from None
        except Exception:
            # A timeout can follow a committed event: retry identical id and text only.
            raise ButlerError('interrupt_delivery_uncertain', 503) from None
        finally:
            hub.close()


class PreviewInterruptHub:
    """Explicit public-preview target; never probes the private runtime."""
    def __init__(self, url, token, *, transport=None):
        from urllib.parse import urlsplit
        target = urlsplit(url)
        try:
            port = target.port
        except ValueError:
            raise ValueError('invalid preview port') from None
        if (target.scheme != 'http' or target.hostname != '127.0.0.1'
                or target.username is not None or target.password is not None
                or target.path not in ('', '/') or target.query or target.fragment
                or port is None or not 1024 <= port <= 65535 or port == 8000):
            raise ValueError('explicit loopback preview origin required; port 8000 forbidden')
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('32+ ASCII non-whitespace token required')
        self.token = token
        self.client = httpx.Client(base_url=url.rstrip('/'), transport=transport,
            timeout=5, follow_redirects=False, trust_env=False)

    def _request(self, method, path, payload=None):
        health = self.client.get('/health')
        health.raise_for_status()
        if health.json().get('environment') != 'developer-preview':
            raise ValueError('developer-preview Hub required')
        response = self.client.request(method, path, json=payload,
            headers={'Authorization': 'Bearer ' + self.token})
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()
