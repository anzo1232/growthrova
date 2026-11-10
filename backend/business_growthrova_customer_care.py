"""Bounded owner-recorded bookings and local customer-care preparation."""
from datetime import date, datetime, timezone, timedelta
import copy
import hashlib
import json
from business_marketing_drafts import MarketingDraftError, _text


def calendar_date(value, name, *, observed=False):
    value = _text(value, name, 10).strip()
    if value:
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value or (observed and parsed > datetime.now(timezone.utc).date()):
                raise ValueError()
        except ValueError:
            raise MarketingDraftError('Use a valid calendar date; observed outcomes cannot be future dated.') from None
    return value


def normalise_customer_care(value):
    if not isinstance(value, dict) or not {'booking', 'retention', 'review'} <= set(value) or set(value) - {'booking', 'retention', 'review', 'repeatRules', 'repeatProgress', 'background'}:
        raise MarketingDraftError('Use the supported booking and customer-care fields.')
    booking = value['booking']
    booking_fields = {'state', 'scheduledDate', 'outcomeDate', 'reference', 'evidence'}
    if not isinstance(booking, dict) or not booking_fields <= set(booking) or set(booking) - booking_fields - {'appointment'}:
        raise MarketingDraftError('Use the supported booking fields.')
    if booking['state'] not in ('unrecorded', 'confirmed', 'attended', 'cancelled', 'no_show'):
        raise MarketingDraftError('Choose a booking outcome.')
    result = dict(booking=dict(state=booking['state'],
        scheduledDate=calendar_date(booking['scheduledDate'], 'Booking date'),
        outcomeDate=calendar_date(booking['outcomeDate'], 'Outcome date', observed=True),
        reference=_text(booking['reference'], 'Booking reference', 300).strip(),
        evidence=_text(booking['evidence'], 'Booking evidence', 1000).strip()))
    saved = result['booking']
    if 'appointment' in booking:
        from business_growthrova_booking_calendar import appointment_times
        appointment, start, _ = appointment_times(booking['appointment'])
        if saved['state'] == 'unrecorded':
            raise MarketingDraftError('Choose a recorded booking state before adding appointment times.')
        saved['appointment'] = appointment
        # Existing reports/agenda retain UTC-day semantics, including when
        # the appointment's local date differs from its UTC start date.
        saved['scheduledDate'] = start.date().isoformat()
    if saved['state'] != 'unrecorded' and not (saved['scheduledDate'] and saved['evidence']):
        raise MarketingDraftError('Record the booking date and how this outcome was confirmed.')
    if saved['state'] in ('attended', 'cancelled', 'no_show') and not saved['outcomeDate']:
        raise MarketingDraftError('Record when the booking outcome occurred.')
    if saved['state'] in ('attended', 'no_show') and saved['outcomeDate'] < saved['scheduledDate']:
        raise MarketingDraftError('Attendance outcomes cannot precede the booking date.')
    if saved['state'] in ('unrecorded', 'confirmed') and saved['outcomeDate']:
        raise MarketingDraftError('Choose an observed outcome before adding its date.')
    for kind in ('retention', 'review'):
        task = value[kind]
        limits = dict(action=1000, responsiblePerson=160, wording=4000)
        if not isinstance(task, dict) or set(task) != set(limits) | {'dueDate', 'state', 'channel'}:
            raise MarketingDraftError('Use the supported customer-care task fields.')
        item = {key: _text(task[key], key, limit).strip() for key, limit in limits.items()}
        item['dueDate'] = calendar_date(task['dueDate'], 'Task date')
        if task['state'] not in ('open', 'done', 'cancelled') or task['channel'] not in ('unspecified', 'email', 'whatsapp', 'phone', 'other'):
            raise MarketingDraftError('Choose a supported task state and channel.')
        item.update(state=task['state'], channel=task['channel'])
        if (item['dueDate'] or item['wording'] or item['responsiblePerson'] or item['state'] != 'open') and not item['action']:
            raise MarketingDraftError('Describe the retention or review action before preparing it.')
        result[kind] = item
    if 'repeatRules' in value:
        rules = value['repeatRules']
        if not isinstance(rules, dict) or set(rules) != {'retention', 'review'}:
            raise MarketingDraftError('Use the supported repeat rules.')
        result['repeatRules'] = {}
        for kind, rule in rules.items():
            if not isinstance(rule, dict) or set(rule) != {'enabled', 'startDate', 'intervalDays', 'action', 'responsiblePerson', 'channel', 'wording'}:
                raise MarketingDraftError('Use the supported repeat rule fields.')
            if type(rule['enabled']) is not bool or type(rule['intervalDays']) is not int or not 1 <= rule['intervalDays'] <= 365:
                raise MarketingDraftError('Choose a repeat interval from 1 to 365 days.')
            item = {key: _text(rule[key], key, limit).strip() for key, limit in dict(action=1000, responsiblePerson=160, wording=4000).items()}
            item.update(enabled=rule['enabled'], intervalDays=rule['intervalDays'], startDate=calendar_date(rule['startDate'], 'First repeat date'), channel=rule['channel'])
            if item['channel'] not in ('unspecified', 'email', 'whatsapp', 'phone', 'other'):
                raise MarketingDraftError('Choose a supported repeat channel.')
            if item['enabled'] and not (item['action'] and item['startDate']):
                raise MarketingDraftError('Add an action and first date before enabling repeat preparation.')
            result['repeatRules'][kind] = item
    if 'background' in value:
        background = value['background']
        if (not isinstance(background, dict) or set(background) != {'enabled', 'throughDate', 'maxOccurrences'}
                or type(background['enabled']) is not bool
                or type(background['maxOccurrences']) is not int or not 1 <= background['maxOccurrences'] <= 100):
            raise MarketingDraftError('Choose background preparation and a limit from 1 to 100 occurrences per rule.')
        through = calendar_date(background['throughDate'], 'Final preparation date')
        if background['enabled'] and not through:
            raise MarketingDraftError('Choose a final date before enabling background preparation.')
        result['background'] = dict(background, throughDate=through)
    if 'repeatProgress' in value:
        progress = value['repeatProgress']
        if not isinstance(progress, dict) or set(progress) - {'retention', 'review'}:
            raise MarketingDraftError('Invalid repeat progress.')
        result['repeatProgress'] = {}
        for kind, item in progress.items():
            if not isinstance(item, dict) or not {'ruleFingerprint', 'dueDate'} <= set(item) or set(item) - {'ruleFingerprint', 'dueDate', 'count'}:
                raise MarketingDraftError('Invalid repeat occurrence.')
            fingerprint = _text(item['ruleFingerprint'], 'Rule fingerprint', 64)
            if len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
                raise MarketingDraftError('Invalid repeat fingerprint.')
            due = calendar_date(item['dueDate'], 'Occurrence date', observed=True)
            if not due:
                raise MarketingDraftError('An occurrence date is required.')
            result['repeatProgress'][kind] = dict(ruleFingerprint=fingerprint, dueDate=due)
            if 'count' in item:
                if type(item['count']) is not int or not 1 <= item['count'] <= 500:
                    raise MarketingDraftError('Invalid preparation count.')
                result['repeatProgress'][kind]['count'] = item['count']
    return result


def prepare_due_care(data, through_date, *, background=False):
    """Latest occurrence only; never replace unfinished human work or contact anyone."""
    cutoff = calendar_date(through_date, 'Preparation cutoff', observed=True)
    if not cutoff:
        raise MarketingDraftError('A preparation cutoff date is required.')
    result = copy.deepcopy(data)
    care = result.get('customerCare', {})
    changed = []
    bounds = care.get('background')
    if background:
        if not bounds or not bounds['enabled']:
            return result, changed
        cutoff = min(cutoff, bounds['throughDate'])
    for kind, rule in care.get('repeatRules', {}).items():
        current = care[kind]
        if not rule['enabled'] or rule['startDate'] > cutoff or (current['action'] and current['state'] == 'open'):
            continue
        start = date.fromisoformat(rule['startDate'])
        days = (date.fromisoformat(cutoff) - start).days
        due = (start + timedelta(days=(days // rule['intervalDays']) * rule['intervalDays'])).isoformat()
        fingerprint = hashlib.sha256(json.dumps(rule, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        progress = care.get('repeatProgress', {}).get(kind, {})
        same_rule = progress.get('ruleFingerprint') == fingerprint
        count = progress.get('count', 1) if same_rule else 0
        if same_rule and progress.get('dueDate', '') >= due:
            continue
        if background and count >= bounds['maxOccurrences']:
            continue
        care[kind] = {key: rule[key] for key in ('action', 'responsiblePerson', 'channel', 'wording')}
        care[kind].update(state='open', dueDate=due)
        care.setdefault('repeatProgress', {})[kind] = dict(ruleFingerprint=fingerprint, dueDate=due)
        if bounds is not None or 'count' in progress:
            care['repeatProgress'][kind]['count'] = count + 1
        changed.append(kind)
    return result, changed
