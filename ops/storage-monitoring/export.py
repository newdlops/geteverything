#!/usr/bin/env python3
"""Forced SSH command: export only one of two fixed, precomputed reports."""
import os
import json
from pathlib import Path
import sys
import re


def main():
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    match = re.fullmatch(r'history (0|[1-9][0-9]{0,18})', command)
    if match:
        after = int(match[1])
        if after >= 2**63:
            return 1
        from history import export_page
        result = export_page('/var/lib/geteverything-storage/log-history.sqlite3', after)
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    files = {'': ('report.json', 65536), 'logs': ('logs.json', 1024 * 1024)}
    if command not in files:
        return 1
    filename, limit = files[command]
    with (Path('/var/lib/geteverything-storage') / filename).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        return 1
    sys.stdout.buffer.write(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
