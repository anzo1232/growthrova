import {creativeFromWebsiteFindings,inferCreativeSector} from "./businessUrlCreativeBrief.mjs";
/** Cross-industry provider bake-off. No provider is treated as the winner without review. */
export const CREATIVE_BENCHMARK_CASES=Object.freeze([
 {id:'encore-vip',business:'Encore VIP',url:'https://encorevip.uk/',industry:'Luxury concierge',offer:'Website-verified luxury concierge positioning',audience:'Prospective private clients',visual:'Discreet luxury editorial; do not imply ownership of aircraft, yachts or inventory'},
 {id:'nomadd',business:'Nomadd',url:null,industry:'Independent restaurant',offer:'Site-verified current seasonal dining',audience:'Local diners',visual:'Authentic seasonal restaurant atmosphere; never invent menu dishes'},
 {id:'beauty-retreat',business:'The Beauty Retreat & Laser Clinic',url:null,industry:'Beauty and aesthetics',offer:'Site-verified treatments only',audience:'Prospective treatment clients',visual:'Trust-led premium beauty editorial; no simulated results or medical claims'},
 {id:'marleo',business:'Marleo Construction',url:'https://www.marleoconstruction.co.uk/',industry:'Residential renovations',offer:'Site-verified renovation service',audience:'Homeowners seeking quotations',visual:'Credible architectural interiors; no fabricated completed projects'}
]);
const PROVIDERS=Object.freeze({
 image:['higgsfield-marketing-image','recraft-v4.1','flux-3-image'],
 video:['higgsfield-marketing-video','seedance-2.5','kling-v3']
});
export function createBenchmarkJobs({mediaType='image',maxJobs=4,maxRetries=0}={}){
 if(!Object.hasOwn(PROVIDERS,mediaType)||!Number.isInteger(maxJobs)||maxJobs<1||maxJobs>4||!Number.isInteger(maxRetries)||maxRetries<0||maxRetries>1)throw new TypeError('Invalid bounded creative benchmark');
 return CREATIVE_BENCHMARK_CASES.slice(0,maxJobs).map((c,i)=>({
  id:`test-${c.id}`,business:c.business,sourceUrl:c.url,businessType:c.industry,mediaType,
  providerCandidate:PROVIDERS[mediaType][i%PROVIDERS[mediaType].length],
  prompt:`Premium commercial ${mediaType} campaign for ${c.industry}. Offer: ${c.offer}. Audience: ${c.audience}. Art direction: ${c.visual}. Controlled typography and verified logos added separately. No made-up customer endorsements, fabricated products, health/financial outcomes or false availability.`,
  spendingAuthorised:false,paidJobSubmitted:false,attempts:0,maxAttempts:1+maxRetries,
  status:'awaiting_verified_website_quote_and_asset_rights',review:'Human brand fidelity and realism check required'}));
}
export function nextCreativeAttempt(job,{assetApproved=false,budgetApproved=false,previousResult='not_started'}={}){
 if(!job||!Number.isInteger(job.attempts)||job.attempts>=job.maxAttempts)return {...job,status:'manual_review_required'};
 if(!assetApproved||!budgetApproved)return {...job,status:'awaiting_approved_assets_and_budget'};
 if(!['not_started','quality_rejected'].includes(previousResult))return {...job,status:'manual_review_required'};
 return {...job,attempts:job.attempts+1,status:'ready_to_submit_once',paidJobSubmitted:false};
}

/** Build actual benchmark briefs from URL audit output, not invented industry claims.
 * Audits are keyed by benchmark ID and contain {source_url, observations}.
 * Incomplete website evidence is blocked, not silently replaced with generic copy.
 */
export function prepareWebsiteBenchmark({audits={},mediaType='image'}={}){
 const base=createBenchmarkJobs({mediaType,maxRetries:0});
 return base.map(job=>{
  const evidence=audits[job.id];
  if(!evidence)return {...job,prompt:null,status:'awaiting_website_audit'};
  try{
   if(job.sourceUrl&&new URL(evidence.source_url).hostname!==new URL(job.sourceUrl).hostname)
    return {...job,prompt:null,status:'source_domain_mismatch'};
   const sector=inferCreativeSector(evidence.observations);
   const direction=creativeFromWebsiteFindings({sourceUrl:evidence.source_url,observations:evidence.observations,businessType:sector});
   return {...job,sourceUrl:evidence.source_url,prompt:direction.prompt,observedFacts:direction.observedFacts,
    inference:sector,ownerConfirmationRequired:true,status:'awaiting_owner_fact_and_spend_approval'};
  }catch{
   return {...job,prompt:null,status:'insufficient_or_unsafe_website_evidence'};
  }
 });
}
