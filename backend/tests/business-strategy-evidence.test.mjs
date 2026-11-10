import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeStrategyEvidence,strategyEvidenceStatus} from '../src/lib/businessStrategyEvidence.mjs';
import {createBusinessRepository} from '../src/lib/businessRepository.mjs';
const org='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const profile={business_description:'Independent pottery studio',offer:'Evening classes',audience:'Adults',differentiation:'Small groups',source_type:'website',source_reference:'https://studio.example',owner_confirmed:true,research_evidence:{offer:{sourceUrl:'https://studio.example/classes',quote:'Evening classes',claim:'Evening classes',status:'verified',reportSha256:'a'.repeat(64)}}};
test('authenticated profile save and reload retain claim-bound excerpts under organisation scope',async()=>{
 let row;const calls=[];
 const client={auth:{getUser:async()=>({data:{user:{id:'owner'}}})},from(table){assert.equal(table,'business_confirmed_profiles');return {
 upsert(value){row=structuredClone(value);return this;},select(){return this;},eq(key,value){calls.push([key,value]);return this;},single:async()=>({data:row}),maybeSingle:async()=>({data:row})};}};
 const repo=createBusinessRepository(client);
 await repo.saveConfirmedProfile(org,{...profile,organisation_id:'attacker',confirmed_by:'attacker'});
 const saved=await repo.readConfirmedProfile(org);
 assert.equal(saved.organisation_id,org);assert.equal(saved.confirmed_by,'owner');
 assert.deepEqual(calls,[['organisation_id',org]]);
 assert.equal(saved.research_evidence.offer.status,'unverified_website_statement');
 assert.equal(saved.research_evidence.offer.reportSha256,'a'.repeat(64));
 assert.match(strategyEvidenceStatus(saved,'offer'),/not independently verified/);
 assert.match(strategyEvidenceStatus({...saved,offer:'Guaranteed results'},'offer'),/Claim changed/);
 assert.match(strategyEvidenceStatus(saved,'audience'),/No source excerpt/);
});
test('unsafe, incomplete and oversized references fail closed; extra authority is stripped',()=>{
 for(const patch of [{sourceUrl:'javascript:alert(1)'},{sourceUrl:'https://user:password@example.com'},{quote:''},{quote:'x'.repeat(1201)}])assert.throws(()=>normalizeStrategyEvidence({offer:{...profile.research_evidence.offer,...patch}}));
 assert.throws(()=>normalizeStrategyEvidence({other:{}}));
 assert.equal(normalizeStrategyEvidence(profile.research_evidence).offer.status,'unverified_website_statement');
});
test('unauthenticated evidence save never reaches database',async()=>{
 const repo=createBusinessRepository({auth:{getUser:async()=>({data:{user:null}})},from(){throw Error('database reached');}});
 await assert.rejects(repo.saveConfirmedProfile(org,profile),e=>e.code==='auth_required');
});
