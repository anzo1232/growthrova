/** Export a review-only shot list, never footage or private R2 URLs. */
function value(text,limit=240) {
  const cleaned=String(text??"").replace(/[\u0000-\u001f\u007f]/g," ").trim().slice(0,limit);
  // Prevent spreadsheet formula execution, including separator bypasses.
  return /^[\s\u200b-\u200d\ufeff]*[=+\-@]/u.test(cleaned)?"'"+cleaned:cleaned;
}
function cell(input) {
  return '"'+String(input).replace(/"/g,'""')+'"';
}
function time(input) {
  const n=Number(input);
  if(!Number.isFinite(n)||n<0)throw new TypeError("Invalid source timeline");
  return Math.round(n*100)/100;
}
export function clipIdentity(clip) {
  const source=String(clip?.source_id||clip?.source||"");
  const start=Number(clip?.start_s);
  const end=Number(clip?.end_s);
  if(!source || !Number.isFinite(start) || !Number.isFinite(end) ||
      start<0 || end<=start)return "";
  return source+":"+start.toFixed(2)+":"+end.toFixed(2);
}
export function buildBusinessShotList({brandName,clips}={}) {
  if(!Array.isArray(clips)||clips.length<1||clips.length>24)
    throw new TypeError("Select between 1 and 24 scenes");
  const lines=[[
    "Brand","Source video","Start (seconds)","End (seconds)","Length (seconds)",
    "Scene title","Creative note","Marketing objective","Suggested use","Potential benefit","Before publishing","Evidence status","Approval status"
  ].map(cell).join(",")];
  const found=new Set();
  for(const clip of clips) {
    const id=clipIdentity(clip);
    if(!id||found.has(id))throw new TypeError("Duplicate or invalid scene in shot list");
    found.add(id);
    const start=time(clip.start_s),end=time(clip.end_s);
    if(end<=start||end-start>300)throw new TypeError("Invalid scene range");
    const columns=[
      value(brandName,120),value(clip.source_name||clip.source||"Source footage",180),
      start,end,Math.round((end-start)*100)/100,
      value(clip.headline||clip.title||"Visual scene",120),
      value(clip.why||"Review original footage before publishing.",240),
      value(clip.editorial?.objective||"Not specified",120),
      value(clip.editorial?.proposedUse||"Review before selecting a platform.",240),
      value(clip.editorial?.intendedBenefit||"Potential benefit not established.",240),
      value(clip.editorial?.reviewAction||"Review the footage and permissions.",240),
      "Editorial suggestion - unverified",
      "Draft - human approval required",
    ];
    lines.push(columns.map(cell).join(","));
  }
  return "\ufeff"+lines.join("\r\n")+"\r\n";
}
export function downloadBusinessShotList(csv,filename="clippr-business-shot-list.csv") {
  if(typeof document==="undefined"||typeof URL==="undefined")
    throw new Error("Downloading requires a browser");
  const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const anchor=document.createElement("a");
  anchor.href=url;
  anchor.download=filename.replace(/[^a-z0-9_.-]/gi,"-").slice(0,80);
  document.body.appendChild(anchor);
  try {anchor.click();}
  finally {
    anchor.remove();
    // Revoke after the click's navigation handoff, not synchronously.
    setTimeout(()=>URL.revokeObjectURL(url),30000);
  }
}
