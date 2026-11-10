import test from 'node:test';
import * as writing from '../src/lib/growthrovaWriting.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {applyWriting,validateWriting,writingText,writingReelBrief,writingContext,writingMatchesDocument} from '../src/lib/growthrovaWriting.mjs';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument,editMarketingPost,reviewMarketingCopy} from '../src/lib/businessMarketingDocument.mjs';
const sample=JSON.parse(fs.readFileSync(new URL('./fixtures/growthrova-writing-synthetic.json',import.meta.url)));
const proposal={state:'proposed',independentReview:'pending',sample,issues:[],material:{business:'Synthetic workshop',
 goal:{value:'enquiries'},audience:{value:'Proposed test bicycle audience'},evidence:[]}};
const document=()=>createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Synthetic workshop',meta_description:'Bicycle servicing and brake adjustments.'}}));

proposal.sourceContext=writingContext(document());

test('scoped revision comparison retains exact original and changed words and checks the other items',()=>{
 const original={...structuredClone(proposal),operationId:'original'};
 for(const target of ['post-2','reel']){
  const revised={...structuredClone(original),operationId:'revised',repairOf:'original',
   revisionRequest:{target,instruction:'Make the customer next step clearer.'}};
  const before=target==='reel'?original.sample.reel:original.sample.posts[1];
  const after=target==='reel'?revised.sample.reel:revised.sample.posts[1];
  after.caption+=' Describe the work you need when contacting us.';
  if(target==='reel')after.shots[0].voiceover='Tell us what your bicycle needs.';
  const snapshot=structuredClone({original,revised});
  const comparison=writing.writingRevisionComparison(revised,[revised,original]);
  assert.deepEqual(comparison,{target,instruction:revised.revisionRequest.instruction,before,after,
   otherItemsUnchanged:true,contentChanged:true});
  assert.deepEqual({original,revised},snapshot);
  revised.sample.posts[0].caption+=' An unrelated change.';
  assert.equal(writing.writingRevisionComparison(revised,[original]).otherItemsUnchanged,false);
 }
 assert.equal(writing.writingRevisionComparison(original,[original]),null);
});

test('revision comparison cannot substitute unrelated history or imply internal angle edits changed customer words',()=>{
 const original={...structuredClone(proposal),operationId:'original'};
 const revised={...structuredClone(original),operationId:'revised',repairOf:'original',
  revisionRequest:{target:'post-2',instruction:'Make this caption more direct.'}};
 revised.sample.posts[1].angle='Only an internal angle changed';
 assert.equal(writing.writingRevisionComparison(revised,[original]).contentChanged,false);
 for(const history of [[],[{...original,operationId:'different'}],[{...original,sample:null}],[{...original,sourceContext:undefined}],
  [{...original,sourceContext:{...original.sourceContext,goal:'bookings'}}]]){
  const result=writing.writingRevisionComparison(revised,history);
  assert.match(result.error,/original.*unavailable/i);
  assert.equal(result.before,undefined);
 }
});

test('editorial revision download retains exact scope and direction as internal history',()=>{
 const revisionRequest={target:'post-2',instruction:'Develop brake adjustments for commuters; keep other posts intact.'};
 const text=writingText({...proposal,revisionRequest,repairOf:'parent-operation'});
 const [publicWords,internal]=text.split('INTERNAL EVIDENCE — not publishable wording');
 assert.ok(!publicWords.includes(revisionRequest.instruction));
 const history=JSON.parse(internal);
 assert.deepEqual(history.revisionRequest,revisionRequest);
 assert.equal(history.repairOf,'parent-operation');
 assert.equal(writingText(proposal).includes('revisionRequest'),false);
});

test('writing proposal changes only the chosen day; revisions and repeat application preserve other work',()=>{
 const doc=document(),before=structuredClone(doc);
 const next=applyWriting(doc,proposal,'post',3,1);
 assert.equal(next.posts[2].copyDraft,sample.posts[1].hook+'\n\n'+sample.posts[1].caption);
 assert.equal(next.posts[2].callToAction,sample.posts[1].callToAction);
 assert.equal(next.posts[2].status,'draft');assert.equal(applyWriting(next,proposal,'post',3,1),next);
 assert.deepEqual(next.creatives,doc.creatives);assert.deepEqual(next.posts.filter(p=>p.day!==3),doc.posts.filter(p=>p.day!==3));
 assert.deepEqual(doc,before);
 assert.ok(writingMatchesDocument(next,proposal));
 assert.throws(()=>applyWriting({...doc,goal:'bookings'},proposal,'post',1),/context/);
 const reviewed=reviewMarketingCopy(next,'post',3);
 const revised=editMarketingPost(reviewed,3,{callToAction:'Contact the workshop about servicing'});
 assert.equal(revised.posts[2].status,'draft');assert.equal(revised.posts[2].copyDraft,next.posts[2].copyDraft);
 assert.deepEqual(revised.posts.filter(p=>p.day!==3),next.posts.filter(p=>p.day!==3));
});
test('reel storyboard connects to existing video concept and retains all other creative and posts',()=>{
 const doc=document(),video=doc.creatives.find(p=>p.format==='video_ad');
 const next=applyWriting(doc,proposal,'reel',video.id);
 assert.deepEqual(next.posts,doc.posts);assert.deepEqual(next.creatives.filter(p=>p.id!==video.id),doc.creatives.filter(p=>p.id!==video.id));
 assert.equal(next.creatives.find(p=>p.id===video.id).brief,writingReelBrief(sample.reel));
 assert.match(writingReelBrief(sample.reel),/0–7s/);assert.match(writingReelBrief(sample.reel),/14–21s/);
 assert.equal(next.creatives.find(p=>p.id===video.id).approved,false);
 assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
 assert.throws(()=>applyWriting(doc,proposal,'reel','creative-1'),/portrait video/);
});
test('a voiceover-only reel revision invalidates checked words without changing the caption or other work',()=>{
 const doc=document(),video=doc.creatives.find(p=>p.format==='video_ad');
 const applied=applyWriting(doc,proposal,'reel',video.id);
 const reviewed=reviewMarketingCopy(applied,'creative',video.id);
 const revised=structuredClone(proposal);
 revised.sample.reel.shots[0].voiceover='Tell us about the bicycle servicing you need.';
 const before=structuredClone(reviewed);
 const next=applyWriting(reviewed,revised,'reel',video.id);
 const current=next.creatives.find(c=>c.id===video.id);
 assert.equal(current.status,'draft','Changed spoken words must not retain caption-only review');
 assert.equal(current.copyDraft,reviewed.creatives.find(c=>c.id===video.id).copyDraft);
 assert.equal(current.callToAction,sample.reel.callToAction);
 assert.match(current.brief,/Tell us about the bicycle servicing you need\./);
 assert.deepEqual(next.posts,reviewed.posts);
 assert.deepEqual(next.creatives.filter(c=>c.id!==video.id),reviewed.creatives.filter(c=>c.id!==video.id));
 assert.deepEqual(reviewed,before);
 assert.equal(current.approved,false);
 assert.equal(applyWriting(reviewed,proposal,'reel',video.id),reviewed,'Unchanged script preserves existing review');
});
test('held output and malformed provider shape cannot enter the draft; export separates evidence',()=>{
 assert.throws(()=>applyWriting(document(),{...proposal,state:'held'},'post',1),/Held/);
 assert.throws(()=>validateWriting({...sample,extra:true}),/fields/);
 assert.throws(()=>validateWriting({...sample,posts:sample.posts.slice(1)}),/count/);
 assert.throws(()=>validateWriting({...sample,reel:{...sample.reel,shots:[{...sample.reel.shots[0],seconds:true},...sample.reel.shots.slice(1)]}}),/duration/);
 const text=writingText(proposal);
 assert.ok(text.indexOf(sample.posts[0].caption)<text.indexOf('INTERNAL EVIDENCE'));
 assert.match(text,/Independent review pending/);assert.match(text,/Goal \(planning input\): enquiries/);
 assert.equal((text.match(/Post \d:/g)||[]).length,3);
});

test('replacement preview shows exact existing and proposed text without editing owner work',()=>{
 const doc=document(),before=structuredClone(doc);
 for(const [kind,target,index] of [['post',3,1],['reel',doc.creatives.find(p=>p.format==='video_ad').id,0]]){
  const preview=writing.previewWritingReplacement(doc,proposal,kind,target,index);
  const field=kind==='post'?'posts':'creatives',key=kind==='post'?'day':'id';
  assert.deepEqual(preview.before,doc[field].find(item=>item[key]===target));
  assert.deepEqual(preview.after,applyWriting(doc,proposal,kind,target,index)[field].find(item=>item[key]===target));
  assert.notEqual(preview.before.copyDraft,preview.after.copyDraft);
  assert.deepEqual(doc,before);
  assert.deepEqual(writing.applyWritingReplacement(doc,proposal,preview),applyWriting(doc,proposal,kind,target,index));
 }
});
test('replacement confirmation rejects changed destination or changed proposal but preserves unrelated edits',()=>{
 const doc=document(),preview=writing.previewWritingReplacement(doc,proposal,'post',3,1);
 const changed=editMarketingPost(doc,3,{callToAction:'Owner changed this while comparing.'});
 assert.throws(()=>writing.applyWritingReplacement(changed,proposal,preview),/changed.*compare again/i);
 assert.equal(changed.posts[2].callToAction,'Owner changed this while comparing.');
 const other=editMarketingPost(doc,4,{copyDraft:'Keep this independent owner edit.'});
 assert.equal(writing.applyWritingReplacement(other,proposal,preview).posts[3].copyDraft,other.posts[3].copyDraft);
 const changedProposal=structuredClone(proposal);changedProposal.sample.posts[1].caption+=' Extra proposed words.';
 assert.throws(()=>writing.applyWritingReplacement(doc,changedProposal,preview),/changed.*compare again/i);
 const video=doc.creatives.find(p=>p.format==='video_ad');
 const reelPreview=writing.previewWritingReplacement(doc,proposal,'reel',video.id);
 const revised={...doc,creatives:doc.creatives.map(item=>item.id===video.id?{...item,brief:'Keep my revised storyboard.'}:item)};
 assert.throws(()=>writing.applyWritingReplacement(revised,proposal,reelPreview),/changed.*compare again/i);
 assert.throws(()=>writing.applyWritingReplacement({...doc,goal:'bookings'},proposal,preview),/context/);
 assert.throws(()=>writing.applyWritingReplacement(doc,{...proposal,state:'held'},preview),/Held/);
});

test('changing only an observation source invalidates a proposed replacement',()=>{
 const doc=document();
 const current={...proposal,sourceContext:writingContext(doc)};
 assert.ok(writingMatchesDocument(doc,current));
 const changed={...doc,observedFactSources:doc.observedFactSources.map(()=>doc.sourceUrl+'detail')};
 assert.equal(writingMatchesDocument(changed,current),false);
 assert.throws(()=>applyWriting(changed,current,'post',1),/context/);
});

test('writing review resolves exact page evidence and distinguishes owner corrections without changing copy',()=>{
 const material={...proposal.material,evidence:[
  {id:'fact-15',quote:'Plumbing services for leaking and burst pipes across all 32 London boroughs.',sourceUrl:'https://example.org/services/plumbing/emergency/',status:'owner_correction'},
  {id:'brief-callToAction',quote:'Contact the workshop.',sourceUrl:'',status:'owner_input'},
  {id:'research-service',quote:'Unreviewed service detail.',sourceUrl:'https://example.org/service/',status:'website_claim_unconfirmed'}]};
 const item={...sample.posts[0],evidence:[
  {id:'fact-15',quote:'leaking and burst pipes across all 32 London boroughs.'},
  {id:'brief-callToAction',quote:'Contact the workshop.'},
  {id:'research-service',quote:'Unreviewed service detail.'},
  {id:'missing',quote:'A missing source must not inherit another page.'}]};
 const before=structuredClone({material,item});
 const sources=writing.writingEvidenceSources({material},item);
 assert.deepEqual(sources[0],{...item.evidence[0],sourceUrl:material.evidence[0].sourceUrl,
  label:'Owner correction · linked page is context, not verification'});
 assert.equal(sources[1].label,'Owner input · no website source');
 assert.equal(sources[1].sourceUrl,'');
 assert.equal(sources[2].label,'Unconfirmed website claim · cannot support proposed copy');
 assert.equal(sources[3].label,'Source missing or excerpt changed · review required');
 assert.equal(sources[3].sourceUrl,'');
 assert.deepEqual({material,item},before);
 assert.equal(writing.writingEvidenceSources({material}, {...item,evidence:[{id:'fact-15',quote:'An invented excerpt.'}]} )[0].sourceUrl,'');
});

test('writing evidence never promotes an unsafe source reference into a clickable link',()=>{
 for(const sourceUrl of ['javascript:alert(1)','http://example.org/service','https://user:password@example.org/','not a URL']){
  const item={evidence:[{id:'fact-0',quote:'We offer bicycle servicing and brake adjustments.'}]};
  const material={evidence:[{...item.evidence[0],status:'owner_reviewed_observation',sourceUrl}]};
  const [source]=writing.writingEvidenceSources({material},item);
  assert.equal(source.sourceUrl,'');
  assert.equal(source.label,'Owner-reviewed observation · source link unavailable');
  const corrected=writing.writingEvidenceSources({material:{evidence:[{...material.evidence[0],status:'owner_correction'}]}},item)[0];
  assert.equal(corrected.sourceUrl,'');
  assert.equal(corrected.label,'Owner correction · source link unavailable');
 }
});
