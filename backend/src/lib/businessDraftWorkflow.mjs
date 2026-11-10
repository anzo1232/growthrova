/** Reviewable campaign state. Never infer human approval from detected scenes. */
import {clipIdentity} from "./businessShotList.mjs";

export const GOALS=[
  {value:"awareness",label:"Brand awareness"},
  {value:"enquiries",label:"Enquiries"},
  {value:"bookings",label:"Bookings"},
  {value:"education",label:"Education"},
  {value:"offers",label:"Offers"}
];

export function scenesFromPack(pack) {
  if (!pack?.clips?.length)return [];
  const found=new Set();
  const result=[];
  for (const clip of pack.clips) {
    const id=clipIdentity(clip);
    if(!id||found.has(id)||result.length===24)continue;
    found.add(id);
    result.push({
      source_id:clip.source_id,
      start_s:Number(clip.start_s),end_s:Number(clip.end_s),
      review_status:"draft",note:""
    });
  }
  return result;
}
export function cleanDraftScenes(scenes) {
  if(!Array.isArray(scenes)||scenes.length>24)
    throw new Error("Campaigns contain at most 24 scenes.");
  const seen=new Set();
  return scenes.map(scene=>{
    const id=clipIdentity(scene),span=Number(scene.end_s)-Number(scene.start_s);
    if(!id||seen.has(id)||!Number.isFinite(span)||span<=0||span>300||
       Number(scene.start_s)<0)
      throw new Error("The campaign contains an invalid or duplicate scene.");
    seen.add(id);
    return {
      source_id:scene.source_id,
      start_s:Number(scene.start_s),end_s:Number(scene.end_s),
      review_status:scene.review_status==="approved"?"approved":"draft",
      note:String(scene.note||"").slice(0,320)
    };
  });
}
export function draftSnapshot({name,goal,notes,brand_id,scenes}) {
  return JSON.stringify({
    name:String(name||"").trim(),goal,notes:String(notes||""),
    brand_id:brand_id||null,scenes:cleanDraftScenes(scenes)
  });
}
export function montageScenes(scenes,chosen) {
  const selected=new Set(chosen||[]);
  const picked=(scenes||[]).filter(x=>selected.has(clipIdentity(x)));
  if(picked.length<2||picked.length>6)
    throw new Error("Choose two to six approved scenes for a montage.");
  if(picked.some(x=>x.review_status!=="approved"))
    throw new Error("Every montage scene needs an explicit approval.");
  const total=picked.reduce((sum,x)=>{
    const span=Number(x.end_s)-Number(x.start_s);
    if(!Number.isFinite(span)||span<3||span>30)
      throw new Error("Each montage scene must be between 3 and 30 seconds.");
    return sum+span;
  },0);
  if(total>120)throw new Error("Montage output must be 120 seconds or less.");
  return picked.map(x=>({
    source_id:x.source_id,start_s:Number(x.start_s),end_s:Number(x.end_s)
  }));
}
export function validMontageUrl(value){
  if(typeof value!=="string")return "";
  try{
    const url=new URL(value);
    return url.protocol==="https:"?url.toString():"";
  }catch{return "";}
}
