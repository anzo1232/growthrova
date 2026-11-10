"""Contact-free summaries of saved outcomes and source observations. No attribution."""
from datetime import datetime, timedelta, timezone
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from business_growthrova_sales import SALE_CURRENCIES, observed_sales


def booking_counts():
    return dict(awaitingReview=0, today=0, upcoming=0, undated=0,
                attended=0, cancelled=0, no_show=0)


def add_booking_count(counts, booking, today):
    state = booking.get('state')
    if state == 'confirmed':
        date = booking.get('scheduledDate')
        group = 'undated' if not date else 'awaitingReview' if date < today else 'today' if date == today else 'upcoming'
        counts[group] += 1
    elif state in ('attended', 'cancelled', 'no_show'):
        counts[state] += 1


def care_counts():
    return {kind: dict(overdue=0, dueToday=0, upcoming=0, undated=0, unassignedDue=0)
            for kind in ('retention', 'review')}


def add_care_counts(counts, data, today):
    # Count prepared tasks only, not rules that might prepare future tasks.
    for kind, result in counts.items():
        task = data.get('customerCare', {}).get(kind, {})
        if task.get('state') != 'open' or not task.get('action', '').strip():
            continue
        due = task.get('dueDate')
        group = 'undated' if not due else 'overdue' if due < today else 'dueToday' if due == today else 'upcoming'
        result[group] += 1
        if group in ('overdue', 'dueToday') and not task.get('responsiblePerson', '').strip():
            result['unassignedDue'] += 1


def measurement_overview(reports, reads, period, now):
    """Keep source identities/windows separate; never add overlapping search reads."""
    def window(zone):
        today = datetime.fromtimestamp(now, ZoneInfo(zone)).date()
        return (None if period == 'all' else (today - timedelta(days=int(period)-1)).isoformat(),
                today.isoformat())

    def selected(rows, first, last):
        return [row for row in rows if row['date'] <= last and (first is None or row['date'] >= first)]

    def missing(first, last, dates):
        if first is None or last < first:
            return None
        return (datetime.fromisoformat(last)-datetime.fromisoformat(first)).days + 1 - len(dates)

    paid = []
    for report in reports:
        data = report['data']
        first, last = window(data['timezone'])
        rows = selected(data['rows'], first, last)
        source = report.get('observation')
        requested_from = source['requestedFrom'] if source else None
        requested_to = source['requestedTo'] if source else None
        coverage_from = max(requested_from, first) if requested_from and first else requested_from
        coverage_to = min(requested_to, last) if requested_to else None
        dates = [row['date'] for row in rows]
        paid.append(dict(reportId=report['id'], revision=report['revision'],
            campaignId=report['document_id'], platform=data['platform'], accountId=data['accountId'],
            platformCampaignId=data['campaignId'], currency=data['currency'], timezone=data['timezone'],
            provenance=report['provenance'], savedAt=report['updated'],
            observedAt=source['observedAt'] if source else None,
            connectionVersion=source['account']['connectionVersion'] if source else None,
            fromDate=first, throughDate=last, requestedFrom=requested_from, requestedTo=requested_to,
            returnedDates=dates, missingDates=missing(coverage_from, coverage_to, dates) if source else None,
            daily=[dict(date=row['date'], impressions=row['impressions'], clicks=row['clicks'],
                        spend=row['spend']) for row in rows],
            impressions=sum(row['impressions'] for row in rows) if rows else None,
            clicks=sum(row['clicks'] for row in rows) if rows else None,
            spend=format(sum((Decimal(row['spend']) for row in rows), Decimal(0)), 'f') if rows else None))

    # A newer failed/queued read does not replace a completed observation.
    # Group by property, not campaign or connection version, to avoid duplicate
    # coverage after reconnects or when campaigns share a Search Console property.
    latest, counts = {}, {}
    for read in reads:
        snap = json.loads(read['snapshot_json'])
        if snap.get('mode') == 'page_query':
            continue  # Pair-level top rows are never daily property totals.
        prop = snap['account']['propertyId']
        counts[prop] = counts.get(prop, 0) + 1
        if prop not in latest or (read['updated'], read['id']) > (latest[prop]['updated'], latest[prop]['id']):
            latest[prop] = read
    search = []
    for prop, read in sorted(latest.items()):
        snap, result = json.loads(read['snapshot_json']), json.loads(read['result_json'])
        first, last = window(result['timezone'])
        rows = selected(result['rows'], first, last)
        dates = [row['date'] for row in rows]
        coverage_from = max(snap['from'], first) if first else snap['from']
        coverage_to = min(snap['to'], last)
        search.append(dict(snapshotId=read['id'], campaignId=read['document_id'], propertyId=prop,
            connectionVersion=snap['account']['connectionVersion'], timezone=result['timezone'],
            observedAt=result['observedAt'], requestedFrom=snap['from'], requestedTo=snap['to'],
            fromDate=first, throughDate=last, returnedDates=dates,
            daily=[dict(date=row['date'], impressions=row['impressions'], clicks=row['clicks'])
                   for row in rows],
            missingDates=missing(coverage_from, coverage_to, dates), olderSnapshotsExcluded=counts[prop]-1,
            impressions=sum(row['impressions'] for row in rows) if rows else None,
            clicks=sum(row['clicks'] for row in rows) if rows else None))
    return dict(paid=paid, search=search)


def outcome_timeline(events, period, today):
    """Bounded intervals of current saved outcomes, independent of creation dates.

    Events are already filtered by the report's outcome window. Keep money in
    integer minor units until serialization; different currencies never sum.
    """
    first = (min((event['date'] for event in events), default=today.isoformat())
             if period == 'all' else (today - timedelta(days=int(period) - 1)).isoformat())
    start = datetime.fromisoformat(first).date()
    span = (today - start).days + 1
    width = max(1, (span + 11) // 12)
    currencies = sorted({event['currency'] for event in events if event['kind'] == 'sale'})
    buckets = [dict(fromDate=(start + timedelta(days=i)).isoformat(),
                    throughDate=min(today, start + timedelta(days=i + width - 1)).isoformat(),
                    bookings=dict(attended=0, cancelled=0, no_show=0),
                    sales={currency: dict(minor=0, count=0) for currency in currencies})
               for i in range(0, span, width)]
    for event in events:
        bucket = buckets[(datetime.fromisoformat(event['date']).date() - start).days // width]
        if event['kind'] == 'sale':
            value = bucket['sales'][event['currency']]
            value['minor'] += event['minor']
            value['count'] += 1
        else:
            bucket['bookings'][event['kind']] += 1
    for bucket in buckets:
        bucket['sales'] = [dict(currency=currency, count=value['count'],
                                amount=f"{value['minor'] // 100}.{value['minor'] % 100:02d}")
                           for currency, value in bucket['sales'].items()]
    return dict(fromDate=first, throughDate=today.isoformat(), timezone='UTC', buckets=buckets)


def repeat_purchase_overview(rows, today):
    """Contact-free all-date review signals from current saved enquiry snapshots."""
    def counts():
        return dict(purchasingEnquiries=0, repeatEnquiries=0, repeatPurchases=0,
                    withoutOpenRetention=0)

    totals, campaigns = counts(), {}
    for row in rows:
        data = json.loads(row['data_json'])
        purchases = [sale for sale in observed_sales(data)
                     if sale.get('state') == 'recorded' and sale.get('date')
                     and sale['date'] <= today and sale.get('currency') in SALE_CURRENCIES]
        if not purchases:
            continue
        current = counts()
        current['purchasingEnquiries'] = 1
        if len(purchases) >= 2:
            current['repeatEnquiries'] = 1
            current['repeatPurchases'] = len(purchases)
            task = data.get('customerCare', {}).get('retention', {})
            current['withoutOpenRetention'] = int(not (
                task.get('state') == 'open' and task.get('action', '').strip()))
        campaign = campaigns.setdefault(row['document_id'], counts())
        for key, value in current.items():
            totals[key] += value
            campaign[key] += value
    return dict(throughDate=today, totals=totals,
                campaigns=[dict(campaignId=ident, **value)
                           for ident, value in sorted(campaigns.items())])


def recorded_overview(rows, period, now):
    today = datetime.fromtimestamp(now, timezone.utc).date()
    end = datetime.combine(today + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()
    dated = [row['created'] for row in rows if 0 < row['created'] < end]
    if period == 'all':
        start = datetime.fromtimestamp(min(dated), timezone.utc).date() if dated else today
    else:
        start = today - timedelta(days=int(period) - 1)
    start_stamp = datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()
    span = (today - start).days + 1
    width = max(1, (span + 11) // 12)
    buckets = [dict(fromDate=(start + timedelta(days=i)).isoformat(),
                    throughDate=min(today, start + timedelta(days=i + width - 1)).isoformat(), count=0)
               for i in range(0, span, width)]
    statuses = {key: 0 for key in ('new', 'contacted', 'qualified', 'booked', 'won', 'lost')}
    bookings = {key: 0 for key in ('attended', 'cancelled', 'no_show')}
    campaigns, currencies, care_campaigns = {}, {}, {}
    booking_campaigns = {}
    total = overdue = voided = 0
    outcome_events = []

    def in_period(value):
        return bool(value and value <= today.isoformat() and (period == 'all' or value >= start.isoformat()))

    for row in rows:
        data = json.loads(row['data_json'])
        care = care_campaigns.setdefault(row['document_id'], care_counts())
        add_care_counts(care, data, today.isoformat())
        campaign = campaigns.setdefault(row['document_id'], dict(campaignId=row['document_id'],
            recordsAdded=0, bookingOutcomes=0, recordedSales=0, overdueActions=0))
        if start_stamp <= row['created'] < end:
            total += 1
            campaign['recordsAdded'] += 1
            if data['status'] in statuses:
                statuses[data['status']] += 1
            buckets[int((row['created'] - start_stamp) // 86400) // width]['count'] += 1
        booking = data.get('customerCare', {}).get('booking', {})
        add_booking_count(booking_campaigns.setdefault(row['document_id'], booking_counts()),
                          booking, today.isoformat())
        if booking.get('state') in bookings and in_period(booking.get('outcomeDate')):
            bookings[booking['state']] += 1
            campaign['bookingOutcomes'] += 1
            outcome_events.append(dict(kind=booking['state'], date=booking['outcomeDate']))
        due = data.get('actionDueDate')
        if data.get('nextAction', '').strip() and data.get('actionState', 'open') == 'open' and due and due < today.isoformat():
            overdue += 1
            campaign['overdueActions'] += 1
        for sale in observed_sales(data):
            if sale and in_period(sale['date']):
                if sale['state'] == 'voided':
                    voided += 1
                elif sale['state'] == 'recorded' and sale['currency'] in SALE_CURRENCIES:
                    whole, fraction = sale['amount'].split('.')
                    minor = int(whole) * 100 + int(fraction)
                    value = currencies.setdefault(sale['currency'], dict(minor=0, count=0))
                    value['minor'] += minor
                    value['count'] += 1
                    campaign['recordedSales'] += 1
                    outcome_events.append(dict(kind='sale', date=sale['date'], currency=sale['currency'], minor=minor))
    care_totals = care_counts()
    booking_totals = booking_counts()
    for counts in booking_campaigns.values():
        for group, count in counts.items():
            booking_totals[group] += count
    for counts in care_campaigns.values():
        for kind, groups in counts.items():
            for group, count in groups.items():
                care_totals[kind][group] += count
    return dict(period=period, fromDate=start.isoformat(), throughDate=today.isoformat(),
                outcomeTimeline=outcome_timeline(outcome_events, period, today),
                repeatPurchases=repeat_purchase_overview(rows, today.isoformat()),
                bookingWork=dict(throughDate=today.isoformat(), observedAt=now, totals=booking_totals,
                    campaigns=[dict(campaignId=ident, counts=counts)
                               for ident, counts in sorted(booking_campaigns.items()) if any(counts.values())]),
                customerCare=dict(throughDate=today.isoformat(), observedAt=now, totals=care_totals,
                    campaigns=[dict(campaignId=ident, tasks=counts) for ident, counts in sorted(care_campaigns.items())
                               if any(sum(groups.values()) for groups in counts.values())]),
                observedAt=now, totalStored=len(rows), recordsAdded=total, statuses=statuses,
                buckets=buckets, bookingOutcomes=bookings, overdueActions=overdue, voidedSales=voided,
                sales=[dict(currency=currency, count=value['count'],
                            amount=f"{value['minor'] // 100}.{value['minor'] % 100:02d}")
                       for currency, value in sorted(currencies.items())],
                campaigns=sorted(campaigns.values(), key=lambda item: item['campaignId']),
                attribution='owner_recorded_unverified',
                outcomePeriod=('All saved outcome dates through ' + today.isoformat()) if period == 'all'
                else start.isoformat() + ' to ' + today.isoformat())
