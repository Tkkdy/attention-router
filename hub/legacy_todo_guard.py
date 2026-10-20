# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Executor-side legacy store deny gate. Not a replacement for platform wiring.

When installed at the dispatch boundary the legacy executor is read/archive only.
Shell and unknown tools are denied wholesale, not inspected with command regexes.
This cannot protect a filesystem from an executor that bypasses this boundary.
"""
from pathlib import Path
import hashlib
import json
import threading


class LegacyWriteDenied(PermissionError):
    pass


class LegacyTodoGuard:
    def __init__(self, root, audit_path):
        self.root = Path(root).resolve(strict=True)
        self.audit_path = Path(audit_path)
        if self.audit_path.resolve().is_relative_to(self.root):
            raise ValueError('audit must be outside archived source')
        self.lock = threading.Lock()

    def dispatch(self, tool, arguments):
        # This executor has no write-capable delegate, so no fallback can write.
        if tool not in {'Read', 'ArchiveManifest'}:
            with self.lock, self.audit_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'tool': tool, 'decision': 'DENY',
                    'reason': 'legacy_store_read_only'}, ensure_ascii=False) + '\n')
            raise LegacyWriteDenied('legacy_store_read_only')
        if tool == 'ArchiveManifest':
            if arguments:
                raise ValueError('unexpected manifest arguments')
            return [{'path': str(p.relative_to(self.root)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                    for p in sorted(self.root.rglob('*')) if p.is_file() and
                    p.resolve().is_relative_to(self.root) and not p.is_symlink()]
        if set(arguments) != {'path'}:
            raise ValueError('Read requires only path')
        path = (self.root / arguments['path']).resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_file():
            raise LegacyWriteDenied('outside_legacy_store')
        return path.read_text(encoding='utf-8')
