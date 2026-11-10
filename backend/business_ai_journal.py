"""Durable, bounded paid-AI admission for Clippr Business campaign packs.

Separate SQLite database protects the creator jobs DB. Atomic transaction
claims one provider request per user+content digest, even across Gunicorn
workers. An uncertain outcome is NOT retried or sent to another paid provider.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from business_campaign_engine import (
    generate_campaign, validate_brief, normalize_candidates, base_suggestions,
)

DEFAULT_PATH="/opt/clippr/tmp/business_ai/business_ai_requests.db"

def _connect(path):
    parent=Path(path).parent
    parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=5)
    os.chmod(path,0o600)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS requests(
        user_id TEXT NOT NULL, digest TEXT NOT NULL,
        day TEXT NOT NULL, status TEXT NOT NULL,
        response TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        PRIMARY KEY(user_id,digest)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_business_ai_day ON requests(day,user_id)")
    db.commit()
    return db

def _digest(brief,clips):
    payload=json.dumps({"brief":brief,"clips":clips},sort_keys=True,separators=(",",":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _safe_cap(value,default,maximum):
    try:
        cap=int(value)
        return max(1,min(maximum,cap))
    except (ValueError,TypeError):
        return default

def _admit(path,user_id,digest,now,per_user_limit,global_limit):
    day=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m-%d")
    db=_connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT status,response FROM requests WHERE user_id=? AND digest=?",
                       (user_id,digest)).fetchone()
        if row:
            db.commit()
            return row[0],row[1]
        per_user=db.execute("SELECT COUNT(*) FROM requests WHERE day=? AND user_id=?",
                            (day,user_id)).fetchone()[0]
        overall=db.execute("SELECT COUNT(*) FROM requests WHERE day=?",(day,)).fetchone()[0]
        if per_user>=per_user_limit or overall>=global_limit:
            db.commit()
            return "quota_exhausted",None
        db.execute("INSERT INTO requests(user_id,digest,day,status,created_at,updated_at) VALUES(?,?,?,'pending',?,?)",
                   (user_id,digest,day,now,now))
        db.commit()
        return "claimed",None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def _finish(path,user_id,digest,status,response):
    db=_connect(path)
    try:
        db.execute("UPDATE requests SET status=?,response=?,updated_at=? WHERE user_id=? AND digest=? AND status='pending'",
                   (status,json.dumps(response,separators=(",",":")),time.time(),user_id,digest))
        db.commit()
    finally: db.close()

def guarded_generate(user_id,source_clips,raw_brief,*,path=None,ai_fn=None,now=None,
                     per_user_limit=None,global_limit=None):
    """Return actual campaign output or explicitly-labelled, review-only drafts.

    Never calls a paid AI provider when the journal cannot be opened.
    Existing unknown/pending/failure entries do not cause a second paid call.
    """
    brief=validate_brief(raw_brief)
    clips=normalize_candidates(source_clips)
    if not clips:
        return {"clips":[],"ai":{"status":"no_candidates","request_count":0}}
    fallback=base_suggestions(clips,brief,ai_status="unavailable")
    if not isinstance(user_id,str) or not user_id.strip():
        return {"clips":fallback,"ai":{"status":"auth_required","request_count":0}}
    now=time.time() if now is None else now
    path=path or os.environ.get("CLIPPR_BUSINESS_AI_DB",DEFAULT_PATH)
    per_user_limit=_safe_cap(per_user_limit if per_user_limit is not None
        else os.environ.get("CLIPPR_BUSINESS_AI_DAILY_LIMIT"),10,50)
    global_limit=_safe_cap(global_limit if global_limit is not None
        else os.environ.get("CLIPPR_BUSINESS_AI_GLOBAL_LIMIT"),100,2000)
    key=_digest(brief,clips)
    try:
        state,cached=_admit(path,user_id,key,now,per_user_limit,global_limit)
    except (sqlite3.Error,OSError):
        return {"clips":fallback,"ai":{"status":"journal_unavailable","request_count":0}}
    if state=="accepted":
        try:
            saved=json.loads(cached)
            saved["ai"]={**saved.get("ai",{}),"cached":True,"request_count":0}
            return saved
        except (ValueError,TypeError):
            return {"clips":fallback,"ai":{"status":"cached_response_unavailable","request_count":0}}
    if state!="claimed":
        return {"clips":fallback,"ai":{"status":state,"request_count":0}}
    try:
        kwargs={"use_ai":True}
        if ai_fn is not None:kwargs["ai_fn"]=ai_fn
        result=generate_campaign(source_clips,brief,**kwargs)
        status="accepted" if result.get("ai",{}).get("status")=="ready" else "unknown"
    except Exception as error:
        print("[business-ai-journal] provider failure: "+type(error).__name__,flush=True)
        status="unknown"
        result={"clips":fallback,"ai":{"status":"unavailable","request_count":1}}
    try: _finish(path,user_id,key,status,result)
    except (sqlite3.Error,OSError):
        # A completed provider request with failed journal persistence cannot
        # safely be retried. The DB row remains pending and blocks another call.
        print("[business-ai-journal] failed to persist response",flush=True)
    return result
