import test from 'node:test';
import assert from 'node:assert/strict';
import * as pipeline from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {editOwnerStrategy,confirmOwnerStrategy,strategyConfirmed} from '../src/lib/businessOwnerStrategy.mjs';

const input={business:'Reviewed Business',sourceUrl:'https://example.org/',goal:'enquiries',sector:'other',
 offer:'Owner input: bicycle brake adjustments by appointment.',audience:'Local bicycle commuters',
 positioning:'Bring your bicycle to discuss its brake problem.',callToAction:'Contact our workshop to discuss an appointment.'};
test('inaccessible website recovery enters existing document journey without fabricated website evidence or confirmation',()=>{
 const campaign=pipeline.prepareOwnerCampaign(input);
 const document=createMarketingDocument(campaign);
 assert.equal(document.business,input.business);
 assert.equal(document.sourceUrl,input.sourceUrl);
 assert.equal(document.ownerStrategy.offer,input.offer);
 assert.equal(document.ownerStrategy.audience,input.audience);
 assert.equal(document.ownerStrategy.positioning,input.positioning);
 assert.equal(document.ownerStrategy.callToAction,input.callToAction);
 assert.deepEqual(document.observedFacts,[]);
 assert.deepEqual(document.websiteImages,[]);
 assert.equal(document.editorialShortlist,null);
 assert.match(document.websiteAuditText,/not read/i);
 assert.match(document.websiteAuditText,/owner.supplied/i);
 assert.equal(strategyConfirmed(document),false);
 assert.equal(document.canPublish,false);assert.equal(document.canSpend,false);
 assert.ok(document.posts.every(p=>p.status==='draft'&&!p.published));
 const edited=editOwnerStrategy(document,'offer','Owner corrected brake adjustment service.');
 const confirmed=confirmOwnerStrategy(edited);
 assert.equal(strategyConfirmed(confirmed),true);
 assert.equal(document.ownerStrategy.offer,input.offer,'existing input is preserved');
 assert.deepEqual(confirmed.observedFacts,[],'confirmation does not invent website observations');
});
test('manual recovery rejects missing, unsafe or overlong business inputs instead of inventing a brief',()=>{
 for(const patch of [{offer:''},{audience:''},{callToAction:''},{business:''},{sourceUrl:'http://127.0.0.1/'},{offer:'x'.repeat(501)},{goal:'publish-now'}]){
  assert.throws(()=>pipeline.prepareOwnerCampaign({...input,...patch}),/required|invalid|maximum/i);
 }
 const campaign=pipeline.prepareOwnerCampaign({...input,positioning:''});
 assert.equal(campaign.suggestedStrategy.positioning,'','a missing differentiator stays missing');
});
test('manual recovery does not populate finished-looking website narration or generic copy before writing',()=>{
 const campaign=pipeline.prepareOwnerCampaign(input);
 assert.ok(campaign.plan.posts.every(post=>post.copyDraft===''),
  'owner brief recovery must await writing, not prefill generic website templates');
 assert.ok(campaign.plan.posts.every(post=>post.callToAction===input.callToAction));
});
