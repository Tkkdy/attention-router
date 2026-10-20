# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Run the isolated shadow Gateway with caller-supplied credentials held only in memory."""
import argparse
import os
import json
from getpass import getpass
from pathlib import Path
import uvicorn
from butler_gateway import create_butler_app
from todo_core import TodoCore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parents[1] / '.build' / 'butler-d1-preview' / 'todo-shadow.sqlite3')
    parser.add_argument('--port', type=int, default=3102)
    parser.add_argument('--deepseek', action='store_true', help='Enable the real resolver using existing DEEPSEEK_* caller environment')
    parser.add_argument('--evidence', type=Path, help='Append redacted semantic request metadata only')
    parser.add_argument('--attention-dir', type=Path, help='Optional isolated .build/.../butler-attention-shadow Hub bridge')
    parser.add_argument('--existing-isolated-hub', action='store_true', help='Project events only through the existing verified localhost:8000 isolated Hub')
    args = parser.parse_args()
    if args.attention_dir and args.existing_isolated_hub:
        parser.error('choose one isolated Hub target')
    if not 1024 <= args.port <= 65535 or args.port in {3001, 3101, 8000}:
        parser.error('use an unprivileged isolated port distinct from existing Hub/MCP/Spike')
    tokens = {}
    for source in ('deepseek', 'grok'):
        token = os.environ.get('BUTLER_' + source.upper() + '_TOKEN', '') if args.deepseek else getpass(f'{source} Gateway credential (32+ chars; blank disables this entry): ')
        if not token:
            continue
        if token in tokens:
            parser.error('each provider requires a distinct credential')
        tokens[token] = source
    # Credentials are validated before opening any database.
    if not tokens or any(len(token) < 32 or any(c.isspace() for c in token) for token in tokens):
        parser.error('at least one non-blank 32+ character credential is required')
    resolver = None
    if args.deepseek:
        from semantic_resolver import DeepSeekSemanticResolver
        def record(value):
            if args.evidence:
                args.evidence.parent.mkdir(parents=True, exist_ok=True)
                with args.evidence.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        resolver = DeepSeekSemanticResolver.from_environment(evidence_sink=record)
    bridge = None
    try:
        if args.attention_dir:
            from butler_bridge import ButlerHubBridge
            bridge = ButlerHubBridge(args.attention_dir)
        if args.existing_isolated_hub:
            from butler_bridge import ButlerHubBridge
            bridge = ButlerHubBridge.existing_isolated_hub()
        application = create_butler_app(TodoCore(args.database), tokens, resolver, bridge)
        uvicorn.run(application, host='127.0.0.1', port=args.port, access_log=False, proxy_headers=False)
    finally:
        if bridge and hasattr(bridge.service, 'close'):
            bridge.service.close()
        if resolver:
            resolver.close()

if __name__ == '__main__':
    main()
