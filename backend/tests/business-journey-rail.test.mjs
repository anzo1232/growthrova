import test from 'node:test';
import assert from 'node:assert/strict';
import {summariseJourney} from '../src/lib/businessJourneyStages.mjs';

function campaign({
 business='Marlow Kitchens',
 goal='enquiries',
 evidence=['We supply and fit bespoke kitchens for residential homeowners.'],
 posts=[{status:'draft'},{status:'copy_reviewed'}],
 shortlist=null,
}={}){
 return {business,goal,sourceUrl:'https://marlow-kitchens.example/',observedFacts:evidence,
         posts,creatives:[{id:'creative-1',status:'copy_reviewed'}],editorialShortlist:shortlist};
}
test('progress is transparent: saved post copy is not a completed marketing service',()=>{
 const output=summariseJourney(campaign(),{assetCount:1});
 assert.deepEqual(output.steps.map(s=>s.id),['research','strategy','plan','production','approval','delivery']);
 assert.equal(output.steps[0].status,'verify');
 assert.equal(output.steps[2].status,'draft');
 assert.equal(output.steps[3].status,'waiting');
 assert.equal(output.steps[4].status,'waiting');
 assert.equal(output.steps[5].status,'not_connected');
 assert.match(output.nextAction,/review/i);
 assert.equal(output.published,0);
 assert.equal(output.measured,false);
});
test('three sourced directions do not become thirty ready posts',()=>{
 const output=summariseJourney(campaign({business:'Atelier Florist',
   shortlist:{status:'three_directions_ready_for_asset_intake',candidates:[{id:'a'},{id:'b'},{id:'c'}]}}),{assetCount:0});
 assert.match(output.steps[2].detail,/3 directions/);
 assert.match(output.nextAction,/authentic/i);
 assert.doesNotMatch(output.steps[2].detail,/30 ready/);
 assert.equal(output.steps[3].status,'waiting');
});
test('missing evidence and unknown industries are explicit blockers',()=>{
 const output=summariseJourney(campaign({business:'Specialist Workshop',evidence:[],posts:[]}),{assetCount:null});
 assert.equal(output.steps[0].status,'blocked');
 assert.equal(output.steps[1].status,'blocked');
 assert.equal(output.steps[2].status,'blocked');
 assert.match(output.nextAction,/evidence/i);
});
test('copy reviewed and six images never imply owner approval, scheduling or performance',()=>{
 const output=summariseJourney(campaign({business:'Private Clinic',
      posts:Array.from({length:4},()=>({status:'copy_reviewed',copyDraft:'Discuss your appointment with the clinic.',callToAction:'Contact the clinic'}))}),{assetCount:6});
 assert.equal(output.steps[2].status,'review');
 assert.equal(output.steps[4].status,'waiting');
 assert.equal(output.steps[5].status,'not_connected');
 assert.equal(output.published,0);
 assert.equal(output.measured,false);
 assert.match(output.steps[3].detail,/6/);
});
test('legacy checked planning instructions do not inflate copy review progress',()=>{
 const output=summariseJourney(campaign({posts:[{status:'copy_reviewed',copyDraft:'Draft direction: Explain the service.',callToAction:'Enquire'}]}));
 assert.equal(output.steps[2].status,'draft');
 assert.match(output.steps[2].detail,/0 copy-reviewed/);
});
test('invalid or negative asset counts do not grant production readiness',()=>{
 for(const assetCount of [-1,NaN,'100',false,Infinity]){
  const output=summariseJourney(campaign(),{assetCount});
  assert.equal(output.steps[3].status,'waiting');
 }
});
test('image attempts cannot be presented as finished review-ready media',()=>{
 const output=summariseJourney(campaign(),{assetCount:4});
 assert.equal(output.steps[3].status,'waiting');
 assert.match(output.steps[3].detail,/4 image attempts/i);
 assert.doesNotMatch(output.steps[3].detail,/completed image output/i);
 assert.match(output.nextAction,/Review each website observation/);
 assert.match(output.steps[3].detail,/verify actual output bytes/i);
});
