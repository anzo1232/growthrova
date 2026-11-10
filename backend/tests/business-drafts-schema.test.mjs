import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const sql=readFileSync(new URL("../supabase/migrations/20261017211000_business_campaign_drafts.sql",import.meta.url),"utf8");
const script=readFileSync(new URL("../supabase/tests/business_campaign_drafts_rls_rollback.sql",import.meta.url),"utf8");
const proxy=readFileSync(new URL("../business_campaign_supabase.py",import.meta.url),"utf8");
const routes=readFileSync(new URL("../business_campaign_store_routes.py",import.meta.url),"utf8");
test("new campaigns table has RLS and restricted update fields",()=>{
  assert.match(sql,/CREATE TABLE public\.business_campaign_drafts/);
  assert.match(sql,/ENABLE ROW LEVEL SECURITY/);
  assert.match(sql,/REVOKE ALL ON public\.business_campaign_drafts FROM PUBLIC, anon, authenticated/);
  assert.match(sql,/GRANT UPDATE\(name,goal,brand_id,scenes,notes,revision,updated_at\)/);
  assert.doesNotMatch(sql,/GRANT UPDATE\(.*owner_id/);
  assert.doesNotMatch(sql,/GRANT UPDATE\(.*organisation_id/);
  assert.match(sql,/jsonb_array_length\(scenes\) <= 24/);
});
test("brand kit for saved draft must belong to same owner organisation",()=>{
  assert.match(sql,/business_drafts_insert/);
  assert.match(sql,/business_drafts_update/);
  assert.match(sql,/b\.organisation_id=organisation_id/);
  assert.match(sql,/owner_id = \(SELECT auth\.uid\(\)\)/);
});
test("revision-based compare and set is server side, JWT scoped",()=>{
  assert.match(proxy,/"revision":"eq\."\+str\(revision\)/);
  assert.match(proxy,/"owner_id":"eq\."\+owner/);
  assert.match(proxy,/Bearer "\+bearer/);
  assert.match(proxy,/if not records:/);
  assert.doesNotMatch(proxy,/service_role|SUPABASE_SERVICE_ROLE/);
  assert.match(routes,/CampaignSupabase\(deps\.supabase_url,deps\.supabase_anon_key,bearer\)/);
});
test("real two-account staging test is transactional and rolls back",()=>{
  assert.match(script,/^BEGIN;/m);
  assert.match(script,/B can read A draft/);
  assert.match(script,/B deleted A draft/);
  assert.match(script,/A attached B brand/);
  assert.match(script,/ROLLBACK;\s*$/);
});
