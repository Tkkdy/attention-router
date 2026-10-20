# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Read-only completion gate; no scheduler, sender, or Todo writer."""
import hashlib
import json


def map_reminders(routines, snapshot, rules):
    output = []
    for routine in routines:
        rule = rules.get(routine['id'], {})
        terms = rule.get('all_terms', [])
        candidates = [t for t in snapshot['todos'] if terms and all(s in t['title'] for s in terms)]
        unique = len(candidates) == 1
        output.append({'legacy_reminder': routine['id'], 'name': routine['name'],
            'legacy_todo': candidates[0]['title'] if unique else None,
            'new_todo_id': candidates[0]['todo_id'] if unique else None,
            'candidate_ids': [t['todo_id'] for t in candidates],
            'status': 'MAPPED' if unique else 'NEEDS_USER_DECISION',
            'evidence': rule.get('evidence', 'no unique explicit object or collection semantics'),
            'match_terms': terms, 'legacy_prompt': routine['prompt_full'],
            'legacy_status': candidates[0]['status'] if unique else None,
            'completion_source': 'Gateway get_context -> canonical Todo Core',
            'schedule': routine['schedule'], 'timezone': routine.get('timezone'),
            'enabled': routine.get('enabled'), 'installed': False})
    return output


class ReminderCompletionGate:
    def __init__(self, read_context):
        self.read_context = read_context

    def evaluate(self, binding, scheduled_at):
        if binding.get('status') != 'MAPPED' or not binding.get('new_todo_id'):
            return {'send_allowed': False, 'reason': 'unresolved_binding'}
        try:
            payload = self.read_context()
            if not payload.get('ok'):
                raise ValueError('gateway unavailable')
            state = payload['result']
            matches = [t for t in state['todos'] if t['todo_id'] == binding['new_todo_id']]
        except Exception:
            return {'send_allowed': False, 'reason': 'status_unavailable'}
        if len(matches) != 1:
            return {'send_allowed': False, 'reason': 'missing_or_ambiguous_todo'}
        key = hashlib.sha256(json.dumps([binding['legacy_reminder'], scheduled_at,
                                        binding['new_todo_id']], ensure_ascii=False).encode()).hexdigest()
        return {'send_allowed': matches[0]['status'] == 'pending', 'status': matches[0]['status'],
                'revision': state['revision'], 'dedupe_key': key,
                'reason': 'pending' if matches[0]['status'] == 'pending' else 'not_pending'}
