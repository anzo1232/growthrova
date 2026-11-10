import test from 'node:test';
import assert from 'node:assert/strict';
import {decisionFramework,CUSTOMER_JOURNEY_STAGES} from '../src/lib/businessDecisionFramework.mjs';
test('category-neutral decision model covers all buying stages',()=>{
 assert.equal(CUSTOMER_JOURNEY_STAGES.length,5);
 for(const {id} of CUSTOMER_JOURNEY_STAGES){
  const value=decisionFramework({stage:id,offer:'Pet grooming',action:'Book online'});
  assert.ok(value.customerQuestion);
  assert.equal(value.offer,'Pet grooming');
  assert.match(value.status,/not independently verified/);
 }
});
test('rejects unknown stage, bounds unsafe untrusted profile',()=>{
 const v=decisionFramework({stage:'made-up',action:'a'.repeat(400)});
 assert.equal(v.stage,'consider');
 assert.equal(v.action.length,160);
 assert.equal(decisionFramework({offer:{secret:'x'}}).offer,'Describe the actual product or service');
});
