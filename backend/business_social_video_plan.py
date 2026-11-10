"""Durable five-second motion-ad pre-production from an exact reviewed hero direction.

NO provider submissions, payments, retries, publication or fabricated completed footage.
"""
from __future__ import annotations
import hashlib,json,re,time
import business_marketing_drafts as drafts
import business_hero_history as hero

MODEL="gen4.5"
DURATION=5
RATIO="720:1280"
CREDIT_ESTIMATE=60
DIRECTIONS={
 "restaurant":(
  "First second: a restaurant door swings open as two friends visibly step into a warmly lit fictional dining space. "
  "Seconds 1–3: the camera moves alongside them, with convincing parallax and real footsteps. "
  "Seconds 3–5: a server guides them towards a table, with natural body motion and no identifiable branded venue. "
  "No food presented as a verified menu item.",
  "First second: an empty table suddenly becomes lively as fictional diners pull chairs back and sit down. "
  "Seconds 1–3: handheld tracking reveals warm real-looking dining atmosphere and human interaction. "
  "Seconds 3–5: natural motion as two guests gesture to each other in conversation. No fabricated actual menu or premises."
 ),
 "beauty":(
  "First second: a customer enters a fictional neutral wellness studio, door clearly moves. "
  "Seconds 1–3: lateral handheld camera follows towards a clean consultation area. "
  "Seconds 3–5: an adult professional gestures to a chair, no treatment or results depicted.",
  "First second: a person visibly opens the door of a fictional spa reception. "
  "Seconds 1–3: camera tracks the arrival; real clothing and natural human movement. "
  "Seconds 3–5: calm check-in consultation scene. No clinical treatment, outcomes or invented endorsements."
 ),
 "construction":(
  "First second: a carpenter's gloved hand moves a measuring tape across unbranded timber in a fictional UK interior. "
  "Seconds 1–3: tracking camera reveals believable construction materials with scale and parallax. "
  "Seconds 3–5: carpenter marks an accurate measured line. No client project or before-after claim.",
  "First second: real movement of work boots walking across a fictional empty renovation site. "
  "Seconds 1–3: ground-height tracking pans to tools and a clear measuring action. "
  "Seconds 3–5: tradesperson handles an unbranded sample material. No fabricated completed job."
 ),
 "concierge":(
  "First second: an unbranded vehicle visibly pulls up outside a fictional urban event venue. "
  "Seconds 1–3: realistic wheel rotation and lateral camera movement. "
  "Seconds 3–5: door opens and guests step out into ambient blue-hour light. No real venue or exclusive-access claim.",
  "First second: unbranded luggage rolls across an imaginary premium hotel lobby. "
  "Seconds 1–3: natural walking and obvious foreground-to-background motion. "
  "Seconds 3–5: luggage handed to a fictional concierge silhouette. No real person, property or booking claim."
 ),
 "roofing":(
  "First second: rain visibly flows into an overflowing gutter on a fictional UK home viewed safely from the ground. "
  "Seconds 1–3: camera moves sideways past water droplets to reveal roofline. "
  "Seconds 3–5: a grounded tradesperson gestures toward the problem, no unsafe climbing or repair guarantee.",
  "First second: wind moves wet leaves beside a fictional roof gutter. "
  "Seconds 1–3: camera tracks sideways revealing water spilling from a downpipe. "
  "Seconds 3–5: a worker safely observes the issue from the ground. No invented real job."
 ),
 "other":(
  "First second: a believable fictional customer enters a service environment with visible movement. "
  "Seconds 1–3: one real service-related action with strong foreground-to-background parallax. "
  "Seconds 3–5: reveal how someone can ask for more information. Do not fabricate the business's work.",
  "First second: a relevant service object or person moves with natural physics in an illustrative setting. "
  "Seconds 1–3: smooth tracking camera movement shows context and purposeful action. "
  "Seconds 3–5: dynamic finishing shot with room for a later verified CTA."
 )
}
GUARD=("Vertical 9:16, photorealistic editorial film, plausible physics, natural skin and hands, true parallax. "
       "This is fictional illustrative creative, not actual premises, staff, customers, venue, work, menu or results. "
       "No on-image lettering, logos, identifiable trademarks, unsupported prices, medical results, claims or celebrity. "
       "No still-photo pan, static building, slideshow, fake footage, text-only video or automatic speech.")
class VideoPlanError(ValueError):
 def __init__(self,message,code='video_plan_invalid',status=400):
  super().__init__(message);self.code=code;self.status=status

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_video_proposals(
  id TEXT PRIMARY KEY,draft_id TEXT NOT NULL,hero_round INTEGER NOT NULL,
  variant TEXT NOT NULL,request_hash TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,sector TEXT NOT NULL,prompt TEXT NOT NULL,
  hook TEXT NOT NULL,cta TEXT NOT NULL,created REAL NOT NULL,
  UNIQUE(draft_id,hero_round,variant))''')
 con.execute('''CREATE INDEX IF NOT EXISTS business_video_proposal_draft_idx ON
  business_video_proposals(draft_id,created)''')

def _storyboard(sector,variant):
    script=DIRECTIONS[sector][0 if variant=='a' else 1]
    pieces=re.split(r'(?=Seconds 1–3:|Seconds 3–5:)',script)
    spans=('0–1s','1–3s','3–5s')
    if len(pieces)!=3:raise VideoPlanError('Video storyboard incomplete','storyboard_invalid',409)
    return [{'time':spans[i],'title':('Stop the scroll','Show real motion','Memorable finish')[i],
             'action':pieces[i].replace('First second:','').replace('Seconds 1–3:','').replace('Seconds 3–5:','').strip()}
            for i in range(3)]

def _public(row):
 return dict(
  id=row['id'],draftId=row['draft_id'],heroRound=row['hero_round'],variant=row['variant'],
  status=row['status'],model=MODEL,duration=DURATION,ratio=RATIO,creditsEstimated=CREDIT_ESTIMATE,
  hook=row['hook'],cta=row['cta'],prompt=row['prompt'],storyboard=_storyboard(row['sector'],row['variant']),
  asset=None,generated=False,publishApproved=False,spendAuthorised=False,
  automaticRetries=False,ownerMediaApprovalRequired=True,sourceDisclosure="Illustrative fictional footage; not the business's actual venue or work.")

def list_plans(con,did):
 drafts._id(did);drafts.read_draft(con,did)
 return [_public(row) for row in con.execute('SELECT * FROM business_video_proposals WHERE draft_id=? ORDER BY created',(did,))]

def propose(con,body):
 if not isinstance(body,dict) or set(body)!={'draftId','heroRound','variant'}:
  raise VideoPlanError('Exact saved video direction required')
 did=drafts._id(body['draftId'])
 round_no=body['heroRound'];variant=body['variant']
 if type(round_no)!=int or not 0<=round_no<=30 or variant not in ('a','b'):
  raise VideoPlanError('Select a saved video direction','bad_selection',400)
 campaign=drafts.read_draft(con,did)
 hero_set=con.execute('SELECT * FROM business_hero_sets WHERE draft_id=?',(did,)).fetchone()
 if not hero_set:raise VideoPlanError('Confirm and save the creative directions first','not_started',409)
 if campaign['revision']!=hero_set['campaign_revision']:
  raise VideoPlanError('Campaign changed; re-verify facts before proposing paid footage','stale_business_facts',409)
 row=con.execute('SELECT * FROM business_hero_rounds WHERE draft_id=? AND slot=? AND round_no=?',(did,'social',round_no)).fetchone()
 if not row:raise VideoPlanError('Unknown video direction','not_found',404)
 if round_no!=hero._latest(con,did,'social'):
  raise VideoPlanError('Select the latest saved video direction','outdated_direction',409)
 reject=con.execute('SELECT 1 FROM business_hero_decisions WHERE draft_id=? AND slot=? AND round_no=? AND variant=?',
  (did,'social',round_no,variant)).fetchone()
 if reject:raise VideoPlanError('Rejected direction cannot be prepared for video','rejected_direction',409)
 sector=hero_set['sector'];direction=row['direction_'+variant]
 # Prompts are authored as part of the exact immutable proposal, not user-provided payloads.
 hook="Visible human/service action within the first second, no static opening"
 cta="See confirmed services or enquire through the business's real website (editable overlay, not baked into generated footage)"
 prompt=(DIRECTIONS[sector][0 if variant=='a' else 1]+' '
  'Company context is only an unverified owner description: '+hero_set['offer'][:160]+'. '
  'Direction to visually review: '+direction[:1400]+'. '+GUARD)[:3800]
 fingerprint=hashlib.sha256(json.dumps((did,round_no,variant,prompt),ensure_ascii=False).encode()).hexdigest()
 uid=fingerprint[:32]
 con.execute('BEGIN IMMEDIATE')
 try:
  existing=con.execute('SELECT * FROM business_video_proposals WHERE request_hash=?',(fingerprint,)).fetchone()
  if existing:con.commit();return _public(existing)
  saved=con.execute('SELECT * FROM business_video_proposals WHERE draft_id=? AND hero_round=? AND variant=?',(did,round_no,variant)).fetchone()
  if saved:raise VideoPlanError('A proposal already exists; do not duplicate generation requests','duplicate_proposal',409)
  now=time.time()
  con.execute('INSERT INTO business_video_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?)',
   (uid,did,round_no,variant,fingerprint,'awaiting_exact_spend_approval',sector,prompt,hook,cta,now))
  con.commit()
 except BaseException:
  con.rollback();raise
 return _public(con.execute('SELECT * FROM business_video_proposals WHERE id=?',(uid,)).fetchone())

def current_quote():
 return {'model':MODEL,'duration':DURATION,'ratio':RATIO,'estimatedCredits':CREDIT_ESTIMATE,
  'priceAssumption':'12 Runway API credits per second; read-only pricing estimate',
  'providerRequestSubmitted':False,'purchaseAuthorised':False,'retryAllowed':False,
  'approvalRequired':'A separate explicit approval for this exact restaurant video proposal before any paid generation'}
