import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const page=readFileSync(new URL("../public/business-staging-confirm.html",import.meta.url),"utf8");
test("staging callback handles consumed OTP without falsely claiming verification",()=>{
  assert.match(page,/otp_expired/);
  assert.match(page,/already used/);
  assert.match(page,/might already be verified/);
  assert.doesNotMatch(page,/Your account is verified|Verified successfully/);
});
test("confirmation URL fragments are removed immediately without logging tokens",()=>{
  assert.match(page,/history\.replaceState\(null, "", location\.pathname\)/);
  assert.match(page,/hash\.get\("access_token"\)/);
  assert.doesNotMatch(page,/localStorage|sessionStorage|console\.log/);
});
test("staging-only callback never redirects token to live Clippr or third parties",()=>{
  assert.match(page,/zbncuxizmjinexifcshe\/auth\/users/);
  assert.doesNotMatch(page,/location\.href\s*=/);
  assert.doesNotMatch(page,/https:\/\/(?:www\.)?clippr\.org/);
});
