# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Synthetic, loopback-only Preview stability acceptance; never uses live Todo data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import logging
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
import uvicorn
from fastapi.testclient import TestClient

from attention import AttentionService, TodoSync
from context_monitor import ForegroundSample, SamplingError
from device_text import title_font
from router_api import create_router_app
from router_store import RouterStore
from slow_diagnostics import SlowDiagnostics
from work_context import WorkSessionConfig

ESP = 'tibo-v1,bitmap-titles-v1'
PATHS = ('/health', '/scene?capabilities=' + ESP, '/api/overview')
HEADERS = {'Authorization': 'Bearer synthetic-stability-token'}
RESULTS = {}


def synthetic_foreground(**kwargs):
    return ForegroundSample('Codex.exe', 'SYNTHETIC_PRIVATE_TITLE', 0)


def timed_get(client, path, timeout=5):
    started = time.perf_counter()
    try:
        response = client.get(path, timeout=timeout)
        response.raise_for_status()
        return {'path': path.split('?')[0], 'seconds': time.perf_counter() - started,
                'status': response.status_code, 'body': response.json()}
    except httpx.ReadTimeout:
        return {'path': path.split('?')[0], 'seconds': time.perf_counter() - started,
                'status': 'READ_TIMEOUT'}


def metrics(rows):
    return {path: {'count': len(group), 'max_seconds': max(r['seconds'] for r in group),
                   'statuses': [r['status'] for r in group]}
            for path in ('/health', '/scene', '/api/overview')
            if (group := [r for r in rows if r['path'] == path])}


class IsolatedHub:
    def __init__(self, foreground=synthetic_foreground):
        self.stack = ExitStack()
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='preview-stability-')))
        # These patches are only synthetic inputs. Monitor/Tibo/Radar scheduling,
        # routing, database transactions and HTTP handling remain real.
        self.stack.enter_context(patch('attention.read_foreground', foreground))
        self.stack.enter_context(patch('app.fetch_radar', side_effect=ValueError('unconfigured synthetic source')))
        self.app = create_router_app(self.directory, start_monitor=True, api_token='synthetic-stability-token')
        self.service = self.app.state.dashboard
        self.service.tibo.reader = lambda *a, **k: (_ for _ in ()).throw(AssertionError('external IO forbidden'))
        self.radar_done = threading.Event()
        original = self.service.adapters._refresh_radar_sync
        def refresh():
            original()
            self.radar_done.set()
        self.stack.enter_context(patch.object(self.service.adapters, '_refresh_radar_sync', refresh))
        # Same prewarm as run_preview.py; fallback behavior has its own existing tests.
        title_font()
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=self.port,
            log_level='critical', access_log=False, proxy_headers=False, lifespan='on'))
        self.loop = None
        self.thread_error = None
        async def serve():
            self.loop = asyncio.get_running_loop()
            await self.server.serve(sockets=[self.sock])
        def run():
            try:
                asyncio.run(serve())
            except BaseException as error:
                self.thread_error = error
        self.thread = threading.Thread(target=run, name='synthetic-preview-http')

    def __enter__(self):
        self.thread.start()
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{self.port}', headers=HEADERS, trust_env=False)
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            if self.thread_error:
                raise self.thread_error
            time.sleep(.01)
        if not self.server.started:
            raise AssertionError('isolated server did not start')
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(15)
        self.client.close()
        self.sock.close()
        if self.thread.is_alive():
            raise AssertionError('worker did not drain on shutdown')
        self.stack.close()
        if self.thread_error:
            raise self.thread_error


class PreviewHttpTests(unittest.TestCase):
    def test_01_six_second_sampler_keeps_all_business_endpoints_responsive(self):
        entered = threading.Event()
        finished = threading.Event()
        def slow(**kwargs):
            entered.set()
            time.sleep(6)
            finished.set()
            return synthetic_foreground()
        with IsolatedHub(slow) as hub:
            self.assertTrue(entered.wait(2))
            with ThreadPoolExecutor(max_workers=6) as pool:
                rows = list(pool.map(lambda path: timed_get(hub.client, path), PATHS * 4))
            self.assertFalse(finished.is_set(), 'requests must finish while the sample is still blocked')
            self.assertTrue(all(r['status'] == 200 and r['seconds'] < 5 for r in rows), rows)
            self.assertTrue(all(r['seconds'] < 1 for r in rows), rows)
            RESULTS['slow_sample_outside_transaction'] = {'monitor': True, 'delay_seconds': 6,
                'port': hub.port, 'interfaces': metrics(rows)}
        RESULTS['slow_sample_outside_transaction']['shutdown_worker_drained'] = finished.is_set()

    def test_02_six_second_transaction_reports_business_timeouts_but_not_health(self):
        with IsolatedHub() as hub:
            self.assertTrue(hub.radar_done.wait(3))
            held = threading.Event()
            def hold():
                with hub.service.db.transaction():
                    held.set()
                    time.sleep(6)
            holder = threading.Thread(target=hold)
            holder.start()
            self.assertTrue(held.wait(2))
            # Exercise the Radar write and disabled Tibo polling under contention.
            radar = asyncio.run_coroutine_threadsafe(hub.service.refresh_radar(), hub.loop)
            with ThreadPoolExecutor(max_workers=4) as pool:
                short = [pool.submit(timed_get, hub.client, p, 5) for p in PATHS[1:]]
                long = [pool.submit(timed_get, hub.client, p, 10) for p in PATHS[1:]]
                health = []
                until = time.monotonic() + 6.3
                while time.monotonic() < until:
                    health.append(timed_get(hub.client, '/health', 1))
                    time.sleep(.15)
                short_rows = [f.result() for f in short]
                long_rows = [f.result() for f in long]
            holder.join(3)
            radar.result(3)
            self.assertTrue(all(r['status'] == 200 and r['seconds'] < 1 for r in health), health)
            self.assertTrue(all(r['status'] == 'READ_TIMEOUT' for r in short_rows), short_rows)
            self.assertTrue(all(r['status'] == 200 and 5 < r['seconds'] < 10 for r in long_rows), long_rows)
            logs = [json.loads(l) for l in hub.service.diagnostics.path.read_text().splitlines()]
            waiting = [r for r in logs if r['kind'] in ('transaction', 'observation') and r['python_lock_wait_ms'] > 4000]
            self.assertTrue(waiting, logs)
            requests = [r for r in logs if r['kind'] == 'request' and r.get('path') in ('/scene', '/api/overview')]
            self.assertTrue(requests, logs)
            self.assertTrue(any(t.get('operation_id') == r['operation_id'] for t in waiting for r in requests))
            self.assertTrue(any(r['kind'] == 'transaction' and r['body_ms'] > 5900 for r in logs))
            RESULTS['injected_transaction_hold'] = {'classification': 'EXPECTED_BUSINESS_TIMEOUT_NOT_NORMAL_LOAD',
                'hold_seconds': 6, 'port': hub.port, 'health': metrics(health),
                'device_timeout_clients': [{k:v for k,v in r.items() if k != 'body'} for r in short_rows],
                'patient_clients': [{k:v for k,v in r.items() if k != 'body'} for r in long_rows],
                'diagnostics': logs}

    def test_03_concurrent_sampling_writes_and_published_snapshot_stay_consistent(self):
        with IsolatedHub() as hub:
            self.assertTrue(hub.radar_done.wait(3))
            active = 0
            maximum = 0
            counted = 0
            counter_lock = threading.Lock()
            original = hub.service._sample_context_sync
            def counted_sample():
                nonlocal active, maximum, counted
                with counter_lock:
                    active += 1
                    maximum = max(maximum, active)
                try:
                    original()
                    counted += 1
                finally:
                    with counter_lock:
                        active -= 1
            async def sample_many():
                await asyncio.gather(*(hub.service.sample_context() for _ in range(20)))
            def writes():
                for revision in range(1, 21):
                    response = hub.client.post('/api/todos/sync', json={'revision': revision,
                        'command_id': f'synthetic-{revision}', 'tasks': [{'id':'todo-1','title':f'Synthetic {revision}'}]})
                    response.raise_for_status()
            def business_reads():
                rows = []
                for _ in range(20):
                    served = timed_get(hub.client, PATHS[1])
                    rows.append(served)
                    snapshot = hub.client.get('/api/scene/snapshot', params={'capabilities':ESP}).json()['snapshot']
                    overview = timed_get(hub.client, '/api/overview')
                    rows.append(overview)
                    self.assertEqual(snapshot['scene'], served['body'])
                    self.assertEqual(snapshot['scene_version'], served['body']['version'])
                    self.assertEqual(overview['body']['delivery']['last_offered_version'], served['body']['version'])
                    revision = snapshot['provenance']['todos']['revision']
                    if revision:
                        self.assertEqual(served['body']['todos'][0]['title'], f'Synthetic {revision}')
                return rows
            with patch.object(hub.service, '_sample_context_sync', counted_sample), ThreadPoolExecutor(max_workers=3) as pool:
                samples = asyncio.run_coroutine_threadsafe(sample_many(), hub.loop)
                writer = pool.submit(writes)
                reader = pool.submit(business_reads)
                health = pool.submit(lambda: [timed_get(hub.client, '/health') for _ in range(20)])
                writer.result(15)
                rows = reader.result(15) + health.result(15)
                samples.result(15)
            self.assertEqual(maximum, 1)
            self.assertGreaterEqual(counted, 20)
            final = hub.client.get('/api/overview').json()['todos']
            self.assertEqual(final['revision'], 20)
            self.assertEqual(final['tasks'][0]['title'], 'Synthetic 20')
            self.assertTrue(all(r['status'] == 200 and r['seconds'] < 1 for r in rows), rows)
            RESULTS['normal_concurrency'] = {'port':hub.port, 'interfaces':metrics(rows),
                'synthetic_writes':20,'samples_completed':counted,'max_simultaneous_samples':maximum,
                'published_snapshot_checks':20,'final_revision':final['revision']}


class WorkerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_drains_worker_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AttentionService(Path(directory))
            entered, release = threading.Event(), threading.Event()
            recorded = []
            original = service.record_context
            calls = 0
            def foreground(**kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    entered.set()
                    release.wait(3)
                return synthetic_foreground()
            def record(evidence):
                recorded.append(calls)
                original(evidence)
            with patch('attention.read_foreground', foreground), patch.object(service,'record_context',record):
                first = asyncio.create_task(service.sample_context())
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                    first.cancel()
                    await asyncio.sleep(.02)
                    second = asyncio.create_task(service.sample_context())
                    first.cancel()
                    await asyncio.sleep(.05)
                    self.assertFalse(first.done())
                    self.assertEqual(calls, 1)
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await first
                    await second
                finally:
                    release.set()
                self.assertEqual(recorded, [1, 2])
                self.assertNotIn('SYNTHETIC_PRIVATE_TITLE', str(service.context()))

    async def test_sampling_errors_and_storage_failure_do_not_poison_next_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AttentionService(Path(directory))
            with patch('attention.read_foreground', side_effect=OSError('PRIVATE_EXCEPTION')):
                await service.sample_context()
            self.assertEqual(service.context()['error_category'], 'SAMPLER_INTERNAL_ERROR')
            with patch('attention.read_foreground', synthetic_foreground), patch.object(service,'record_context',side_effect=RuntimeError('storage')):
                with self.assertRaises(RuntimeError):
                    await service.sample_context()
            with patch('attention.read_foreground', synthetic_foreground):
                await service.sample_context()
            self.assertIsNone(service.db.local.__dict__.get('db'))

    async def test_config_change_cannot_split_inflight_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            service = AttentionService(Path(directory))
            old = service.context_detector
            entered, release = threading.Event(), threading.Event()
            def foreground(**kwargs):
                entered.set(); release.wait(3)
                return synthetic_foreground()
            with patch('attention.read_foreground', foreground):
                sample = asyncio.create_task(service.sample_context())
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                change = asyncio.create_task(asyncio.to_thread(service.configure_context, WorkSessionConfig()))
                await asyncio.sleep(.03)
                self.assertIs(service.context_detector, old)
                release.set()
                await sample
                await change
                self.assertIsNot(service.context_detector, old)


class BoundaryAndDiagnosticTests(unittest.TestCase):
    def test_overview_uses_one_read_snapshot_and_keeps_explicit_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_router_app(Path(directory),start_monitor=False,api_token='synthetic-stability-token')
            service = app.state.dashboard
            service.diagnostics.threshold_ms = 0
            with TestClient(app, client=('192.168.1.50',5000)) as client:
                scene = client.get('/scene?capabilities='+ESP).json()
                snapshot = service.scene_snapshot(ESP)
                before = service.db.path.read_bytes()
                response = client.get('/api/overview',headers=HEADERS)
                response.raise_for_status()
                self.assertEqual(before,service.db.path.read_bytes())
                self.assertEqual(service.scene_snapshot(ESP)['snapshot'],snapshot['snapshot'])
                self.assertEqual(response.json()['runtime']['esp32']['device_requested_version'],scene['version'])
                records = [json.loads(l) for l in service.diagnostics.path.read_text().splitlines()]
                request = next(r for r in reversed(records) if r['kind']=='request' and r['path']=='/api/overview')
                associated = [r for r in records if r.get('operation_id')==request['operation_id'] and r['kind'] in ('transaction','observation')]
                self.assertEqual([r['kind'] for r in associated],['observation'])
                client.get('/api/overview',headers={**HEADERS,'X-Hub-Request-ID':'synthetic-audit'}).raise_for_status()
                with service.db.observation() as db:
                    actions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM actions')]
                matches=[a for a in actions if a.get('stage')=='MCP_READ_RECEIVED' and a.get('request_id')=='synthetic-audit']
                self.assertEqual(len(matches),1)
                self.assertEqual(service.scene_snapshot(ESP)['snapshot'],snapshot['snapshot'])

    def test_sqlite_begin_wait_is_separate_from_python_lock_and_rollback_works(self):
        with tempfile.TemporaryDirectory() as directory:
            diag = SlowDiagnostics(Path(directory)/'slow.jsonl',threshold_ms=0)
            store = RouterStore(Path(directory),{},diagnostics=diag)
            store.write('item',{'value':1})
            held=threading.Event()
            def external_writer():
                db=sqlite3.connect(store.path,isolation_level=None)
                db.execute('BEGIN IMMEDIATE'); held.set(); time.sleep(.25); db.rollback(); db.close()
            thread=threading.Thread(target=external_writer); thread.start(); self.assertTrue(held.wait(1))
            store.write('item',{'value':2}); thread.join()
            rows=[json.loads(l) for l in diag.path.read_text().splitlines()]
            self.assertTrue(any(r['sqlite_begin_ms']>150 and r['python_lock_wait_ms']<50 for r in rows))
            with self.assertRaises(RuntimeError):
                with store.transaction() as outer:
                    with store.transaction() as inner:
                        self.assertIs(inner,outer)
                        store.write('item',{'value':3})
                    raise RuntimeError('synthetic rollback')
            self.assertEqual(store.read('item'),{'value':2})
            with store.observation():
                with self.assertRaises(sqlite3.OperationalError):
                    store.write('item',{'value':4})
            self.assertEqual(store.read('item'),{'value':2})
            RESULTS['sqlite_begin_separation']={'max_begin_ms':max(r['sqlite_begin_ms'] for r in rows),'rollback':'PASS','observation_read_only':'PASS'}

    def test_diagnostics_are_bounded_redacted_and_independent_of_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_router_app(Path(directory),start_monitor=False,api_token='synthetic-stability-token')
            diag=app.state.dashboard.diagnostics; diag.threshold_ms=0
            prior=logging.root.manager.disable
            try:
                logging.disable(logging.CRITICAL)
                with TestClient(app) as client:
                    client.get('/scene?capabilities='+ESP+'&token=PRIVATE_TOKEN',headers={'X-Private':'PRIVATE_HEADER'})
                    client.get('/PRIVATE_PATH?token=PRIVATE_TOKEN',headers=HEADERS)
            finally:
                logging.disable(prior)
            raw=diag.path.read_text()
            for secret in ('PRIVATE_TOKEN','PRIVATE_HEADER','PRIVATE_PATH','synthetic-stability-token'):
                self.assertNotIn(secret,raw)
            diag.path.write_text('x'*262144)
            for _ in range(3):
                diag.record('request',1001,path='/health',status=200)
                self.assertTrue(Path(str(diag.path)+'.1').exists())
                diag.path.write_text('x'*262144)
            self.assertFalse(Path(str(diag.path)+'.3').exists())
            blocked=SlowDiagnostics(diag.path/'no-file')
            blocked.record('request',1001)
            self.assertEqual(blocked.write_failures,1)
            self.assertIsNotNone(blocked.last_error)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--results',type=Path)
    args,remaining=parser.parse_known_args()
    result=unittest.main(argv=['test_preview_stability.py',*remaining],exit=False)
    if args.results:
        args.results.write_text(json.dumps(RESULTS,indent=2),encoding='utf-8')
    raise SystemExit(not result.result.wasSuccessful())
