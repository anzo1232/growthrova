"""Private, owner-scoped source uploads for Clippr Business.

Dedicated SQLite reservations, outside the creator jobs database. A source must
be HEAD-verified before an authenticated /api/analyse may consume its key.
Do NOT expose these functions to anonymous callers or change creator uploads.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import sqlite3
import threading
import time
import uuid

MIMES = {".mp4": "video/mp4", ".mov": "video/quicktime",
         ".webm": "video/webm", ".m4v": "video/x-m4v"}
MAX_BYTES = 512 * 1024 * 1024
MIN_BYTES = 1024
MAX_SOURCES_PER_DAY = 12
TTL = 48 * 3600
REGISTRY_PATH = "/opt/clippr/tmp/business_sources/sources.db"
_DB_INIT_LOCK = threading.RLock()
ID = re.compile(r"^[a-f0-9]{32}$", re.I)
UUID = re.compile(r"^[a-f0-9-]{36}$", re.I)
KEY = re.compile(r"^business/sources/([a-f0-9-]{36})/([a-f0-9]{32})\.(mp4|mov|webm|m4v)$", re.I)


def validate_file(filename, mime, size):
    if (not isinstance(filename, str) or len(filename) > 180 or len(filename)<3
            or "/" in filename or "\\" in filename
            or any(not c.isprintable() for c in filename)):
        raise ValueError("Choose a valid source file.")
    ext = Path(filename).suffix.lower()
    if ext not in MIMES or mime != MIMES[ext]:
        raise ValueError("Upload MP4, MOV, M4V or WebM video footage.")
    try:
        size = int(size)
    except (ValueError, TypeError):
        raise ValueError("The video size is missing.") from None
    if not (MIN_BYTES <= size <= MAX_BYTES):
        raise ValueError("Video must be between 1KB and 512MB.")
    return ext, size


def _db_once(path):
    dest = Path(path)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(str(dest), timeout=5)
    os.chmod(dest, 0o600)
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS business_sources (
      source_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
      source_key TEXT NOT NULL UNIQUE, client_nonce TEXT NOT NULL,
      filename TEXT NOT NULL, declared_size INTEGER NOT NULL, content_type TEXT NOT NULL,
      status TEXT NOT NULL, created_at REAL NOT NULL, confirmed_at REAL,
      etag TEXT, UNIQUE (user_id, client_nonce)
    )""")
    cols={r[1] for r in db.execute("PRAGMA table_info(business_sources)")}
    if "etag" not in cols:
        db.execute("ALTER TABLE business_sources ADD COLUMN etag TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_biz_src_user ON business_sources(user_id,created_at)")
    db.commit()
    return db


def _db(path):
    # Initial WAL setup must not race another request creating the registry.
    with _DB_INIT_LOCK:
        for attempt in range(4):
            try:
                return _db_once(path)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 3:
                    raise
                time.sleep(.08*(attempt+1))


def reserve_source(owner, organisation, filename, mime, size, nonce, *, path=None, now=None):
    if not owner or not UUID.fullmatch(str(organisation or "")):
        raise ValueError("Choose your business and sign in.")
    if not ID.fullmatch(str(nonce or "")):
        raise ValueError("Upload request identifier is invalid.")
    ext, size = validate_file(filename, mime, size)
    path = path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB", REGISTRY_PATH)
    now = time.time() if now is None else now
    db = _db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT source_id,source_key,organisation_id,declared_size,content_type,status,created_at,filename FROM business_sources WHERE user_id=? AND client_nonce=?",
                              (owner, nonce)).fetchone()
        if existing:
            db.commit()
            if existing[2] != organisation or existing[3] != size or existing[4] != mime or existing[7] != filename:
                raise ValueError("This upload request belongs to different footage.")
            return {**dict(zip(("source_id","source_key","organisation_id","declared_size",
                             "content_type","status","created_at","filename"), existing)), "replayed": True}
        count = db.execute("SELECT COUNT(*) FROM business_sources WHERE user_id=? AND created_at >= ?",
                           (owner, now-86400)).fetchone()[0]
        if count >= MAX_SOURCES_PER_DAY:
            db.commit()
            raise ValueError("Daily source upload limit reached.")
        sid = uuid.uuid4().hex
        key = f"business/sources/{organisation}/{sid}{ext}"
        db.execute("INSERT INTO business_sources(source_id,user_id,organisation_id,source_key,client_nonce,filename,declared_size,content_type,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (sid,owner,organisation,key,nonce,filename,size,mime,"pending",now))
        db.commit()
        return {"source_id":sid,"source_key":key,"organisation_id":organisation,
                "declared_size":size,"content_type":mime,"filename":filename,"status":"pending","created_at":now,"replayed":False}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def source_for_owner(key, owner, *, path=None):
    if not owner or not isinstance(key, str) or not KEY.fullmatch(key):
        return None
    db = _db(path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",REGISTRY_PATH))
    try:
        row = db.execute("SELECT source_id,organisation_id,declared_size,content_type,status,created_at,etag FROM business_sources WHERE source_key=? AND user_id=?",
                         (key,owner)).fetchone()
        if not row:
            return None
        return dict(zip(("source_id","organisation_id","declared_size",
                          "content_type","status","created_at","etag"),row))
    finally: db.close()


def confirm_source(key, owner, actual_size, actual_type, *, path=None, now=None, actual_etag=None):
    path=path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",REGISTRY_PATH)
    record=source_for_owner(key,owner,path=path)
    if not record:
        raise ValueError("Source not found for this account.")
    if record["declared_size"] != int(actual_size or -1) or actual_type != record["content_type"]:
        raise ValueError("Uploaded footage did not match the original file.")
    if record["status"] == "confirmed":
        if record.get("etag") and actual_etag is not None and record["etag"]!=actual_etag:
            raise ValueError("The confirmed source video has changed since approval.")
        return record
    now=time.time() if now is None else now
    if now-record["created_at"] > TTL:
        raise ValueError("The upload reservation has expired.")
    db=_db(path)
    try:
        if actual_etag is not None and (not isinstance(actual_etag,str) or len(actual_etag)>160):
            raise ValueError("Invalid file storage version.")
        db.execute("UPDATE business_sources SET status='confirmed',confirmed_at=?,etag=? WHERE source_key=? AND user_id=? AND status='pending'",
                   (now,actual_etag,key,owner))
        db.commit()
        return {**record,"status":"confirmed","etag":actual_etag}
    finally:db.close()


def may_analyse_source(key, owner, *, path=None):
    record=source_for_owner(key,owner,path=path)
    return bool(record and record["status"]=="confirmed")


def list_sources_for_owner(owner, organisation, *, path=None, limit=20):
    if not owner or not UUID.fullmatch(str(organisation or "")):
        return []
    db=_db(path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",REGISTRY_PATH))
    try:
        rows=db.execute("SELECT source_id,filename,declared_size,status,created_at,client_nonce,content_type FROM business_sources WHERE user_id=? AND organisation_id=? ORDER BY created_at DESC LIMIT ?",
                        (owner,organisation,max(1,min(int(limit),20)))).fetchall()
        return [dict(zip(("source_id","filename","size","status","created_at","client_nonce","content_type"),row)) for row in rows]
    finally:db.close()


def lookup_source_by_id(source_id, owner, *, path=None):
    if not ID.fullmatch(str(source_id or "")) or not owner:
        return None
    db=_db(path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",REGISTRY_PATH))
    try:
        row=db.execute("SELECT source_key,organisation_id,declared_size,status,etag FROM business_sources WHERE source_id=? AND user_id=?",
                       (source_id,owner)).fetchone()
        if not row:return None
        return dict(zip(("source_key","organisation_id","declared_size","status","etag"),row))
    finally:db.close()


class SourceStorageUnavailable(RuntimeError):
    """Remote R2 HEAD could not be verified. Never silently accept footage."""


def verified_source_object(key, owner, storage, bucket, *, path=None):
    """Require the EXACT confirmed R2 ETag before any Business processing.

    Returns False for missing/foreign/unconfirmed/changed sources. Distinguish
    storage outages so the UI can retry status without reuploading footage.
    """
    source=source_for_owner(key,owner,path=path)
    if not source or source["status"]!="confirmed" or not source.get("etag"):
        return False
    if storage is None or not bucket:
        raise SourceStorageUnavailable("R2 is not available")
    try:
        head=storage.head_object(Bucket=bucket,Key=key)
    except Exception as exc:
        raise SourceStorageUnavailable("R2 version verification unavailable") from exc
    size=int(head.get("ContentLength") or 0)
    kind=(head.get("ContentType") or "").split(";",1)[0].lower().strip()
    return (size==source["declared_size"]
            and head.get("ETag")==source["etag"]
            and kind==source["content_type"])
