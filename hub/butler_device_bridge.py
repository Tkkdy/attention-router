# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Narrow local client for the already running M3 isolated Hub.

Uses its existing loopback console authentication/CSRF contract. No credential
files, firmware commands, settings, Todo or workspace writes are exposed.
"""
import httpx


class ExistingIsolatedHub:
    event_only = True

    def __init__(self, *, transport=None):
        self.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=transport,
            timeout=10, follow_redirects=False, trust_env=False)
        self.instance_id = None
        self._verify()
        response = self.client.get('/')
        response.raise_for_status()
        if not self.client.cookies.get('hub_session'):
            raise ValueError('isolated Hub local authentication unavailable')

    def close(self):
        self.client.close()

    def _verify(self):
        response = self.client.get('/health')
        response.raise_for_status()
        health = response.json()
        if (health.get('environment') != 'attention-m3-isolated'
                or not health.get('instance_id')
                or self.instance_id not in (None, health['instance_id'])):
            raise ValueError('verified isolated Hub instance required')
        self.instance_id = health['instance_id']

    def _request(self, method, path, payload=None):
        self._verify()  # Never carry a session over an unverified Hub restart/switch.
        response = self.client.request(method, path, json=payload,
            headers={'Origin': 'http://127.0.0.1:8000', 'X-Hub-Action': '1'})
        response.raise_for_status()
        return response.json()

    def publish(self, event):
        return self._request('POST', '/api/events', event.model_dump(mode='json'))

    def acknowledge(self, event_id, command, *, cancel=False):
        from butler_models import Identifier
        from pydantic import TypeAdapter
        event_id = TypeAdapter(Identifier).validate_python(event_id)
        operation = 'cancel' if cancel else 'ack'
        return self._request('POST', f'/api/events/{event_id}/{operation}', command.model_dump(mode='json'))

    def reevaluate(self):
        # overview invokes the existing Router/Scene evaluation; no manual display command.
        self.overview()

    def overview(self):
        return self._request('GET', '/api/overview')
