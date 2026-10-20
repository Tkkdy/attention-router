# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""SIMULATED failure/contract tests; real client and physical acceptance are separate."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from attention import AttentionService
from hub_models import ContextOverride
from quota_collector import QuotaCollector, sanitize_limits
from quota_policy import QuotaPreferences
from router_api import create_router_app


class M3Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.service = AttentionService(self.path)

    def test_collector_success_failure_recovery_preserves_manual_policy(self):
        sample = sanitize_limits({'rateLimits': {'planType': 'pro', 'primary': {
            'usedPercent': 31, 'windowDurationMins': 10080, 'resetsAt': 9999999999}, 'credits': {'private': 1}}})
        self.assertNotIn('credits', sample)
        self.service.set_quota_preferences(QuotaPreferences(five_hour_override=False))
        collector = QuotaCollector(self.service, reader=lambda: sample)
        self.assertEqual(collector.sample(), 120)
        state = self.service.state()['codex']
        self.assertEqual(state['collection'], 'AUTOMATIC')
        self.assertEqual(state['windows'][0]['status'], 'UNKNOWN')
        self.assertEqual(state['windows'][1]['remaining_percent'], 69)
        successful = state['last_success_at']
        def failure(): raise TimeoutError('not retained')
        collector.reader = failure
        self.assertEqual(collector.sample(), 240)
        self.assertEqual(collector.sample(), 480)
        state = self.service.state()['codex']
        self.assertEqual(state['last_success_at'], successful)
        self.assertEqual(state['windows'][1]['status'], 'STALE')
        self.assertEqual(state['windows'][1]['remaining_percent'], 69)
        self.assertEqual(state['windows'][0]['status'], 'UNKNOWN')
        self.assertFalse(state['display_policy']['five_hour']['visible'])
        collector.reader = lambda: sample
        self.assertEqual(collector.sample(), 120)
        self.assertEqual(self.service.state()['codex']['collection'], 'AUTOMATIC')

    def test_failure_without_snapshot_remains_unknown(self):
        def failure(): raise OSError()
        collector = QuotaCollector(self.service, reader=failure)
        collector.sample()
        state = self.service.state()['codex']
        self.assertEqual(state['status'], 'UNKNOWN')
        self.assertEqual(state['collection'], 'DEGRADED')
        self.assertNotIn('last_success_at', state)

    def test_automatic_unchanged_sample_does_not_refresh_scene(self):
        sample = {'source': 'codex_app_server', 'windows': [{'windowDurationMins':10080,'usedPercent':24,'resetsAt':9999999999}]}
        self.service.set_context(ContextOverride(mode='CODING'))
        collector = QuotaCollector(self.service, reader=lambda: sample)
        collector.sample()
        before = self.service.scene()['version']
        collector.sample()
        self.assertEqual(self.service.scene()['version'], before)
        actions=self.service.overview()['recent_actions']
        self.assertEqual(sum(a['stage']=='QUOTA_SAMPLE_SUCCEEDED' for a in actions), 2)

    def test_mcp_correlation_target_and_auth(self):
        app=create_router_app(self.path, start_monitor=False, environment='isolated-test')
        client=TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1',1234))
        self.assertEqual(client.get('/api/overview',headers={'X-Hub-Request-ID':'mcp-test-1'}).status_code,401)
        client.get('/')
        state=client.get('/api/overview',headers={'X-Hub-Request-ID':'mcp-test-1'}).json()
        self.assertEqual(state['environment'],'isolated-test')
        self.assertEqual(state['request_id'],'mcp-test-1')
        action=next(a for a in state['recent_actions'] if a['stage']=='MCP_READ_RECEIVED')
        self.assertEqual(action['instance_id'],state['instance_id'])
        self.assertEqual(action['request_id'],state['request_id'])
