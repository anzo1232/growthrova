import test from "node:test";
import assert from "node:assert/strict";
import {reviewCreative} from "../src/lib/businessCreativeReview.mjs";

const approved = () => ({assetUrl:"https://media.example.org/creative.png",
  brandVerified:true, claimsVerified:true, approved:true,
  approvedAt:"2026-10-18T12:00:00Z", approvedBy:"test-owner",
  copyDraft:"Approved offer", reviewStatus:"approved_for_manual_export", published:false});

test("changing copy revokes prior approval and the old claims check", () => {
  const original=approved();
  const changed=reviewCreative(original,{type:"edit",copy:"A different offer"});
  assert.equal(changed.approved,false);
  assert.equal(changed.claimsVerified,false);
  assert.equal(changed.approvedAt,null);
  assert.equal(changed.approvedBy,null);
  assert.equal(changed.reviewStatus,"needs_review");
  assert.equal(changed.published,false);
  assert.equal(original.approved,true,"must not mutate the previous revision");
  assert.throws(()=>reviewCreative(changed,{type:"approve"}));
});

test("editing accepts empty and one-character drafts without crashing an input", () => {
  for(const copy of ["", "A", "Book "]) {
    const result=reviewCreative(approved(),{type:"edit",copy});
    assert.equal(result.copyDraft,copy);
    assert.equal(result.approved,false);
  }
  assert.throws(()=>reviewCreative(approved(),{type:"edit",copy:"x".repeat(401)}));
});

test("approval rejects unsafe asset URLs", () => {
  for(const assetUrl of ["javascript:alert(1)","data:image/png;base64,QQ==",
    "http://media.example.org/a.png","https://user:pass@example.org/a.png","not a URL"])
    assert.throws(()=>reviewCreative({...approved(),assetUrl},{type:"approve"}),assetUrl);
});

test("approval requires literal verification booleans", () => {
  for(const value of ["false", "true", 1, {}, []]) {
    assert.throws(()=>reviewCreative({...approved(),claimsVerified:value},{type:"approve"}));
    assert.throws(()=>reviewCreative({...approved(),brandVerified:value},{type:"approve"}));
  }
});

test("regeneration invalidates approval and cannot approve the old asset", () => {
  const next=reviewCreative(approved(),{type:"regenerate"});
  assert.equal(next.approved,false);
  assert.equal(next.claimsVerified,false);
  assert.equal(next.approvedAt,null);
  assert.equal(next.regenerationRequested,true);
  assert.equal(next.published,false);
  assert.throws(()=>reviewCreative({...next,claimsVerified:true,brandVerified:true},{type:"approve"}));
});

test("valid manual export approval never publishes or grants spending", () => {
  const result=reviewCreative(approved(),{type:"approve"});
  assert.equal(result.reviewStatus,"approved_for_manual_export");
  assert.equal(result.published,false);
  assert.equal(result.canSpend,undefined);
});
