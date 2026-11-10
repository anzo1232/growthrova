import test from "node:test";
import assert from "node:assert/strict";
import { validateBusinessVideo, uploadBusinessVideo } from "../src/lib/businessUploadClient.mjs";
import { readFileSync } from "node:fs";

const org="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const nonce="1".repeat(32);
function file(n=3000){return new File([new Uint8Array(n)],"brunch.mp4",{type:"video/mp4"});}
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});
function withFetch(fn,callback){
  const previous=globalThis.fetch;
  globalThis.fetch=fn;
  return Promise.resolve().then(callback).finally(()=>{globalThis.fetch=previous;});
}
test("business uploaded videos are strictly type and size checked",()=>{
  assert.equal(validateBusinessVideo(file()),"");
  assert.match(validateBusinessVideo(new File([new Uint8Array(3000)],"bad.svg",{type:"image/svg+xml"})),/MP4/);
  assert.match(validateBusinessVideo(new File([new Uint8Array(3000)],"bad.mp4",{type:"image/png"})),/does not match/);
});
test("direct upload requires authenticated init, PUT and confirmation",async()=>{
  const seen=[];
  const result=await withFetch(async (url,opts)=>{
    seen.push([url,opts]);
    if(String(url).includes("/sources/init"))return json({mode:"single",source_id:nonce,key:"business/sources/"+org+"/"+nonce+".mp4",upload_url:"https://put.example/upload",content_type:"video/mp4"});
    if(String(url).includes("put.example"))return new Response(null,{status:200});
    if(String(url).includes("/sources/confirm"))return json({ok:true,source_id:nonce});
    throw Error("unrecognised network call");
  },()=>uploadBusinessVideo({token:"test-token",organisationId:org,file:file(),nonce}));
  assert.equal(result.sourceId,nonce);
  assert.equal(seen.length,3);
  assert.equal(seen[0][1].headers.Authorization,"Bearer test-token");
  assert.equal(seen[1][1].method,"PUT");
  assert.equal(seen[2][1].method,"POST");
});
test("failed upload cannot be reported as confirmed",async()=>{
  let calls=0;
  await assert.rejects(withFetch(async(url)=>{
    calls++;
    if(String(url).includes("/sources/init"))return json({mode:"single",source_id:nonce,key:"any",upload_url:"https://put.example/upload"});
    if(String(url).includes("put.example"))return new Response(null,{status:403});
    throw Error("confirmation must not happen");
  },()=>uploadBusinessVideo({token:"test-token",organisationId:org,file:file(),nonce})));
  assert.equal(calls,2);
});
test("Business source keys guard preview/analysis and creator exports reject Business media",()=>{
  const backend=readFileSync(new URL("../server.py",import.meta.url),"utf8");
  const routes=readFileSync(new URL("../business_source_routes.py",import.meta.url),"utf8");
  assert.match(backend,/may_analyse_source\(_biz_key, _uid\)/);
  assert.match(backend,/may_analyse_source\(url\[5:\], _business_preview_owner\)/);
  assert.match(backend,/verified_source_object\(_biz_key, _uid, get_r2\(\), R2_BUCKET\)/);
  assert.match(backend,/verified_source_object\(url\[5:\],_business_preview_owner,get_r2\(\),R2_BUCKET\)/);
  assert.match(backend,/business_export_requires_approval/);
  assert.match(backend,/business_source_use_private_preview/);
  assert.match(routes,/source_for_owner\(key,user\["id"\]\)/);
});

test("multipart completion acknowledgement loss is reconciled, never repeated or aborted",async()=>{
  const seen=[];
  const token="test-token";
  const confirmed=await withFetch(async(url,options)=>{
    const target=String(url);
    seen.push([target,options?.method]);
    if(target.includes("/sources/init"))return json({
      mode:"worker",source_id:nonce,key:"business/sources/"+org+"/"+nonce+".mp4",
      base:"https://uploads.example",exp:1234567890,sig:"test-sig",part_size:8*1024*1024,
      content_type:"video/mp4"
    });
    if(target.includes("/mpu/create"))return json({uploadId:"test-upload"});
    if(target.includes("/mpu/part"))return json({etag:"part-one"});
    if(target.includes("/mpu/complete"))throw new TypeError("network died after successful commit");
    if(target.includes("/sources/confirm"))return json({ok:true,source_id:nonce});
    if(target.includes("/mpu/abort"))throw Error("must never abort after an unknown commit");
    throw Error("unrecognised network call "+target);
  },()=>uploadBusinessVideo({token,organisationId:org,file:file(),nonce}));
  assert.equal(confirmed.sourceId,nonce);
  assert.equal(confirmed.recovered,true);
  assert.equal(seen.filter(x=>x[0].includes("/mpu/create")).length,1);
  assert.equal(seen.filter(x=>x[0].includes("/mpu/complete")).length,1);
  assert.equal(seen.filter(x=>x[0].includes("/mpu/abort")).length,0);
});

test("server-recognised completed upload skips duplicate multipart creation entirely",async()=>{
  const seen=[];
  const result=await withFetch(async(url,opts)=>{
    seen.push(String(url));
    if(String(url).includes("/sources/init"))return json({
      status:"confirmed",replayed:true,source_id:nonce,
      key:"business/sources/"+org+"/"+nonce+".mp4"
    });
    throw Error("confirmed R2 object must not trigger another PUT");
  },()=>uploadBusinessVideo({token:"test-token",organisationId:org,file:file(),nonce}));
  assert.equal(result.recovered,true);
  assert.equal(seen.length,1);
});

test("unknown completion with no confirmed object fails safely without double-upload",async()=>{
  const seen=[];
  await assert.rejects(withFetch(async(url,opts)=>{
    const target=String(url);
    seen.push(target);
    if(target.includes("/sources/init"))return json({
      mode:"worker",source_id:nonce,key:"business/sources/"+org+"/"+nonce+".mp4",
      base:"https://uploads.example",exp:987654321,sig:"secret",part_size:8*1024*1024,
      content_type:"video/mp4"
    });
    if(target.includes("/mpu/create"))return json({uploadId:"u1"});
    if(target.includes("/mpu/part"))return json({etag:"e1"});
    if(target.includes("/mpu/complete"))throw TypeError("completion response missing");
    if(target.includes("/sources/confirm"))return json({code:"upload_invalid",error:"Object is not yet complete"},400);
    if(target.includes("/mpu/abort"))throw Error("abort must not run after commit started");
    throw Error("Unexpected call "+target);
  },()=>uploadBusinessVideo({
    token:"test-token",organisationId:org,file:file(),nonce
  })),e=>e.code==="upload_outcome_unknown");
  assert.equal(seen.filter(x=>x.includes("/mpu/create")).length,1);
  assert.equal(seen.filter(x=>x.includes("/mpu/complete")).length,1);
  assert.equal(seen.filter(x=>x.includes("/mpu/abort")).length,0);
});

test("HTTP 403 upload rejection never marks footage ready",async()=>{
  let checked=0;
  await assert.rejects(withFetch(async(url)=>{
    if(String(url).includes("/sources/init"))return json({
      mode:"single",source_id:nonce,key:"business/sources/"+org+"/"+nonce+".mp4",
      upload_url:"https://put.example/upload"
    });
    if(String(url).includes("put.example"))return new Response(null,{status:403});
    if(String(url).includes("/sources/confirm"))checked++;
    throw Error("must not verify definitive 403");
  },()=>uploadBusinessVideo({
    token:"test-token",organisationId:org,file:file(),nonce
  })),e=>e.status===403);
  assert.equal(checked,0);
});
