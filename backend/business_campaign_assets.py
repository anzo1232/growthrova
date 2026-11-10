"""Campaign-bound media planning and offline selections; no approval or generation."""
import business_asset_planning as planning
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_campaign_identity as identity
import business_asset_catalog as catalog
import json
import threading

_video_preview_lock = threading.Lock()

def observation_hash(note):
    # Presentation flags and this derived identity are never persisted.
    return contracts._hash({k:v for k,v in note.items() if k not in {'stale','observationSha256'}})

def initialise_selections(con):
    con.execute('''CREATE TABLE IF NOT EXISTS business_campaign_asset_selections(
        draft_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
        document_sha TEXT NOT NULL, selection_version INTEGER NOT NULL,
        asset_ids TEXT NOT NULL)''')
    # Dedicated offline catalogue only; no hosted schema or deployed migration.
    if 'post_assignments' not in {r[1] for r in con.execute('PRAGMA table_info(business_campaign_asset_selections)')}:
        con.execute("ALTER TABLE business_campaign_asset_selections ADD COLUMN post_assignments TEXT NOT NULL DEFAULT '[]'")

    columns={r[1] for r in con.execute('PRAGMA table_info(business_campaign_asset_selections)')}
    for name, declaration in [('review_notes', "TEXT NOT NULL DEFAULT '[]'"),
                              ('review_version', 'INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:
            con.execute(f'ALTER TABLE business_campaign_asset_selections ADD COLUMN {name} {declaration}')

def saved_selection(con, saved, organisation_id, owner_id):
    """Planning selection only. Any saved document revision invalidates its review."""
    row=con.execute('SELECT * FROM business_campaign_asset_selections WHERE draft_id=?',
                    (saved['id'],)).fetchone()
    ids=json.loads(row['asset_ids']) if row else []
    assignments=json.loads(row['post_assignments']) if row else []
    items=[catalog.original(con,organisation_id,owner_id,ident)[0] for ident in ids]
    current=bool(row and row['revision']==saved['revision'] and
                 row['document_sha']==contracts._hash(saved['document']))
    blocked=[item['assetId'] for item in items if item.get('permissionWithdrawn')]
    days={p['day'] for p in saved['document']['posts']}
    orphaned=[a['day'] for a in assignments if a['day'] not in days]
    current=current and not blocked and not orphaned
    return {'assetIds':ids,'assets':items,'selectionVersion':row['selection_version'] if row else 0,
            'postAssignments':assignments,'orphanedDays':orphaned,
            'reviewVersion':row['review_version'] if row else 0,
            'reviewNotes':[{**note,'observationSha256':observation_hash(note),
                            'stale':not current or note['selectionVersion']!=row['selection_version']}
                           for note in json.loads(row['review_notes'])] if row else [],
            'blockedAssetIds':blocked,
            'status':'candidate_selection_pending_review' if current else 'selection_requires_review',
            'stale':bool(row and not current),'approved':False,'canSpend':False,'canPublish':False}

def select_assets(con, saved, organisation_id, owner_id, payload):
    required={'revision','selectionVersion','assetIds'}
    if not isinstance(payload,dict) or not required.issubset(payload) or set(payload)-required-{'postAssignments'}:
        raise CampaignAssetError('Selection details required')
    ids=payload['assetIds']
    if not isinstance(ids,list) or len(ids)>30 or any(not isinstance(x,str) or not catalog.ID.fullmatch(x) for x in ids) or len(ids)!=len(set(ids)):
        raise CampaignAssetError('Select at most thirty distinct assets')
    if type(payload['revision']) is not int or payload['revision']!=saved['revision']:
        raise drafts.MarketingDraftError('Reload the current campaign before selecting media','revision_conflict',409)
    old=saved_selection(con,saved,organisation_id,owner_id)
    if type(payload['selectionVersion']) is not int or payload['selectionVersion']!=old['selectionVersion']:
        raise drafts.MarketingDraftError('Media selection changed. Reload before saving','revision_conflict',409)
    if 'postAssignments' not in payload and old['postAssignments']:
        raise CampaignAssetError('Review existing post assignments before saving media')
    for ident in ids:
        item,_=catalog.original(con,organisation_id,owner_id,ident)
        if item.get('permissionWithdrawn'):raise CampaignAssetError('Permission for this asset was withdrawn. Remove it from the selection')
        if item['consentStatus']!='owner_asserted':raise CampaignAssetError('Declare rights before selecting this asset')
    assignments=payload.get('postAssignments',[])
    days={p['day'] for p in saved['document']['posts']}
    seen=set(); durations={}; photo_sizes={}
    previous={a['day']:a for a in old['postAssignments']}
    if not isinstance(assignments,list) or len(assignments)>30:
        raise CampaignAssetError('Assign media to at most thirty calendar posts')
    for entry in assignments:
        if not isinstance(entry,dict) or not {'day','assetIds'}.issubset(entry) or set(entry)-{'day','assetIds','videoEdits','photoCrops','staticLogoAssetId','carouselSlides','carouselCaptions'}:
            raise CampaignAssetError('Post day and media IDs required')
        day=entry['day'];photos=entry['assetIds']
        if type(day) is not int or day not in days or day in seen:
            raise CampaignAssetError('Choose distinct days from the current saved calendar')
        seen.add(day)
        if (not isinstance(photos,list) or not 1<=len(photos)<=5 or
            any(not isinstance(x,str) or x not in ids for x in photos) or len(set(photos))!=len(photos)):
            raise CampaignAssetError('Each post needs one to five distinct selected originals')
        if previous.get(day,{}).get('videoEdits') and 'videoEdits' not in entry:
            raise CampaignAssetError('Review existing video edits before saving this post')
        edits=entry.get('videoEdits',[])
        if not isinstance(edits,list) or len(edits)>len(photos):
            raise CampaignAssetError('Provide at most one edit per assigned video')
        edited=set()
        for edit in edits:
            if not isinstance(edit,dict) or set(edit)!={'assetId','startMs','endMs','muted'}:
                raise CampaignAssetError('Video asset, in/out points and mute choice required')
            asset=edit['assetId'];start=edit['startMs'];end=edit['endMs']
            if (not isinstance(asset,str) or asset not in photos or asset in edited or
                type(start) is not int or type(end) is not int or type(edit['muted']) is not bool or
                not 0<=start<end<=60000 or end-start<250):
                raise CampaignAssetError('Choose a distinct assigned video and an excerpt of at least 250 ms')
            edited.add(asset)
            if asset not in durations:
                durations[asset]=catalog.original_video_duration_ms(con,organisation_id,owner_id,asset)
            if end>durations[asset]:
                raise CampaignAssetError('Video out point exceeds the original video duration')
        if previous.get(day,{}).get('photoCrops') and 'photoCrops' not in entry:
            raise CampaignAssetError('Review existing photo crops before saving this post')
        if previous.get(day,{}).get('staticLogoAssetId') and 'staticLogoAssetId' not in entry:
            raise CampaignAssetError('Review the existing static logo choice before saving this post')
        logo_id=entry.get('staticLogoAssetId','')
        if not isinstance(logo_id,str) or (logo_id and logo_id not in photos):
            raise CampaignAssetError('Choose a logo from this post’s assigned originals, or explicitly choose no logo')
        if logo_id and catalog.original(con,organisation_id,owner_id,logo_id)[0]['mediaKind']!='photo':
            raise CampaignAssetError('Choose a saved photo for the static logo')
        if previous.get(day,{}).get('carouselSlides') and 'carouselSlides' not in entry:
            raise CampaignAssetError('Review the existing carousel words before saving this post')
        if 'carouselSlides' in entry:
            slides=entry['carouselSlides']
            if not isinstance(slides,list) or len(slides)>5:
                raise CampaignAssetError('Prepare at most five carousel slides')
            slide_ids=set()
            for slide in slides:
                if (not isinstance(slide,dict) or set(slide)!={'assetId','graphicText','callToAction'}
                    or not isinstance(slide['assetId'],str) or slide['assetId'] not in photos
                    or slide['assetId']==logo_id or slide['assetId'] in slide_ids):
                    raise CampaignAssetError('Each carousel slide needs a distinct assigned photo, separate from the logo')
                slide_ids.add(slide['assetId'])
                if catalog.original(con,organisation_id,owner_id,slide['assetId'])[0]['mediaKind']!='photo':
                    raise CampaignAssetError('Carousel slides support photos only')
                for field,limit in [('graphicText',600),('callToAction',180)]:
                    if (not isinstance(slide[field],str) or len(slide[field])>limit
                        or any(ord(c)<32 and c not in '\n\t' for c in slide[field])):
                        raise CampaignAssetError('Use bounded plain text for each carousel slide')
        if previous.get(day,{}).get('carouselCaptions') and 'carouselCaptions' not in entry:
            raise CampaignAssetError('Review existing carousel channel captions before saving this post')
        if 'carouselCaptions' in entry:
            captions=entry['carouselCaptions']
            if (not isinstance(captions,dict) or set(captions)-{'instagram','facebook','linkedin','tiktok','x'}
                    or any(not isinstance(text,str) or not text.strip() or len(text)>3000
                           or any(ord(c)<32 and c not in '\n\t' for c in text) for text in captions.values())):
                raise CampaignAssetError('Choose supported handoff channels with nonempty captions up to 3000 characters')
            # These are saved preparation words, never provider eligibility or approval.
            if captions and len(entry.get('carouselSlides',[]))<2:
                raise CampaignAssetError('Prepare at least two carousel slides before saving channel captions')
        crops=entry.get('photoCrops',[])
        if not isinstance(crops,list) or len(crops)>len(photos):
            raise CampaignAssetError('Provide at most one crop per assigned photo')
        cropped=set()
        for crop in crops:
            if not isinstance(crop,dict) or not isinstance(crop.get('assetId'),str):
                raise CampaignAssetError('Assigned photo required for cropping')
            asset=crop['assetId']
            if asset==logo_id:
                raise CampaignAssetError('Use the whole original logo; remove its crop before selecting it as a logo')
            if asset not in photos or asset in cropped:
                raise CampaignAssetError('Choose a distinct assigned photo for each crop')
            cropped.add(asset)
            if asset not in photo_sizes:
                _,image=catalog.original_photo(con,organisation_id,owner_id,asset)
                try:photo_sizes[asset]=image.size
                finally:image.close()
            catalog.validate_photo_crop(crop,photo_sizes[asset])
    con.execute('''INSERT INTO business_campaign_asset_selections
        (draft_id,revision,document_sha,selection_version,asset_ids,post_assignments) VALUES(?,?,?,?,?,?)
        ON CONFLICT(draft_id) DO UPDATE SET revision=excluded.revision,document_sha=excluded.document_sha,
        selection_version=excluded.selection_version,asset_ids=excluded.asset_ids,post_assignments=excluded.post_assignments''',
                (saved['id'],saved['revision'],contracts._hash(saved['document']),old['selectionVersion']+1,
                 json.dumps(ids),json.dumps(sorted(assignments,key=lambda a:a['day']))))
    return saved_selection(con,saved,organisation_id,owner_id)

class CampaignAssetError(ValueError):pass

def overview(con,draft_id,revision,organisation_id,business_id,*,kind=None):
    try:
        saved=drafts.read_draft(con,draft_id)
        if type(revision) is not int or saved['revision']!=revision:
            raise CampaignAssetError('Current saved campaign revision required')
        document=saved['document']
        identity.require(con,draft_id,revision,organisation_id,business_id)
        assets=planning.shortlist(con,organisation_id,business_id,kind=kind)
    except (drafts.MarketingDraftError,planning.PlanningError,identity.BindingError) as exc:
        raise CampaignAssetError(str(exc)) from exc
    return {'draftId':draft_id,'revision':revision,
            'documentSha256':contracts._hash(document),
            'business':business_id,'assetCandidates':assets['assets'],
            'assetCount':len(assets['assets']),
            'requiresIndependentRightsAndRelevanceReview':True,
            'ownerAssetsInProduction':False,'canGenerate':False,
            'canPublish':False,'canSpend':False}


def photo_crop_preview(con, saved, organisation_id, owner_id, day, asset_id, revision, version):
    """Render only a current saved candidate, without persisting or approving output."""
    import io, hashlib
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if (revision!=saved['revision'] or version!=selection['selectionVersion'] or selection['stale']):
        raise drafts.MarketingDraftError('Reload and review the current campaign media first','revision_conflict',409)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    crop=next((c for c in (assignment or {}).get('photoCrops',[]) if c['assetId']==asset_id),None)
    if not crop or asset_id not in assignment['assetIds']:
        raise CampaignAssetError('Save a crop for this assigned photo before previewing')
    item,image=catalog.original_photo(con,organisation_id,owner_id,asset_id)
    try:
        box=catalog.validate_photo_crop(crop,image.size)
        with image.crop(box) as output:
            # Bounded review image; full resolution original remains in catalogue.
            output.thumbnail((1200,1200))
            output.info.clear()  # Do not carry EXIF/GPS or source metadata into review pixels.
            buf=io.BytesIO();output.save(buf,format='PNG')
            content=buf.getvalue()
            return content,dict(assetId=asset_id,sourceSha256=item['sourceSha256'],
                previewSha256=hashlib.sha256(content).hexdigest(),crop=crop,
                width=output.width,height=output.height,revision=revision,selectionVersion=version,
                day=day,approved=False,canSpend=False,canPublish=False)
    finally:image.close()


def video_excerpt_preview(con, saved, organisation_id, owner_id, day, asset_id, revision, version):
    """Render one saved excerpt for offline review; never attach it as an original.

    This catalogue uses authenticated immutable document scope, unlike the local
    reel workbench's source IDs. Do not bridge its owner attestations into here.
    Caller holds a single read snapshot. No persisted derivative or approval.
    """
    import hashlib, math, subprocess, tempfile
    from pathlib import Path
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if revision!=saved['revision'] or version!=selection['selectionVersion'] or selection['stale']:
        raise drafts.MarketingDraftError('Reload and review the current campaign media first','revision_conflict',409)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    edit=next((e for e in (assignment or {}).get('videoEdits',[]) if e['assetId']==asset_id),None)
    if not edit or asset_id not in assignment['assetIds']:
        raise CampaignAssetError('Save an excerpt for this assigned video before rendering')
    item,content=catalog.original(con,organisation_id,owner_id,asset_id)
    if item['mediaKind']!='video' or item.get('permissionWithdrawn') or item['consentStatus']!='owner_asserted':
        raise CampaignAssetError('Video permission is required before rendering')
    if (set(edit)!={'assetId','startMs','endMs','muted'} or type(edit['startMs']) is not int or
        type(edit['endMs']) is not int or type(edit['muted']) is not bool or
        not 0<=edit['startMs']<edit['endMs']<=60000 or edit['endMs']-edit['startMs']<250):
        raise CampaignAssetError('Invalid saved video excerpt')
    if not _video_preview_lock.acquire(blocking=False):
        raise CampaignAssetError('Another video review is rendering. Try again shortly')
    try:
        with tempfile.TemporaryDirectory(prefix='clippr-video-review-') as folder:
            source=Path(folder)/'original.mp4';target=Path(folder)/'review.mp4'
            source.write_bytes(content)
            info=catalog.probe_offline_video(source)
            video=next(s for s in info['streams'] if s['codec_type']=='video')
            durations=[float(info['format']['duration']),float(video['duration'])]
            if any(not math.isfinite(d) for d in durations) or edit['endMs']>math.floor(min(durations)*1000):
                raise CampaignAssetError('Saved excerpt exceeds the original video duration')
            seconds=(edit['endMs']-edit['startMs'])/1000
            audio=[]
            if not edit['muted'] and any(s['codec_type']=='audio' for s in info['streams']):
                # Excerpt offsets are measured from the first video frame, as
                # in the player and composition renderer, not container start.
                origin=float(video['start_time'])-float(info['format']['start_time'])
                if not math.isfinite(origin) or not 0<=origin<=60:
                    raise CampaignAssetError('Cannot align saved audio with video')
                # Materialise the source timeline's silent gaps BEFORE output
                # seeking. Otherwise an excerpt wholly before/after the audio
                # has no track and fails review; a partial gap may be skipped by
                # a player. Pad only an existing track, never invent sound for a
                # muted/trackless original. Output -t bounds the padded stream.
                audio=['-map','0:a:0','-af',
                       f'asetpts=PTS-({origin})/TB,aresample=48000:async=1:first_pts=0,apad',
                       '-c:a','aac','-b:a','96k']
            result=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-err_detect','explode',
                '-protocol_whitelist','file','-format_whitelist','mov','-enable_drefs','0',
                '-threads','1','-i',str(source),'-ss',str(edit['startMs']/1000),'-t',str(seconds),
                '-map','0:v:0',*audio,*(['-an'] if edit['muted'] else []),
                '-map_metadata','-1','-map_chapters','-1',
                '-vf','setpts=PTS-STARTPTS,scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=24',
                '-c:v','libx264','-threads','1','-filter_threads','1','-preset','ultrafast',
                '-pix_fmt','yuv420p','-b:v','800k','-maxrate','1000k','-bufsize','2000k',
                '-fs',str(10*1024*1024),'-movflags','+faststart',str(target)],
                capture_output=True,timeout=45,check=True)
            if result.stderr.strip() or not 0<target.stat().st_size<=10*1024*1024:
                raise CampaignAssetError('Video review could not be rendered safely')
            output=catalog.probe_offline_video(target)
            actual=float(output['format']['duration'])
            has_audio=any(s['codec_type']=='audio' for s in output['streams'])
            expected_audio=not edit['muted'] and any(s['codec_type']=='audio' for s in info['streams'])
            if abs(actual-seconds)>0.125 or has_audio!=expected_audio:
                raise CampaignAssetError('Rendered excerpt duration or audio did not match saved settings')
            catalog.validate_offline_video(target)
            rendered=target.read_bytes()
            return rendered,dict(assetId=asset_id,sourceSha256=item['sourceSha256'],edit=edit,
                previewSha256=hashlib.sha256(rendered).hexdigest(),previewBytes=len(rendered),
                durationMs=round(actual*1000),hasAudio=has_audio,day=day,revision=revision,
                selectionVersion=version,approved=False,canSpend=False,canPublish=False)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        raise CampaignAssetError('Video review unavailable. Keep the original and retry after checking saved settings') from exc
    finally:
        _video_preview_lock.release()


def review_binding(con, saved, organisation_id, owner_id, day, asset_id, revision, version):
    """Exact saved candidate identity; never a rights or quality verdict."""
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if (type(revision) is not int or type(version) is not int or revision!=saved['revision'] or
        version!=selection['selectionVersion'] or selection['stale']):
        raise drafts.MarketingDraftError('Reload and inspect the current saved media','revision_conflict',409)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    if not assignment or asset_id not in assignment['assetIds']:
        raise CampaignAssetError('Review requires a saved post assignment')
    item,_=catalog.original(con,organisation_id,owner_id,asset_id)
    if item.get('permissionWithdrawn') or item['consentStatus']!='owner_asserted':
        raise CampaignAssetError('Current media permission required')
    return dict(draftId=saved['id'],organisationId=organisation_id,ownerId=owner_id,
                day=day,assetId=asset_id,revision=revision,selectionVersion=version,
                sourceSha256=item['sourceSha256'],documentSha256=contracts._hash(saved['document']),
                assignmentSha256=contracts._hash(assignment))


def whole_original_review(con, saved, organisation_id, owner_id, day, asset_id, revision, version):
    """Inspect an unchanged saved candidate using exact original bytes, no render/store."""
    binding=review_binding(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
    selection=saved_selection(con,saved,organisation_id,owner_id)
    assignment=next(a for a in selection['postAssignments'] if a['day']==day)
    if any(e['assetId']==asset_id for key in ('photoCrops','videoEdits') for e in assignment.get(key,[])):
        raise CampaignAssetError('Inspect the saved crop or excerpt for this edited candidate')
    item,content=catalog.original(con,organisation_id,owner_id,asset_id)
    return item,content,dict(**binding,previewSha256=item['sourceSha256'],
        wholeOriginal=True,approved=False,canSpend=False,canPublish=False)


def _review_candidate(con, saved, organisation_id, owner_id, day, asset_id,
                   revision, version, review_version, observation_sha):
    """Download one observed candidate for independent QC, never a final export.

    Caller authenticates and holds a read snapshot. Reuse the existing renderers;
    require byte equality with the observation rather than silently exporting a
    new candidate. No package, derivative, or approval is persisted.
    """
    import hashlib
    binding=review_binding(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
    selection=saved_selection(con,saved,organisation_id,owner_id)
    note=next((n for n in selection['reviewNotes'] if (n['day'],n['assetId'])==(day,asset_id)),None)
    if (type(review_version) is not int or review_version!=selection['reviewVersion'] or
        not note or note['stale'] or observation_sha!=note['observationSha256']):
        raise drafts.MarketingDraftError('Reload the current saved observation before downloading','revision_conflict',409)
    if any(note.get(k)!=binding[k] for k in ('revision','selectionVersion','sourceSha256','documentSha256','assignmentSha256')):
        raise CampaignAssetError('Observe the current saved candidate before downloading')
    item,_=catalog.original(con,organisation_id,owner_id,asset_id)
    assignment=next(a for a in selection['postAssignments'] if a['day']==day)
    edit=next((e for key in ('photoCrops','videoEdits') for e in assignment.get(key,[]) if e['assetId']==asset_id),
              dict(assetId=asset_id,wholeOriginal=True))
    if note.get('candidateEdit')!=edit:
        raise CampaignAssetError('Observe the current saved edit before downloading')
    if edit.get('wholeOriginal'):
        _,content,metadata=whole_original_review(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
        mime=item['mimeType']
    elif item['mediaKind']=='photo':
        content,metadata=photo_crop_preview(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
        mime='image/png'
    else:
        content,metadata=video_excerpt_preview(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
        mime='video/mp4'
    if metadata['previewSha256']!=note['previewSha256'] or hashlib.sha256(content).hexdigest()!=note['previewSha256']:
        raise CampaignAssetError('Rendered bytes changed. Inspect and record a fresh observation before downloading')
    filename='candidate'+{'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','video/mp4':'.mp4'}[mime]
    manifest=dict(schemaVersion=1,purpose='independent_qc_review',
        **{k:v for k,v in binding.items() if k not in {'ownerId','organisationId'}},
        reviewVersion=review_version,observationSha256=observation_sha,
        candidateFile=filename,candidateMimeType=mime,candidateBytes=len(content),
        previewSha256=note['previewSha256'],candidateEdit=edit,
        post=next(p for p in saved['document']['posts'] if p['day']==day),
        ownerObservation=note,
        rightsDeclaration=dict(statement=item['rightsStatement'],consentStatus=item['consentStatus'],independentlyVerified=False),
        containsOriginalMetadata=bool(edit.get('wholeOriginal')),
        requiresIndependentQC=True,requiresOwnerApproval=True,
        approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
    return content,manifest


_REVIEW_NOTICE = (b'UNAPPROVED QC REVIEW COPY\n'
    b'Owner observations and rights declarations are not independent QC, proof of rights or approval.\n'
    b'Calendar copy is draft context; claims remain unverified. Do not publish this package.\n'
    b'Whole originals retain metadata. Downloaded copies cannot be recalled after permission withdrawal.\n')
POST_REVIEW_LIMIT = 25 * 1024 * 1024


def _post_review_page(manifest):
    """Read-only offline consumption of the existing handoff; no review authority.

    All owner text is inert, including URLs. Only fixed package media paths may
    become resource attributes. No scripts, submissions or external resources.
    """
    import html, re
    escape=lambda value:html.escape(str(value),quote=True)
    def details(values):
        return '<dl>'+''.join('<dt>'+escape(key)+'</dt><dd><pre>'+escape(
            json.dumps(value,ensure_ascii=False,indent=2) if isinstance(value,(dict,list)) else value
        )+'</pre></dd>' for key,value in values.items())+'</dl>'
    cards=[];navigation=[]
    for index,candidate in enumerate(manifest['candidates'],1):
        path=candidate['candidateFile']
        if not re.fullmatch(r'media/'+f'{index:02d}'+r'/candidate\.(png|jpg|webp|mp4)',path):
            raise CampaignAssetError('Unsafe review media path')
        video=candidate['candidateMimeType']=='video/mp4'
        if video!=(path.endswith('.mp4')):raise CampaignAssetError('Review media type changed')
        navigation.append(f'<a href="#candidate-{index}">Candidate {index}</a>')
        media=(f'<video controls preload="none" src="{path}"></video>' if video else
               f'<img src="{path}" alt="Saved candidate {index}; inspect against the draft context below">')
        note=candidate['ownerObservation']
        response=note.get('revisionResponse')
        revision=(' <h3>Owner revision response</h3>'+details({
            'Edit description':response['changeSummary'],
            'Immediate previous request (previous media is not included)':response['previousObservation']})
            if response else '')
        cards.append(f'<section id="candidate-{index}"><h2>Candidate {index}</h2>'+media+
            details({'Asset':candidate['assetId'],'Saved edit':candidate['candidateEdit'],
                     'Original SHA-256':candidate['sourceSha256'],'Candidate SHA-256':candidate['previewSha256'],
                     'Observation SHA-256':candidate['observationSha256']})+
            '<h3>Owner observation — not independent QC</h3>'+details({
                'Outcome':note['outcome'],'Observed relevance / requested changes':note['note'],
                'Recorded by':note['reviewedBy'],'Recorded at':note['recordedAt']})+revision+
            '<h3>Rights declaration — unverified</h3>'+details(candidate['rightsDeclaration'])+
            ('<p>Whole original: original metadata is retained.</p>' if candidate['containsOriginalMetadata'] else '')+
            '</section>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'img-src \'self\'; media-src \'self\'; style-src \'unsafe-inline\'; '
        'script-src \'none\'; connect-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Unapproved post media review</title><style>'
        'body{font:18px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;color:#182124}'
        'section{border-top:2px solid #777;margin-top:2rem;padding-top:1rem}'
        'img,video{display:block;max-width:100%;max-height:75vh;background:#eee}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0}'
        'dt{font-weight:bold;margin-top:1rem}dd{margin-left:0}nav a{margin-right:1rem}'
        '@media print{nav{display:none}section{break-before:page}}'
        '</style></head><body><h1>Unapproved post media review</h1>'
        '<p>Extract the entire ZIP to one folder, then open REVIEW.html. Keep the media folder beside it. '
        'If a candidate does not display or play, open its file directly; do not mark it reviewed.</p>'
        '<p>This page records no decisions. Independent QC and owner approval remain required. '
        'No spending, delivery, scheduling or publication is authorised. '
        'Owner notes and rights assertions do not prove authenticity, permission or quality. '
        'Downloaded copies cannot be recalled after permission withdrawal. Recheck current permission and versions before further use.</p>'
        '<nav aria-label="Candidates">'+''.join(navigation)+'</nav><h2>Saved draft post context — claims unverified</h2>'+
        details(manifest['post'])+'<h2>Handoff identity</h2>'+details({key:manifest[key] for key in
            ('draftId','day','revision','selectionVersion','reviewVersion','documentSha256','assignmentSha256')})+
        '<h2>Independent assessment still needed</h2><p>Inspect every image at full size and every video '
        'through its full duration, including audio. Compare relevance, framing, continuity, legibility, '
        'claims and requested changes against the saved draft. Record findings with candidate hashes '
        'through the authorised review workflow. This page cannot submit findings or grant approval.</p>'+
        ''.join(cards)+'<p>manifest.json contains the machine-readable bindings. '
        'This is a saved-media review, not an assembled final creative or final-export review.</p></body></html>').encode('utf-8')


def _review_archive(files, manifest, limit):
    import io, zipfile
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        for name,data in [*files,('manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode()),
                          ('REVIEW-NOT-APPROVED.txt',_REVIEW_NOTICE)]:
            # Include central-directory overhead before allocating the next entry.
            if output.tell()+len(data)+2*len(name.encode())+200>limit:
                raise CampaignAssetError('Review package exceeds the offline download limit')
            archive.writestr(zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0)),data)
    package=output.getvalue()
    if len(package)>limit:raise CampaignAssetError('Review package exceeds the offline download limit')
    return package,manifest


def review_package(con, saved, organisation_id, owner_id, day, asset_id,
                   revision, version, review_version, observation_sha):
    content,manifest=_review_candidate(con,saved,organisation_id,owner_id,day,asset_id,
                                      revision,version,review_version,observation_sha)
    return _review_archive([(manifest['candidateFile'],content)],manifest,11*1024*1024)


def post_review_package(con, saved, organisation_id, owner_id, day, revision, version, review_version):
    """All saved media for one post, in assignment order; never omit held candidates.

    Authentication and a single read snapshot belong to the caller. No independent
    reviewer authority is inferred, and no assets, notes or approvals are written.
    """
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if (type(review_version) is not int or review_version!=selection['reviewVersion']):
        raise drafts.MarketingDraftError('Reload current observations before downloading','revision_conflict',409)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    if not assignment or not 1<=len(assignment['assetIds'])<=5:
        raise CampaignAssetError('Save one to five originals for this calendar post first')
    notes=[]
    # Check the complete set before any potentially expensive rendering.
    for asset_id in assignment['assetIds']:
        review_binding(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
        note=next((n for n in selection['reviewNotes'] if n['day']==day and n['assetId']==asset_id),None)
        if not note or note['stale']:
            raise CampaignAssetError('Inspect and record a current observation for every saved original in this post')
        notes.append(note)
    files=[];candidates=[];total=0
    for index,note in enumerate(notes,1):
        content,metadata=_review_candidate(con,saved,organisation_id,owner_id,day,note['assetId'],
            revision,version,review_version,note['observationSha256'])
        total+=len(content)
        if total>POST_REVIEW_LIMIT:
            raise CampaignAssetError('Post review exceeds 25 MB. Download individual candidate packages instead')
        filename=f"media/{index:02d}/"+metadata['candidateFile']
        files.append((filename,content));candidates.append({**metadata,'candidateFile':filename})
    manifest=dict(schemaVersion=1,purpose='independent_post_qc_review',draftId=saved['id'],
        day=day,revision=revision,selectionVersion=version,reviewVersion=review_version,
        documentSha256=contracts._hash(saved['document']),assignmentSha256=contracts._hash(assignment),
        post=next(p for p in saved['document']['posts'] if p['day']==day),candidates=candidates,
        containsOriginalMetadata=any(c['containsOriginalMetadata'] for c in candidates),
        requiresIndependentQC=True,requiresOwnerApproval=True,
        approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
    import hashlib
    page=_post_review_page(manifest)
    manifest['reviewPage']=dict(file='REVIEW.html',bytes=len(page),sha256=hashlib.sha256(page).hexdigest())
    return _review_archive([('REVIEW.html',page),*files],manifest,POST_REVIEW_LIMIT)


def observed_static_candidate(con, saved, organisation_id, owner_id, day, asset_id,
                              revision, version, review_version, *, logo=False):
    """Resolve a current observed photo/whole logo through the catalogue contract."""
    selection=saved_selection(con,saved,organisation_id,owner_id)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    review_binding(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
    item,_=catalog.original(con,organisation_id,owner_id,asset_id)
    if item['mediaKind']!='photo':
        raise CampaignAssetError('Assign photos for static artwork; saved videos remain unchanged')
    if logo and any(c['assetId']==asset_id for c in assignment.get('photoCrops',[])):
        raise CampaignAssetError('Use the whole original logo, without a crop')
    note=next((n for n in selection['reviewNotes'] if n['day']==day and n['assetId']==asset_id),None)
    if not note or note['stale'] or note['outcome']!='usable_candidate':
        raise CampaignAssetError('Inspect the saved photo and logo and record current usable-candidate observations first')
    return _review_candidate(con,saved,organisation_id,owner_id,day,asset_id,
        revision,version,review_version,note['observationSha256'])


def render_static_candidate(content, brand, post, logo_content=None, *, frame='portrait', layout='standard'):
    """Shared exact-brand/copy renderer for genuine and labelled generated pixels."""
    import io
    from contextlib import ExitStack
    from PIL import Image
    from business_brand_render import compose_static_post, BrandRenderError
    try:
        with ExitStack() as stack:
            image=stack.enter_context(Image.open(io.BytesIO(content)))
            logo=stack.enter_context(Image.open(io.BytesIO(logo_content))) if logo_content else None
            words=post.get('graphicText','').strip() or post['copyDraft']
            pixels,layout_manifest=compose_static_post(image,brand,words,post['callToAction'],logo=logo,frame=frame,layout=layout)
        try:
            output=io.BytesIO();pixels.save(output,format='PNG');content=output.getvalue()
        finally:pixels.close()
    except BrandRenderError as exc:
        raise CampaignAssetError(str(exc)) from exc
    return content,layout_manifest


def post_static_preview(con, saved, organisation_id, owner_id, day, revision, version, review_version):
    """Ephemeral static draft using the existing exact observed-candidate contract."""
    import hashlib
    selection=saved_selection(con,saved,organisation_id,owner_id)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    logo_id=(assignment or {}).get('staticLogoAssetId','')
    photo_ids=[ident for ident in (assignment or {}).get('assetIds',[]) if ident!=logo_id]
    if len(photo_ids)!=1 or (logo_id and logo_id not in assignment['assetIds']):
        raise CampaignAssetError('Save exactly one observed photo and optionally one explicitly selected logo, or use the carousel preview for multiple photos')
    # Resolve every role through the same observation/permission contract.
    rendered=[observed_static_candidate(con,saved,organisation_id,owner_id,day,asset_id,
        revision,version,review_version,logo=asset_id==logo_id)
        for asset_id in photo_ids+([logo_id] if logo_id else [])]
    content,candidate=rendered[0]
    brand=saved['document'].get('brandKit')
    post=next(p for p in saved['document']['posts'] if p['day']==day)
    issue=drafts.marketing_copy_issue(post,saved['document']['business'])
    if issue:
        raise CampaignAssetError('Edit the saved post words before composing: '+issue)
    content,layout=render_static_candidate(content,brand,post,rendered[1][0] if logo_id else None)
    manifest=dict(schemaVersion=1,purpose='unapproved_static_post',draftId=saved['id'],day=day,
        revision=revision,selectionVersion=version,reviewVersion=review_version,
        documentSha256=contracts._hash(saved['document']),assignmentSha256=contracts._hash(assignment),
        post=post,brandKit=brand,candidates=[candidate],layout=layout,logoIncluded=bool(logo_id),
        width=1080,height=1350,frameFit='contain',previewBytes=len(content),
        previewSha256=hashlib.sha256(content).hexdigest(),requiresIndependentQC=True,
        requiresOwnerApproval=True,approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
    if logo_id:manifest['logoCandidate']=rendered[1][1]
    return content,manifest


def post_composition_preview(con, saved, organisation_id, owner_id, day, revision, version, review_version,
                             audio_policy="silent_review"):
    """Ephemeral draft from exact observed catalogue candidates, no approval.

    Caller authenticates and holds a read snapshot. Reuse candidate validation
    and the existing cut renderer, without creating a workbench project or
    accepting its local owner attestations as catalogue ownership.
    """
    import hashlib, io, math, tempfile
    from pathlib import Path
    from PIL import Image, ImageOps
    import business_reel_workbench as reel
    if audio_policy not in ("silent_review","saved_candidate_audio"):
        raise CampaignAssetError("Choose silent review or saved candidate audio")
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if type(review_version) is not int or review_version!=selection['reviewVersion']:
        raise drafts.MarketingDraftError('Reload current observations before composing','revision_conflict',409)
    assignment=next((a for a in selection['postAssignments'] if a['day']==day),None)
    if not assignment or not 1<=len(assignment['assetIds'])<=5:
        raise CampaignAssetError('Save one to five originals for this post first')
    notes=[]
    for asset_id in assignment['assetIds']:
        review_binding(con,saved,organisation_id,owner_id,day,asset_id,revision,version)
        note=next((n for n in selection['reviewNotes'] if n['day']==day and n['assetId']==asset_id),None)
        if not note or note['stale'] or note['outcome']=='unsuitable':
            raise CampaignAssetError('Inspect and record current usable candidate observations before composing')
        notes.append(note)
    # Never persist a derivative or change the campaign/observations here.
    with tempfile.TemporaryDirectory(prefix='clippr-post-composition-') as folder:
        paths=[];candidates=[];timeline=[];audio_sources=[];total_bytes=0;frames=0
        for index,note in enumerate(notes):
            content,metadata=_review_candidate(con,saved,organisation_id,owner_id,day,note['assetId'],
                revision,version,review_version,note['observationSha256'])
            total_bytes+=len(content)
            if total_bytes>POST_REVIEW_LIMIT:raise CampaignAssetError('Composition sources exceed 25 MB')
            photo=metadata['candidateMimeType'].startswith('image/')
            path=Path(folder)/(str(index)+('.png' if photo else '.mp4'))
            if photo:
                with Image.open(io.BytesIO(content)) as image:
                    with ImageOps.exif_transpose(image) as oriented:
                        # Composite transparency onto the same black canvas;
                        # dropping alpha would expose otherwise hidden RGB.
                        with oriented.convert('RGBA') as rgba:
                            with Image.new('RGB',rgba.size,(0,0,0)) as pixels:
                                pixels.paste(rgba,mask=rgba.getchannel('A'))
                                pixels.thumbnail((1200,1200));pixels.info.clear();pixels.save(path,format='PNG')
                seconds=3.0;has_audio=False
            else:
                path.write_bytes(content)
                source_info=catalog.probe_offline_video(path)
                seconds=float(source_info['format']['duration'])
                has_audio=any(s['codec_type']=='audio' for s in source_info['streams'])
            audio_sources.append(has_audio)
            if not math.isfinite(seconds) or not 0<seconds<=30:
                raise CampaignAssetError('Save shorter excerpts: a composed preview is limited to 30 seconds')
            count=round(seconds*24)
            if count<1 or frames+count>720:
                raise CampaignAssetError('Save shorter excerpts: a composed preview is limited to 30 seconds')
            timeline.append(dict(assetId=note['assetId'],startFrame=frames,endFrame=frames+count))
            if audio_policy=='saved_candidate_audio':timeline[-1]['hasAudio']=has_audio
            frames+=count;paths.append((note['assetId'],path,count/24));candidates.append(metadata)
        if not _video_preview_lock.acquire(blocking=False):
            raise CampaignAssetError('Another video review is rendering. Try again shortly')
        try:
            target=Path(folder)/'composed.mp4'
            reel._render_cut(paths,target,catalogue_review=True,
                **({'catalogue_audio':audio_sources} if audio_policy=='saved_candidate_audio' else {}))
            info=catalog.probe_offline_video(target)
            video=next(s for s in info['streams'] if s['codec_type']=='video')
            if (abs(float(info['format']['duration'])-frames/24)>0.25 or
                any(s['codec_type']=='audio' for s in info['streams']) !=
                 (audio_policy=='saved_candidate_audio' and any(audio_sources)) or
                (video['width'],video['height'])!=(720,1280)):
                raise CampaignAssetError('Composed preview did not match the saved sequence')
            catalog.validate_offline_video(target)
            content=target.read_bytes()
            if not 0<len(content)<=10*1024*1024:raise CampaignAssetError('Composed preview exceeds 10 MB')
        except reel.ReelError as exc:
            raise CampaignAssetError('Composed preview could not render safely; saved originals are unchanged') from exc
        finally:_video_preview_lock.release()
    manifest=dict(schemaVersion=1,purpose='unapproved_post_composition',draftId=saved['id'],day=day,
        revision=revision,selectionVersion=version,reviewVersion=review_version,
        documentSha256=contracts._hash(saved['document']),assignmentSha256=contracts._hash(assignment),
        post=next(p for p in saved['document']['posts'] if p['day']==day),candidates=candidates,
        timeline=timeline,fps=24,durationMs=round(frames/24*1000),width=720,height=1280,
        audioPolicy=audio_policy,frameFit='contain',photoDurationMs=3000,
        previewSha256=hashlib.sha256(content).hexdigest(),previewBytes=len(content),
        requiresIndependentQC=True,requiresOwnerApproval=True,
        approved=False,canSpend=False,canPublish=False,hostedStorageVerified=False)
    return content,manifest


def record_review_note(con, saved, organisation_id, owner_id, day, asset_id, payload, *, verify_receipt):
    """Persist owner observations only; receipt authenticates bytes served, not viewing."""
    from datetime import datetime, timezone
    fields={'revision','selectionVersion','reviewVersion','receipt','outcome','note'}
    if not isinstance(payload,dict) or not fields.issubset(payload) or set(payload)-fields-{'revisionResponse'}:
        raise CampaignAssetError('Review details required')
    binding=review_binding(con,saved,organisation_id,owner_id,day,asset_id,
                           payload['revision'],payload['selectionVersion'])
    receipt=verify_receipt(payload['receipt'])
    if any(receipt.get(k)!=v for k,v in binding.items()):
        raise CampaignAssetError('Preview changed. Inspect the saved media again')
    if payload['outcome'] not in ('usable_candidate','needs_changes','unsuitable'):
        raise CampaignAssetError('Choose a review outcome')
    note=payload['note']
    if not isinstance(note,str) or not 20<=len(note.strip())<=1000 or any(ord(c)<32 and c not in '\n\t' for c in note):
        raise CampaignAssetError('Describe observed relevance or needed changes in 20–1000 characters')
    selection=saved_selection(con,saved,organisation_id,owner_id)
    if type(payload['reviewVersion']) is not int or payload['reviewVersion']!=selection['reviewVersion']:
        raise drafts.MarketingDraftError('Review notes changed. Reload before saving','revision_conflict',409)
    assignment=next(a for a in selection['postAssignments'] if a['day']==day)
    candidate_edit=next((e for key in ('photoCrops','videoEdits') for e in assignment.get(key,[])
                         if e['assetId']==asset_id),None)
    if receipt.get('wholeOriginal'):
        if candidate_edit is not None or receipt['previewSha256']!=binding['sourceSha256']:
            raise CampaignAssetError('Original candidate changed. Inspect the saved media again')
        candidate_edit=dict(assetId=asset_id,wholeOriginal=True)
    previous=next((n for n in selection['reviewNotes'] if (n['day'],n['assetId'])==(day,asset_id)),None)
    response={}
    if 'revisionResponse' in payload:
        requested=payload['revisionResponse']
        if (not isinstance(requested,dict) or set(requested)!={'observationSha256','changeSummary'} or
            not previous or requested['observationSha256']!=observation_hash(previous)):
            raise CampaignAssetError('The original change request changed. Reload before responding')
        summary=requested['changeSummary']
        if (not isinstance(summary,str) or not 20<=len(summary.strip())<=1000 or
            any(ord(c)<32 and c not in '\n\t' for c in summary)):
            raise CampaignAssetError('Describe the actual edit in 20–1000 characters')
        if (previous['outcome'] not in ('needs_changes','unsuitable') or
            previous['sourceSha256']!=binding['sourceSha256'] or
            previous['documentSha256']!=binding['documentSha256'] or
            previous['selectionVersion']>=binding['selectionVersion'] or
            not previous.get('candidateEdit') or previous['candidateEdit']==candidate_edit or
            previous['assignmentSha256']==binding['assignmentSha256'] or
            previous['previewSha256']==receipt['previewSha256']):
            raise CampaignAssetError('Save a changed edit for this request and inspect its new rendered preview first')
        # One bounded predecessor, not an approval ledger or recursive history.
        original={k:v for k,v in previous.items() if k not in {'stale','observationSha256','revisionResponse'}}
        response={'revisionResponse':dict(observationSha256=observation_hash(previous),
                    changeSummary=summary.strip(),previousObservation=original)}
    notes=[{k:v for k,v in n.items() if k not in {'stale','observationSha256'}} for n in selection['reviewNotes']
           if (n['day'],n['assetId'])!=(day,asset_id)]
    # Keep the latest observation per day/asset, including stale observations.
    if len(notes)>=150:raise CampaignAssetError('Review note limit reached')
    notes.append(dict(day=day,assetId=asset_id,revision=binding['revision'],selectionVersion=binding['selectionVersion'],
        sourceSha256=binding['sourceSha256'],documentSha256=binding['documentSha256'],
        assignmentSha256=binding['assignmentSha256'],previewSha256=receipt['previewSha256'],candidateEdit=candidate_edit,
        outcome=payload['outcome'],note=note.strip(),reviewedBy=owner_id,
        recordedAt=datetime.now(timezone.utc).isoformat(),approved=False,canSpend=False,canPublish=False,**response))
    con.execute('UPDATE business_campaign_asset_selections SET review_notes=?,review_version=review_version+1 WHERE draft_id=?',
                (json.dumps(notes),saved['id']))
    return saved_selection(con,saved,organisation_id,owner_id)
