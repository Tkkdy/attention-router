# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Opt-in, loopback-only wiring of the existing Gateway to a fresh preview Hub."""
import argparse
import getpass
from pathlib import Path
import uvicorn
from butler_gateway import create_butler_app
from grok_capabilities import INTERRUPT_ACTIONS
from interrupt_gateway import InterruptGatewayPort, PreviewInterruptHub
from todo_core import TodoCore

def credential(prompt):
    value = getpass.getpass(prompt)
    if len(value) < 32 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError('32+ ASCII non-whitespace token required')
    return value

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-autonomous-interrupts', action='store_true',
        help='Owner grants this provider standing permission to choose Interrupt timing and text')
    parser.add_argument('--provider', choices=('grok', 'deepseek'), required=True)
    parser.add_argument('--hub-url', default='http://127.0.0.1:8765')
    parser.add_argument('--port', type=int, default=3102)
    args = parser.parse_args()
    if not args.allow_autonomous_interrupts:
        parser.error('explicit --allow-autonomous-interrupts standing grant required')
    if not 1024 <= args.port <= 65535 or args.port == 8000:
        parser.error('choose an unused port, excluding 8000')
    try:
        hub_token = credential('Preview Hub token: ')
        gateway_token = credential('Different provider Gateway token: ')
        if hub_token == gateway_token:
            raise ValueError('Hub and Gateway tokens must differ')
        # Validate target syntax before constructing any service or listener.
        target = PreviewInterruptHub(args.hub_url, hub_token)
        try:
            target._request('GET', '/api/overview')
        finally:
            target.close()
    except (ValueError, OSError):
        parser.error('invalid configuration; no Gateway started')
    core = TodoCore(Path(__file__).resolve().parents[1] / '.build/interrupt-preview/todo-shadow.sqlite3')
    application = create_butler_app(core, {gateway_token: args.provider},
        action_permissions={args.provider: INTERRUPT_ACTIONS},
        interrupt_port=InterruptGatewayPort(lambda: PreviewInterruptHub(args.hub_url, hub_token)))
    uvicorn.run(application, host='127.0.0.1', port=args.port,
                access_log=False, proxy_headers=False)

if __name__ == '__main__':
    main()
