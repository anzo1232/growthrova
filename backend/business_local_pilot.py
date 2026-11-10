"""Actual FFmpeg local pilot for Clippr Business — sandbox only.

This is NOT the production Business API: no real Supabase/R2/Stripe, no
automatic billing, no production customer data. Binds only to 127.0.0.1.
Connects the production scene-discovery and montage COMPOSITION functions to
real local video files for safe end-to-end testing with user-approved footage.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit,unquote
from business_visual import scan_visual_scenes
from business_spoken_clips import spoken_windows
from business_website_analysis import extract_website,expand_business_audit,WebsiteSafetyError
from business_montage import build_montage
import business_marketing_drafts as marketing_drafts
import business_runway as runway
import business_agency_pack_jobs as packs
import business_post_approvals as approvals
import business_cinematic_video as cinematic
import business_creative_review as creative_review
import business_website_media as website_media
import business_hero_history as hero_history
import business_social_video_plan as social_video
import business_restaurant_video_paid_test as restaurant_paid_video
import business_reel_workbench as reel_workbench
import business_reel_provider_bridge as reel_bridge
import business_reel_semantic_bridge as reel_semantic
import business_reel_owner_media as reel_owner_media
import business_reel_brand_lock as reel_brand_lock
import business_reel_captions as reel_captions
import business_reel_caption_exports as reel_caption_exports

HOST="127.0.0.1"
PORT=int(os.environ.get("CLIPPR_LOCAL_PILOT_PORT","4192"))
BASE=Path(os.environ.get("CLIPPR_LOCAL_PILOT_ROOT",str(Path.home()/".clippr-business-local-pilot"))).resolve()
MAX_VIDEO=170*1024*1024
MAX_TOTAL_STORAGE=650*1024*1024
MAX_SOURCES=12
VALID_ORIGINS=frozenset({"http://localhost:4185","http://127.0.0.1:4185",
 "http://localhost:4218","http://127.0.0.1:4218"})
ALLOWED_TYPES={"video/mp4":".mp4","video/quicktime":".mov","video/webm":".webm"}
LOCK=threading.RLock()
EXEC=ThreadPoolExecutor(max_workers=1,thread_name_prefix="clippr-local-pilot")
MEDIA_SIGNING_SECRET=secrets.token_bytes(32)
MEDIA_TTL_SECONDS=15*60

def media_ticket(source_id, *, now=None):
    if not valid_id(source_id):
        raise ValueError("Invalid video identifier")
    expiry=int(time.time() if now is None else now)+MEDIA_TTL_SECONDS
    message=f"{source_id}:{expiry}".encode()
    sig=hmac.new(MEDIA_SIGNING_SECRET,message,hashlib.sha256).hexdigest()
    return {"url":f"/api/pilot/stream/{source_id}?expires={expiry}&sig={sig}",
            "expires":expiry}

def verify_media_ticket(source_id, query, *, now=None):
    if not valid_id(source_id):return False
    fields=parse_qs(query,keep_blank_values=True)
    if len(fields.get("expires",[]))!=1 or len(fields.get("sig",[]))!=1:
        return False
    try:expiry=int(fields["expires"][0])
    except (TypeError,ValueError,OverflowError):return False
    clock=int(time.time() if now is None else now)
    if expiry<clock or expiry>clock+MEDIA_TTL_SECONDS:
        return False
    supplied=fields["sig"][0]
    if len(supplied)!=64:return False
    expected=hmac.new(MEDIA_SIGNING_SECRET,
        f"{source_id}:{expiry}".encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,supplied)

def parse_media_range(value,total):
    """A single HTTP byte range. Return (start,end), or raise ValueError."""
    if not isinstance(total,int) or total<1:
        raise ValueError("Invalid media size")
    if not value:return (0,total-1)
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("Only one byte range supported")
    spec=value[6:]
    if spec.count("-")!=1:raise ValueError("Invalid range")
    a,b=spec.split("-",1)
    if not a and not b:raise ValueError("Missing range")
    if not a:
        try:suffix=int(b)
        except ValueError:raise ValueError("Invalid suffix") from None
        if suffix<=0:raise ValueError("Empty suffix")
        return (max(0,total-suffix),total-1)
    try:start=int(a);end=int(b) if b else total-1
    except ValueError:raise ValueError("Invalid range") from None
    if start>=total or start<0 or end<start:
        raise ValueError("Unsatisfiable range")
    return (start,min(end,total-1))

def hero_photo_crop(photo):
    """Planning advice only; no deceptive crop preview is considered approved."""
    width=photo["width"];height=photo["height"]
    if width<=0 or height<=0:raise ValueError("Invalid photo dimensions")
    outputs={}
    for name,ratio,target in (("instagram4x5",4/5,(1080,1350)),("tiktok9x16",9/16,(1080,1920))):
        actual=width/height
        kept=min(actual/ratio,ratio/actual)
        scale=max(target[0]/width,target[1]/height)
        outputs[name]={"sourceDimensions":[width,height],"targetDimensions":list(target),
            "imageAreaRetainedPercent":round(kept*100,1),"upscaleRequired":scale>1.001,
            "notice":"Review face, product and text cropping on the mobile preview before use",
            "suitableForAutomaticApproval":False}
    return outputs

def db():
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
    (BASE/"files").mkdir(mode=0o700,exist_ok=True)
    (BASE/"exports").mkdir(mode=0o700,exist_ok=True)
    path=BASE/"pilot.db"
    con=sqlite3.connect(str(path),timeout=6)
    os.chmod(path,0o600)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA busy_timeout=6000")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
      CREATE TABLE IF NOT EXISTS sources(
        id TEXT PRIMARY KEY,filename TEXT NOT NULL,mime TEXT NOT NULL,
        bytes INTEGER NOT NULL, status TEXT NOT NULL,
        result_json TEXT,created REAL NOT NULL,updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS campaigns(
        id TEXT PRIMARY KEY,revision INTEGER NOT NULL,name TEXT NOT NULL,
        brand_name TEXT NOT NULL,goal TEXT NOT NULL,
        scenes_json TEXT NOT NULL,updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS renders(
        id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,
        fingerprint TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,output_seconds REAL NOT NULL,
        error TEXT,created REAL NOT NULL,updated REAL NOT NULL);
    """)
    marketing_drafts.initialise(con)
    website_media.initialise(con)
    runway.initialise(con)
    packs.initialise(con)
    approvals.initialise(con)
    cinematic.initialise(con)
    hero_history.initialise(con)
    social_video.initialise(con)
    restaurant_paid_video.initialise(con)
    reel_workbench.initialise(con)
    reel_bridge.initialise(con)
    reel_semantic.initialise(con)
    con.commit()
    return con

@contextmanager
def session():
    con=db()
    try:
        with con:
            yield con
    finally:
        con.close()

def row(con,table,id):
    value=con.execute("SELECT * FROM "+table+" WHERE id=?",(id,)).fetchone()
    return dict(value) if value else None

def valid_id(value):
    return isinstance(value,str) and len(value)==32 and all(c in "0123456789abcdef" for c in value)

def scan_source(id):
    try:
        with LOCK,session() as con:
            old=row(con,"sources",id)
            if not old or old["status"]!="queued":return
            con.execute("UPDATE sources SET status='scanning',updated=? WHERE id=?",(time.time(),id))
        source=BASE/"files"/(id+ALLOWED_TYPES[old["mime"]])
        result=scan_visual_scenes(source)
        scenes=result.get("scenes") or []
        if len(scenes)<2 and result.get("duration_s",0)>=8:
            duration=float(result["duration_s"])
            middle=round(duration/2,2)
            scenes=[
                {"timestamp_start":0,"timestamp_end":middle,"title":"Review window 1",
                 "reason":"First half of the original footage; review before approving.",
                 "review_required":True,"visual_only":True},
                {"timestamp_start":middle,"timestamp_end":round(duration,2),"title":"Review window 2",
                 "reason":"Second half of the original footage; review before approving.",
                 "review_required":True,"visual_only":True}
            ]
            result["scenes"]=scenes
        with LOCK,session() as con:
            con.execute("UPDATE sources SET status='done',result_json=?,updated=? WHERE id=? AND status='scanning'",
                        (json.dumps(result),time.time(),id))
    except Exception as exc:
        print("LOCAL_PILOT_SCAN_ERROR",type(exc).__name__,flush=True)
        with LOCK,session() as con:
            con.execute("UPDATE sources SET status='error',updated=? WHERE id=? AND status IN ('queued','scanning')",
                        (time.time(),id))

def compose(id,windows,brand):
    try:
        with LOCK,session() as con:
            current=row(con,"renders",id)
            if not current or current["status"]!="queued":return
            con.execute("UPDATE renders SET status='rendering',updated=? WHERE id=?",(time.time(),id))
        result=build_montage(windows,BASE/"exports"/(id+".mp4"),brand={
            "name":brand,"primary_color":"#18271d","secondary_color":"#ffffff",
            "font_style":"modern","default_cta":""
        },width=360,height=640)
        with LOCK,session() as con:
            con.execute("UPDATE renders SET status='done',output_seconds=?,updated=? WHERE id=? AND status='rendering'",
                        (result["duration_s"],time.time(),id))
    except Exception as exc:
        print("LOCAL_PILOT_RENDER_ERROR",type(exc).__name__,flush=True)
        with LOCK,session() as con:
            con.execute("UPDATE renders SET status='error',error=?,updated=? WHERE id=?",
                        ("Rendering failed; original footage is unchanged.",time.time(),id))

def approved_windows(campaign):
    try:scenes=json.loads(campaign["scenes_json"])
    except Exception:raise ValueError("Invalid saved campaign")
    if not 2<=len(scenes)<=6:raise ValueError("Approve two to six scenes")
    windows=[]
    total=0.
    with session() as con:
        for item in scenes:
            if not isinstance(item,dict) or not valid_id(item.get("source_id")) or item.get("review_status")!="approved":
                raise ValueError("All montage scenes must be explicitly approved")
            src=row(con,"sources",item["source_id"])
            if not src or src["status"]!="done":raise ValueError("Source video is not ready")
            try:a=float(item["start_s"]);b=float(item["end_s"])
            except (ValueError,TypeError,KeyError):raise ValueError("Invalid scene timing")
            if not (math.isfinite(a) and math.isfinite(b) and 0<=a<b and 3<=b-a<=30):
                raise ValueError("Scene length must be 3–30 seconds")
            actual=json.loads(src["result_json"]).get("scenes") or []
            if not any(abs(a-float(x["timestamp_start"]))<.02 and abs(b-float(x["timestamp_end"]))<.02 for x in actual):
                raise ValueError("Approved scene does not match analysed footage")
            focus=item.get("focus_x",0.5)
            if isinstance(focus,bool) or not isinstance(focus,(float,int)) or not math.isfinite(focus) or not 0<=focus<=1:
                raise ValueError("Invalid scene framing position")
            total+=b-a
            windows.append({"focus_x":float(focus),"path":str(BASE/"files"/(src["id"]+ALLOWED_TYPES[src["mime"]])),
                            "start_s":a,"end_s":b})
    if total>120:raise ValueError("Montage exceeds two minutes")
    return windows,total

def render_agency_pack_job(jid):
    """Build only revision-bound, verified current images; no paid provider call."""
    try:
        with session() as con:
            packs.render_pack(con,jid,BASE)
    except packs.PackError as exc:
        # Replacing a document while its previous export is rendering is an
        # expected stale-job outcome, not a server failure or permission to retry.
        if exc.code not in ("revision_conflict","source_changed"):
            print("LOCAL_AGENCY_KIT_RENDER_ERROR",exc.code,flush=True)
    except Exception as exc:
        print("LOCAL_AGENCY_KIT_RENDER_ERROR",type(exc).__name__,flush=True)

def annotate_runway_job(con,job):
    if job is None:return job
    reviews={r["assetId"]:r for r in creative_review.list_reviews(con,job["draftId"])}
    match=reviews.get(job["id"])
    if match and match["assetType"]=="image":
        return {**job,"editorialStatus":"rejected","reviewReason":match["reason"],"reviewNote":match["note"],"approved":False}
    return {**job,"editorialStatus":"needs_review"}

def public_source(row):
    return {"id":row["id"],"filename":row["filename"],"status":row["status"],
            "size":row["bytes"],"created":row["created"],
            "result":json.loads(row["result_json"]) if row["result_json"] else None}

def public_campaign(row):
    return {"id":row["id"],"revision":row["revision"],"name":row["name"],
            "brand_name":row["brand_name"],"goal":row["goal"],
            "scenes":json.loads(row["scenes_json"]),"updated":row["updated"]}

def public_render(record):
    result=dict(record)
    out=BASE/"exports"/(result["id"]+".mp4")
    # A finished record is not proof that its MP4 is still on disk.
    status=result["status"]
    if status=="done" and (not out.is_file() or out.stat().st_size<1500):
        status="unavailable"
    return {"id":result["id"],"campaign_id":result["campaign_id"],
            "campaign_name":result.get("campaign_name") or "Saved campaign",
            "revision":result["revision"],"status":status,
            "output_seconds":result["output_seconds"] if status=="done" else None,
            "error":("Local render file is missing; check this job before retrying."
                     if status=="unavailable" else result.get("error")),
            "created":result["created"],"updated":result["updated"]}


class Handler(BaseHTTPRequestHandler):
    server_version="ClipprLocalPilot/0.1"
    def log_message(self,format,*args):pass
    def _origin(self):return self.headers.get("Origin","")
    def send(self,status,value,*,typ="application/json"):
        payload=json.dumps(value).encode("utf8") if typ=="application/json" else value
        self.send_response(status)
        self.send_header("Content-Type",typ)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        if self._origin() in VALID_ORIGINS:
            self.send_header("Access-Control-Allow-Origin",self._origin())
            self.send_header("Vary","Origin")
        self.end_headers()
        self.wfile.write(payload)
    def authorised(self):
        if self._origin() not in VALID_ORIGINS or self.headers.get("X-Clippr-Pilot")!="local-only":
            self.send(403,{"code":"forbidden","error":"Local pilot is accessible from the Clippr development UI only."})
            return False
        return True
    def body_json(self, max_bytes=8192):
        size=int(self.headers.get("Content-Length","0"))
        if size<1 or size>max_bytes:raise ValueError("Invalid JSON body")
        return json.loads(self.rfile.read(size))
    def do_OPTIONS(self):
        if self._origin() not in VALID_ORIGINS:
            self.send(403,{"code":"forbidden"});return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",self._origin())
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type,X-Clippr-Pilot,X-Clippr-Filename")
        self.send_header("Access-Control-Max-Age","300")
        self.end_headers()
    def stream_media(self,*,head_only=False):
        parsed=urlsplit(self.path)
        parts=parsed.path.strip("/").split("/")
        if len(parts)!=4 or parts[:3]!=["api","pilot","stream"] or not valid_id(parts[3]):
            self.send(404,{"code":"not_found"});return
        # The <video> element cannot send a custom request header. Instead,
        # a short-lived signed URL is issued by the protected JSON endpoint.
        if self._origin() not in VALID_ORIGINS or not verify_media_ticket(parts[3],parsed.query):
            self.send(403,{"code":"media_link_expired","error":"Reopen this scene to renew its local preview link."});return
        with session() as con:src=row(con,"sources",parts[3])
        if not src:
            self.send(404,{"code":"not_found"});return
        target=BASE/"files"/(src["id"]+ALLOWED_TYPES[src["mime"]])
        if not target.is_file() or target.stat().st_size!=src["bytes"]:
            self.send(404,{"code":"source_missing"});return
        total=target.stat().st_size
        requested=self.headers.get("Range","")
        try:start,end=parse_media_range(requested,total)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range",f"bytes */{total}")
            self.send_header("Cache-Control","no-store")
            self.send_header("Access-Control-Allow-Origin",self._origin())
            self.send_header("Access-Control-Expose-Headers","Content-Range,Accept-Ranges,Content-Length")
            self.end_headers()
            return
        status=206 if requested else 200
        length=end-start+1
        self.send_response(status)
        self.send_header("Content-Type",src["mime"])
        self.send_header("Content-Length",str(length))
        self.send_header("Accept-Ranges","bytes")
        if requested:self.send_header("Content-Range",f"bytes {start}-{end}/{total}")
        self.send_header("Content-Disposition",'inline; filename="clippr-local-preview"')
        self.send_header("Cache-Control","private,no-store")
        self.send_header("Access-Control-Allow-Origin",self._origin())
        self.send_header("Access-Control-Expose-Headers","Content-Range,Accept-Ranges,Content-Length")
        self.send_header("Vary","Origin")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.end_headers()
        if head_only:return
        try:
            with target.open("rb") as media:
                media.seek(start)
                remaining=length
                while remaining>0:
                    block=media.read(min(256*1024,remaining))
                    if not block:break
                    self.wfile.write(block)
                    remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError):
            pass  # Browser deliberately cancelled a seeked range.

    def do_HEAD(self):
        self.stream_media(head_only=True)

    def do_GET(self):
        if urlsplit(self.path).path.startswith("/api/pilot/stream/"):
            self.stream_media();return
        if not self.authorised():return
        parts=urlsplit(self.path).path.strip("/").split("/")
        try:
            if len(parts)==5 and parts[:3]==["api","pilot","website-photos"] and parts[4]=="image":
                try:
                    did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                    with session() as con:path=website_media.photo_path(con,did,parts[3],BASE)
                    self.send(200,path.read_bytes(),typ="image/jpeg");return
                except (website_media.MediaError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","premium-image-proposal"]:
                try:
                    did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                    with session() as con:
                        saved=marketing_drafts.read_draft(con,runway._id(did))
                        recipe=runway._recipe(saved["document"],"creative-1")
                        existing=con.execute("SELECT status FROM runway_image_jobs WHERE draft_id=? AND creative_id='creative-1'",(did,)).fetchall()
                        shortlist=saved["document"].get("editorialShortlist") or {}
                    self.send(200,{
                        "draftId":did,"revision":saved["revision"],
                        "estimatedCredits":runway.IMAGE_CREDITS,
                        "model":recipe["model"],"ratio":recipe["ratio"],"quality":recipe["quality"],
                        "outputCount":recipe["outputCount"],"exactPrompt":recipe["promptText"],
                        "sourceDirections":[c.get("hook","") for c in shortlist.get("candidates",[]) if isinstance(c,dict)][:3],
                        "existingPaidAttemptCount":len(existing),
                        "automaticSpendApproved":False,"retryAllowed":False,
                        "published":False,"imageGenerated":False,
                        "nextStep":"Specific owner approval required for one image attempt and exact 20-credit ceiling."})
                    return
                except (runway.RunwayError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","reel-vision-quotes"]:
                try:
                    if len(parts)==5 and parts[3]:
                        with session() as con:
                            proposal=reel_semantic.prepare(con,parts[3],parts[4])
                        self.send(200,{"quote":proposal});return
                    self.send(404,{"code":"not_found"});return
                except (reel_semantic.SemanticError,reel_workbench.ReelError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","reel-shot-quotes"]:
                try:
                    if len(parts)==5 and parts[3]:
                        with session() as con:
                            info=reel_bridge.quote(con,parts[3],parts[4])
                        self.send(200,{"quote":info});return
                    self.send(404,{"code":"not_found"});return
                except (reel_bridge.BridgeError,reel_workbench.ReelError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","reel-workbench"]:
                try:
                    with session() as con:
                        if len(parts)==3:
                            did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                            info=reel_workbench.read_for_draft(con,did)
                            self.send(200,{"project":info});return
                        if len(parts)==4:
                            self.send(200,{"project":reel_workbench.read(con,parts[3])});return
                        if len(parts)==6 and parts[4] in ("previews","captions"):
                            expected=parse_qs(urlsplit(self.path).query).get("contentSha256",[None])[0]
                            if expected is not None:
                                state=reel_workbench.read(con,parts[3])
                                edit=next((e for e in state["edits"] if e["variant"]==parts[5]),None)
                                if not edit or edit["contentSha256"]!=expected:
                                    raise reel_workbench.ReelError('Refresh to load the current edit and captions','stale_review',409)
                        if len(parts)==6 and parts[4]=="previews":
                            preview=reel_caption_exports.preview_file(con,parts[3],parts[5],BASE)
                            self.send(200,preview.read_bytes(),typ="video/mp4");return
                        if len(parts)==6 and parts[4]=="deliveries":
                            query=parse_qs(urlsplit(self.path).query)
                            delivery=reel_caption_exports.approved_file(con,parts[3],parts[5],BASE,
                                expected_content_sha256=query.get("contentSha256",[None])[0],
                                expected_review_set_sha256=query.get("reviewSetSha256",[None])[0])
                            self.send(200,delivery.read_bytes(),typ="video/mp4");return
                        if len(parts)==6 and parts[4]=="captions":
                            caption=reel_captions.file_for(con,parts[3],parts[5],BASE)
                            self.send(200,caption.read_bytes(),typ="text/vtt");return
                    self.send(404,{"code":"not_found"});return
                except (reel_workbench.ReelError,reel_captions.CaptionError,reel_caption_exports.CaptionExportError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","social-video-proposals"]:
                try:
                    did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                    with session() as con:items=social_video.list_plans(con,did)
                    self.send(200,{"proposals":items,"quote":social_video.current_quote()});return
                except (social_video.VideoPlanError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","hero-creative-history"]:
                try:
                    did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                    with session() as con:
                        result=hero_history.read(con,did)
                        photos=website_media.list_photos(con,did)
                        result["photos"]=[{**photo,"cropping":hero_photo_crop(photo)} for photo in photos]
                    self.send(200,result);return
                except (hero_history.HeroHistoryError,marketing_drafts.MarketingDraftError,website_media.MediaError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","website-photos"]:
                try:
                    did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                    with session() as con:photos=website_media.list_photos(con,did)
                    self.send(200,{"photos":photos});return
                except (website_media.MediaError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","post-approvals"]:
                try:
                    query=parse_qs(urlsplit(self.path).query)
                    did=query.get("draftId",[""])[0]
                    kit_id=query.get("kitId",[""])[0]
                    with session() as con:items=approvals.list_approvals(con,did,kit_id,BASE)
                    self.send(200,{"approvals":items});return
                except (approvals.ApprovalError,packs.PackError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","agency-packs"]:
                try:
                    if parts==["api","pilot","agency-packs"]:
                        did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                        with session() as con:items=packs.latest_pack(con,did,BASE)
                        self.send(200,{"kits":items});return
                    if len(parts)>=4:
                        kit_id=parts[3]
                        with session() as con:
                            if len(parts)==4:
                                self.send(200,packs.read_pack(con,kit_id,BASE));return
                            name=("campaign-kit.zip" if len(parts)==5 and parts[4]=="download" else
                                  parts[5] if len(parts)==6 and parts[4]=="assets" else None)
                            path=packs.asset_path(con,kit_id,BASE,name)
                        if name=="campaign-kit.zip":kind="application/zip"
                        elif name.endswith(".png"):kind="image/png"
                        elif name.endswith(".mp4"):kind="video/mp4"
                        elif name.endswith(".md"):kind="text/markdown; charset=utf-8"
                        elif name.endswith(".csv"):kind="text/csv; charset=utf-8"
                        elif name.endswith(".html"):kind="text/html; charset=utf-8"
                        else:kind="application/json"
                        if kind=="application/json":
                            self.send(200,json.loads(path.read_text(encoding="utf8")));return
                        self.send(200,path.read_bytes(),typ=kind);return
                    self.send(404,{"code":"not_found"});return
                except (packs.PackError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","runway"]:
                try:
                    if parts==["api","pilot","runway","config"]:
                        try:cap=int(os.environ.get("CLIPPR_BUSINESS_RUNWAY_TEST_CAP","0"))
                        except ValueError:cap=0
                        self.send(200,{"provider":"Runway developer API","enabled":20<=cap<=1000,"imageCredits":20,"retryAllowed":False});return
                    if parts==["api","pilot","runway","jobs"]:
                        did=parse_qs(urlsplit(self.path).query).get("draftId",[""])[0]
                        with session() as con:jobs=[annotate_runway_job(con,job) for job in runway.list_jobs(con,did)]
                        self.send(200,{"jobs":jobs});return
                    if len(parts) in (5,6) and parts[3]=="jobs":
                        jid=parts[4]
                        if len(parts)==6 and parts[5]=="image":
                            with session() as con:job=annotate_runway_job(con,runway.public_job(runway.get_job(con,jid)))
                            path=BASE/"generated"/(jid+".png")
                            if job.get("editorialStatus")=="rejected":
                                self.send(403,{"code":"rejected_creative","error":"This image was rejected during review."});return
                            if job["status"]!="completed" or path.is_symlink() or not path.is_file():
                                self.send(404,{"code":"asset_not_ready"});return
                            data=path.read_bytes()
                            if len(data)>runway.MAX_IMAGE_BYTES or hashlib.sha256(data).hexdigest()!=job["asset"]["sha256"]:
                                self.send(409,{"code":"asset_integrity_changed"});return
                            self.send(200,data,typ="image/png");return
                        if len(parts)==5:
                            with session() as con:job=annotate_runway_job(con,runway.refresh_job(con,jid,BASE))
                            self.send(200,job);return
                    self.send(404,{"code":"not_found"});return
                except (runway.RunwayError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","marketing-drafts"]:
                try:
                    with session() as con:
                        result=({"drafts":marketing_drafts.list_drafts(con)} if len(parts)==3
                                else marketing_drafts.read_draft(con,parts[3]) if len(parts)==4 else None)
                    if result is None:self.send(404,{"code":"not_found"});return
                    self.send(200,result)
                except marketing_drafts.MarketingDraftError as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                return
            if parts==["api","pilot","health"]:
                self.send(200,{"ready":True,"mode":"loopback_only","real_ffmpeg":True,
                    "external_services":False,"billing":False,"environment":"LOCAL PILOT"});return
            if parts==["api","pilot","sources"]:
                with session() as con:
                    entries=con.execute("SELECT * FROM sources ORDER BY created DESC LIMIT 20").fetchall()
                self.send(200,{"sources":[public_source(x) for x in entries]});return
            if len(parts)==4 and parts[:3]==["api","pilot","sources"] and valid_id(parts[3]):
                with session() as con:x=row(con,"sources",parts[3])
                if not x:self.send(404,{"code":"not_found"});return
                self.send(200,public_source(x));return
            if len(parts)==5 and parts[:3]==["api","pilot","sources"] and parts[4]=="playback" and valid_id(parts[3]):
                with session() as con:src=row(con,"sources",parts[3])
                if not src or src["status"] not in ("done","queued","scanning"):
                    self.send(404,{"code":"not_found"});return
                target=BASE/"files"/(src["id"]+ALLOWED_TYPES[src["mime"]])
                if not target.is_file() or target.stat().st_size!=src["bytes"]:
                    self.send(409,{"code":"source_missing","error":"The original local video is no longer available."});return
                self.send(200,media_ticket(src["id"]));return
            if parts==["api","pilot","campaigns"]:
                with session() as con:
                    items=con.execute("SELECT * FROM campaigns ORDER BY updated DESC LIMIT 30").fetchall()
                self.send(200,{"campaigns":[public_campaign(x) for x in items]});return
            if parts==["api","pilot","renders"]:
                with session() as con:
                    records=con.execute("""SELECT r.*, c.name AS campaign_name
                         FROM renders r LEFT JOIN campaigns c ON c.id=r.campaign_id
                         ORDER BY r.created DESC LIMIT 30""").fetchall()
                self.send(200,{"renders":[public_render(x) for x in records]});return
            if len(parts)==4 and parts[:3]==["api","pilot","renders"] and valid_id(parts[3]):
                with session() as con:x=row(con,"renders",parts[3])
                if not x:self.send(404,{"code":"not_found"});return
                result=public_render(x)
                result["url"]="/api/pilot/download/"+x["id"] if result["status"]=="done" else None
                self.send(200,result);return
            if len(parts)==4 and parts[:3]==["api","pilot","download"] and valid_id(parts[3]):
                with session() as con:x=row(con,"renders",parts[3])
                target=BASE/"exports"/(parts[3]+".mp4")
                if not x:
                    self.send(404,{"code":"not_found"});return
                if public_render(x)["status"]!="done":
                    self.send(409,{"code":"render_unavailable",
                        "error":"The export is not available. Review the render status before trying again."});return
                size=target.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type","video/mp4")
                self.send_header("Content-Length",str(size))
                self.send_header("Content-Disposition",'attachment; filename="clippr-business-local-test.mp4"')
                self.send_header("Cache-Control","no-store")
                if self._origin() in VALID_ORIGINS:self.send_header("Access-Control-Allow-Origin",self._origin())
                self.end_headers()
                with target.open("rb") as f:
                    while chunk:=f.read(256*1024):self.wfile.write(chunk)
                return
            self.send(404,{"code":"unknown_route"})
        except Exception as exc:
            print("LOCAL_PILOT_READ_ERROR",type(exc).__name__,flush=True)
            self.send(503,{"code":"pilot_unavailable","error":"Local processing status temporarily unavailable."})
    def do_POST(self):
        if not self.authorised():return
        parts=urlsplit(self.path).path.strip("/").split("/")
        try:
            if parts[:3]==["api","pilot","reel-shot-quotes"]:
                try:
                    if len(parts)==6 and parts[5]=="reconcile":
                        body=self.body_json(max_bytes=256)
                        if body!={}:
                            raise reel_bridge.BridgeError("Only existing shot status may be checked","invalid_request",400)
                        with session() as con:
                            result=reel_bridge.reconcile_existing(con,parts[3],parts[4],BASE)
                        self.send(200,result);return
                    self.send(404,{"code":"not_found"});return
                except (reel_bridge.BridgeError,reel_workbench.ReelError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts[:3]==["api","pilot","reel-workbench"]:
                try:
                    maxbody=3000000 if len(parts)==5 and parts[4]=='brand' else 12000
                    body=self.body_json(max_bytes=maxbody)
                    if not isinstance(body,dict):raise reel_workbench.ReelError('Invalid Reel request','invalid_request',400)
                    # Local rendition/sidecar filenames are immutable. Serialise
                    # mutations so two browser tabs cannot reserve the same version.
                    with LOCK,session() as con:
                        if len(parts)==3:
                            if set(body)!={"draftId","expectedRevision"}:
                                raise reel_workbench.ReelError('Exact saved draft and revision required','invalid_request',400)
                            result=reel_workbench.create(con,body["draftId"],body["expectedRevision"])
                        elif len(parts)==5 and parts[4]=="edits":
                            if body!={}:raise reel_workbench.ReelError('Cannot request new paid generations from the edit control','invalid_request',400)
                            result=reel_workbench.prepare_edits(con,parts[3],BASE)
                        elif len(parts)==5 and parts[4]=="endcard":
                            if set(body)!={"name","cta","contactUrl","ownerConfirmed"}:
                                raise reel_workbench.ReelError("Confirm the actual business and its contact destination","invalid_request",400)
                            result=reel_workbench.prepare_local_endcard(con,parts[3],BASE,
                                name=body["name"],cta=body["cta"],contact_url=body["contactUrl"],
                                owner_confirmed=body["ownerConfirmed"])
                        elif len(parts)==5 and parts[4]=="owner-video":
                            if set(body)!={"slot","sourceId","rightsNote","ownerConfirmed"}:
                                raise reel_workbench.ReelError('Source, slot and owner media rights required','invalid_request',400)
                            reel_owner_media.select(con,parts[3],body["slot"],body["sourceId"],BASE,
                                owner_confirmed=body["ownerConfirmed"],rights_note=body["rightsNote"])
                            result=reel_workbench.read(con,parts[3])
                        elif len(parts)==5 and parts[4]=="owner-photo":
                            if set(body)!={"slot","photoId","ownerConfirmed"}:
                                raise reel_workbench.ReelError('Choose real photo and reconfirm rights','invalid_request',400)
                            reel_owner_media.stage_approved_photo(con,parts[3],body["slot"],body["photoId"],BASE,
                                owner_confirmed=body["ownerConfirmed"])
                            result=reel_workbench.read(con,parts[3])
                        elif len(parts)==5 and parts[4]=="brand":
                            expected={"brandName","primary","accent","contactUrl","style",
                                "mime","logoBase64","ownerAttestation","ownerConfirmed"}
                            if set(body)!=expected:
                                raise reel_workbench.ReelError('Exact owner brand kit and source required','invalid_request',400)
                            reel_brand_lock.lock_uploaded(con,parts[3],BASE,
                                brand_name=body["brandName"],primary=body["primary"],
                                accent=body["accent"],contact_url=body["contactUrl"],
                                style=body["style"],logo_base64=body["logoBase64"],mime=body["mime"],
                                owner_attestation=body["ownerAttestation"],owner_confirmed=body["ownerConfirmed"])
                            result=reel_workbench.read(con,parts[3])
                        elif len(parts)==5 and parts[4]=="captions":
                            if set(body)!={"variant","cues","source","style","ownerConfirmed","expectedEditRevision","expectedCaptionRevision"}:
                                raise reel_workbench.ReelError('Caption track, styles and verified transcript required','invalid_request',400)
                            reel_captions.save(con,parts[3],body["variant"],BASE,
                                cues=body["cues"],source=body["source"],style=body["style"],
                                expected_edit_revision=body["expectedEditRevision"],
                                expected_caption_revision=body["expectedCaptionRevision"],
                                owner_confirmed=body["ownerConfirmed"])
                            result=reel_workbench.read(con,parts[3])
                        elif len(parts)==5 and parts[4]=="render-captions":
                            if set(body)!={"variant","expectedContentSha256","expectedEditRevision","expectedCaptionRevision"}:
                                raise reel_workbench.ReelError("Exact saved cut and captions required","invalid_request",400)
                            result=reel_caption_exports.render(con,parts[3],body["variant"],BASE,
                                expected_content_sha256=body["expectedContentSha256"],
                                expected_edit_revision=body["expectedEditRevision"],
                                expected_caption_revision=body["expectedCaptionRevision"])
                        elif len(parts)==5 and parts[4]=="owner-choice":
                            if set(body)!={"variant","ownerReference","approvalNote","ownerConfirmed","expectedContentSha256","expectedReviewSetSha256"}:
                                raise reel_workbench.ReelError('Exact complete cut and owner consent required','invalid_request',400)
                            result=reel_workbench.record_local_owner_choice(con,parts[3],body["variant"],BASE,
                                owner_reference=body["ownerReference"],approval_note=body["approvalNote"],
                                expected_content_sha256=body["expectedContentSha256"],
                                expected_review_set_sha256=body["expectedReviewSetSha256"],
                                owner_confirmed=body["ownerConfirmed"])
                        elif len(parts)==5 and parts[4]=="feedback":
                            if set(body)!={"variant","message"}:
                                raise reel_workbench.ReelError('Only timeline feedback is allowed','invalid_request',400)
                            result=reel_workbench.save_feedback(con,parts[3],body["variant"],body["message"])
                        else:raise reel_workbench.ReelError('Unknown Reel action','not_found',404)
                    self.send(200,{"project":result});return
                except (reel_workbench.ReelError,marketing_drafts.MarketingDraftError,
                    reel_owner_media.OwnerMediaError,reel_brand_lock.BrandLockError,
                    reel_captions.CaptionError,reel_caption_exports.CaptionExportError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","social-video-proposals"]:
                try:
                    data=self.body_json(max_bytes=1200)
                    with session() as con:result=social_video.propose(con,data)
                    self.send(200,result);return
                except (social_video.VideoPlanError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","hero-creative-history"]:
                try:
                    data=self.body_json(max_bytes=9000)
                    with session() as con:result=hero_history.mutate(con,data)
                    self.send(200,result);return
                except (hero_history.HeroHistoryError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)});return
            if parts==["api","pilot","website-photos","import"]:
                try:
                    data=self.body_json()
                    if not isinstance(data,dict) or set(data)!={"draftId","url","ownerConfirmed"}:
                        raise website_media.MediaError("Select a website image and confirm permission","invalid_request",400)
                    with session() as con:
                        photo=website_media.import_photo(con,data["draftId"],data["url"],BASE,
                            owner_confirmed=data["ownerConfirmed"])
                    self.send(200,photo)
                except (website_media.MediaError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                return
            if parts==["api","pilot","post-approvals"]:
                try:
                    data=self.body_json()
                    keys={"draftId","expectedRevision","kitId","day","claimsChecked","visualsChecked","rightsChecked"}
                    if not isinstance(data,dict) or set(data)!=keys:
                        raise approvals.ApprovalError("A specific checked post, saved pack and explicit confirmations are needed","invalid_request",400)
                    with session() as con:
                        result=approvals.approve_post(con,data["draftId"],data["expectedRevision"],data["kitId"],data["day"],BASE,
                            claims_checked=data["claimsChecked"],visuals_checked=data["visualsChecked"],rights_checked=data["rightsChecked"])
                    self.send(200,result)
                except (approvals.ApprovalError,packs.PackError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                return
            if parts==["api","pilot","agency-packs"]:
                try:
                    data=self.body_json()
                    if not isinstance(data,dict) or set(data)!={"draftId","expectedRevision"}:
                        raise packs.PackError("A saved campaign and exact revision are required","invalid_request",400)
                    with session() as con:job=packs.enqueue_pack(con,data["draftId"],data["expectedRevision"],BASE)
                    if job["status"]=="queued":
                        EXEC.submit(render_agency_pack_job,job["id"])
                    self.send(202 if job["status"] in ("queued","rendering") else 200,job)
                except (packs.PackError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                return
            if parts==["api","pilot","runway","jobs"]:
                try:
                    data=self.body_json()
                    with session() as con:job=runway.start_job(con,data)
                    self.send(200,job)
                except (runway.RunwayError,marketing_drafts.MarketingDraftError) as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                return
            if parts==["api","pilot","marketing-drafts"]:
                try:
                    body=self.body_json(max_bytes=250000)
                    with session() as con:result=marketing_drafts.save_draft(con,body)
                    self.send(200,result)
                except marketing_drafts.MarketingDraftError as exc:
                    self.send(exc.status,{"code":exc.code,"error":str(exc)})
                except (ValueError,TypeError):
                    self.send(400,{"code":"invalid_marketing_draft","error":"Invalid campaign document"})
                return
            if parts==["api","pilot","website-audit"]:
                body=self.body_json()
                try:
                    report=expand_business_audit(extract_website(body.get("website")),reader=extract_website)
                except WebsiteSafetyError as exc:
                    self.send(422,{"code":"website_audit_failed","error":str(exc)[:150]});return
                self.send(200,{"audit":report,"approval_required":True});return
            if parts==["api","pilot","uploads"]:
                content_type=self.headers.get("Content-Type","").split(";",1)[0].lower()
                if content_type not in ALLOWED_TYPES:
                    self.send(415,{"code":"video_type","error":"Use an MP4, MOV or WebM video."});return
                length=int(self.headers.get("Content-Length","0"))
                if not 1024<=length<=MAX_VIDEO:
                    self.send(413,{"code":"video_size","error":"This local pilot accepts files up to 170 MB."});return
                name=unquote(self.headers.get("X-Clippr-Filename","video"))[:100]
                name=Path(name.replace("\\","/")).name
                with LOCK,session() as con:
                    total,count=con.execute("SELECT COALESCE(SUM(bytes),0),COUNT(*) FROM sources").fetchone()
                    if count>=MAX_SOURCES or total+length>MAX_TOTAL_STORAGE:
                        self.send(507,{"code":"local_storage_limit",
                          "error":"This test workspace is at its 650 MB / 12 video limit. Clear old local tests before uploading more."});return
                    pending=con.execute("SELECT COUNT(*) FROM sources WHERE status IN ('queued','scanning')").fetchone()[0]
                    if pending>=2:
                        self.send(429,{"code":"scan_queue_full"});return
                    id=uuid.uuid4().hex
                    target=BASE/"files"/(id+ALLOWED_TYPES[content_type])
                    try:
                        with target.open("xb") as out:
                            remaining=length
                            while remaining:
                                chunk=self.rfile.read(min(256*1024,remaining))
                                if not chunk:raise ValueError("Upload was interrupted")
                                out.write(chunk)
                                remaining-=len(chunk)
                        os.chmod(target,0o600)
                        test=subprocess.run(["ffprobe","-v","error","-show_entries",
                            "format=duration","-of","default=nokey=1:noprint_wrappers=1",str(target)],
                            capture_output=True,text=True,timeout=12)
                        duration=float(test.stdout.strip())
                        if test.returncode or not math.isfinite(duration) or not 3<=duration<=600:
                            raise ValueError("Use a valid video between 3 seconds and 10 minutes")
                    except Exception:
                        target.unlink(missing_ok=True)
                        self.send(400,{"code":"invalid_video","error":"Video was incomplete or could not be verified."});return
                    con.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                        (id,name,content_type,length,"queued",None,time.time(),time.time()))
                    con.commit()
                EXEC.submit(scan_source,id)
                self.send(202,{"id":id,"status":"queued","duration":round(duration,2)});return
            if (len(parts)==5 and parts[:3]==["api","pilot","sources"]
                    and valid_id(parts[3]) and parts[4]=="retry"):
                source_id=parts[3]
                with LOCK,session() as con:
                    con.execute("BEGIN IMMEDIATE")
                    source=row(con,"sources",source_id)
                    if not source:
                        self.send(404,{"code":"source_not_found"});return
                    if source["status"] in ("queued","scanning"):
                        self.send(200,{"id":source_id,"status":source["status"],"replayed":True});return
                    if source["status"]=="done":
                        self.send(409,{"code":"already_analysed","error":"This source has already been analysed."});return
                    if source["status"] not in ("interrupted","error"):
                        self.send(409,{"code":"retry_not_allowed"});return
                    target=BASE/"files"/(source_id+ALLOWED_TYPES[source["mime"]])
                    if not target.is_file() or target.stat().st_size!=source["bytes"]:
                        self.send(409,{"code":"source_missing",
                            "error":"Original video is missing or changed. Upload it again."});return
                    pending=con.execute("SELECT COUNT(*) FROM sources WHERE status IN ('queued','scanning')").fetchone()[0]
                    if pending>=2:
                        self.send(429,{"code":"scan_queue_full",
                            "error":"Two local scans are already pending. Retry when one finishes."});return
                    con.execute("UPDATE sources SET status='queued',result_json=NULL,updated=? WHERE id=?",
                                (time.time(),source_id))
                    con.commit()
                EXEC.submit(scan_source,source_id)
                self.send(202,{"id":source_id,"status":"queued","replayed":False});return
            if (len(parts)==5 and parts[:3]==["api","pilot","sources"]
                    and valid_id(parts[3]) and parts[4]=="transcript"):
                body=self.body_json(max_bytes=100000)
                segments=body.get("segments")
                with LOCK,session() as con:
                    con.execute("BEGIN IMMEDIATE")
                    source=row(con,"sources",parts[3])
                    if not source or source["status"]!="done":
                        self.send(409,{"code":"source_not_ready"});return
                    stored=json.loads(source["result_json"])
                    try:
                        candidates=spoken_windows(segments,duration=float(stored["duration_s"]))
                    except (ValueError,TypeError,KeyError) as exc:
                        self.send(400,{"code":"invalid_transcript","error":str(exc)[:120]});return
                    if not candidates:
                        self.send(422,{"code":"no_speech_windows"});return
                    stored["spoken_scenes"]=[{
                        "timestamp_start":x["start_s"],"timestamp_end":x["end_s"],
                        "title":x["title"],"transcript":x["transcript"],
                        "reason":x["reason"],"review_required":True,
                        "visual_only":False,"verified":False} for x in candidates]
                    con.execute("UPDATE sources SET result_json=?,updated=? WHERE id=?",
                                (json.dumps(stored),time.time(),parts[3]))
                    con.commit()
                self.send(200,{"count":len(candidates),"source_id":parts[3]});return
            if parts==["api","pilot","reset"]:
                data=self.body_json()
                if data.get("confirmation")!="DELETE LOCAL TESTS":
                    self.send(400,{"code":"confirmation_required"});return
                with LOCK,session() as con:
                    active_source=con.execute("SELECT COUNT(*) FROM sources WHERE status IN ('queued','scanning')").fetchone()[0]
                    active_render=con.execute("SELECT COUNT(*) FROM renders WHERE status IN ('queued','rendering')").fetchone()[0]
                    active_pack=con.execute("SELECT COUNT(*) FROM marketing_pack_jobs WHERE status IN ('queued','rendering')").fetchone()[0]
                    paid_jobs=con.execute("SELECT COUNT(*) FROM runway_image_jobs").fetchone()[0]+con.execute("SELECT COUNT(*) FROM runway_video_jobs").fetchone()[0]+con.execute("SELECT COUNT(*) FROM runway_cinematic_shots").fetchone()[0]+con.execute("SELECT COUNT(*) FROM business_paid_video_tests").fetchone()[0]
                    creative_versions=con.execute("SELECT COUNT(*) FROM business_hero_rounds").fetchone()[0]
                    pending_video_briefs=con.execute("SELECT COUNT(*) FROM business_video_proposals").fetchone()[0]
                    if creative_versions or pending_video_briefs:
                        self.send(409,{"code":"creative_history_preserved",
                            "error":"Saved creative versions and feedback must not be cleared by a local test reset."});return
                    if paid_jobs:
                        self.send(409,{"code":"generation_audit_preserved",
                            "error":"Paid AI generation records exist. Do not clear them from the local test reset; preserve the spend evidence."});return
                    if active_source or active_render or active_pack:
                        self.send(409,{"code":"processing_in_progress",
                            "error":"Wait for local jobs to finish before clearing this test workspace."});return
                    sources=con.execute("SELECT id,mime FROM sources").fetchall()
                    renders=con.execute("SELECT id FROM renders").fetchall()
                    kits=[row["id"] for row in con.execute("SELECT id FROM marketing_pack_jobs").fetchall()]
                    photos=[(row["draft_id"],row["id"]) for row in
                        con.execute("SELECT draft_id,id FROM marketing_website_media").fetchall()]
                    con.execute("DELETE FROM business_post_approvals")
                    con.execute("DELETE FROM business_creative_rejections")
                    con.execute("DELETE FROM marketing_pack_jobs")
                    con.execute("DELETE FROM marketing_website_media")
                    con.execute("DELETE FROM marketing_draft_mutations")
                    con.execute("DELETE FROM marketing_drafts")
                    con.execute("DELETE FROM campaigns")
                    con.execute("DELETE FROM sources")
                    con.execute("DELETE FROM renders")
                    con.commit()
                for item in sources:
                    (BASE/"files"/(item["id"]+ALLOWED_TYPES[item["mime"]])).unlink(missing_ok=True)
                for item in renders:
                    (BASE/"exports"/(item["id"]+".mp4")).unlink(missing_ok=True)
                for draft_id,asset_id in photos:
                    folder=BASE/"website_photos"/draft_id
                    (folder/(asset_id+".jpg")).unlink(missing_ok=True)
                    try:folder.rmdir()
                    except OSError:pass
                for kit_id in kits:
                    folder=BASE/"marketing_packs"/kit_id
                    if not folder.is_symlink():
                        for file in packs.FILE_NAMES:(folder/file).unlink(missing_ok=True)
                        try:folder.rmdir()
                        except OSError:pass
                self.send(200,{"ok":True,"deleted_sources":len(sources),
                    "deleted_renders":len(renders),"deleted_website_photos":len(photos),
                    "deleted_marketing_packs":len(kits)});return
            if parts==["api","pilot","campaigns"]:
                body=self.body_json()
                name=str(body.get("name","")).strip()
                brand=str(body.get("brand_name","")).strip()
                scenes=body.get("scenes")
                goal=str(body.get("goal","awareness"))
                if not 2<=len(name)<=100 or not 2<=len(brand)<=80 or not isinstance(scenes,list) or len(scenes)>6:
                    self.send(400,{"code":"invalid_campaign","error":"Name, brand and review scenes required."});return
                allowed_goals={"awareness","enquiries","bookings","education","offers"}
                if goal not in allowed_goals:
                    self.send(400,{"code":"invalid_goal"});return
                clean=[]
                for item in scenes:
                    if not isinstance(item,dict) or not valid_id(item.get("source_id")):
                        self.send(400,{"code":"invalid_scene"});return
                    with session() as con:
                        source=row(con,"sources",item["source_id"])
                    if not source or source["status"]!="done":
                        self.send(409,{"code":"source_not_ready"});return
                    try:a=float(item["start_s"]);b=float(item["end_s"])
                    except (TypeError,ValueError,KeyError):
                        self.send(400,{"code":"invalid_times"});return
                    if not math.isfinite(a) or not math.isfinite(b) or a<0 or b<=a:
                        self.send(400,{"code":"invalid_times"});return
                    choices=json.loads(source["result_json"]).get("scenes") or []
                    if not any(abs(a-float(x["timestamp_start"]))<.02 and abs(b-float(x["timestamp_end"]))<.02 for x in choices):
                        self.send(409,{"code":"unreviewed_timeline","error":"Choose scene windows from the analysed original video."});return
                    focus=item.get("focus_x",0.5)
                    if isinstance(focus,bool) or not isinstance(focus,(float,int)) or not math.isfinite(focus) or not 0<=focus<=1:
                        self.send(400,{"code":"invalid_framing"});return
                    clean.append({"source_id":item["source_id"],"start_s":a,"end_s":b,
                        "focus_x":float(focus),"review_status":"approved" if item.get("review_status")=="approved" else "draft"})
                id=body.get("id") or uuid.uuid4().hex
                if not valid_id(id):self.send(400,{"code":"invalid_campaign_id"});return
                with LOCK,session() as con:
                    con.execute("BEGIN IMMEDIATE")
                    existing=row(con,"campaigns",id)
                    if existing:
                        if body.get("revision") is None:
                            # A lost HTTP acknowledgement may arrive after the
                            # first save committed. Replay only identical intent.
                            if (existing["name"]==name and existing["brand_name"]==brand
                                and existing["goal"]==goal and
                                json.loads(existing["scenes_json"])==clean):
                                self.send(200,{"id":id,"revision":existing["revision"],"replayed":True})
                                return
                            self.send(409,{"code":"create_id_conflict",
                                "error":"That save identifier belongs to different campaign content."});return
                        if body.get("revision")!=existing["revision"]:
                            self.send(409,{"code":"revision_conflict","error":"Campaign changed; reload before saving."});return
                        revision=existing["revision"]+1
                        con.execute("UPDATE campaigns SET revision=?,name=?,brand_name=?,goal=?,scenes_json=?,updated=? WHERE id=?",
                            (revision,name,brand,goal,json.dumps(clean),time.time(),id))
                    else:
                        revision=1
                        con.execute("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)",
                            (id,revision,name,brand,goal,json.dumps(clean),time.time()))
                    con.commit()
                self.send(200,{"id":id,"revision":revision});return
            if (len(parts)==5 and parts[:3]==["api","pilot","renders"]
                    and valid_id(parts[3]) and parts[4]=="retry"):
                previous_id=parts[3]
                with LOCK,session() as con:
                    con.execute("BEGIN IMMEDIATE")
                    previous=row(con,"renders",previous_id)
                    if not previous:
                        self.send(404,{"code":"render_not_found"});return
                    prior=public_render(previous)
                    if prior["status"] not in ("error","interrupted","unavailable"):
                        self.send(409,{"code":"retry_not_allowed",
                          "error":"Only failed or interrupted renders can be retried."});return
                    campaign=row(con,"campaigns",previous["campaign_id"])
                    if not campaign or campaign["revision"]!=previous["revision"]:
                        self.send(409,{"code":"campaign_changed",
                           "error":"Campaign changed. Review and save approvals again."});return
                    fingerprint=hashlib.sha256(("retry:"+previous_id).encode()).hexdigest()
                    already=con.execute("SELECT * FROM renders WHERE fingerprint=?",(fingerprint,)).fetchone()
                    if already:
                        state=public_render(already)
                        self.send(200,{"id":already["id"],"status":state["status"],
                                       "replayed":True});return
                    attempts=con.execute("SELECT COUNT(*) FROM renders WHERE campaign_id=? AND revision=?",
                        (campaign["id"],campaign["revision"])).fetchone()[0]
                    if attempts>=3:
                        self.send(409,{"code":"retry_limit","error":"Maximum of three render attempts reached. Review and save a new campaign revision."});return
                    active=con.execute("SELECT COUNT(*) FROM renders WHERE status IN ('queued','rendering')").fetchone()[0]
                    if active:
                        self.send(429,{"code":"render_busy","error":"Another montage is currently processing."});return
                    try:
                        windows,total=approved_windows(campaign)
                        for window in windows:
                            if not Path(window["path"]).is_file():
                                raise ValueError("Original source is missing; upload it again.")
                    except ValueError as exc:
                        self.send(409,{"code":"approval_required","error":str(exc)});return
                    export=uuid.uuid4().hex
                    con.execute("INSERT INTO renders VALUES (?,?,?,?,?,?,?,?,?)",
                       (export,campaign["id"],campaign["revision"],fingerprint,"queued",
                        total,None,time.time(),time.time()))
                    con.commit()
                EXEC.submit(compose,export,windows,campaign["brand_name"])
                self.send(202,{"id":export,"status":"queued","replayed":False});return
            if parts==["api","pilot","renders"]:
                data=self.body_json()
                id=data.get("campaign_id")
                if not valid_id(id):self.send(400,{"code":"invalid_campaign"});return
                with LOCK,session() as con:
                    con.execute("BEGIN IMMEDIATE")
                    campaign=row(con,"campaigns",id)
                    if not campaign:self.send(404,{"code":"not_found"});return
                    if campaign["revision"]!=data.get("revision"):
                        self.send(409,{"code":"revision_conflict","error":"Reload the approved campaign."});return
                    try:windows,total=approved_windows(campaign)
                    except ValueError as exc:
                        self.send(409,{"code":"approval_required","error":str(exc)});return
                    fingerprint=hashlib.sha256((id+":"+str(campaign["revision"])+":"+campaign["scenes_json"]).encode()).hexdigest()
                    prior=con.execute("SELECT * FROM renders WHERE fingerprint=?",(fingerprint,)).fetchone()
                    if prior:
                        visible=public_render(prior)
                        if visible["status"] in ("error","interrupted","unavailable"):
                            self.send(409,{"code":"render_retry_required","id":prior["id"],
                                "status":visible["status"],
                                "error":"The previous export did not complete safely. Review the saved campaign before retrying."});return
                        self.send(200,{"id":prior["id"],"status":visible["status"],"replayed":True});return
                    active=con.execute("SELECT COUNT(*) FROM renders WHERE status IN ('queued','rendering')").fetchone()[0]
                    if active>=1:self.send(429,{"code":"render_busy"});return
                    export=uuid.uuid4().hex
                    con.execute("INSERT INTO renders VALUES (?,?,?,?,?,?,?,?,?)",
                        (export,id,campaign["revision"],fingerprint,"queued",total,None,time.time(),time.time()))
                    con.commit()
                EXEC.submit(compose,export,windows,campaign["brand_name"])
                self.send(202,{"id":export,"status":"queued","replayed":False});return
            self.send(404,{"code":"unknown_route"})
        except ValueError as exc:
            self.send(400,{"code":"invalid_request","error":str(exc)[:180]})
        except Exception as exc:
            print("LOCAL_PILOT_WRITE_ERROR",type(exc).__name__,flush=True)
            self.send(503,{"code":"pilot_unavailable","error":"The local pilot could not complete this action. Check existing status before retrying."})

def main():
    if os.environ.get("CLIPPR_LOCAL_PILOT")!="1":
        raise RuntimeError("Local isolated pilot must be explicitly enabled")
    with LOCK,session() as con:
        con.execute("UPDATE sources SET status='interrupted' WHERE status IN ('queued','scanning')")
        con.execute("UPDATE renders SET status='interrupted' WHERE status IN ('queued','rendering')")
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    print("CLIPPR_LOCAL_PILOT_LISTENING=http://"+HOST+":"+str(PORT),flush=True)
    print("CLIPPR_LOCAL_PILOT_REAL_FFMPEG_NO_PRODUCTION_SERVICES=true",flush=True)
    try:server.serve_forever(poll_interval=.5)
    finally:server.server_close()
if __name__=="__main__":main()
