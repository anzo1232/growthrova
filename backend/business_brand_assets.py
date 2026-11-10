"""Private, owner-checked brand logo uploads to existing R2 storage."""
from __future__ import annotations
import os
import re
import tempfile
import uuid
from pathlib import Path

import requests
from flask import jsonify, request

TYPE_EXT = {"image/png":".png", "image/jpeg":".jpg", "image/webp":".webp"}
MAX_LOGO = 2_000_000
KEY_RE = re.compile(r"^[a-f0-9-]{36}$", re.I)

def _path(org_id, brand_id):
    return f"business/brands/{org_id}/{brand_id}/"

def register_brand_asset_routes(app, deps, current_user, load_org, load_brand, disabled):
    def owner(data):
        user, error = current_user()
        if error is not None: return None, None, error
        org, error = load_org(data.get("organisation_id"), user)
        if error is not None: return None, None, error
        brand, error = load_brand(org["id"], data.get("brand_id"))
        if error is not None: return None, None, error
        if not brand: return None, None, (jsonify({"code":"brand_required"}),400)
        return org, brand, None

    @app.post("/api/business/brands/logo/init")
    def logo_init():
        off=disabled()
        if off is not None: return off
        body=request.get_json(silent=True)
        if not isinstance(body,dict): return jsonify({"code":"invalid_input"}),400
        org,brand,error=owner(body)
        if error is not None: return error
        if deps.rate_limited("brand_logo_init",15,3600):
            return jsonify({"code":"rate_limited"}),429
        mime=body.get("content_type")
        try: size=int(body.get("size") or 0)
        except (ValueError,TypeError): size=0
        if mime not in TYPE_EXT or not (100<=size<=MAX_LOGO):
            return jsonify({"error":"Use a PNG, JPG or WebP logo under 2MB.","code":"invalid_file"}),400
        key=_path(org["id"],brand["id"])+uuid.uuid4().hex+TYPE_EXT[mime]
        if deps.get_r2() is None: return jsonify({"code":"storage_unavailable"}),503
        try:
            url=deps.r2_presigned_put(key,mime,expires=300)
        except Exception: url=None
        if not url: return jsonify({"code":"storage_unavailable"}),503
        return jsonify({"key":key,"upload_url":url,"content_type":mime,"expires_seconds":300})

    @app.post("/api/business/brands/logo/complete")
    def logo_complete():
        off=disabled()
        if off is not None: return off
        body=request.get_json(silent=True)
        if not isinstance(body,dict): return jsonify({"code":"invalid_input"}),400
        org,brand,error=owner(body)
        if error is not None: return error
        key=body.get("key")
        if not isinstance(key,str) or len(key)>240 or not key.startswith(_path(org["id"],brand["id"])):
            return jsonify({"code":"not_found"}),404
        extension=Path(key).suffix.lower()
        if extension not in TYPE_EXT.values() or not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|webp)",key.split("/")[-1]):
            return jsonify({"code":"invalid_file"}),400
        storage=deps.get_r2()
        if storage is None: return jsonify({"code":"storage_unavailable"}),503
        try:
            head=storage.head_object(Bucket=deps.r2_bucket,Key=key)
            size=int(head.get("ContentLength") or 0)
            if size<100 or size>MAX_LOGO:
                return jsonify({"code":"invalid_file","error":"Logo file size invalid."}),400
            from PIL import Image, UnidentifiedImageError
            with tempfile.TemporaryDirectory(prefix="clippr-logo-check-") as folder:
                file=Path(folder)/("asset"+extension)
                storage.download_file(deps.r2_bucket,key,str(file))
                if file.stat().st_size!=size: raise ValueError("mismatched size")
                with Image.open(file) as image:
                    fmt=image.format
                    w,h=image.size
                    if fmt not in {"PNG","JPEG","WEBP"} or w>4000 or h>4000 or w<16 or h<16:
                        raise ValueError("invalid image")
                    if {".png":"PNG",".jpg":"JPEG",".webp":"WEBP"}[extension]!=fmt:
                        raise ValueError("image format mismatch")
                    image.verify()
        except (ValueError, OSError, UnidentifiedImageError):
            return jsonify({"code":"invalid_file","error":"Upload a valid image logo."}),400
        except Exception:
            return jsonify({"code":"storage_unavailable"}),503
        token=(request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        try:
            result=requests.patch(
                deps.supabase_url.rstrip("/")+"/rest/v1/business_brand_kits",
                params={"id":"eq."+brand["id"],"organisation_id":"eq."+org["id"]},
                headers={"apikey":deps.supabase_anon_key,"Authorization":"Bearer "+token,
                         "Prefer":"return=representation","Content-Type":"application/json"},
                json={"logo_r2_key":key},timeout=8)
            if result.status_code!=200 or not isinstance(result.json(),list) or len(result.json())!=1:
                return jsonify({"code":"save_failed"}),503
        except (requests.RequestException,ValueError):
            return jsonify({"code":"save_failed"}),503
        return jsonify({"ok":True,"logo_key":key})

    @app.get("/api/business/brands/logo")
    def logo_download():
        off=disabled()
        if off is not None: return off
        org,brand,error=owner(request.args)
        if error is not None:return error
        key=brand.get("logo_r2_key")
        if not isinstance(key,str) or not key.startswith(_path(org["id"],brand["id"])):
            return jsonify({"code":"not_found"}),404
        extension=Path(key).suffix.lower()
        mime={".png":"image/png",".jpg":"image/jpeg",".webp":"image/webp"}.get(extension)
        if not mime:return jsonify({"code":"invalid_file"}),400
        try:
            url=deps.get_r2().generate_presigned_url("get_object",
                Params={"Bucket":deps.r2_bucket,"Key":key,
                        "ResponseContentType":mime},ExpiresIn=600)
        except Exception:return jsonify({"code":"storage_unavailable"}),503
        if not url:return jsonify({"code":"storage_unavailable"}),503
        return jsonify({"url":url})
