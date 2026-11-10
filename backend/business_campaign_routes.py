"""Owner-verified Clippr Business campaign endpoints.

Private development feature, guarded by CLIPPR_BUSINESS_API=1.
No creator endpoints or billing semantics are modified.
"""
from __future__ import annotations

import os
import re
import uuid
import requests
from flask import jsonify, request
from business_campaign_engine import BusinessCampaignError, generate_campaign, validate_brief
from business_auth_config import business_auth_projects_match

UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$", re.I)
SID = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")
MAX_SOURCE_CLIPS = 40

def register_business_routes(app, deps):
    def disabled():
        if os.environ.get("CLIPPR_BUSINESS_API", "0") != "1":
            return (jsonify({"error": "Business campaign features are not enabled.", "code": "business_unavailable"}), 404)
        if not business_auth_projects_match(getattr(deps,"supabase_url",None),
                                             getattr(deps,"auth_supabase_url",None),
                                             getattr(deps,"supabase_anon_key",None)):
            return (jsonify({"error":"Business login and database configuration must be aligned.",
                             "code":"business_auth_config_mismatch"}),503)
        return None

    def current_user():
        try:
            user = deps.get_user(strict=True)
        except Exception:
            return None, (jsonify({"error": "Could not verify your session. Try again shortly.", "code": "auth_unavailable"}), 503)
        if not user or not user.get("id"):
            return None, (jsonify({"error": "Sign in to Clippr first.", "code": "auth_required"}), 401)
        return user, None

    def owned_session(sid, user):
        if not SID.fullmatch(str(sid or "")):
            return None, (jsonify({"error": "Invalid session ID.", "code": "invalid_session"}), 400)
        try:
            source = deps.get_session(sid)
        except Exception:
            # SQLite lock / backend interruption is NOT "your job disappeared".
            return None, (jsonify({"error": "Processing status is temporarily unavailable. Retry status checking without resubmitting the video.",
                                   "code": "status_unavailable"}), 503)
        # Both unknown IDs and someone else's sessions get the same 404.
        if not source or not source.get("user_id") or str(source["user_id"]) != str(user["id"]):
            return None, (jsonify({"error": "Campaign source not found.", "code": "not_found"}), 404)
        return source, None

    def load_organisation(organisation_id, user):
        if not isinstance(organisation_id, str) or not UUID.fullmatch(organisation_id):
            return None, (jsonify({"error": "Select a valid business.", "code": "invalid_organisation"}), 400)
        base = (deps.supabase_url or "").rstrip("/")
        anon = deps.supabase_anon_key or ""
        bearer = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if not base or not anon or not bearer:
            return None, (jsonify({"error": "Business data is not connected.", "code": "storage_not_ready"}), 503)
        # User JWT, NOT service role: actual table RLS is the ultimate check.
        try:
            result = requests.get(
                base + "/rest/v1/business_organisations",
                params={"id": "eq." + organisation_id, "owner_id": "eq." + str(user["id"]), "select": "id,name,industry,primary_goal", "limit": 1},
                headers={"apikey": anon, "Authorization": "Bearer " + bearer},
                timeout=7,
            )
            if result.status_code in (401, 403):
                return None, (jsonify({"error": "You cannot access that business.", "code": "forbidden"}), 403)
            if result.status_code != 200:
                return None, (jsonify({"error": "Business storage temporarily unavailable.", "code": "storage_unavailable"}), 503)
            rows = result.json()
            if not isinstance(rows, list) or not rows:
                return None, (jsonify({"error": "Business not found.", "code": "not_found"}), 404)
            return rows[0], None
        except (requests.RequestException, ValueError):
            return None, (jsonify({"error": "Business storage temporarily unavailable.", "code": "storage_unavailable"}), 503)

    def load_brand(organisation_id, brand_id):
        if not brand_id:
            return None, None
        if not isinstance(brand_id, str) or not UUID.fullmatch(brand_id):
            return None, (jsonify({"error": "Invalid Brand Kit.", "code": "invalid_brand"}), 400)
        anon = deps.supabase_anon_key or ""
        bearer = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        try:
            result = requests.get(
                deps.supabase_url.rstrip("/") + "/rest/v1/business_brand_kits",
                params={"id": "eq." + brand_id, "organisation_id": "eq." + organisation_id,
                        "select": "id,name,font_style,default_cta,primary_color,secondary_color,logo_r2_key", "limit": 1},
                headers={"apikey": anon, "Authorization": "Bearer " + bearer},
                timeout=7,
            )
            if result.status_code != 200:
                return None, (jsonify({"error": "Brand Kit could not be loaded.", "code": "brand_unavailable"}), 503)
            rows = result.json()
            if not isinstance(rows, list) or not rows:
                return None, (jsonify({"error": "Brand Kit not found.", "code": "not_found"}), 404)
            return rows[0], None
        except (requests.RequestException, ValueError):
            return None, (jsonify({"error": "Brand Kit temporarily unavailable.", "code": "brand_unavailable"}), 503)

    @app.get("/api/business/sessions/<sid>")
    def business_session_status(sid):
        off = disabled()
        if off is not None:
            return off
        user, err = current_user()
        if err is not None:
            return err
        source, err = owned_session(sid, user)
        if err is not None:
            return err
        status = source.get("status")
        try:
            progress = max(0, min(100, int(float(source.get("progress") or 0))))
        except (TypeError, ValueError, OverflowError):
            progress = 0
        body = {"session_id": sid, "status": status, "progress": progress}
        if status == "done":
            # Only accessible to the owner, needed to use current preview/export engine.
            body["video_url"] = source.get("url") or ""
        if status == "done":
            body["clips"] = (source.get("clips") or [])[:MAX_SOURCE_CLIPS]
            body["clip_count"] = len(source.get("clips") or [])
        elif status == "error":
            body["error"] = "Your source video could not be analysed. You can retry without losing your Brand Kit."
            body["code"] = "analysis_failed"
        return jsonify(body)

    @app.post("/api/business/campaigns/prepare")
    def business_prepare_campaign():
        off = disabled()
        if off is not None:
            return off
        user, err = current_user()
        if err is not None:
            return err
        if deps.rate_limited("business_prepare", 15, 3600):
            return jsonify({"error": "Campaign requests are temporarily limited. Please retry later.", "code": "rate_limited"}), 429
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid campaign details.", "code": "invalid_input"}), 400
        sid = data.get("session_id")
        source, err = owned_session(sid, user)
        if err is not None:
            return err
        if source.get("status") != "done":
            return jsonify({"error": "The video is still processing.", "code": "source_not_ready"}), 409
        org, err = load_organisation(data.get("organisation_id"), user)
        if err is not None:
            return err
        brand, err = load_brand(org["id"], data.get("brand_id"))
        if err is not None:
            return err
        try:
            brief = validate_brief({
                "goal": data.get("goal") or org["primary_goal"],
                "industry": org["industry"],
                "brand_name": org["name"],
                "style": (brand or {}).get("font_style") or "modern",
                "cta": (brand or {}).get("default_cta") or "",
                "approved_offer": data.get("approved_offer") or "",
                "audience": data.get("audience") or "",
            })
        except BusinessCampaignError as exc:
            return jsonify({"error": str(exc), "code": "invalid_brief"}), 400
        # This is deliberately off by default. An AI-generated pack must not
        # accidentally trigger expensive calls or a provider fallback.
        use_ai = os.environ.get("CLIPPR_BUSINESS_AI", "0") == "1"
        if use_ai:
            from business_ai_journal import guarded_generate
            result = guarded_generate(user["id"], source.get("clips") or [], brief)
        else:
            result = generate_campaign(source.get("clips") or [], brief, use_ai=False)
        return jsonify({
            "session_id": sid, "organisation_id": org["id"],
            "brand": {"name": (brand or {}).get("name") or org["name"],
                      "primary_color": (brand or {}).get("primary_color") or "#111111",
                      "secondary_color": (brand or {}).get("secondary_color") or "#FFFFFF"},
            "goal": brief["goal"], "review_required": True, **result,
        })

    # Registered inside the same feature gate: same verified Supabase session,
    # own source-session lookup, owner RLS and saved Brand Kit validation.
    from business_brand_exports import register_brand_export_routes
    register_brand_export_routes(
        app, deps, current_user, owned_session, load_organisation, load_brand,
        disabled,
    )

    from business_brand_assets import register_brand_asset_routes
    register_brand_asset_routes(
        app, deps, current_user, load_organisation, load_brand, disabled,
    )

    from business_source_routes import register_source_routes
    register_source_routes(app, deps, disabled, current_user, load_organisation)

    from business_visual_routes import register_visual_routes
    register_visual_routes(app, deps, disabled, current_user, load_organisation, load_brand)

    from business_montage_routes import register_montage_routes
    register_montage_routes(app, deps, current_user, load_organisation,
                            load_brand, disabled)
    from business_campaign_store_routes import register_campaign_store_routes
    register_campaign_store_routes(app, current_user, load_organisation,
                                   load_brand, disabled, deps)
