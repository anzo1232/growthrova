"""Explicit photo layouts from saved candidates; never modifies approved originals."""
import hashlib

from business_campaign_assets import (
    CampaignAssetError, saved_selection, observed_static_candidate,
    render_static_candidate, _review_archive,
)
import business_marketing_drafts as drafts
import business_scene_contracts as contracts

LIMIT = 20 * 1024 * 1024


def preview(con, saved, organisation_id, owner_id, day, revision, version, review_version):
    selection = saved_selection(con, saved, organisation_id, owner_id)
    assignment = next((a for a in selection['postAssignments'] if a['day'] == day), None)
    logo_id = (assignment or {}).get('staticLogoAssetId', '')
    ids = [a for a in (assignment or {}).get('assetIds', []) if a != logo_id]
    slides = (assignment or {}).get('carouselSlides', [])
    by_id = {s['assetId']: s for s in slides}
    if not 2 <= len(ids) <= 5 or set(by_id) != set(ids) or len(slides) != len(ids):
        raise CampaignAssetError('Save graphic words and a next step for every carousel photo (two to five); exclude the optional logo')
    if (revision != saved['revision'] or version != selection['selectionVersion']
            or review_version != selection['reviewVersion'] or selection['stale']):
        raise drafts.MarketingDraftError('Reload and review the current saved carousel first', 'revision_conflict', 409)
    post = next(p for p in saved['document']['posts'] if p['day'] == day)
    brand = saved['document'].get('brandKit')
    # Validate the complete set before rendering, using the same current rights,
    # crop and owner-observation boundaries as the single-image composer.
    for ident in ids:
        wording = dict(copyDraft=by_id[ident]['graphicText'], callToAction=by_id[ident]['callToAction'])
        issue = drafts.marketing_graphic_issue(wording, saved['document']['business'])
        if issue:
            raise CampaignAssetError(f'Edit slide {ids.index(ident)+1} before composing: {issue}')
    resolved = [observed_static_candidate(con, saved, organisation_id, owner_id, day,
                ident, revision, version, review_version, logo=ident == logo_id)
                for ident in ids + ([logo_id] if logo_id else [])]
    files, metadata, total = [], [], 0
    for index, (ident, (content, candidate)) in enumerate(zip(ids, resolved), 1):
        words = by_id[ident]
        try:
            pixels, layout = render_static_candidate(content, brand, words, resolved[-1][0] if logo_id else None)
        except CampaignAssetError as exc:
            raise CampaignAssetError(f'Slide {index}: {exc}') from exc
        total += len(pixels)
        if total > LIMIT:
            raise CampaignAssetError('Carousel exceeds 20 MB; use smaller photos or fewer slides')
        filename = f'slide-{index:02d}.png'
        files.append((filename, pixels))
        metadata.append(dict(file=filename, assetId=ident, graphicText=words['graphicText'],
            callToAction=words['callToAction'], candidate=candidate, layout=layout,
            bytes=len(pixels), sha256=hashlib.sha256(pixels).hexdigest()))
    manifest = dict(schemaVersion=1, purpose='unapproved_photo_carousel', draftId=saved['id'],
        day=day, revision=revision, selectionVersion=version, reviewVersion=review_version,
        documentSha256=contracts._hash(saved['document']), assignmentSha256=contracts._hash(assignment),
        post=post, brandKit=brand, width=1080, height=1350, slides=metadata,
        logoIncluded=bool(logo_id), approved=False, canSpend=False, canPublish=False,
        requiresOwnerApproval=True, requiresIndependentQC=True, hostedStorageVerified=False)
    if assignment.get('carouselCaptions'):
        manifest['channelCaptions'] = assignment['carouselCaptions']
    if logo_id:
        manifest['logoCandidate'] = resolved[-1][1]
    return files, manifest


def package(files, manifest):
    extras = []
    if manifest.get('channelCaptions'):
        lines = ['CAROUSEL POSTING HANDOFF — UNAPPROVED',
            'Local preparation only. Nothing is scheduled or published.',
            'This export is not publishing approval. Scheduling requires a separate saved posting draft and eligible carousel delivery connection.',
            'Recheck rights, facts, destination account and current channel format/caption limits before use.',
            'Channel selection is an intention, not verified platform eligibility.',
            f"Campaign: {manifest['draftId']} | day {manifest['day']} | revision {manifest['revision']}",
            f"Media version: {manifest['selectionVersion']} | observations: {manifest['reviewVersion']}",
            f"Document SHA-256: {manifest['documentSha256']}",
            f"Assignment SHA-256: {manifest['assignmentSha256']}", '', 'SLIDE ORDER']
        lines += [f"{i}. {slide['file']} | SHA-256 {slide['sha256']}" for i,slide in enumerate(manifest['slides'],1)]
        for channel,caption in manifest['channelCaptions'].items():
            lines += ['', f'CHANNEL: {channel}', 'CAPTION BEGIN', caption, 'CAPTION END']
        extras.append(('posting-handoff.txt', ('\n'.join(lines)+'\n').encode('utf-8')))
    return _review_archive(files + extras, manifest, LIMIT + 128 * 1024)[0]
