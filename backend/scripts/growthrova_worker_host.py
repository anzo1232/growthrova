#!/usr/bin/env python3
"""Opt-in operator runner. No default factory, environment lookup or web listener."""
import argparse
import importlib
import json
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from business_growthrova_worker_host import SERVICES, WorkerHost, health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    probe = commands.add_parser('health', help='Read heartbeat without importing runtime')
    probe.add_argument('--database', required=True)
    probe.add_argument('--max-age', type=int, default=300)
    run = commands.add_parser('run', help='Explicit execution; requires separate operator authority')
    run.add_argument('--factory', required=True, help='Reviewed Python module:function returning configured private app')
    run.add_argument('--services', nargs='+', choices=tuple(SERVICES), required=True)
    run.add_argument('--once', action='store_true')
    run.add_argument('--interval', type=int, choices=range(1, 61), default=5)
    args = parser.parse_args()
    try:
        if args.command == 'health':
            result = health(args.database, max_age=args.max_age)
            print(json.dumps(result))
            return 0 if result['progressing'] else 1
        module, name = args.factory.split(':')
        factory = getattr(importlib.import_module(module), name)
        app = factory()
        host = WorkerHost(app.extensions, args.services)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: host.stop.set())
        return host.run(once=args.once, interval=args.interval)
    except Exception:
        # No exceptions/provider bodies/configuration/paths in service logs.
        print('Worker host refused or failed. Review private configuration, lock, disk and heartbeat.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
