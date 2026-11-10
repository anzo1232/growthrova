"""Local operator recovery only; no runtime registration, keys or cloud access.

Snapshots contain ALL tenants and encrypted grants. Keep them private. Preparing
a candidate never starts workers or restores external auth, keys or provider state.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time

from business_marketing_offline import DOCUMENT_TABLES, OPTIONAL_TABLES

DISK_RESERVE = 12 * 1024 ** 3
FORMAT = 'growthrova-private-sqlite-v1'


def _private_path(value, *, exists=True):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('An absolute private path is required')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symbolic links are not supported')
    parent = path.parent
    if not parent.is_dir() or parent.stat().st_mode & 0o077:
        raise ValueError('Parent directory must be private to the operator')
    if exists:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError('A private regular file is required')
    elif path.exists():
        raise ValueError('Destination already exists')
    return path


def _read(path):
    con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    con.execute('PRAGMA query_only=ON')
    con.execute('PRAGMA trusted_schema=OFF')
    return con


def _inspect(con, project_origin):
    if not isinstance(project_origin, str) or not project_origin.startswith('https://'):
        raise ValueError('Explicit expected project origin required')
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if (not (DOCUMENT_TABLES | {'marketing_storage_project'}).issubset(tables)
            or tables - DOCUMENT_TABLES - OPTIONAL_TABLES):
        raise ValueError('Not an isolated Growthrova repository')
    # Runtime schemas have no triggers/views. Refuse executable additions rather
    # than copying an unexpected database into the runtime trust boundary.
    if con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
        raise ValueError('Unexpected executable schema')
    rows = con.execute('SELECT singleton,origin FROM marketing_storage_project').fetchall()
    if rows != [(1, project_origin)]:
        raise ValueError('Authentication project does not match')
    if con.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('Repository integrity check failed')
    # Names come only from the shared exact allowlist; values never enter SQL.
    counts = {name: con.execute('SELECT count(*) FROM "' + name + '"').fetchone()[0]
              for name in sorted(tables)}
    orphan = con.execute('''SELECT count(*) FROM marketing_drafts d
        LEFT JOIN offline_document_owners o ON o.draft_id=d.id WHERE o.draft_id IS NULL''').fetchone()[0]
    missing = con.execute('''SELECT count(*) FROM offline_document_owners o
        LEFT JOIN marketing_drafts d ON d.id=o.draft_id WHERE d.id IS NULL''').fetchone()[0]
    if orphan or missing:
        raise ValueError('Document ownership mapping is incomplete')
    return dict(projectSha256=hashlib.sha256(project_origin.encode()).hexdigest(),
                tableRows=counts, integrity='ok')


def diagnostics(database, project_origin):
    """Operator-wide aggregate counts; no IDs, wording, contact details or keys."""
    path = _private_path(database)
    with closing(_read(path)) as con:
        con.execute('BEGIN')
        return dict(format=FORMAT, **_inspect(con, project_origin),
                    limitations=['Counts are not delivery outcomes or an execution safety check.',
                                 'External auth, vault keys and provider state are not inspected.'])


def _sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy(source, destination, project_origin):
    """SQLite backup includes committed WAL frames without mutating job states."""
    with closing(_read(source)) as src:
        # Pin identity, schema and copied data to one consistent source snapshot.
        src.execute('BEGIN')
        _inspect(src, project_origin)
        size = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        if shutil.disk_usage(destination.parent).free - size < DISK_RESERVE:
            raise ValueError('Snapshot would breach the 12 GiB disk reserve')
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        deadline = time.monotonic() + 60
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise ValueError('Snapshot deadline exceeded')
        try:
            with closing(sqlite3.connect(destination)) as dest:
                src.backup(dest, pages=256, progress=progress, sleep=0.05)
                dest.execute('PRAGMA journal_mode=DELETE')
                report = _inspect(dest, project_origin)
            with destination.open('rb') as stream:
                os.fsync(stream.fileno())
            return report
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def snapshot(database, bundle, project_origin):
    """Create a new private bundle; never overwrite or prune another backup."""
    source = _private_path(database)
    target = _private_path(bundle, exists=False)
    target.mkdir(mode=0o700)
    try:
        copy = target / 'repository.sqlite3'
        report = _copy(source, copy, project_origin)
        manifest = dict(format=FORMAT, createdAt=datetime.now(timezone.utc).isoformat(),
                        database='repository.sqlite3', bytes=copy.stat().st_size,
                        sha256=_sha(copy), **report)
        with open(target / 'manifest.json', 'x', encoding='utf-8',
                  opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as stream:
            json.dump(manifest, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(target)
        _sync_directory(target.parent)
        return manifest
    except BaseException:
        shutil.rmtree(target)
        raise


def prepare_restore(bundle, destination, project_origin):
    """Verify bundle and prepare a NEW candidate. No swap or worker execution."""
    target = _private_path(destination, exists=False)
    base = Path(bundle)
    metadata = _private_path(base / 'manifest.json')
    source = _private_path(base / 'repository.sqlite3')
    if metadata.stat().st_size > 64 * 1024:
        raise ValueError('Invalid snapshot manifest')
    manifest = json.loads(metadata.read_text())
    if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
            or manifest.get('database') != 'repository.sqlite3'
            or manifest.get('bytes') != source.stat().st_size
            or manifest.get('sha256') != _sha(source)
            or manifest.get('projectSha256') != hashlib.sha256(project_origin.encode()).hexdigest()):
        raise ValueError('Snapshot checksum or identity mismatch')
    # A published bundle must be immutable and self-contained, unlike a live WAL
    # repository. Never accept extra committed state outside the checked file.
    if any(Path(str(source) + suffix).exists() for suffix in ('-wal', '-journal')):
        raise ValueError('Snapshot has external journal state')
    report = _copy(source, target, project_origin)
    try:
        if _sha(source) != manifest['sha256']:
            raise ValueError('Snapshot changed during restore preparation')
        _sync_directory(target.parent)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return dict(format=FORMAT, **report, activated=False,
                nextAction='Keep candidate offline; reconcile external actions before any supervised runtime swap.')
