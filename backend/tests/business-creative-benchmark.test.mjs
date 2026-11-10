import test from 'node:test';import assert from 'node:assert/strict';
import {createBenchmarkJobs,nextCreativeAttempt,prepareWebsiteBenchmark} from '../src/lib/businessCreativeBenchmark.mjs';
test('four real business cases with provider diversity and no implicit charges',()=>{
 const jobs=createBenchmarkJobs();assert.equal(jobs.length,4);
 assert.equal(new Set(jobs.map(j=>j.businessType)).size,4);
 assert.equal(new Set(jobs.map(j=>j.providerCandidate)).size,3);
 assert.ok(jobs.every(j=>!j.spendingAuthorised&&!j.paidJobSubmitted));
});
test('paid retries disabled by default, even after quality rejection',()=>{
 const initial=createBenchmarkJobs({maxJobs:1})[0];
 assert.equal(nextCreativeAttempt(initial).attempts,0);
 const first=nextCreativeAttempt(initial,{assetApproved:true,budgetApproved:true});
 const second=nextCreativeAttempt(first,{assetApproved:true,budgetApproved:true,previousResult:'quality_rejected'});
 assert.equal(second.attempts,1);
 assert.equal(second.status,'manual_review_required');
});
test('rejects uncontrolled counts and retries',()=>{
 assert.throws(()=>createBenchmarkJobs({maxJobs:100}));
 assert.throws(()=>createBenchmarkJobs({maxRetries:8}));
});

test('benchmark names the actual four businesses and defaults to one paid attempt',()=>{
 const jobs=createBenchmarkJobs();
 assert.deepEqual(jobs.map(j=>j.business),['Encore VIP','Nomadd','The Beauty Retreat & Laser Clinic','Marleo Construction']);
 assert.ok(jobs.every(j=>j.maxAttempts===1));
});

test('URL benchmark requires genuine audit evidence and does not invent service details',()=>{
 const empty=prepareWebsiteBenchmark();
 assert.ok(empty.every(j=>j.prompt===null&&j.status==='awaiting_website_audit'));
 const populated=prepareWebsiteBenchmark({audits:{'test-encore-vip':{source_url:'https://encorevip.uk/',observations:{title:'Encore VIP',meta_description:'Concierge for exclusive experiences',headings:['Our services']}}}});
 assert.equal(populated[0].status,'awaiting_owner_fact_and_spend_approval');
 assert.match(populated[0].prompt,/Concierge for exclusive experiences/);
 assert.equal(populated[0].maxAttempts,1);
 assert.equal(populated[1].prompt,null);
 const bad=prepareWebsiteBenchmark({audits:{'test-encore-vip':{source_url:'https://wrong.example/',observations:{title:'False site'}}}});
 assert.equal(bad[0].status,'source_domain_mismatch');
});
