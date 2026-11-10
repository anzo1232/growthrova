import test from 'node:test';import assert from 'node:assert/strict';
import {normalizeBusinessCampaignDraft,createBusinessRepository,BusinessDataError} from '../src/lib/businessRepository.mjs';
const ORG='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const DRAFT='dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const USER='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const draft={name:'Launch campaign',goal:'enquiries',notes:'Internal only',scenes:[]};
function mock(result){const calls=[];const chain={select(...args){calls.push(['select',...args]);return this},eq(...args){calls.push(['eq',...args]);return this},update(...args){calls.push(['update',...args]);return this},insert(...args){calls.push(['insert',...args]);return this},single(){return Promise.resolve({data:result,error:null})},maybeSingle(){return Promise.resolve({data:result,error:null})},order(){return Promise.resolve({data:result,error:null})}};
 return {calls,auth:{getUser:async()=>({data:{user:{id:USER}}})},from(table){calls.push(['from',table]);return chain}}}
test('draft persistence strips unauthorised publish fields',async()=>{
 const client=mock({id:DRAFT});await createBusinessRepository(client).createCampaignDraft(ORG,{...draft,published:true,spendAuthorised:true,owner_id:'attacker'});
 const inserted=client.calls.find(c=>c[0]==='insert')[1];
 assert.equal(inserted.owner_id,USER);assert.equal(inserted.published,undefined);assert.equal(inserted.spendAuthorised,undefined);
});
test('campaign update is scoped to org, draft and expected revision',async()=>{
 const client=mock({id:DRAFT,revision:2});await createBusinessRepository(client).updateCampaignDraft(ORG,DRAFT,draft,1);
 assert.deepEqual(client.calls.filter(c=>c[0]==='eq').map(x=>x.slice(1)),[['id',DRAFT],['organisation_id',ORG],['revision',1]]);
 assert.equal(client.calls.find(c=>c[0]==='update')[1].revision,2);
});
test('revision conflicts fail without silently overwriting changes',async()=>{
 const client=mock(null);
 await assert.rejects(()=>createBusinessRepository(client).updateCampaignDraft(ORG,DRAFT,draft,5),e=>e.code==='revision_conflict');
});
test('rejects forged ids, invalid scene timings and unknown goals',()=>{
 assert.throws(()=>normalizeBusinessCampaignDraft({...draft,goal:'spend money'}),BusinessDataError);
 assert.throws(()=>normalizeBusinessCampaignDraft({...draft,scenes:[{source_id:ORG,start_s:8,end_s:2}]}),BusinessDataError);
 assert.throws(()=>normalizeBusinessCampaignDraft({...draft,brand_id:'bad'}),BusinessDataError);
});
