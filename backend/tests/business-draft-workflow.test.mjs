import test from "node:test";
import assert from "node:assert/strict";
import {scenesFromPack,cleanDraftScenes,draftSnapshot,montageScenes,
  validMontageUrl} from "../src/lib/businessDraftWorkflow.mjs";
const a="a".repeat(32),b="b".repeat(32);
const inputs=[
  {source_id:a,start_s:0,end_s:8,review_status:"approved",note:"Review"},
  {source_id:b,start_s:10,end_s:19,review_status:"approved",note:"Review"}
];
const ids=inputs.map(x=>x.source_id+":"+x.start_s.toFixed(2)+":"+x.end_s.toFixed(2));
test("scene pack defaults to human-review-required and strips video links",()=>{
  const source={clips:[
    {...inputs[0],video_url:"r2://private",review_status:"approved"},
    {...inputs[1],access_token:"secret",review_status:"approved"}
  ]};
  const result=scenesFromPack(source);
  assert.equal(result.length,2);
  assert.ok(result.every(x=>x.review_status==="draft"));
  assert.doesNotMatch(JSON.stringify(result),/r2:|secret/);
});
test("draft snapshot is stable and excludes signed links",()=>{
  const payload={name:"  Cafe launch  ",goal:"awareness",notes:"Manual review",
    brand_id:null,scenes:inputs.map(x=>({...x,video_url:"r2://private"}))};
  const json=draftSnapshot(payload);
  assert.match(json,/Cafe launch/);
  assert.doesNotMatch(json,/r2:/);
});
test("montage requires selected approved scenes with exact limits",()=>{
  const result=montageScenes(inputs,ids);
  assert.equal(result.length,2);
  assert.equal(result[0].start_s,0);
  assert.equal("review_status" in result[0],false);
  assert.throws(()=>montageScenes(inputs,[ids[0]]),/two to six/);
  assert.throws(()=>montageScenes([{...inputs[0],review_status:"draft"},inputs[1]],ids),/explicit approval/);
  assert.throws(()=>montageScenes([{...inputs[0],end_s:34},inputs[1]],
    [a+":0.00:34.00",ids[1]]),/3 and 30/);
});
test("duplicate scenes, unsafe links and bad times fail closed",()=>{
  assert.throws(()=>cleanDraftScenes([inputs[0],inputs[0]]),/duplicate/);
  assert.throws(()=>cleanDraftScenes([{...inputs[0],start_s:-5,end_s:-1}]),/invalid/);
  assert.equal(validMontageUrl("javascript:alert(1)"),"");
  assert.equal(validMontageUrl("http://example.com/video.mp4"),"");
  assert.equal(validMontageUrl("https://cdn.example.com/video.mp4"),"https://cdn.example.com/video.mp4");
});
