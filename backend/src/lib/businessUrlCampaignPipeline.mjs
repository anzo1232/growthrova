/** Offline orchestration of URL evidence into reviewable, uncharged agency deliverables. */
import {creativeFromWebsiteFindings,inferCreativeSector} from './businessUrlCreativeBrief.mjs';
import {buildThirtyDayPlan,recommendBusinessServices} from './businessThirtyDayPlan.mjs';
import {auditBusinessWebsite,siteAuditMarkdown} from './businessSiteAudit.mjs';
import {buildWebsiteStory,storyMarkdown,websiteExcerptText} from './businessUrlStoryEngine.mjs';
import {editorialShortlist} from './businessEditorialShortlist.mjs';
import {BUSINESS_GOALS} from './businessConfig.mjs';
import {strategyFields} from './businessOwnerStrategy.mjs';
const text=(v,n=160)=>typeof v==='string'?v.trim().slice(0,n):'';
// Keep the useful body details from every audited page in the review budget.
// This selects unconfirmed observations only; it never confirms a claim.
function researchFactsForReview(pages){
 const facts=[],sources=[];
 const add=(value,sourceUrl)=>{
  if(typeof value!=='string')return;
  let quote=value.trim();
  if(quote.length<3||/^(?:upload (?:a |your |any )|choose any file|if yes[, ]|your data will|(?:accept|reject) (?:all |optional )?cookies|(?:this website uses|our use of) cookies|cookie policy|privacy policy)/i.test(quote))return;
  if(quote.length>600){
   const sentences=quote.match(/[^.!?]+[.!?](?:\s+|$)/g)||[];
   quote='';for(const sentence of sentences){if((quote+sentence).trim().length>600)break;quote+=sentence;}
   quote=quote.trim();
  }
  if(quote&&quote.length<=600&&!facts.includes(quote)&&facts.length<40){facts.push(quote);sources.push(sourceUrl);}
 };
 add(pages[0].observations?.title,pages[0].source_url);
 const bodies=pages.map(page=>[page.observations?.meta_description,...(Array.isArray(page.observations?.visible_paragraphs)?page.observations.visible_paragraphs:[])]);
 const length=Math.max(0,...bodies.map(items=>items.length));
 // Round-robin keeps a long homepage from crowding out dedicated service pages.
 for(let i=0;i<length&&facts.length<36;i++)for(let j=0;j<bodies.length;j++)add(bodies[j][i],pages[j].source_url);
 for(const page of pages){
  for(const heading of page.observations?.headings||[])add(heading,page.source_url);
  for(const service of page.observations?.service_links||[])add(service?.label,page.source_url);
 }
 return {facts,sources};
}
function researchPages(audit){
 const pages=Array.isArray(audit.page_reports)?audit.page_reports.slice(0,4):[audit];
 if(!pages.length)throw new TypeError('Research page source is missing');
 const base=new URL(audit.source_url);
 for(const page of pages){
  if(!page||typeof page.source_url!=='string'||page.source_url.length>512||(audit.page_reports&&page.status!=='extracted_unconfirmed'))throw new TypeError('Invalid unconfirmed page source');
  let source;try{source=new URL(page.source_url);}catch{throw new TypeError('Invalid page source');}
  if(source.protocol!=='https:'||source.hostname!==base.hostname||source.username||source.password||source.port!==base.port||source.hash||/[\u0000-\u0020\u007f\\]/.test(page.source_url))
   throw new TypeError('Research page source must belong to the same site');
 }
 return pages;
}
function researchImages(audit){
 const base=new URL(audit.source_url);
 return (Array.isArray(audit.observations.image_candidates)?audit.observations.image_candidates:[]).filter(image=>{
  if(typeof image?.url!=='string'||image.url.length>512||/[\u0000-\u0020\u007f]/.test(image.url))return false;
  try{
   const ref=new URL(image.url);
   return ref.protocol==='https:'&&ref.hostname===base.hostname&&!ref.username&&!ref.password
    &&(!ref.port||ref.port==='443')&&!ref.hash&&!!ref.pathname;
  }catch{return false;}
 }).slice(0,8).map(image=>({url:image.url,alt:text(image.alt,160),rights_confirmed:false,authenticity_verified:false}));
}

function researchBrandIdentity(audit){
 const raw=audit?.observations?.visual_identity;
 if(!raw||raw.status!=='website_observed_unconfirmed'||raw.method!=='rendered_computed_styles')return null;
 const hex=value=>typeof value==='string'&&/^#[0-9A-F]{6}$/.test(value)?value:'';
 const roles={background:hex(raw.roles?.background),text:hex(raw.roles?.text),accent:hex(raw.roles?.accent)};
 const colours=(Array.isArray(raw.colours)?raw.colours:[]).slice(0,12).filter(item=>
  item&&hex(item.hex)&&Number.isInteger(item.count)&&item.count>0&&item.count<=10000)
  .map(item=>({hex:item.hex,count:item.count}));
 const fontFamilies=(Array.isArray(raw.fontFamilies)?raw.fontFamilies:[]).slice(0,6).filter(item=>
  item&&typeof item.family==='string'&&item.family.trim()&&item.family.length<=80&&
  Number.isInteger(item.count)&&item.count>0&&item.count<=10000)
  .map(item=>({family:item.family.trim(),count:item.count}));
 const logoCandidates=(Array.isArray(raw.logoCandidates)?raw.logoCandidates:[]).slice(0,4).filter(item=>{
  if(!item||typeof item.description!=='string'||item.description.length>120)return false;
  if(item.kind==='image_url'){try{const u=new URL(item.url);return u.protocol==='https:'&&!u.username&&!u.password&&!u.hash&&(!u.port||u.port==='443');}catch{return false;}}
  return item.kind==='inline_svg'&&typeof item.svg==='string'&&item.svg.startsWith('<svg')&&
   item.svg.length<=32768&&/^[0-9a-f]{64}$/.test(item.sha256);
 }).map(item=>structuredClone(item));
 const suggested=raw.suggestedBrandKit||{};
 const primary=hex(suggested.primary_color),secondary=hex(suggested.secondary_color);
 const fontStyle=['modern','classic','bold','minimal'].includes(suggested.font_style)?suggested.font_style:'modern';
 if(!primary||!secondary)return null;
 return {status:'website_observed_unconfirmed',sourceUrl:audit.source_url,capturedAt:audit.fetched_at||'',
  method:raw.method,roles,colours,fontFamilies,logoCandidates,
  suggestedBrandKit:{primary_color:primary,secondary_color:secondary,font_style:fontStyle}};
}
function researchBrandKit(business,identity){
 if(!identity)return null;
 const suggested=identity.suggestedBrandKit;
 return {name:business.slice(0,38),primary_color:suggested.primary_color,
  secondary_color:suggested.secondary_color,font_style:suggested.font_style};
}

function suggestResearchStrategy(business,sourceUrl,shortlist,story){
 const candidates=shortlist.candidates||[];
 const fit=(items,max)=>{
  let value='';for(const item of new Set(items.filter(Boolean))){
   if((value+(value?'\n':'')+item).length>max)continue;
   value+=(value?'\n':'')+item;
  }return value;
 };
 // Fewer than three categories blocks the shortlist, not the existing sourced
 // service details. Avoid copying the whole review list, including promotions.
 const details=fit(candidates.map(item=>item.evidence?.quote),500)||
  fit(story.differentiators.filter(item=>!item.sourceDateSensitive).map(item=>item.evidence),500);
 const angles=fit(candidates.map(item=>item.hook),440);
 return {
  audience:('Potential customers considering '+business+' (suggested audience; review before confirming).').slice(0,300),
  offer:details||'Review the website observations and identify the specific service or product to promote.',
  positioning:angles?'Suggested directions to review:\n'+angles:details?'Suggested service focus to review:\n'+fit(details.split('\n'),460):'Identify a concrete reason to choose this business from the reviewed facts.',
  callToAction:('Visit '+sourceUrl+' to enquire about the current options.').slice(0,240),
  constraints:'Website-derived draft suggestions only. Review the audience, offering and next step before confirming. Use only reviewed facts; do not invent prices, offers, testimonials, availability or outcomes. Check date-sensitive claims. No media, publication or spending approval.',
  factDecisions:[],confirmedContext:null
 };
}

/** Recovery when public research is unavailable. Owner input is never converted
 * into extracted observations or source evidence; the normal review/save path
 * still owns confirmation, writing eligibility and all approval holds. */
export function prepareOwnerCampaign({business,sourceUrl,goal,sector='other',offer,audience,positioning='',callToAction}={}){
 const field=(value,label,max,required=true)=>{
  if(typeof value!=='string'||value.length>max||(required&&!value.trim()))
   throw new TypeError(label+' is required and must respect its maximum length of '+max+'.');
  return value.trim();
 };
 business=field(business,'Business name',120);
 sourceUrl=field(sourceUrl,'Official website',512);
 let url;try{url=new URL(sourceUrl);}catch{throw new TypeError('Invalid official website');}
 if(url.protocol!=='https:'||url.username||url.password||url.hash||url.port||/[\u0000-\u0020\u007f\\]/.test(sourceUrl))
  throw new TypeError('Invalid official website; use the saved HTTPS business address.');
 if(!BUSINESS_GOALS.some(item=>item.id===goal))throw new TypeError('Invalid marketing goal');
 offer=field(offer,'Service or product',strategyFields.offer);audience=field(audience,'Audience',strategyFields.audience);
 positioning=field(positioning,'Reason to choose the business',strategyFields.positioning,false);
 callToAction=field(callToAction,'Next step',strategyFields.callToAction);
 const constraints='Owner-supplied brief; website not read. Confirm these details before requesting writing. Do not invent prices, offers, testimonials, availability or outcomes. Missing differentiators need owner input. No media, publication or spending approval.';
 const plan=buildThirtyDayPlan({business,offer,audience,goal,sector});
 // Reuse the planner's slots, not its generic website-copy templates. Actual
 // writing must come from the reviewed/saved brief or explicit owner edits.
 plan.posts=plan.posts.map(post=>({...post,copyDraft:'',callToAction}));
 return {business,sourceUrl,goal,observedFacts:[],websiteImages:[],
  websiteAuditText:'Website not read. This campaign starts from owner-supplied details, not website research. The saved website address is a business reference only, not evidence for these statements.',
  suggestedStrategy:{offer,audience,positioning,callToAction,constraints,factDecisions:[],confirmedContext:null},
  plan,
  creative:{prompt:'Owner-supplied creative context, pending review:\n'+offer+'\nAudience: '+audience+'\n'+constraints,ctaDraft:callToAction},
  canPublish:false,canSpend:false};
}

/** Refresh evidence without asking sparse observations to generate a new plan.
 * Existing owner strategy/copy remains separate; no new claims or directions. */
export function prepareLimitedResearchContext(audit){
 if(!audit?.source_url||!audit.observations)throw new TypeError('Retained website findings required');
 const reviewed=researchFactsForReview(researchPages(audit));
 return {sourceUrl:audit.source_url,observedFacts:reviewed.facts,observedFactSources:reviewed.sources,
  websiteImages:researchImages(audit),editorialShortlist:null,
  websiteAuditText:('Limited website findings retained for review. These findings do not establish the offering. '+
   'Existing strategy and words require review against the current findings; no claims are confirmed. '+
   'No media, publication or spending approval.\n\n'+siteAuditMarkdown(auditBusinessWebsite(audit))).slice(0,12000)};
}

/** Limited observations stay limited. The explicit owner offer supplies the
 * missing planning input, never evidence or permission to generate or deliver. */
export function prepareLimitedResearchCampaign(audit,{business,goal,strategy}={}){
 if(!audit?.source_url||!audit.observations)throw new TypeError('Retained website findings required');
 const pages=researchPages(audit);
 const reviewed=researchFactsForReview(pages);
 const campaign=prepareOwnerCampaign({business,sourceUrl:audit.source_url,goal,
  offer:strategy?.offer,
  audience:strategy?.audience||'Potential customers (suggested audience; review before confirming).',
  positioning:strategy?.positioning||'',
  callToAction:strategy?.callToAction||('Visit '+audit.source_url+' to enquire about the current options.').slice(0,240)});
 const notice='Limited website findings retained for review. The owner-supplied service or product supplies the planning brief; these findings do not establish the offering. Review all details before requesting writing. Do not invent prices, offers, testimonials, availability or outcomes. No media, publication or spending approval.';
 return {...campaign,observedFacts:reviewed.facts,observedFactSources:reviewed.sources,
  websiteImages:researchImages(audit),
  websiteAuditText:(notice+'\n\n'+siteAuditMarkdown(auditBusinessWebsite(audit))).slice(0,12000),
  creative:{...campaign.creative,prompt:'Owner-supplied creative context, pending review:\n'+
   campaign.suggestedStrategy.offer+'\nAudience: '+campaign.suggestedStrategy.audience+'\n'+notice},
  suggestedStrategy:{...campaign.suggestedStrategy,constraints:notice}};
}

export function prepareUrlCampaign(audit,{objective='enquiries',expectedLocation='',expectedDomain='',businessName}={}){
 if(!audit||!audit.source_url||!audit.observations)throw new TypeError('Successful website audit required');
 if(audit.evidence?.status==='insufficient')throw new TypeError('Insufficient business evidence. Retry website research or supply business details for review; existing work is preserved.');
 // The private backend supplies its scoped saved name. It is owner context,
 // never an extracted fact; leave all original page evidence untouched.
 if(businessName!==undefined&&(typeof businessName!=='string'||!businessName.trim()
   ||businessName.length>120||/[\u0000-\u001f\u007f]/.test(businessName)))
  throw new TypeError('Valid saved business name required');
 // A shared name is not proof of a shared business. Validate user-provided identity
 // against the fetched website before producing location-specific branded creative.
 if(expectedDomain){
  if(typeof expectedDomain!=='string'||expectedDomain.length>150||!/^[a-z\d.-]+$/i.test(expectedDomain))throw new TypeError('Invalid expected business domain');
  const actual=new URL(audit.source_url).hostname.toLowerCase().replace(/^www\./,'');
  if(actual!==expectedDomain.toLowerCase().replace(/^www\./,''))
   throw new TypeError('Business identity mismatch: website domain is not the expected official domain');
 }
 if(expectedLocation){
  if(typeof expectedLocation!=='string'||expectedLocation.length>90||!/^[\p{L} .'-]+$/u.test(expectedLocation))throw new TypeError('Invalid expected business location');
  const o=audit.observations;
  const copy=[o.title,o.meta_description,...(Array.isArray(o.headings)?o.headings:[]),...(Array.isArray(o.visible_paragraphs)?o.visible_paragraphs:[])].filter(x=>typeof x==='string').join(' ').toLowerCase();
  if(!copy.includes(expectedLocation.trim().toLowerCase()))
   throw new TypeError('Business identity mismatch: requested location is not supported by this website');
 }
 const o=audit.observations, sector=inferCreativeSector(o);
 const creative=creativeFromWebsiteFindings({sourceUrl:audit.source_url,observations:o,businessType:sector,objective});
 const business=businessName===undefined
  ?text(o.title,100).split(/\s*[:|]\s*/).find(part=>part.trim()&&!/^(home|welcome|homepage|official website)$/i.test(part.trim()))?.trim()||''
  :businessName.trim();
 if(!business)throw new TypeError('Business name must be observed, not invented');
 // The precise offer and audience must NOT be invented from page metadata.
 const observedParagraphs=Array.isArray(o.visible_paragraphs)?o.visible_paragraphs.filter(x=>typeof x==='string'&&x.trim().length>=24):[];
 const offer=text(o.meta_description,300)||text(observedParagraphs[0],300);
 const hasOffer=offer.length>=8;
 const audience='Potential customers (inferred; requires verification)';
 const plan=hasOffer?buildThirtyDayPlan({business,offer,audience,goal:objective,sector}):null;
 const pages=researchPages(audit);
 const story=buildWebsiteStory(o,sector,pages);
 const shortlist=editorialShortlist(story,{brand:business,sourceUrl:audit.source_url});
 const reviewedResearch=researchFactsForReview(pages);
 creative.observedFacts=reviewedResearch.facts;
 const suggestedStrategy=suggestResearchStrategy(business,audit.source_url,shortlist,story);
 const websiteAuditText=(siteAuditMarkdown(auditBusinessWebsite(audit))+'\n\n'+storyMarkdown(story)).slice(0,12000);
 if(plan?.posts&&story.angles.length){
  plan.posts=plan.posts.map((post,i)=>{
   if(i>=story.angles.length)return post;
   const angle=story.angles[i];
   return {...post,theme:angle.hook,
    copyDraft:('Draft direction: '+angle.hook+'\n'+websiteExcerptText(angle)+'\nSource (unconfirmed): '+angle.sourceUrl+'\nCheck the current offering, availability and suitability with the business before relying on this draft.').slice(0,1700),
    proofNeeded:'Owner verification and authorised visual evidence are required before approval'};
  });
 }
 // Research may describe external CDN images, but the saved media-reference
 // contract accepts same-site HTTPS metadata only. Do not let an unusable
 // reference prevent saving the business research and owner edits.
 const websiteImages=researchImages(audit);
 const brandIdentity=researchBrandIdentity(audit),brandKit=researchBrandKit(business,brandIdentity);
 return {sourceUrl:audit.source_url,business,sector,goal:objective,suggestedStrategy,
  observedFacts:creative.observedFacts,observedFactSources:reviewedResearch.sources,websiteImages,websiteAuditText,siteSpecificStory:story,editorialShortlist:shortlist,
  ...(brandIdentity?{brandIdentity,brandKit}:{}),unverifiedInferences:['Business category','Target audience','Core offer and conversion goal','Generated visual authenticity'],
  creative:{...creative,approvalStatus:'awaiting_business_owner_review',assetUrl:null},
  plan,services:recommendBusinessServices({goal:objective,hasWebsite:true}),
  reviewRequired:true,canGenerate:false,canPublish:false,canSpend:false,
  status:hasOffer?(shortlist.status==='three_directions_ready_for_asset_intake'?'three_concepts_need_media':'needs_more_brand_specific_evidence'):'needs_more_website_evidence'};
}
/** Do not mark anything generated, verified, approved or paid from a mocked provider response. */
export function attachGeneratedAsset(campaign,asset,{verifiedProvider=false}={}){
 if(!campaign||!asset||!verifiedProvider)throw new TypeError('Verified generation job result required');
 if(asset.status!=='completed'||!asset.jobId||!asset.url||!/^https:\/\//.test(asset.url))
  throw new TypeError('Completed HTTPS provider result required');
 if(campaign.creative.assetUrl)throw new TypeError('Asset already attached; no implicit retry or overwrite');
 return {...campaign,creative:{...campaign.creative,assetUrl:asset.url,jobId:asset.jobId,
  assetProvenance:'ai_generated',approvalStatus:'awaiting_owner_review'},canPublish:false};
}
