import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {evaluate,ROOT} from "../scripts/business_release_gate.mjs";
import {join} from "node:path";
const source=JSON.parse(readFileSync(join(ROOT,"docs/business-risk-evidence.json"),"utf8"));
const history=source.retrospective_commits.map(c=>c.sha);
const clone=()=>structuredClone(source);
test("all reviewed Business commits have risk mapping and evidence",()=>{
  const result=evaluate(source,{phase:"dev",currentHistory:history});
  assert.equal(result.ok,true,JSON.stringify(result.errors));
  assert.equal(result.mapped_commits,14);
  assert.equal(result.risks,14);
  assert.equal(result.warnings.length,1);
});
test("unreviewed or undocumented commits fail the development gate",()=>{
  const result=evaluate(source,{phase:"dev",currentHistory:[...history,"deadbee"]});
  assert.equal(result.ok,false);
  assert.match(result.errors.join(" "),/Unreviewed retrospective commit/);
});
test("missing evidence file and changed risk severity fail closed",()=>{
  const bad=clone();
  bad.risk_definitions[0].evidence.push("docs/nonexistent-proof.txt");
  bad.risk_definitions[0].severity="unknown";
  const result=evaluate(bad,{currentHistory:history});
  assert.equal(result.ok,false);
  assert.match(result.errors.join(" "),/Evidence not found/);
  assert.match(result.errors.join(" "),/Invalid severity/);
});
test("new commits require traceable Risk-ID trailers",()=>{
  const no=evaluate(source,{currentHistory:history,
    nextCommits:[...source.trailer_exceptions.map(x=>({sha:x.sha.slice(0,7),full_sha:x.sha,message:"Historic audited fix"})),{sha:"abc1234",message:"Fix backend without explaining risk"}]});
  assert.equal(no.ok,false);
  assert.match(no.errors.join(" "),/missing Risk-ID trailer/);
  const yes=evaluate(source,{currentHistory:history,
    nextCommits:[...source.trailer_exceptions.map(x=>({sha:x.sha.slice(0,7),full_sha:x.sha,message:"Historic audited fix"})),{sha:"abc1234",message:"Fix auth and upload risk\n\nRisk-ID: AUTH,TENANT,R2"}]});
  assert.equal(yes.ok,true,yes.errors.join("; "));
});
test("a status label alone cannot fake real staging or production evidence",()=>{
  const forged=clone();
  forged.release_approved=true;
  for(const risk of forged.risk_definitions)risk.status="production-verified";
  const result=evaluate(forged,{phase:"production",currentHistory:history});
  assert.equal(result.ok,false);
  assert.match(result.errors.join(" "),/Missing real staging API attestation/);
  assert.match(result.errors.join(" "),/Missing production sign-off evidence/);
});
test("production gate refuses a falsely marked release approved without evidence",()=>{
  const bad=clone();
  bad.release_approved=true;
  const result=evaluate(bad,{phase:"production",currentHistory:history});
  assert.equal(result.ok,false);
  assert.match(result.errors.join(" "),/Critical risk not production-verified/);
});
test("staging gate never accepts DB-only RLS tests as real Auth/R2",()=>{
  const r=evaluate(source,{phase:"staging",currentHistory:history});
  assert.equal(r.ok,false);
  assert.match(r.errors.join(" "),/Real staging API exit test outstanding: AUTH/);
  assert.match(r.errors.join(" "),/Real staging API exit test outstanding: R2/);
});

test("risk trailer exceptions require the exact reviewed full SHA",()=>{
  const historical=source.trailer_exceptions.map(x=>({
    sha:x.sha.slice(0,7),full_sha:x.sha,message:"Audited past missing trailer",
  }));
  assert.equal(evaluate(source,{currentHistory:history,nextCommits:historical}).ok,true);
  const tampered=[...historical];
  tampered[0]={...tampered[0],full_sha:"f".repeat(40)};
  const denied=evaluate(source,{currentHistory:history,nextCommits:tampered});
  assert.equal(denied.ok,false);
  assert.match(denied.errors.join(" "),/Stale trailer exception|missing Risk-ID trailer/);
});

test("merged connected product commits have dated exact-SHA risk reviews",()=>{
  for(const sha of [
    "8e576a16bf93962ddc61ff83d2ef1c1bd221a458",
    "d4caef41d1ed0c0cc25cc2efe39b69c79a035a93",
  ]){
    const review=source.trailer_exceptions.find(entry=>entry.sha===sha);
    assert.ok(review,`Missing connected-product risk review for ${sha}`);
    assert.equal(review.reviewed_at,"2026-11-04");
    for(const id of ["AUTH","TENANT","CAMPAIGNS","UX"])
      assert.ok(review.risk_ids.includes(id),`Missing ${id} mapping for ${sha}`);
    assert.ok(review.reason.includes("docs/CONNECTED_PRODUCT_ACCEPTANCE_20261104.md"));
  }
});
