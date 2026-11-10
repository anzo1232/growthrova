"""Explicit Growthrova generation admission; never consults creator billing.

The operator resolver must be a bounded local metadata read of independently
verified grants. It must not make network calls or mutate the request database:
admission runs inside the existing generation reservation transaction. This is
coverage admission, not metered credits, checkout or event verification.
"""
from dataclasses import dataclass
import math
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError


@dataclass(frozen=True)
class GenerationAccessConfig:
    enforced: bool = False
    resolve: object = None
    clock: object = time.time
    source: str = 'operator'

    def __post_init__(self):
        if self.source not in ('operator', 'test_subscription') or type(self.enforced) is not bool or not callable(self.clock):
            raise ValueError('Explicit generation access policy required')
        if self.enforced and not callable(self.resolve):
            raise ValueError('Enforced access requires a verified local grant resolver')


class GenerationAccess:
    def __init__(self, repo, config=None, credit_config=None):
        self.repo = repo
        self.config = config or GenerationAccessConfig()
        from business_growthrova_credits import GenerationCredits
        self.credits = GenerationCredits(repo, credit_config) if credit_config else None

    def status(self, organisation_id):
        owner, org = self.repo._scope(organisation_id)
        if not self.config.enforced:
            return dict(mode='preview', state='unconfigured', newGenerationAllowed=True,
                        billingConfigured=False, creditBalance=None)
        try:
            row = self.config.resolve(owner, org)
            now = self.config.clock()
            if row is None:
                return dict(mode='enforced', accessSource=self.config.source, state='missing', newGenerationAllowed=False,
                            billingConfigured=False, creditBalance=None)
            if (not isinstance(row, dict) or row.get('ownerId') != owner
                    or row.get('organisationId') != org
                    or row.get('state') not in ('active', 'suspended')
                    or not isinstance(row.get('version'), str)
                    or not 1 <= len(row['version']) <= 128
                    or any(type(row.get(key)) not in (int, float)
                           or not math.isfinite(row[key]) for key in ('from', 'until'))
                    or row['from'] < 0 or not row['from'] < row['until'] <= 253402300799
                    or type(now) not in (int, float) or not math.isfinite(now)):
                raise ValueError('Invalid grant')
            state = ('suspended' if row['state'] == 'suspended' else
                     'scheduled' if now < row['from'] else
                     'expired' if now >= row['until'] else 'active')
            return dict(mode='enforced', accessSource=self.config.source, state=state, newGenerationAllowed=state == 'active',
                        grantVersion=row['version'], validFrom=row['from'], validUntil=row['until'],
                        billingConfigured=False, creditBalance=None)
        except Exception:
            # Never leak resolver exceptions, upstream payloads or billing identifiers.
            raise MarketingDraftError('Generation access could not be checked. Saved work is retained; retry the access check.',
                                      'generation_access_unavailable', 503) from None

    def overview(self, organisation_id):
        status = self.status(organisation_id)
        if self.credits:
            credits = self.credits.status(organisation_id)
            status['credits'] = credits
            status['creditBalance'] = credits.get('remaining')
            status['newGenerationAllowed'] = (status['newGenerationAllowed'] and credits['available']
                and credits['remaining'] >= min(credits['writingCost'], credits['imageCost']))
        return status

    def admit(self, organisation_id, *, con=None, family=None):
        status = self.status(organisation_id)
        if not status['newGenerationAllowed']:
            raise MarketingDraftError('New generation is paused for this business. Review Generation access; saved work and pending request checks remain available.',
                                      'generation_access_required', 403)
        result = {key: status[key] for key in ('mode', 'grantVersion', 'validFrom', 'validUntil') if key in status}
        if self.credits:
            if con is None or not con.in_transaction:
                raise ValueError('Credit reservation requires the request transaction')
            result['credits'] = self.credits.reserve(organisation_id, con, family)
        return result


def register_generation_access(app, repo, root, *, config=None, credit_config=None, revalidate=None):
    service = GenerationAccess(repo, config, credit_config)
    app.extensions['growthrova_generation_access'] = service

    @app.get(root + '/generation-access')
    def generation_access_status(organisation_id):
        service.overview(organisation_id)
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        # Re-read local grant after the potentially slow ownership check.
        return jsonify(service.overview(organisation_id))

    @app.get(root + '/generation-credit-activity')
    def generation_credit_activity(organisation_id):
        page = request.args.get('page', '1')
        if not page.isascii() or not page.isdigit() or len(page) > 7 or not 1 <= int(page) <= 1000000:
            raise MarketingDraftError('Choose a valid credit activity page.', 'invalid_input', 400)
        scope = repo._scope(organisation_id)
        result = (service.credits.activity(organisation_id, int(page)) if service.credits else
                  dict(allowance=dict(state='unconfigured', available=False), count=0,
                       page=1, pageSize=50, pages=1, groups=[], requests=[]))
        if revalidate:
            error = revalidate()
            if error is not None:
                return error
        if repo._scope(organisation_id) != scope:
            raise MarketingDraftError('Business access changed. Refresh before reviewing credits.', 'access_denied', 403)
        response = jsonify(result)
        response.headers['Cache-Control'] = 'no-store'
        return response

    return service
