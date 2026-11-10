"""Immutable, locally scoped creative rounds. No generation, charging or publishing.

Each owner feedback operation creates TWO competing new drafts. Restore creates
a new round rather than mutating or deleting older decisions.
"""
from __future__ import annotations
import json,re,time
import business_marketing_drafts as drafts

SECTORS={'restaurant','beauty','construction','concierge','roofing','other'}
SLOTS={'editorial','educational','social'}
ANGLES={
 'editorial':(
  'Cinematic natural-light commercial photograph, tangible service moment, carefully composed foreground and depth',
  'Authentic-looking documentary environmental photograph, human-scale activity and natural imperfections'),
 'educational':(
  'Photorealistic close-up of a relevant service detail, clear negative space for a separately typeset explanation',
  'Grounded wide-context photograph revealing the practical customer question, suitable for a precise carousel'),
 'social':(
  'Vertical cinematic action video shot list, meaningful human or product movement visible from the first second',
  'Vertical handheld documentary video shot list, real-world context, natural motion and a specific hook')
}
GUARD='Photorealistic only. No cartoons, vector illustration, abstract props, fake brands, results, customer jobs, testimonials, dishes or medical claims. Synthetic locations/people are illustrative, never documented business reality. Place verified copy and logos separately.'
class HeroHistoryError(ValueError):
 def __init__(self,message,code='hero_history_invalid',status=400):
  super().__init__(message);self.code=code;self.status=status

def _str(x,limit,field):
 if not isinstance(x,str) or not 1<=len(x.strip())<=limit or any(ord(c)<32 for c in x if c not in '\n\t'):
  raise HeroHistoryError('Invalid '+field)
 return ' '.join(x.split())
def _uuid(x):
 if not isinstance(x,str) or not re.fullmatch('[0-9a-f]{32}',x):
  raise HeroHistoryError('Invalid operation identifier')
 return x

def initialise(con):
 con.execute('''CREATE TABLE IF NOT EXISTS business_hero_sets(
  draft_id TEXT PRIMARY KEY,campaign_revision INTEGER NOT NULL,sector TEXT NOT NULL,
  offer TEXT NOT NULL,audience TEXT NOT NULL,created REAL NOT NULL)''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_hero_rounds(
  draft_id TEXT NOT NULL,slot TEXT NOT NULL,round_no INTEGER NOT NULL,
  action TEXT NOT NULL,parent_round INTEGER,feedback TEXT,
  direction_a TEXT NOT NULL,direction_b TEXT NOT NULL,created REAL NOT NULL,
  PRIMARY KEY(draft_id,slot,round_no))''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_hero_decisions(
  draft_id TEXT NOT NULL,slot TEXT NOT NULL,round_no INTEGER NOT NULL,
  variant TEXT NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL,
  PRIMARY KEY(draft_id,slot,round_no,variant))''')
 con.execute('''CREATE TABLE IF NOT EXISTS business_hero_operations(
  draft_id TEXT NOT NULL,operation_id TEXT NOT NULL,intent TEXT NOT NULL,
  result_json TEXT NOT NULL,PRIMARY KEY(draft_id,operation_id))''')

def _brief(sector,slot,choice,brand,offer,audience,feedback=None):
 prefix=ANGLES[slot][choice]
 details={'restaurant':'Only depict dishes the business actually confirms; otherwise use an explicitly conceptual hospitality atmosphere',
  'beauty':'Avoid simulated treatment results, patient photographs, or clinical efficacy claims',
  'construction':'Never imply a synthetic house or installation is a completed customer job',
  'concierge':'Never imply a fictional property, aircraft or event is operated or owned by this brand',
  'roofing':'Keep any workers safe and never depict a fictional repair as a completed customer job',
  'other':'Use a recognisable, plausibly accurate service context'}[sector]
 text=f'{prefix}. Business: {brand}. Owner-described offer (not independently verified): {offer}. Audience hypothesis: {audience}. {details}. {GUARD}'
 if feedback:
  text+=' Owner requested this improvement (review its factual claims): '+feedback
 return text[:4600]

def _history(con,draft):
 return [dict(r) for r in con.execute('SELECT slot,round_no,action,parent_round,feedback,direction_a,direction_b,created FROM business_hero_rounds WHERE draft_id=? ORDER BY slot,round_no',(draft,))]

def read(con,draft):
 drafts._id(draft)
 record=con.execute('SELECT * FROM business_hero_sets WHERE draft_id=?',(draft,)).fetchone()
 if not record:
  drafts.read_draft(con,draft)
  return {'exists':False,'draftId':draft,'rounds':[],'spendAuthorised':False,'published':False}
 return {'exists':True,'draftId':draft,'sector':record['sector'],'offer':record['offer'],'audience':record['audience'],
  'campaignRevisionAtCreation':record['campaign_revision'],'rounds':_history(con,draft),
  'rejectedDirections':[dict(r) for r in con.execute('SELECT slot,round_no,variant,reason,created FROM business_hero_decisions WHERE draft_id=? ORDER BY created',(draft,))],
  'spendAuthorised':False,'published':False,'requiresOwnerMediaReview':True,'creativeStatus':'brief_only_not_generated'}

def _latest(con,draft,slot):
 n=con.execute('SELECT MAX(round_no) FROM business_hero_rounds WHERE draft_id=? AND slot=?',(draft,slot)).fetchone()[0]
 return n if n is not None else -1

def mutate(con,body):
 if not isinstance(body,dict):raise HeroHistoryError('Invalid creative operation')
 action=body.get('action')
 if action not in ('start','revise','restore','reject'):raise HeroHistoryError('Unknown creative operation')
 draft=drafts._id(body.get('draftId'));operation=_uuid(body.get('operationId'))
 # Intent fingerprint handles lost responses without duplicate rounds.
 payload=json.dumps(body,sort_keys=True,ensure_ascii=False)
 if len(payload.encode())>7000:raise HeroHistoryError('Creative request too large')
 con.execute('BEGIN IMMEDIATE')
 try:
  receipt=con.execute('SELECT * FROM business_hero_operations WHERE draft_id=? AND operation_id=?',(draft,operation)).fetchone()
  if receipt:
   if receipt['intent']!=payload:raise HeroHistoryError('Operation ID already used for other feedback','operation_conflict',409)
   result=json.loads(receipt['result_json'])
   if result!=read(con,draft):raise HeroHistoryError('Newer creative feedback exists; refresh before continuing','replay_superseded',409)
   con.commit();return result
  campaign=drafts.read_draft(con,draft)
  if action=='start':
   sector=body.get('sector')
   if sector not in SECTORS:raise HeroHistoryError('Choose a supported business category')
   if body.get('ownerConfirmed') is not True:raise HeroHistoryError('Owner confirmation required','owner_confirmation_required',403)
   revision=body.get('expectedRevision')
   if type(revision) is not int or revision!=campaign['revision']:raise HeroHistoryError('Campaign has changed; reload before starting','revision_conflict',409)
   offer=_str(body.get('offer'),160,'offer');audience=_str(body.get('audience'),160,'audience')
   if con.execute('SELECT 1 FROM business_hero_sets WHERE draft_id=?',(draft,)).fetchone():
    raise HeroHistoryError('Creative set already exists; reload its saved history','already_started',409)
   con.execute('INSERT INTO business_hero_sets VALUES(?,?,?,?,?,?)',(draft,revision,sector,offer,audience,time.time()))
   for slot in ('editorial','educational','social'):
    a,b=(_brief(sector,slot,i,campaign['document']['business'],offer,audience) for i in (0,1))
    con.execute('INSERT INTO business_hero_rounds VALUES(?,?,?,?,?,?,?,?,?)',(draft,slot,0,'start',None,None,a,b,time.time()))
  else:
   row=con.execute('SELECT * FROM business_hero_sets WHERE draft_id=?',(draft,)).fetchone()
   if not row:raise HeroHistoryError('Start and save the creative set first','not_started',409)
   slot=body.get('slot')
   if slot not in SLOTS:raise HeroHistoryError('Invalid creative slot')
   current=_latest(con,draft,slot)
   if type(body.get('expectedRound')) is not int or body['expectedRound']!=current:
    raise HeroHistoryError('Newer feedback exists; reload before editing','round_conflict',409)
   if current>=30 and action!='reject':raise HeroHistoryError('Maximum 30 creative revisions reached','round_limit',409)
   previous=con.execute('SELECT * FROM business_hero_rounds WHERE draft_id=? AND slot=? AND round_no=?',(draft,slot,current)).fetchone()
   if action=='reject':
    rejected_round=body.get('reviewRound')
    variant=body.get('variant')
    if type(rejected_round) is not int or not 0<=rejected_round<=current or variant not in ('a','b'):
     raise HeroHistoryError('Choose a valid direction to reject')
    reason=_str(body.get('reason'),500,'rejection reason')
    if len(reason)<12:raise HeroHistoryError('Explain why the direction is unsuitable')
    if not con.execute('SELECT 1 FROM business_hero_rounds WHERE draft_id=? AND slot=? AND round_no=?',(draft,slot,rejected_round)).fetchone():
     raise HeroHistoryError('Version not found','not_found',404)
    if con.execute('SELECT 1 FROM business_hero_decisions WHERE draft_id=? AND slot=? AND round_no=? AND variant=?',(draft,slot,rejected_round,variant)).fetchone():
     raise HeroHistoryError('Direction already rejected','already_rejected',409)
    con.execute('INSERT INTO business_hero_decisions VALUES(?,?,?,?,?,?)',(draft,slot,rejected_round,variant,reason,time.time()))
   elif action=='revise':
    feedback=_str(body.get('feedback'),800,'feedback')
    if len(feedback)<12:raise HeroHistoryError('Describe the change in at least 12 characters')
    base_a=previous['direction_a'];base_b=previous['direction_b']
    # No external calls: two editorial interpretations of the owner feedback.
    a=(base_a+'\nRevision direction: prioritise '+feedback+'. Keep the existing source/claims safeguards.')[:5800]
    b=(base_b+'\nAlternative direction: reinterpret '+feedback+' with a different camera composition and natural lighting. Keep the existing source/claims safeguards.')[:5800]
    parent=current
   elif action=='restore':
    restored=body.get('restoreRound')
    if type(restored) is not int or not 0<=restored<=current:raise HeroHistoryError('Invalid historical round')
    old=con.execute('SELECT * FROM business_hero_rounds WHERE draft_id=? AND slot=? AND round_no=?',(draft,slot,restored)).fetchone()
    if old is None:raise HeroHistoryError('Historical version not found','not_found',404)
    a,b=old['direction_a'],old['direction_b'];feedback=None;parent=restored
   if action in ('revise','restore'):
    con.execute('INSERT INTO business_hero_rounds VALUES(?,?,?,?,?,?,?,?,?)',(draft,slot,current+1,action,parent,feedback,a,b,time.time()))
  result=read(con,draft)
  con.execute('INSERT INTO business_hero_operations VALUES(?,?,?,?)',(draft,operation,payload,json.dumps(result)))
  con.commit()
  return result
 except BaseException:
  con.rollback();raise
