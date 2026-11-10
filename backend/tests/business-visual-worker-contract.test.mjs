import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const routes=readFileSync(new URL("../business_visual_routes.py",import.meta.url),"utf8");
const jobs=readFileSync(new URL("../business_visual_jobs.py",import.meta.url),"utf8");
const worker=readFileSync(new URL("../business_visual_worker.py",import.meta.url),"utf8");
const service=readFileSync(new URL("../deploy/systemd/clippr-business-visual.service.template",import.meta.url),"utf8");
test("Business visual API does not spawn work on HTTP worker threads",()=>{
  assert.match(routes,/claim=reserve_job\(/);
  assert.doesNotMatch(routes,/EXECUTOR\.submit|scan_job\(/);
  assert.match(worker,/claim_next_visual\(/);
  assert.match(worker,/lease_token=item\["lease_token"\]/);
});
test("visual worker service is isolated and disabled by default",()=>{
  assert.match(worker,/CLIPPR_BUSINESS_VISUAL_WORKER/);
  assert.match(worker,/WorkerUnavailable\("Business visual worker flag is OFF"\)/);
  assert.match(service,/^User=clippr-worker$/m);
  assert.match(service,/^NoNewPrivileges=true$/m);
  assert.match(service,/^ExecStartPre=.*--check-config$/m);
  assert.match(service,/^ReadWritePaths=.*business_visual.*business_sources$/m);
  assert.match(service,/DO NOT INSTALL OR ENABLE/);
});
test("stale workers cannot finish scans or mint source usage",()=>{
  assert.match(jobs,/AND lease_token=\?/);
  assert.match(jobs,/claim_next_visual/);
  assert.match(jobs,/cursor\.rowcount==1 and status=="done"/);
  assert.match(jobs,/INSERT OR IGNORE INTO visual_usage_candidates/);
});
