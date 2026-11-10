"""Durable owner-only Business campaign snapshot store.

Read-only scenes contain no signed URLs, JWTs or source downloads.
UI can be redesigned independently of this stable API.
"""
from __future__ import annotations
import hashlib,json,os,re,sqlite3,time
from pathlib import Path
from threading import RLock
DB_PATH="/opt/clippr/tmp/business_campaigns/campaigns.db"
LOCK=RLock()
VALID_ID=re.compile(r"^[0-9a-f]{32}$")
MAX_SCENES=24
class StoreError(ValueError):pass

def _db(path=None):
    p=Path(path or os.environ.get("CLIPPR_BUSINESS_CAMPAIGN_DB",DB_PATH))
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with LOCK:
        db=sqlite3.connect(str(p),timeout=5)
        os.chmod(p,0o600)
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS business_campaigns(
          id TEXT PRIMARY KEY,owner TEXT NOT NULL,organisation TEXT NOT NULL,
          name TEXT NOT NULL,goal TEXT NOT NULL,brand_id TEXT,
          scenes_json TEXT NOT NULL,notes TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1,created REAL NOT NULL,
          updated REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_campaign_owner ON business_campaigns(owner,organisation,updated)")
        db.commit();return db

def _scenes(rows):
    if not isinstance(rows,list) or len(rows)>MAX_SCENES:
        raise StoreError("Campaign has too many scenes")
    cleaned=[]
    for scene in rows:
        if not isinstance(scene,dict):raise StoreError("Invalid scene")
        sid=scene.get("source_id")
        start=scene.get("start_s")
        end=scene.get("end_s")
        try: start,end=float(start),float(end)
        except (ValueError,TypeError):raise StoreError("Invalid timing") from None
        import math
        if not isinstance(sid,str) or not VALID_ID.fullmatch(sid) or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end or end-start>300:
            raise StoreError("Invalid campaign scene")
        cleaned.append({"source_id":sid,"start_s":start,"end_s":end,
                        "review_status":"approved" if scene.get("review_status")=="approved" else "draft",
                        "note":str(scene.get("note") or "")[:320]})
    return cleaned

def save(owner,org,name,goal,brand_id,scenes,notes="",*,campaign_id=None,revision=None,path=None,now=None):
    if not owner or not org:raise StoreError("Owner and organisation required")
    if not isinstance(name,str) or not 2<=len(name.strip())<=100:raise StoreError("Campaign name required")
    if goal not in ("awareness","enquiries","bookings","education","offers"):raise StoreError("Invalid campaign objective")
    if brand_id is not None and not isinstance(brand_id,str):raise StoreError("Invalid Brand Kit")
    if not isinstance(notes,str) or len(notes)>1500:raise StoreError("Campaign notes too long")
    chosen=_scenes(scenes)
    now=time.time() if now is None else now
    import uuid
    cid=campaign_id or uuid.uuid4().hex
    if not VALID_ID.fullmatch(cid):raise StoreError("Invalid campaign identifier")
    db=_db(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("SELECT owner,organisation,revision FROM business_campaigns WHERE id=?",(cid,)).fetchone()
        if old:
            if old[0]!=owner or old[1]!=org:raise StoreError("Campaign not found")
            if revision is None or int(revision)!=old[2]:raise StoreError("Campaign changed. Refresh before saving.")
            new_revision=old[2]+1
            db.execute("""UPDATE business_campaigns SET name=?,goal=?,brand_id=?,scenes_json=?,notes=?,revision=?,updated=?
                          WHERE id=? AND owner=?""",(name.strip(),goal,brand_id,json.dumps(chosen),notes,new_revision,now,cid,owner))
        else:
            if campaign_id:raise StoreError("Campaign not found")
            count=db.execute("SELECT count(*) FROM business_campaigns WHERE owner=? AND organisation=?",(owner,org)).fetchone()[0]
            if count>=100:raise StoreError("Campaign limit reached")
            new_revision=1
            db.execute("INSERT INTO business_campaigns(id,owner,organisation,name,goal,brand_id,scenes_json,notes,revision,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (cid,owner,org,name.strip(),goal,brand_id,json.dumps(chosen),notes,1,now,now))
        db.commit()
        return {"id":cid,"revision":new_revision,"updated":now}
    except Exception:
        db.rollback();raise
    finally:db.close()

def get(owner,campaign_id,*,path=None):
    if not owner or not VALID_ID.fullmatch(str(campaign_id)):return None
    db=_db(path)
    try:
        row=db.execute("SELECT id,organisation,name,goal,brand_id,scenes_json,notes,revision,created,updated FROM business_campaigns WHERE id=? AND owner=?",(campaign_id,owner)).fetchone()
        if not row:return None
        fields=("id","organisation_id","name","goal","brand_id","scenes","notes","revision","created","updated")
        payload=dict(zip(fields,row))
        payload["scenes"]=json.loads(payload["scenes"])
        return payload
    finally:db.close()

def list_for(owner,org,*,path=None):
    if not owner or not org:return []
    db=_db(path)
    try:
        rows=db.execute("SELECT id,name,goal,brand_id,revision,updated FROM business_campaigns WHERE owner=? AND organisation=? ORDER BY updated DESC LIMIT 100",(owner,org)).fetchall()
        return [dict(zip(("id","name","goal","brand_id","revision","updated"),r)) for r in rows]
    finally:db.close()

def delete(owner,org,campaign_id,*,path=None):
    db=_db(path)
    try:
        result=db.execute("DELETE FROM business_campaigns WHERE id=? AND owner=? AND organisation=?",(campaign_id,owner,org))
        db.commit();return result.rowcount==1
    finally:db.close()
