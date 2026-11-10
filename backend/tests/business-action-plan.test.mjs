import test from 'node:test';import assert from 'node:assert/strict';
import {businessOpportunityAudit} from '../src/lib/businessOpportunityAudit.mjs';
import {businessActionPlan} from '../src/lib/businessActionPlan.mjs';
test('website alone never counts as verified business profile',()=>{
 const p=businessActionPlan(businessOpportunityAudit({website:'example.com'}));
 assert.equal(p.readyCount,0);assert.equal(p.nextTask,'profile');
 assert.equal(p.tasks[4].ready,false);
});
test('business description starts useful, permission-gated tasks',()=>{
 const p=businessActionPlan(businessOpportunityAudit({description:'commercial cleaning company',goal:'enquiries'}));
 assert.equal(p.readyCount,1);assert.equal(p.nextTask,'cta');
 assert.equal(p.tasks.length,6);
 assert.match(p.tasks[1].title,/enquiries/);
 assert.ok(p.tasks.every(t=>t.approval));
});
