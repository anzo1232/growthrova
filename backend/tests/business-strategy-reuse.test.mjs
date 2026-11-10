import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {confirmOwnerStrategy,prepareNextStrategyCampaign,strategyConfirmed} from '../src/lib/businessOwnerStrategy.mjs';

function source(){
 const doc=createMarketingDocument({business:'Harbour Cycles',sourceUrl:'https://cycles.example/',goal:'enquiries',
  observedFacts:['Workshop servicing'],observedFactSources:['https://cycles.example/services'],
  websiteAuditText:'Saved workshop research',websiteImages:[],
  plan:{posts:[{day:1,theme:'Old campaign',channel:'Instagram',format:'Image post',objective:'enquiries',copyDraft:'Original words'}]},
  creative:{prompt:'Original exact brief',ctaDraft:'Ask us'},
  suggestedStrategy:{audience:'Local bicycle owners',offer:'Bicycle servicing',positioning:'',callToAction:'Ask us',constraints:'Confirm availability.',
   factDecisions:[{index:0,observation:'Workshop servicing',decision:'confirmed',statement:''}]}});
 return {...confirmOwnerStrategy(doc),brandKit:{name:'Harbour',primary_color:'#123ABC',secondary_color:'',font_style:''},
  paidCampaign:{secret:'must stay original'},googleCampaign:{old:true},organicWork:{old:true},prospects:[{email:'private@example.com'}]};
}

test('fresh goal reuses context without old copy, delivery preparation or confirmation; server accepts it',()=>{
 const original=source(),before=structuredClone(original);
 const next=prepareNextStrategyCampaign(original,{goal:'bookings',startDate:'2026-12-01'});
 assert.deepEqual(original,before);
 assert.equal(next.goal,'bookings');assert.equal(next.calendarStartDate,'2026-12-01');
 for(const key of ['observedFacts','observedFactSources','brandKit']){
  assert.deepEqual(next[key],original[key]);assert.notEqual(next[key],original[key]);
 }
 assert.equal(next.ownerStrategy.offer,original.ownerStrategy.offer);
 assert.deepEqual(next.ownerStrategy.factDecisions,original.ownerStrategy.factDecisions);
 assert.equal(strategyConfirmed(next),false);
 for(const key of ['paidCampaign','googleCampaign','organicWork','prospects'])assert.equal(Object.hasOwn(next,key),false);
 assert.equal(next.posts.length,30);
 assert(next.posts.every(post=>post.objective==='bookings'&&post.status==='draft'&&!post.published&&!post.scheduled&&!post.copyDraft.includes('Original words')));
 assert(next.creatives.every(item=>item.format!=='video_ad'&&!item.assetUrl&&!item.approved&&item.status==='draft'&&item.brief.includes('Goal: bookings')));
 assert.equal(next.canPublish,false);assert.equal(next.canSpend,false);
 const check=spawnSync('.venv-business-tests/bin/python',['-c',
  'import json,sys; from business_marketing_drafts import normalise_document; print(json.dumps(normalise_document(json.loads(sys.stdin.readline()))))'],
 {input:JSON.stringify(next)+'\n',encoding:'utf8',timeout:20000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
 assert.equal(check.status,0,check.stderr);
 const saved=JSON.parse(check.stdout);
 assert.deepEqual(saved.ownerStrategy,next.ownerStrategy);
 assert.deepEqual(saved.posts,next.posts);
 assert.deepEqual(saved.brandKit,next.brandKit);
 assert.equal(saved.goal,'bookings');
});

test('reuse rejects unreviewed context, unsupported goals and invalid dates',()=>{
 const doc=source();
 assert.throws(()=>prepareNextStrategyCampaign({...doc,ownerStrategy:{...doc.ownerStrategy,confirmedContext:null}},{goal:'bookings',startDate:'2026-12-01'}),/Confirm/);
 assert.throws(()=>prepareNextStrategyCampaign(doc,{goal:'sales',startDate:'2026-12-01'}),/goal/);
 assert.throws(()=>prepareNextStrategyCampaign(doc,{goal:'bookings',startDate:'2026-02-30'}),/date/);
});
