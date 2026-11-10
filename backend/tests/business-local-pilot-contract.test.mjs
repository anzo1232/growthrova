import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync,existsSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {dirname,join} from "node:path";
import {resolvePilotApi} from "../src/lib/businessPilotEndpoint.mjs";
const ROOT=join(dirname(fileURLToPath(import.meta.url)),"..");
const read=p=>readFileSync(join(ROOT,p),"utf8");
const api=read("business_local_pilot.py");
const entry=read("src/business-pilot-main.jsx");
const main=read("src/main.jsx");
const ui=read("src/BusinessLocalPilot.jsx");
test("pilot never loads creator app, payments, analytics or Supabase",()=>{
  assert.doesNotMatch(entry,/^import .*?(?:\bApp\b|supabase|Sentry|stripe|analytics|CookieConsent)/im);
  assert.match(entry,/import\.meta\.env\.DEV/);
  assert.doesNotMatch(main,/BusinessLocalPilot|business\/pilot/);
  assert.match(ui,/const API=resolvePilotApi\(import\.meta\.env\.VITE_BUSINESS_PILOT_API\)/);
  assert.equal(resolvePilotApi(),"http://127.0.0.1:4192");
  assert.throws(()=>resolvePilotApi("https://api.clippr.org"));
});
test("pilot backend is loopback-only with explicit flag and CORS allowlist",()=>{
  assert.match(api,/HOST="127\.0\.0\.1"/);
  assert.match(api,/CLIPPR_LOCAL_PILOT"\)!="1"/);
  assert.match(api,/X-Clippr-Pilot/);
  assert.match(api,/VALID_ORIGINS=frozenset/);
  assert.doesNotMatch(api,/0\.0\.0\.0|stripe\.com|clippr\.org\/api/);
});
test("source limits and destructive actions require confirmation",()=>{
  assert.match(api,/MAX_VIDEO=170\*1024\*1024/);
  assert.match(api,/MAX_TOTAL_STORAGE=650\*1024\*1024/);
  assert.match(api,/MAX_SOURCES=12/);
  assert.match(api,/DELETE LOCAL TESTS/);
  assert.match(ui,/window\.confirm\(/);
  assert.match(ui,/window\.prompt\(/);
});
test("pilot excluded from default Vite production build",()=>{
  const dist=join(ROOT,"dist/business-pilot.html");
  assert.equal(existsSync(dist),false);
  assert.match(read("business-pilot.html"),/business-pilot-main\.jsx/);
});
test("only existing actual FFmpeg algorithms build clips",()=>{
  assert.match(api,/scan_visual_scenes\(source\)/);
  assert.match(api,/build_montage\(windows,/);
  assert.match(api,/LOCAL_PILOT_REAL_FFMPEG_NO_PRODUCTION_SERVICES|LOCAL PILOT/);
});


test("scene review links are short-lived, signed and origin-restricted",()=>{
  assert.match(api,/MEDIA_TTL_SECONDS=15\*60/);
  assert.match(api,/hmac\.new\(MEDIA_SIGNING_SECRET/);
  assert.match(api,/hmac\.compare_digest/);
  assert.match(api,/self\._origin\(\) not in VALID_ORIGINS/);
  assert.match(api,/parse_media_range\(requested,total\)/);
  assert.match(api,/self\.send_header\("Accept-Ranges","bytes"\)/);
  assert.match(api,/Cache-Control","private,no-store"/);
  assert.match(ui,/crossOrigin="anonymous"/);
  assert.match(ui,/onTimeUpdate=\{onPreviewTimeUpdate\}/);
  assert.match(ui,/Watch this window/);
});

test('URL-first agency preview is isolated from live creator entry and excluded from production',()=>{
 const agency=read('src/business-agency-main.jsx');
 assert.match(agency,/import\.meta\.env\.DEV/);
 assert.match(agency,/BusinessAgencyPreview/);
 assert.doesNotMatch(main,/BusinessAgencyPreview|business-agency/);
 assert.equal(existsSync(join(ROOT,'dist/business-agency.html')),false);
});
