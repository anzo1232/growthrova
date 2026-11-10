import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const demo = readFileSync(new URL("../src/BusinessMediaDemo.jsx", import.meta.url),"utf8");
const privateStudio = readFileSync(new URL("../src/BusinessMediaStudio.jsx", import.meta.url),"utf8");
const shared = readFileSync(new URL("../src/BusinessStudioDesign.jsx", import.meta.url),"utf8");
const sharedStyle = readFileSync(new URL("../src/BusinessStudioDesign.css", import.meta.url),"utf8");

test("login-free demo is strictly local and keeps private workspace separate",()=>{
  assert.match(privateStudio,/import\.meta\.env\.DEV &&/);
  assert.match(privateStudio,/URLSearchParams\(window\.location\.search\)/);
  assert.match(privateStudio,/localDemo \? <BusinessMediaDemo\/> : <BusinessMediaStudioPrivate\/>/);
  assert.match(demo,/INTERACTIVE DESIGN DEMO|SAMPLE|demo/);
  assert.match(shared,/Preview mode — uploads are disabled/);
  assert.match(demo,/<StudioUploadBox demo\/>/);
  assert.doesNotMatch(demo,/supabase\.auth|getSession|fetch\(|uploadBusinessVideo|prepareVisualPack/);
});
test("signed-out user can open the demo without authenticating",()=>{
  assert.match(privateStudio,/to="\/business\/media\?demo=1"/);
  assert.match(privateStudio,/Explore interactive demo/);
});
test("creative components are shared, not separate demo-only mockups",()=>{
  for(const symbol of ["StudioHero","StudioBrandBar","StudioSectionHeader",
    "StudioUploadBox","StudioSourceCard","StudioOutputCard"]){
    assert.match(demo,new RegExp("<"+symbol));
    assert.match(privateStudio,new RegExp("<"+symbol));
  }
});
test("demo controls reflect selection and brand direction state",()=>{
  assert.match(demo,/setSelected\(/);
  assert.match(demo,/setLookIndex\(/);
  assert.match(demo,/setShowPack\(/);
  assert.match(demo,/disabled=\{!selectedCount\}/);
});
test("real previews must represent real footage when available",()=>{
  assert.match(shared,/function useLocalPoster\(file, seconds/);
  assert.match(shared,/URL\.createObjectURL\(file\)/);
  assert.match(shared,/URL\.revokeObjectURL\(fileURL\)/);
  assert.match(shared,/video\.videoWidth/);
  assert.match(shared,/previewUrl\?<video/);
  assert.match(shared,/Preview loads when requested/);
});
test("private workflows still run the original owner-scoped routes",()=>{
  for(const name of ["uploadBusinessVideo","startVisualScan","prepareVisualPack",
    "readVisualScan","getToken","chooseOrg","watchVisual"]){
    assert.ok(privateStudio.includes(name),"Missing private workflow: "+name);
  }
});
test("creative polish supports mobile and reduced motion",()=>{
  assert.match(sharedStyle,/@media\(max-width:600px\)/);
  assert.match(sharedStyle,/@media\(prefers-reduced-motion:reduce\)/);
  assert.match(sharedStyle,/cbst-source-grid/);
  assert.match(sharedStyle,/cbst-output-grid/);
});
