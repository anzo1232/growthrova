import test from 'node:test';import assert from 'node:assert/strict';import {assessCreativeReadiness} from '../src/lib/businessCreativeQuality.mjs';
test('generic text-only creative cannot pass generation or publishing gates',()=>{
 const r=assessCreativeReadiness({artDirection:'Luxury premium'});
 assert.equal(r.readyForGeneration,false);assert.equal(r.readyForPublication,false);
 assert.ok(r.issues.length>=5);
});
test('full brief is generation ready yet still needs owner publish approval',()=>{
 const r=assessCreativeReadiness({brandAssets:['brandkit'],referenceAssets:['authentic-photo'],offerVerified:true,claimsVerified:true,artDirection:'Cinematic understated editorial campaign with warm natural lighting',layoutPlan:'Grid typography, balanced whitespace and product hero placement'});
 assert.equal(r.readyForGeneration,true);assert.equal(r.readyForPublication,false);
});
