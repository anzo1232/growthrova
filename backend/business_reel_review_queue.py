"""Private internal creative-director queue for isolated Clippr Business.

Read-only: no approval, generation, provider submission or publishing actions.
Use authenticated staff tooling to pass decisions into private reviewer APIs;
never expose a staff acceptance endpoint through the local customer pilot.
"""
from __future__ import annotations
import json
import business_reel_workbench as workbench
import business_marketing_drafts as drafts

PRIORITY={'semantic_rejected':0,'technical_rejected':1,'rejected':2,
          'reconcile_required':3,'provider_failed':4,'provider_rejected':4,
          'awaiting_internal_review':5,'awaiting_internal_import':6,
          'provider_queued':7,'provider_running':7,'not_generated':8,
          'awaiting_authorised_brand_assets':9,'accepted':10}

def queue(con,*,draft_id=None,limit=60):
 if draft_id is not None:drafts._id(draft_id)
 if type(limit)!=int or not 1<=limit<=100:raise ValueError('Invalid review queue limit')
 rows=con.execute('SELECT id,draft_id FROM business_reel_projects '
  +('WHERE draft_id=? ' if draft_id else '')
  +'ORDER BY created DESC LIMIT ?',([draft_id,limit] if draft_id else [limit])).fetchall()
 items=[]
 for record in rows:
  current=workbench.read(con,record['id'])
  if not current['isCurrentRevision']:continue
  for s in current['slots']:
   status=s['productionStatus']
   if status=='accepted':continue
   reason=s.get('reviewReason') or s.get('providerErrorCode')
   visual=s.get('technicalQC') or {}
   machine=s.get('automaticVisualReviewStatus') or 'not_run'
   if status in ('technical_rejected','semantic_rejected','rejected',
     'provider_failed','provider_cancelled','provider_rejected'):
    action='Preserve passing footage; reject this shot; compare two free edits before requesting new paid generation.'
   elif status in ('reconcile_required',):
    action='Reconcile original provider task and actual provider cost; do not retry.'
   elif status=='awaiting_internal_review':
    action='Inspect source-linked shot and real decoded frames; record all seven category findings and a signed verdict.'
   elif status=='awaiting_internal_import':
    action='Import the original completed video, verify its SHA-256 and run staged QC.'
   elif status=='awaiting_authorised_brand_assets':
    action='Require rights-confirmed logo, business contact and CTA before final review.'
   else:
    action='Wait for approved footage or a separately approved provider quote.'
   items.append({'projectId':current['id'],'draftId':current['draftId'],
    'business':current['business'],'slot':s['slot'],'status':status,
    'priority':PRIORITY.get(status,10),'reason':reason or 'No independent creative decision recorded',
    'sourceEvidence':s.get('sourceEvidence','')[:200],
    'sourceDirection':s.get('sourceDirection','')[:160],
    'manualCategoriesReviewed':s.get('visualCategoriesReviewed',[]),
    'machineReview':machine,'technicalSampleCount':len(visual.get('cheapVisualReview',{}).get('frameSamples',[])),
    'nextAction':action,'projectProviderCost':current['providerCreditsForThisReel'],
    'customerAllowanceConsumed':current['customerAllowanceConsumed'],
    'newPaidGenerationApproved':False,'ownerVisibleAsFinished':False})
 items.sort(key=lambda x:(x['priority'],x['business'],x['slot']))
 return {'pending':items[:limit],'totalPending':len(items),
  'internalOnly':True,'customerCanApproveFromQueue':False,
  'paidGenerationStartedByQueue':False,
  'publishingDisabled':True,'requiresAuthorisedReviewer':True}

def statistics(con,*,draft_id=None):
 data=queue(con,draft_id=draft_id,limit=100)
 counters={}
 for item in data['pending']:counters[item['status']]=counters.get(item['status'],0)+1
 return {'byState':counters,'total':data['totalPending'],
  'noAutomaticPaidRetry':True,'noClientAllowanceChargedForFailedQc':True}

def render_staff_report(con,*,draft_id=None):
 """Private read-only HTML queue for an authorised staff workstation.

 No controls that would mark work approved, spend model credits or publish.
 Escape ALL business-originated text as untrusted input.
 """
 from html import escape
 summary=queue(con,draft_id=draft_id)
 cells=[]
 for x in summary['pending']:
  fields=(('Priority',str(x['priority'])),('Business',x['business']),
   ('Shot',x['slot']),('Status',x['status']),
   ('Source',x['sourceEvidence']),('QC reason',x['reason']),
   ('Next step',x['nextAction']),('Provider credits',str(x['projectProviderCost'])),
   ('Customer allowance used',str(x['customerAllowanceConsumed'])))
  contents=''.join('<div><small>'+escape(k)+'</small><p>'+escape(str(v),quote=True)+'</p></div>'
   for k,v in fields)
  cells.append('<article>'+contents+'</article>')
 return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
  '<meta name="viewport" content="width=device-width,initial-scale=1">'
  '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;;">'
  '<title>Internal Reel Creative Review</title><style>'
  'body{font:14px system-ui;margin:32px auto;max-width:1100px;padding:0 18px;color:#20352c;background:#f6f6f1}'
  'header{border-bottom:1px solid #c5d1c8;padding-bottom:12px}h1{font-size:25px;letter-spacing:-.03em}'
  'section{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;padding-top:18px}'
  'article{border:1px solid #d4dcd5;border-radius:12px;padding:18px;background:white;min-width:0}'
  'article div{margin:0 0 7px;border-bottom:1px solid #eef1ee}'
  'small{color:#657968;font-size:10px;text-transform:uppercase;letter-spacing:.13em}'
  'p{overflow-wrap:anywhere;line-height:1.45;margin:4px 0 10px}'
  '.notice{font-size:12px;color:#71594a}footer{margin:22px 0}</style></head><body>'
  '<header><h1>Clippr Business · Internal Creative QC</h1>'
  '<p class="notice">Private read-only queue · source facts unverified · '
  'no customer approvals, paid calls or publishing</p><strong>'+
  str(summary['totalPending'])+' shot(s) awaiting resolution</strong></header><section>'
  +''.join(cells)+'</section><footer class="notice">A technical pass is not a creative '
  'approval. Review original videos and brand evidence internally.</footer></body></html>')
