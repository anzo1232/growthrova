"""Bounded owner-observed sale snapshots, not payments or ad attribution."""
from datetime import date, datetime, timezone
import re

from business_marketing_drafts import MarketingDraftError, _id, _text

# Initial supported currencies use two decimal places; no conversion is performed.
SALE_CURRENCIES = ('USD', 'GBP', 'EUR', 'AUD', 'CAD', 'NZD', 'INR', 'SGD', 'ZAR', 'AED')


def normalise_purchases(value):
    if not isinstance(value, list) or len(value) > 50:
        raise MarketingDraftError('Record at most 50 additional purchases per enquiry.')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or 'id' not in item:
            raise MarketingDraftError('Each additional purchase needs its saved identity.')
        ident = _id(item['id'])
        if ident in seen:
            raise MarketingDraftError('Each additional purchase needs a different identity.')
        seen.add(ident)
        result.append(dict(normalise_sale({k: v for k, v in item.items() if k != 'id'}), id=ident))
    return result


def observed_sales(data):
    """Current versions only; preserve the original single-sale representation."""
    return ([data['sale']] if data.get('sale') else []) + data.get('purchases', [])


def validate_sale_changes(previous, current):
    if previous and not current:
        raise MarketingDraftError('Keep the saved sale; mark it voided with a correction note instead of removing it.')
    if previous and current != previous and (not current['correctionNote']
            or current['correctionNote'] == previous['correctionNote']):
        raise MarketingDraftError('Add a new explanation for this sale correction or void. Earlier values remain in history.')


def normalise_sale(value):
    fields = {'amount', 'currency', 'date', 'sourceReference', 'state', 'correctionNote'}
    if not isinstance(value, dict) or set(value) != fields:
        raise MarketingDraftError('Use the supported sale fields.')
    result = {key: _text(value[key], key, limit).strip() for key, limit in
              dict(amount=12, currency=3, date=10, sourceReference=512, state=8, correctionNote=1000).items()}
    amount = result['amount']
    if not re.fullmatch(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?', amount) or not any(c in '123456789' for c in amount):
        raise MarketingDraftError('Record a positive sale value up to 999999999.99, with at most two decimal places.')
    whole, _, fraction = amount.partition('.')
    result['amount'] = whole + '.' + fraction.ljust(2, '0')
    if result['currency'] not in SALE_CURRENCIES:
        raise MarketingDraftError('Choose a supported sale currency; currency conversion is unavailable.')
    try:
        observed = date.fromisoformat(result['date'])
        if observed.isoformat() != result['date'] or observed > datetime.now(timezone.utc).date():
            raise ValueError()
    except ValueError:
        raise MarketingDraftError('Record a valid observed sale date through today (UTC).') from None
    if not result['sourceReference']:
        raise MarketingDraftError('Record where this sale was observed, such as an order or receipt reference.')
    if result['state'] not in ('recorded', 'voided'):
        raise MarketingDraftError('Choose a recorded or voided sale state.')
    if result['state'] == 'voided' and not result['correctionNote']:
        raise MarketingDraftError('Explain why this sale record is voided. This does not issue a refund.')
    return result
