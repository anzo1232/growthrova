"""Business-wide saved payment review. No provider reads or purchase writes."""
from contextlib import closing
import json
import time

from flask import jsonify, request
from business_marketing_drafts import MarketingDraftError
from business_marketing_offline import OfflineDocumentAccessError


def register_payment_queue(app, repo, root, *, revalidate):
    @app.get(root + '/payment-review')
    def growthrova_business_payment_review(organisation_id):
        if request.args:
            raise MarketingDraftError('Use the workspace filters for saved payment evidence.')
        scope = repo._scope(organisation_id)
        with closing(repo._connect()) as con:
            con.execute('BEGIN')
            # The existing business receipt limit is 5,000. Join every ownership
            # identity, including the enquiry, before releasing a projection.
            rows = con.execute('SELECT r.*,l.revision,l.data_json,d.document_json,c.observation_json '
                'FROM growthrova_payment_receipts r '
                'JOIN growthrova_leads l ON l.id=r.lead_id AND l.document_id=r.document_id '
                'AND l.owner_id=r.owner_id AND l.organisation_id=r.organisation_id '
                'JOIN offline_document_owners o ON o.draft_id=r.document_id '
                'AND o.owner_id=r.owner_id AND o.organisation_id=r.organisation_id '
                'JOIN marketing_drafts d ON d.id=r.document_id '
                'LEFT JOIN growthrova_payment_checks c ON c.account_id=r.account_id AND c.charge_id=r.charge_id '
                'WHERE r.owner_id=? AND r.organisation_id=? '
                'ORDER BY r.recorded DESC,r.account_id,r.charge_id', scope).fetchall()
            payments = []
            for row in rows:
                initial = json.loads(row['sale_json'])
                data = json.loads(row['data_json'])
                current = (data.get('sale') if row['purchase_key'] == 'sale' else
                    next((item for item in data.get('purchases', []) if item['id'] == row['purchase_key']), None))
                # Compare the complete original sale, but expose no correction
                # wording or source reference in this business-wide summary.
                changed = current is None or any(current.get(key) != value for key, value in initial.items())
                money_fields = ('amount', 'currency', 'date', 'state')
                latest = json.loads(row['observation_json']) if row['observation_json'] else None
                evidence = None if latest is None else {key: latest[key] for key in (
                    'checkedAt', 'needsRecheck', 'refundedAmount', 'fullyRefunded', 'disputed',
                    'objectKind', 'objectCurrency', 'objectAmountMinor', 'objectStatus') if key in latest}
                payments.append(dict(campaignId=row['document_id'], enquiryId=row['lead_id'],
                    enquiryRevision=row['revision'], campaignName=json.loads(row['document_json'])['name'],
                    name=data['name'], accountId=row['account_id'], chargeId=row['charge_id'],
                    purchaseKey=row['purchase_key'], initialCheckedAt=row['recorded'],
                    initial={key: initial[key] for key in money_fields},
                    current={key: current[key] for key in money_fields} if current else None,
                    ownerChanged=changed, latest=evidence))
            error = revalidate() if revalidate else None
            if error is not None:
                return error
            if repo._scope(organisation_id) != scope:
                raise OfflineDocumentAccessError('Business access changed')
            response = jsonify(payments=payments, total=len(payments), observedAt=time.time())
            response.headers['Cache-Control'] = 'no-store'
            return response
