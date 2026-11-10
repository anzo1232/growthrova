import {normalizeStrategyEvidence} from "./businessStrategyEvidence.mjs";
import { BUSINESS_GOALS, BUSINESS_INDUSTRIES } from "./businessConfig.mjs";

const IDS = new Set(BUSINESS_INDUSTRIES.map(x => x.id));
const GOALS = new Set(BUSINESS_GOALS.map(x => x.id));
const FONTS = new Set(["modern", "classic", "bold", "minimal"]);
const UUID_RE = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const HEX_RE = /^#[0-9a-f]{6}$/i;

export class BusinessDataError extends Error {
  constructor(message, code = "business_error") {
    super(message);
    this.name = "BusinessDataError";
    this.code = code;
  }
}
const bad = (message) => { throw new BusinessDataError(message, "invalid_input"); };
const str = (v) => typeof v === "string" ? v.trim() : "";

export function normalizeWebsite(value) {
  const input = str(value);
  if (!input) return null;
  if (input.length > 512) bad("Website address is too long.");
  try {
    const url = new URL(input);
    if (!["https:", "http:"].includes(url.protocol) || !url.hostname.includes(".") || url.username || url.password) {
      bad("Enter a valid public website URL, including https://.");
    }
    return url.toString();
  } catch {
    bad("Enter a valid public website URL, including https://.");
  }
}
export function normalizeOrganisation(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) bad("Business details are required.");
  const name = str(input.name);
  if (name.length < 2 || name.length > 120) bad("Business name must be 2–120 characters.");
  const industry = str(input.industry);
  if (!IDS.has(industry)) bad("Choose a valid business category.");
  const primary_goal = str(input.primary_goal);
  if (!GOALS.has(primary_goal)) bad("Choose a valid marketing goal.");
  return { name, industry, primary_goal, website: normalizeWebsite(input.website) };
}
export function normalizeBrand(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) bad("Brand details are required.");
  const name = str(input.name);
  if (name.length < 2 || name.length > 120) bad("Brand name must be 2–120 characters.");
  const primary_color = str(input.primary_color).toUpperCase();
  const secondary_color = str(input.secondary_color).toUpperCase();
  if (!HEX_RE.test(primary_color) || !HEX_RE.test(secondary_color)) bad("Choose valid six-digit brand colours.");
  const font_style = str(input.font_style);
  if (!FONTS.has(font_style)) bad("Choose a valid font style.");
  const default_cta = str(input.default_cta);
  if (default_cta.length > 160) bad("Call to action must be 160 characters or fewer.");
  return { name, primary_color, secondary_color, font_style, default_cta };
}
function checkedUuid(id) {
  if (!UUID_RE.test(str(id))) bad("Invalid organisation or brand identifier.");
  return str(id);
}
function checkedRow({ data, error }) {
  if (error) {
    if (error.code === "42P01" || error.code === "PGRST205") {
      throw new BusinessDataError("Business workspace storage has not been enabled yet.", "storage_not_ready");
    }
    // Keep provider diagnostics out of customer-facing messages.
    if (error.code === "42501") throw new BusinessDataError("You don't have access to that business.", "forbidden");
    throw new BusinessDataError("Could not save or load business information. Please try again.", "storage_failure");
  }
  return data;
}
export function normalizeConfirmedProfile(input) {
  if (!input || typeof input!=="object" || Array.isArray(input)) bad("Business profile required.");
  const values={};
  for(const [key,min,max] of [["business_description",5,1000],["offer",2,240],["audience",2,240],["differentiation",0,240],["source_reference",0,512]]){
    const value=str(input[key]);
    if(value.length<min||value.length>max)bad(`Invalid ${key.replaceAll("_"," ")}.`);
    values[key]=value;
  }
  const source_type=str(input.source_type);
  if(!["website","social","description","assets","mixed"].includes(source_type))bad("Choose a valid business information source.");
  if(input.owner_confirmed!==true)bad("Owner must confirm the business profile.");
  let research_evidence;
  try{research_evidence=normalizeStrategyEvidence(input.research_evidence||{},values);}catch(error){bad(error.message);}
  return {...values,source_type,owner_confirmed:true,research_evidence};
}
/** Persist reviewed drafts only; never store a publish or spend permission in a draft. */
export function normalizeBusinessCampaignDraft(input) {
  if (!input || typeof input!=="object" || Array.isArray(input)) bad("Campaign draft required.");
  const name=str(input.name),goal=str(input.goal),notes=typeof input.notes==="string"?input.notes:"";
  if(name.length<2||name.length>100||!GOALS.has(goal)||notes.length>1500)bad("Invalid campaign draft.");
  if(!Array.isArray(input.scenes)||input.scenes.length>24)bad("Maximum 24 scenes per draft.");
  const scenes=input.scenes.map(scene=>{
    if(!scene||typeof scene!=="object"||Array.isArray(scene))bad("Invalid campaign scene.");
    const source_id=str(scene.source_id),start_s=Number(scene.start_s),end_s=Number(scene.end_s);
    if(!UUID_RE.test(source_id)||!Number.isFinite(start_s)||!Number.isFinite(end_s)||start_s<0||end_s<=start_s||end_s-start_s>300)bad("Invalid campaign scene timings.");
    return {source_id,start_s,end_s,review_status:scene.review_status==="approved"?"approved":"draft",note:str(scene.note).slice(0,320)};
  });
  return {name,goal,notes,scenes,brand_id:input.brand_id?checkedUuid(input.brand_id):null};
}
export function createBusinessRepository(client, {expectedUserId} = {}) {
  if (!client?.auth?.getUser || !client?.from) throw new TypeError("A Supabase client is required");
  async function userId() {
    const { data, error } = await client.auth.getUser();
    if (error || !data?.user?.id) throw new BusinessDataError("Sign in before managing a business.", "auth_required");
    // The standalone workspace pins its rendered account. An identity lookup
    // completing after an account switch must not start a write as that account.
    if (expectedUserId !== undefined && data.user.id !== expectedUserId) {
      throw new BusinessDataError("Your session changed. Sign in again before managing a business.", "auth_required");
    }
    return data.user.id;
  }
  return {
    async listCampaignDrafts(organisationId) {
      const id=checkedUuid(organisationId);await userId();
      return checkedRow(await client.from("business_campaign_drafts")
        .select("id,organisation_id,name,goal,brand_id,scenes,notes,revision,updated_at")
        .eq("organisation_id",id).order("updated_at",{ascending:false})) || [];
    },
    async createCampaignDraft(organisationId,input) {
      const id=checkedUuid(organisationId),owner_id=await userId(),fields=normalizeBusinessCampaignDraft(input);
      return checkedRow(await client.from("business_campaign_drafts")
        .insert({...fields,organisation_id:id,owner_id}).select("id,revision,updated_at").single());
    },
    async updateCampaignDraft(organisationId,draftId,input,expectedRevision) {
      const id=checkedUuid(organisationId),draft=checkedUuid(draftId);
      if(!Number.isSafeInteger(expectedRevision)||expectedRevision<1)bad("A known campaign revision is required.");
      const fields=normalizeBusinessCampaignDraft(input);await userId();
      const response=await client.from("business_campaign_drafts")
        .update({...fields,revision:expectedRevision+1,updated_at:new Date().toISOString()})
        .eq("id",draft).eq("organisation_id",id).eq("revision",expectedRevision)
        .select("id,revision,updated_at").maybeSingle();
      const result=checkedRow(response);
      if(!result)throw new BusinessDataError("This draft changed elsewhere. Reload before saving.","revision_conflict");
      return result;
    },
    async listOrganisations() {
      await userId();
      return checkedRow(await client.from("business_organisations").select("id,name,industry,primary_goal,website,created_at").order("created_at", { ascending: false })) || [];
    },
    async createOrganisation(input, createId = null) {
      const fields = normalizeOrganisation(input);
      const owner_id = await userId();
      const id = createId ? checkedUuid(createId) : null;
      const result = await client.from("business_organisations").insert({ ...fields, owner_id, ...(id?{id}:{}) }).select("id,name,industry,primary_goal,website,created_at").single();
      if(id && result.error?.code==='23505') {
        const existing=checkedRow(await client.from('business_organisations').select('id,name,industry,primary_goal,website,created_at')
          .eq('id',id).eq('owner_id',owner_id).maybeSingle());
        if(existing&&Object.entries(fields).every(([key,value])=>existing[key]===value))return existing;
        throw new BusinessDataError('This save identifier belongs to different business details. Reload your businesses before retrying.','revision_conflict');
      }
      return checkedRow(result);
    },
    async updateOrganisation(organisationId,input,expected) {
      const id=checkedUuid(organisationId),fields=normalizeOrganisation(input),before=normalizeOrganisation(expected),owner=await userId();
      let query=client.from('business_organisations').update({...fields,updated_at:new Date().toISOString()}).eq('id',id).eq('owner_id',owner);
      for(const [key,value] of Object.entries(before))query=value===null?query.is(key,null):query.eq(key,value);
      const result=checkedRow(await query.select('id,name,industry,primary_goal,website,created_at').maybeSingle());
      if(result)return result;
      // A committed update may have lost its acknowledgement. Only recover an
      // exact match through the caller's RLS and owner filter; never overwrite a
      // later correction or treat a missing/inaccessible row as a saved edit.
      const existing=checkedRow(await client.from('business_organisations')
        .select('id,name,industry,primary_goal,website,created_at')
        .eq('id',id).eq('owner_id',owner).maybeSingle());
      if(existing&&Object.entries(fields).every(([key,value])=>existing[key]===value))return existing;
      throw new BusinessDataError('Business details changed elsewhere. Reload your businesses before saving.','revision_conflict');
    },
    async readConfirmedProfile(organisationId) {
      const id=checkedUuid(organisationId);await userId();
      return checkedRow(await client.from("business_confirmed_profiles").select("organisation_id,business_description,offer,audience,differentiation,source_type,source_reference,research_evidence,owner_confirmed,confirmed_at").eq("organisation_id",id).maybeSingle());
    },
    async saveConfirmedProfile(organisationId, input) {
      const id=checkedUuid(organisationId), confirmed_by=await userId();
      const fields=normalizeConfirmedProfile(input);
      return checkedRow(await client.from("business_confirmed_profiles")
        .upsert({...fields,organisation_id:id,confirmed_by,confirmed_at:new Date().toISOString(),updated_at:new Date().toISOString()},{onConflict:"organisation_id"})
        .select("organisation_id,business_description,offer,audience,differentiation,source_type,source_reference,research_evidence,owner_confirmed,confirmed_at").single());
    },
    async listBrands(organisationId) {
      checkedUuid(organisationId);
      await userId();
      return checkedRow(await client.from("business_brand_kits").select("id,organisation_id,name,primary_color,secondary_color,font_style,default_cta,logo_r2_key").eq("organisation_id", organisationId).order("created_at", { ascending: true })) || [];
    },
    async saveBrand(organisationId, brand, brandId = null) {
      const id = checkedUuid(organisationId);
      const fields = normalizeBrand(brand);
      const safeBrandId = brandId ? checkedUuid(brandId) : null;
      await userId();
      if (safeBrandId) {
        return checkedRow(await client.from("business_brand_kits").update(fields).eq("id", safeBrandId).eq("organisation_id", id).select("id,organisation_id,name,primary_color,secondary_color,font_style,default_cta,logo_r2_key").single());
      }
      return checkedRow(await client.from("business_brand_kits").insert({ ...fields, organisation_id: id }).select("id,organisation_id,name,primary_color,secondary_color,font_style,default_cta,logo_r2_key").single());
    }
  };
}
