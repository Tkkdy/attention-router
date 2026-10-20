# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Optional MCP regressions in a disposable copy; never load private runtime."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    if sys.argv[1:] == ['--worker']:
        import socket
        import unittest
        from unittest.mock import patch
        original = socket.socket.connect
        def loopback_only(sock, address):
            if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] in (8000, 3102, 3103):
                raise AssertionError('Only disposable loopback listeners are permitted')
            return original(sock, address)
        with patch.object(socket.socket, 'connect', loopback_only):
            suite = unittest.defaultTestLoader.loadTestsFromName('experiments.grok_butler.test_server')
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if sys.argv[1:]:
        raise SystemExit('Usage: python -B ci/run_mcp.py')
    with tempfile.TemporaryDirectory(prefix='attention-mcp-ci-') as directory:
        temp = Path(directory)
        for name in ('hub', 'experiments'):
            for source in (ROOT/name).rglob('*'):
                if source.is_file() and (source.suffix == '.py' or source.name == 'console.html') and '__pycache__' not in source.parts:
                    target = temp/source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        keep = {'PATH', 'SYSTEMROOT', 'COMSPEC', 'PATHEXT', 'SYSTEMDRIVE'}
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env.update(TEMP=str(temp), TMP=str(temp), HOME=str(temp), USERPROFILE=str(temp),
            APPDATA=str(temp/'appdata'), LOCALAPPDATA=str(temp/'localappdata'),
            WINDIR=str(temp/'no-fonts'), PYTHONPATH=str(temp/'hub')+os.pathsep+str(temp),
            PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONUTF8='1',
            PYTHONIOENCODING='utf-8', ATTENTION_RADAR_URL='')
        return subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'],
                              cwd=temp, env=env, timeout=90).returncode

if __name__ == '__main__':
    raise SystemExit(main())
