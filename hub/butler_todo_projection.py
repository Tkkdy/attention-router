# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""One-way shadow Todo/current projection through existing isolated Hub APIs.

Business IDs/text remain untouched. Short device IDs and ASCII fallback labels
are display-only mappings; they never feed back into Todo Core.
"""
import hashlib
import httpx

from attention import TodoSync
from hub_models import WorkspaceSync
from butler_device_bridge import ExistingIsolatedHub


def device_item(todo):
    identity = 'b_' + hashlib.sha256(todo['todo_id'].encode()).hexdigest()[:20]
    title = todo['title']
    supported = bool(title.strip()) and all(32 <= ord(c) <= 126 for c in title)
    label = title[:33] if supported else 'Todo ' + identity[2:10]
    display = ' '.join(title.split())
    display = display if len(display) <= 63 else display[:60] + '...'
    return {'id': identity, 'title': label, 'display_title': display, 'status': todo['status']}


class ProjectionHub(ExistingIsolatedHub):
    """Restart-aware client, still pinned to verified isolated loopback Hub."""
    def __init__(self, *, transport=None):
        self.client = httpx.Client(base_url='http://127.0.0.1:8000', transport=transport,
            timeout=5, follow_redirects=False, trust_env=False)
        self.instance_id = None

    def _verify(self):
        response = self.client.get('/health')
        response.raise_for_status()
        health = response.json()
        if health.get('environment') != 'attention-m3-isolated' or not health.get('instance_id'):
            self.client.cookies.clear()
            self.instance_id = None
            raise ValueError('Verified isolated Hub required')
        if health['instance_id'] != self.instance_id:
            self.client.cookies.clear()
            self.instance_id = None
            response = self.client.get('/')
            response.raise_for_status()
            if not self.client.cookies.get('hub_session'):
                raise ValueError('Local isolated session unavailable')
            self.instance_id = health['instance_id']

    def sync_todos(self, value):
        return self._request('POST', '/api/todos/sync', value.model_dump(mode='json', exclude_unset=True))

    def sync_workspace(self, value):
        return self._request('POST', '/api/workspace/sync', value.model_dump(mode='json', exclude_unset=True))


def project_state(state, service):
    if state.get('authority') != 'shadow':
        raise ValueError('Only shadow state may be projected')
    todos = sorted(state['todos'], key=lambda todo: todo['position'])
    items = [device_item(todo) for todo in todos]
    mapping = {todo['todo_id']: item['id'] for todo, item in zip(todos, items)}
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Display identity collision')
    current = next(({'id': item['id'], 'title': item['title'], 'display_title': item['display_title']} for todo, item in zip(todos, items)
                    if todo['todo_id'] == state.get('current_item_id')), None)
    view = service.overview()
    changed = []
    if view['todos'].get('tasks', []) != items or not view['todos'].get('snapshot_known'):
        revision = view['todos'].get('revision', 0) + 1
        service.sync_todos(TodoSync(revision=revision, command_id=f"butler-todos-{state['revision']}-{revision}",
                                   tasks=items, provenance='SIMULATED'))
        changed.append('todos')
    if view['workspace'].get('current_item') != current:
        revision = view['workspace'].get('revision', 0) + 1
        service.sync_workspace(WorkspaceSync(revision=revision,
            command_id=f"butler-current-{state['revision']}-{revision}",
            current_item=current, provenance='SIMULATED'))
        changed.append('current')
    # overview recomputes the existing Router/Scene; no force_scene or device command.
    if changed:
        service.overview()
    return {'core_revision': state['revision'], 'projected_count': len(items), 'changed': changed,
            'id_mapping': mapping, 'authority': 'shadow', 'device_delivery': 'UNKNOWN',
            'legacy_display_fallback_ids': [todo['todo_id'] for todo in todos
                if device_item(todo)['title'] != todo['title']]}
