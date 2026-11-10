import test from 'node:test';import assert from 'node:assert/strict';
import {creativeDirector} from '../src/lib/businessCreativeDirector.mjs';
test('three to five useful creative formats and a four-week marketing plan',()=>{
 for(const count of [3,4,5]){
  const d=creativeDirector({business:'Mobile groomer',offer:'Dog grooming',audience:'Local pet owners',confirmed:true,variationCount:count});
  assert.equal(d.variations.length,count);assert.equal(d.marketingPlan.weekly.length,4);
  assert.equal(d.mediaGenerated,false);assert.ok(d.variations.every(v=>v.generated===false&&v.published===false));
  assert.ok(d.variations.some(v=>v.format==='video_ad'));
 }
});
test('labels synthetic visuals and never claims a provider quality winner',()=>{
 const d=creativeDirector({business:'Dentist',offer:'Consultations',audience:'Adults',confirmed:true,assetMode:'generated'});
 assert.ok(d.variations.every(v=>v.sourcePolicy==='SYNTHETIC_VISUALS_DISCLOSED'));
 assert.ok(d.variations.every(v=>v.providerSelection==='benchmark_pending_no_winner_claimed'));
});
test('refuses unverifiable intake, invalid counts or modes',()=>{
 const fields={business:'A',offer:'B',audience:'C',confirmed:true};
 assert.throws(()=>creativeDirector({...fields,confirmed:false}));
 assert.throws(()=>creativeDirector({...fields,variationCount:9}));
 assert.throws(()=>creativeDirector({...fields,assetMode:'secret'}));
});
