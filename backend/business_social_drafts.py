"""Exact, disconnected posting drafts. No OAuth, provider calls or dispatch authority."""
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import re
import zipfile
import requests
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Response, jsonify, request
from business_marketing_drafts import MarketingDraftError, _id


PLANNED_CHANNELS = {
    'instagram': 'Instagram', 'facebook': 'Facebook', 'linkedin': 'LinkedIn',
    'tiktok': 'TikTok', 'x': 'X (Twitter)',
}


def channel_checks(channels, caption=None, channel_captions=None, destination_accounts=None, artwork=None):
    """Disconnected planning checks for retained PNGs; never delivery capability.

    These are planning holds, never a connected-account capability grant. Legacy
    snapshots get the same checks on read without changing their frozen inputs.
    See SOCIAL_POSTING_INTEGRATION_20261104.md for the dated provider evidence.
    """
    # Dated Ayrshare limits; this preliminary code-point count is not the
    # account-specific platform validator (notably X weighted text).
    caption_limits = {'instagram': 2200, 'linkedin': 3000, 'tiktok': 2200}
    # Values come from the server renderer's immutable manifest, never client
    # dimensions or requested frame names (complete adverts retain native size).
    media = {name: artwork.get(key) if isinstance(artwork, dict) else None
             for name, key in (('width', 'width'), ('height', 'height'), ('bytes', 'previewBytes'))}
    media = {key: value if type(value) is int and value > 0 else None for key, value in media.items()}
    slides = artwork.get('slides', []) if isinstance(artwork, dict) else []
    if slides:
        media['bytes'] = max(slide['bytes'] for slide in slides)
    checks = []
    for channel in channels:
        label = PLANNED_CHANNELS[channel]
        reasons = [dict(code='account_not_connected',
                        message=f'No {label} destination account connected. Publishing is unavailable.'),
                   dict(code='validation_pending',
                        message='Account permissions, caption and media limits need validation before approval.')]
        destination = (destination_accounts or {}).get(channel) if isinstance(destination_accounts, dict) else None
        if destination:
            reasons[0] = dict(code='destination_snapshot_only', message=
                'Saved destination identity only. Current connection, permissions and media support must be rechecked before approval.')
        channel_caption = (channel_captions or {}).get(channel, caption)
        count = len(channel_caption) if channel_caption is not None else None
        limit = caption_limits.get(channel)
        if count is not None and limit is not None and count > limit:
            reasons.append(dict(code='caption_too_long', message=
                f'{label} caption has {count} characters; the planned integration allows {limit}. '
                'Review a shorter channel caption before approval. The saved caption is unchanged.'))
        if channel == 'tiktok' and channel_caption is not None and ('\n' in channel_caption or '\r' in channel_caption):
            reasons.append(dict(code='line_breaks_unsupported', message=
                'TikTok ignores caption line breaks through the planned integration. '
                'Review a separate channel caption before approval. The saved caption is unchanged.'))
        media_state = 'validation_pending'
        if channel == 'instagram':
            # Dated provider image limits; aspect, account permissions, quotas,
            # crop and disclosure handling still need independent validation.
            if media['width'] is not None and not 320 <= media['width'] <= 1440:
                reasons.append(dict(code='image_width_unsupported', message=
                    f"Instagram image width is {media['width']} px; the planned integration allows 320–1440 px. "
                    'Preview and approve a separate rendition. Original artwork preserved.'))
                media_state = 'needs_rendition'
            if media['bytes'] is not None and media['bytes'] > 8_000_000:
                reasons.append(dict(code='image_too_large', message=
                    f"Instagram image has {media['bytes']} bytes; the preliminary limit is 8 MB. "
                    'Preview and approve a separate rendition. Original artwork preserved.'))
                media_state = 'needs_rendition'
        if channel == 'tiktok':
            media_state = 'needs_rendition'
            reasons.append(dict(code='rendition_required', message=
                'TikTok photo publishing requires JPEG or WebP through the planned integration. '
                'This PNG is preserved; a separate rendition must be previewed and approved.'))
        if isinstance(artwork, dict) and artwork.get('slides'):
            reasons.append(dict(code='carousel_validation_pending', message=
                'Every ordered slide and this destination need an explicit carousel-capable delivery check before approval.'))
        checks.append(dict(channel=channel, label=label, state='blocked', destinationAccount=destination,
                           format='carousel' if isinstance(artwork, dict) and artwork.get('slides') else 'single_image', mediaType='image/png', reasons=reasons,
                           mediaCheck=dict(**media, state=media_state),
                           captionCheck=dict(characters=count, preliminaryLimit=limit)))
    return checks


def local_schedule(local_time, zone_name, offset_minutes):
    """Round-trip both folds: reject spring gaps and require an explicit offset."""
    if (not isinstance(local_time, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', local_time)
            or not isinstance(zone_name, str) or len(zone_name) > 100
            or type(offset_minutes) is not int or not -840 <= offset_minutes <= 840):
        raise MarketingDraftError('Choose a local date/time, IANA timezone and explicit UTC offset in minutes.')
    try:
        wall = datetime.strptime(local_time, '%Y-%m-%dT%H:%M')
        zone = ZoneInfo(zone_name)
        matches = []
        for fold in (0, 1):
            aware = wall.replace(tzinfo=zone, fold=fold)
            utc = aware.astimezone(timezone.utc)
            if (utc.astimezone(zone).replace(tzinfo=None) == wall
                    and aware.utcoffset().total_seconds() == offset_minutes * 60):
                matches.append(utc)
        if not matches:
            raise ValueError('Nonexistent time or wrong offset')
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        raise MarketingDraftError('That local time and UTC offset do not exist in this timezone. '
                                  'Check daylight saving; repeated hours need the intended offset.') from None
    return dict(localTime=local_time, timezone=zone_name, utcOffsetMinutes=offset_minutes,
                utcTime=matches[0].strftime('%Y-%m-%dT%H:%M:%SZ'))


def register_social_draft_routes(app, repo, root, compose, *, revalidate=None, social_accounts=None):
    """Reuse the exact export renderer and the authenticated project-bound document store."""
    with closing(repo._connect()) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS growthrova_social_drafts(
            document_id TEXT NOT NULL, draft_id TEXT NOT NULL, input_hash TEXT NOT NULL,
            draft_json TEXT NOT NULL, artwork BLOB NOT NULL,
            PRIMARY KEY(document_id,draft_id))''')
        con.commit()

    endpoint = root + '/<ident>/social-drafts'

    def outcome(row, saved):
        value = json.loads(row['draft_json'])
        captions = value.get('channelCaptions', {c: value['caption'] for c in value['channels']})
        return {**value, 'channelCaptions': captions, 'current': value['revision'] == saved['revision'],
                'canPublish': False, 'approval': None, 'channelChecks': channel_checks(
                    value['channels'], value['caption'], captions, value.get('destinationAccounts'), value.get('manifest'))}

    def fresh(saved, con):
        row = con.execute('SELECT revision FROM marketing_drafts WHERE id=?', (saved['id'],)).fetchone()
        if not row or row[0] != saved['revision']:
            raise MarketingDraftError('Campaign changed. Reopen the artwork before saving a posting draft.',
                                      'revision_conflict', 409)

    def recheck():
        if revalidate:
            return revalidate()
        return None

    @app.get(endpoint)
    def social_drafts(organisation_id, ident):
        saved = repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            rows = con.execute('SELECT draft_json FROM growthrova_social_drafts WHERE document_id=? '
                               'ORDER BY rowid DESC LIMIT 100', (ident,)).fetchall()
            # A read can wait too. Do not release saved captions or artwork
            # references to a revoked grant or a replacement authenticated user.
            error = recheck()
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
                raise MarketingDraftError('Business access changed. Sign in again before reopening posting drafts.',
                                          'access_denied', 403)
        return jsonify(drafts=[outcome(row, saved) for row in rows], canPublish=False,
                       connectionState='unavailable', message='Draft only. No social account connected; nothing is scheduled.')

    @app.post(endpoint)
    def save_social_draft(organisation_id, ident):
        saved = repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        data = request.get_json(silent=True)
        fields = {'draftId', 'expectedRevision', 'operationId', 'frame', 'artworkSha256',
                  'channels', 'localTime', 'timezone', 'utcOffsetMinutes'}
        if not isinstance(data, dict) or not fields <= set(data) or set(data) - fields - {'channelCaptions', 'sourceDraftId', 'destinationAccounts', 'format', 'day', 'selectionVersion', 'reviewVersion'}:
            raise MarketingDraftError('Choose the exact saved artwork, planned channels and local time. Posting approval is unavailable.')
        carousel = data.get('format') == 'carousel'
        if 'format' in data and not carousel:
            raise MarketingDraftError('Unsupported posting format.')
        extra = {'day', 'selectionVersion', 'reviewVersion'}
        if (carousel and (not extra <= set(data) or any(type(data[k]) is not int or data[k] < 1 for k in extra)
                          or data['operationId'] != ident or data['frame'] != 'carousel' or 'sourceDraftId' in data)
                or not carousel and (extra & set(data) or data['frame'] == 'carousel')):
            raise MarketingDraftError('Choose the exact saved carousel and its media review versions.')
        _id(data['draftId'])
        _id(data['operationId'])
        if 'sourceDraftId' in data:
            _id(data['sourceDraftId'])
            if data['sourceDraftId'] == data['draftId']:
                raise MarketingDraftError('A revised posting draft needs a new draft ID.')
        if (not isinstance(data['artworkSha256'], str) or not re.fullmatch('[a-f0-9]{64}', data['artworkSha256'])
                or data['frame'] not in ('original', 'portrait', 'square', 'story', 'carousel')
                or not isinstance(data['channels'], list) or not 1 <= len(data['channels']) <= len(PLANNED_CHANNELS)
                or any(not isinstance(channel, str) or channel not in PLANNED_CHANNELS for channel in data['channels'])
                or len(set(data['channels'])) != len(data['channels'])
                or type(data['expectedRevision']) is not int):
            raise MarketingDraftError('Choose one to five distinct planned channels and a valid inspected artwork.')
        # This is the existing campaign draft text bound, not platform eligibility.
        overrides = data.get('channelCaptions', {})
        if (not isinstance(overrides, dict) or set(overrides) - set(data['channels'])
                or any(not isinstance(text, str) or not text.strip() or len(text) > 3000
                       for text in overrides.values())):
            raise MarketingDraftError('Channel captions must be nonempty text up to 3000 characters for selected channels only.')
        schedule = local_schedule(data['localTime'], data['timezone'], data['utcOffsetMinutes'])
        selections = data.get('destinationAccounts', {})
        if (not isinstance(selections, dict) or set(selections) - set(data['channels'])
                or any(not isinstance(ident, str) or not ident.strip() or len(ident) > 300
                       or any(ord(c) < 32 for c in ident) for ident in selections.values())):
            raise MarketingDraftError('Choose destination IDs for selected channels only. Recheck the business accounts.')
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

        def replay(row, con):
            # Both acknowledgement paths can follow a database wait. Recheck
            # access before releasing the frozen draft, without rendering it or
            # requiring the destination provider to be available again.
            error = recheck()
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
                raise MarketingDraftError('Business access changed. Sign in again before reopening a posting draft.',
                                          'access_denied', 403)
            if row['input_hash'] != fingerprint:
                raise MarketingDraftError('This draft ID already has different inputs. Reopen the saved draft.',
                                          'operation_conflict', 409)
            return jsonify(draft=outcome(row, saved)), 200

        error = recheck()
        if error is not None:
            return error
        # Resolve uncertain saves before any provider lookup. Replaying a frozen
        # snapshot must work even after disconnect or an upstream outage.
        with closing(repo._connect()) as con:
            fresh(saved, con)
            row = con.execute('SELECT * FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                              (ident, data['draftId'])).fetchone()
            if row:
                return replay(row, con)
        if data['expectedRevision'] != saved['revision']:
            raise MarketingDraftError('Campaign changed. Reopen the saved artwork.', 'revision_conflict', 409)
        destinations = {}
        if selections:
            try:
                inventory = social_accounts(organisation_id) if social_accounts else []
            except (requests.RequestException, ValueError, TypeError, OSError, LookupError, RuntimeError):
                raise MarketingDraftError('Destination accounts could not be checked. Retry this same draft; your work is preserved.',
                                          'social_accounts_unavailable', 503) from None
            for channel, selected_id in selections.items():
                account = next((a for a in inventory if a['channel'] == channel), None)
                if (not account or account['state'] != 'reported' or not account['destination']
                        or account['destination']['id'] != selected_id
                        or account.get('accountTypeCheck', {}).get('state') == 'unsupported'):
                    raise MarketingDraftError('Selected destination is unavailable, changed or needs reconnection. '
                                              'Recheck accounts and explicitly choose the intended destination.')
                destinations[channel] = account['destination']
            error = recheck()
            if error is not None:
                return error
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            fresh(saved, con)
            row = con.execute('SELECT * FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                              (ident, data['draftId'])).fetchone()
            if row:
                return replay(row, con)
            if data['expectedRevision'] != saved['revision']:
                raise MarketingDraftError('Campaign changed. Reopen the saved artwork.', 'revision_conflict', 409)
            if 'sourceDraftId' in data:
                source = con.execute('SELECT draft_json FROM growthrova_social_drafts '
                                     'WHERE document_id=? AND draft_id=?',
                                     (ident, data['sourceDraftId'])).fetchone()
                if not source:
                    raise MarketingDraftError('Source posting draft not found in this campaign.', 'draft_not_found', 404)
                source = json.loads(source['draft_json'])
                same_artwork = all(source[key] == data[key] for key in ('operationId', 'frame', 'artworkSha256'))
                if not same_artwork or source['revision'] != saved['revision']:
                    raise MarketingDraftError('Source artwork or campaign changed. Inspect a new posting draft instead.',
                                              'revision_conflict', 409)
            if carousel:
                from business_photo_carousel import preview, package
                files, manifest = preview(con, saved, scope[1], scope[0], data['day'], saved['revision'],
                    data['selectionVersion'], data['reviewVersion'])
                pixels = package(files, manifest)
                manifest = dict(manifest, previewSha256=hashlib.sha256(pixels).hexdigest(), previewBytes=len(pixels))
            else:
                rendered = compose(con, saved, scope, ident, data['operationId'], data['frame'])
                manifest = rendered['manifest']
                pixels = base64.b64decode(rendered['previewBase64'], validate=True)
            if manifest['previewSha256'] != data['artworkSha256']:
                raise MarketingDraftError('Artwork changed. Inspect this exact export before saving.', 'artwork_changed', 409)
            # Rendering can outlive a session or business grant. Keep the write
            # transaction open so a failed recheck rolls back without retaining
            # a posting draft. A newly authenticated user is not the saved owner.
            error = recheck()
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope:
                raise MarketingDraftError('Business access changed. Sign in again before saving a posting draft.',
                                          'access_denied', 403)
            captions = {c: overrides.get(c, manifest['post']['copyDraft']) for c in data['channels']}
            draft = dict(draftId=data['draftId'], state='draft', revision=saved['revision'],
                operationId=data['operationId'], day=manifest['day'], frame=data['frame'],
                artworkSha256=data['artworkSha256'], caption=manifest['post']['copyDraft'],
                channels=data['channels'], channelCaptions=captions, schedule=schedule, destinationAccounts=destinations,
                manifest=manifest)
            if carousel:
                draft['format'] = 'carousel'
            if 'sourceDraftId' in data:
                draft['sourceDraftId'] = data['sourceDraftId']
            con.execute('INSERT INTO growthrova_social_drafts VALUES(?,?,?,?,?)',
                        (ident, data['draftId'], fingerprint, json.dumps(draft), pixels))
            con.commit()
        return jsonify(draft=outcome({'draft_json': json.dumps(draft)}, saved)), 201

    @app.get(endpoint + '/<draft_id>/artwork')
    def social_draft_artwork(organisation_id, ident, draft_id):
        repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(draft_id)
        with closing(repo._connect()) as con:
            row = con.execute('SELECT artwork FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                              (ident, draft_id)).fetchone()
            metadata = con.execute('SELECT draft_json FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                                   (ident, draft_id)).fetchone()
            draft = json.loads(metadata['draft_json']) if metadata else {}
            files = None
            if row and draft.get('format') == 'carousel':
                from business_social_media import carousel_files
                try:
                    if hashlib.sha256(row['artwork']).hexdigest() != draft['artworkSha256']:
                        raise ValueError('Retained carousel changed')
                    files = carousel_files(row['artwork'], draft['manifest'])
                except (ValueError, KeyError, OSError, zipfile.BadZipFile):
                    raise MarketingDraftError('Saved carousel failed its integrity check. Delivery remains held.',
                                              'artwork_changed', 409) from None
            error = recheck()
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
                raise MarketingDraftError('Business access changed. Sign in again before downloading posting artwork.',
                                          'access_denied', 403)
        if not row:
            raise MarketingDraftError('Posting draft not found.', 'draft_not_found', 404)
        if files is not None:
            index = request.args.get('slide', type=int)
            if index is not None:
                if not 1 <= index <= len(files):
                    raise MarketingDraftError('Saved carousel slide not found.', 'draft_not_found', 404)
                return Response(files[index-1], mimetype='image/png')
            return Response(row['artwork'], mimetype='application/zip')
        return Response(row['artwork'], mimetype='image/png')

    @app.post(endpoint + '/<draft_id>/cancel')
    def cancel_social_draft(organisation_id, ident, draft_id):
        saved = repo.read(organisation_id, ident)
        scope = repo._scope(organisation_id)
        _id(draft_id)
        if request.get_json(silent=True) != {}:
            raise MarketingDraftError('Cancel this saved draft with an empty request.')
        with closing(repo._connect()) as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM growthrova_social_drafts WHERE document_id=? AND draft_id=?',
                              (ident, draft_id)).fetchone()
            if not row:
                raise MarketingDraftError('Posting draft not found.', 'draft_not_found', 404)
            # Acquiring the SQLite write lock can wait. Recheck the grant and
            # original owner after that wait, before changing or returning work.
            error = recheck()
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope or not repo._owned(con, ident, scope):
                raise MarketingDraftError('Business access changed. Sign in again before cancelling a posting draft.',
                                          'access_denied', 403)
            draft = json.loads(row['draft_json'])
            from business_social_delivery import cancel_delivery_jobs
            in_flight = cancel_delivery_jobs(con, ident, draft_id)
            draft['state'] = 'cancellation_requested' if in_flight else 'cancelled'
            con.execute('UPDATE growthrova_social_drafts SET draft_json=? WHERE document_id=? AND draft_id=?',
                        (json.dumps(draft), ident, draft_id))
            con.commit()
        return jsonify(draft=outcome({'draft_json': json.dumps(draft)}, saved))
