"""Optional assigned-account reads; no execution or returned credential-wide roster.

The operator allowlists business-owned accounts and rotates version on any grant,
credential or roster change. Fresh read authority is separate from paid authority.
A separately opted-in Page-task check inspects one bounded credential edge and
returns only the selected assigned Page observation. No cache/store: observations
expire with the screen; selections use PaidSetup.
"""
from dataclasses import dataclass, field
import re

import requests

from business_growthrova_paid_setup import CURRENCIES


@dataclass(frozen=True)
class DiscoveryBinding:
    owner_id: str
    organisation_id: str
    platform: str
    version: str
    account_ids: tuple
    enabled: bool = False
    access_token: str = field(default='', repr=False)
    developer_token: str = field(default='', repr=False)
    manager_id: str = ''
    graph_version: str = 'v26.0'  # Existing operator bindings retain their wire version.
    page_ids: tuple = ()  # Explicit assignments only; never a credential-wide roster.
    linkage_checks: bool = False  # Separately reviewed account-edge read eligibility.
    page_task_checks: bool = False  # Separate opt-in to one bounded credential Page edge.


def text(value, limit=180):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid account observation')
    return value


class PaidAccountDiscovery:
    def __init__(self, resolve, authorised, *, http=None):
        self.resolve, self.authorised, self.http = resolve, authorised, http

    def binding(self, scope, platform):
        value = self.resolve(*scope, platform)
        pattern = r'[0-9]{10}' if platform == 'google' else r'[0-9]{1,40}'
        if (not isinstance(value, DiscoveryBinding) or value.enabled is not True
                or (value.owner_id, value.organisation_id, value.platform) != (*scope, platform)
                or not isinstance(value.account_ids, tuple) or not 1 <= len(value.account_ids) <= 5
                or any(not isinstance(v, str) or not re.fullmatch(pattern, v) for v in value.account_ids)
                or len(set(value.account_ids)) != len(value.account_ids)
                or not value.access_token or (platform == 'google' and not value.developer_token)
                or (platform == 'meta' and (not isinstance(value.graph_version, str)
                    or not re.fullmatch(r'v[1-9][0-9]{0,2}\.0', value.graph_version)))
                or not isinstance(value.page_ids, tuple) or len(value.page_ids) > 5
                or (platform != 'meta' and value.page_ids)
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{1,40}', v) for v in value.page_ids)
                or len(set(value.page_ids)) != len(value.page_ids)
                or (value.manager_id and (platform != 'google' or not re.fullmatch(r'[0-9]{10}', value.manager_id)))):
            return None
        text(value.version)
        return value

    @staticmethod
    def identity(binding):
        identity = dict(ownerId=binding.owner_id, organisationId=binding.organisation_id,
                    platform=binding.platform, connectionVersion=binding.version,
                    accountIds=list(binding.account_ids), managerId=binding.manager_id)
        if binding.page_ids:
            identity['pageIds'] = list(binding.page_ids)
        if binding.linkage_checks is True:
            identity['linkageChecks'] = True
        if binding.page_task_checks is True:
            identity['pageTaskChecks'] = True
        return identity

    def permitted(self, binding):
        scope = (binding.owner_id, binding.organisation_id)
        return (self.binding(scope, binding.platform) == binding
                and self.authorised(*scope, binding.platform, self.identity(binding)) is True
                and self.binding(scope, binding.platform) == binding)

    def wire(self, method, url, binding, **options):
        headers = {'Authorization': 'Bearer '+binding.access_token}
        if binding.platform == 'google':
            headers['developer-token'] = binding.developer_token
            if binding.manager_id:
                headers['login-customer-id'] = binding.manager_id
        options.update(headers=headers, timeout=(3, 6), allow_redirects=False)
        if self.http is None:
            with requests.Session() as session:
                session.trust_env = False
                response = getattr(session, method)(url, **options)
        else:
            response = getattr(self.http, method)(url, **options)
        if response.status_code != 200 or len(getattr(response, 'content', b'')) > 100_000:
            raise ValueError('Account read not confirmed')
        return response.json()

    def read_account(self, binding, ident):
        if binding.platform == 'google':
            value = self.wire('post', f'https://googleads.googleapis.com/v26/customers/{ident}/googleAds:search', binding,
                json={'query': 'SELECT customer.id, customer.descriptive_name, customer.currency_code, '
                      'customer.time_zone, customer.status, customer.manager, customer.test_account FROM customer LIMIT 1'})
            if (not isinstance(value, dict) or value.get('error') or value.get('nextPageToken')
                    or not isinstance(value.get('results'), list) or len(value['results']) != 1):
                raise ValueError('Incomplete account read')
            row = value['results'][0]['customer']
            # Google REST omits protobuf scalar defaults, including false flags.
            if str(row['id']) != ident or type(row.get('manager', False)) is not bool or type(row.get('testAccount', False)) is not bool:
                raise ValueError('Account identity not confirmed')
            status = text(row['status'], 60)
            label, currency, zone = row.get('descriptiveName') or ident, row['currencyCode'], row['timeZone']
            selectable = status == 'ENABLED' and not row.get('manager', False) and not row.get('testAccount', False)
            reason = '' if selectable else 'Use an enabled client account for live preparation; manager, test or restricted accounts need separate setup.'
        else:
            row = self.wire('get', f'https://graph.facebook.com/{binding.graph_version}/act_{ident}', binding,
                params={'fields': 'account_id,name,currency,timezone_name,account_status,disable_reason'})
            if (not isinstance(row, dict) or row.get('error') or row.get('account_id') != ident
                    or type(row.get('account_status')) is not int or type(row.get('disable_reason')) is not int):
                raise ValueError('Account identity not confirmed')
            status = str(row['account_status'])
            label, currency, zone = row['name'], row['currency'], row['timezone_name']
            selectable = row['account_status'] == 1 and row['disable_reason'] == 0
            reason = '' if selectable else 'Review the account restriction in Meta Ads Manager before selecting it.'
        text(currency, 3)
        if currency not in CURRENCIES:
            selectable, reason = False, 'This account currency is not supported by campaign preparation yet.'
        return dict(accountId=ident, label=text(label), currency=currency, timezone=text(zone),
                    status=status, selectable=selectable, reason=reason,
                    managerId=binding.manager_id)

    def observe(self, scope, platform):
        binding = self.binding(scope, platform)
        if binding is None:
            return dict(available=False, accounts=[])
        accounts = []
        for ident in binding.account_ids:
            if not self.permitted(binding):
                raise ValueError('Account read authority changed')
            accounts.append(self.read_account(binding, ident))
            if not self.permitted(binding):
                raise ValueError('Account read authority changed')
        return dict(available=True, connectionVersion=binding.version, accounts=accounts)

    def observe_pages(self, scope, platform):
        if platform != 'meta':
            return dict(available=False, pages=[])
        binding = self.binding(scope, platform)
        if binding is None or not binding.page_ids:
            return dict(available=False, pages=[])
        pages = []
        for ident in binding.page_ids:
            if not self.permitted(binding):
                raise ValueError('Page read authority changed')
            row = self.wire('get', f'https://graph.facebook.com/{binding.graph_version}/{ident}',
                            binding, params={'fields': 'id,name'})
            if (not isinstance(row, dict) or row.get('error') or row.get('id') != ident):
                raise ValueError('Page identity not confirmed')
            pages.append(dict(pageId=ident, label=text(row.get('name'))))
            if not self.permitted(binding):
                raise ValueError('Page read authority changed')
        # Identity reads do not prove advertising tasks or ad-account linkage.
        return dict(available=True, connectionVersion=binding.version, pages=pages)

    def observe_linkage(self, scope, platform, account_id, page_id):
        if platform != 'meta':
            return dict(available=False)
        binding = self.binding(scope, platform)
        if binding is None or binding.linkage_checks is not True:
            return dict(available=False)
        if account_id not in binding.account_ids or page_id not in binding.page_ids:
            return dict(available=False)

        def read(path, params):
            if not self.permitted(binding):
                raise ValueError('Pair read authority changed')
            value = self.wire('get', f'https://graph.facebook.com/{binding.graph_version}/{path}',
                              binding, params=params)
            if not self.permitted(binding):
                raise ValueError('Pair read authority changed')
            return value

        account = read('act_'+account_id, {'fields': 'account_id,user_tasks'})
        if (not isinstance(account, dict) or account.get('error')
                or account.get('account_id') != account_id):
            raise ValueError('Account task identity not confirmed')
        tasks = account.get('user_tasks')
        if tasks is not None and (not isinstance(tasks, list) or len(tasks) > 50
                or any(not isinstance(t, str) or not re.fullmatch(r'[A-Z_]{1,80}', t) for t in tasks)):
            raise ValueError('Account tasks not confirmed')
        # One bounded account edge only. Never follow provider-supplied URLs,
        # expose other Page IDs, or equate a missing row with missing permission.
        value = read('act_'+account_id+'/promote_pages', {'fields': 'id', 'limit': 25})
        if (not isinstance(value, dict) or value.get('error')
                or not isinstance(value.get('data'), list) or len(value['data']) > 25
                or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or not re.fullmatch(r'[0-9]{1,40}', row['id']) for row in value['data'])):
            raise ValueError('Promotable Page observation not confirmed')
        page_tasks = None
        if binding.page_task_checks is True:
            # Meta exposes current-user Page tasks on the accounts edge, not
            # the ordinary Page identity read. This broader edge needs its own
            # host opt-in; inspect one bounded response and discard other Pages.
            pages = read('me/accounts', {'fields': 'id,tasks', 'limit': 25})
            if (not isinstance(pages, dict) or pages.get('error')
                    or not isinstance(pages.get('data'), list) or len(pages['data']) > 25
                    or any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
                        or not re.fullmatch(r'[0-9]{1,40}', row['id']) for row in pages['data'])):
                raise ValueError('Page task observation not confirmed')
            selected = [row for row in pages['data'] if row['id'] == page_id]
            if len(selected) > 1:
                raise ValueError('Page task identity not confirmed')
            page_tasks = selected[0].get('tasks') if selected else None
            if page_tasks is not None and (not isinstance(page_tasks, list) or len(page_tasks) > 50
                    or any(not isinstance(t, str) or not re.fullmatch(r'[A-Z_]{1,80}', t) for t in page_tasks)):
                raise ValueError('Page tasks not confirmed')
        return dict(available=True, connectionVersion=binding.version,
                    accountId=account_id, pageId=page_id,
                    accountAdvertiseTask='observed' if tasks is not None and 'ADVERTISE' in tasks else 'unconfirmed',
                    pageInPromotablePages=any(row['id'] == page_id for row in value['data']),
                    pageTasks='observed' if page_tasks is not None else 'unverified',
                    pageTaskCheckEnabled=binding.page_task_checks is True,
                    pageAdvertiseTask='observed' if page_tasks is not None and any(
                        task in ('ADVERTISE', 'PROFILE_PLUS_ADVERTISE') for task in page_tasks) else 'unconfirmed',
                    bounded=True)
