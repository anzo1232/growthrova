import test from 'node:test';import assert from 'node:assert/strict';
import {businessOpportunityAudit} from '../src/lib/businessOpportunityAudit.mjs';
test('works for user description without a fixed niche',()=>{
 const a=businessOpportunityAudit({description:'mobile dog groomer',goal:'bookings'});
 assert.equal(a.opportunities.length,5);assert.match(a.editingApproach,/finished result/);
 assert.equal(a.verifiedWebsite,false);
});
test('website alone never pretends website has been scanned',()=>{
 const a=businessOpportunityAudit({website:'https://example.com'});
 assert.equal(a.website,'example.com');assert.match(a.status,/not scanned/);
 assert.match(a.editingApproach,/Confirm business activities/);
});
test('rejects empty and unsafe addresses',()=>{
 assert.throws(()=>businessOpportunityAudit({}));
 assert.throws(()=>businessOpportunityAudit({website:'javascript:alert(1)'}));
});
