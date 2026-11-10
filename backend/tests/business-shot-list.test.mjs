import test from "node:test";
import assert from "node:assert/strict";
import {buildBusinessShotList,clipIdentity} from "../src/lib/businessShotList.mjs";
const clip={source_id:"s1",source_name:"footage.mp4",
  start_s:1.25,end_s:15.5,title:"Chef explains the menu",
  why:"Human review required"};
test("shot list contains only descriptive fields and precise timestamps",()=>{
  const result=buildBusinessShotList({brandName:"Example Café",clips:[clip]});
  assert.match(result,/Example Café/);
  assert.match(result,/footage\.mp4/);
  assert.match(result,/1\.25/);
  assert.match(result,/15\.5/);
  assert.match(result,/14\.25/);
  assert.match(result,/human approval required/);
  assert.ok(result.startsWith("\ufeff"));
  assert.equal((result.match(/\r\n/g)||[]).length,2);
});
test("dangerous CSV formulas escaped and source URLs never emitted",()=>{
  const result=buildBusinessShotList({brandName:"=1+2",clips:[{
    ...clip,source_name:"@SUM(1,1)",title:"-IMPORTXML(\"x\")",
    why:"+cmd|' /C calc",video_url:"r2://business/private/key",
    token:"sensitive-bearer"
  }]});
  assert.match(result,/'=1\+2/);
  assert.match(result,/'@SUM\(1,1\)/);
  assert.match(result,/'-IMPORTXML/);
  assert.match(result,/'\+cmd/);
  assert.doesNotMatch(result,/r2:\/\/business|sensitive-bearer/);
  assert.match(result,/""x""/);
});
test("invalid, duplicate and oversized shot lists rejected",()=>{
  assert.equal(clipIdentity(clip),"s1:1.25:15.50");
  assert.throws(()=>buildBusinessShotList({clips:[]}),/Select between/);
  assert.throws(()=>buildBusinessShotList({clips:[clip,clip]}),/Duplicate/);
  assert.throws(()=>buildBusinessShotList({clips:[{...clip,start_s:-1}]}),/Duplicate or invalid/);
  assert.throws(()=>buildBusinessShotList({clips:[{...clip,end_s:999}]}),/Invalid scene range/);
});

test("editorial export explains possible use without inventing measured outcomes",()=>{
 const csv=buildBusinessShotList({brandName:"Demo",clips:[{...clip,editorial:{
  objective:"Encourage bookings",proposedUse:"Reels for restaurant discovery",
  intendedBenefit:"Show an authentic food experience",
  reviewAction:"Verify customer consent and booking CTA"}}]});
 for(const entry of ["Marketing objective","Potential benefit","Evidence status",
   "Encourage bookings","Reels for restaurant discovery","Editorial suggestion - unverified"])
   assert.ok(csv.includes(entry),entry);
 assert.doesNotMatch(csv,/guaranteed conversions|confirmed uplift/i);
});
