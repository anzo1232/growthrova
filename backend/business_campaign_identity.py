"""Trusted internal-only organisation/business binding for local marketing drafts.
No HTTP write endpoint, login verification, spend, or publication authority.
"""
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_asset_catalog as catalog

class BindingError(ValueError):pass

def initialise(con):
 con.execute('CREATE TABLE IF NOT EXISTS business_campaign_identity(draft_id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, business_id TEXT NOT NULL, document_sha TEXT NOT NULL, verified_owner_reference TEXT NOT NULL)')

def bind_internal(con,draft_id,revision,organisation_id,business_id,*,verified_owner_reference):
 """Caller must verify authenticated owner and tenancy out of band."""
 for value in (organisation_id,business_id):
  if not isinstance(value,str) or not catalog.ID.fullmatch(value):raise BindingError('Invalid tenant scope')
 if not isinstance(verified_owner_reference,str) or len(verified_owner_reference.strip())<12:raise BindingError('Verified owner evidence required')
 try:saved=drafts.read_draft(con,draft_id)
 except drafts.MarketingDraftError as exc:raise BindingError(str(exc)) from exc
 if type(revision) is not int or saved['revision']!=revision:raise BindingError('Stale campaign')
 sha=contracts._hash(saved['document'])
 row=con.execute('SELECT * FROM business_campaign_identity WHERE draft_id=?',(draft_id,)).fetchone()
 if row:
  if (row['organisation_id'],row['business_id'],row['verified_owner_reference'])!=(organisation_id,business_id,verified_owner_reference):raise BindingError('Campaign tenant binding is immutable')
  if row['document_sha']!=sha:
   # Reconfirm the latest saved campaign with the SAME tenant and trusted owner.
   # Never transfer a campaign between businesses or owners as a side effect.
   con.execute('UPDATE business_campaign_identity SET document_sha=? WHERE draft_id=? AND organisation_id=? AND business_id=? AND verified_owner_reference=?',
               (sha,draft_id,organisation_id,business_id,verified_owner_reference))
 else:con.execute('INSERT INTO business_campaign_identity VALUES(?,?,?,?,?)',(draft_id,organisation_id,business_id,sha,verified_owner_reference))
 return {'draftId':draft_id,'organisationId':organisation_id,'businessId':business_id,'documentSha256':sha,'canSpend':False,'canPublish':False}

def require(con,draft_id,revision,organisation_id,business_id):
 try:saved=drafts.read_draft(con,draft_id)
 except drafts.MarketingDraftError as exc:raise BindingError(str(exc)) from exc
 row=con.execute('SELECT * FROM business_campaign_identity WHERE draft_id=?',(draft_id,)).fetchone()
 if type(revision) is not int or saved['revision']!=revision or not row or row['organisation_id']!=organisation_id or row['business_id']!=business_id or row['document_sha']!=contracts._hash(saved['document']):raise BindingError('Current verified campaign tenant binding required')
 return True
