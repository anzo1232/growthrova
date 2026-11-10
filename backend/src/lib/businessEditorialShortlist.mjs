/** Deliberately few specific pre-production candidates. No asset, approval, cost or publishing. */
import {DATE_SENSITIVE_SOURCE_WARNING} from './businessUrlStoryEngine.mjs';
const treatments={
 restaurant:[
  {id:'craft',role:'Editorial hero',media:'Reel',direction:'One genuine preparation action in the first second, close-up craft, service handoff and a verified venue end card',format:'9:16'},
  {id:'discover',role:'First-timer discovery',media:'Carousel',direction:'Show the real food and explain unfamiliar dish names without fake menu images',format:'4:5'},
  {id:'insider',role:'For returning diners',media:'Image',direction:'One highly recognisable regional detail with an authentic in-venue photograph, rather than a generic hospitality stock image',format:'4:5'}
 ],
 concierge:[
  {id:'process',role:'Concierge journey',media:'Reel',direction:'Begin with real message / human service, show the request process and avoid pretending any booking was confirmed',format:'9:16'},
  {id:'services',role:'Service clarity',media:'Carousel',direction:'Verified offerings plus grounded qualifiers and distinct service-specific pictures',format:'4:5'},
  {id:'trust',role:'Premium editorial',media:'Image',direction:'One genuine discreet service moment, not unrelated luxurious furniture',format:'4:5'}
 ]};
const defaults=[
 {id:'proof',role:'Service proof',media:'Reel',direction:'Show a genuine craft or service action as source-authorised video',format:'9:16'},
 {id:'education',role:'First-time education',media:'Carousel',direction:'Explain one real decision using verified references and accurately labelled sources',format:'4:5'},
 {id:'decision',role:'Enquiry step',media:'Image',direction:'Describe one accurate next step with specific, owner-approved business imagery',format:'4:5'}
];
const safe=x=>String(x||'').replace(/\s+/g,' ').trim().slice(0,420);
const intro={restaurant:'Discover the actual food, craft and way of sharing',concierge:'Understand the single-enquiry concierge experience'};
const preferredKeys={
 restaurant:[['method','dish','bread'],['heritage','dish','sharing','cuisine'],['bread','dish','sharing','cuisine']],
 concierge:[['message','service'],['events','travel','dining'],['transfers','service','travel']]
};
function specificHook(item){
 const evidence=String(item?.evidence||'').toLowerCase();
 // Named source details can focus a question; they do not prove ingredients,
 // preparation, geography or a founder's biography.
 if(item?.key==='dish'&&/koobideh/.test(evidence)&&/jujeh/.test(evidence))return 'Koobideh and jujeh: which dish would you like to explore?';
 if(item?.key==='dish'&&/koobideh/.test(evidence))return 'Koobideh: get to know the dish';
 if(item?.key==='dish'&&/kebbeh/.test(evidence)&&/shish taouk/.test(evidence))return 'Kebbeh and shish taouk: get to know the dishes';
 if(item?.key==='bread'&&/taftoon/.test(evidence)&&/sangak/.test(evidence))return 'Taftoon and sangak: get to know the breads';
 if(item?.key==='bread'&&/sangak/.test(evidence))return 'Sangak: get to know the bread';
 if(item?.key==='method'&&/mangal/.test(evidence))return 'The mangal: explore the cooking method';
 if(item?.key==='method'&&/charcoal/.test(evidence))return 'Charcoal cooking: explore the method';
 if(item?.key==='sharing'&&/ma[z|zh]eh/.test(evidence))return 'Mazeh: explore the dishes';
 if(item?.key==='heritage'&&/tehran/.test(evidence))return 'Tehran: explore the story behind the food';
 return item?.hook||'A source-based customer question';
}
/** Expects source fields from buildWebsiteStory, not a guessed LLM summary. */
export function editorialShortlist(story, {brand,sourceUrl}={}){
 if(!story||!Array.isArray(story.differentiators)||!Array.isArray(story.angles))throw new TypeError('Source-linked website story required');
 if(typeof brand!=='string'||brand.trim().length<3||typeof sourceUrl!=='string'||!/^https:\/\//i.test(sourceUrl))throw new TypeError('Grounded business and URL required');
 const evidence=story.differentiators.filter(x=>x.ownerConfirmed===false&&x.sourceLabel&&safe(x.evidence).length>=16);
 const unique=[...new Map(evidence.map(x=>[x.key,x])).values()];
 const minimum=3;
 const ready=unique.length>=minimum;
 const strategies=treatments[story.sector]||defaults;
 const used=new Set();
 const ordered=['dish','cuisine','method','heritage','sharing','message','service','travel','events','dining','transfers','hospitality','catering','project','craft'];
 const rank=key=>ordered.includes(key)?ordered.indexOf(key):ordered.length;
 const ranked=[...unique].sort((a,b)=>rank(a.key)-rank(b.key));
 const candidates=ready?strategies.map((shape,index)=>{
  const preferred=(preferredKeys[story.sector]||[])[index]||[];
  const item=preferred.map(k=>ranked.find(x=>x.key===k&&!used.has(x.key))).find(Boolean)||
    ranked.find(x=>!used.has(x.key));
  if(item)used.add(item.key);
  return {id:shape.id,role:shape.role,media:shape.media,format:shape.format,
    direction:shape.direction+(item?.sourceDateSensitive?'\n'+DATE_SENSITIVE_SOURCE_WARNING:''),hook:specificHook(item),
    evidence:{kind:item?.key,label:item?.sourceLabel,quote:safe(item?.evidence),...(item?.sourceUrl?{sourceUrl:item.sourceUrl}:{})},
    brand:safe(brand),sourceUrl,realMediaRequired:true,
    generationState:'unrendered',publishApproved:false,quality:'needs_authentic_assets_and_human_art_review',
    spendApproved:false,autoRetry:false};
 }):[];
 return {business:safe(brand),sourceUrl,sector:story.sector,status:ready?'three_directions_ready_for_asset_intake':'blocked_insufficient_unique_brand_evidence',
  differentiatorCount:unique.length,evidenceMinimum:minimum,canGenerateAutomatically:false,approved:false,
  candidates,blockers:[
   ...(ready?[]:['fewer_than_three_distinct_evidence_categories']),
   'no_verified_current_brand_kit','no_rights_cleared_actual_business_media','no_owner_claims_approval','no_art_director_acceptance'],
  note:'Source quotes are website claims requiring owner verification; ideas are not finished media.'};
}
