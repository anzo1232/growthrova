import test from "node:test";
import assert from "node:assert/strict";
import {readdir, readFile} from "node:fs/promises";
import {transform} from "esbuild";

// A normal index.html build omits the separate local pilot. Compile every
// Business component so an unreachable entry cannot hide a broken UI.
const src = new URL("../src/", import.meta.url);
const files = (await readdir(src)).filter(name =>
  (name.startsWith("Business") || name === "business-pilot-main.jsx" || name === "business-agency-main.jsx") && name.endsWith(".jsx"));
assert.ok(files.includes("BusinessLocalPilot.jsx"));
for (const file of files) {
  test(`Business component compiles: ${file}`, async () => {
    await transform(await readFile(new URL(file, src), "utf8"), {
      loader: "jsx", jsx: "automatic", sourcefile: file, logLevel: "silent",
    });
  });
}
