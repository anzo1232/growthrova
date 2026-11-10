import test from 'node:test';
import assert from 'node:assert/strict';
import {milestoneAReadiness} from '../src/lib/businessMilestoneReadiness.mjs';
const campaign={draftId:'draft123',revision:2,documentSha256:'f'.repeat(64),calendarEntries:Array.from({length:30},(_,i)=>({day:i+1}))};
const research={state:'captured_for_review',draftId:'draft123',revision:2,claimsVerified:false};
const owner={status:'owner_brief_confirmed',draftId:'draft123',revision:2};
const assets={draftId:'draft123',revision:2,documentSha256:'f'.repeat(64),assetCandidates:[{assetId:'photo',verifiedRights:false,authenticityVerified:false}]};
test('available but unverified research and owner-uploaded media cannot mark A complete',()=>{
 const r=milestoneAReadiness({authenticated:true,campaign,research,owner,assets});
 assert.equal(r.status,'blocked');
 assert.ok(r.gaps.includes('independent_research_confirmation_required'));
 assert.ok(r.gaps.includes('verified_customer_asset_rights_required'));
 assert.equal(r.canPublish,false);assert.equal(r.canSpend,false);
});
test('cross-campaign evidence, stale revisions and missing days fail closed',()=>{
 const r=milestoneAReadiness({authenticated:true,campaign:{...campaign,calendarEntries:campaign.calendarEntries.slice(1)},research:{...research,revision:1},owner:{...owner,draftId:'other'},assets:{...assets,revision:1}});
 for(const gap of ['complete_thirty_day_calendar_required','current_research_receipt_required','current_owner_confirmation_required','current_scoped_asset_inventory_required'])
  assert.ok(r.gaps.includes(gap),gap);
});
test('even complete evidence only enables supervised review, not money or publishing',()=>{
 const r=milestoneAReadiness({authenticated:true,campaign,research:{...research,claimsVerified:true},owner,assets:{...assets,assetCandidates:[{verifiedRights:true,authenticityVerified:true}]}});
 assert.equal(r.status,'ready_for_supervised_review');
 assert.equal(r.canSpend,false);assert.equal(r.canPublish,false);assert.equal(r.productionApproved,false);
});
