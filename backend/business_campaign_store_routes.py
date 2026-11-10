"""Authenticated Business campaign drafts, with optimistic revisions and RLS-style owner isolation."""
from __future__ import annotations
import re
import math
import sqlite3
from flask import request,jsonify
from business_campaign_store import StoreError
from business_campaign_supabase import CampaignSupabase,CampaignForbidden,CampaignStorageUnavailable
from business_sources import lookup_source_by_id
from business_visual_jobs import _id,find_job
ID=re.compile(r"^[a-f0-9]{32}$")
def register_campaign_store_routes(app,current_user,load_org,load_brand,disabled,deps):
    def repo():
        bearer=(request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return CampaignSupabase(deps.supabase_url,deps.supabase_anon_key,bearer)
    def failure(exc):
        if isinstance(exc,CampaignForbidden):
            return jsonify({"code":"forbidden","error":"This campaign is not accessible."}),403
        if isinstance(exc,CampaignStorageUnavailable):
            return jsonify({"code":"storage_unavailable","error":"Campaign storage unavailable. Retry checking before resubmitting."}),503
        message=str(exc)
        return jsonify({"code":"revision_conflict" if "changed" in message else "invalid_campaign",
                        "error":message}),409 if "changed" in message else 400
    def access(org_id):
        user,err=current_user()
        if err is not None:return None,None,err
        org,err=load_org(org_id,user)
        return user,org,err
    def secure_scenes(user,org,items):
        if not isinstance(items,list) or len(items)>24:return False
        for item in items:
            if not isinstance(item,dict):return False
            sid=item.get("source_id")
            if not isinstance(sid,str) or not ID.fullmatch(sid):return False
            source=lookup_source_by_id(sid,user["id"])
            if not source or source["organisation_id"]!=org["id"] or source["status"]!="confirmed":return False
            # Source owner check is essential, but saved timing must also come
            # from an actual completed visual scan — no made-up marketing shots.
            job=find_job(user["id"],_id(user["id"],sid))
            if not job or job["org_id"]!=org["id"] or job["status"]!="done":return False
            try:a,b=float(item["start_s"]),float(item["end_s"])
            except (KeyError,TypeError,ValueError):return False
            if not (math.isfinite(a) and math.isfinite(b) and a>=0 and b>a):return False
            if not any(abs(a-z.get("timestamp_start",-1))<.01 and abs(b-z.get("timestamp_end",-1))<.01
                       for z in (job["result"] or {}).get("scenes",[])):return False
        return True
    @app.get("/api/business/drafts")
    def drafts_list():
        if (off:=disabled()) is not None:return off
        user,org,err=access(request.args.get("organisation_id"))
        if err is not None:return err
        try:return jsonify({"campaigns":repo().list(user["id"],org["id"])})
        except (StoreError,CampaignForbidden,CampaignStorageUnavailable) as exc:return failure(exc)
    @app.get("/api/business/drafts/<cid>")
    def drafts_get(cid):
        if (off:=disabled()) is not None:return off
        user,err=current_user()
        if err is not None:return err
        try:draft=repo().get(user["id"],cid)
        except (StoreError,CampaignForbidden,CampaignStorageUnavailable) as exc:return failure(exc)
        if not draft:return jsonify({"code":"not_found"}),404
        _,org,err=access(draft["organisation_id"])
        if err is not None:return err
        return jsonify(draft)
    @app.post("/api/business/drafts")
    def drafts_save():
        if (off:=disabled()) is not None:return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify({"code":"invalid_input"}),400
        user,org,err=access(data.get("organisation_id"))
        if err is not None:return err
        try:
            scenes_ok=secure_scenes(user,org,data.get("scenes"))
        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
            return jsonify({"code":"source_status_unavailable",
                            "error":"Source verification is temporarily unavailable. Retry without uploading again."}),503
        if not scenes_ok:
            return jsonify({"code":"scenes_not_owned"}),403
        if data.get("brand_id"):
            brand,err=load_brand(org["id"],data["brand_id"])
            if err is not None:return err
            if not brand:return jsonify({"code":"brand_not_found"}),404
        try:
            result=repo().save(user["id"],org["id"],data.get("name"),data.get("goal"),
                               data.get("brand_id"),data.get("scenes"),data.get("notes",""),
                               id=data.get("id"),revision=data.get("revision"),
                               create_id=data.get("create_id"))
            return jsonify(result)
        except (StoreError,CampaignForbidden,CampaignStorageUnavailable) as exc:
            return failure(exc)
    @app.delete("/api/business/drafts/<cid>")
    def drafts_delete(cid):
        if (off:=disabled()) is not None:return off
        user,err=current_user()
        if err is not None:return err
        try:
            old=repo().get(user["id"],cid)
            if not old:return jsonify({"code":"not_found"}),404
            _,org,err=access(old["organisation_id"])
            if err is not None:return err
            if repo().delete(user["id"],org["id"],cid):return jsonify({"ok":True})
            return jsonify({"code":"not_found"}),404
        except (StoreError,CampaignForbidden,CampaignStorageUnavailable) as exc:
            return failure(exc)
