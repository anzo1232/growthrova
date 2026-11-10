import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {BRAND_TEMPLATES,contrastRatio,readableColour,brandContrastWarning,creativeLayout} from "../src/lib/businessBrandSafety.mjs";
import {makeDetectionBrief,validBusinessVideoUrl} from "../src/lib/businessCampaignClient.mjs";

test("brand colors have predictable WCAG contrast and readable fallback",()=>{
  assert.ok(contrastRatio("#FFFFFF","#111111")>15);
  assert.equal(contrastRatio("#FFFFFF","#FFFFFF"),1);
  assert.equal(readableColour("#FFFFFF"),"#111111");
  assert.equal(readableColour("#111111"),"#FFFFFF");
  assert.match(brandContrastWarning("#FFFEEE","#FFFFFF"),/enough contrast/);
  assert.equal(brandContrastWarning("#111111","#FFFFFF"),"");
  assert.equal(BRAND_TEMPLATES.length,4);
  assert.equal(creativeLayout("not-a-template").id,"modern");
});

test("detection briefs include the business goal but not invented offers",()=>{
  const base={name:" Acme Agency",industry:"agency",goal:"enquiries"};
  const brief=makeDetectionBrief(base);
  assert.match(brief,/Acme Agency/);
  assert.match(brief,/relevant enquiries/);
  assert.doesNotMatch(brief,/50% off/);
  assert.throws(()=>makeDetectionBrief({...base,goal:"offers"}),/approved offer/);
  assert.match(makeDetectionBrief({...base,goal:"offers",approvedOffer:"Free first consultation"}),/Free first consultation/);
});

test("business Campaign Studio uses existing analyse, preview and export paths, with no automatic captions",()=>{
  const api=readFileSync(new URL("../src/lib/businessCampaignClient.mjs",import.meta.url),"utf8");
  const ui=readFileSync(new URL("../src/BusinessCampaign.jsx",import.meta.url),"utf8");
  const route=readFileSync(new URL("../src/main.jsx",import.meta.url),"utf8");
  assert.match(api,/api\/analyse/);
  assert.match(api,/api\/business\/sessions/);
  assert.match(api,/api\/preview-segment/);
  assert.match(api,/api\/export/);
  assert.match(ui,/useState\(false\); \/\/ user-selected, NEVER forced on/);
  assert.match(ui,/Resume checking/);
  assert.match(ui,/runToken\.current/);
  assert.match(ui,/loadedFor===identity/);
  assert.match(route,/BUSINESS_PREVIEW_ENABLED && <Route path="\/business\/campaign"/);
});

test("business only accepts supported video hosts, not deceptive domains or local endpoints",()=>{
  assert.equal(validBusinessVideoUrl("https://www.youtube.com/watch?v=abc"),true);
  assert.equal(validBusinessVideoUrl("https://youtu.be/abc"),true);
  assert.equal(validBusinessVideoUrl("https://clips.twitch.tv/example"),true);
  assert.equal(validBusinessVideoUrl("https://kick.com/example"),true);
  assert.equal(validBusinessVideoUrl("http://youtube.com/video"),false);
  assert.equal(validBusinessVideoUrl("https://youtube.com.evil.example/path"),false);
  assert.equal(validBusinessVideoUrl("https://user:pw@youtube.com/video"),false);
  assert.equal(validBusinessVideoUrl("https://127.0.0.1/admin"),false);
});
