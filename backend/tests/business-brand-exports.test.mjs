import test from "node:test";
import assert from "node:assert/strict";
import {validLogoFile} from "../src/lib/businessLogoClient.mjs";
import {readFileSync} from "node:fs";

test("Only small supported raster images are accepted",()=>{
  assert.equal(validLogoFile({type:"image/png",size:1024}),true);
  assert.equal(validLogoFile({type:"image/webp",size:1500}),true);
  assert.equal(validLogoFile({type:"image/svg+xml",size:1024}),false);
  assert.equal(validLogoFile({type:"image/png",size:3_000_000}),false);
  assert.equal(validLogoFile({type:"image/png",size:50}),false);
});
test("Business exports only after the original Clippr export completes",()=>{
  const frontend=readFileSync(new URL("../src/BusinessCampaign.jsx",import.meta.url),"utf8");
  const backend=readFileSync(new URL("../business_brand_exports.py",import.meta.url),"utf8");
  assert.match(frontend,/requestBrandedExport\(token/);
  assert.match(frontend,/source_export_id:response.export_id/);
  assert.match(backend,/original.get\("status"\) != "done"/);
  assert.match(backend,/original.get\("user_id"\) != user\["id"\]/);
  assert.match(backend,/original.get\("sid"\) != data.get\("session_id"\)/);
});
