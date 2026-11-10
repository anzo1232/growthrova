const API = import.meta.env?.VITE_API_URL || "https://api.clippr.org";
const MIME = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX = 2_000_000;

async function jsonResponse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || "Logo request failed. Please try again.");
  return body;
}
function headers(token) {
  if (!token) throw new Error("Sign in to manage brand assets.");
  return {"Authorization": "Bearer " + token, "Content-Type": "application/json"};
}
export function validLogoFile(file) {
  return Boolean(file && MIME.has(file.type) && file.size >= 100 && file.size <= MAX);
}
export async function uploadBrandLogo({token, organisationId, brandId, file}) {
  if (!validLogoFile(file)) throw new Error("Choose a PNG, JPG or WebP logo under 2MB.");
  if (!organisationId || !brandId) throw new Error("Save your Brand Kit before uploading a logo.");
  const body={organisation_id:organisationId,brand_id:brandId};
  const init=await jsonResponse(await fetch(API+"/api/business/brands/logo/init",{
    method:"POST",headers:headers(token),
    body:JSON.stringify({...body,content_type:file.type,size:file.size})
  }));
  if (!init.upload_url || !init.key) throw new Error("Logo upload could not start.");
  const transferred=await fetch(init.upload_url,{
    method:"PUT",headers:{"Content-Type":file.type},body:file
  });
  if (!transferred.ok) throw new Error("Logo upload was interrupted. Try again.");
  await jsonResponse(await fetch(API+"/api/business/brands/logo/complete",{
    method:"POST",headers:headers(token),body:JSON.stringify({...body,key:init.key})
  }));
  return getBrandLogoUrl({token,organisationId,brandId});
}
export async function getBrandLogoUrl({token,organisationId,brandId}) {
  if (!organisationId||!brandId) return "";
  const url=new URL(API+"/api/business/brands/logo");
  url.searchParams.set("organisation_id",organisationId);
  url.searchParams.set("brand_id",brandId);
  const data=await jsonResponse(await fetch(url.toString(),{
    headers:{"Authorization":"Bearer "+token}
  }));
  return data.url || "";
}
