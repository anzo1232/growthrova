import test from 'node:test';
import assert from 'node:assert/strict';
import * as ownerStrategy from '../src/lib/businessOwnerStrategy.mjs';
import {businessFactReview,businessFactsReviewed,reviewBusinessFact,strategyFields,editOwnerStrategy,confirmOwnerStrategy,strategyConfirmed,completeStrategyCalendar} from '../src/lib/businessOwnerStrategy.mjs';
test('confirmed brief becomes usable post words without editorial instructions or unrelated changes',()=>{
 let doc={business:'Harbour Cycles',goal:'enquiries',observedFacts:['Unsupported same-day promise'],
  posts:[{day:1,copyDraft:'My draft',callToAction:'Old CTA',theme:'Service introduction',channel:'Website',format:'Owner format',status:'draft'},
   {day:2,copyDraft:'Keep my reviewed post',status:'copy_reviewed'}],creatives:[{id:'creative-1',copyDraft:'Keep my creative'}]};
 const brief={audience:'Local bicycle owners',offer:'Bicycle servicing by appointment.',
  positioning:'Discuss your bicycle and the work you need with our workshop.',callToAction:'Contact the workshop.',
  constraints:'Do not promise same-day completion. INTERNAL NOTE: confirm availability.'};
 for(const [key,value] of Object.entries(brief))doc=editOwnerStrategy(doc,key,value);
 doc=reviewBusinessFact(doc,0,'excluded');
 assert.throws(()=>ownerStrategy.useConfirmedBriefForPost(doc,1),/Confirm/);
 doc=confirmOwnerStrategy(doc);
 const original=structuredClone(doc);
 const next=ownerStrategy.useConfirmedBriefForPost(doc,1);
 assert.equal(next.posts[0].copyDraft,'Harbour Cycles\n\n'+brief.offer+'\n\n'+brief.positioning);
 assert.equal(next.posts[0].callToAction,brief.callToAction);
 assert.doesNotMatch(next.posts[0].copyDraft,/Draft direction|INTERNAL NOTE|Unsupported same-day|Local bicycle owners/);
 for(const key of ['theme','channel','format'])assert.equal(next.posts[0][key],doc.posts[0][key]);
 assert.equal(next.posts[1],doc.posts[1]);assert.equal(next.creatives,doc.creatives);
 assert.equal(next.ownerStrategy,doc.ownerStrategy);assert.deepEqual(doc,original);
 assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
 assert.equal(ownerStrategy.useConfirmedBriefForPost(next,1),next);
 assert.throws(()=>ownerStrategy.useConfirmedBriefForPost(doc,2),/Reviewed/);
 assert.throws(()=>ownerStrategy.useConfirmedBriefForPost(doc,31),/not found/);
 assert.throws(()=>ownerStrategy.useConfirmedBriefForPost(editOwnerStrategy(doc,'offer','Changed'),1),/Confirm/);
});
for(const business of ['Restaurant','Beauty clinic','Accountancy practice'])test(`${business}: confirmed brief fills 30 days and preserves edits`,()=>{
 let doc={business,goal:'enquiries',sourceUrl:'https://example.org/',observedFacts:['Published service description'],calendarStartDate:'2026-11-01',posts:[{day:8,copyDraft:'My carefully edited copy',status:'copy_reviewed'}]};
 assert.throws(()=>completeStrategyCalendar(doc),/Confirm/);
 for(const k of Object.keys(strategyFields))doc=editOwnerStrategy(doc,k,`${business} ${k}`);
 for(let i=0;i<(doc.observedFacts||[]).length;i++)doc=reviewBusinessFact(doc,i,'confirmed');
 doc=confirmOwnerStrategy(doc);
 assert.equal(strategyConfirmed(doc),true);
 assert.equal(strategyConfirmed({...doc,ownerStrategy:{...doc.ownerStrategy,confirmedContext:Object.fromEntries(Object.entries(doc.ownerStrategy.confirmedContext).reverse())}}),true);
 const filled=completeStrategyCalendar(doc);
 assert.equal(filled.posts.length,30);
 assert.equal(filled.posts[7],doc.posts[0]);
 assert.match(filled.posts[0].copyDraft,new RegExp(business));
 assert.equal(filled.canSpend,false);assert.equal(filled.canPublish,false);
 assert.deepEqual(completeStrategyCalendar(filled),filled);
 for(const patch of [{business:'Other'},{goal:'bookings'},{sourceUrl:'https://other.org/'},{observedFacts:['Changed evidence']}])assert.equal(strategyConfirmed({...doc,...patch}),false);
 assert.equal(strategyConfirmed(editOwnerStrategy(doc,'offer','Revised service')),false);
 assert.throws(()=>completeStrategyCalendar({...doc,calendarStartDate:''}),/start date/);
 assert.throws(()=>completeStrategyCalendar({...doc,calendarStartDate:'2026-02-31'}),/start date/);
});

test('append a reviewed detail explicitly without replacing owner work or duplicating it',()=>{
 const {reviewedBusinessDetails,appendReviewedBusinessDetail}=ownerStrategy;
 let doc={business:'Workshop',observedFacts:['Servicing','Sunday opening','Unsupported guarantee','Pending detail'],
  posts:[{day:1,copyDraft:'My opening hook',callToAction:'Contact us',channel:'Instagram',format:'Image post',status:'copy_reviewed'},
         {day:2,copyDraft:'Keep this day',status:'copy_reviewed'}],creatives:[{id:'creative-1',copyDraft:'Keep creative'}]};
 doc=reviewBusinessFact(doc,0,'confirmed');
 doc=reviewBusinessFact(doc,1,'corrected','Appointments on weekdays');
 doc=reviewBusinessFact(doc,2,'excluded');
 const original=structuredClone(doc);
 assert.deepEqual(reviewedBusinessDetails(doc),[
  {index:0,statement:'Servicing',decision:'confirmed'},
  {index:1,statement:'Appointments on weekdays',decision:'corrected'}]);
 const next=appendReviewedBusinessDetail(doc,1,1);
 assert.equal(next.posts[0].copyDraft,'My opening hook\n\nAppointments on weekdays');
 assert.equal(next.posts[0].status,'draft');
 for(const key of ['channel','format','callToAction'])assert.equal(next.posts[0][key],doc.posts[0][key]);
 assert.equal(next.posts[1],doc.posts[1]);assert.equal(next.creatives,doc.creatives);
 assert.equal(next.ownerStrategy,doc.ownerStrategy);assert.equal(next.observedFacts,doc.observedFacts);
 assert.deepEqual(doc,original);
 assert.equal(appendReviewedBusinessDetail(next,1,1),next);
 assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
 for(const index of [2,3,10,'1',-1])assert.throws(()=>appendReviewedBusinessDetail(doc,1,index),/reviewed detail/i);
 assert.throws(()=>appendReviewedBusinessDetail(doc,30,1),/Post not found/);
 const changed={...doc,observedFacts:['Servicing','Different hours',...doc.observedFacts.slice(2)]};
 assert.throws(()=>appendReviewedBusinessDetail(changed,1,1),/reviewed detail/i);
 const blank=reviewBusinessFact(doc,1,'corrected',' ');
 assert.throws(()=>appendReviewedBusinessDetail(blank,1,1),/reviewed detail/i);
 const full={...doc,posts:[{...doc.posts[0],copyDraft:'x'.repeat(2990)}]};
 assert.throws(()=>appendReviewedBusinessDetail(full,1,1),/room/i);
 assert.equal(full.posts[0].copyDraft.length,2990);
 const included={...doc,posts:[{...doc.posts[0],copyDraft:'An opening\nAppointments on weekdays\nA closing'}]};
 assert.equal(appendReviewedBusinessDetail(included,1,1),included);
});
test('reviewed details enrich only the chosen creative and require new copy review',()=>{
 const {appendReviewedCreativeDetail}=ownerStrategy;
 let doc={observedFacts:['Bicycle servicing','Weekend hours','Unconfirmed claim','Pending'],
  posts:[{day:1,copyDraft:'Keep post'}],creatives:[
   {id:'creative-1',copyDraft:'An owner-written hook',brief:'Use my genuine workshop photo',ratio:'4:5',callToAction:'Contact the workshop',status:'copy_reviewed',approved:false},
   {id:'creative-2',copyDraft:'Keep other concept',status:'copy_reviewed'}]};
 doc=reviewBusinessFact(doc,0,'confirmed');
 doc=reviewBusinessFact(doc,1,'corrected','Weekday appointments\nContact us for availability');
 doc=reviewBusinessFact(doc,2,'excluded');
 const original=structuredClone(doc);
 const next=appendReviewedCreativeDetail(doc,'creative-1',1);
 assert.equal(next.creatives[0].copyDraft,'An owner-written hook\n\nWeekday appointments\nContact us for availability');
 assert.equal(next.creatives[0].status,'draft');assert.equal(next.creatives[0].approved,false);
 for(const key of ['brief','ratio','callToAction'])assert.equal(next.creatives[0][key],doc.creatives[0][key]);
 assert.equal(next.creatives[1],doc.creatives[1]);assert.equal(next.posts,doc.posts);
 assert.equal(next.ownerStrategy,doc.ownerStrategy);assert.deepEqual(doc,original);
 assert.equal(appendReviewedCreativeDetail(next,'creative-1',1),next);
 assert.equal(appendReviewedCreativeDetail({...next,creatives:[{...next.creatives[0],status:'copy_reviewed'}]},'creative-1',1).creatives[0].status,'copy_reviewed');
 assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
 assert.ok(appendReviewedCreativeDetail(doc,'creative-1',0).creatives[0].copyDraft.endsWith('\n\nBicycle servicing'));
 for(const index of [2,3,40,'1',-1])assert.throws(()=>appendReviewedCreativeDetail(doc,'creative-1',index),/reviewed detail/i);
 assert.throws(()=>appendReviewedCreativeDetail(doc,'missing',1),/Creative not found/);
 assert.throws(()=>appendReviewedCreativeDetail({...doc,observedFacts:['Bicycle servicing','Changed hours']},'creative-1',1),/reviewed detail/i);
 const full={...doc,creatives:[{...doc.creatives[0],copyDraft:'x'.repeat(1990)}]};
 assert.throws(()=>appendReviewedCreativeDetail(full,'creative-1',1),/room.*creative/i);
 assert.equal(full.creatives[0].copyDraft.length,1990);
 // A partial prose match must not hide a requested standalone detail.
 const prose={...doc,creatives:[{...doc.creatives[0],copyDraft:'Ask about Bicycle servicing today.'}]};
 assert.equal(appendReviewedCreativeDetail(prose,'creative-1',0).creatives[0].copyDraft,'Ask about Bicycle servicing today.\n\nBicycle servicing');
});
test('incomplete and oversized briefs cannot be confirmed',()=>{
 assert.throws(()=>confirmOwnerStrategy({business:'Example'}),/Complete/);
 assert.throws(()=>editOwnerStrategy({},'offer','x'.repeat(501)),/Invalid/);
});
test('refresh applies the current strategy to selected drafts and preserves reviewed work',async()=>{
 const {refreshStrategyCalendar}=await import('../src/lib/businessOwnerStrategy.mjs');
 let doc={business:'Local studio',goal:'enquiries',calendarStartDate:'2026-11-01',posts:[]};
 for(const key of Object.keys(strategyFields))doc=editOwnerStrategy(doc,key,'Confirmed '+key);
 doc=completeStrategyCalendar(confirmOwnerStrategy(doc));
 assert.equal(new Set(doc.posts.map(p=>p.theme)).size,30);
 doc.posts[0]={...doc.posts[0],status:'copy_reviewed',copyDraft:'Reviewed owner copy'};
 doc.posts[1]={...doc.posts[1],channel:'LinkedIn',format:'Owner format',copyDraft:'Unreviewed edit'};
 const original=structuredClone(doc);
 doc=confirmOwnerStrategy(editOwnerStrategy(doc,'offer','New owner offer'));
 const refreshed=refreshStrategyCalendar(doc,[2,30]);
 assert.equal(refreshed.posts[0],doc.posts[0]);assert.equal(refreshed.posts[2],doc.posts[2]);
 assert.match(refreshed.posts[1].copyDraft,/New owner offer/);
 assert.equal(refreshed.posts[1].channel,'LinkedIn');assert.equal(refreshed.posts[1].format,'Owner format');
 assert.equal(refreshed.posts[1].status,'draft');assert.equal(refreshed.posts[1].published,false);
 assert.equal(doc.posts[1].copyDraft,original.posts[1].copyDraft);
 assert.throws(()=>refreshStrategyCalendar(doc,[1]),/Reviewed/);
 for(const days of [[],[2,2],[0],[31],['2'],[2.5]])assert.throws(()=>refreshStrategyCalendar(doc,days),/valid/);
 assert.throws(()=>refreshStrategyCalendar({...doc,posts:doc.posts.slice(0,2)},[30]),/not found/);
 assert.throws(()=>refreshStrategyCalendar(editOwnerStrategy(doc,'audience','Changed'),[2]),/Confirm/);
 assert.equal(refreshed.canPublish,false);assert.equal(refreshed.canSpend,false);
});
test('maximum length brief keeps every confirmed instruction in every daily direction',()=>{
 let doc={business:'Studio',goal:'enquiries',calendarStartDate:'2026-11-01',posts:[]};
 for(const [key,limit] of Object.entries(strategyFields))doc=editOwnerStrategy(doc,key,key.padEnd(limit-8,'x')+' — END '+key[0]);
 doc=completeStrategyCalendar(confirmOwnerStrategy(doc));
 for(const post of doc.posts){
  assert.ok(post.copyDraft.length<=3000);
  for(const key of ['constraints','audience','offer','positioning'])assert.ok(post.copyDraft.includes(doc.ownerStrategy[key]),key+' must survive in day '+post.day);
  assert.equal(post.callToAction,doc.ownerStrategy.callToAction);
  assert.ok(post.copyDraft.startsWith('Draft direction: '));
 }
 const copied=ownerStrategy.useConfirmedBriefForPost(doc,1).posts[0];
 assert.equal(copied.copyDraft,[doc.business,doc.ownerStrategy.offer,doc.ownerStrategy.positioning].join('\n\n'));
 assert.equal(copied.callToAction,doc.ownerStrategy.callToAction);
 assert.ok(copied.copyDraft.length<=3000);
 assert.ok(!copied.copyDraft.includes(doc.ownerStrategy.constraints));
});
test('strategy links only this campaign research and invalidates confirmation when evidence changes',async()=>{
 const {strategyEvidence,strategyEvidenceState,linkStrategyEvidence}=await import('../src/lib/businessOwnerStrategy.mjs');
 let d={business:'Accountancy practice',goal:'enquiries',sourceUrl:'https://example.org/',editorialShortlist:{candidates:[{id:'services',evidence:{quote:'We prepare annual accounts.',label:'Services page'}}]}};
 for(const key of Object.keys(strategyFields))d=editOwnerStrategy(d,key,'Owner supplied '+key);
 assert.equal(strategyEvidenceState(d,'offer').status,'absent');
 assert.throws(()=>linkStrategyEvidence(d,'offer','other-campaign'),/not in this campaign/);
 d=linkStrategyEvidence(d,'offer','services');
 assert.equal(strategyEvidenceState(d,'offer').status,'unverified');
 d=confirmOwnerStrategy(d);assert.equal(strategyConfirmed(d),true);
 const changed={...d,editorialShortlist:{candidates:[{id:'services',evidence:{quote:'Changed source'}}]}};
 assert.equal(strategyConfirmed(changed),false);assert.equal(strategyEvidenceState(changed,'offer').status,'stale');
 assert.equal(strategyEvidenceState({...d,sourceUrl:'https://other.org/'},'offer').status,'stale');
 assert.deepEqual(strategyEvidence({...d,sourceUrl:'javascript:alert(1)'}),[]);
 assert.equal(strategyConfirmed(linkStrategyEvidence(d,'offer','')),false);
 assert.equal(strategyEvidenceState({...d,editorialShortlist:null},'offer').status,'stale');
 // Reconfirming changed research cannot bless a reference to the old excerpt.
 for(const stale of [changed,{...d,sourceUrl:'https://other.org/'},{...d,editorialShortlist:null}]){
  assert.throws(()=>confirmOwnerStrategy(stale),/source link/i);
  assert.throws(()=>ownerStrategy.useConfirmedBriefForPost(stale,1),/Confirm/);
  const forged={...stale,ownerStrategy:{...stale.ownerStrategy,confirmedContext:(await import('../src/lib/businessOwnerStrategy.mjs')).strategyContext(stale)}};
  assert.equal(strategyConfirmed(forged),false);
  const removed=confirmOwnerStrategy(linkStrategyEvidence(stale,'offer',''));
  assert.equal(strategyConfirmed(removed),true);
  assert.deepEqual(removed.posts,stale.posts);
 }
 const repaired=confirmOwnerStrategy(linkStrategyEvidence(changed,'offer','services'));
 assert.equal(strategyConfirmed(repaired),true);
 assert.equal(repaired.ownerStrategy.evidenceLinks.offer.quote,'Changed source');
});

test('owners review exact observations without rewriting evidence or existing copy',()=>{
 let doc={business:'Workshop',goal:'enquiries',sourceUrl:'https://example.org/',
  observedFacts:['Bicycle servicing','Open on Sundays','Guaranteed results'],posts:[{day:1,copyDraft:'Owner draft',status:'draft'}],creatives:[]};
 for(const key of Object.keys(strategyFields))doc=editOwnerStrategy(doc,key,'Owner '+key);
 const original=structuredClone(doc);
 assert.equal(businessFactsReviewed(doc),false);
 assert.throws(()=>confirmOwnerStrategy(doc),/Review each/);
 doc=reviewBusinessFact(doc,0,'confirmed');
 doc=reviewBusinessFact(doc,1,'corrected');
 doc=reviewBusinessFact(doc,2,'excluded');
 assert.equal(businessFactsReviewed(doc),false);
 assert.throws(()=>confirmOwnerStrategy(doc),/Review each/);
 doc=reviewBusinessFact(doc,1,'corrected','By appointment on weekdays');
 doc=confirmOwnerStrategy(doc);
 assert.equal(strategyConfirmed(doc),true);
 assert.deepEqual(doc.observedFacts,original.observedFacts);
 assert.deepEqual(doc.posts,original.posts);
 assert.deepEqual(doc.creatives,original.creatives);
 assert.equal(businessFactReview(doc,1).statement,'By appointment on weekdays');
 const changed={...doc,observedFacts:['Changed service',...doc.observedFacts.slice(1)]};
 assert.equal(businessFactReview(changed,0),null);
 assert.equal(strategyConfirmed(changed),false);
 assert.throws(()=>confirmOwnerStrategy(changed),/Review each/);
 assert.equal(strategyConfirmed(reviewBusinessFact(doc,1,'corrected','Different hours')),false);
 assert.equal(businessFactsReviewed(reviewBusinessFact(doc,2,'pending')),false);
 for(const [index,decision,statement] of [[-1,'confirmed',''],[3,'confirmed',''],[0,'approved',''],[1,'corrected','x'.repeat(601)]])
  assert.throws(()=>reviewBusinessFact(doc,index,decision,statement),/Invalid/);
});

test('secondary-page source links retain their identity and hold when the source changes',()=>{
 let d={business:'Synthetic club',goal:'enquiries',sourceUrl:'https://example.org/',editorialShortlist:{candidates:[
  {id:'membership',evidence:{quote:'Membership enquiries start with a conversation.',sourceUrl:'https://example.org/membership',label:'paragraph 1'}}]}};
 for(const key of Object.keys(strategyFields))d=editOwnerStrategy(d,key,'Synthetic owner '+key);
 d=ownerStrategy.linkStrategyEvidence(d,'offer','membership');
 assert.equal(d.ownerStrategy.evidenceLinks.offer.sourceUrl,'https://example.org/membership');
 d=confirmOwnerStrategy(d);
 assert.equal(strategyConfirmed(d),true);
 const changed=structuredClone(d);
 changed.editorialShortlist.candidates[0].evidence.sourceUrl='https://example.org/other';
 assert.equal(strategyConfirmed(changed),false);
 assert.throws(()=>confirmOwnerStrategy(changed),/source link/i);
 assert.deepEqual(changed.ownerStrategy.confirmedContext,d.ownerStrategy.confirmedContext);
 for(const sourceUrl of ['https://foreign.example.org/membership','http://example.org/membership','https://user@example.org/membership']){
  assert.deepEqual(ownerStrategy.strategyEvidence({...d,editorialShortlist:{candidates:[{id:'bad',evidence:{quote:'Untrusted source reference',sourceUrl}}]}}),[]);
 }
});
