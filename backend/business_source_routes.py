"""Business-only source upload endpoints backed by owner-checked reservations."""
from __future__ import annotations

import os
import re
import requests
from business_sources import reserve_source, confirm_source, source_for_owner, KEY

def register_source_routes(app, deps, disabled, current_user, load_organisation):
    from flask import jsonify, request
    def auth_and_org(data):
        user, error = current_user()
        if error is not None: return None, None, error
        org, error = load_organisation(data.get("organisation_id"), user)
        return user, org, error

    @app.post("/api/business/sources/init")
    def init_business_source():
        off=disabled()
        if off is not None: return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify({"error":"Upload details required.","code":"invalid_input"}),400
        user, org, error = auth_and_org(data)
        if error is not None:return error
        if deps.rate_limited("business_source_init",20,3600):
            return jsonify({"error":"Too many uploads. Try later.","code":"rate_limited"}),429
        try:
            reserved=reserve_source(user["id"],org["id"],data.get("filename"),
                                    data.get("content_type"),data.get("size"),
                                    data.get("client_nonce"))
        except ValueError as exc:
            return jsonify({"error":str(exc),"code":"invalid_source"}),400
        except Exception:
            return jsonify({"error":"Upload storage is temporarily unavailable.",
                            "code":"storage_unavailable"}),503
        key=reserved["source_key"]
        if reserved["status"]=="confirmed":
            return jsonify({"source_id":reserved["source_id"],"key":key,
                            "status":"confirmed","replayed":True})
        if reserved.get("replayed"):
            # Same user, same nonce and file. Check whether the previous
            # request actually completed before issuing a second upload token.
            r2=deps.get_r2()
            if r2 is None:
                return jsonify({"code":"storage_unavailable"}),503
            try:
                head=r2.head_object(Bucket=deps.r2_bucket,Key=key)
            except Exception as exc:
                code=str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
                if code not in ("404","NoSuchKey","NotFound"):
                    return jsonify({"code":"upload_verification_unavailable"}),503
            else:
                if not head.get("ETag"):
                    return jsonify({"code":"upload_verification_unavailable"}),503
                length=int(head.get("ContentLength") or 0)
                actual_type=(head.get("ContentType") or "").split(";",1)[0].lower().strip()
                try:
                    verified=confirm_source(key,user["id"],length,actual_type,
                                            actual_etag=head.get("ETag"))
                except (TypeError,ValueError):
                    return jsonify({"code":"upload_mismatch","error":"Previous upload does not match the reserved video."}),409
                return jsonify({"source_id":verified["source_id"],"key":key,
                                "status":"confirmed","replayed":True})
        try:
            if deps.worker_enabled():
                exp,sig=deps.worker_upload_token(key)
                return jsonify({"mode":"worker","source_id":reserved["source_id"],
                    "key":key,"base":deps.upload_base,"exp":exp,"sig":sig,
                    "part_size":deps.upload_part_size,
                    "content_type":reserved["content_type"]})
            url=deps.r2_presigned_put(key,reserved["content_type"],expires=1200)
            if not url:raise ValueError("presigning unavailable")
            return jsonify({"mode":"single","source_id":reserved["source_id"],
                            "key":key,"upload_url":url,
                            "content_type":reserved["content_type"]})
        except Exception:
            return jsonify({"error":"Upload endpoint is temporarily unavailable.",
                            "code":"storage_unavailable"}),503

    @app.post("/api/business/sources/confirm")
    def confirm_business_source():
        off=disabled()
        if off is not None:return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify({"error":"Source details required.","code":"invalid_input"}),400
        user,org,error=auth_and_org(data)
        if error is not None:return error
        key=data.get("key")
        if not isinstance(key,str) or not KEY.fullmatch(key):
            return jsonify({"code":"invalid_source"}),400
        registered=source_for_owner(key,user["id"])
        if not registered or registered["organisation_id"]!=org["id"]:
            return jsonify({"error":"Source not found.","code":"not_found"}),404
        client=deps.get_r2()
        if client is None:
            return jsonify({"error":"Upload storage unavailable.","code":"storage_unavailable"}),503
        try:
            head=client.head_object(Bucket=deps.r2_bucket,Key=key)
            if not head.get("ETag"):
                return jsonify({"code":"storage_unavailable","error":"Source version could not be verified."}),503
            actual=int(head.get("ContentLength") or 0)
            content_type=(head.get("ContentType") or "").split(";",1)[0].strip().lower()
            verified=confirm_source(key,user["id"],actual,content_type,
                                    actual_etag=head.get("ETag"))
            return jsonify({"ok":True,"source_id":verified["source_id"],
                            "key":key,"size":actual})
        except ValueError as exc:
            return jsonify({"error":str(exc),"code":"upload_invalid"}),400
        except Exception:
            return jsonify({"error":"Upload verification is temporarily unavailable.",
                            "code":"storage_unavailable"}),503

    @app.post("/api/business/sources/recover")
    def recover_business_source():
        """Recover an R2 upload that completed before browser confirmation."""
        off=disabled()
        if off is not None:return off
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            return jsonify({"code":"invalid_input"}),400
        user,org,error=auth_and_org(data)
        if error is not None:return error
        source_id=data.get("source_id")
        if not isinstance(source_id,str) or not re.fullmatch(r"[a-f0-9]{32}",source_id):
            return jsonify({"code":"invalid_source"}),400
        from business_sources import lookup_source_by_id
        saved=lookup_source_by_id(source_id,user["id"])
        if not saved or saved["organisation_id"]!=org["id"]:
            return jsonify({"code":"not_found"}),404
        if saved["status"]=="confirmed":
            return jsonify({"ok":True,"source_id":source_id,"status":"confirmed","replayed":True})
        if saved["status"]!="pending":
            return jsonify({"code":"source_unavailable"}),409
        r2=deps.get_r2()
        if r2 is None:return jsonify({"code":"storage_unavailable"}),503
        try:
            head=r2.head_object(Bucket=deps.r2_bucket,Key=saved["source_key"])
        except Exception as exc:
            status=str(getattr(exc,"response",{}).get("Error",{}).get("Code",""))
            if status in ("404","NoSuchKey","NotFound"):
                return jsonify({"code":"upload_still_pending",
                                "error":"This footage has not finished uploading. Choose the same original file to continue safely."}),409
            return jsonify({"code":"storage_unavailable"}),503
        try:
            actual=int(head.get("ContentLength") or 0)
            if not head.get("ETag"):
                return jsonify({"code":"storage_unavailable"}),503
            mime=(head.get("ContentType") or "").split(";",1)[0].lower().strip()
            verified=confirm_source(saved["source_key"],user["id"],actual,mime,
                                    actual_etag=head.get("ETag"))
            return jsonify({"ok":True,"source_id":verified["source_id"],
                            "status":"confirmed","replayed":True})
        except (TypeError,ValueError):
            return jsonify({"code":"upload_invalid",
                            "error":"Uploaded video metadata does not match the original reservation."}),409

    @app.get("/api/business/sources")
    def list_business_sources():
        off=disabled()
        if off is not None:return off
        user,error=current_user()
        if error is not None:return error
        org,error=load_organisation(request.args.get("organisation_id"),user)
        if error is not None:return error
        from business_sources import list_sources_for_owner
        try:
            rows=list_sources_for_owner(user["id"],org["id"])
            return jsonify({"sources":rows})
        except Exception:
            return jsonify({"code":"storage_unavailable"}),503

    @app.get("/api/business/sources/<source_id>")
    def business_source_status(source_id):
        off=disabled()
        if off is not None:return off
        user,error=current_user()
        if error is not None:return error
        if not re.fullmatch(r"[a-f0-9]{32}",str(source_id or "")):
            return jsonify({"code":"invalid_source"}),400
        # Never infer a source from source_id alone; record its exact path in
        # a user-owned org by a separate lookup query.
        from business_sources import lookup_source_by_id
        record=lookup_source_by_id(source_id,user["id"])
        if not record:
            return jsonify({"code":"not_found"}),404
        org,error=load_organisation(record["organisation_id"],user)
        if error is not None:return error
        return jsonify({"source_id":source_id,"status":record["status"],
                        "size":record["declared_size"]})


def register_offline_photo_routes(app, repo, *, root='/offline/organisations/<organisation_id>/marketing-documents/<ident>/media'):
    """Shared private SQLite media routes; caller must verify identity and scope.

    Accepts photos and bounded short MP4 originals through the same catalogue.
    Reuses trusted document auth callbacks and the existing asset catalogue.
    No upload tokens, cloud clients, new hosted schema or ownership attestations.
    """
    import uuid
    from contextlib import closing
    import business_asset_catalog as catalog
    import business_campaign_assets as assets
    import business_marketing_drafts as drafts
    from business_marketing_offline import OfflineDocumentAccessError
    from flask import Response, jsonify, request
    from werkzeug.exceptions import RequestEntityTooLarge

    app.config['MAX_CONTENT_LENGTH'] = 11 * 1024 * 1024
    with closing(repo._connect()) as con:
        catalog.initialise_originals(con)
        assets.initialise_selections(con)
        con.commit()

    @app.errorhandler(catalog.AssetError)
    @app.errorhandler(assets.CampaignAssetError)
    def invalid_asset(exc):
        if isinstance(exc,catalog.AssetIntakeConflict):
            return jsonify(code='intake_conflict', error=str(exc)), 409
        if isinstance(exc,catalog.AssetStorageLimit):
            return jsonify(code='storage_limit', error=str(exc)), 409
        return jsonify(code='invalid_asset', error=str(exc)), 400

    def owned(con, org, ident, scope):
        drafts._id(ident)
        if not repo._owned(con, ident, scope):
            raise OfflineDocumentAccessError('Document access denied')
        return drafts.read_draft(con, ident)

    # Ephemeral receipt key is local to this factory. It signs served preview
    # identity only; all reads/writes still require independent scope checks.
    import secrets, hmac, hashlib, json, time
    receipt_key=secrets.token_bytes(32)

    def preview_receipt(con, saved, scope, day, asset_id, metadata):
        binding=assets.review_binding(con,saved,scope[1],scope[0],day,asset_id,
                                      metadata['revision'],metadata['selectionVersion'])
        body=json.dumps({**binding,'previewSha256':metadata['previewSha256'],
                         **({'wholeOriginal':True} if metadata.get('wholeOriginal') else {}),
                         'expires':int(time.time())+3600},sort_keys=True,separators=(',',':'))
        return body+'.'+hmac.new(receipt_key,body.encode(),hashlib.sha256).hexdigest()

    def verify_receipt(token):
        try:
            if not isinstance(token,str) or len(token)>2400:raise ValueError()
            body,signature=token.rsplit('.',1)
            if not hmac.compare_digest(signature,hmac.new(receipt_key,body.encode(),hashlib.sha256).hexdigest()):raise ValueError()
            value=json.loads(body)
            if value['expires']<time.time():raise ValueError()
            return value
        except (ValueError,KeyError,TypeError):
            raise assets.CampaignAssetError('Preview receipt expired or invalid. Inspect the saved media again')


    @app.get(root)
    def offline_media_library(organisation_id, ident):
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            saved = owned(con, organisation_id, ident, scope)
            rows = con.execute('''SELECT asset_id FROM business_asset_originals
                WHERE organisation_id=? AND owner_id=? ORDER BY asset_id''',
                (scope[1], scope[0])).fetchall()
            items = [catalog.original(con, scope[1], scope[0], row['asset_id'])[0] for row in rows]
            return jsonify(assets=items, selection=assets.saved_selection(con, saved, scope[1], scope[0]),
                           posts=saved['document']['posts'], brandKit=saved['document'].get('brandKit'),
                           revision=saved['revision'], storage='offline_original_bytes',
                           hostedStorageVerified=False, canSpend=False, canPublish=False)

    @app.post(root)
    def offline_receive_photo(organisation_id, ident):
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            try:
                con.execute('BEGIN IMMEDIATE')
                owned(con, organisation_id, ident, scope)
                # Only authorised multipart intake needs the larger envelope.
                # Other requests retain their previous size limits.
                if request.mimetype=='multipart/form-data':
                    request.max_content_length=21*1024*1024
                if (set(request.files) != {'file'} or
                    set(request.form) != {'rightsStatement','consentStatus'} or
                    any(len(request.form.getlist(key))!=1 for key in request.form)):
                    raise catalog.AssetError('Original media and one rights declaration required')
                files=request.files.getlist('file')
                if not 1<=len(files)<=5:
                    raise catalog.AssetError('Choose one to five originals per import')
                originals=[]; size=0
                for file in files:
                    content=file.read(10*1024*1024+1)
                    size+=len(content)
                    if len(content)>10*1024*1024:
                        raise RequestEntityTooLarge('Each original must be at most 10 MB')
                    if size>20*1024*1024:
                        raise catalog.AssetError('Import at most 20 MB at once')
                    originals.append(dict(asset_id=uuid.uuid4().hex,content=content,
                                          mime=file.mimetype,name=file.filename))
                retry_id=request.headers.get('Idempotency-Key')
                replayed=False
                if retry_id is not None:
                    results,replayed=catalog.receive_retryable_originals(con, owner_id=scope[0], organisation_id=scope[1],
                        document_id=ident,intake_id=retry_id, originals=originals,
                        rights_statement=request.form['rightsStatement'],consent_status=request.form['consentStatus'])
                else:
                    results = catalog.receive_originals(con, owner_id=scope[0], organisation_id=scope[1],
                        originals=originals, rights_statement=request.form['rightsStatement'],
                        consent_status=request.form['consentStatus'])
                con.commit()
                response=jsonify(assets=results, **({'asset':results[0]} if len(results)==1 else {}),
                    storage='offline_original_bytes', hostedStorageVerified=False,
                    intakeId=retry_id,replayed=replayed)
                response.headers['Cache-Control']='no-store'
                return response, 200 if replayed else 201
            finally:
                con.rollback()

    @app.get(root+'/<asset_id>/thumbnail')
    def offline_original_thumbnail(organisation_id, ident, asset_id):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            owned(con,organisation_id,ident,scope)
            row=con.execute('''SELECT 1 FROM business_asset_originals
                WHERE organisation_id=? AND owner_id=? AND asset_id=?''',
                (scope[1],scope[0],asset_id)).fetchone()
            if row is None:raise OfflineDocumentAccessError('Document access denied')
            if not assets._video_preview_lock.acquire(blocking=False):
                raise assets.CampaignAssetError('Another media preview is rendering. Try again shortly')
            try:content,metadata=catalog.original_thumbnail(con,scope[1],scope[0],asset_id)
            finally:assets._video_preview_lock.release()
            response=jsonify(**metadata,previewBase64=base64.b64encode(content).decode('ascii'),
                             storage='offline_original_bytes',hostedStorageVerified=False)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/<asset_id>/original')
    def offline_photo_original(organisation_id, ident, asset_id):
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            owned(con, organisation_id, ident, scope)
            # Return the same denial for missing and foreign assets.
            row = con.execute('''SELECT 1 FROM business_asset_originals
                WHERE organisation_id=? AND owner_id=? AND asset_id=?''',
                (scope[1], scope[0], asset_id)).fetchone()
            if row is None:raise OfflineDocumentAccessError('Document access denied')
            item, content = catalog.original(con, scope[1], scope[0], asset_id)
            # Explicit JSON negotiation lets the existing JSON-only offline
            # transport inspect one original without unauthenticated media URLs.
            # Normal downloads keep their exact binary response. No derivatives
            # or review approvals are stored by inspecting the original.
            if request.accept_mimetypes.best == 'application/json':
                import base64
                bounds={}
                if request.args.get('photo_edit_bounds')=='1':
                    _,image=catalog.original_photo(con,scope[1],scope[0],asset_id)
                    try:bounds.update(photoWidth=image.width,photoHeight=image.height)
                    finally:image.close()
                if request.args.get('video_edit_bounds')=='1':
                    bounds['videoDurationMs']=catalog.original_video_duration_ms(con, scope[1], scope[0], asset_id)
                return jsonify(asset=item, originalBase64=base64.b64encode(content).decode('ascii'),
                               **bounds,
                               storage='offline_original_bytes', hostedStorageVerified=False,
                               canSpend=False, canPublish=False)
            return Response(content, mimetype=item['mimeType'], headers={
                'Content-Disposition':'attachment; filename="original-media"',
                'X-Content-SHA256':item['sourceSha256']})

    @app.get(root+'/posts/<int:day>/<asset_id>/original-review')
    def offline_whole_original_review(organisation_id, ident, day, asset_id):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            item,content,metadata=assets.whole_original_review(con,saved,scope[1],scope[0],day,asset_id,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int))
            # Internal scope stays in the signed receipt, not the presentation envelope.
            public={k:v for k,v in metadata.items() if k not in {'ownerId','organisationId','draftId'}}
            response=jsonify(**public,asset=item,originalBase64=base64.b64encode(content).decode('ascii'),
                reviewReceipt=preview_receipt(con,saved,scope,day,asset_id,metadata),hostedStorageVerified=False)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/<asset_id>/photo-preview')
    def offline_photo_crop_preview(organisation_id, ident, day, asset_id):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            # One read snapshot binds the saved document, selection and original.
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            row=con.execute('SELECT 1 FROM business_asset_originals WHERE organisation_id=? AND owner_id=? AND asset_id=?',
                            (scope[1],scope[0],asset_id)).fetchone()
            if row is None:raise OfflineDocumentAccessError('Document access denied')
            revision=request.args.get('revision',type=int)
            version=request.args.get('selectionVersion',type=int)
            content,metadata=assets.photo_crop_preview(con,saved,scope[1],scope[0],day,asset_id,revision,version)
            return jsonify(**metadata,reviewReceipt=preview_receipt(con,saved,scope,day,asset_id,metadata),previewBase64=base64.b64encode(content).decode('ascii'),
                           mimeType='image/png',hostedStorageVerified=False)

    @app.get(root+'/posts/<int:day>/<asset_id>/video-preview')
    def offline_video_excerpt_preview(organisation_id, ident, day, asset_id):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            row=con.execute('SELECT 1 FROM business_asset_originals WHERE organisation_id=? AND owner_id=? AND asset_id=?',
                            (scope[1],scope[0],asset_id)).fetchone()
            if row is None:raise OfflineDocumentAccessError('Document access denied')
            content,metadata=assets.video_excerpt_preview(con,saved,scope[1],scope[0],day,asset_id,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int))
            response=jsonify(**metadata,reviewReceipt=preview_receipt(con,saved,scope,day,asset_id,metadata),previewBase64=base64.b64encode(content).decode('ascii'),
                             mimeType='video/mp4',hostedStorageVerified=False)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/<asset_id>/review-package')
    def offline_media_review_package(organisation_id, ident, day, asset_id):
        import base64, hashlib
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            content,manifest=assets.review_package(con,saved,scope[1],scope[0],day,asset_id,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int),
                request.args.get('reviewVersion',type=int),request.args.get('observationSha256'))
            response=jsonify(manifest=manifest,packageBase64=base64.b64encode(content).decode('ascii'),
                packageBytes=len(content),packageSha256=hashlib.sha256(content).hexdigest(),
                approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/review-package')
    def offline_post_review_package(organisation_id, ident, day):
        import base64, hashlib
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            content,manifest=assets.post_review_package(con,saved,scope[1],scope[0],day,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int),
                request.args.get('reviewVersion',type=int))
            response=jsonify(manifest=manifest,packageBase64=base64.b64encode(content).decode('ascii'),
                packageBytes=len(content),packageSha256=hashlib.sha256(content).hexdigest(),
                approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/static-preview')
    def offline_post_static(organisation_id, ident, day):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            content,manifest=assets.post_static_preview(con,saved,scope[1],scope[0],day,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int),
                request.args.get('reviewVersion',type=int))
            response=jsonify(manifest=manifest,previewBase64=base64.b64encode(content).decode('ascii'))
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/carousel-preview')
    def offline_post_carousel(organisation_id, ident, day):
        import base64, hashlib
        import business_photo_carousel as carousel
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            files,manifest=carousel.preview(con,saved,scope[1],scope[0],day,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int),
                request.args.get('reviewVersion',type=int))
            if request.args.get('package')=='1':
                content=carousel.package(files,manifest)
                response=jsonify(manifest=manifest,packageBase64=base64.b64encode(content).decode('ascii'),
                    packageBytes=len(content),packageSha256=hashlib.sha256(content).hexdigest())
            else:
                response=jsonify(manifest=manifest,
                    slidesBase64=[base64.b64encode(content).decode('ascii') for _,content in files])
            response.headers['Cache-Control']='no-store'
            return response

    @app.get(root+'/posts/<int:day>/composition-preview')
    def offline_post_composition(organisation_id, ident, day):
        import base64
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            saved=owned(con,organisation_id,ident,scope)
            content,manifest=assets.post_composition_preview(con,saved,scope[1],scope[0],day,
                request.args.get('revision',type=int),request.args.get('selectionVersion',type=int),
                request.args.get('reviewVersion',type=int),
                audio_policy=request.args.get('audioPolicy','silent_review'))
            response=jsonify(manifest=manifest,previewBase64=base64.b64encode(content).decode('ascii'))
            response.headers['Cache-Control']='no-store'
            return response

    @app.put(root+'/posts/<int:day>/<asset_id>/review-note')
    def offline_media_review_note(organisation_id, ident, day, asset_id):
        scope=repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            try:
                con.execute('BEGIN IMMEDIATE')
                saved=owned(con,organisation_id,ident,scope)
                result=assets.record_review_note(con,saved,scope[1],scope[0],day,asset_id,
                    request.get_json(silent=True),verify_receipt=verify_receipt)
                response=jsonify(selection=result,approved=False,canSpend=False,canPublish=False)
                con.commit()
                return response
            finally:con.rollback()

    @app.put(root+'/selection')
    def offline_select_photos(organisation_id, ident):
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            try:
                con.execute('BEGIN IMMEDIATE')
                saved = owned(con, organisation_id, ident, scope)
                result = assets.select_assets(con, saved, scope[1], scope[0], request.get_json(silent=True))
                con.commit()
                return jsonify(selection=result, canSpend=False, canPublish=False)
            finally:
                con.rollback()

    @app.post(root+'/<asset_id>/withdraw-permission')
    def offline_withdraw_photo_permission(organisation_id, ident, asset_id):
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            try:
                con.execute('BEGIN IMMEDIATE')
                saved = owned(con, organisation_id, ident, scope)
                row = con.execute('''SELECT 1 FROM business_asset_originals
                    WHERE organisation_id=? AND owner_id=? AND asset_id=?''',
                    (scope[1], scope[0], asset_id)).fetchone()
                if row is None:raise OfflineDocumentAccessError('Document access denied')
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or set(payload) != {'reason'}:
                    raise catalog.AssetError('A withdrawal reason is required')
                item = catalog.withdraw_permission(con, scope[1], scope[0], asset_id, payload['reason'])
                selection = assets.saved_selection(con, saved, scope[1], scope[0])
                con.commit()
                return jsonify(asset=item, selection=selection, canSpend=False, canPublish=False,
                               storage='offline_original_bytes', hostedStorageVerified=False)
            finally:
                con.rollback()
