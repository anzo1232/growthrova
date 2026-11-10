/** Safe repeat-admission semantics for metered Clippr source analysis.
 * One idempotency key per account + business + brief + URL over a rolling day.
 * sessionStorage is best effort; in-memory map covers disabled storage in this tab.
 */
const memory=new Map();
const PREFIX="clippr:business:admission:";
const ONE_DAY=24*60*60*1000;

export function businessSourceFingerprint({userId,organisationId,url,goal,approvedOffer=""}){
  if(!userId||!organisationId||!url||!goal)throw new Error("Missing campaign submission details.");
  return JSON.stringify([organisationId,url.trim(),goal,approvedOffer.trim()]);
}
function storageRead(store,key){
  try{return store?.getItem(key);}catch{return null;}
}
function storageWrite(store,key,data){
  try{store?.setItem(key,JSON.stringify(data));}catch{ /* private mode; use memory */ }
}
export function admissionFor(storage, {userId,organisationId,url,goal,approvedOffer=""}, {
  now=Date.now(), uuid=()=>crypto.randomUUID()
}={}){
  const fingerprint=businessSourceFingerprint({userId,organisationId,url,goal,approvedOffer});
  const storageKey=PREFIX+userId;
  let entry=memory.get(storageKey);
  if(!entry){
    try{entry=JSON.parse(storageRead(storage,storageKey)||"null");}
    catch{entry=null;}
  }
  if(entry?.fingerprint===fingerprint && now-entry.createdAt<=ONE_DAY && now>=entry.createdAt && /^[a-zA-Z0-9_-]{8,160}$/.test(entry.key)){
    return {key:entry.key,sessionId:entry.sessionId||null,reused:true};
  }
  const key="biz_"+uuid().replace(/-/g,"");
  entry={fingerprint,key,sessionId:null,createdAt:now};
  memory.set(storageKey,entry);
  storageWrite(storage,storageKey,entry);
  return {key,sessionId:null,reused:false};
}
export function confirmAdmission(storage,userId,key,sessionId){
  const storageKey=PREFIX+userId;
  let entry=memory.get(storageKey);
  if(!entry){
    try{entry=JSON.parse(storageRead(storage,storageKey)||"null");}catch{entry=null;}
  }
  if(!entry || entry.key!==key || !/^[a-zA-Z0-9_-]{8,160}$/.test(sessionId||""))return false;
  const saved={...entry,sessionId};
  memory.set(storageKey,saved);
  storageWrite(storage,storageKey,saved);
  return true;
}
export function forgetAdmission(storage,userId){
  const key=PREFIX+userId;
  memory.delete(key);
  try{storage?.removeItem(key);}catch{}
}
