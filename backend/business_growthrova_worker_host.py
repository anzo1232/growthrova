"""Explicit operator host for existing workers. Importing this module starts nothing.

No queue reset, reconciliation, credential discovery or retry is performed here.
Health describes host progress only; workers retain all execution authority.
"""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import time

from business_growthrova_recovery import DISK_RESERVE, _private_path

SERVICES = {
    'social': 'growthrova_social_delivery',
    'followup': 'growthrova_followup_delivery',
    'paid': 'growthrova_paid_delivery',
    'search': 'growthrova_search_observations',
    'measurement': 'growthrova_measurement_refresh',
    'organic': 'growthrova_organic_delivery',
    'care': 'growthrova_care_preparation',
}
FORMAT = 'growthrova-worker-health-v1'


def sidecar(database, suffix):
    return Path(str(_private_path(database)) + suffix)


@contextmanager
def singleton(database):
    """Persistent inode; never unlink the lock, including after a crash."""
    path = sidecar(database, '.worker.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError('Private host lock required')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def write_health(database, value):
    path = sidecar(database, '.worker-health.json')
    # Replace, never follow an existing sidecar, and keep incomplete JSON private.
    fd, temporary = tempfile.mkstemp(prefix='.worker-health-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def health(database, *, max_age=300, clock=time.time):
    """Local probe; no app import, provider call or record/body disclosure."""
    if not isinstance(max_age, (int, float)) or not math.isfinite(max_age) or not 1 <= max_age <= 86400:
        raise ValueError('Invalid health age')
    path = _private_path(sidecar(database, '.worker-health.json'))
    if path.stat().st_size > 4096:
        raise ValueError('Invalid host heartbeat')
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or value.get('format') != FORMAT
            or value.get('state') not in ('starting', 'idle', 'working', 'stopped', 'failed', 'disk_hold')
            or type(value.get('updated')) not in (int, float) or not math.isfinite(value['updated'])):
        raise ValueError('Invalid host heartbeat')
    age = clock() - value['updated']
    # Return an allowlist, not arbitrary local JSON content.
    state = value['state']
    return dict(format=FORMAT, state=state, fresh=0 <= age <= max_age,
                progressing=0 <= age <= max_age and state in ('idle', 'working'),
                ageSeconds=max(0, int(age)),
                meaning='Host progress only; does not confirm connection or delivery.')


class WorkerHost:
    def __init__(self, extensions, selected, *, clock=time.time, free_bytes=None):
        if (not isinstance(selected, (list, tuple)) or not selected
                or any(name not in SERVICES for name in selected) or len(set(selected)) != len(selected)):
            raise ValueError('Select distinct existing workers explicitly')
        self.workers = [(name, extensions[SERVICES[name]]) for name in selected]
        paths = {_private_path(worker.repo.path) for _, worker in self.workers}
        if len(paths) != 1:
            raise ValueError('Workers must share one private repository')
        self.database = paths.pop()
        # Prevent alternate relative/symlink paths from creating another lock.
        if self.database != self.database.resolve():
            raise ValueError('Canonical database path required')
        for name, worker in self.workers:
            method = 'run_batch' if name == 'care' else 'run_one'
            if not callable(getattr(worker, method, None)):
                raise ValueError('Existing worker interface required')
        self.clock = clock
        self.free_bytes = free_bytes or (lambda: shutil.disk_usage(self.database.parent).free)
        self.stop = threading.Event()
        self.cursor = ''
        self.completed = 0

    def report(self, state, service=None):
        write_health(self.database, dict(format=FORMAT, state=state, service=service,
                     updated=self.clock(), completedCalls=self.completed))

    def run(self, *, once=False, interval=5):
        if type(once) is not bool or type(interval) not in (int, float) or not math.isfinite(interval) or not 1 <= interval <= 60:
            raise ValueError('Invalid bounded host interval')
        with singleton(self.database):
            self.report('starting')
            try:
                while not self.stop.is_set():
                    for name, worker in self.workers:
                        if self.stop.is_set():
                            break
                        if self.free_bytes() < DISK_RESERVE:
                            self.report('disk_hold')
                            return 2
                        self.report('working', name)
                        if name == 'care':
                            result = worker.run_batch(cursor=self.cursor)
                            self.cursor = result['nextCursor'] or ''
                        else:
                            worker.run_one()
                        self.completed += 1
                        self.report('idle')
                    if once:
                        break
                    self.stop.wait(interval)
            except Exception:
                # A call may have dispatched. Exit; never repeat it inside this host.
                self.report('failed')
                return 1
            self.report('stopped')
            return 0
