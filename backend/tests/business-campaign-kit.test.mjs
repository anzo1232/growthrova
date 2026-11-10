import test from 'node:test';import assert from 'node:assert/strict';
import {buildCampaignKit} from '../src/lib/businessCampaignKit.mjs';
test('creates multiple editable formats without claiming evidence',()=>{
 const k=buildCampaignKit({business:{name:'Example Barber',goal:'bookings'},customer:{audience:'local customers',desire:'great haircut',proof:'finished result'},decision:{offer:'haircuts',action:'book online'},clips:[{title:'Scene 1',start_s:1,end_s:31}]});
 assert.equal(k.deliverables.clipPlans.length,1);assert.equal(k.deliverables.socialCaptions.length,1);
 assert.match(k.deliverables.emailDraft.subject,/Example Barber/);
 assert.equal(k.noClaimsVerified,true);assert.match(k.status,/approval/);
});
test('does not silently fabricate a result for unknown niche',()=>{
 const k=buildCampaignKit({clips:[{start_s:0,end_s:22,title:'Scene'}]});
 assert.match(k.deliverables.clipPlans[0].limitation,/not confirmed/);
 assert.throws(()=>buildCampaignKit({clips:[]}),/Choose/);
});
