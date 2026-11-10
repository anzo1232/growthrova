"""Selected historical wording, prepared through the ordinary current editor."""
import json
import re

from flask import jsonify, request

import business_marketing_drafts as drafts
from business_growthrova_document_history import read_version


def register_content_recovery(app, root, *, prepare_saved_edit, prepare):
    @app.post(root + '/prepare-history-copy')
    def prepare_history_copy(organisation_id):
        data = request.get_json(silent=True)

        def invalid():
            return jsonify(code='invalid_request', error=
                'Choose an earlier saved revision and 1–30 distinct posts, concepts or website work items with word fields to recover.'), 400

        if (not isinstance(data, dict)
                or set(data) != {'id', 'expectedRevision', 'sourceRevision', 'changes'}
                or type(data.get('expectedRevision')) is not int
                or not 1 <= data['expectedRevision'] < 2147483647
                or type(data.get('sourceRevision')) is not int
                or not 1 <= data['sourceRevision'] < data['expectedRevision']):
            return invalid()
        drafts._id(data['id'])
        changes = data['changes']
        if not isinstance(changes, list) or not 1 <= len(changes) <= 30:
            return invalid()
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or change.get('type') not in ('post', 'creative', 'organic'):
                return invalid()
            post = change['type'] == 'post'
            key = 'day' if post else 'id'
            target = change.get(key)
            if set(change) != {'type', key, 'fields'}:
                return invalid()
            if post:
                if type(target) is not int or not 1 <= target <= 30:
                    return invalid()
            elif not isinstance(target, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', target):
                return invalid()
            fields = change['fields']
            allowed = ({'title', 'brief', 'draft', 'nextAction'} if change['type'] == 'organic' else
                       {'copyDraft', 'callToAction'} | ({'graphicText', 'supportingLine'} if post else set()))
            if (not isinstance(fields, list) or not 1 <= len(fields) <= len(allowed)
                    or any(not isinstance(field, str) or field not in allowed for field in fields)
                    or len(set(fields)) != len(fields)
                    or (change['type'], target) in seen):
                return invalid()
            seen.add((change['type'], target))

        snapshot = None
        historical = None

        def validate_source(con, scope, website):
            nonlocal snapshot, historical
            # prepare_saved_edit has already checked this campaign's ownership
            # in the same read transaction. Never accept a second campaign ID.
            row = read_version(con, data['id'], data['sourceRevision'])
            if row is None:
                raise drafts.MarketingDraftError('This saved revision was not retained. Choose available history.',
                                                 'history_not_retained', 404)
            exact = tuple(row)
            if snapshot is not None and exact != snapshot:
                raise drafts.MarketingDraftError('Selected saved history changed. Inspect it again.',
                                                 'plan_source_changed', 409)
            if snapshot is None:
                snapshot = exact
                historical = json.loads(row['document_json'])

        def recover(current, selections):
            if (historical.get('business') != current['business']
                    or historical.get('sourceUrl', '') != current.get('sourceUrl', '')):
                raise drafts.MarketingDraftError('Choose wording saved for the current business website.')
            edits, organic_edits = [], []
            for selection in selections:
                post = selection['type'] == 'post'
                key, collection = (('day', 'posts') if post else
                                   ('id', 'organicWork' if selection['type'] == 'organic' else 'creatives'))
                item = next((item for item in historical.get(collection, [])
                             if item.get(key) == selection[key]), None)
                if item is None or any(not isinstance(item.get(field), str) for field in selection['fields']):
                    raise drafts.MarketingDraftError('A selected item or word field is absent from this saved revision.')
                fields = {field: item[field] for field in selection['fields']}
                if selection['type'] == 'organic':
                    target = next((work for work in current.get('organicWork', [])
                                   if work['id'] == selection['id']), None)
                    # A reused ID must not attach historical words to different
                    # evidence. Preserve today's reference, including stale ones.
                    if (target is None or target['kind'] != item.get('kind')
                            or target['reference'] != item.get('reference')):
                        raise drafts.MarketingDraftError('Choose existing website work with the same retained research reference.')
                    changed = any(target[field] != value for field, value in fields.items())
                    organic_edits.append(dict(id=selection['id'], **fields,
                        **({'status': 'drafting'} if changed else {})))
                else:
                    edits.append(dict(type=selection['type'], **{key: selection[key]}, fields=fields))
            # The shared editors enforce present targets/limits, invalidate
            # changed-word review and preserve current artwork and other work.
            result = prepare(dict(sourceDocument=current, contentCopyPreparation=edits)) if edits else current
            if organic_edits:
                from business_organic_work import prepare_edit
                result = prepare_edit(result, organic_edits)
            return result

        result = prepare_saved_edit(organisation_id, data, 'contentCopyPreparation', changes,
            'Choose retained word fields and existing posts, concepts or website work for the current business website. '
            'Website work must keep the same research reference. '
            'Recovered words need checking against current facts before review and explicit save.',
            prepare=recover, validate_source=validate_source)
        if isinstance(result, tuple) or result.status_code != 200:
            return result
        return jsonify(**result.get_json(), recovery=dict(sourceRevision=data['sourceRevision'],
            changes=changes, limitations='Selected historical words only. Check them against current facts. '
                'Changed website wording returns to drafting. '
                'No historical approvals or delivery authority transferred; inspect and explicitly save.'))
