"""Opt-in Google Search transport for the existing paused-only execution ledger.

No OAuth discovery, ambient credentials, installation, launch or automatic retries.
The resolver is trusted server configuration scoped to owner AND business. Rotate
its version on credentials/grant/identity changes. Execution settings additionally
bind the exact saved plan hash, and are frozen with the approval. `eligible` must
freshly establish project access, ad-account grants, billing, destination/policy,
conversion readiness where required and permitted costs. A paused plan does not
authorise future spend. One atomic mutation avoids intermediate resource writes;
a missing response identity remains uncertain and MUST NOT be replayed remotely.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, date
import re
from zoneinfo import ZoneInfo

import requests

from business_growthrova_paid_delivery import account_binding, missing
from business_paid_campaign import normalise_google
from business_social_delivery import _hash
from business_growthrova_paid_pause_transport import GooglePauseTransport


@dataclass(frozen=True)
class GoogleAdsBinding:
    owner_id: str
    organisation_id: str
    account_id: str
    label: str
    version: str
    currency: str
    plan_hash: str
    location_text: str
    language_text: str
    location_ids: tuple = ()
    language_id: str = ''
    cpc_bid_micros: int = 0
    non_political_confirmed: bool = False
    verified: bool = False
    enabled: bool = False
    login_customer_id: str = ''
    access_token: str = field(default='', repr=False)
    pause_enabled: bool = False
    developer_token: str = field(default='', repr=False)
    total_budget_enabled: bool = False
    account_timezone: str = ''


class GoogleSearchPausedAdapter(GooglePauseTransport):
    mode = 'live'
    google_total_budget_paused = True
    API = 'https://googleads.googleapis.com/v26'

    def __init__(self, resolve, eligible, *, http=None, pause_eligible=None):
        self.resolve, self.eligible, self.http = resolve, eligible, http
        self.pause_eligible = pause_eligible

    @staticmethod
    def identity(binding):
        return dict(platform='google', ownerId=binding.owner_id,
                    organisationId=binding.organisation_id, accountId=binding.account_id,
                    label=binding.label, connectionVersion=binding.version, currency=binding.currency)

    def binding(self, owner, business):
        value = self.resolve(owner, business, 'google')
        if (not isinstance(value, GoogleAdsBinding) or not value.verified
                or (value.owner_id, value.organisation_id) != (owner, business)
                or not re.fullmatch(r'[0-9]{10}', value.account_id)
                or (value.login_customer_id and not re.fullmatch(r'[0-9]{10}', value.login_customer_id))
                or not account_binding(self.identity(value), 'google', (owner, business))):
            return None
        return value

    def account(self, owner, business):
        binding = self.binding(owner, business)
        return self.identity(binding) if binding else None

    def execution(self, snap):
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if (not binding or not snap['plan']
                or binding.plan_hash != _hash(snap['plan'])
                or binding.location_text != snap['plan']['location']
                or binding.language_text != snap['plan']['language']
                or not isinstance(binding.location_ids, tuple) or not 1 <= len(binding.location_ids) <= 20
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{1,12}', v) for v in binding.location_ids)
                or len(set(binding.location_ids)) != len(binding.location_ids)
                or not isinstance(binding.language_id, str) or not re.fullmatch(r'[0-9]{1,12}', binding.language_id)
                or type(binding.cpc_bid_micros) is not int or not 0 < binding.cpc_bid_micros <= 10**12
                or binding.non_political_confirmed is not True):
            return None
        schedule = snap['plan'].get('budgetSchedule')
        if schedule is not None and (binding.total_budget_enabled is not True
                or not binding.account_timezone or binding.account_timezone != schedule['accountTimezone']):
            return None
        return dict(strategy='MANUAL_CPC', cpcBidMicros=str(binding.cpc_bid_micros),
                    locationIds=list(binding.location_ids), languageId=binding.language_id,
                    locationText=binding.location_text, languageText=binding.language_text,
                    politicalDeclaration='DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING',
                    network='GOOGLE_SEARCH_ONLY', locationPresence='PRESENCE',
                    schedule='ACCOUNT_LOCAL_TOTAL_PAUSED' if schedule is not None else 'UNSCHEDULED_PAUSED',
                    planHash=binding.plan_hash,
                    **({'budgetSchedule':deepcopy(schedule)} if schedule is not None else {}))

    def blockers(self, snap):
        result = []
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if not binding or not binding.enabled or not binding.access_token:
            result.append('Connect a dedicated Google account and enable paused creation after setup review.')
        if not self.execution(snap):
            result.append('Confirm exact Google locations, language, manual click bid and political declaration for this saved plan.')
        plan = snap.get('plan')
        if plan:
            schedule = plan.get('budgetSchedule')
            if schedule is not None:
                if not binding or binding.total_budget_enabled is not True or binding.account_timezone != schedule['accountTimezone']:
                    result.append('Review total-budget eligibility and the exact Google account timezone before paused creation.')
                if schedule.get('startDate') and schedule.get('accountTimezone'):
                    if date.fromisoformat(schedule['startDate']) <= datetime.now(ZoneInfo(schedule['accountTimezone'])).date():
                        result.append('Choose a future start date in the Google account timezone before creating this paused campaign.')
            # Save allows incomplete alternatives; creation must never silently omit them.
            if any(not text.strip() for key in ('headlines', 'descriptions', 'keywords', 'negativeKeywords') for text in plan[key]):
                result.append('Remove blank advert or keyword options before creation.')
            if any(len(set(plan[key])) != len(plan[key]) for key in ('headlines', 'descriptions', 'keywords', 'negativeKeywords')):
                result.append('Remove duplicate advert or keyword options before creation.')
            if set(plan['keywords']) & set(plan['negativeKeywords']):
                result.append('Resolve keywords that are also excluded searches.')
        return result

    def launch_blockers(self, snap):
        if snap.get('plan', {}).get('budgetSchedule'):
            return [
                'This Google campaign total budget does not enforce the hard daily spending ceiling in this approval.',
                'Its end is a whole account-local day, not the exact UTC launch expiry. Keep the campaign paused until a separately reviewed activation path enforces every approved limit.',
            ]
        # Existing receipts identify average-daily-budget Search campaigns.
        # Google forbids changing a created campaign's budget type in place.
        return [
            'This Google Search campaign uses an average daily budget, which is not the hard daily spending ceiling in this approval.',
            'It was created without a campaign total budget or end time. Google requires total budgets to be chosen at creation with a start and end date; this campaign cannot switch budget type.',
            'Keep this campaign paused. A new, separately reviewed campaign preparation path must support the required spending and schedule limits before Growthrova can activate it; changing the total or expiry here cannot convert it.',
        ]

    def ready_binding(self, snap, *, creation):
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if (not binding or not binding.enabled or not binding.access_token
                or snap.get('platform') != 'google' or snap.get('intent') != 'create_paused_only'
                or self.identity(binding) != snap.get('account')):
            return None
        if creation:
            if (not snap.get('execution') or self.execution(snap) != snap['execution']
                    or missing(snap.get('plan'), 'google', total_budget_supported=True) or self.blockers(snap)
                    or normalise_google(snap['plan']) != snap['plan']
                    or snap['plan']['currency'] != binding.currency
                    or self.eligible(deepcopy(snap)) is not True):
                return None
        return binding

    def remote(self, binding, path, payload):
        headers = {'Authorization': 'Bearer ' + binding.access_token}
        if binding.developer_token:
            headers['developer-token'] = binding.developer_token
        if binding.login_customer_id:
            headers['login-customer-id'] = binding.login_customer_id
        options = dict(headers=headers, json=payload, timeout=15, allow_redirects=False)
        url = self.API + '/customers/' + binding.account_id + '/googleAds:' + path
        if self.http is not None:
            return self.http.request('POST', url, **options)
        with requests.Session() as session:
            session.trust_env = False
            return session.request('POST', url, **options)

    def search(self, binding, query):
        response = self.remote(binding, 'searchStream', {'query': query})
        if response.status_code != 200:
            return None
        data = response.json()
        if not isinstance(data, list) or any(not isinstance(v, dict) or 'error' in v for v in data):
            return None
        return [row for chunk in data for row in chunk.get('results', [])]

    def check(self, snap):
        try:
            binding = self.ready_binding(snap, creation=True)
            if not binding:
                return False
            total = snap['plan'].get('budgetSchedule')
            rows = self.search(binding, 'SELECT customer.id, customer.currency_code, customer.status, customer.manager'
                + (', customer.time_zone' if total else '') + ' FROM customer LIMIT 1')
            if not rows or len(rows) != 1:
                return False
            customer = rows[0]['customer']
            return (str(customer.get('id')) == binding.account_id and customer.get('currencyCode') == binding.currency
                    and customer.get('status') == 'ENABLED' and customer.get('manager', False) is False
                    and (not total or customer.get('timeZone') == total['accountTimezone']))
        except Exception:
            return False

    @staticmethod
    def operations(snap, key):
        if not re.fullmatch(r'[a-f0-9]{64}', key):
            raise ValueError('A durable job identity is required')
        plan, settings = snap['plan'], snap['execution']
        schedule = plan.get('budgetSchedule')
        if schedule is not None:
            if (normalise_google(plan) != plan
                    or missing(plan, 'google', total_budget_supported=True)
                    or settings.get('schedule') != 'ACCOUNT_LOCAL_TOTAL_PAUSED'
                    or settings.get('budgetSchedule') != schedule):
                raise ValueError('Total-budget creation requires the exact reviewed budget and schedule')
        root = 'customers/' + snap['account']['accountId']
        budget, campaign, group = root+'/campaignBudgets/-1', root+'/campaigns/-2', root+'/adGroups/-3'
        name = 'Growthrova ' + key
        def create(kind, value):
            return {kind+'Operation': {'create': value}}
        budget_amount = (dict(period='CUSTOM_PERIOD',
            totalAmountMicros=str(int(Decimal(schedule['totalBudget'])*1000000))) if schedule is not None
            else dict(amountMicros=str(int(Decimal(plan['dailyBudget'])*1000000))))
        operations = [
            create('campaignBudget', dict(resourceName=budget, name=name, explicitlyShared=False,
                   **budget_amount, deliveryMethod='STANDARD')),
            create('campaign', dict(resourceName=campaign, name=name, status='PAUSED',
                   advertisingChannelType='SEARCH', campaignBudget=budget, manualCpc={},
                   containsEuPoliticalAdvertising=settings['politicalDeclaration'],
                   networkSettings=dict(targetGoogleSearch=True, targetSearchNetwork=False,
                                        targetContentNetwork=False, targetPartnerSearchNetwork=False),
                   geoTargetTypeSetting=dict(positiveGeoTargetType='PRESENCE'))),
            create('adGroup', dict(resourceName=group, name=name, campaign=campaign,
                   status='PAUSED', type='SEARCH_STANDARD', cpcBidMicros=settings['cpcBidMicros']))]
        if schedule is not None:
            # Budget type is immutable. This is always a new atomic resource tree.
            operations[1]['campaignOperation']['create'].update(
                startDateTime=schedule['startDate']+' 00:00:00',
                endDateTime=schedule['endDate']+' 23:59:59')
        for location in settings['locationIds']:
            operations.append(create('campaignCriterion', dict(campaign=campaign,
                location=dict(geoTargetConstant='geoTargetConstants/'+location))))
        operations.append(create('campaignCriterion', dict(campaign=campaign,
            language=dict(languageConstant='languageConstants/'+settings['languageId']))))
        for keyword in plan['keywords']:
            operations.append(create('adGroupCriterion', dict(adGroup=group, status='ENABLED',
                keyword=dict(text=keyword, matchType=plan['keywordMatch'].upper()))))
        for keyword in plan['negativeKeywords']:
            operations.append(create('campaignCriterion', dict(campaign=campaign, negative=True,
                keyword=dict(text=keyword, matchType=plan['keywordMatch'].upper()))))
        operations.append(create('adGroupAd', dict(adGroup=group, status='PAUSED', ad=dict(
            finalUrls=[plan['destinationUrl']], responsiveSearchAd=dict(
                headlines=[dict(text=t) for t in plan['headlines']],
                descriptions=[dict(text=t) for t in plan['descriptions']])))))
        return operations

    def create_paused(self, snap, *, idempotency_key):
        # The worker commits dispatch intent before this entry. Never retry this
        # request (Google does not promise application-key deduplication here).
        if not self.check(snap):
            return None
        binding = self.ready_binding(snap, creation=True)
        if not binding:
            return None
        operations = self.operations(snap, idempotency_key)
        response = self.remote(binding, 'mutate', dict(mutateOperations=operations,
            partialFailure=False, validateOnly=False, responseContentType='RESOURCE_NAME_ONLY'))
        if response.status_code != 200:
            return None  # HTTP errors/timeouts alone do not prove non-creation.
        data = response.json()
        results = data.get('mutateOperationResponses', [])
        if not isinstance(results, list):
            return None
        valid_results = [item for item in results if isinstance(item, dict)]
        resources = {}
        for kind, label, collection in (('campaignBudget', 'budgetId', 'campaignBudgets'),
                ('campaign', 'campaignId', 'campaigns'), ('adGroup', 'adGroupId', 'adGroups'),
                ('adGroupAd', 'adId', 'adGroupAds')):
            names = [item[kind+'Result'].get('resourceName') for item in valid_results
                     if isinstance(item.get(kind+'Result'), dict)]
            pattern = 'customers/'+binding.account_id+'/'+collection+r'/[0-9]+(?:~[0-9]+)?'
            if len(names) == 1 and isinstance(names[0], str) and re.fullmatch(pattern, names[0]):
                resources[label] = names[0]
        complete = (len(valid_results) == len(results) == len(operations) and len(resources) == 4
                    and not data.get('partialFailureError') and not data.get('error'))
        if complete:
            # Every criterion must also have an acknowledged result. Do not turn
            # a malformed/partial payload into a complete campaign claim.
            for operation, result in zip(operations, results):
                kind = next(iter(operation)).removesuffix('Operation')
                item = result.get(kind+'Result')
                value = item.get('resourceName', '') if isinstance(item, dict) else ''
                if not isinstance(value, str) or not re.fullmatch(
                        'customers/'+binding.account_id+r'/[A-Za-z]+/[0-9]+(?:~[0-9]+)?', value):
                    complete = False
        return dict(id=idempotency_key, resources=resources, outcome='paused' if complete else 'partial')

    def lookup(self, snap, *, idempotency_key, reference):
        # No name guessing and no mutation, including when the response was lost.
        binding = self.ready_binding(snap, creation=False)
        if not binding or not isinstance(reference, dict) or reference.get('id') != idempotency_key:
            return None
        resources = reference.get('resources', {})
        campaign = resources.get('campaignId', '')
        if not re.fullmatch('customers/'+binding.account_id+r'/campaigns/[0-9]+', campaign):
            return None
        schedule = snap['plan'].get('budgetSchedule')
        if schedule is not None:
            if (snap.get('execution', {}).get('schedule') != 'ACCOUNT_LOCAL_TOTAL_PAUSED'
                    or snap['execution'].get('budgetSchedule') != schedule
                    or binding.account_timezone != schedule['accountTimezone']):
                return None
            customers = self.search(binding, 'SELECT customer.id, customer.time_zone FROM customer LIMIT 1')
            if (not customers or len(customers) != 1
                    or str(customers[0]['customer'].get('id')) != binding.account_id
                    or customers[0]['customer'].get('timeZone') != schedule['accountTimezone']):
                return None
        rows = self.search(binding, "SELECT campaign.resource_name, campaign.status, campaign.name, campaign.advertising_channel_type, campaign.bidding_strategy_type, campaign.contains_eu_political_advertising, campaign.network_settings.target_google_search, campaign.network_settings.target_search_network, campaign.network_settings.target_content_network, campaign.network_settings.target_partner_search_network, campaign.geo_target_type_setting.positive_geo_target_type, ad_group.resource_name, ad_group.status, ad_group.cpc_bid_micros, ad_group_ad.resource_name, ad_group_ad.status, ad_group_ad.ad.final_urls, ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions, campaign.campaign_budget" + (", campaign.start_date_time, campaign.end_date_time" if schedule is not None else "") + " FROM ad_group_ad WHERE campaign.resource_name = '"+campaign+"' LIMIT 2")
        if not rows or len(rows) != 1:
            return None
        row = rows[0]
        actual = dict(campaignId=row['campaign']['resourceName'], budgetId=row['campaign']['campaignBudget'],
                      adGroupId=row['adGroup']['resourceName'], adId=row['adGroupAd']['resourceName'])
        if any(key in actual and actual[key] != value for key, value in resources.items()):
            return None
        plan, settings = snap['plan'], snap['execution']
        group = actual['adGroupId']
        if not re.fullmatch('customers/'+binding.account_id+r'/adGroups/[0-9]+', group):
            return None
        campaign_criteria = self.search(binding, "SELECT campaign_criterion.negative, campaign_criterion.type, campaign_criterion.location.geo_target_constant, campaign_criterion.language.language_constant, campaign_criterion.keyword.text, campaign_criterion.keyword.match_type FROM campaign_criterion WHERE campaign.resource_name = '"+campaign+"' AND campaign_criterion.status != 'REMOVED' LIMIT 200")
        group_criteria = self.search(binding, "SELECT ad_group_criterion.negative, ad_group_criterion.type, ad_group_criterion.status, ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type FROM ad_group_criterion WHERE ad_group.resource_name = '"+group+"' AND ad_group_criterion.status != 'REMOVED' LIMIT 200")
        expected_campaign = ([('LOCATION', False, 'geoTargetConstants/'+v) for v in settings['locationIds']]
            + [('LANGUAGE', False, 'languageConstants/'+settings['languageId'])]
            + [('KEYWORD', True, v, plan['keywordMatch'].upper()) for v in plan['negativeKeywords']])
        expected_group = [('KEYWORD', False, v, plan['keywordMatch'].upper(), 'ENABLED') for v in plan['keywords']]
        def criterion(value, ad_group=False):
            base = (value.get('type'), value.get('negative', False))
            if value.get('type') == 'KEYWORD':
                keyword = value.get('keyword', {})
                base += (keyword.get('text'), keyword.get('matchType'))
            elif value.get('type') == 'LOCATION':
                base += (value.get('location', {}).get('geoTargetConstant'),)
            elif value.get('type') == 'LANGUAGE':
                base += (value.get('language', {}).get('languageConstant'),)
            return base + (value.get('status'),) if ad_group else base
        budget = actual['budgetId']
        if not re.fullmatch('customers/'+binding.account_id+r'/campaignBudgets/[0-9]+', budget):
            return None
        budgets = self.search(binding, "SELECT campaign_budget.amount_micros, campaign_budget.explicitly_shared" + (", campaign_budget.total_amount_micros, campaign_budget.period" if schedule is not None else "") + " FROM campaign_budget WHERE campaign_budget.resource_name = '"+budget+"' LIMIT 1")
        if not budgets or len(budgets) != 1:
            return None
        c, b, ad = row['campaign'], budgets[0]['campaignBudget'], row['adGroupAd'].get('ad', {})
        network = c.get('networkSettings', {})
        rsa = ad.get('responsiveSearchAd', {})
        budget_matches = (str(b.get('amountMicros')) == str(int(Decimal(plan['dailyBudget'])*1000000))) if schedule is None else (
            str(b.get('totalAmountMicros')) == str(int(Decimal(schedule['totalBudget'])*1000000))
            and b.get('period') == 'CUSTOM_PERIOD'
            and str(b.get('amountMicros', '0')) == '0'
            and c.get('startDateTime') == schedule['startDate']+' 00:00:00'
            and c.get('endDateTime') == schedule['endDate']+' 23:59:59')
        complete = (c.get('name') == 'Growthrova '+idempotency_key
                    and c.get('advertisingChannelType') == 'SEARCH' and c.get('biddingStrategyType') == 'MANUAL_CPC'
                    and c.get('containsEuPoliticalAdvertising') == settings['politicalDeclaration']
                    and network.get('targetGoogleSearch') is True
                    and all(network.get(k, False) is False for k in ('targetSearchNetwork', 'targetContentNetwork', 'targetPartnerSearchNetwork'))
                    and c.get('geoTargetTypeSetting', {}).get('positiveGeoTargetType') == 'PRESENCE'
                    and str(row['adGroup'].get('cpcBidMicros')) == settings['cpcBidMicros']
                    and budget_matches
                    and b.get('explicitlyShared', False) is False
                    and ad.get('finalUrls') == [plan['destinationUrl']]
                    and rsa.get('headlines') == [dict(text=v) for v in plan['headlines']]
                    and rsa.get('descriptions') == [dict(text=v) for v in plan['descriptions']]
                    and all(row[k].get('status') == 'PAUSED' for k in ('campaign', 'adGroup', 'adGroupAd'))
                    and campaign_criteria is not None and group_criteria is not None
                    and sorted(criterion(v['campaignCriterion']) for v in campaign_criteria) == sorted(expected_campaign)
                    and sorted(criterion(v['adGroupCriterion'], True) for v in group_criteria) == sorted(expected_group))
        return dict(id=idempotency_key, resources=actual, outcome='paused' if complete else 'partial')
