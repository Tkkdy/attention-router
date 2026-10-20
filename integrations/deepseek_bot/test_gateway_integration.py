# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Real cross-language transport fixture, without a real Bot, model or production data."""
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "hub"))

import uvicorn
from butler_gateway import create_butler_app
from todo_core import TodoCore


class GatewayIntegration(unittest.TestCase):
    def test_node_adapter_to_python_core(self):
        with tempfile.TemporaryDirectory(prefix="butler-node-") as directory:
            deepseek, grok = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            core = TodoCore(Path(directory) / "todo-shadow.sqlite3")
            application = create_butler_app(core, {deepseek: "deepseek", grok: "grok"})
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(application, log_level="error", access_log=False, proxy_headers=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.02)
                self.assertTrue(server.started, "isolated gateway did not start")
                payload = {"origin": f"http://127.0.0.1:{listener.getsockname()[1]}", "deepseek": deepseek, "grok": grok}
                result = subprocess.run(
                    ["node", str(Path(__file__).with_name("gateway-live.mjs"))],
                    input=json.dumps(payload), text=True, capture_output=True, timeout=25,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                listener.close()
                self.assertFalse(thread.is_alive(), "fixture server did not stop")


if __name__ == "__main__":
    unittest.main()

