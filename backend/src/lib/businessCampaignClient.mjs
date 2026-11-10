import { guardedFetch } from "./businessNetwork.mjs";
/** Authenticated business workflow, reusing existing Clippr endpoints and quotas. */
const API = import.meta.env?.VITE_API_URL || "https://api.clippr.org";
export const GOAL_HINTS = Object.freeze({
  awareness: "Find moments that introduce the business, what it does and its character.",
  enquiries: "Find clear descriptions of services that prompt relevant enquiries.",
  bookings: "Highlight experiences or services viewers may want to book; never invent availability.",
  education: "Select clear and useful explanations; avoid unsupported factual claims.",
  offers: "Select footage relevant to the supplied approved offer; never invent discounts or deadlines.",
});
export function validBusinessVideoUrl(value) {
  if(typeof value!=="string" || value.length>1500)return false;
  try{
    const parsed=new URL(value.trim());
    if(parsed.protocol!=="https:" || parsed.username || parsed.password)return false;
    const host=parsed.hostname.toLowerCase();
    return ["youtube.com","www.youtube.com","m.youtube.com","youtu.be","twitch.tv","www.twitch.tv","clips.twitch.tv","kick.com","www.kick.com"].includes(host);
  }catch{return false;}
}
export function makeDetectionBrief({name, industry, goal, approvedOffer = ""}) {
  if (typeof name !== "string" || name.trim().length < 2 || !GOAL_HINTS[goal]) throw new Error("Select a business and goal.");
  const safeName = name.replace(/[\r\n]/g, " ").trim().slice(0, 120);
  const safeIndustry = typeof industry === "string" ? industry.replace(/[\r\n]/g, " ").slice(0, 40) : "business";
  const approved = typeof approvedOffer === "string" ? approvedOffer.trim().slice(0, 200) : "";
  if (goal === "offers" && !approved) throw new Error("Enter the approved offer before starting.");
  return [
    "BUSINESS CONTENT SEARCH (clip selection only).",
    "Organisation: " + safeName + "; sector: " + safeIndustry + "; objective: " + goal + ".",
    GOAL_HINTS[goal],
    ...(approved ? ["User-approved offer information: " + approved] : []),
    "Find authentic self-contained footage moments with accurate beginnings and endings.",
    "Avoid invented pricing, discounts, medical outcomes or unverified claims.",
  ].join("\n");
}
async function apiRequest(path, token, options = {}) {
  if (!token) throw Object.assign(new Error("Sign in to Clippr first."), { code: "auth_required" });
  const response = await guardedFetch(API + path, {
    ...options,
    headers: {
      Authorization: "Bearer " + token,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    }
  }, { timeoutMs: options.method === "POST" ? 24000 : 12000 });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || "This request could not be completed."), { code: data.code || "http_" + response.status, status: response.status });
  return data;
}
export async function startBusinessSource(token, {url, brief, idempotencyKey}) {
  if (!validBusinessVideoUrl(url)) throw new Error("Enter a valid HTTPS YouTube, Kick or Twitch link.");
  if (!/^[a-zA-Z0-9_-]{8,160}$/.test(idempotencyKey || "")) throw new Error("Submission key is invalid.");
  return apiRequest("/api/analyse", token, {
    method: "POST", headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({url: url.trim(), brief})
  });
}
export const readBusinessSession = (token,sid,{signal}={}) => apiRequest("/api/business/sessions/"+encodeURIComponent(sid),token,{signal});
export const prepareBusinessCampaign = (token, payload) => apiRequest("/api/business/campaigns/prepare",token,{method:"POST",body:JSON.stringify(payload)});
export const requestClipPreview = (token, payload) => apiRequest("/api/preview-segment",token,{method:"POST",body:JSON.stringify(payload)});
export const readClipPreview = (token,id) => apiRequest("/api/preview-status/"+encodeURIComponent(id),token);
export const requestClipExport = (token, payload) => apiRequest("/api/export",token,{method:"POST",body:JSON.stringify(payload)});
export const readClipExport = (token,id) => apiRequest("/api/export/status/"+encodeURIComponent(id),token);

// Brand rendering is a SECOND, owner-verified phase after the original Clippr
// export succeeds, so creator billing/watermarks cannot be skipped.
export const requestBrandedExport = (token, payload) => apiRequest("/api/business/exports/brand",token,{method:"POST",body:JSON.stringify(payload)});
export const readBrandedExport = (token, id) => apiRequest("/api/business/exports/brand/"+encodeURIComponent(id),token);
