#!/usr/bin/env python3
"""Package two caller-exported Google Sheet value arrays for private editorial staging.

Not a Google API client or an authentication mechanism. It does not establish
that caller-provided arrays are exhaustive or sourced from a particular account.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from snapshot_integrity import RANGES, digest, validate


def package(master, watch, destination, *, require_existing=False):
    out = Path(destination).resolve()
    for part in (out.parent, *out.parent.parents):
        if (part / '.git').exists():
            raise ValueError('PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY')
    if require_existing and not out.parent.is_dir():
        raise ValueError('PRIVATE_DESTINATION_MISSING')
    if out.exists():
        raise ValueError('SNAPSHOT_OUTPUT_ALREADY_EXISTS')
    if not isinstance(master, list) or not isinstance(watch, list):
        raise ValueError('INPUT_VALUES_MUST_BE_ARRAYS')
    tables = {'Master_Index': master, 'MRI_Research_Watch': watch}
    payload = {'_snapshot_complete': True,
               '_snapshot_scope': 'CALLER_EXPORTED_VALUES_NOT_AUTHENTICATED',
               '_snapshot_envelope': {'tabs': {
                   name: {'range': RANGES[name], 'rows': len(rows), 'sha256': digest(rows)}
                   for name, rows in tables.items()}}, **tables}
    validate(payload)
    # Atomic no-clobber creation prevents a repeated run from silently
    # replacing an earlier snapshot under the same destination.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(out), flags, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(payload, file, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            file.write('\n')
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return {'path': str(out), 'tab_rows': {name: len(rows) for name, rows in tables.items()},
            'sha256': {name: payload['_snapshot_envelope']['tabs'][name]['sha256'] for name in tables},
            'source_authentication_verified': False, 'complete_google_read_verified': False}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--master-json', type=Path, required=True)
    cli.add_argument('--watch-json', type=Path, required=True)
    cli.add_argument('--output-json', type=Path, required=True)
    args = cli.parse_args()
    try:
        master = json.loads(args.master_json.read_text(encoding='utf-8-sig'))
        watch = json.loads(args.watch_json.read_text(encoding='utf-8-sig'))
        print(json.dumps(package(master, watch, args.output_json), ensure_ascii=False))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print('ERROR: ' + str(exc))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
