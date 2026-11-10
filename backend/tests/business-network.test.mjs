import test from "node:test";
import assert from "node:assert/strict";
import { guardedFetch } from "../src/lib/businessNetwork.mjs";

test("finite deadline converts stalled fetch to recoverable timeout", async()=>{
  const original=globalThis.fetch;
  let abortSeen=false;
  globalThis.fetch=(url,opts)=>new Promise((resolve,reject)=>{
    opts.signal.addEventListener("abort",()=>{
      abortSeen=true;
      reject(Object.assign(new Error("aborted"),{name:"AbortError"}));
    },{once:true});
  });
  try {
    await assert.rejects(guardedFetch("https://api.example.invalid/status",{},{
      timeoutMs:1000
    }),e=>e.code==="request_timeout" && /existing job/.test(e.message));
    assert.equal(abortSeen,true);
  }finally{globalThis.fetch=original;}
});
test("explicit user cancel must not be misreported as timeout",async()=>{
  const previous=globalThis.fetch;
  let calls=0;
  globalThis.fetch=()=>{calls++;return Promise.resolve(new Response("",{status:200}));};
  try {
    const controller=new AbortController();
    controller.abort();
    await assert.rejects(guardedFetch("https://api.example.invalid/status",
      {signal:controller.signal}),e=>e.code==="request_cancelled");
    assert.equal(calls,0);
  }finally{globalThis.fetch=previous;}
});
test("fast successful request returns original response without altering it",async()=>{
  const previous=globalThis.fetch;
  let abortedAfter=false;
  globalThis.fetch=(url,options)=>{
    options.signal.addEventListener("abort",()=>{abortedAfter=true;});
    return Promise.resolve(new Response(JSON.stringify({ready:true}),{status:200}));
  };
  try {
    const res=await guardedFetch("https://api.example.invalid/status");
    assert.equal(res.status,200);
    assert.equal((await res.json()).ready,true);
    assert.equal(abortedAfter,false);
  }finally{globalThis.fetch=previous;}
});
test("absurd request deadlines are rejected",async()=>{
  await assert.rejects(guardedFetch("about:blank",{}, {timeoutMs:0}),TypeError);
  await assert.rejects(guardedFetch("about:blank",{}, {timeoutMs:999999}),TypeError);
});
