import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const migration=readFileSync(new URL("../supabase/migrations/20261017191500_business_foundation.sql",import.meta.url),"utf8");
const checks=readFileSync(new URL("../supabase/tests/business_rls_staging.psql",import.meta.url),"utf8");
const transactionalChecks=readFileSync(new URL("../supabase/tests/business_rls_rollback_fixtures.sql",import.meta.url),"utf8");
const repo=readFileSync(new URL("../src/lib/businessRepository.mjs",import.meta.url),"utf8");
const api=readFileSync(new URL("../business_campaign_routes.py",import.meta.url),"utf8");

test("versioned migration contains only the new business tables and RLS, not creator mutations",()=>{
  assert.match(migration,/CREATE TABLE public\.business_organisations/);
  assert.match(migration,/CREATE TABLE public\.business_brand_kits/);
  assert.equal((migration.match(/CREATE TABLE public\./g)||[]).length,2);
  for(const name of ["business_organisations","business_brand_kits"]){
    assert.ok(migration.includes("ALTER TABLE public."+name+" ENABLE ROW LEVEL SECURITY"),name);
    assert.ok(migration.includes("REVOKE ALL ON public."+name+" FROM PUBLIC, anon, authenticated"),name);
  }
  assert.doesNotMatch(migration,/(?:ALTER|UPDATE|DELETE FROM)\s+(?:auth\.users|public\.jobs|public\.projects)/i);
  assert.match(migration,/BEGIN;/);
  assert.match(migration,/COMMIT;/);
});
test("anonymous users cannot access brand records and organisation owners cannot be reassigned",()=>{
  assert.match(migration,/GRANT UPDATE \(name, industry, primary_goal, website, updated_at\)/);
  assert.match(migration,/GRANT UPDATE \(name, primary_color, secondary_color, font_style, default_cta, logo_r2_key, updated_at\)/);
  assert.doesNotMatch(migration,/GRANT UPDATE\s+ON public\.business_organisations/i);
  assert.doesNotMatch(migration,/GRANT UPDATE\s+ON public\.business_brand_kits/i);
  assert.match(migration,/owner_id = \(SELECT auth\.uid\(\)\)/);
  assert.match(migration,/WITH CHECK/);
  assert.match(migration,/business\/brands\//);
});
test("backend and frontend query fields exist in the migration",()=>{
  for(const col of ["id","owner_id","organisation_id","name","industry","primary_goal","website","created_at","primary_color","secondary_color","font_style","default_cta","logo_r2_key"]){
    assert.ok(migration.includes(col),"Missing column contract "+col);
  }
  assert.match(repo,/client\.from\("business_organisations"\)/);
  assert.match(repo,/client\.from\("business_brand_kits"\)/);
  assert.match(api,/business_organisations/);
  assert.match(api,/business_brand_kits/);
});
test("staging RLS script explicitly requires two known users and rolls back",()=>{
  assert.match(checks,/STAGING ONLY/);
  assert.ok(checks.includes(":{?user_a}"));
  assert.ok(checks.includes(":{?user_b}"));
  assert.match(checks,/SET LOCAL ROLE authenticated/);
  assert.match(checks,/request\.jwt\.claim\.sub/);
  assert.match(checks,/Cross-tenant brand insert was permitted/);
  assert.match(checks,/Ownership spoofing was permitted/);
  assert.match(checks,/Owner B can read Owner A brand/);
  assert.match(checks,/ROLLBACK;/);
});

test("repeatable staging RLS fixture cannot leave test customers behind",()=>{
  assert.match(transactionalChecks,/STAGING ONLY/);
  assert.match(transactionalChecks,/^BEGIN;/m);
  assert.match(transactionalChecks,/ROLLBACK;\s*$/);
  assert.match(transactionalChecks,/SET LOCAL ROLE authenticated/);
  assert.match(transactionalChecks,/request\.jwt\.claim\.sub/);
  assert.match(transactionalChecks,/B can read A organisation/);
  assert.match(transactionalChecks,/B forged A owner/);
  assert.match(transactionalChecks,/A can read B brand/);
  assert.match(transactionalChecks,/example\.invalid/);
});
