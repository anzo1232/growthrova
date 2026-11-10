#!/usr/bin/env python3
"""Explicit local paths only. Never imports the runtime or reads configuration."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from business_growthrova_recovery import diagnostics, prepare_restore, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-origin', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('diagnostics', help='Private operator aggregate report')
    check.add_argument('--database', required=True)
    backup = commands.add_parser('snapshot', help='Create a NEW local private bundle')
    backup.add_argument('--database', required=True)
    backup.add_argument('--bundle', required=True)
    restore = commands.add_parser('prepare-restore', help='Prepare a NEW offline candidate; never activate')
    restore.add_argument('--bundle', required=True)
    restore.add_argument('--destination', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'diagnostics':
            result = diagnostics(args.database, args.project_origin)
        elif args.command == 'snapshot':
            result = snapshot(args.database, args.bundle, args.project_origin)
        else:
            result = prepare_restore(args.bundle, args.destination, args.project_origin)
    except (OSError, ValueError, sqlite3.Error):
        # Raw SQLite/OS errors can include paths or customer data. Do not dump.
        print('Recovery operation refused or failed. Check private paths, project identity, integrity, space and bundle checksum.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
