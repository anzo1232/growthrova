import test from 'node:test';import assert from 'node:assert/strict';
import {businessOpportunityAudit} from '../src/lib/businessOpportunityAudit.mjs';
import {marketingLoop} from '../src/lib/businessMarketingLoop.mjs';
test('business website alone does not claim researched brand or completed launch',()=>{
 const m=marketingLoop(businessOpportunityAudit({website:'example.com'}));
 assert.equal(m.steps.length,5);
 assert.equal(m.steps[0].status,'needs_business_details');
 assert.equal(m.publishingEnabled,false);assert.equal(m.verifiedWebsite,false);
 assert.ok(m.steps.every(s=>s.status!=='complete'));
});
test('typed business receives an honest next step',()=>{
 const m=marketingLoop(businessOpportunityAudit({description:'independent barber'}));
 assert.equal(m.steps[0].status,'brief_started');
 assert.match(m.nextAction,/Confirm/);
});
