"""Flag-gated montage HTTP entrypoint. Paid entitlement, source ownership and
scene bounds verified before any storage download or FFmpeg worker activity.
"""
from __future__ import annotations
import os
import re
import math
import json
import hashlib
import tempfile
from threading import Event, Thread, Lock
from pathlib import Path
from flask import request,jsonify
from business_montage_ledger import claim,lookup,update,heartbeat,usage_summary,MontageLimit,HEARTBEAT_SECONDS
from business_sources import lookup_source_by_id,MAX_BYTES
from business_visual_jobs import find_job,_id
from business_brand_render import validate_brand,BrandRenderError
from business_montage import build_montage
from business_montage_approval import verify_approved_draft,MontageApprovalError
from business_campaign_supabase import CampaignForbidden,CampaignStorageUnavailable

ID=re.compile(r"^[a-f0-9]{32}$",re.I)
MAX_MONTAGE_SOURCE_BYTES=1024*1024*1024  # 1 GiB per render, not per file

def _validated_scenes(owner,org,rows):
    if not isinstance(rows,list) or not 2<=len(rows)<=6:return None
    approved=[]
    total=0
    counted={}
    for x in rows:
        if not isinstance(x,dict):return None
        sid=x.get("source_id")
        if not isinstance(sid,str) or not ID.fullmatch(sid):return None
        source=lookup_source_by_id(sid,owner)
        if not source or source["organisation_id"]!=org or source["status"]!="confirmed":
            return None
        if not source.get("etag") or not source.get("declared_size"):
            return None  # legacy/unverifiable uploads cannot be exported
        counted[source["source_key"]]=int(source["declared_size"])
        if sum(counted.values())>MAX_MONTAGE_SOURCE_BYTES:return None
        job=find_job(owner,_id(owner,sid))
        if not job or job["status"]!="done" or job["org_id"]!=org:return None
        try:
            start=float(x["start_s"]);end=float(x["end_s"])
        except (KeyError,TypeError,ValueError):return None
        if not (math.isfinite(start) and math.isfinite(end) and start>=0
                and 3<=end-start<=30):return None
        if not any(abs(start-z["timestamp_start"])<.01 and abs(end-z["timestamp_end"])<.01
                   for z in (job["result"] or {}).get("scenes",[])):
            return None
        total+=end-start
        if total>120:return None
        approved.append({"source_id":sid,"key":source["source_key"],
                         "size":source["declared_size"],"etag":source["etag"],
                         "start_s":start,"end_s":end})
    return approved

def _worker(deps,owner,jid,scenes,brand,brand_id,org,*,lease_token=None):
    """R2 + FFmpeg worker with safe liveness and never-retry semantics."""
    stop=Event()
    lost=Event()
    guard=Lock()
    phase=["starting"]
    def beat():
        while not stop.wait(HEARTBEAT_SECONDS):
            with guard:state=phase[0]
            try:
                if not heartbeat(owner,jid,state,lease_token=lease_token):
                    lost.set()
                    return
            except Exception as exc:
                print("[business-montage] heartbeat error="+type(exc).__name__,flush=True)
                # The worker can still recover a short database interruption.
                # No extra charges/jobs are scheduled as a result.
    def advance(value):
        if lost.is_set():
            raise RuntimeError("montage_lease_lost")
        if not heartbeat(owner,jid,value,lease_token=lease_token):
            raise RuntimeError("montage_job_interrupted")
        with guard:phase[0]=value

    beat_thread=None
    try:
        if lease_token is None and not update(owner,jid,"running"):
            return  # Legacy tests; production worker leases jobs explicitly.
        if lease_token is not None and not heartbeat(owner,jid,"starting",lease_token=lease_token):
            return  # No active lease, don't download anything.
        beat_thread=Thread(target=beat,daemon=True,name="business-montage-heartbeat")
        beat_thread.start()
        r2=deps.get_r2()
        if r2 is None:raise RuntimeError("r2_unavailable")
        advance("downloading")
        if lease_token is not None:
            unique={}
            for scene in scenes:
                key=scene["key"]
                if (not isinstance(scene.get("etag"),str) or not scene["etag"]
                    or type(scene.get("size")) is not int):
                    raise ValueError("unverified_source_version")
                existing=unique.get(key)
                if existing and existing!=(scene["size"],scene["etag"]):
                    raise ValueError("inconsistent_source_versions")
                unique[key]=(scene["size"],scene["etag"])
            if sum(x[0] for x in unique.values())>MAX_MONTAGE_SOURCE_BYTES:
                raise ValueError("montage_download_budget_exceeded")
            # HEAD all immutable versions before spending bandwidth on any.
            for key,(expected_length,etag) in unique.items():
                head=r2.head_object(Bucket=deps.r2_bucket,Key=key)
                if int(head.get("ContentLength") or 0)!=expected_length or head.get("ETag")!=etag:
                    raise ValueError("approved_source_changed")
        with tempfile.TemporaryDirectory(prefix="clippr-montage-job-") as root:
            files={}
            segments=[]
            for scene in scenes:
                key=scene["key"]
                if key not in files:
                    head=r2.head_object(Bucket=deps.r2_bucket,Key=key)
                    size=int(head.get("ContentLength") or 0)
                    if not 1024<=size<=MAX_BYTES:raise ValueError("invalid_file_size")
                    target=Path(root)/("source-"+str(len(files)) + Path(key).suffix)
                    r2.download_file(deps.r2_bucket,key,str(target))
                    if target.stat().st_size!=size:raise ValueError("partial_download")
                    if lease_token is not None:
                        current=r2.head_object(Bucket=deps.r2_bucket,Key=key)
                        if (current.get("ETag")!=scene["etag"] or
                                int(current.get("ContentLength") or 0)!=scene["size"]):
                            raise ValueError("source_changed_during_download")
                    files[key]=target
                segments.append({"path":str(files[key]),"start_s":scene["start_s"],"end_s":scene["end_s"]})
                advance("downloading")
            logo=None
            logo_key=brand.get("logo_r2_key")
            if logo_key:
                prefix=f"business/brands/{org}/{brand_id}/"
                if not logo_key.startswith(prefix):raise ValueError("foreign_logo")
                head=r2.head_object(Bucket=deps.r2_bucket,Key=logo_key)
                length=int(head.get("ContentLength") or 0)
                if not 100<=length<=2_000_000:raise ValueError("logo_size")
                logo=Path(root)/("logo"+Path(logo_key).suffix)
                r2.download_file(deps.r2_bucket,logo_key,str(logo))
                if logo.stat().st_size!=length:raise ValueError("partial_logo")
            advance("rendering")
            target=Path(root)/"finished.mp4"
            build_montage(segments,target,brand=brand,logo_path=logo,
                          logo_root=root if logo else None)
            advance("uploading")
            key=f"business/montages/{owner}/{jid}.mp4"
            if deps.upload_to_r2(target,key,filename="clippr-business-montage.mp4")!=key:
                raise RuntimeError("upload_failed")
            if not update(owner,jid,"done",key=key,lease_token=lease_token):
                print("[business-montage] output rendered but job became inactive; no download link issued",flush=True)
    except Exception as error:
        print("[business-montage] failed "+type(error).__name__,flush=True)
        try:update(owner,jid,"error",error="montage_failed",lease_token=lease_token)
        except Exception:pass
    finally:
        stop.set()
        if beat_thread is not None:beat_thread.join(timeout=2)

def register_montage_routes(app,deps,current_user,load_org,load_brand,disabled):
    def off():
        guarded=disabled()
        if guarded is not None:return guarded
        if os.environ.get("CLIPPR_BUSINESS_MONTAGE","0")!="1":
            return jsonify({"code":"montage_unavailable"}),404
        return None
    @app.post("/api/business/montages")
    def create_montage():
        stop=off()
        if stop is not None:return stop
        user,err=current_user()
        if err is not None:return err
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):return jsonify({"code":"invalid_input"}),400
        org,err=load_org(payload.get("organisation_id"),user)
        if err is not None:return err
        brand,err=load_brand(org["id"],payload.get("brand_id"))
        if err is not None:return err
        if not brand:return jsonify({"code":"brand_required"}),400
        try:brand_settings=validate_brand(brand)
        except BrandRenderError:return jsonify({"code":"invalid_brand"}),400
        scenes=_validated_scenes(user["id"],org["id"],payload.get("scenes"))
        if not scenes:return jsonify({"code":"scenes_not_owned_or_unapproved"}),403
        bearer=(request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        try:
            approved=verify_approved_draft(deps,bearer,user["id"],org["id"],brand["id"],
                                           payload.get("draft_id"),payload.get("draft_revision"),scenes)
        except MontageApprovalError as exc:
            return jsonify({"code":exc.code,"error":str(exc)}),(
                404 if exc.code=="not_found" else
                401 if exc.code=="auth_required" else
                400 if exc.code=="draft_required" else 409)
        except CampaignForbidden:
            return jsonify({"code":"forbidden"}),403
        except CampaignStorageUnavailable:
            return jsonify({"code":"storage_unavailable"}),503
        if not deps.has_paid_access(user):
            return jsonify({"code":"paid_plan_required",
                            "error":"Montage exports require an active paid subscription."}),402
        try:
            # Freeze creative design in the idempotency fingerprint. If a user
            # changes Brand Kit colours/logo, that is a new montage version,
            # not a replay of the old visual output.
            brand_snapshot={**brand_settings,"logo_r2_key":brand.get("logo_r2_key")}
            brand_digest=hashlib.sha256(json.dumps(
                brand_snapshot,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]
            frozen_version=approved["id"]+":"+str(approved["revision"])
            ticket=claim(user["id"],org["id"],
                         brand["id"]+":"+brand_digest+":"+frozen_version,scenes,
                         brand_snapshot=brand_snapshot,render_brand_id=brand["id"])
            # API owns admission ONLY. An independent persistent worker reads
            # durable queued payloads after API process restarts.
            return jsonify({"montage_id":ticket["id"],"status":ticket["status"],
                            "phase":ticket["phase"],"replayed":ticket["replayed"]}),202 if ticket["status"] in ("queued","running") else 200
        except MontageLimit:
            return jsonify({"code":"montage_quota","error":"Montage capacity reached. Try later."}),429
        except Exception:
            return jsonify({"code":"storage_unavailable"}),503
    @app.get("/api/business/montages/usage")
    def montage_usage():
        stop=off()
        if stop is not None:return stop
        user,err=current_user()
        if err is not None:return err
        try:
            return jsonify({"meter":usage_summary(user["id"]),
                            "billable":False,
                            "billing_note":"Render output is recorded for metering; no automatic Stripe charge is made."})
        except Exception:
            return jsonify({"code":"storage_unavailable"}),503

    @app.get("/api/business/montages/<jid>")
    def montage_status(jid):
        stop=off()
        if stop is not None:return stop
        user,err=current_user()
        if err is not None:return err
        if not ID.fullmatch(str(jid or "")):return jsonify({"code":"invalid_montage"}),400
        job=lookup(user["id"],jid)
        if not job:return jsonify({"code":"not_found"}),404
        if job["status"]=="done":
            expected=f"business/montages/{user['id']}/{jid}.mp4"
            if job["output_key"]!=expected:return jsonify({"code":"storage_unavailable"}),503
            url=deps.r2_presigned_url(expected,expires=600,filename="clippr-business-montage.mp4")
            if not url:return jsonify({"code":"storage_unavailable"}),503
            return jsonify({"status":"done","url":url,"montage_id":jid})
        return jsonify({"status":job["status"],"phase":job["phase"],"montage_id":jid,
                        "error":job["error_code"] if job["status"] in ("error","interrupted") else None})
