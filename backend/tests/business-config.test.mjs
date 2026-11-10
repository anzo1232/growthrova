import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BUSINESS_INDUSTRIES, BUSINESS_GOALS } from "../src/lib/businessConfig.mjs";

test("business onboarding options are valid and unique", () => {
  for (const choices of [BUSINESS_INDUSTRIES, BUSINESS_GOALS]) {
    assert.ok(choices.length >= 5);
    assert.equal(new Set(choices.map(x => x.id)).size, choices.length);
    for (const item of choices) {
      assert.match(item.id, /^[a-z_]+$/);
      assert.ok(item.label.trim().length >= 5);
      assert.ok((item.description || item.benefit).trim().length >= 15);
    }
  }
});
test("business route is hidden unless the preview flag is enabled", () => {
  const main = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.match(main, /VITE_BUSINESS_PREVIEW === "1"/);
  assert.match(main, /BUSINESS_PREVIEW_ENABLED && <Route path="\/business"/);
});
test("preview is honest about what is not functional yet", () => {
  const page = readFileSync(new URL("../src/BusinessLanding.jsx", import.meta.url), "utf8");
  assert.match(page, /business campaigns, storage and billing are not enabled yet/);
  assert.match(page, /does not submit or save data or generate clips yet/);
});

test("public navigation exposes business entry only with feature flag", () => {
  const landing = readFileSync(new URL("../src/Landing.jsx", import.meta.url), "utf8");
  assert.equal((landing.match(/VITE_BUSINESS_PREVIEW === "1" && <a href="\/business"/g) || []).length, 2);
});
