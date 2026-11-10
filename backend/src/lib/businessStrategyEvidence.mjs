/** Website excerpts are unverified source statements, never proof of a claim. */
export const evidenceFields=['business_description','offer','audience','differentiation'];
export function normalizeStrategyEvidence(input={},profile={}){
 if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>!evidenceFields.includes(k)))throw new TypeError('Invalid strategy evidence');
 const result={};
 for(const key of evidenceFields){
  const item=input[key];
  if(!item)continue;
  if(typeof item!=='object'||Array.isArray(item)||typeof item.quote!=='string'||item.quote.length>1200||typeof item.sourceUrl!=='string'||item.sourceUrl.length>512||typeof item.claim!=='string'||item.claim.length>1000)throw new TypeError('Invalid source excerpt');
  if(!item.quote.trim()&&!item.sourceUrl.trim())continue;
  let url;try{url=new URL(item.sourceUrl);}catch{throw new TypeError('Use an HTTPS evidence URL');}
  if(url.protocol!=='https:'||url.username||url.password||!url.hostname.includes('.')||!item.quote.trim())throw new TypeError('A source URL and exact excerpt are required');
  if(item.reportSha256!==undefined&&!/^[a-f0-9]{64}$/.test(item.reportSha256))throw new TypeError('Invalid research fingerprint');
  result[key]={...(item.reportSha256?{reportSha256:item.reportSha256}:{}),sourceUrl:url.href,quote:item.quote.trim(),claim:item.claim,status:'unverified_website_statement'};
 }
 return result;
}
export function strategyEvidenceStatus(profile,key){
 const item=profile.research_evidence?.[key];
 if(!item?.quote||!item?.sourceUrl)return 'No source excerpt linked — owner-supplied claim only.';
 if(item.claim!==profile[key])return 'Claim changed — review and link the evidence again.';
 return 'Website statement linked — not independently verified.';
}
