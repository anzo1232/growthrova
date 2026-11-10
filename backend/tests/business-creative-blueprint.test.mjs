import test from 'node:test';import assert from 'node:assert/strict';
import {creativeBlueprint} from '../src/lib/businessCreativeBlueprint.mjs';
test('generates multiple formats without inventing media or outcomes',()=>{
 const p=creativeBlueprint({business:'Niche service',offer:'Equipment servicing',audience:'local manufacturers',confirmed:true});
 assert.equal(p.creatives.length,4);assert.equal(p.generationEnabled,false);
 assert.equal(p.creatives[0].status,'brief_only_not_generated');
 assert.ok(p.creatives.every(c=>!c.verifiedClaims));
});
test('requires audience and real offering before proposing creatives',()=>{
 assert.throws(()=>creativeBlueprint({business:'Test'}),/audience/);
 const p=creativeBlueprint({business:'Barber',offer:'Haircuts',audience:'Local customers'});
 assert.equal(p.profileConfirmed,false);
});
