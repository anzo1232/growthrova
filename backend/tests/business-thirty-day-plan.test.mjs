import test from 'node:test';import assert from 'node:assert/strict';
import {buildThirtyDayPlan,recommendBusinessServices} from '../src/lib/businessThirtyDayPlan.mjs';
import {reviewCreative} from '../src/lib/businessCreativeReview.mjs';
test('creates 30 unscheduled day-scoped content drafts with objectives',()=>{
 const plan=buildThirtyDayPlan({business:'Mobile detailing',offer:'Interior cleaning',audience:'Car owners'});
 assert.equal(plan.posts.length,30);assert.equal(plan.posts[29].day,30);
 assert.ok(plan.posts.every(p=>!p.published&&!p.scheduled&&p.proofNeeded));
 assert.ok(new Set(plan.posts.map(p=>p.format)).size>=4);
});
test('service opportunities make no external audit claims',()=>{
 const services=recommendBusinessServices({hasWebsite:false});
 assert.equal(services.length,5);assert.match(services[1].reason,/optional/);
});
test('review controls do not turn a nonexistent asset into an approved advert',()=>{
 assert.throws(()=>reviewCreative({title:'Mock'},{type:'approve'}));
 const draft=reviewCreative({title:'Mock'},{type:'edit',copy:'Revised headline'});
 assert.equal(draft.reviewStatus,'needs_review');
 assert.equal(reviewCreative(draft,{type:'regenerate'}).reviewStatus,'needs_generation');
 const approved=reviewCreative({assetUrl:'https://example.org/media.png',brandVerified:true,claimsVerified:true},{type:'approve'});
 assert.equal(approved.published,false);
});
test('website-derived 30-day plan has distinct useful copy, not repeated placeholder sentences',()=>{
 const plan=buildThirtyDayPlan({business:'Encore VIP',offer:'EncoreVIP is a premium access platform built around exclusivity, ease, and experience. Members enjoy elevated benefits and curated opportunities.',audience:'Potential customers (inferred; requires verification)',goal:'enquiries',sector:'concierge'});
 assert.equal(plan.posts.length,30);
 assert.equal(new Set(plan.posts.map(p=>p.theme)).size,30);
 assert.equal(new Set(plan.posts.map(p=>p.copyDraft)).size,30);
 assert.ok(plan.posts.every(p=>p.copyDraft.length>65&&!p.copyDraft.includes('Potential customers')&&!p.copyDraft.includes('for undefined')));
 assert.ok(plan.posts.some(p=>/EncoreVIP is a premium access platform/i.test(p.copyDraft)));
 assert.ok(plan.posts.every(p=>p.proofNeeded&&!p.scheduled&&!p.published));
 assert.ok(plan.posts.every(p=>!(p.channel==='Email'&&p.format==='Video advert')));
});
test('long verified website descriptions are not cut mid-word into nonsensical captions',()=>{
 const description='EncoreVIP is a premium access platform built around exclusivity, ease, and experience. Members enjoy elevated benefits, priority access, and curated opportunities that make every moment feel intentional and unforgettable.';
 const plan=buildThirtyDayPlan({business:'Encore VIP',offer:description,audience:'Unverified audience',sector:'concierge'});
 assert.ok(plan.posts[0].copyDraft.includes('intentional and unforgettable'),plan.posts[0].copyDraft);
});
test('roofing customer posts explain actual roof problems, not generic marketing slogans',()=>{
 const p=buildThirtyDayPlan({business:'Harbour Roofing',offer:'Roof repairs, guttering and flat roofs',audience:'Homeowners',sector:'roofing'});
 assert.equal(p.posts.length,30);
 assert.ok(p.posts.some(x=>/leak|gutter|tile/i.test(x.copyDraft)));
 assert.ok(p.posts.some(x=>/quote|survey|repair/i.test(x.copyDraft)));
 assert.ok(p.posts.every(x=>!x.copyDraft.includes('premium access')&&!x.copyDraft.includes('someone weighing up')));
});
