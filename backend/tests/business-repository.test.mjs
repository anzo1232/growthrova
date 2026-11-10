import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  BusinessDataError, normalizeOrganisation, normalizeBrand, normalizeWebsite, createBusinessRepository
} from "../src/lib/businessRepository.mjs";

const ALICE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ORG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const BRAND = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const ORG_DETAILS = { name: "  Sitewisers  ", industry: "agency", primary_goal: "enquiries", website: "https://sitewisers.co.uk" };
const BRAND_DETAILS = { name: "Main brand", primary_color: "#aabbcc", secondary_color: "#ffffff", font_style: "modern", default_cta: "Get in touch" };

function clientMock({ user = { id: ALICE }, err = null, response = [] } = {}) {
  const calls = [];
  const client = {
    calls,
    auth: { getUser: async () => ({ data: { user }, error: null }) },
    from(table) {
      calls.push(["from", table]);
      const chain = {
        select(fields) { calls.push(["select", fields]); return this; },
        insert(fields) { calls.push(["insert", fields]); return this; },
        update(fields) { calls.push(["update", fields]); return this; },
        eq(field, value) { calls.push(["eq", field, value]); return this; },
        is(field, value) { calls.push(["is", field, value]); return this; },
        order(field, config) { calls.push(["order", field, config]); return Promise.resolve({ data: response, error: err }); },
        single() { calls.push(["single"]); return Promise.resolve({ data: response, error: err }); },
        maybeSingle() { return Promise.resolve({ data: response, error: err }); },
      };
      return chain;
    }
  };
  return client;
}

test("normalizes safe input, removes extra whitespace, validates brand colours", () => {
  const org = normalizeOrganisation(ORG_DETAILS);
  assert.equal(org.name, "Sitewisers");
  assert.equal(org.website, "https://sitewisers.co.uk/");
  assert.equal(normalizeWebsite(""), null);
  assert.equal(normalizeBrand(BRAND_DETAILS).primary_color, "#AABBCC");
  assert.throws(() => normalizeBrand({ ...BRAND_DETAILS, secondary_color: "#GGGGGG" }), BusinessDataError);
  assert.throws(() => normalizeOrganisation({ ...ORG_DETAILS, industry: "private" }), BusinessDataError);
  assert.throws(() => normalizeOrganisation({ ...ORG_DETAILS, primary_goal: "go_viral" }), BusinessDataError);
  assert.throws(() => normalizeOrganisation({ ...ORG_DETAILS, name: "a" }), BusinessDataError);
  assert.throws(() => normalizeWebsite("javascript:alert(1)"), BusinessDataError);
  assert.throws(() => normalizeWebsite("https://username:password@example.com"), BusinessDataError);
  assert.throws(() => normalizeBrand({ ...BRAND_DETAILS, default_cta: "x".repeat(161) }), BusinessDataError);
});

test('uncertain business creation recovers the same owner intent without a duplicate',async()=>{
  let row=null,inserts=0;
  const client={auth:{getUser:async()=>({data:{user:{id:ALICE}}})},from(){
    let writing=false,payload;
    return {insert(value){writing=true;payload=value;return this;},select(){return this;},eq(){return this;},
      async single(){
        if(!row){row=payload;inserts++;return {error:{code:'network_lost_after_write'}};}
        return {error:{code:'23505'}};
      },async maybeSingle(){assert.equal(writing,false);return {data:row};}};
  }};
  const repo=createBusinessRepository(client);
  await assert.rejects(()=>repo.createOrganisation(ORG_DETAILS,ORG));
  assert.equal((await repo.createOrganisation(ORG_DETAILS,ORG)).id,ORG);
  assert.equal(inserts,1);
  await assert.rejects(()=>repo.createOrganisation({...ORG_DETAILS,name:'Different business'},ORG),e=>e.code==='revision_conflict');
});

test('business detail edits require the same owner and unchanged saved context',async()=>{
  const client=clientMock({response:{id:ORG}});
  await createBusinessRepository(client).updateOrganisation(ORG,{...ORG_DETAILS,primary_goal:'bookings'},ORG_DETAILS);
  assert.ok(client.calls.some(call=>call[0]==='eq'&&call[1]==='owner_id'&&call[2]===ALICE));
  assert.ok(client.calls.some(call=>call[0]==='eq'&&call[1]==='primary_goal'&&call[2]==='enquiries'));
  const unavailable=clientMock({response:null});
  await assert.rejects(()=>createBusinessRepository(unavailable).updateOrganisation(ORG,ORG_DETAILS,ORG_DETAILS),e=>e.code==='revision_conflict');
});

test('lost business edit acknowledgement recovers matching saved details without overwriting later edits',async()=>{
  let row={id:ORG,owner_id:ALICE,...normalizeOrganisation(ORG_DETAILS)},writes=0,loseResponse=true;
  const client={auth:{getUser:async()=>({data:{user:{id:ALICE}}})},from(){
    let payload=null;const filters=[];
    return {update(value){payload=value;return this;},select(){return this;},
      eq(key,value){filters.push([key,value]);return this;},is(key,value){filters.push([key,value]);return this;},
      async maybeSingle(){
        const matches=filters.every(([key,value])=>row?.[key]===value);
        if(!payload){
          assert.ok(filters.some(([key,value])=>key==='owner_id'&&value===ALICE));
          return {data:matches?{...row}:null};
        }
        if(!matches)return {data:null};
        row={...row,...payload};writes++;
        if(loseResponse){loseResponse=false;return {error:{code:'network_lost_after_write'}};}
        return {data:{...row}};
      }};
  }};
  const repo=createBusinessRepository(client),edit={...ORG_DETAILS,primary_goal:'bookings'};
  await assert.rejects(()=>repo.updateOrganisation(ORG,edit,ORG_DETAILS),e=>e.code==='storage_failure');
  assert.equal((await repo.updateOrganisation(ORG,edit,ORG_DETAILS)).primary_goal,'bookings');
  assert.equal(writes,1);
  row.name='Later owner correction';
  await assert.rejects(()=>repo.updateOrganisation(ORG,edit,ORG_DETAILS),e=>e.code==='revision_conflict');
  assert.equal(row.name,'Later owner correction');assert.equal(writes,1);
  row={id:ORG,owner_id:'other-owner',...normalizeOrganisation(edit)};
  await assert.rejects(()=>repo.updateOrganisation(ORG,edit,ORG_DETAILS),e=>e.code==='revision_conflict');
  row=null;
  await assert.rejects(()=>repo.updateOrganisation(ORG,edit,ORG_DETAILS),e=>e.code==='revision_conflict');
});

test("authenticated creation assigns owner_id from Supabase user, not input", async () => {
  const client = clientMock({ response: { id: ORG } });
  const saved = await createBusinessRepository(client).createOrganisation({ ...ORG_DETAILS, owner_id: "attacker-id" });
  assert.equal(saved.id, ORG);
  const [, payload] = client.calls.find(x => x[0] === "insert");
  assert.equal(payload.owner_id, ALICE);
  assert.equal(payload.name, "Sitewisers");
  assert.equal(client.calls[0][1], "business_organisations");
});

test("no database request is made without a verified authenticated user", async () => {
  const client = clientMock({ user: null });
  const repo = createBusinessRepository(client);
  await assert.rejects(() => repo.listOrganisations(), e => e.code === "auth_required");
  await assert.rejects(() => repo.createOrganisation(ORG_DETAILS), e => e.code === "auth_required");
  await assert.rejects(() => repo.listBrands(ORG), e => e.code === "auth_required");
  assert.equal(client.calls.length, 0);
});

test('a delayed identity check cannot move a business save to the next account', async () => {
  const client=clientMock({response:{id:ORG}});
  let resolveIdentity;
  client.auth.getUser=()=>new Promise(resolve=>{resolveIdentity=resolve;});
  const repo=createBusinessRepository(client,{expectedUserId:ALICE});
  const saving=repo.createOrganisation(ORG_DETAILS,ORG);
  resolveIdentity({data:{user:{id:BRAND}}});
  await assert.rejects(()=>saving,e=>e.code==='auth_required'&&/session changed/i.test(e.message));
  assert.equal(client.calls.length,0,'No PostgREST write under the replacement account');
  client.auth.getUser=async()=>({data:{user:{id:BRAND}}});
  await assert.rejects(()=>repo.updateOrganisation(ORG,ORG_DETAILS,ORG_DETAILS),e=>e.code==='auth_required');
  await assert.rejects(()=>repo.listOrganisations(),e=>e.code==='auth_required');
  assert.equal(client.calls.length,0);
  client.auth.getUser=async()=>({data:{user:{id:ALICE}}});
  assert.equal((await repo.createOrganisation(ORG_DETAILS,ORG)).id,ORG);
});

test("brand mutations are scoped to the selected organisation and brand ID", async () => {
  const client = clientMock({ response: { id: BRAND, organisation_id: ORG } });
  const saved = await createBusinessRepository(client).saveBrand(ORG, BRAND_DETAILS, BRAND);
  assert.equal(saved.id, BRAND);
  assert.deepEqual(client.calls.filter(x => x[0] === "eq"), [["eq", "id", BRAND], ["eq", "organisation_id", ORG]]);
  const fields = client.calls.find(x => x[0] === "update")[1];
  assert.equal(fields.primary_color, "#AABBCC");
  assert.equal(fields.organisation_id, undefined);
});

test("rejects untrusted organisation or brand identifier before querying", async () => {
  const client = clientMock();
  const repo = createBusinessRepository(client);
  await assert.rejects(() => repo.listBrands("../../other"), e => e.code === "invalid_input");
  await assert.rejects(() => repo.saveBrand(ORG, BRAND_DETAILS, "not-uuid"), e => e.code === "invalid_input");
  assert.equal(client.calls.length, 0);
});

test("missing schema presents an honest setup message instead of fake success", async () => {
  const client = clientMock({ response: null, err: { code: "42P01", message: "relation does not exist" } });
  await assert.rejects(() => createBusinessRepository(client).listOrganisations(), e =>
    e.code === "storage_not_ready" && /not been enabled/.test(e.message));
});

test("unrecognized server errors are not leaked to the UI", async () => {
  const client = clientMock({ err: { code: "500", message: "internal system secret details" } });
  await assert.rejects(() => createBusinessRepository(client).listOrganisations(), e =>
    e.code === "storage_failure" && !e.message.includes("secret"));
});

test("business tables require owner scoping, RLS and an unauthenticated grant revocation", () => {
  const sql = readFileSync(new URL("../docs/sql/business-foundation-DRAFT.sql", import.meta.url), "utf8");
  for (const table of ["business_organisations", "business_brand_kits"]) {
    assert.match(sql, new RegExp("ALTER TABLE public\\." + table + " ENABLE ROW LEVEL SECURITY"));
    assert.match(sql, new RegExp("REVOKE ALL ON public\\." + table + " FROM PUBLIC, anon, authenticated"));
  }
  assert.match(sql, /owner_id = \(SELECT auth.uid\(\)\)/);
  assert.match(sql, /FOR INSERT TO authenticated WITH CHECK/);
  assert.match(sql, /FOR UPDATE TO authenticated USING/);
});

test("business workspace is only mounted through the preview gate", () => {
  const main = readFileSync(new URL("../src/main.jsx", import.meta.url), "utf8");
  assert.match(main, /BUSINESS_PREVIEW_ENABLED && <Route path="\/business\/workspace"/);
});

test("account changes reset workspace identity before showing client records", () => {
  const page = readFileSync(new URL("../src/BusinessWorkspace.jsx", import.meta.url), "utf8");
  assert.match(page, /const \[userId, setUserId\]/);
  assert.match(page, /setOrganisations\(\[\]\)/);
  assert.match(page, /loadedFor === userId/);
  assert.match(page, /\}, \[userId\]\)/);
});
