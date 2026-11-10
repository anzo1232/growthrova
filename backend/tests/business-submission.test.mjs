import test from "node:test";
import assert from "node:assert/strict";
import {admissionFor,confirmAdmission,businessSourceFingerprint,forgetAdmission} from "../src/lib/businessSubmissionState.mjs";

function store(){
  const entries=new Map();
  return {getItem:k=>entries.get(k)||null,setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)};
}
const a={userId:"account-A",organisationId:"orgA",url:"https://youtube.com/watch?v=example",goal:"awareness",approvedOffer:""};

test("lost HTTP response reuses the exact same admission key on retry",()=>{
  const storage=store();
  const first=admissionFor(storage,a,{now:1000,uuid:()=>"11111111-1111-4111-8111-111111111111"});
  const second=admissionFor(storage,a,{now:2200,uuid:()=>{throw new Error("unexpected duplicate job key")}});
  assert.equal(first.key,second.key);
  assert.equal(second.reused,true);
  assert.equal(second.sessionId,null);
  assert.ok(confirmAdmission(storage,a.userId,first.key,"a".repeat(32)));
  const third=admissionFor(storage,a,{now:5000});
  assert.equal(third.sessionId,"a".repeat(32));
  forgetAdmission(storage,a.userId);
});

test("different accounts, campaigns or 24-hour expiry get new admission keys",()=>{
  const storage=store();
  let n=0;
  const opts=(now)=>({now,uuid:()=>String(++n).padStart(32,"f")});
  const one=admissionFor(storage,a,opts(3000)).key;
  const two=admissionFor(storage,{...a,userId:"account-B"},opts(4000)).key;
  const three=admissionFor(storage,{...a,goal:"bookings"},opts(5000)).key;
  const four=admissionFor(storage,{...a,goal:"bookings"},opts(30*60*60*1000)).key;
  assert.equal(new Set([one,two,three,four]).size,4);
});

test("an admission cannot be assigned a mismatched job response",()=>{
  const storage=store();
  const ticket=admissionFor(storage,{...a,userId:"account-C"},{now:30000,uuid:()=>"c".repeat(32)});
  assert.equal(confirmAdmission(storage,"account-C","forged-key","a".repeat(32)),false);
  assert.equal(confirmAdmission(storage,"account-C",ticket.key,"../other-user"),false);
});

test("storage unavailability does not block in-tab repeat-safety",()=>{
  const storage={getItem:()=>{throw new Error("blocked");},setItem:()=>{throw new Error("blocked");}};
  const first=admissionFor(storage,{...a,userId:"account-D"},{now:1,uuid:()=>"d".repeat(32)});
  const second=admissionFor(storage,{...a,userId:"account-D"},{now:2,uuid:()=>{throw Error("new key not expected")}});
  assert.equal(first.key,second.key);
});
