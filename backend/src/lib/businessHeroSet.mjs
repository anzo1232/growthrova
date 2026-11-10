/** Three distinct social concepts, never generated, charged or published by planning. */
const STRATEGIES={
 restaurant:['Show the food or atmosphere actually offered, with approved images','Answer a menu or booking question using confirmed information','Use a light, relatable dining dilemma without inventing a dish or promotion'],
 beauty:['Show a genuine treatment environment or clearly labelled photorealistic AI scene','Explain suitability, consultation or preparation without outcome claims','Answer a common appointment question sensitively; no before-and-after fabrication'],
 construction:['Show real material or approved project imagery without implying fictional completions','Explain a practical project decision with sourced details','Create a relatable renovation planning moment, not a fictional testimonial'],
 concierge:['Show photorealistic synthetic service context, never implied ownership','Explain exactly what service is offered and how to enquire','Use a subtle high-end observation, not memes or fake exclusive access'],
 roofing:['Show a real issue or clearly labelled synthetic photographic roof inspection','Explain a practical roofing symptom without diagnosing from an image','Use a relatable weather-related question without inventing past jobs'],
 other:['Show the real offering using approved references or labelled illustration','Answer one customer buying question with evidence','Create a brand-sensitive relatable customer moment']
};
const PURPOSES=[['editorial','Premium visual hero','4:5','Instagram','Facebook'],['educational','Useful explanation','4:5','Instagram','Facebook'],['social','Entertaining/social concept','9:16','TikTok','Instagram']];
export function buildHeroSet({business,offer,audience,sector='other',sourceFacts=[],assetReferences=[],ownerConfirmed=false}={}){
 if(!ownerConfirmed||![business,offer,audience].every(x=>typeof x==='string'&&x.trim().length>=3))throw new TypeError('Owner-confirmed business, offering and audience required');
 if(!Array.isArray(sourceFacts)||!Array.isArray(assetReferences))throw new TypeError('Evidence and asset references must be arrays');
 const types=STRATEGIES[sector]||STRATEGIES.other;
 const items=PURPOSES.map(([id,title,ratio,primary,secondary],i)=>({
  id:`hero-${i+1}`,purpose:id,title,ratio,platforms:[primary,secondary],
  direction:types[i],business:business.trim(),audience:audience.trim(),
  offer:offer.trim(),sourceFacts:sourceFacts.slice(0,8),assetReferences:assetReferences.slice(0,8),
  mediaState:'concept_only_not_generated',quality:'awaiting_actual_creative_and_owner_review',
  disclosure:'AI imagery must be labelled illustrative; do not imply actual client work or outcomes',
  spendAuthorised:false,retriesAllowed:false,approved:false,scheduled:false,published:false
 }));
 return {business:business.trim(),sector,items,qualityGate:'technical_and_fact_checks_then_owner_aesthetic_approval',
  noAutomaticSpending:true,requiresSeparatePaidTestApproval:true,
  launchStatus:'concepts_not_finished_content'};
}
