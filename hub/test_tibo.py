# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Optional feed integration: simulated providers, no live requests or production data."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from attention import AttentionService, EventInput, AckInput
from router_api import create_router_app
from tibo import TiboModule, TiboPreferences, URLS, parse_events, parse_forecast


class TiboTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.service = AttentionService(self.path)
        self.now = datetime.now(timezone.utc)
        self.calls = []
        self.module = TiboModule(self.service.db, reader=self.reader, clock=lambda: self.now)
        self.service.tibo = self.module

    def reader(self, url):
        self.calls.append(url)
        if url == URLS['events']:
            return {'meta': {'generated_at': self.now.isoformat()}, 'data': {
                'latest_reset': {'announced_at': (self.now-timedelta(days=1)).isoformat(),
                                 'reset_type': 'regular', 'source': {'url': 'https://x.com/thsottiaux/status/1'}},
                'scheduled_reset': None}}
        return {'asOf': self.now.isoformat(), 'expiresAt': (self.now+timedelta(minutes=15)).isoformat(),
                'version': 'TEST', 'degraded': False, 'checks': {'history': {'ok': True}},
                'windows': [{'hours': h, 'probability': p} for h, p in [(24, .12), (48, .24), (72, .38)]]}

    def enable(self, forecast=True, page=True):
        self.module.configure(TiboPreferences(enabled=True, forecast_enabled=forecast, show_page=page))

    def test_disabled_has_no_network_and_preserves_scene(self):
        before = self.service.scene()
        for source in URLS:
            self.module.sample(source)
        self.assertEqual(self.calls, [])
        self.assertEqual(before, self.service.scene())
        self.assertEqual(self.module.view()['events']['status'], 'OFF')

    def test_optional_forecast_and_restart_preferences(self):
        self.enable(forecast=False)
        self.module.sample('events')
        self.module.sample('forecast')
        self.assertEqual(self.calls, [URLS['events']])
        again = AttentionService(self.path)
        self.assertTrue(again.tibo.preferences()['enabled'])
        self.assertFalse(again.tibo.preferences()['forecast_enabled'])
        self.assertEqual(again.scene(tibo_supported=True)['page'], 'tibo')
        self.assertIsNone(again.scene(tibo_supported=True)['tibo']['p24'])
        with again.db.transaction() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_freshness_failure_cooldown_and_recovery(self):
        self.enable()
        for source in URLS:
            self.module.sample(source)
        self.assertEqual(self.module.device()['p24'], 12)
        before = self.service.scene(tibo_supported=True)
        self.module.sample('forecast')
        self.assertEqual(len(self.calls), 2)
        self.now += timedelta(minutes=5)
        self.module.sample('forecast')
        self.assertEqual(before['version'], self.service.scene(tibo_supported=True)['version'])
        self.now += timedelta(minutes=5)
        self.module.reader = lambda url: (_ for _ in ()).throw(TimeoutError('private error'))
        self.module.sample('forecast')
        self.assertEqual(self.module.view()['forecast']['status'], 'STALE')
        self.assertIsNone(self.module.device()['p24'])
        self.assertNotIn('private error', str(self.module.view()))
        self.now += timedelta(minutes=11)
        self.module.reader = self.reader
        self.module.sample('forecast')
        self.assertEqual(self.module.device()['p24'], 12)
        self.now += timedelta(minutes=16)
        self.assertIsNone(self.module.device()['p24'])
        self.assertEqual(self.module.device()['pending'], 'UNKNOWN')

    def test_disabled_inflight_result_is_discarded_without_blocking_scene(self):
        self.enable()
        entered, release = threading.Event(), threading.Event()
        original_reader = self.reader
        def slow(url):
            entered.set()
            release.wait(3)
            return original_reader(url)
        self.module.reader = slow
        thread = threading.Thread(target=self.module.sample, args=('events',))
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.service.scene()['page'], 'home')
            self.module.configure(TiboPreferences(enabled=False))
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.module.view()['events']['status'], 'OFF')
        self.assertEqual(self.service.db.read('tibo_events'), {})

    def test_legacy_capability_interrupt_and_disable(self):
        self.enable()
        legacy = self.service.scene()
        self.assertEqual(legacy['page'], 'home')
        self.assertNotIn('tibo', legacy)
        self.assertEqual(self.service.scene(tibo_supported=True)['page'], 'tibo')
        self.assertEqual(self.service.scene()['version'], legacy['version'])
        self.service.publish(EventInput(id='alarm', revision=1, title='TEST', message='Action needed',
                                       kind='reminder', authorization='user_reminder'))
        self.assertEqual(self.service.scene(tibo_supported=True)['page'], 'interrupt')
        self.service.acknowledge('alarm', AckInput(revision=1, command_id='ack'))
        self.assertEqual(self.service.scene(tibo_supported=True)['page'], 'tibo')
        self.module.configure(TiboPreferences())
        self.assertEqual(self.service.scene(tibo_supported=True)['page'], 'home')

    def test_invalid_upstream_and_expiration_are_not_probabilities(self):
        good = self.reader(URLS['forecast'])
        for value in [-.1, 1.1, True, float('nan'), '0.5']:
            bad = copy.deepcopy(good)
            bad['windows'][0]['probability'] = value
            with self.assertRaises(ValueError):
                parse_forecast(bad, self.now)
        with self.assertRaises(ValueError):
            parse_forecast(good, self.now+timedelta(hours=1))
        bad = self.reader(URLS['events'])
        bad['data']['latest_reset']['source']['url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            parse_events(bad, self.now)
        bad = self.reader(URLS['events'])
        bad['data']['latest_reset']['reset_type'] = 'banked'
        self.assertEqual(parse_events(bad, self.now)['latest']['kind'], 'banked')

    def test_retry_after_is_respected(self):
        self.enable()
        def limited(url):
            self.calls.append(url)
            raise HTTPError(url,429,'limited',{'Retry-After':'1200'},None)
        self.module.reader = limited
        self.assertEqual(self.module.sample('events'),1200)
        self.now += timedelta(minutes=5)
        self.module.sample('events')
        self.assertEqual(len(self.calls),1)

    def test_authenticated_api_and_legacy_negotiation(self):
        app = create_router_app(self.path,start_monitor=False)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            self.assertEqual(client.get('/api/tibo').status_code,401)
            client.get('/')
            command={'enabled':True,'forecast_enabled':False,'show_page':True}
            self.assertEqual(client.post('/api/tibo/preferences',json=command).status_code,403)
            headers={'X-Hub-Action':'1','Origin':'http://127.0.0.1'}
            self.assertEqual(client.post('/api/tibo/preferences',json=command,headers=headers).status_code,200)
            self.assertEqual(client.get('/scene').json()['page'],'home')
            self.assertEqual(client.get('/scene?capabilities=tibo-v1').json()['page'],'tibo')
            self.assertEqual(client.get('/scene?capabilities=unknown').json()['page'],'home')
            self.assertEqual(client.post('/api/tibo/preferences',json={**command,'enabled':'true'},headers=headers).status_code,422)
            command['enabled']=False
            client.post('/api/tibo/preferences',json=command,headers=headers)
            self.assertEqual(client.get('/scene?capabilities=tibo-v1').json()['page'],'home')

    def test_worker_stops_cleanly(self):
        async def check():
            task=asyncio.create_task(self.module.run())
            await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        asyncio.run(check())
        self.assertEqual(self.calls,[])


if __name__ == '__main__':
    unittest.main()
