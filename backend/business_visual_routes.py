"""Owner-verified visual scene analysis across up to six uploaded business videos."""
from __future__ import annotations
import re
import os
from flask import jsonify, request
from business_sources import source_for_owner, lookup_source_by_id
from business_visual_jobs import reserve_job, find_job, usage_candidates, VisualQueueFull

ID=re.compile(r"^[a-f0-9]{32}$",re.I)
MAX_BATCH=6

def register_visual_routes(app,deps,disabled,current_user,load_organisation,load_brand):
    def check(data):
        user,error=current_user()
        if error is not None:return None,None,error
        org,error=load_organisation(data.get("organisation_id"),user)
        return user,org,error

    @app.post("/api/business/visual/start")
    def start_scene_scan():
        off=disabled()
        if off is not None:return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify({"code":"invalid_input"}),400
        user,org,error=check(data)
        if error is not None:return error
        sid=data.get("source_id")
        if not isinstance(sid,str) or not ID.fullmatch(sid):
            return jsonify({"code":"invalid_source"}),400
        source=lookup_source_by_id(sid,user["id"])
        if not source or source["organisation_id"]!=org["id"] or source["status"]!="confirmed":
            return jsonify({"code":"not_found","error":"Upload not verified for this business."}),404
        if not source.get("etag"):
            return jsonify({"code":"source_version_unavailable",
                            "error":"This footage must be reverified before visual analysis."}),409
        from business_visual_jobs import _id
        existing=find_job(user["id"],_id(user["id"],sid))
        if existing:
            # Checking/replaying an existing job never costs another scanning
            # slot and must work even when request admission is rate-limited.
            state=existing["status"]
            return jsonify({"job_id":existing["job_id"],"status":state,
                            "replayed":True}),202 if state in (
                "queued","running","downloading","scanning","finalizing") else 200
        if os.environ.get("CLIPPR_BUSINESS_VISUAL_DISPATCH","0")!="1":
            return jsonify({"code":"worker_unavailable",
                            "error":"Visual scanning has not been activated. Your upload remains safe."}),503
        if deps.rate_limited("business_visual",8,3600):
            return jsonify({"code":"rate_limited","error":"Visual scan limit reached."}),429
        try:
            claim=reserve_job(user["id"],org["id"],sid,source["source_key"])
            # Admission only. An independent visual worker claims the durable
            # job later; API restarts cannot discard accepted requests.
            return jsonify(claim),202 if claim["status"] in ("queued","running","downloading","scanning","finalizing") else 200
        except VisualQueueFull:
            return jsonify({"code":"queue_full",
                            "error":"Visual scanning is busy. Your upload is safe; try again shortly.",
                            "retry_after_seconds":30}),429
        except Exception:
            return jsonify({"code":"storage_unavailable","error":"Visual scan unavailable."}),503

    @app.get("/api/business/visual/usage")
    def visual_processing_usage():
        off=disabled()
        if off is not None:return off
        user,error=current_user()
        if error is not None:return error
        try:
            return jsonify(usage_candidates(user["id"]))
        except Exception:
            return jsonify({"code":"storage_unavailable",
                            "error":"Source processing usage is temporarily unavailable."}),503

    @app.get("/api/business/visual/source/<source_id>")
    def visual_status_for_source(source_id):
        off=disabled()
        if off is not None:return off
        user,error=current_user()
        if error is not None:return error
        source=lookup_source_by_id(source_id,user["id"])
        if not source:return jsonify({"code":"not_found"}),404
        org,error=load_organisation(source["organisation_id"],user)
        if error is not None:return error
        from business_visual_jobs import _id
        job=find_job(user["id"],_id(user["id"],source_id))
        if not job:return jsonify({"status":"not_started","source_id":source_id})
        return jsonify({"status":job["status"],"job_id":job["job_id"],"source_id":source_id,
                        "scene_count":len((job["result"] or {}).get("scenes") or [])})

    @app.get("/api/business/visual/<job_id>")
    def scene_scan_status(job_id):
        off=disabled()
        if off is not None:return off
        user,error=current_user()
        if error is not None:return error
        if not ID.fullmatch(str(job_id or "")):
            return jsonify({"code":"invalid_job"}),400
        job=find_job(user["id"],job_id)
        if not job:return jsonify({"code":"not_found"}),404
        org,error=load_organisation(job["org_id"],user)
        if error is not None:return error
        output={"job_id":job_id,"status":job["status"],"phase":job["status"],
                "source_id":job["source_id"]}
        if job["status"]=="done":
            output["scenes"]=(job["result"] or {}).get("scenes") or []
            output["video_url"]="r2://"+job["source_key"]
        elif job["status"] in ("error","interrupted"):
            output["error"]="This scan did not finish. The source footage is safe; contact support if it happens again."
        return jsonify(output)

    @app.post("/api/business/campaigns/prepare-visual")
    def prepare_visual_pack():
        off=disabled()
        if off is not None:return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify({"code":"invalid_input"}),400
        user,org,error=check(data)
        if error is not None:return error
        raw_ids=data.get("visual_job_ids")
        if (not isinstance(raw_ids,list) or not 1<=len(raw_ids)<=MAX_BATCH
            or len(set(str(x) for x in raw_ids))!=len(raw_ids)
            or any(not isinstance(x,str) or not ID.fullmatch(x) for x in raw_ids)):
            return jsonify({"code":"invalid_sources","error":"Choose one to six completed visual scans."}),400
        brand,err=load_brand(org["id"],data.get("brand_id"))
        if err is not None:return err
        results=[]
        for jid in raw_ids:
            job=find_job(user["id"],jid)
            if not job or job["org_id"]!=org["id"]:
                return jsonify({"code":"not_found"}),404
            if job["status"]!="done":
                return jsonify({"code":"not_ready","error":"Some footage has not finished visual scanning."}),409
            for item in (job["result"] or {}).get("scenes",[])[:8]:
                if len(results)>=24:break
                idx=len(results)
                results.append({
                    "index":idx,"source_id":job["source_id"],
                    "video_url":"r2://"+job["source_key"],
                    "start_s":item["timestamp_start"],"end_s":item["timestamp_end"],
                    "title":item["title"],"headline":item["title"],
                    "caption":"Review footage and write a factual caption.",
                    "why":"Visual scene boundary detected locally. Content must be reviewed.",
                    "creative_angle":"Visual scene","ai_status":"not_used",
                    "visual_only":True,"review_required":True
                })
        return jsonify({
            "clips":results,"review_required":True,
            "ai":{"status":"not_used","request_count":0},
            "brand":{"name":(brand or {}).get("name") or org["name"],
                     "primary_color":(brand or {}).get("primary_color") or "#111111",
                     "secondary_color":(brand or {}).get("secondary_color") or "#FFFFFF"}
        })
