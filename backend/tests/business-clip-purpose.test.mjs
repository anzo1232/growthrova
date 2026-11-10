import test from 'node:test';
import assert from 'node:assert/strict';
import {clipPurpose,customerDecision} from '../src/lib/businessClipPurpose.mjs';
test('each objective states intended outcome without inventing confirmed success',()=>{
 for(const goal of ['awareness','enquiries','bookings','education','offers']){
  const result=clipPurpose({title:'Visual scene 2',start_s:75},goal);
  assert.equal(result.verified,false);
  assert.match(result.title,/Footage to review/);
  assert.match(result.evidence,/not verified/);
  assert.ok(result.reviewAction.length>20);
 }
});
test('preserves grounded descriptive titles, not visual placeholder or unsupported rating',()=>{
 assert.equal(clipPurpose({title:'Chef explains the starter'},'bookings').title,'Chef explains the starter');
 assert.equal(clipPurpose({title:'Visual scene 8',start_s:160},'bookings').title,'Footage to review · 160s');
 assert.equal(clipPurpose({},'unknown').objective,'Build awareness');
});

test('business-specific uses remain unverified suggestions',()=>{
 const sectors=['hospitality','property','wellness','consulting','agency','other'];
 for(const sector of sectors){
  const item=clipPurpose({start_s:10,end_s:18},'bookings',sector);
  assert.equal(item.verified,false);
  assert.ok(item.proposedUse.length>20);
  assert.match(item.durationWarning,/B-roll/);
 }
 const property=clipPurpose({start_s:50,end_s:85},'enquiries','property');
 assert.match(property.reviewAction,/rooms remain in frame/);
 assert.equal(property.durationWarning,'');
 const wellness=clipPurpose({start_s:10,end_s:80},'education','wellness');
 assert.match(wellness.reviewAction,/consent/);
 assert.match(wellness.durationWarning,/pacing/);
});

test('customer decision brief is bounded and never treated as proven footage evidence',()=>{
 const profile={audience:'Local first-time customers',desire:'Great value',
   objection:'Unsure about quality',proof:'Real customer reviews'};
 const item=clipPurpose({start_s:15,end_s:42},'bookings','hospitality',profile);
 assert.equal(item.customerAudience,profile.audience);
 assert.equal(item.buyerObjection,profile.objection);
 assert.equal(item.evidenceNeeded,profile.proof);
 assert.equal(item.verified,false);
 assert.match(item.evidence,/not verified/);
 assert.equal(customerDecision({audience:'x'.repeat(500)}).audience.length,160);
 assert.equal(customerDecision({desire:{secret:'bad'}}).desire,'');
});
