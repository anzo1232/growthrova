"""Pixel-bound creative review status. No heuristic can grant artistic approval."""
import hashlib,json
from contextlib import closing
from flask import jsonify
from business_marketing_drafts import MarketingDraftError,_id

VERSION='growthrova-creative-20261104'
CHECKS=('visual','factual','brand','commercial','legibility','crop','cta','wording')
RUBRIC={
 'visual':'Inspect actual pixels for coherent anatomy/objects, materials, lighting and believable detail.',
 'factual':'Compare every visible claim with current reviewed business evidence; no invented offers, outcomes or product fidelity.',
 'brand':'Check exact business name, saved palette and authorised logo treatment; no invented marks.',
 'commercial':'Judge a useful customer proposition and cohesive composition against the selected concept; compare sibling adverts for meaningful variety.',
 'legibility':'Read the actual headline, supporting line and CTA at phone size; inspect hierarchy and contrast.',
 'crop':'Inspect all edges, safe margins and complete subjects on the actual export frame.',
 'cta':'Check the entire CTA is readable, visible and appropriate for the reviewed destination/action.',
 'wording':'Transcribe and compare all visible words with the requested advertCopy; check spelling and unwanted microtext.'
}

def review_report(candidate,observations,pixels_match):
 """Accumulate explicit current checks; a stale positive never clears rejection."""
 states=dict.fromkeys(CHECKS,'not_reviewed')
 for observation in observations:
  for check,state in observation.get('checks',{}).items():
   if check not in states:continue
   if state=='needs_changes':
    states[check]=state
   elif observation.get('current') is True and state=='checked':
    states[check]=state
 failed=[k for k,v in states.items() if v=='needs_changes']
 missing=[k for k,v in states.items() if v=='not_reviewed']
 technical=bool(candidate.get('technicalReview',{}).get('flags'))
 held=not pixels_match or technical or bool(failed)
 return dict(standardVersion=VERSION,status='held' if held else 'pending_review' if missing else 'reviewed_draft',
  operationId=candidate.get('operationId'),sha256=candidate.get('sha256'),
  checks=states,missingChecks=missing,failedChecks=failed,criteria=RUBRIC.copy(),
  pixelsMatch=bool(pixels_match),approved=False,canPublish=False,canSpend=False,
  reviewAuthority='recorded_observations_not_independent_certification',
  limitation='Passing recorded checks is not owner approval, independent review or evidence of campaign performance.')

def register_creative_review_routes(app,repo,root,observe,*,revalidate=None):
 @app.get(root+'/<ident>/images/<operation>/creative-review')
 def creative_review(organisation_id,ident,operation):
  saved=repo.read(organisation_id,ident)
  _id(operation)
  with closing(repo._connect()) as con:
   row=con.execute('SELECT result_json,image_bytes FROM growthrova_image_requests WHERE document_id=? AND operation_id=?',
     (ident,operation)).fetchone()
   if not row:raise MarketingDraftError('Saved image request not found.','image_missing',404)
   candidate=json.loads(row['result_json'])
   if candidate.get('renderingMode')!='complete_advert':
    raise MarketingDraftError('Choose a complete advert for this review.','complete_advert_required',409)
   candidate=observe(con,ident,saved,candidate)
   matches=bool(row['image_bytes']) and hashlib.sha256(row['image_bytes']).hexdigest()==candidate.get('sha256')
   report=review_report(candidate,candidate.get('observations',[]),matches)
  if revalidate:
   error=revalidate()
   if error is not None:return error
  repo.read(organisation_id,ident)
  return jsonify(report)
