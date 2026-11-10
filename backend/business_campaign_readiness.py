"""One read-only campaign view: saved calendar + tenant-bound asset review.
Never implies that prepared content is produced, approved, published or paid.
"""
from datetime import date,timedelta
import business_marketing_drafts as drafts
import business_campaign_assets as assets
class ReadinessError(ValueError):pass

def overview(con,draft_id,revision,organisation_id,business_id):
 try:
  campaign=assets.overview(con,draft_id,revision,organisation_id,business_id)
  doc=drafts.read_draft(con,draft_id)['document']
 except (assets.CampaignAssetError,drafts.MarketingDraftError) as exc:
  raise ReadinessError(str(exc)) from exc
 start=doc.get('calendarStartDate') or ''
 try:base=date.fromisoformat(start) if start else None
 except ValueError as exc:raise ReadinessError('Invalid calendar start date') from exc
 posts=sorted(doc.get('posts',[]),key=lambda x:x['day'])
 entries=[{'day':p['day'],'date':(base+timedelta(days=p['day']-1)).isoformat() if base else None,
  'theme':p['theme'],'channel':p['channel'],'format':p['format'],
  'copyDraft':p['copyDraft'],'callToAction':p['callToAction'],
  'copyStatus':p['status'],'mediaReady':False,'scheduled':False,'published':False} for p in posts]
 return {'draftId':draft_id,'revision':revision,'documentSha256':campaign['documentSha256'],
  'businessId':business_id,'goal':doc['goal'],'sourceUrl':doc.get('sourceUrl',''),
  'calendarEntries':entries,'calendarCoverage':len(set(x['day'] for x in entries)),
  'completeThirtyDayCalendar':len(entries)==30 and {x['day'] for x in entries}==set(range(1,31)),
  'calendarGaps':sorted(set(range(1,31))-{x['day'] for x in entries}),
  'ownerAssets':campaign['assetCandidates'],'ownerAssetCount':campaign['assetCount'],
  'researchVerified':False,'ownerApprovalVerified':False,'mediaProduced':False,
  'canSpend':False,'canPublish':False,
  'nextAction':'complete_thirty_day_calendar' if len(entries)!=30 or {x['day'] for x in entries}!=set(range(1,31)) else 'verify_business_research_and_owner_brief'}
