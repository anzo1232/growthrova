import { guardedFetch } from "./businessNetwork.mjs";
/** Owner-scoped business R2 uploads, separate from anonymous creator uploads. */
const API = import.meta.env?.VITE_API_URL || "https://api.clippr.org";
const MIMES = Object.freeze({
  ".mp4":"video/mp4",".mov":"video/quicktime",
  ".m4v":"video/x-m4v",".webm":"video/webm"
});
const MAX = 512 * 1024 * 1024;
const wait = ms => new Promise(resolve => setTimeout(resolve,ms));

export function validateBusinessVideo(file){
  if(!file || typeof file.name!=="string" || file.name.length>180) return "Choose a valid video file.";
  const suffix="."+file.name.split(".").pop().toLowerCase();
  if(!MIMES[suffix]) return "Use MP4, MOV, M4V or WebM videos.";
  if(file.type && file.type!==MIMES[suffix]) return "The video's file type does not match its extension.";
  if(!Number.isFinite(file.size)||file.size<1024||file.size>MAX)
    return "Each video must be between 1KB and 512MB.";
  return "";
}
async function request(path,token,payload,{signal}={}){
  if(!token)throw new Error("Your Clippr session has expired.");
  const response=await guardedFetch(API+path,{
    method:"POST",headers:{"Authorization":"Bearer "+token,"Content-Type":"application/json"},
    body:JSON.stringify(payload),signal
  }, { timeoutMs: 18000 });
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Object.assign(new Error(data.error||"Upload service unavailable."),{code:data.code||"upload_error"});
  return data;
}
async function safeFetch(url,opts,{attempts=3,timeoutMs=150000}={}){
  for(let i=0;i<attempts;i++){
    let response;
    try{response=await guardedFetch(url,opts,{timeoutMs});}
    catch(error){
      if(i===attempts-1||opts.signal?.aborted)throw error;
      await wait(500*2**i);continue;
    }
    if(response.ok)return response;
    if(![408,429,500,502,503,504].includes(response.status) || i===attempts-1)
      throw Object.assign(new Error("Upload connection failed (HTTP "+response.status+")."),{
        status:response.status,code:"upload_http_rejected"
      });
    await wait(500*2**i);
  }
  throw new Error("Upload connection failed.");
}
async function putWorker(file,init,onProgress,signal){
  const {base,key,exp,sig}=init;
  const auth=new URLSearchParams({key,exp:String(exp),sig}).toString();
  const type=encodeURIComponent(init.content_type);
  // An unknown multipart-create outcome can leave an orphaned upload. Do not
  // auto-create a second multipart session on a network timeout.
  const create=await safeFetch(base+"/mpu/create?"+auth+"&ct="+type,
    {method:"POST",signal},{attempts:1});
  const body=await create.json().catch(()=>({}));
  if(!body.uploadId)throw new Error("Upload could not initialise.");
  const uploadId=body.uploadId;
  const partSize=init.part_size||90*1024*1024;
  const n=Math.ceil(file.size/partSize);
  const pieces=[];
  let completing=false;
  try{
    for(let i=0;i<n;i++){
      const blob=file.slice(i*partSize,Math.min(file.size,(i+1)*partSize));
      const partNo=i+1;
      const q=auth+"&uploadId="+encodeURIComponent(uploadId)+"&part="+partNo;
      const response=await safeFetch(base+"/mpu/part?"+q,{method:"PUT",body:blob,signal});
      const answer=await response.json().catch(()=>({}));
      if(!answer.etag)throw new Error("Upload part was not acknowledged.");
      pieces.push({part:partNo,etag:answer.etag});
      onProgress?.(Math.min(99,Math.round(100*(i+1)/n)));
    }
    completing=true;
    const completed=await safeFetch(base+"/mpu/complete?"+auth,{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({uploadId,parts:pieces}),signal
    },{attempts:1,timeoutMs:30000}); // unknown completion outcome: do not auto-complete twice
    const result=await completed.json().catch(()=>({}));
    if(!result.ok)throw new Error("Upload completion was not confirmed.");
    return key;
  }catch(error){
    // Once multipart completion was sent the outcome is unknown. The object
    // may already be safely stored, so DO NOT abort or automatically resubmit.
    if(!completing && !signal?.aborted){
      fetch(base+"/mpu/abort?"+auth+"&uploadId="+encodeURIComponent(uploadId),{
        method:"POST",keepalive:true
      }).catch(()=>{});
    }
    throw error;
  }
}
async function verifyUpload(token,shared,key,sourceId,{signal,attempts=3}={}){
  for(let i=0;i<attempts;i++){
    if(signal?.aborted)throw new Error("Upload verification cancelled.");
    try{
      const body=await request("/api/business/sources/confirm",token,{
        ...shared,key
      },{signal});
      if(!body.ok||body.source_id!==sourceId)
        throw new Error("Upload verification returned an unexpected source.");
      return true;
    }catch(error){
      // Storage can be briefly unavailable while multipart completion settles.
      // Do not retry forbidden/invalid object metadata (4xx).
      if(i===attempts-1 || ["not_found","upload_invalid","invalid_source",
        "auth_required","forbidden"].includes(error.code))throw error;
      await wait(650*(i+1));
    }
  }
  return false;
}
export async function uploadBusinessVideo({token,organisationId,file,nonce,onProgress,signal}){
  const error=validateBusinessVideo(file);
  if(error)throw new Error(error);
  if(!organisationId||!/^[a-f0-9]{32}$/i.test(nonce||""))
    throw new Error("Select your business and a valid upload identifier.");
  const shared={organisation_id:organisationId};
  const suffix="."+file.name.split(".").pop().toLowerCase();
  const mime=file.type||MIMES[suffix];
  const init=await request("/api/business/sources/init",token,{
    ...shared,filename:file.name,content_type:mime,size:file.size,client_nonce:nonce
  },{signal});
  if(!init.key)throw new Error("Upload reservation is missing its key.");
  if(init.status==="confirmed"){
    onProgress?.(100);
    return {key:init.key,sourceId:init.source_id,recovered:Boolean(init.replayed)};
  }
  let transportFailure=null;
  try{
    if(init.mode==="worker"){
      await putWorker(file,init,onProgress,signal);
    }else if(init.mode==="single"){
      if(!init.upload_url)throw new Error("Presigned upload URL is unavailable.");
      // PUT uses a single stable R2 key. Unknown-response completion is
      // reconciled via HEAD; don't blindly upload the whole video twice.
      await safeFetch(init.upload_url,{
        method:"PUT",headers:{"Content-Type":init.content_type||mime},
        body:file,signal
      },{attempts:1});
      onProgress?.(99);
    }else{
      throw new Error("Unsupported upload mode.");
    }
  }catch(error){
    if(signal?.aborted)throw error;
    // A definite 4xx reject is not an unknown upload outcome. Don't try to
    // verify or mark a denied request as a completed upload.
    if(error.status>=400 && error.status<500 &&
       ![408,429].includes(error.status))throw error;
    transportFailure=error;
  }
  try{
    await verifyUpload(token,shared,init.key,init.source_id,{
      signal,attempts:transportFailure?4:3
    });
  }catch(verificationError){
    if(transportFailure){
      throw Object.assign(new Error(
        "Upload confirmation was interrupted. Clippr has kept your reservation; retry with the same file to check its status before uploading again."
      ),{code:"upload_outcome_unknown",cause:verificationError});
    }
    throw verificationError;
  }
  onProgress?.(100);
  return {key:init.key,sourceId:init.source_id,
    recovered:Boolean(transportFailure)};
}
export const startVisualScan=(token,orgId,sourceId)=>request("/api/business/visual/start",token,{
  organisation_id:orgId,source_id:sourceId
});
export async function readVisualScan(token,jobId,{signal}={}){
  if(!token)throw new Error("Sign in to Clippr.");
  const resp=await guardedFetch(API+"/api/business/visual/"+encodeURIComponent(jobId),{
    headers:{"Authorization":"Bearer "+token},signal
  },{timeoutMs:12000});
  const body=await resp.json().catch(()=>({}));
  if(!resp.ok)throw Object.assign(new Error(body.error||"Visual scan could not be loaded."),{code:body.code});
  return body;
}
export const prepareVisualPack=(token,orgId,brandId,ids)=>request("/api/business/campaigns/prepare-visual",token,{
  organisation_id:orgId,brand_id:brandId||null,visual_job_ids:ids
});

export async function listBusinessUploads(token,organisationId){
  const q=new URLSearchParams({organisation_id:organisationId});
  const resp=await guardedFetch(API+"/api/business/sources?"+q.toString(),{
    headers:{"Authorization":"Bearer "+token}
  },{timeoutMs:12000});
  const result=await resp.json().catch(()=>({}));
  if(!resp.ok)throw new Error(result.error||"Could not restore uploaded footage.");
  return result.sources||[];
}
export async function visualStatusBySource(token,sourceId){
  const resp=await guardedFetch(API+"/api/business/visual/source/"+encodeURIComponent(sourceId),{
    headers:{"Authorization":"Bearer "+token}
  },{timeoutMs:12000});
  const data=await resp.json().catch(()=>({}));
  if(!resp.ok)throw new Error(data.error||"Could not load scene status.");
  return data;
}


/** Check a previously reserved source without uploading another file. */
export async function recoverBusinessUpload(token,organisationId,sourceId){
  return request("/api/business/sources/recover",token,{
    organisation_id:organisationId,source_id:sourceId
  });
}
