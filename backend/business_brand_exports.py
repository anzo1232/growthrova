"""Owner-gated Business export derivatives built from paid/free-entitled Clippr exports.

The ORIGINAL export is always created through Clippr's existing /api/export, which
enforces free export limits, subscription usage and any required creator watermark.
This module only brands a finished, user-owned export without re-downloading the
original source video or calling an AI provider.

Execution and status remain off until CLIPPR_BUSINESS_API=1. No separate paid service.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import jsonify, request
from business_brand_render import BrandRenderError, validate_brand, render_branded_clip

_ID = re.compile(r"^[a-f0-9]{32}$", re.I)
_MAX_SOURCE_BYTES = 400 * 1024 * 1024
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clippr-brand")


def _make_id(secret, uid, original_export_id, org_id, brand_id, brand):
    if not isinstance(secret, str) or len(secret) < 24:
        raise BrandRenderError("Branded exports are not configured")
    digest = json.dumps([uid, original_export_id, org_id, brand_id, brand],
                        sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), digest, hashlib.sha256).hexdigest()[:32]


def _render_job(deps, export_id, original_key, uid, brand, title,
                logo_key=None, org_id=None, brand_id=None):
    """Background render. On failure, persist error; never retry a possibly-billed job."""
    try:
        r2 = deps.get_r2()
        if r2 is None:
            raise BrandRenderError("Storage unavailable")
        head = r2.head_object(Bucket=deps.r2_bucket, Key=original_key)
        size = int(head.get("ContentLength", 0) or 0)
        if not (1024 <= size <= _MAX_SOURCE_BYTES):
            raise BrandRenderError("Original export exceeds the brand render size limit")
        with tempfile.TemporaryDirectory(prefix="clippr-biz-export-") as scratch:
            source = Path(scratch) / "source.mp4"
            target = Path(scratch) / "branded.mp4"
            r2.download_file(deps.r2_bucket, original_key, str(source))
            if not source.exists() or source.stat().st_size != size:
                raise BrandRenderError("Original export could not be fully downloaded")
            logo=None
            if logo_key:
                prefix=f"business/brands/{org_id}/{brand_id}/"
                if not logo_key.startswith(prefix):
                    raise BrandRenderError("Logo does not belong to this brand")
                suffix=Path(logo_key).suffix.lower()
                if suffix not in (".png", ".jpg", ".webp"):
                    raise BrandRenderError("Logo type not supported")
                logo_head=deps.get_r2().head_object(Bucket=deps.r2_bucket,Key=logo_key)
                logo_size=int(logo_head.get("ContentLength") or 0)
                if not (100 <= logo_size <= 2_000_000):
                    raise BrandRenderError("Logo size invalid")
                logo=Path(scratch)/("logo"+suffix)
                deps.get_r2().download_file(deps.r2_bucket, logo_key, str(logo))
                if not logo.is_file() or logo.stat().st_size != logo_size:
                    raise BrandRenderError("Logo file invalid")
            render_branded_clip(source, target, brand, logo_path=logo,
                                logo_root=scratch if logo else None, timeout=180)
            if not target.is_file() or target.stat().st_size < 1500:
                raise BrandRenderError("Branded video is incomplete")
            dest_key = f"business/exports/{uid}/{export_id}.mp4"
            uploaded = deps.upload_to_r2(target, dest_key, filename="clippr-branded.mp4")
            if uploaded != dest_key:
                raise BrandRenderError("Could not store the branded export")
            deps.update_export_status(export_id, "done", r2_key=dest_key,
                                      count_milestone=False)
            print(f"[business-export] completed id={export_id[:12]}", flush=True)
    except Exception as exc:
        print(f"[business-export] failed id={export_id[:12]} kind={type(exc).__name__}", flush=True)
        try:
            deps.update_export_status(export_id, "error", error_type="brand_render_failed",
                                      count_milestone=False)
        except Exception as nested:
            print(f"[business-export] failed to save error state: {type(nested).__name__}", flush=True)


def register_brand_export_routes(app, deps, current_user, owned_session,
                                 load_organisation, load_brand, disabled):
    @app.post("/api/business/exports/brand")
    def start_branded_export():
        off = disabled()
        if off is not None:
            return off
        user, err = current_user()
        if err is not None:
            return err
        if deps.rate_limited("business_brand_export", 12, 3600):
            return jsonify({"error":"Too many branded exports. Please try again later.",
                            "code":"rate_limited"}), 429
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error":"Export details required.", "code":"invalid_input"}),400
        source, err = owned_session(data.get("session_id"), user)
        if err is not None:
            return err
        if source.get("status") != "done":
            return jsonify({"error":"Source analysis is not complete.", "code":"not_ready"}),409
        org, err = load_organisation(data.get("organisation_id"), user)
        if err is not None:
            return err
        if not data.get("brand_id"):
            return jsonify({"error":"Save a Brand Kit before applying branding.",
                            "code":"brand_required"}),400
        brand, err = load_brand(org["id"], data.get("brand_id"))
        if err is not None:
            return err
        # The server has loaded this specific org's brand under the caller JWT.
        try:
            render_brand = validate_brand(brand)
        except BrandRenderError:
            return jsonify({"error":"Your Brand Kit needs valid, readable colours.",
                            "code":"invalid_brand"}),400
        original_id = data.get("source_export_id")
        if not isinstance(original_id,str) or not _ID.fullmatch(original_id):
            return jsonify({"error":"Select an existing Clippr export.",
                            "code":"invalid_export"}),400
        try:
            original = deps.get_export(original_id)
        except Exception:
            return jsonify({"error":"Export storage is temporarily unavailable.",
                            "code":"storage_unavailable"}),503
        if (not original or original.get("user_id") != user["id"]
                or original.get("sid") != data.get("session_id")):
            return jsonify({"error":"Original export not found.","code":"not_found"}),404
        if original.get("status") != "done" or not original.get("r2_key"):
            return jsonify({"error":"Wait until the original export is ready.",
                            "code":"export_not_ready"}),409
        # No other R2 keys are accepted from clients. We only consume the
        # original exported media already verified against user/session owner.
        try:
            export_id = _make_id(deps.export_signing_key, user["id"],
                                 original_id, org["id"], brand["id"],
                                 {**render_brand,"logo_r2_key":brand.get("logo_r2_key")})
        except BrandRenderError:
            return jsonify({"error":"Branded exports aren't configured.",
                            "code":"storage_not_ready"}),503
        try:
            existing = deps.get_export(export_id)
            if existing:
                if existing.get("user_id") != user["id"]:
                    return jsonify({"error":"Export not found.","code":"not_found"}),404
                # Stable idempotency. Never create a second job on repeated POST.
                if existing.get("status") != "error":
                    return jsonify({"export_id":export_id,
                                    "status":existing.get("status") or "processing",
                                    "replayed":True}),202 if existing.get("status") != "done" else 200
                return jsonify({"error":"Previous branded export failed. The original clip is safe.",
                                "code":"render_failed"}),409
            deps.save_export(
                export_id, original.get("sid"), None,
                ((original.get("title") or "Clip")[:85] + " — branded"),
                float(original.get("duration_s") or 0),
                original.get("format") or "9:16",
                bool(original.get("captions")),
                user["id"], video_url=original.get("video_url"),
                start_s=original.get("start_s"), end_s=original.get("end_s"),
                status="processing",count_milestone=False,
            )
        except deps.duplicate_error:
            # Concurrent request on a second Gunicorn worker. The unique
            # exports.export_id constraint has already claimed this key.
            return jsonify({"export_id":export_id, "status":"processing",
                            "replayed":True}),202
        except Exception:
            return jsonify({"error":"Could not reserve the branded export.",
                            "code":"storage_unavailable"}),503
        try:
            _EXECUTOR.submit(_render_job, deps, export_id, original["r2_key"],
                             user["id"], render_brand, original.get("title"),
                             brand.get("logo_r2_key"), org["id"], brand["id"])
        except Exception:
            deps.update_export_status(export_id, "error", error_type="executor_unavailable",
                                      count_milestone=False)
            return jsonify({"error":"Export rendering is currently unavailable.",
                            "code":"render_unavailable"}),503
        return jsonify({"export_id":export_id,"status":"processing",
                        "replayed":False}),202

    @app.get("/api/business/exports/brand/<export_id>")
    def status_branded_export(export_id):
        off = disabled()
        if off is not None:
            return off
        user, err = current_user()
        if err is not None:
            return err
        if not _ID.fullmatch(str(export_id or "")):
            return jsonify({"error":"Invalid export ID.","code":"invalid_export"}),400
        try:
            export = deps.get_export(export_id)
        except Exception:
            return jsonify({"error":"Export status is temporarily unavailable.",
                            "code":"storage_unavailable"}),503
        if (not export or export.get("user_id") != user["id"]
                or not str(export.get("title") or "").endswith(" — branded")):
            return jsonify({"error":"Export not found.","code":"not_found"}),404
        status = export.get("status") or "processing"
        if status == "done":
            key = export.get("r2_key")
            if not isinstance(key,str) or key != f"business/exports/{user['id']}/{export_id}.mp4":
                return jsonify({"error":"The branded file could not be verified.",
                                "code":"storage_unavailable"}),503
            signed = deps.r2_presigned_url(key,expires=600,filename="clippr-branded.mp4")
            if not signed:
                return jsonify({"error":"Branded download link unavailable.",
                                "code":"storage_unavailable"}),503
            return jsonify({"status":"done","export_id":export_id,"url":signed})
        if status == "error":
            return jsonify({"status":"error","export_id":export_id,
                            "message":"Branding failed. Your original export is still safe."})
        return jsonify({"status":"processing","export_id":export_id})
