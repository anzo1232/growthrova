"""Bounded, payload-free diagnostics at the synchronous Playwright boundary.

Instrument only the boundary, avoiding a global profiler on every renderer,
fixture and library call. Actions, deadlines and original exceptions are intact.
"""
from functools import wraps
import json
import sys
import time


class BrowserActionTiming:
    def __init__(self, directory, *, boundary=None):
        self.path = directory / 'browser-actions.jsonl'
        self.boundary = boundary
        self.original = None
        self.sequence = 0
        self.output = None

    def __enter__(self):
        if self.boundary is None:
            from playwright._impl._sync_base import SyncBase
            self.boundary = SyncBase
        self.original = self.boundary._sync
        self.output = self.path.open('w', encoding='utf-8')
        original = self.original

        @wraps(original)
        def timed(instance, *args, **kwargs):
            # Keep exact return/exception semantics, including nested route
            # callbacks. Never inspect arguments, results or exception payloads.
            if self.sequence >= 6000:
                return original(instance, *args, **kwargs)
            self.sequence += 1
            ident = self.sequence
            caller = sys._getframe(1)
            row = dict(id=ident, event='started', action=caller.f_code.co_name,
                       monotonicSeconds=time.monotonic())
            while caller is not None:
                if caller.f_code.co_filename.endswith('growthrova-workspace-recovery.browser.py'):
                    row['journeyLine'] = caller.f_lineno
                caller = caller.f_back
            cpu = time.process_time()
            self._write(row)
            try:
                return original(instance, *args, **kwargs)
            finally:
                # Unwinding a failed action is not a PASS. Flush every row so
                # an external deadline retains the in-flight start.
                self._write(dict(id=ident, event='returned',
                    wallSeconds=time.monotonic()-row['monotonicSeconds'],
                    cpuSeconds=time.process_time()-cpu))

        self.boundary._sync = timed
        return self

    def __exit__(self, *exception):
        self.boundary._sync = self.original
        self.output.close()

    def _write(self, row):
        self.output.write(json.dumps(row) + '\n')
        # Keep starts readable even when the controller kills the child during
        # an action. Reuse the stream without buffering away timeout evidence.
        self.output.flush()
