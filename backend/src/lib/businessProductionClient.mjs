/** Backend-first Clippr Business API contract for later UI development.
 *
 * Functions are authenticated, bounded and never retry writes automatically.
 * The new routes are gated OFF until the Business database and entitlement
 * checks have been verified in staging.
 */
import {guardedFetch} from "./businessNetwork.mjs";
const API=import.meta.env?.VITE_API_URL||"https://api.clippr.org";
async function read(path,token,{method="GET",body,signal}={}){
  if(!token)throw Object.assign(new Error("Sign in to Clippr"),{code:"auth_required"});
  const response=await guardedFetch(API+path,{
    method,signal,
    headers:{"Authorization":"Bearer "+token,...(body===undefined?{}:{"Content-Type":"application/json"})},
    ...(body===undefined?{}:{body:JSON.stringify(body)})
  },{timeoutMs:method==="GET"?12000:23000});
  const json=await response.json().catch(()=>({}));
  if(!response.ok)
    throw Object.assign(new Error(json.error||"Business request unavailable."),{
      code:json.code||"http_"+response.status,status:response.status
    });
  return json;
}
export function listBusinessDrafts(token,orgId,{signal}={}){
  return read("/api/business/drafts?"+new URLSearchParams({organisation_id:orgId}),token,{signal});
}
export function readBusinessDraft(token,id,{signal}={}){
  return read("/api/business/drafts/"+encodeURIComponent(id),token,{signal});
}
export function createBusinessDraftIntent(){
  if(!globalThis.crypto?.randomUUID)
    throw new Error("Secure campaign identifiers are not available.");
  return globalThis.crypto.randomUUID();
}
export function saveBusinessDraft(token,payload,{signal}={}){
  if(!payload?.id && !payload?.create_id)
    throw new TypeError("New campaigns need a stable create_id. Generate one once and reuse it on network retry.");
  return read("/api/business/drafts",token,{method:"POST",body:payload,signal});
}
export function deleteBusinessDraft(token,id,{signal}={}){
  return read("/api/business/drafts/"+encodeURIComponent(id),token,{method:"DELETE",signal});
}
export function startBusinessMontage(token,{organisation_id,brand_id,scenes,draft_id,draft_revision},{signal}={}){
  if(!draft_id||!Number.isInteger(draft_revision)||draft_revision<1)
    throw new TypeError("Approve a saved campaign revision before exporting a montage.");
  return read("/api/business/montages",token,{
    method:"POST",body:{organisation_id,brand_id,scenes,draft_id,draft_revision},signal
  });
}
export function readBusinessMontage(token,jobId,{signal}={}){
  return read("/api/business/montages/"+encodeURIComponent(jobId),token,{signal});
}


export function readBusinessMontageUsage(token,{signal}={}){
  return read("/api/business/montages/usage",token,{signal});
}

/** Completed Business visual-scan source seconds, NOT a Stripe invoice. */
export function readBusinessSourceUsage(token,{signal}={}){
  return read("/api/business/visual/usage",token,{signal});
}
