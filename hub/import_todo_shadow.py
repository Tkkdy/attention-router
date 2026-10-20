# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Local, explicitly supplied export only. Imports into a fresh shadow DB, never canonical."""
import argparse
import json
from pathlib import Path
from todo_core import TodoCore
from todo_shadow import ShadowSnapshot, parity

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True, help='User-approved structured export JSON')
    parser.add_argument('--database', type=Path, required=True, help='New isolated todo-shadow.sqlite3')
    parser.add_argument('--request-id', required=True)
    args = parser.parse_args()
    if args.snapshot.stat().st_size > 8 * 1024 * 1024:
        parser.error('snapshot exceeds 8 MiB')
    snapshot = ShadowSnapshot.model_validate(json.loads(args.snapshot.read_text(encoding='utf-8-sig')))
    core = TodoCore(args.database)
    core.import_shadow(snapshot, request_id=args.request_id)
    report = parity(snapshot, core.snapshot())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['match'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
