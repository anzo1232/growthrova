"""Owner-scoped, restart-aware visual scanning with a bounded shared SQLite queue.

Jobs are durable and non-retriable automatically: stale or failed work is
reported clearly rather than replayed or charged again. A separate database
avoids Clippr's creator processing SQLite lock contention.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from threading import RLock, Event, Thread

from business_visual import scan_visual_scenes
from business_sources import MAX_BYTES,source_for_owner

DB_LOCK = RLock()
DEFAULT_DB = "/opt/clippr/tmp/business_visual/jobs.db"
TIMEOUT_SECONDS = 120
QUEUE_TIMEOUT_SECONDS = 15 * 60
HEARTBEAT_INTERVAL_SECONDS = 15
MAX_PENDING_JOBS = 3
ACTIVE_STATES = ("queued", "running", "downloading", "scanning", "finalizing")
WORKER_STATES = ("running", "downloading", "scanning", "finalizing")


class VisualQueueFull(RuntimeError):
    pass


def _db(path):
    with DB_LOCK:
        for attempt in range(4):
            try:
                p = Path(path)
                p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                db = sqlite3.connect(str(p), timeout=5)
                os.chmod(p, 0o600)
                db.execute("PRAGMA busy_timeout=5000")
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("""CREATE TABLE IF NOT EXISTS visual_jobs(
                  job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, org_id TEXT NOT NULL,
                  source_id TEXT NOT NULL, source_key TEXT NOT NULL,
                  status TEXT NOT NULL, result_json TEXT,
                  created_at REAL NOT NULL, updated_at REAL NOT NULL,
                  UNIQUE(owner,source_id)
                )""")
                # Durable candidate usage record; NEVER charges Stripe.
                # Inserted in same DB transaction as successful scan finalization.
                db.execute("""CREATE TABLE IF NOT EXISTS visual_usage_candidates(
                  job_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                  source_id TEXT NOT NULL, processed_seconds REAL NOT NULL,
                  state TEXT NOT NULL DEFAULT 'needs_billing_review',
                  created_at REAL NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES visual_jobs(job_id)
                )""")
                db.execute("CREATE INDEX IF NOT EXISTS idx_visual_usage_owner ON visual_usage_candidates(owner,created_at)")
                cols={row[1] for row in db.execute("PRAGMA table_info(visual_jobs)")}
                if "lease_token" not in cols:
                    db.execute("ALTER TABLE visual_jobs ADD COLUMN lease_token TEXT")
                if "worker_id" not in cols:
                    db.execute("ALTER TABLE visual_jobs ADD COLUMN worker_id TEXT")
                db.commit()
                return db
            except sqlite3.OperationalError as exc:
                try:
                    db.close()
                except (UnboundLocalError, sqlite3.Error):
                    pass
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                time.sleep(.08 * (attempt + 1))


def _path(path):
    return path or os.environ.get("CLIPPR_BUSINESS_VISUAL_DB", DEFAULT_DB)


def _id(owner, source_id):
    return hashlib.sha256((owner + ":" + source_id).encode("utf-8")).hexdigest()[:32]


def _interrupt_stale(db, now):
    db.execute("""UPDATE visual_jobs SET status='interrupted',updated_at=?
                  WHERE status='queued' AND updated_at < ?""",
               (now, now - QUEUE_TIMEOUT_SECONDS))
    db.execute("""UPDATE visual_jobs SET status='interrupted',updated_at=?
                  WHERE status IN ('running','downloading','scanning','finalizing')
                  AND updated_at < ?""", (now, now - TIMEOUT_SECONDS))


def find_job(owner, job_id, *, path=None, now=None):
    now = time.time() if now is None else now
    db = _db(_path(path))
    try:
        db.execute("BEGIN IMMEDIATE")
        _interrupt_stale(db, now)
        row = db.execute(
            "SELECT org_id,source_id,source_key,status,result_json FROM visual_jobs WHERE owner=? AND job_id=?",
            (owner, job_id)).fetchone()
        db.commit()
        if not row:
            return None
        try:
            result = json.loads(row[4]) if row[4] else None
        except (ValueError, TypeError):
            result = None
        return {"job_id": job_id, "org_id": row[0], "source_id": row[1],
                "source_key": row[2], "status": row[3], "result": result}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def reserve_job(owner, org_id, source_id, source_key, *, path=None, now=None):
    now = time.time() if now is None else now
    path = _path(path)
    job_id = _id(owner, source_id)
    db = _db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        _interrupt_stale(db, now)
        row = db.execute(
            "SELECT job_id,status FROM visual_jobs WHERE owner=? AND source_id=?",
            (owner, source_id)).fetchone()
        if row:
            db.commit()
            return {"job_id": row[0], "status": row[1], "replayed": True}
        count = db.execute("""SELECT COUNT(*) FROM visual_jobs
                              WHERE status IN ('queued','running','downloading','scanning','finalizing')""").fetchone()[0]
        if count >= MAX_PENDING_JOBS:
            db.commit()
            raise VisualQueueFull("Visual scan queue is busy")
        db.execute("""INSERT INTO visual_jobs(
                      job_id,owner,org_id,source_id,source_key,status,created_at,updated_at)
                      VALUES(?,?,?,?,?,'queued',?,?)""",
                   (job_id, owner, org_id, source_id, source_key, now, now))
        db.commit()
        return {"job_id": job_id, "status": "queued", "replayed": False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _stage(job_id,owner,status,path,*,now=None,lease_token=None):
    if status not in WORKER_STATES:raise ValueError("Invalid worker stage")
    db=_db(path)
    try:
        guard=" AND lease_token IS NULL" if lease_token is None else " AND lease_token=?"
        values=(status,time.time() if now is None else now,job_id,owner)
        if lease_token is not None:values+=(lease_token,)
        changed=db.execute("""UPDATE visual_jobs SET status=?,updated_at=?
            WHERE job_id=? AND owner=?
            AND status IN ('queued','running','downloading','scanning','finalizing')"""+guard,values)
        db.commit()
        return changed.rowcount==1
    finally:db.close()


def _heartbeat(job_id,owner,path,stop,*,lease_token=None,lost=None):
    while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
        try:
            db=_db(path)
            try:
                guard=" AND lease_token IS NULL" if lease_token is None else " AND lease_token=?"
                vals=(time.time(),job_id,owner)
                if lease_token is not None:vals+=(lease_token,)
                changed=db.execute("""UPDATE visual_jobs SET updated_at=?
                    WHERE job_id=? AND owner=?
                    AND status IN ('running','downloading','scanning','finalizing')"""+guard,vals)
                db.commit()
                if changed.rowcount!=1:
                    if lost is not None:lost.set()
                    return
            finally:db.close()
        except (sqlite3.Error,OSError) as exc:
            print("[business-visual] heartbeat unavailable: "+type(exc).__name__,flush=True)


def _finish(job_id, owner, status, result, path, *, lease_token=None):
    if status not in ("done", "error"):
        raise ValueError("Terminal status must be done or error")
    if status=="done":
        # A successful scan must include a defensible processed duration;
        # otherwise later usage-billing integration would omit work silently.
        try:seconds=float(result["duration_s"])
        except (TypeError,KeyError,ValueError):
            raise ValueError("Completed source scan missing duration") from None
        if not math.isfinite(seconds) or not 3<=seconds<=600:
            raise ValueError("Invalid completed scan duration")
    db = _db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        now=time.time()
        guard=" AND lease_token IS NULL" if lease_token is None else " AND lease_token=?"
        values=(status,json.dumps(result,separators=(",",":")) if result else None,
                now,job_id,owner)
        if lease_token is not None:values+=(lease_token,)
        cursor=db.execute("""UPDATE visual_jobs SET status=?,result_json=?,updated_at=?
            WHERE job_id=? AND owner=?
            AND status IN ('queued','running','downloading','scanning','finalizing')"""+guard,values)
        if cursor.rowcount==1 and status=="done":
            owner_source=db.execute(
                "SELECT source_id FROM visual_jobs WHERE job_id=? AND owner=?",
                (job_id,owner)).fetchone()
            db.execute("""INSERT OR IGNORE INTO visual_usage_candidates(
                job_id,owner,source_id,processed_seconds,state,created_at)
                VALUES (?,?,?,?,'needs_billing_review',?)""",
                (job_id,owner,owner_source[0],round(seconds,2),now))
        db.commit()
        return cursor.rowcount==1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def usage_candidates(owner, *, path=None):
    """Owner-only source processing records, strictly not an invoice."""
    if not owner:return {"events":[],"billable":False}
    db=_db(_path(path))
    try:
        rows=db.execute("""SELECT job_id,source_id,processed_seconds,state
            FROM visual_usage_candidates WHERE owner=?
            ORDER BY created_at DESC LIMIT 100""",(owner,)).fetchall()
        return {"events":[dict(zip(
            ("job_id","source_id","processed_seconds","state"),row)) for row in rows],
            "billable":False}
    finally:db.close()


def scan_job(deps,job_id,owner,key,*,path=None,lease_token=None,source_path=None):
    path=_path(path)
    stop=Event()
    lost=Event()
    thread=None
    def advance(stage):
        if lost.is_set() or not _stage(job_id,owner,stage,path,lease_token=lease_token):
            raise RuntimeError("Visual scan lease lost; work must stop")
    try:
        advance("running")
        thread=Thread(target=_heartbeat,args=(job_id,owner,path,stop),
                      kwargs={"lease_token":lease_token,"lost":lost},
                      daemon=True,name="clippr-visual-heartbeat")
        thread.start()
        record=source_for_owner(key,owner,path=source_path)
        if not record or record["status"]!="confirmed" or not record.get("etag"):
            raise ValueError("Source version not confirmed")
        r2=deps.get_r2()
        if r2 is None:raise ValueError("Storage not configured")
        head=r2.head_object(Bucket=deps.r2_bucket,Key=key)
        size=int(head.get("ContentLength") or 0)
        if (not 1024<=size<=MAX_BYTES or size!=record["declared_size"]
                or head.get("ETag")!=record["etag"]):
            raise ValueError("Source object changed after confirmation")
        suffix=Path(key).suffix.lower()
        advance("downloading")
        with tempfile.TemporaryDirectory(prefix="clippr-business-scenes-") as folder:
            source=Path(folder)/("source"+suffix)
            r2.download_file(deps.r2_bucket,key,str(source))
            if source.stat().st_size!=size:
                raise ValueError("Incomplete downloaded source")
            after=r2.head_object(Bucket=deps.r2_bucket,Key=key)
            if after.get("ETag")!=record["etag"] or int(after.get("ContentLength") or 0)!=size:
                raise ValueError("Source changed during scan download")
            advance("scanning")
            result=scan_visual_scenes(source)
        advance("finalizing")
        _finish(job_id,owner,"done",result,path,lease_token=lease_token)
    except Exception as exc:
        print("[business-visual] scan failed: "+type(exc).__name__,flush=True)
        try:
            _finish(job_id,owner,"error",
                    {"error":"Visual scan failed. Your source remains available."},path,
                    lease_token=lease_token)
        except (sqlite3.Error,OSError) as save_error:
            print("[business-visual] failed to save error: "+type(save_error).__name__,flush=True)
    finally:
        stop.set()
        if thread is not None:thread.join(timeout=2)


def claim_next_visual(worker_id,*,path=None,now=None):
    """Atomic persistent lease: one worker per queued scan, no automatic replay."""
    if not isinstance(worker_id,str) or not 1<=len(worker_id)<=120:
        raise ValueError("Invalid worker identity")
    now=time.time() if now is None else now
    db=_db(_path(path))
    try:
        db.execute("BEGIN IMMEDIATE")
        _interrupt_stale(db,now)
        record=db.execute("""SELECT job_id,owner,org_id,source_id,source_key
          FROM visual_jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1""").fetchone()
        if not record:
            db.commit()
            return None
        token=uuid.uuid4().hex
        changed=db.execute("""UPDATE visual_jobs SET status='running',updated_at=?,
           lease_token=?,worker_id=? WHERE job_id=? AND status='queued'""",
           (now,token,worker_id,record[0]))
        if changed.rowcount!=1:
            db.rollback()
            return None
        db.commit()
        return {**dict(zip(("job_id","owner","org_id","source_id","source_key"),record)),
                "lease_token":token}
    except Exception:
        db.rollback()
        raise
    finally:db.close()
