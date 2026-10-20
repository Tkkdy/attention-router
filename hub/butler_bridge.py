# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Shadow-only projection to the existing AttentionService/Router/Scene implementation.

The Core is authoritative. A failed projection remains retryable with deterministic IDs.
No monitor, network polling, physical device loop, or Hub-owned Todo mutations are started.
"""
from pathlib import Path
from attention import AttentionService, EventInput, AckInput
from hub_models import WorkspaceSync


class ButlerHubBridge:
    def __init__(self, data_dir, *, service=None):
        path = Path(data_dir).resolve()
        isolated = Path(__file__).resolve().parents[1] / '.build'
        if not path.is_relative_to(isolated) or path.name != 'butler-attention-shadow':
            raise ValueError('bridge requires .build/.../butler-attention-shadow isolation')
        self.service = service or AttentionService(path)

    @classmethod
    def existing_isolated_hub(cls):
        from butler_device_bridge import ExistingIsolatedHub
        bridge = cls.__new__(cls)
        bridge.service = ExistingIsolatedHub()
        return bridge

    def project(self, state):
        projected, skipped = [], []
        for suggestion in state.get('suggestions', []):
            if getattr(self.service, 'event_only', False):
                skipped.append({'id': suggestion['id'], 'reason': 'existing_hub_workspace_preserved'})
                continue
            text = suggestion.get('device_text') or suggestion['text']
            if not text.isascii() or len(text) > 47:
                skipped.append({'id': suggestion['id'], 'reason': 'explicit_ascii_device_text_required'})
                continue
            projected.append({'id': suggestion['id'], 'text': text, 'expires_at': suggestion.get('expires_at')})
        try:
            # This dedicated Hub workspace receives only suggestion projections, never current/Todos.
            if state.get('suggestions') and not getattr(self.service, 'event_only', False):
                self.service.sync_workspace(WorkspaceSync(
                    revision=state['revision'], command_id=f"butler-suggestions-{state['revision']}",
                    suggestions=projected, provenance='SIMULATED'))
            for event in state.get('attention_events', []):
                published = self.service.publish(EventInput.model_validate({
                    k: v for k, v in event.items() if k not in {'todo_id', 'cancelled'}}))
                if event.get('cancelled') and published['status'] == 'active':
                    self.service.acknowledge(event['id'], AckInput(revision=event['revision'],
                        command_id=f"butler-cancel-{event['id']}-{event['revision']}"), cancel=True)
            for ack in state.get('interrupt_acks', []):
                event = next((e for e in state.get('attention_events', []) if e['id'] == ack['event_id']), None)
                if event is None or event.get('cancelled') or event['revision'] != ack['revision']:
                    continue
                self.service.acknowledge(ack['event_id'], AckInput(
                    revision=ack['revision'], command_id=ack['command_id']))
            self.service.reevaluate()
            return {'status': 'projected', 'core_revision': state['revision'],
                    'unprojected_suggestions': skipped, 'device_delivery': 'UNKNOWN'}
        except Exception:
            # Core commit already succeeded. Never claim rollback or leak backend diagnostics.
            return {'status': 'projection_pending', 'core_revision': state['revision'],
                    'retryable': True, 'device_delivery': 'UNKNOWN'}

    def dashboard(self, state):
        view = self.service.overview()
        return {**view, 'todos': {'authority': state['authority'], 'revision': state['revision'],
                                 'tasks': state['todos'], 'current_item_id': state['current_item_id']},
                'todo_scene_projection': 'not_configured', 'data_scope': 'isolated_shadow'}
