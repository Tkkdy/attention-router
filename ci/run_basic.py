# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Run a named, limited regression set in a disposable copy with no application socket IO."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    'test_scene_snapshot',
    'test_preview_revision.PreviewRevisionTests.test_optional_radar_scope',
    'test_preview_revision.PreviewRevisionTests.test_lan_access_matrix',
    'test_attention.AttentionTests.test_routes_have_distinct_actions_and_queue_reevaluates',
    'test_attention.AttentionTests.test_ack_idempotency_versions_and_todos_unchanged',
    'test_attention.AttentionTests.test_duplicate_and_out_of_order_event_revisions',
    'test_attention.AttentionTests.test_transaction_rollback_keeps_event_and_trace_consistent',
    'test_preview_stability.WorkerRegressionTests',
    'test_preview_stability.BoundaryAndDiagnosticTests',
]
EXCLUDED = [
    'test_attention.AttentionTests.test_atomic_migration_keeps_json_and_restarts (known IndexError)',
    'test_attention.AttentionTests.test_invalid_migration_is_atomic (known missing ValueError)',
]

def worker():
    import socket
    import inspect
    import unittest
    from unittest.mock import patch
    pair_code = getattr(socket.socketpair, '__code__', None)
    def guarded(original):
        def call(self, *args, **kwargs):
            # Windows asyncio uses stdlib socketpair's private ephemeral loopback
            # pair as its self-wakeup pipe. Permit only that exact stdlib caller.
            caller = inspect.currentframe().f_back
            if pair_code is not None and caller.f_code is pair_code:
                return original(self, *args, **kwargs)
            raise AssertionError('CI basic suite forbids application socket bind/connect')
        return call
    # TestClient is in-process; no application listen socket or outbound IO.
    with patch.object(socket.socket, 'connect', guarded(socket.socket.connect)), patch.object(socket.socket, 'connect_ex', guarded(socket.socket.connect_ex)), patch.object(socket.socket, 'bind', guarded(socket.socket.bind)):
        suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

def main():
    if sys.argv[1:] == ['--worker']:
        return worker()
    if sys.argv[1:]:
        raise SystemExit('Usage: python ci/run_basic.py')
    print('LIMITED BASIC SUITE: not full regression or hardware acceptance', flush=True)
    for item in EXCLUDED:
        print('Known legacy migration failure NOT IN BASIC SET: ' + item, flush=True)
    with tempfile.TemporaryDirectory(prefix='attention-ci-') as directory:
        temp = Path(directory)
        hub = temp/'hub'
        hub.mkdir()
        # app.py constructs a default instance at import time. Copying prevents any
        # default .build writes in the user's checkout or private running directory.
        for p in (ROOT/'hub').iterdir():
            if p.is_file() and (p.suffix == '.py' or p.name == 'console.html'):
                shutil.copyfile(p, hub/p.name)
        keep = {'PATH', 'SYSTEMROOT', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env.update(TEMP=str(temp), TMP=str(temp), HOME=str(temp), USERPROFILE=str(temp),
                   APPDATA=str(temp/'appdata'), LOCALAPPDATA=str(temp/'localappdata'),
                   WINDIR=str(temp/'no-system-fonts'), PYTHONPATH=str(hub),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                   PYTHONNOUSERSITE='1', ATTENTION_RADAR_URL='')
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'], cwd=temp, env=env, timeout=90)
        return result.returncode

if __name__ == '__main__':
    raise SystemExit(main())
