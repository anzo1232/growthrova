"""Dedicated campaign-only pause transports for the existing durable paid ledger.

No connection is installed here. Mutation needs both the ledger's separate pause
authority and a default-off binding plus fresh adapter eligibility. Creation
settings are deliberately irrelevant to stopping old resources. No remote retry
or name search: uncertain writes use read-only lookup of frozen resource IDs.
"""
from copy import deepcopy
import re


class PauseTransport:
    platform = None

    def observe_campaign(self, snap):
        """Read the exact tree using pause lookup scope; never request a pause.

        This is configured campaign state only, not effective ad delivery.
        Creation settings and expired spending approvals must not hide an old
        campaign, but the frozen account identity must still match.
        """
        binding = self.pause_binding(snap)
        if binding is None:
            return None
        status = self.pause_status(binding, snap)
        if self.pause_binding(snap) != binding:
            return None
        if status not in ('ACTIVE', 'ENABLED', 'PAUSED'):
            return None
        return dict(campaignState='paused' if status == 'PAUSED' else 'enabled')

    def pause_binding(self, snap, *, mutation=False):
        if (snap.get('intent') != 'pause_exact_resources'
                or snap.get('platform') != self.platform):
            return None
        binding = self.binding(snap['ownerId'], snap['organisationId'])
        if (not binding or not binding.access_token
                or (self.platform == 'google' and not binding.developer_token)
                or self.identity(binding) != snap.get('account')):
            return None
        if mutation:
            if (binding.pause_enabled is not True or not callable(self.pause_eligible)
                    or self.pause_eligible(deepcopy(snap)) is not True):
                return None
            # A trusted callback may rotate/revoke its binding while checking.
            current = self.binding(snap['ownerId'], snap['organisationId'])
            if current != binding:
                return None
        return binding

    def check_pause(self, snap):
        try:
            binding = self.pause_binding(snap, mutation=True)
            return (binding is not None and self.pause_status(binding, snap) is not None
                    and self.pause_binding(snap, mutation=True) == binding)
        except Exception:
            return False

    def pause(self, snap, *, idempotency_key):
        # The worker already committed dispatch intent. Even a timeout after
        # this single write must be reconciled through lookup, never retried.
        if not re.fullmatch(r'[a-f0-9]{64}', idempotency_key):
            return None
        binding = self.pause_binding(snap, mutation=True)
        if binding is None:
            return None
        status = self.pause_status(binding, snap)
        if status is None or self.pause_binding(snap, mutation=True) != binding:
            return None
        if status != 'PAUSED':
            if not self.write_pause(binding, snap):
                return None
        return self.lookup_pause(snap, idempotency_key=idempotency_key, reference=None)

    def lookup_pause(self, snap, *, idempotency_key, reference):
        if not re.fullmatch(r'[a-f0-9]{64}', idempotency_key):
            return None
        binding = self.pause_binding(snap)
        if binding is None:
            return None
        status = self.pause_status(binding, snap)
        if status is None or self.pause_binding(snap) != binding:
            return None
        # ACTIVE immediately after a write can reflect propagation delay. Keep
        # it uncertain for later reads rather than declaring a terminal failure.
        return dict(outcome='paused', resources=deepcopy(snap['resources'])) if status == 'PAUSED' else None


class MetaPauseTransport(PauseTransport):
    platform = 'meta'

    def pause_status(self, binding, snap):
        resources = snap.get('resources')
        if (not isinstance(resources, dict)
                or set(resources) != {'campaignId', 'adSetId', 'adId', 'creativeId', 'imageHash'}
                or any(not isinstance(resources[k], str) or not re.fullmatch(r'[0-9]{1,40}', resources[k])
                       for k in ('campaignId', 'adSetId', 'adId', 'creativeId'))
                or not isinstance(resources['imageHash'], str)
                or not re.fullmatch(r'[a-fA-F0-9]{32}', resources['imageHash'])):
            return None
        fields = dict(campaignId='id,account_id,status',
                      adSetId='id,account_id,campaign_id',
                      adId='id,account_id,campaign_id,adset_id,creative',
                      creativeId='id,account_id,object_story_spec')
        rows = {}
        for key, selected in fields.items():
            row = self.remote(binding, 'GET', resources[key], dict(fields=selected))
            if (not row or str(row.get('id')) != resources[key]
                    or str(row.get('account_id')) != binding.account_id):
                return None
            rows[key] = row
        group, ad = rows['adSetId'], rows['adId']
        if (str(group.get('campaign_id')) != resources['campaignId']
                or str(ad.get('campaign_id')) != resources['campaignId']
                or str(ad.get('adset_id')) != resources['adSetId']
                or str(ad.get('creative', {}).get('id')) != resources['creativeId']
                or rows['creativeId'].get('object_story_spec', {}).get('link_data', {}).get('image_hash') != resources['imageHash']):
            return None
        status = rows['campaignId'].get('status')
        return status if status in ('ACTIVE', 'PAUSED') else None

    def write_pause(self, binding, snap):
        result = self.remote(binding, 'POST', snap['resources']['campaignId'], dict(status='PAUSED'))
        return isinstance(result, dict) and result.get('success') is True


class GooglePauseTransport(PauseTransport):
    platform = 'google'

    def pause_status(self, binding, snap):
        resources = snap.get('resources')
        collections = dict(campaignId='campaigns', adGroupId='adGroups', adId='adGroupAds', budgetId='campaignBudgets')
        if not isinstance(resources, dict) or set(resources) != set(collections):
            return None
        for key, collection in collections.items():
            suffix = r'[0-9]+~[0-9]+' if key == 'adId' else r'[0-9]+'
            if (not isinstance(resources[key], str) or not re.fullmatch(
                    'customers/'+binding.account_id+'/'+collection+'/'+suffix, resources[key])):
                return None
        campaign = resources['campaignId']
        # Exact account-scoped names are validated above before interpolation.
        rows = self.search(binding, "SELECT campaign.resource_name, campaign.status, campaign.campaign_budget, ad_group.resource_name, ad_group_ad.resource_name FROM ad_group_ad WHERE ad_group_ad.resource_name = '"+resources['adId']+"' AND campaign.resource_name = '"+campaign+"' LIMIT 2")
        if not rows or len(rows) != 1:
            return None
        row = rows[0]
        actual = dict(campaignId=row['campaign']['resourceName'], budgetId=row['campaign']['campaignBudget'],
                      adGroupId=row['adGroup']['resourceName'], adId=row['adGroupAd']['resourceName'])
        if actual != resources:
            return None
        status = row['campaign'].get('status')
        return status if status in ('ENABLED', 'PAUSED') else None

    def write_pause(self, binding, snap):
        campaign = snap['resources']['campaignId']
        response = self.remote(binding, 'mutate', dict(mutateOperations=[dict(campaignOperation=dict(
            update=dict(resourceName=campaign, status='PAUSED'), updateMask='status'))],
            partialFailure=False, validateOnly=False, responseContentType='RESOURCE_NAME_ONLY'))
        if response.status_code != 200:
            return False
        data = response.json()
        return (isinstance(data, dict) and not data.get('error') and not data.get('partialFailureError')
                and data.get('mutateOperationResponses') == [dict(campaignResult=dict(resourceName=campaign))])
