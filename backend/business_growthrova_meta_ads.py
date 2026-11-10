"""Opt-in Meta paused website-traffic transport. No installed connection or host.

Trusted configuration supplies a dedicated business/account/Page binding, exact
plan-bound settings, current grants/billing/policy/destination/cost authority and
credentials. Rotate connection version on any credential/grant/identity change.
Never use an ambient account. All five writes need the worker's durable journal;
unknown outcomes have GET-only recovery, never resume/retry/name-based guessing.
"""
import base64
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

import requests

from business_growthrova_paid_delivery import META_STEPS, account_binding, missing
from business_paid_campaign import normalise
from business_social_delivery import _hash
from business_growthrova_paid_pause_transport import MetaPauseTransport


def numeric(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9]{1,40}', value) is not None


@dataclass(frozen=True)
class MetaAdsBinding:
    owner_id: str
    organisation_id: str
    account_id: str
    label: str
    version: str
    currency: str
    page_id: str
    page_label: str
    plan_hash: str
    countries: tuple = ()
    age_min: int = 18
    age_max: int = 65
    cta_text: str = ''
    cta_type: str = ''
    beneficiary: str = ''
    payor: str = ''
    non_special_category_confirmed: bool = False
    verified: bool = False
    enabled: bool = False
    access_token: str = field(default='', repr=False)
    pause_enabled: bool = False
    total_budget_enabled: bool = False
    account_timezone: str = ''


def lifetime_settings(schedule):
    """Explicit local-day boundaries; reject ambiguous/nonexistent wall times."""
    zone = ZoneInfo(schedule['accountTimezone'])
    times = []
    for key, clock in (('startDate', '00:00:00'), ('endDate', '23:59:59')):
        wall = datetime.fromisoformat(schedule[key]+'T'+clock)
        local = wall.replace(tzinfo=zone)
        if (local.utcoffset() != local.replace(fold=1).utcoffset()
                or local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall):
            raise ValueError('Choose unambiguous account-local day boundaries')
        times.append(local.isoformat())
    return dict(lifetimeBudgetMinor=str(int(Decimal(schedule['totalBudget'])*100)),
                startTime=times[0], endTime=times[1], budgetSchedule=deepcopy(schedule))


def same_instant(actual, expected):
    try:
        parsed = datetime.fromisoformat(actual)
        return parsed.tzinfo is not None and parsed == datetime.fromisoformat(expected)
    except (TypeError, ValueError):
        return False


class MetaTrafficPausedAdapter(MetaPauseTransport):
    mode = 'live'
    meta_total_budget_paused = True
    API = 'https://graph.facebook.com/v26.0'
    CTA_TYPES = ('LEARN_MORE', 'CONTACT_US', 'BOOK_NOW', 'SHOP_NOW', 'SIGN_UP', 'GET_A_QUOTE')
    CREATIVE_OPT_OUTS = ('standard_enhancements', 'advantage_plus_creative', 'image_touchups',
        'image_enhancement', 'image_uncrop', 'image_background_gen', 'image_animation',
        'text_generation', 'text_optimizations', 'add_text_overlay', 'dynamic_cta_text')

    def __init__(self, resolve, eligible, *, http=None, pause_eligible=None):
        self.resolve, self.eligible, self.http = resolve, eligible, http
        self.pause_eligible = pause_eligible

    @staticmethod
    def identity(binding):
        return dict(platform='meta', ownerId=binding.owner_id, organisationId=binding.organisation_id,
                    accountId=binding.account_id, label=binding.label,
                    connectionVersion=binding.version, currency=binding.currency)

    def binding(self, owner, business):
        value = self.resolve(owner, business, 'meta')
        if (not isinstance(value, MetaAdsBinding) or value.verified is not True
                or (value.owner_id, value.organisation_id) != (owner, business)
                or not numeric(value.account_id) or not numeric(value.page_id)
                or not account_binding(self.identity(value), 'meta', (owner, business))
                or not isinstance(value.page_label, str) or not 1 <= len(value.page_label.strip()) <= 180
                or any(ord(c) < 32 for c in value.page_label)):
            return None
        return value

    def account(self, owner, business):
        value = self.binding(owner, business)
        return self.identity(value) if value else None

    def execution(self, snap):
        value = self.binding(snap['ownerId'], snap['organisationId'])
        plan = snap.get('plan')
        if (not value or not plan or value.plan_hash != _hash(plan) or plan['objective'] != 'traffic'
                or value.non_special_category_confirmed is not True
                or not isinstance(value.countries, tuple) or not 1 <= len(value.countries) <= 20
                or len(set(value.countries)) != len(value.countries)
                or any(not isinstance(c, str) or not re.fullmatch('[A-Z]{2}', c) for c in value.countries)
                or type(value.age_min) is not int or type(value.age_max) is not int
                or not 18 <= value.age_min <= value.age_max <= 65
                or value.cta_text != plan['callToAction'] or value.cta_type not in self.CTA_TYPES
                or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 180
                       or any(ord(c) < 32 for c in v) for v in (value.beneficiary, value.payor))):
            return None
        schedule = plan.get('budgetSchedule')
        if schedule is not None:
            if (value.total_budget_enabled is not True or not value.account_timezone
                    or value.account_timezone != schedule['accountTimezone']
                    or missing(plan, 'meta', total_budget_supported=True)):
                return None
            try:
                budget = lifetime_settings(schedule)
            except (ValueError, KeyError, ArithmeticError):
                return None
        else:
            budget = dict(dailyBudgetMinor=str(int(Decimal(plan['dailyBudget'] or '0') * 100)))
        # Supported currencies all use two minor-unit digits. No currency inference.
        return dict(pageId=value.page_id, pageLabel=value.page_label, planHash=value.plan_hash,
                    objective='OUTCOME_TRAFFIC', optimizationGoal='LINK_CLICKS', billingEvent='IMPRESSIONS',
                    bidStrategy='LOWEST_COST_WITHOUT_CAP', specialAdCategories=[],
                    targeting=dict(geo_locations=dict(countries=list(value.countries)),
                        age_min=value.age_min, age_max=value.age_max,
                        publisher_platforms=['facebook'], facebook_positions=['feed'],
                        targeting_automation=dict(advantage_audience=0)),
                    callToAction=value.cta_type, beneficiary=value.beneficiary, payor=value.payor,
                    creativeFeatures={key: dict(enroll_status='OPT_OUT') for key in self.CREATIVE_OPT_OUTS},
                    **budget,
                    schedule='ACCOUNT_LOCAL_LIFETIME_PAUSED' if schedule is not None else 'UNSCHEDULED_PAUSED')

    def blockers(self, snap):
        value = self.binding(snap['ownerId'], snap['organisationId'])
        reasons = []
        if not value or not value.enabled or not value.access_token:
            reasons.append('Connect a dedicated Meta ad account and Facebook Page; verify permissions, billing and creation authority.')
        if snap.get('plan') and snap['plan']['objective'] != 'traffic':
            reasons.append('This connection prepares website-traffic campaigns only. Other goals need a separately supported conversion or lead setup; your plan stays saved.')
        if (snap.get('plan') or {}).get('budgetSchedule'):
            schedule = snap['plan']['budgetSchedule']
            if not value or value.total_budget_enabled is not True or value.account_timezone != schedule['accountTimezone']:
                reasons.append('This plan remains preparation only until lifetime-budget eligibility and the exact Meta account timezone are reviewed for paused creation.')
            if schedule.get('startDate') and schedule.get('accountTimezone'):
                if schedule['startDate'] <= datetime.now(ZoneInfo(schedule['accountTimezone'])).date().isoformat():
                    reasons.append('Choose a future start date in the Meta account timezone before paused creation.')
        if not self.execution(snap):
            reasons.append('Confirm countries, adult ages, Facebook Feed, CTA mapping, beneficiary/payor and non-special-category policy for this saved version.')
        return reasons

    def launch_blockers(self, snap):
        # This is a local compatibility check, not a claim about live grants.
        # Do not infer hard caps from a daily budget or from SDK field names.
        if (snap.get('plan') or {}).get('budgetSchedule'):
            return [
                'This Meta lifetime budget does not enforce the hard daily spending ceiling in this approval.',
                'Keep this total-budget campaign paused. Its reviewed local-day boundaries do not establish the exact UTC launch expiry; activation remains unavailable.',
            ]
        return [
            'This Meta campaign uses an average daily budget, which does not establish the hard daily spending ceiling in this approval.',
            'Its paused creation settings have no verified total spending cap or end time. Connecting an account alone does not supply those limits.',
            'Keep this campaign paused. A separately supported budget and schedule path must be prepared and reviewed before Growthrova can activate it; changing the total or expiry here cannot convert it.',
        ]

    def ready_binding(self, snap, *, creation):
        value = self.binding(snap['ownerId'], snap['organisationId'])
        if (not value or not value.enabled or not value.access_token or snap.get('platform') != 'meta'
                or snap.get('intent') != 'create_paused_only' or self.identity(value) != snap.get('account')):
            return None
        if creation and (not snap.get('execution') or self.execution(snap) != snap['execution']
                or missing(snap.get('plan'), 'meta', total_budget_supported=True) or self.blockers(snap)
                or normalise(snap['plan']) != snap['plan']
                or value.currency != snap['plan']['currency']
                or self.eligible(deepcopy(snap)) is not True):
            return None
        return value

    def remote(self, binding, method, path, payload):
        options = dict(headers={'Authorization': 'Bearer '+binding.access_token}, timeout=15, allow_redirects=False)
        # Graph nested form values must be JSON strings; requests never retries.
        if method == 'POST':
            options['data'] = {key: json.dumps(value, separators=(',', ':')) if isinstance(value, (dict, list, bool)) else value
                               for key, value in payload.items()}
        else:
            options['params'] = payload
        if self.http is not None:
            response = self.http.request(method, self.API+'/'+path, **options)
        else:
            with requests.Session() as session:
                session.trust_env = False
                response = session.request(method, self.API+'/'+path, **options)
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) and not value.get('error') else None

    def check(self, snap):
        try:
            value = self.ready_binding(snap, creation=True)
            if not value:
                return False
            account = self.remote(value, 'GET', 'act_'+value.account_id,
                                  dict(fields='account_id,currency,account_status'+(',timezone_name' if snap['plan'].get('budgetSchedule') else '')))
            page = self.remote(value, 'GET', value.page_id, dict(fields='id,name'))
            return (account is not None and str(account.get('account_id')) == value.account_id
                    and account.get('currency') == value.currency and account.get('account_status') == 1
                    and (not snap['plan'].get('budgetSchedule') or account.get('timezone_name') == value.account_timezone)
                    and page is not None and str(page.get('id')) == value.page_id)
        except Exception:
            return False

    @staticmethod
    def payload(step, snap, resources, key):
        plan, settings = snap['plan'], snap['execution']
        name = 'Growthrova '+key
        if step == 'campaignId':
            return 'campaigns', dict(name=name, objective='OUTCOME_TRAFFIC', status='PAUSED',
                buying_type='AUCTION', special_ad_categories=[], is_adset_budget_sharing_enabled=False)
        if step == 'creativeId':
            return 'adcreatives', dict(name=name,
                degrees_of_freedom_spec=dict(creative_features_spec=deepcopy(settings['creativeFeatures'])),
                object_story_spec=dict(page_id=settings['pageId'],
                link_data=dict(link=plan['destinationUrl'], message=plan['primaryText'], name=plan['headline'],
                    image_hash=resources['imageHash'],
                    call_to_action=dict(type=settings['callToAction'], value=dict(link=plan['destinationUrl'])))))
        if step == 'adSetId':
            schedule = plan.get('budgetSchedule')
            if schedule is not None:
                if (settings.get('schedule') != 'ACCOUNT_LOCAL_LIFETIME_PAUSED'
                        or any(settings.get(k) != v for k,v in lifetime_settings(schedule).items())
                        or 'dailyBudgetMinor' in settings):
                    raise ValueError('Lifetime creation requires the exact reviewed schedule')
                budget = dict(lifetime_budget=settings['lifetimeBudgetMinor'],
                              start_time=settings['startTime'], end_time=settings['endTime'])
            else:
                budget = dict(daily_budget=settings['dailyBudgetMinor'])
            return 'adsets', dict(name=name, campaign_id=resources['campaignId'], status='PAUSED',
                **budget, billing_event='IMPRESSIONS',
                optimization_goal='LINK_CLICKS', bid_strategy='LOWEST_COST_WITHOUT_CAP',
                destination_type='WEBSITE', targeting=deepcopy(settings['targeting']),
                dsa_beneficiary=settings['beneficiary'], dsa_payor=settings['payor'])
        if step == 'adId':
            return 'ads', dict(name=name, adset_id=resources['adSetId'], status='PAUSED',
                creative=dict(creative_id=resources['creativeId']))
        raise ValueError('Unsupported Meta resource')

    def create_paused(self, snap, *, idempotency_key):
        raise ValueError('Meta creation requires the durable per-resource worker journal')

    def create_paused_progressive(self, snap, *, idempotency_key, journal, image_bytes):
        if (not re.fullmatch('[a-f0-9]{64}', idempotency_key) or not self.check(snap)
                or hashlib.sha256(image_bytes).hexdigest() != snap['plan']['asset']['sha256']):
            return None
        resources = {}
        for step in META_STEPS:
            value = self.ready_binding(snap, creation=True)
            if not value:
                break
            if step == 'adSetId' and snap['plan'].get('budgetSchedule') and not self.check(snap):
                break
            if step == 'imageHash':
                edge, body = 'adimages', dict(bytes=base64.b64encode(image_bytes).decode('ascii'))
            else:
                edge, body = self.payload(step, snap, resources, idempotency_key)
            if journal(step) is not True:
                break
            # After committed intent any exception or missing acknowledgement
            # ends this run. Neither the adapter nor a restarted worker retries.
            data = self.remote(value, 'POST', 'act_'+value.account_id+'/'+edge, body)
            ident = data.get('id') if data else None
            if step == 'imageHash':
                images = data.get('images') if data else None
                entries = list(images.values()) if isinstance(images, dict) else []
                ident = entries[0].get('hash') if len(entries) == 1 and isinstance(entries[0], dict) else None
            pattern = r'[a-fA-F0-9]{32}' if step == 'imageHash' else r'[0-9]{1,40}'
            if not isinstance(ident, str) or not re.fullmatch(pattern, ident):
                break
            if journal(step, ident) is not True:
                break
            resources[step] = ident
        result = dict(id=idempotency_key, resources=resources, outcome='partial')
        if len(resources) == len(META_STEPS):
            return self.lookup(snap, idempotency_key=idempotency_key, reference=result) or result
        return result

    def lookup(self, snap, *, idempotency_key, reference):
        # Read only, including if some earlier acknowledgements were lost.
        value = self.ready_binding(snap, creation=False)
        if (not value or not isinstance(reference, dict) or reference.get('id') != idempotency_key
                or not re.fullmatch('[a-f0-9]{64}', idempotency_key) or not snap.get('execution')):
            return None
        resources = reference.get('resources', {})
        settings = snap['execution']
        schedule = snap['plan'].get('budgetSchedule')
        if schedule is not None:
            if (value.total_budget_enabled is not True or value.account_timezone != schedule['accountTimezone']
                    or settings.get('schedule') != 'ACCOUNT_LOCAL_LIFETIME_PAUSED'
                    or any(settings.get(k) != v for k,v in lifetime_settings(schedule).items())):
                return None
            account = self.remote(value, 'GET', 'act_'+value.account_id, dict(fields='account_id,timezone_name'))
            if (not account or str(account.get('account_id')) != value.account_id
                    or account.get('timezone_name') != schedule['accountTimezone']):
                return None
        if any(k not in META_STEPS or not isinstance(v, str) or not re.fullmatch(
                r'[a-fA-F0-9]{32}' if k == 'imageHash' else r'[0-9]{1,40}', v) for k, v in resources.items()):
            return None
        # Partial IDs are retained; a GET can inspect each known resource but
        # cannot establish missing identities or authorise a second creation.
        fields = dict(campaignId='id,account_id,name,status,objective,special_ad_categories',
                      creativeId='id,account_id,name,object_story_spec,degrees_of_freedom_spec',
                      adSetId='id,account_id,name,status,campaign_id,daily_budget,billing_event,optimization_goal,bid_strategy,targeting,dsa_beneficiary,dsa_payor,destination_type',
                      adId='id,account_id,name,status,campaign_id,adset_id,creative')
        if schedule is not None:
            fields['adSetId'] += ',lifetime_budget,start_time,end_time'
        actual = {}
        for step, selected in fields.items():
            if step in resources:
                data = self.remote(value, 'GET', resources[step], dict(fields=selected))
                if (not data or str(data.get('id')) != resources[step]
                        or str(data.get('account_id')) != value.account_id):
                    return None
                actual[step] = data
        if set(resources) != set(META_STEPS):
            return dict(id=idempotency_key, resources=dict(resources), outcome='partial')
        plan, settings = snap['plan'], snap['execution']
        campaign, creative, group, ad = (actual[k] for k in ('campaignId', 'creativeId', 'adSetId', 'adId'))
        story = creative.get('object_story_spec', {})
        link = story.get('link_data', {})
        cta = link.get('call_to_action', {})
        # Compare explicit targeting keys, disallow unapproved expansion keys.
        targeting = group.get('targeting', {})
        expected = settings['targeting']
        target_ok = (set(targeting) == set(expected) and all(targeting.get(k) == v for k,v in expected.items()))
        budget_ok = (str(group.get('daily_budget')) == settings['dailyBudgetMinor']) if schedule is None else (
            str(group.get('lifetime_budget')) == settings['lifetimeBudgetMinor']
            and str(group.get('daily_budget', '0')) == '0'
            and same_instant(group.get('start_time'), settings['startTime'])
            and same_instant(group.get('end_time'), settings['endTime']))
        complete = (all(v.get('name') == 'Growthrova '+idempotency_key for v in actual.values())
            and all(actual[k].get('status') == 'PAUSED' for k in ('campaignId', 'adSetId', 'adId'))
            and campaign.get('objective') == 'OUTCOME_TRAFFIC' and campaign.get('special_ad_categories') == []
            and str(group.get('campaign_id')) == resources['campaignId']
            and budget_ok
            and group.get('billing_event') == 'IMPRESSIONS' and group.get('optimization_goal') == 'LINK_CLICKS'
            and group.get('bid_strategy') == 'LOWEST_COST_WITHOUT_CAP' and group.get('destination_type') == 'WEBSITE'
            and group.get('dsa_beneficiary') == settings['beneficiary'] and group.get('dsa_payor') == settings['payor']
            and target_ok and str(story.get('page_id')) == settings['pageId']
            and all(creative.get('degrees_of_freedom_spec', {}).get('creative_features_spec', {}).get(k, {}).get('enroll_status') == 'OPT_OUT'
                    for k in settings['creativeFeatures'])
            and link.get('link') == plan['destinationUrl'] and link.get('message') == plan['primaryText']
            and link.get('name') == plan['headline'] and link.get('image_hash') == resources['imageHash']
            and cta.get('type') == settings['callToAction'] and cta.get('value', {}).get('link') == plan['destinationUrl']
            and str(ad.get('campaign_id')) == resources['campaignId']
            and str(ad.get('adset_id')) == resources['adSetId'] and str(ad.get('creative', {}).get('id')) == resources['creativeId'])
        return dict(id=idempotency_key, resources=dict(resources), outcome='paused' if complete else 'partial')
