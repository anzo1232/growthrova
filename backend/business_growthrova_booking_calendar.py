"""Exact saved appointment times and private RFC 5545 calendar handoffs.

No calendar service, invitation, reminder, attendance inference or external IO.
Local wall times stay in CRM history; exports use unambiguous UTC instants.
"""
from datetime import datetime, timezone
import hashlib
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from business_marketing_drafts import MarketingDraftError, _text


def appointment_times(value):
    local_fields = {'localStart', 'localEnd', 'timeZone'}
    if not isinstance(value, dict) or set(value) not in (local_fields, local_fields | {'utcStart', 'utcEnd'}):
        raise MarketingDraftError('Use appointment start, end and timezone.')
    name = _text(value['timeZone'], 'Appointment timezone', 100).strip()
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise MarketingDraftError('Choose a valid timezone, such as Europe/London or UTC.') from None
    instants = []
    result = dict(timeZone=name)
    for key in ('localStart', 'localEnd'):
        text = _text(value[key], 'Appointment time', 16)
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}', text):
                raise ValueError()
            local = datetime.fromisoformat(text)
            # Round-trip both folds: reject missing hours and require UTC entry
            # for repeated DST hours instead of silently choosing an occurrence.
            candidates = set()
            for fold in (0, 1):
                instant = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if instant.astimezone(zone).replace(tzinfo=None) == local:
                    candidates.add(instant)
            if len(candidates) != 1:
                raise MarketingDraftError('This local time is skipped or repeated by a clock change. Enter both appointment times in UTC to identify the exact appointment.')
            instants.append(candidates.pop())
        except MarketingDraftError:
            raise
        except (ValueError, OverflowError):
            raise MarketingDraftError('Use complete appointment dates and times to the minute.') from None
        result[key] = text
    if not 0 < (instants[1] - instants[0]).total_seconds() <= 7 * 86400:
        raise MarketingDraftError('Appointment end must follow its start, within seven days.')
    # Pin the interpretation in the saved revision. A timezone-rule update
    # must never silently change an already approved appointment on export.
    for key, instant in zip(('utcStart', 'utcEnd'), instants):
        result[key] = instant.isoformat(timespec='minutes').replace('+00:00', 'Z')
        if key in value and value[key] != result[key]:
            raise MarketingDraftError('The saved UTC times differ from these local times or current timezone rules. Review the appointment and re-enter its times before saving.')
    return result, instants[0], instants[1]


def _text_value(value):
    value = ''.join(char for char in value if (ord(char) >= 32 and ord(char) != 127) or char in '\r\n\t')
    return (value.replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n')
            .replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,'))


def _fold(line):
    # Fold by UTF-8 octets without splitting a character. Continuation space
    # counts toward the 75-octet physical line limit.
    lines, current, size = [], '', 0
    for char in line:
        width = len(char.encode('utf-8'))
        if size + width > 75:
            lines.append(current)
            current, size = ' ', 1
        current += char
        size += width
    lines.append(current)
    return '\r\n'.join(lines)


def booking_calendar(row):
    """Caller must fence the saved revision and recheck current access."""
    import json
    data = json.loads(row['data_json'])
    booking = data.get('customerCare', {}).get('booking', {})
    if booking.get('state') not in ('confirmed', 'attended', 'cancelled', 'no_show') or not booking.get('appointment'):
        raise MarketingDraftError('Save a recorded booking with exact appointment times before downloading its calendar file.')
    _, start, end = appointment_times(booking['appointment'])
    uid = hashlib.sha256(('\n'.join((row['owner_id'], row['organisation_id'], row['id']))).encode()).hexdigest()
    stamp = datetime.fromtimestamp(row['updated'], timezone.utc)
    def fmt(value):
        return f'{value.year:04d}{value.month:02d}{value.day:02d}T{value.hour:02d}{value.minute:02d}{value.second:02d}Z'
    description = 'Owner-recorded booking: ' + booking['state'] + '.'
    if booking.get('reference'):
        description += '\nReference: ' + booking['reference']
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Growthrova//Saved booking handoff//EN',
             'CALSCALE:GREGORIAN', 'BEGIN:VEVENT', 'UID:' + uid + '@growthrova',
             'DTSTAMP:' + fmt(stamp), 'LAST-MODIFIED:' + fmt(stamp),
             'SEQUENCE:' + str(row['revision']), 'DTSTART:' + fmt(start), 'DTEND:' + fmt(end),
             'SUMMARY:' + _text_value('Booking · ' + data['name']),
             'DESCRIPTION:' + _text_value(description), 'CLASS:PRIVATE',
             'STATUS:' + ('CANCELLED' if booking['state'] == 'cancelled' else 'CONFIRMED'),
             'TRANSP:' + ('OPAQUE' if booking['state'] == 'confirmed' else 'TRANSPARENT'),
             'END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'
