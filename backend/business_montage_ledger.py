"""Durable, idempotent and heartbeat-aware montage admission.

Explicit paid entitlement is checked by the HTTP route before admission.
Ledger never charges or retries work automatically. Stale workers cannot
overwrite an interrupted, failed or completed job.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from pathlib import Path
from threading import RLock

DB_PATH="/opt/clippr/tmp/business_montage/ledger.db"
_LOCK=RLock()
LIMIT_PER_USER_DAY=3
LIMIT_GLOBAL_DAY=30
MAX_PROCESSING=2
# Processing admission safety ceilings. These are NOT financial charges.
MAX_USER_OUTPUT_SECONDS_DAY=360
MAX_GLOBAL_OUTPUT_SECONDS_DAY=3600
# Waiting work may be delayed longer than an actively processing worker that
# stopped updating its heartbeat.
QUEUE_STALE_SECONDS=15*60
RUNNING_STALE_SECONDS=3*60
HEARTBEAT_SECONDS=15
ACTIVE=("queued","running")
PHASES=("queued","starting","downloading","rendering","uploading","finished","interrupted","failed")

class MontageLimit(Exception):pass

def _db(path=None):
    path=Path(path or os.environ.get("CLIPPR_BUSINESS_MONTAGE_DB",DB_PATH))
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    with _LOCK:
        con=sqlite3.connect(path,timeout=5)
        try:
            os.chmod(path,0o600)
            con.execute("PRAGMA busy_timeout=5000")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS montage_jobs (
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,organisation TEXT NOT NULL,
                digest TEXT NOT NULL,status TEXT NOT NULL,
                source_json TEXT NOT NULL,output_key TEXT,error_code TEXT,
                created REAL NOT NULL,updated REAL NOT NULL,
                UNIQUE(owner,digest))""")
            cols={r[1] for r in con.execute("PRAGMA table_info(montage_jobs)")}
            if "phase" not in cols:
                con.execute("ALTER TABLE montage_jobs ADD COLUMN phase TEXT NOT NULL DEFAULT 'queued'")
            if "payload_json" not in cols:
                con.execute("ALTER TABLE montage_jobs ADD COLUMN payload_json TEXT")
            if "lease_token" not in cols:
                con.execute("ALTER TABLE montage_jobs ADD COLUMN lease_token TEXT")
            if "worker_id" not in cols:
                con.execute("ALTER TABLE montage_jobs ADD COLUMN worker_id TEXT")
            if "reserved_seconds" not in cols:
                con.execute("ALTER TABLE montage_jobs ADD COLUMN reserved_seconds REAL NOT NULL DEFAULT 0")
            con.execute("""CREATE TABLE IF NOT EXISTS montage_usage_events(
                job_id TEXT PRIMARY KEY,owner TEXT NOT NULL,
                output_seconds REAL NOT NULL,created REAL NOT NULL
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS montage_usage_owner ON montage_usage_events(owner,created)")
            con.execute("CREATE INDEX IF NOT EXISTS montage_day ON montage_jobs(owner,created)")
            con.commit()
            return con
        except Exception:
            con.close()
            raise

def identity(owner,org,brand_id,windows):
    canonical=json.dumps([org,brand_id,windows],sort_keys=True,separators=(",",":"))
    digest=hashlib.sha256(canonical.encode()).hexdigest()
    job_id=hashlib.sha256((owner+":"+digest).encode()).hexdigest()[:32]
    return job_id,digest

def _reap(db,now):
    db.execute("""UPDATE montage_jobs SET status='interrupted',phase='interrupted',
                  error_code='worker_interrupted',lease_token=NULL,worker_id=NULL,updated=?
                  WHERE status='queued' AND updated<?""",
               (now,now-QUEUE_STALE_SECONDS))
    db.execute("""UPDATE montage_jobs SET status='interrupted',phase='interrupted',
                  error_code='worker_interrupted',lease_token=NULL,worker_id=NULL,updated=?
                  WHERE status='running' AND updated<?""",
               (now,now-RUNNING_STALE_SECONDS))

def _output_seconds(windows):
    if not isinstance(windows,list) or not 2<=len(windows)<=6:
        raise ValueError("Choose two to six scenes")
    total=0.0
    for row in windows:
        if not isinstance(row,dict):
            raise ValueError("Invalid montage scene")
        try:start=float(row["start_s"]);end=float(row["end_s"])
        except (KeyError,TypeError,ValueError):
            raise ValueError("Invalid montage timeline") from None
        if not (math.isfinite(start) and math.isfinite(end) and start>=0
                and 3<=end-start<=30):
            raise ValueError("Montage scene timing must be 3-30 seconds")
        total+=end-start
    if total>120:
        raise ValueError("Montage may not exceed two minutes")
    return round(total,3)


def claim(owner,org,brand_id,windows,*,path=None,now=None,brand_snapshot=None,render_brand_id=None):
    if not owner or not org:
        raise ValueError("Invalid montage claim")
    reserved_seconds=_output_seconds(windows)
    now=time.time() if now is None else now
    job_id,digest=identity(owner,org,brand_id,windows)
    payload=None
    if brand_snapshot is not None:
        if (not isinstance(brand_snapshot,dict) or not isinstance(render_brand_id,str)
                or not render_brand_id):
            raise ValueError("Montage render configuration invalid")
        payload=json.dumps({"brand":brand_snapshot,"brand_id":render_brand_id,
                            "org":org,"scenes":windows},sort_keys=True,separators=(",",":"))
    db=_db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        _reap(db,now)
        row=db.execute("SELECT status,phase FROM montage_jobs WHERE id=? AND owner=?",
                       (job_id,owner)).fetchone()
        if row:
            db.commit()
            return {"id":job_id,"status":row[0],"phase":row[1],"replayed":True}
        since=now-86400
        user=db.execute("SELECT COUNT(*) FROM montage_jobs WHERE owner=? AND created>=?",
                        (owner,since)).fetchone()[0]
        total=db.execute("SELECT COUNT(*) FROM montage_jobs WHERE created>=?",(since,)).fetchone()[0]
        active=db.execute("SELECT COUNT(*) FROM montage_jobs WHERE status IN ('queued','running')").fetchone()[0]
        used_user=db.execute("""SELECT COALESCE(SUM(reserved_seconds),0) FROM montage_jobs
                 WHERE owner=? AND created>=?""",(owner,since)).fetchone()[0]
        used_global=db.execute("""SELECT COALESCE(SUM(reserved_seconds),0) FROM montage_jobs
                 WHERE created>=?""",(since,)).fetchone()[0]
        if (user>=LIMIT_PER_USER_DAY or total>=LIMIT_GLOBAL_DAY or active>=MAX_PROCESSING
                or used_user+reserved_seconds>MAX_USER_OUTPUT_SECONDS_DAY
                or used_global+reserved_seconds>MAX_GLOBAL_OUTPUT_SECONDS_DAY):
            db.commit()
            raise MontageLimit("Daily or concurrent montage capacity reached")
        db.execute("""INSERT INTO montage_jobs(
                      id,owner,organisation,digest,status,phase,source_json,payload_json,
                      reserved_seconds,created,updated)
                      VALUES(?,?,?,?,'queued','queued',?,?,?,?,?)""",
                   (job_id,owner,org,digest,json.dumps(windows,separators=(",",":")),
                    payload,reserved_seconds,now,now))
        db.commit()
        return {"id":job_id,"status":"queued","phase":"queued","replayed":False}
    except Exception:
        db.rollback()
        raise
    finally:db.close()

def lookup(owner,job_id,*,path=None,now=None):
    if not owner:return None
    db=_db(path)
    try:
        now=time.time() if now is None else now
        db.execute("BEGIN IMMEDIATE")
        _reap(db,now)
        row=db.execute("""SELECT status,phase,output_key,error_code,organisation,updated
                          FROM montage_jobs WHERE owner=? AND id=?""",
                       (owner,job_id)).fetchone()
        db.commit()
        return dict(zip(("status","phase","output_key","error_code","organisation","updated"),row)) if row else None
    except Exception:
        db.rollback()
        raise
    finally:db.close()

def update(owner,job_id,status,*,key=None,error=None,path=None,now=None,lease_token=None):
    if status not in ("running","done","error","interrupted"):
        raise ValueError("Invalid montage status")
    now=time.time() if now is None else now
    phase={"running":"starting","done":"finished",
           "error":"failed","interrupted":"interrupted"}[status]
    db=_db(path)
    try:
        if status=="running":
            condition="status='queued'"
        else:
            condition="status='running'" if status=="done" else "status IN ('queued','running')"
        if status=="running":
            lease_where="AND lease_token IS NULL"
            lease_args=()
        elif lease_token is None:
            lease_where="AND lease_token IS NULL"
            lease_args=()
        else:
            lease_where="AND lease_token=?"
            lease_args=(lease_token,)
        db.execute("BEGIN IMMEDIATE")
        cursor=db.execute("""UPDATE montage_jobs SET status=?,phase=?,
            output_key=COALESCE(?,output_key),error_code=?,updated=?
            WHERE owner=? AND id=? AND """+condition+" "+lease_where,
            (status,phase,key,error,now,owner,job_id,*lease_args))
        if cursor.rowcount==1 and status=="done":
            expected=f"business/montages/{owner}/{job_id}.mp4"
            if key!=expected:
                raise ValueError("Cannot settle without the verified owner-scoped montage key")
            # Ledger event and terminal transition commit together. Not a
            # Stripe charge: counted output duration, exactly once per job.
            job=db.execute("SELECT reserved_seconds FROM montage_jobs WHERE id=? AND owner=?",
                           (job_id,owner)).fetchone()
            db.execute("""INSERT OR IGNORE INTO montage_usage_events(
                         job_id,owner,output_seconds,created) VALUES(?,?,?,?)""",
                       (job_id,owner,float(job[0] if job else 0),now))
        db.commit()
        return cursor.rowcount==1
    except Exception:
        db.rollback()
        raise
    finally:db.close()

def heartbeat(owner,job_id,phase,*,path=None,now=None,lease_token=None):
    """Update a running job only. False means cancelled/reaped/finished."""
    if phase not in ("starting","downloading","rendering","uploading"):
        raise ValueError("Invalid montage phase")
    db=_db(path)
    try:
        lease_where="AND lease_token IS NULL" if lease_token is None else "AND lease_token=?"
        values=(phase,time.time() if now is None else now,owner,job_id)
        if lease_token is not None:values+= (lease_token,)
        cursor=db.execute("""UPDATE montage_jobs SET phase=?,updated=?
                             WHERE owner=? AND id=? AND status='running' """+lease_where,values)
        db.commit()
        return cursor.rowcount==1
    finally:db.close()


def claim_next(worker_id, *, path=None, now=None):
    """Atomic durable lease; one job at most, never retries abandoned jobs."""
    if not isinstance(worker_id,str) or not 1<=len(worker_id)<=120:
        raise ValueError("Invalid worker identity")
    now=time.time() if now is None else now
    db=_db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        _reap(db,now)
        row=db.execute("""SELECT id,owner,organisation,payload_json FROM montage_jobs
                          WHERE status='queued' AND payload_json IS NOT NULL
                          ORDER BY created ASC LIMIT 1""").fetchone()
        if not row:
            db.commit()
            return None
        try:
            payload=json.loads(row[3])
            if (not isinstance(payload,dict) or not isinstance(payload.get("scenes"),list)
                    or not isinstance(payload.get("brand"),dict)
                    or payload.get("org")!=row[2]):
                raise ValueError("Bad stored render job")
        except (ValueError,TypeError):
            db.execute("""UPDATE montage_jobs SET status='error',phase='failed',
                          error_code='invalid_job_payload',updated=? WHERE id=? AND status='queued'""",
                       (now,row[0]))
            db.commit()
            return None
        token=uuid.uuid4().hex
        db.execute("""UPDATE montage_jobs SET status='running',phase='starting',
                       worker_id=?,lease_token=?,updated=?
                       WHERE id=? AND status='queued'""",(worker_id,token,now,row[0]))
        db.commit()
        return {"id":row[0],"owner":row[1],"organisation":row[2],
                "payload":payload,"lease_token":token}
    except Exception:
        db.rollback()
        raise
    finally:db.close()



def usage_summary(owner, *, path=None, now=None):
    """Owner-scoped actual output accounting, not an invoice or Stripe charge."""
    if not owner:
        return {"completed_outputs":0,"output_seconds":0.0,
                "reserved_seconds_24h":0.0,"daily_limit_seconds":MAX_USER_OUTPUT_SECONDS_DAY}
    now=time.time() if now is None else now
    db=_db(path)
    try:
        settled=db.execute("""SELECT COUNT(*),COALESCE(SUM(output_seconds),0)
            FROM montage_usage_events WHERE owner=?""",(owner,)).fetchone()
        reserved=db.execute("""SELECT COALESCE(SUM(reserved_seconds),0)
            FROM montage_jobs WHERE owner=? AND created>=?""",(owner,now-86400)).fetchone()[0]
        return {"completed_outputs":settled[0],
                "output_seconds":round(settled[1],3),
                "reserved_seconds_24h":round(reserved,3),
                "daily_limit_seconds":MAX_USER_OUTPUT_SECONDS_DAY}
    finally:db.close()
