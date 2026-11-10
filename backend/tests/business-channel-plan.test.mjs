// Retained for the later audit; build-first checks do not execute this suite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmOwnerStrategy,editOwnerStrategy,strategyFields} from '../src/lib/businessOwnerStrategy.mjs';
import {channelSuggestions,proposedChannelPlan,applyChannelPlan,applySuggestedChannel} from '../src/lib/businessChannelPlan.mjs';
import {marketingPlanCsv} from '../src/lib/businessMarketingDocument.mjs';

function campaign(goal='education'){
  let doc={business:'Workshop',goal,observedFacts:[],posts:[
    {day:4,channel:'Website',format:'Carousel',copyDraft:'Keep fourth day',status:'draft'},
    {day:1,channel:'Instagram',format:'Image post',copyDraft:'Keep first day',status:'draft'},
    {day:2,channel:'X',format:'Image post',copyDraft:'Reviewed words',status:'copy_reviewed'},
    {day:3,channel:'TikTok',format:'Video',copyDraft:'Existing video plan',status:'draft'},
  ],creatives:[]};
  for(const key of Object.keys(strategyFields))doc=editOwnerStrategy(doc,key,'Owner supplied '+key);
  return confirmOwnerStrategy(doc);
}
test('preview agrees with explicit edits, preserves excluded days and survives document roundtrip/export',()=>{
  const original=campaign(),before=structuredClone(original),plan=proposedChannelPlan(original);
  const next=applyChannelPlan(original);
  assert.deepEqual(plan.map(({day,channel})=>({day,channel})),[{day:1,channel:'LinkedIn'},{day:4,channel:'Instagram'}]);
  for(const item of plan)assert.equal(next.posts.find(post=>post.day===item.day).channel,item.channel);
  for(const day of [2,3])assert.equal(next.posts.find(post=>post.day===day),original.posts.find(post=>post.day===day));
  for(const post of next.posts){const old=original.posts.find(item=>item.day===post.day);assert.equal(post.copyDraft,old.copyDraft);assert.equal(post.format,old.format);}
  assert.equal(next.creatives,original.creatives);assert.deepEqual(original,before);
  assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
  assert.deepEqual(JSON.parse(JSON.stringify(next)).posts,next.posts);
  assert.match(marketingPlanCsv(next),/LinkedIn/);
  assert.equal(applyChannelPlan(next),next);
});
test('current goal/confirmation and eligible day are required for every application',()=>{
  const doc=campaign();
  assert.throws(()=>applySuggestedChannel(doc,2,'LinkedIn'),/unreviewed/);
  assert.throws(()=>applySuggestedChannel(doc,3,'LinkedIn'),/unreviewed/);
  assert.throws(()=>applySuggestedChannel(doc,1,'TikTok'),/suggested channel/);
  const changed={...doc,goal:'awareness'};
  assert.deepEqual(channelSuggestions(changed),[]);
  assert.throws(()=>applyChannelPlan(changed),/Confirm/);
  const confirmed=confirmOwnerStrategy(changed);
  assert.equal(proposedChannelPlan(confirmed)[0].channel,'Instagram');
  assert.notDeepEqual(channelSuggestions(confirmed),channelSuggestions(doc));
});
