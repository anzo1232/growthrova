"""Optional read-only transports. Dedicated operator bindings only; never installed here.

The resolver must rotate version on grant/credential/account changes. Config's
separate authorised callback freshly establishes read grants, project access and
commercial authority. No account enrolment, ambient credentials, token refresh,
remote retry, scheduling, mutations, conversions or sales inference.
"""
from dataclasses import dataclass, field
from decimal import Decimal
import json
import re

import requests


def numeric(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,39}', value) is not None


def count(value):
    if isinstance(value, bool) or not re.fullmatch(r'[0-9]{1,13}', str(value)) or int(value) > 10**12:
        raise ValueError('Invalid count')
    return int(value)


@dataclass(frozen=True)
class ReportingBinding:
    owner_id: str
    organisation_id: str
    platform: str
    account_id: str
    label: str
    version: str
    currency: str
    timezone: str
    verified: bool = False
    enabled: bool = False
    access_token: str = field(default='', repr=False)
    login_customer_id: str = ''


class ReportingAdapter:
    platform = None

    def __init__(self, resolve, *, http=None):
        self.resolve, self.http = resolve, http

    @staticmethod
    def identity(binding):
        return dict(ownerId=binding.owner_id, organisationId=binding.organisation_id,
                    platform=binding.platform, accountId=binding.account_id, label=binding.label,
                    connectionVersion=binding.version, currency=binding.currency, timezone=binding.timezone)

    def binding(self, owner, business):
        value = self.resolve(owner, business, self.platform)
        if (not isinstance(value, ReportingBinding) or value.enabled is not True or value.verified is not True
                or (value.owner_id, value.organisation_id, value.platform) != (owner, business, self.platform)
                or not numeric(value.account_id) or not value.access_token
                or (value.login_customer_id and not re.fullmatch(r'[0-9]{10}', value.login_customer_id))
                or (self.platform == 'google' and not re.fullmatch(r'[0-9]{10}', value.account_id))):
            return None
        return value

    def account(self, owner, business):
        binding = self.binding(owner, business)
        return self.identity(binding) if binding else None

    def checked_binding(self, snap):
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if not binding or self.identity(binding) != snap['account']:
            raise ValueError('Reporting connection changed')
        return binding

    def wire(self, method, url, binding, **options):
        headers = dict(Authorization='Bearer '+binding.access_token)
        if self.platform == 'google' and binding.login_customer_id:
            headers['login-customer-id'] = binding.login_customer_id
        if self.http is not None:
            response = getattr(self.http, method)(url, headers=headers,
                                timeout=(5, 25), allow_redirects=False, **options)
        else:
            # Dedicated bearer credentials only: requests must not consult ambient
            # netrc/proxy authentication or follow redirects with account headers.
            with requests.Session() as session:
                session.trust_env = False
                response = getattr(session, method)(url, headers=headers,
                                    timeout=(5, 25), allow_redirects=False, **options)
        if response.status_code != 200:
            raise ValueError('Reporting request not confirmed')
        if len(getattr(response, 'content', b'')) > 2_000_000:
            raise ValueError('Reporting response exceeds bound')
        return response.json()

    def report(self, snap, rows):
        self.checked_binding(snap)
        a = snap['account']
        return dict(platform=self.platform, accountId=a['accountId'], campaignId=snap['campaignId'],
                    currency=a['currency'], timezone=a['timezone'],
                    sourceReference=f"{self.platform} daily campaign API read · {snap['from']} to {snap['to']}", rows=rows)


class GoogleReportingAdapter(ReportingAdapter):
    platform = 'google'
    API = 'https://googleads.googleapis.com/v26'

    def query(self, binding, query):
        value = self.wire('post', f'{self.API}/customers/{binding.account_id}/googleAds:searchStream',
                          binding, json=dict(query=query))
        if not isinstance(value, list) or len(value) > 101:
            raise ValueError('Incomplete Google report')
        rows = []
        for batch in value:
            if not isinstance(batch, dict) or batch.get('error') or not isinstance(batch.get('results', []), list):
                raise ValueError('Invalid Google report')
            rows.extend(batch.get('results', []))
        if len(rows) > 100:
            raise ValueError('Report exceeds date bound')
        return rows

    def read(self, snap):
        binding = self.checked_binding(snap)
        customer = self.query(binding, 'SELECT customer.id, customer.currency_code, customer.time_zone FROM customer LIMIT 1')
        if len(customer) != 1:
            raise ValueError('Customer not confirmed')
        observed = customer[0]['customer']
        if (str(observed['id']) != binding.account_id or observed['currencyCode'] != binding.currency
                or observed['timeZone'] != binding.timezone):
            raise ValueError('Reporting account changed')
        self.checked_binding(snap)
        # Scope and dates have already been strictly normalised by the private route.
        if not numeric(snap['campaignId']) or any(not re.fullmatch(r'\d{4}-\d{2}-\d{2}', snap[k]) for k in ('from', 'to')):
            raise ValueError('Invalid report request')
        query = ("SELECT campaign.id, segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros "
                 f"FROM campaign WHERE campaign.id = {snap['campaignId']} "
                 f"AND segments.date BETWEEN '{snap['from']}' AND '{snap['to']}' ORDER BY segments.date LIMIT 101")
        records = self.query(binding, query)
        rows = []
        for record in records:
            if str(record['campaign']['id']) != snap['campaignId']:
                raise ValueError('Campaign mismatch')
            metrics = record.get('metrics', {})
            cost = metrics.get('costMicros', '0')
            if not re.fullmatch(r'[0-9]{1,15}', str(cost)):
                raise ValueError('Invalid cost')
            rows.append(dict(date=record['segments']['date'], impressions=count(metrics.get('impressions', '0')),
                             clicks=count(metrics.get('clicks', '0')), spend=format(Decimal(str(cost))/1000000, 'f')))
        return self.report(snap, rows)


class MetaReportingAdapter(ReportingAdapter):
    platform = 'meta'
    API = 'https://graph.facebook.com/v26.0'

    def read(self, snap):
        binding = self.checked_binding(snap)
        account = self.wire('get', f'{self.API}/act_{binding.account_id}', binding,
                            params=dict(fields='account_id,currency,timezone_name'))
        if (str(account['account_id']) != binding.account_id or account['currency'] != binding.currency
                or account['timezone_name'] != binding.timezone):
            raise ValueError('Reporting account changed')
        self.checked_binding(snap)
        value = self.wire('get', f'{self.API}/act_{binding.account_id}/insights', binding, params=dict(
            fields='account_id,campaign_id,account_currency,date_start,date_stop,impressions,clicks,spend',
            level='campaign', time_increment=1, limit=101,
            time_range=json.dumps(dict(since=snap['from'], until=snap['to'])),
            filtering=json.dumps([dict(field='campaign.id', operator='IN', value=[snap['campaignId']])])))
        # Never follow a provider-supplied URL containing credentials. The bounded
        # campaign/day request fits one page; reject any incomplete page wholesale.
        if (not isinstance(value, dict) or not isinstance(value.get('data'), list)
                or len(value['data']) > 100 or value.get('paging', {}).get('next')):
            raise ValueError('Incomplete Meta report')
        rows = []
        for record in value['data']:
            if (str(record['account_id']) != binding.account_id or record['account_currency'] != binding.currency
                    or str(record['campaign_id']) != snap['campaignId'] or record['date_start'] != record['date_stop']):
                raise ValueError('Campaign/date mismatch')
            rows.append(dict(date=record['date_start'], impressions=count(record['impressions']),
                             clicks=count(record['clicks']), spend=record['spend']))
        return self.report(snap, rows)
