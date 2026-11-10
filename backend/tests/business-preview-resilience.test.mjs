import test from "node:test";
import assert from "node:assert/strict";
import {resolveBusinessPreview} from "../src/lib/businessPreviewResilience.mjs";
const pause=async()=>{};

test("already rendered preview is returned without polling or rejoining",async()=>{
  let started=0;
  const result=await resolveBusinessPreview({
    start:async()=>{started++;return {preview_url:"https://example.com/p.mp4"};},
    read:async()=>{throw Error("should not poll");},sleep:pause
  });
  assert.equal(result.url,"https://example.com/p.mp4");
  assert.equal(started,1);
});
test("lost backend preview status ID re-joins only once, same source request",async()=>{
  let started=0,checks=0;
  const result=await resolveBusinessPreview({
    start:async()=>({status:"running",preview_id:"job-"+(++started)}),
    read:async id=>{
      checks++;
      if(id==="job-1")throw Object.assign(new Error("expired preview"),{code:"http_404"});
      return {status:"done",preview_url:"https://example.com/rejoined.mp4"};
    },sleep:pause
  });
  assert.equal(started,2);
  assert.equal(checks,2);
  assert.equal(result.status,"ready");
});
test("second expired preview does not rejoin indefinitely",async()=>{
  let started=0;
  await assert.rejects(resolveBusinessPreview({
    start:async()=>({preview_id:"job-"+(++started),status:"running"}),
    read:async()=>{throw Object.assign(new Error("expired"),{code:"http_404"});},
    sleep:pause,maxChecks:7
  }));
  assert.equal(started,2);
});
test("non-expiry processing failure is not retried",async()=>{
  let started=0;
  await assert.rejects(resolveBusinessPreview({
    start:async()=>{started++;return {status:"running",preview_id:"j"};},
    read:async()=>({status:"error",error:"Source video is corrupt"}),
    sleep:pause
  }),/Source video is corrupt/);
  assert.equal(started,1);
});
test("stale campaign stops polling and cannot populate new card",async()=>{
  let current=true,readCalls=0;
  const result=await resolveBusinessPreview({
    start:async()=>({status:"running",preview_id:"j"}),
    read:async()=>{readCalls++;return {status:"done",preview_url:"https://example.com/stale.mp4"};},
    sleep:async()=>{current=false;},
    isCurrent:()=>current
  });
  assert.equal(result.status,"cancelled");
  assert.equal(readCalls,0);
});
test("transient polling failure resumes without creating a second preview",async()=>{
  let started=0,checked=0;
  const result=await resolveBusinessPreview({
    start:async()=>{started++;return {preview_id:"original"};},
    read:async()=>{checked++;if(checked<3)throw Error("temporary network");return {status:"done",preview_url:"https://example.com/ready.mp4"};},
    sleep:pause
  });
  assert.equal(started,1);
  assert.equal(checked,3);
  assert.equal(result.status,"ready");
});
