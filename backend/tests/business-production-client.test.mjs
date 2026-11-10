import test from "node:test";
import assert from "node:assert/strict";
import {listBusinessDrafts,saveBusinessDraft,readBusinessMontage,startBusinessMontage,deleteBusinessDraft,createBusinessDraftIntent,readBusinessMontageUsage,readBusinessSourceUsage} from "../src/lib/businessProductionClient.mjs";
const orig=globalThis.fetch;
function mock(fn){globalThis.fetch=fn;return ()=>{globalThis.fetch=orig;};}
test("authenticated campaign draft lists and writes target the expected routes",async()=>{
  const calls=[];
  const reset=mock(async(url,opts)=>{
    calls.push({url,opts});
    return new Response(JSON.stringify({ok:true}),{status:200});
  });
  try {
    await listBusinessDrafts("test-token","org-1");
    await saveBusinessDraft("test-token",{organisation_id:"org-1",name:"Reel campaign",create_id:"11111111-1111-4111-8111-111111111111"});
    await deleteBusinessDraft("test-token","d".repeat(32));
    assert.match(calls[0].url,/\/api\/business\/drafts\?organisation_id=org-1/);
    assert.equal(calls[0].opts.headers.Authorization,"Bearer test-token");
    assert.equal(calls[1].opts.method,"POST");
    assert.equal(calls[2].opts.method,"DELETE");
    assert.equal(calls.length,3);
  }finally{reset();}
});
test("montage request cannot omit auth or leak a source key through status",async()=>{
  await assert.rejects(startBusinessMontage("",{organisation_id:"o",scenes:[],draft_id:"draft-1",draft_revision:1}),e=>e.code==="auth_required");
  const calls=[];
  const reset=mock(async(url,opts)=>{
    calls.push({url,opts});
    return new Response(JSON.stringify({status:"queued",montage_id:"a".repeat(32)}),{status:202});
  });
  try {
    const montage=await startBusinessMontage("jwt-test",{organisation_id:"o",brand_id:"b",
      draft_id:"draft-1",draft_revision:2,scenes:[{source_id:"s",start_s:0,end_s:8},{source_id:"s",start_s:8,end_s:16}]});
    assert.equal(montage.status,"queued");
    assert.equal(JSON.parse(calls[0].opts.body).scenes.length,2);
    assert.equal(JSON.parse(calls[0].opts.body).draft_revision,2);
    await readBusinessMontage("jwt-test","a".repeat(32));
    assert.match(calls[1].url,/\/api\/business\/montages\/a+$/);
    assert.equal(calls[1].opts.method,"GET");
  }finally{reset();}
});
test("backend failures preserve typed errors and do not automatically retry paid work",async()=>{
  let count=0;
  const reset=mock(async()=>{count++;return new Response(JSON.stringify({
    code:"paid_plan_required",error:"A paid subscription is needed"
  }),{status:402});});
  try {
    await assert.rejects(startBusinessMontage("jwt",{organisation_id:"o",brand_id:"b",scenes:[],draft_id:"draft-1",draft_revision:1}),
      e=>e.code==="paid_plan_required"&&e.status===402);
    assert.equal(count,1);
  }finally{reset();}
});


test("draft creation requires stable client intent to prevent duplicate saves",async()=>{
  const first=createBusinessDraftIntent();
  const second=createBusinessDraftIntent();
  assert.match(first,/^[0-9a-f-]{36}$/i);
  assert.notEqual(first,second);
  assert.throws(()=>saveBusinessDraft("jwt",{name:"Missing request intent"}),
    TypeError);
});

test("montage requires an approved saved campaign revision",()=>{
  assert.throws(()=>startBusinessMontage("jwt",{organisation_id:"o",brand_id:"b",scenes:[]}),TypeError);
  assert.throws(()=>startBusinessMontage("jwt",{organisation_id:"o",brand_id:"b",scenes:[],draft_id:"d",draft_revision:0}),TypeError);
});


test("owner usage meter is authenticated, read-only and not a Stripe payment",async()=>{
  const calls=[];
  const reset=mock(async(url,opts)=>{
    calls.push({url,opts});
    return new Response(JSON.stringify({
      billable:false,meter:{completed_outputs:1,output_seconds:12}
    }),{status:200});
  });
  try {
    const stats=await readBusinessMontageUsage("owner-jwt");
    assert.equal(stats.billable,false);
    assert.equal(stats.meter.output_seconds,12);
    assert.equal(calls.length,1);
    assert.match(calls[0].url,/\/api\/business\/montages\/usage$/);
    assert.equal(calls[0].opts.method,"GET");
    assert.equal(calls[0].opts.headers.Authorization,"Bearer owner-jwt");
  }finally{reset();}
});

test("visual source usage is read-only, owner scoped and explicitly nonbillable",async()=>{
  const calls=[];
  const reset=mock(async(url,options)=>{
    calls.push({url,options});
    return new Response(JSON.stringify({billable:false,events:[{
      source_id:"a".repeat(32),processed_seconds:180,state:"needs_billing_review"
    }]}),{status:200});
  });
  try {
    const usage=await readBusinessSourceUsage("owner-jwt");
    assert.equal(usage.billable,false);
    assert.equal(usage.events[0].processed_seconds,180);
    assert.equal(calls.length,1);
    assert.match(calls[0].url,/\/api\/business\/visual\/usage$/);
    assert.equal(calls[0].options.method,"GET");
    assert.equal(calls[0].options.headers.Authorization,"Bearer owner-jwt");
  }finally{reset();}
});
