"""Bounded preparation inside the existing document; no platform/spend authority."""
import re
from datetime import date
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalise(value):
    from business_marketing_drafts import MarketingDraftError, _text, _id
    limits = dict(objective=20, audience=1000, primaryText=3000, headline=180,
                  callToAction=80, destinationUrl=512, currency=3, dailyBudget=12)
    required = set(limits) | {'durationDays', 'asset'}
    if not isinstance(value, dict) or set(value) not in (required, required | {'budgetSchedule'}):
        raise MarketingDraftError('Use only the supported paid campaign draft settings')
    result = {key:_text(value[key], key, limit) for key,limit in limits.items()}
    _validate_settings(result, value['durationDays'])
    asset=value['asset']
    if asset is not None:
        if (not isinstance(asset,dict) or set(asset)!={'operationId','sha256'}
                or not isinstance(asset['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',asset['sha256'])):
            raise MarketingDraftError('Choose an exact saved image')
        _id(asset['operationId'])
    return {**result,'durationDays':value['durationDays'],'asset':dict(asset) if asset else None,
            **({'budgetSchedule':normalise_meta_budget_schedule(value['budgetSchedule'])}
               if 'budgetSchedule' in value else {})}


def _validate_settings(result, days):
    from business_marketing_drafts import MarketingDraftError
    if result['objective'] not in ('awareness','traffic','leads','sales'):
        raise MarketingDraftError('Choose a campaign goal')
    if result['currency'] not in ('USD','GBP','EUR','AUD','CAD','INR'):
        raise MarketingDraftError('Choose a planning currency')
    if result['dailyBudget'] and not re.fullmatch(r'(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,2})?',result['dailyBudget']):
        raise MarketingDraftError('Enter a proposed daily budget with at most two decimal places')
    if type(days) is not int or not 1 <= days <= 90:
        raise MarketingDraftError('Choose a proposed duration from 1 to 90 days')
    url=result['destinationUrl']
    if url:
        try:
            parsed=urlsplit(url)
            if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.port==0 or '\\' in url or any(ord(c)<=32 or ord(c)==127 for c in url)):
                raise ValueError()
        except ValueError:
            raise MarketingDraftError('Use a complete HTTPS campaign destination without credentials or spaces') from None


def normalise_google(value):
    """One Search preparation plan; no account identifiers or execution settings.

    Lists may be incomplete so disconnected owners can save work in progress.
    These are preparation bounds, not a claim of platform eligibility.
    """
    from business_marketing_drafts import MarketingDraftError, _text
    fields = dict(objective=20, audience=1000, location=500, language=120,
                  destinationUrl=512, currency=3, dailyBudget=12, keywordMatch=10)
    lists = dict(headlines=(15,30), descriptions=(4,90), keywords=(50,80),
                 negativeKeywords=(50,80))
    required = set(fields) | set(lists) | {'durationDays'}
    if not isinstance(value,dict) or set(value) not in (required, required | {'budgetSchedule'}):
        raise MarketingDraftError('Use only the supported Google Search preparation settings')
    result = {key:_text(value[key],key,limit) for key,limit in fields.items()}
    _validate_settings(result,value['durationDays'])
    if result['objective'] not in ('traffic','leads','sales'):
        raise MarketingDraftError('Choose website visits, enquiries or sales for this Search plan')
    if result['keywordMatch'] not in ('phrase','exact'):
        raise MarketingDraftError('Choose phrase or exact keyword intentions')
    for key,(count,limit) in lists.items():
        items=value[key]
        if not isinstance(items,list) or len(items)>count:
            raise MarketingDraftError(f'Too many {key} in this preparation plan')
        result[key]=[_text(item,key,limit) for item in items]
        if any('\n' in item or '\r' in item for item in result[key]):
            raise MarketingDraftError('Use one keyword or advert option per line')
    # Do not add defaults to historical plans: exact saved approvals and mutation
    # receipt fingerprints must retain their original representation.
    return {**result,'durationDays':value['durationDays'],
            **({'budgetSchedule':normalise_google_budget_schedule(value['budgetSchedule'])}
               if 'budgetSchedule' in value else {})}


def normalise_google_budget_schedule(value):
    return _normalise_budget_schedule(value, 'Google', 'campaign_total', 3)


def normalise_meta_budget_schedule(value):
    return _normalise_budget_schedule(value, 'Meta', 'ad_set_lifetime', 1)


def _normalise_budget_schedule(value, platform, kind, minimum_days):
    """Whole account-local days for preparation, never UTC launch authority."""
    from business_marketing_drafts import MarketingDraftError, _text
    fields = dict(kind=20, totalBudget=12, startDate=10, endDate=10, accountTimezone=80)
    if not isinstance(value, dict) or set(value) != set(fields):
        raise MarketingDraftError(f'Use only the supported {platform} total-budget preparation fields')
    result = {key:_text(value[key], key, limit) for key,limit in fields.items()}
    if result['kind'] != kind:
        raise MarketingDraftError(f'Choose a supported {platform} budget preparation type')
    if result['totalBudget'] and not re.fullmatch(r'(?:0|[1-9][0-9]{0,6})(?:\.[0-9]{1,2})?', result['totalBudget']):
        raise MarketingDraftError('Enter a proposed total budget with at most two decimal places')
    dates = {}
    for key in ('startDate', 'endDate'):
        if not result[key]:
            continue  # Incomplete disconnected preparation remains saveable.
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', result[key]):
                raise ValueError()
            dates[key] = date.fromisoformat(result[key])
        except ValueError:
            raise MarketingDraftError(f'Use a valid calendar date for the {platform} schedule') from None
    if len(dates) == 2 and not minimum_days <= (dates['endDate']-dates['startDate']).days+1 <= 90:
        raise MarketingDraftError(f'Choose {minimum_days} to 90 inclusive calendar days for the {platform} total-budget plan')
    timezone = result['accountTimezone']
    if timezone:
        try:
            # A named zone preserves DST rules; do not infer it from the browser.
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise MarketingDraftError(f'Use the {platform} account timezone name, such as Europe/London') from None
    return result


def validate_asset(con, document_id, plan):
    """Check immutable bytes within the existing authenticated write transaction."""
    from business_marketing_drafts import MarketingDraftError
    import hashlib
    asset=plan.get('asset') if plan else None
    if not asset:
        return
    # Import lazily: images already depend on document validation.
    from business_growthrova_images import retained_image_bytes
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='growthrova_image_requests'").fetchone():
        raise MarketingDraftError('Saved image is unavailable in this campaign','image_held',409)
    content=retained_image_bytes(con,document_id,asset['operationId'])
    if hashlib.sha256(content).hexdigest()!=asset['sha256']:
        raise MarketingDraftError('Saved image changed. Inspect it again before saving.','artwork_changed',409)
