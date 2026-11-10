"""Execute the customer model then persist through the real SQLite repository."""
import copy,json,sqlite3,subprocess,tempfile,unittest
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

class OwnerStrategyTests(unittest.TestCase):
 def test_full_brief_calendar_survives_save_reopen_and_download_models(self):
  script="""
import {strategyFields,reviewBusinessFact,editOwnerStrategy,confirmOwnerStrategy,completeStrategyCalendar} from './src/lib/businessOwnerStrategy.mjs';
let d=JSON.parse(process.argv[1]);d.posts=[];d.calendarStartDate='2026-11-01';
for(const [key,limit] of Object.entries(strategyFields))d=editOwnerStrategy(d,key,key.padEnd(limit-8,'x')+' — END '+key[0]);
for(let i=0;i<d.observedFacts.length;i++)d=reviewBusinessFact(d,i,'confirmed');
console.log(JSON.stringify(completeStrategyCalendar(confirmOwnerStrategy(d))));
"""
  doc=json.loads(subprocess.check_output(['node','--input-type=module','-e',script,json.dumps(document())],text=True))
  with tempfile.TemporaryDirectory() as folder:
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row;drafts.initialise(con)
    payload={'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':doc}
    drafts.save_draft(con,payload)
    self.assertTrue(drafts.save_draft(con,payload)['replayed'])
    con.commit()
    drafts.save_draft(con,{**payload,'id':'c'*32,'mutationId':'d'*32})
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row
    records=[drafts.read_draft(con,ident*32) for ident in ('a','c')]
    reopened=records[0]['document']
   self.assertEqual(reopened['posts'],doc['posts'])
   revised=copy.deepcopy(reopened)
   revised['posts'][0]['copyDraft']='Owner corrected bicycle servicing details'
   revised['posts'][0]['callToAction']='Ask about servicing'
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row
    change={'id':'a'*32,'mutationId':'e'*32,'expectedRevision':1,'document':revised}
    saved=drafts.save_draft(con,change)
    self.assertTrue(drafts.save_draft(con,change)['replayed'])
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row
    records.append(drafts.read_draft(con,'a'*32))
   self.assertEqual(records[2]['revision'],2)
   self.assertEqual(records[2]['updated'],saved['updated'])
   self.assertEqual(records[2]['document']['posts'][1:],reopened['posts'][1:])
   check=r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {strategyConfirmed} from './src/lib/businessOwnerStrategy.mjs';
import {editMarketingPost,marketingPlanCsv} from './src/lib/businessMarketingDocument.mjs';
import {createPublicationCalendar,publicationCalendarIcs} from './src/lib/businessPublicationCalendar.mjs';
const records=JSON.parse(fs.readFileSync(0,'utf8')),d=records[0].document;assert.ok(strategyConfirmed(d));
const exportRecord=record=>publicationCalendarIcs(createPublicationCalendar(record.document.posts,record.document.calendarStartDate),{business:record.document.business,sourceUrl:record.document.sourceUrl,campaignId:record.id,revision:record.revision,updated:record.updated}).replace(/\r\n /g,'');
const csv=marketingPlanCsv(d),ics=exportRecord(records[0]);
const ids=text=>text.split('\r\n').filter(line=>line.startsWith('UID:'));
assert.equal(new Set([...ids(ics),...ids(exportRecord(records[1]))]).size,60);
assert.equal(exportRecord(records[0]),ics);
const revised=exportRecord(records[2]);
assert.deepEqual(ids(revised),ids(ics));
assert.equal(ics.split('SEQUENCE:0').length-1,30);
assert.equal(revised.split('SEQUENCE:1').length-1,30);
assert.ok(revised.includes('Caption: Owner corrected bicycle servicing details\\nCTA: Ask about servicing'));
assert.ok(!revised.includes('DTSTAMP:20260101T000000Z'));
assert.equal(exportRecord(records[2]),revised);
for(const key of ['audience','offer','positioning','constraints']){
 assert.ok(csv.includes(d.ownerStrategy[key]));assert.ok(ics.includes(d.ownerStrategy[key]));
 for(const post of d.posts)assert.ok(post.copyDraft.includes(d.ownerStrategy[key]));
}
assert.ok(ics.includes(d.ownerStrategy.callToAction));assert.ok(ics.includes(d.sourceUrl));
assert.equal(editMarketingPost(d,1,{copyDraft:'a'.repeat(3000)}).posts[0].copyDraft.length,3000);
assert.throws(()=>editMarketingPost(d,1,{copyDraft:'a'.repeat(3001)}));
"""
   subprocess.run(['node','--input-type=module','-e',check],input=json.dumps(records),text=True,check=True)
   invalid=copy.deepcopy(reopened);invalid['posts'][0]['copyDraft']='x'*3001
   with self.assertRaises(drafts.MarketingDraftError):drafts.normalise_document(invalid)
   invalid=copy.deepcopy(reopened);invalid['creatives'][0]['copyDraft']='x'*2001
   with self.assertRaises(drafts.MarketingDraftError):drafts.normalise_document(invalid)

 def test_fact_decisions_are_bounded_and_legacy_confirmation_needs_review(self):
  doc=document()
  strategy={key:'Owner '+key for key in ('audience','offer','positioning','callToAction','constraints')}
  strategy['confirmedContext']={**{key:doc[key] for key in ('business','goal','sourceUrl','observedFacts')},**strategy}
  doc['ownerStrategy']=strategy
  # A legacy or constructed confirmation cannot skip the new observation review.
  self.assertIsNone(drafts.normalise_document(doc)['ownerStrategy']['confirmedContext'])
  entry={'index':0,'observation':doc['observedFacts'][0],'decision':'corrected','statement':'Weekday dining by reservation'}
  for decision in ('confirmed','corrected','excluded'):
   d=copy.deepcopy(doc);review={**entry,'decision':decision,'statement':entry['statement'] if decision=='corrected' else ''}
   d['ownerStrategy']['factDecisions']=[review]
   d['ownerStrategy']['confirmedContext']['factDecisions']=[review]
   self.assertIsNotNone(drafts.normalise_document(d)['ownerStrategy']['confirmedContext'])
  for reviews in ([entry,entry],[{**entry,'index':True}],[{**entry,'index':40}],
      [{**entry,'decision':'approved'}],[{**entry,'statement':'x'*601}],
      [{**entry,'decision':'excluded'}],{}):
   d=copy.deepcopy(doc);d['ownerStrategy']['factDecisions']=reviews
   with self.subTest(reviews=reviews),self.assertRaises(drafts.MarketingDraftError):drafts.normalise_document(d)
  for review in ({**entry,'statement':' '},{**entry,'observation':'Different source observation'}):
   d=copy.deepcopy(doc);d['ownerStrategy']['factDecisions']=[review]
   d['ownerStrategy']['confirmedContext']['factDecisions']=[review]
   clean=drafts.normalise_document(d)
   self.assertIsNone(clean['ownerStrategy']['confirmedContext'])
   self.assertEqual(clean['ownerStrategy']['factDecisions'],[review])

 def test_js_to_sqlite_reload_edit_and_stale_context(self):
  doc=document();doc['posts']=doc['posts'][:1];doc['posts'][0]['copyDraft']='Preserve owner edit'
  script="""
import {reviewBusinessFact,editOwnerStrategy,confirmOwnerStrategy,completeStrategyCalendar} from './src/lib/businessOwnerStrategy.mjs';
let d=JSON.parse(process.argv[1]);
for(const k of ['audience','offer','positioning','callToAction','constraints'])d=editOwnerStrategy(d,k,'Owner supplied '+k);
for(let i=0;i<(d.observedFacts||[]).length;i++)d=reviewBusinessFact(d,i,'confirmed');
d.calendarStartDate='2026-11-01';console.log(JSON.stringify(completeStrategyCalendar(confirmOwnerStrategy(d))));
"""
  composed=json.loads(subprocess.check_output(['node','--input-type=module','-e',script,json.dumps(doc)],text=True))
  with tempfile.TemporaryDirectory() as folder:
   con=sqlite3.connect(folder+'/drafts.db');con.row_factory=sqlite3.Row;drafts.initialise(con)
   payload={'id':'1'*32,'mutationId':'2'*32,'expectedRevision':0,'document':composed}
   saved=drafts.save_draft(con,payload);self.assertEqual(saved['revision'],1)
   self.assertTrue(drafts.save_draft(con,payload)['replayed']);con.close()
   con=sqlite3.connect(folder+'/drafts.db');con.row_factory=sqlite3.Row
   restored=drafts.read_draft(con,'1'*32)['document']
   self.assertEqual(len(restored['posts']),30);self.assertEqual(restored['posts'][0]['copyDraft'],'Preserve owner edit')
   self.assertIsNotNone(restored['ownerStrategy']['confirmedContext'])
   check="import {strategyConfirmed} from './src/lib/businessOwnerStrategy.mjs';console.log(strategyConfirmed(JSON.parse(process.argv[1])));"
   self.assertEqual(subprocess.check_output(['node','--input-type=module','-e',check,json.dumps(restored,sort_keys=True)],text=True).strip(),'true')
   for key,value in [('business','Changed business'),('goal','bookings'),('sourceUrl','https://other.org/'),('observedFacts',['New evidence'])]:
    changed=copy.deepcopy(restored);changed[key]=value
    self.assertIsNone(drafts.normalise_document(changed)['ownerStrategy']['confirmedContext'])
   refresh="""
import {refreshStrategyCalendar} from './src/lib/businessOwnerStrategy.mjs';
let d=JSON.parse(process.argv[1]);console.log(JSON.stringify(refreshStrategyCalendar(d,[2,30])));
"""
   restored=json.loads(subprocess.check_output(['node','--input-type=module','-e',refresh,json.dumps(restored)],text=True))
   refreshed=drafts.save_draft(con,{**payload,'mutationId':'5'*32,'expectedRevision':1,'document':restored})
   self.assertEqual(refreshed['revision'],2)
   con.close();con=sqlite3.connect(folder+'/drafts.db');con.row_factory=sqlite3.Row
   restored=drafts.read_draft(con,'1'*32)['document']
   self.assertEqual(restored['posts'][0]['copyDraft'],'Preserve owner edit')
   self.assertIn('Owner supplied offer',restored['posts'][1]['copyDraft'])
   self.assertEqual(len({p['theme'] for p in restored['posts']}),30)
   self.assertEqual(restored['posts'][29]['status'],'draft')
   restored['posts'][1]['copyDraft']='Owner changed day two'
   changed=drafts.save_draft(con,{**payload,'mutationId':'3'*32,'expectedRevision':2,'document':restored})
   self.assertIsNotNone(changed['document']['ownerStrategy']['confirmedContext'])
   self.assertFalse(changed['document']['canSpend']);self.assertFalse(changed['document']['canPublish'])
   with self.assertRaises(drafts.MarketingDraftError):drafts.save_draft(con,{**payload,'mutationId':'4'*32})
   con.rollback();con.close()

 def test_source_links_survive_sqlite_and_changed_excerpt_invalidates_confirmation(self):
  doc=document()
  doc['editorialShortlist']={'status':'blocked_insufficient_unique_brand_evidence','sector':'other','candidates':[
   {'id':'service','role':'Service','media':'Image','format':'4:5','direction':'Explain the service','hook':'Annual accounts',
    'evidence':{'kind':'service','label':'Website','quote':'We prepare annual accounts.'}}]}
  script="""
import {reviewBusinessFact,editOwnerStrategy,linkStrategyEvidence,confirmOwnerStrategy,strategyConfirmed,strategyEvidenceState} from './src/lib/businessOwnerStrategy.mjs';
let d=JSON.parse(process.argv[1]);
for(const k of ['audience','offer','positioning','callToAction','constraints'])d=editOwnerStrategy(d,k,'Owner supplied '+k);
for(let i=0;i<(d.observedFacts||[]).length;i++)d=reviewBusinessFact(d,i,'confirmed');
console.log(JSON.stringify(confirmOwnerStrategy(linkStrategyEvidence(d,'offer','service'))));
"""
  doc=json.loads(subprocess.check_output(['node','--input-type=module','-e',script,json.dumps(doc)],text=True))
  with tempfile.TemporaryDirectory() as folder:
   con=sqlite3.connect(folder+'/drafts.db');con.row_factory=sqlite3.Row;drafts.initialise(con)
   drafts.save_draft(con,{'id':'a'*32,'mutationId':'b'*32,'expectedRevision':0,'document':doc});con.close()
   con=sqlite3.connect(folder+'/drafts.db');con.row_factory=sqlite3.Row
   restored=drafts.read_draft(con,'a'*32)['document'];con.close()
   self.assertIsNotNone(restored['ownerStrategy']['confirmedContext'])
   self.assertEqual(restored['ownerStrategy']['evidenceLinks']['offer']['quote'],'We prepare annual accounts.')
   check="import {strategyConfirmed,strategyEvidenceState} from './src/lib/businessOwnerStrategy.mjs';let d=JSON.parse(process.argv[1]);console.log(JSON.stringify([strategyConfirmed(d),strategyEvidenceState(d,'offer').status]));"
   self.assertEqual(json.loads(subprocess.check_output(['node','--input-type=module','-e',check,json.dumps(restored)],text=True)),[True,'unverified'])
   restored['editorialShortlist']['candidates'][0]['evidence']['quote']='Changed service statement'
   self.assertIsNone(drafts.normalise_document(restored)['ownerStrategy']['confirmedContext'])
   # A submitted context matching the new research must not bless the old link.
   restored['ownerStrategy']['confirmedContext']['researchEvidence'][0]['quote']='Changed service statement'
   clean=drafts.normalise_document(restored)
   self.assertIsNone(clean['ownerStrategy']['confirmedContext'])
   self.assertEqual(clean['ownerStrategy']['evidenceLinks']['offer']['quote'],'We prepare annual accounts.')
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row
    saved=drafts.save_draft(con,{'id':'a'*32,'mutationId':'c'*32,'expectedRevision':1,'document':restored})
    self.assertIsNone(saved['document']['ownerStrategy']['confirmedContext'])
   # Reopen an actually persisted stale reference, then repair through the owner model.
   with sqlite3.connect(folder+'/drafts.db') as con:
    con.row_factory=sqlite3.Row
    stale=drafts.read_draft(con,'a'*32)['document']
   for index,source in enumerate(('', 'service')):
    repair="""
import {linkStrategyEvidence,confirmOwnerStrategy} from './src/lib/businessOwnerStrategy.mjs';
console.log(JSON.stringify(confirmOwnerStrategy(linkStrategyEvidence(JSON.parse(process.argv[1]),'offer',process.argv[2]))));
"""
    repaired=json.loads(subprocess.check_output(['node','--input-type=module','-e',repair,json.dumps(stale),source],text=True))
    with sqlite3.connect(folder+'/drafts.db') as con:
     con.row_factory=sqlite3.Row
     drafts.save_draft(con,{'id':'a'*32,'mutationId':str(index+4)*32,'expectedRevision':index+2,'document':repaired})
    with sqlite3.connect(folder+'/drafts.db') as con:
     con.row_factory=sqlite3.Row
     reopened=drafts.read_draft(con,'a'*32)['document']
    self.assertEqual(reopened['posts'],stale['posts'])
    self.assertEqual(reopened['creatives'],stale['creatives'])
    self.assertEqual(reopened['observedFacts'],stale['observedFacts'])
    self.assertEqual(json.loads(subprocess.check_output(['node','--input-type=module','-e',check,json.dumps(reopened)],text=True)),[True,'unverified' if source else 'absent'])
