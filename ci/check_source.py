# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Read-only syntax and published-file checks. No imports of application modules."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BANNED_PARTS = {'.build', '.venv', 'node_modules', '__pycache__', 'review-private', 'private'}
BANNED_NAMES = {'private_config.h', 'config.local.json', '.env'}
BANNED_SUFFIXES = {'.bin', '.elf', '.hex', '.map', '.db', '.sqlite', '.sqlite3', '.dpapi', '.log', '.zip', '.pfx', '.p12', '.key'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--syntax-only', action='store_true')
    args = parser.parse_args()
    paths = []
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if '.git' in rel.parts:
            continue  # A future checkout may contain Git metadata; never distribute it.
        if p.is_symlink():
            raise SystemExit(f'Symlink requires explicit release review: {rel.as_posix()}')
        if not p.is_file():
            continue
        paths.append(p)
    errors = []
    for p in paths:
        rel = p.relative_to(ROOT)
        if any(part in BANNED_PARTS for part in rel.parts) or p.name in BANNED_NAMES or p.suffix.lower() in BANNED_SUFFIXES or (p.name.startswith('.env.') and p.name != '.env.example'):
            errors.append(f'private/generated file: {rel.as_posix()}')
        if p.suffix == '.py':
            ast.parse(p.read_text(encoding='utf-8-sig'), filename=rel.as_posix())
    print(f'Python syntax: {sum(p.suffix == ".py" for p in paths)} files parsed without execution')
    if not args.syntax_only:
        actual = {p.relative_to(ROOT).as_posix(): p for p in paths}
        declared = json.loads((ROOT/'SOURCE_MANIFEST.json').read_text(encoding='utf-8-sig'))['files']
        recorded = {}
        for entry in declared:
            rel = entry['path']
            pp = PurePosixPath(rel)
            if pp.is_absolute() or '..' in pp.parts or chr(92) in rel or rel in recorded:
                errors.append('invalid or duplicate manifest path')
                continue
            recorded[rel] = entry
        # The manifest cannot contain its own hash. GIT_FILES lists every public file.
        expected = set(actual) - {'SOURCE_MANIFEST.json'}
        if set(recorded) != expected:
            errors.append('manifest file-set mismatch; update reviewed manifest for legitimate additions/removals')
        for rel in expected & set(recorded):
            data = actual[rel].read_bytes()
            if len(data) != recorded[rel]['bytes'] or hashlib.sha256(data).hexdigest() != recorded[rel]['sha256']:
                errors.append(f'manifest hash/size mismatch: {rel}')
        listed = (ROOT/'GIT_FILES.txt').read_text(encoding='utf-8-sig').splitlines()
        if len(listed) != len(set(listed)) or set(listed) != set(actual):
            errors.append('GIT_FILES mismatch; update reviewed public-file list')
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Source checks PASS' + (' (manifest not checked in syntax-only mode)' if args.syntax_only else '; manifest, hashes and public-file list match'))

if __name__ == '__main__':
    main()
