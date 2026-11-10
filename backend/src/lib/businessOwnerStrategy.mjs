/** Local owner attestation of planning context; never authenticated approval. */
import {calendarDirection} from './businessCalendarDirections.mjs';
import {BUSINESS_GOALS} from './businessConfig.mjs';
import {createMarketingDocument,editMarketingPost,editMarketingCreative,MARKETING_POST_COPY_LIMIT,MARKETING_CREATIVE_COPY_LIMIT} from './businessMarketingDocument.mjs';
export const strategyFields={audience:300,offer:500,positioning:500,callToAction:240,constraints:1000};
/** Keep website observations intact; corrections are explicitly owner statements. */
export function businessFactReview(doc,index){
 const entry=doc.ownerStrategy?.factDecisions?.find(item=>item.index===index);
 return entry?.observation===doc.observedFacts?.[index]?entry:null;
}
/** Only current owner-reviewed details; never silently reuse excluded/source text. */
export function reviewedBusinessDetails(doc){
 return (doc.observedFacts||[]).flatMap((observation,index)=>{
  const review=businessFactReview(doc,index);
  const statement=review?.decision==='confirmed'?observation:review?.decision==='corrected'?review.statement:'';
  return typeof statement==='string'&&statement.trim()
   ?[{index,statement:statement.trim(),decision:review.decision}]:[];
 });
}
/** An explicit copy edit, not claim verification or an approval. */
export function appendReviewedBusinessDetail(doc,day,index){
 return appendReviewedDetail(doc,'post',day,index);
}
export function appendReviewedCreativeDetail(doc,id,index){
 return appendReviewedDetail(doc,'creative',id,index);
}
function appendReviewedDetail(doc,type,id,index){
 const detail=reviewedBusinessDetails(doc).find(item=>item.index===index);
 if(!detail)throw new TypeError('Choose a current reviewed detail first');
 const creative=type==='creative';
 const item=creative?doc.creatives.find(item=>item.id===id):doc.posts.find(item=>item.day===id);
 if(!item)throw new TypeError(creative?'Creative not found':'Post not found');
 // Match whole lines (including multi-line corrections), not partial prose.
 const lines='\n'+item.copyDraft.replaceAll('\r\n','\n').trim()+'\n';
 if(lines.includes('\n'+detail.statement.replaceAll('\r\n','\n')+'\n'))return doc;
 const copyDraft=item.copyDraft+(item.copyDraft?'\n\n':'')+detail.statement;
 if(copyDraft.length>(creative?MARKETING_CREATIVE_COPY_LIMIT:MARKETING_POST_COPY_LIMIT))throw new TypeError(`Make room in this ${creative?'creative':'post'} before adding the reviewed detail. Your copy has been kept.`);
 return {...(creative?editMarketingCreative(doc,id,{copyDraft}):editMarketingPost(doc,id,{copyDraft})),canPublish:false,canSpend:false};
}
export function businessFactsReviewed(doc){
 return (doc.observedFacts||[]).every((_,index)=>{
  const entry=businessFactReview(doc,index);
  return entry&&(['confirmed','excluded'].includes(entry.decision)||
   entry.decision==='corrected'&&Boolean(entry.statement.trim()));
 });
}
export function reviewBusinessFact(doc,index,decision,statement=''){
 if(!Number.isInteger(index)||index<0||index>39||typeof doc.observedFacts?.[index]!=='string'||
  !['pending','confirmed','corrected','excluded'].includes(decision)||typeof statement!=='string'||statement.length>600)
  throw new TypeError('Invalid business fact review');
 const entries=(doc.ownerStrategy?.factDecisions||[]).filter(item=>item.index!==index);
 if(decision!=='pending')entries.push({index,observation:doc.observedFacts[index],decision,statement:decision==='corrected'?statement:''});
 entries.sort((a,b)=>a.index-b.index);
 return {...doc,ownerStrategy:{...doc.ownerStrategy,factDecisions:entries,confirmedContext:null}};
}
/** References come only from this document's existing website research. */
export function strategyEvidence(doc){
 let url;
 try{url=new URL(doc.sourceUrl);if(url.protocol!=='https:'||url.username||url.password)return [];}catch{return [];}
 return (doc.editorialShortlist?.candidates||[]).flatMap(c=>{
  const evidence=c.evidence;
  if(typeof evidence?.quote!=='string'||!evidence.quote.trim())return [];
  const sourceUrl=evidence.sourceUrl||doc.sourceUrl;
  try{
   const source=new URL(sourceUrl);
   if(source.origin!==url.origin||source.username||source.password)return [];
  }catch{return [];}
  return [{id:c.id,sourceUrl,quote:evidence.quote,label:evidence.label||'Website excerpt'}];
 });
}
export function strategyEvidenceState(doc,key){
 const link=doc.ownerStrategy?.evidenceLinks?.[key];
 if(!link)return {status:'absent',detail:'No source linked. This is an owner-supplied statement requiring verification.'};
 const current=strategyEvidence(doc).find(e=>e.id===link.id&&e.sourceUrl===link.sourceUrl&&e.quote===link.quote);
 return current?{status:'unverified',detail:'Website excerpt linked. Relevance, accuracy and freshness still need verification.',evidence:current}:{status:'stale',detail:'The source or excerpt changed. Choose current evidence before relying on this claim.'};
}
export function strategyEvidenceCurrent(doc){
 return Object.keys(doc.ownerStrategy?.evidenceLinks||{}).every(key=>
  Object.hasOwn(strategyFields,key)&&strategyEvidenceState(doc,key).status==='unverified');
}
export function linkStrategyEvidence(doc,key,id){
 if(!Object.hasOwn(strategyFields,key))throw new TypeError('Invalid strategy field');
 const evidence=id?strategyEvidence(doc).find(e=>e.id===id):null;
 if(id&&!evidence)throw new TypeError('Source evidence is not in this campaign');
 const links={...doc.ownerStrategy?.evidenceLinks};
 if(evidence)links[key]={id:evidence.id,sourceUrl:evidence.sourceUrl,quote:evidence.quote};else delete links[key];
 return {...doc,ownerStrategy:{...doc.ownerStrategy,evidenceLinks:links,confirmedContext:null}};
}
export function strategyContext(doc){
 return {business:doc.business,goal:doc.goal,sourceUrl:doc.sourceUrl||'',observedFacts:doc.observedFacts||[],
  ...(doc.observedFactSources?{observedFactSources:doc.observedFactSources}:{}),
  ...Object.fromEntries(Object.keys(strategyFields).map(k=>[k,doc.ownerStrategy?.[k]||''])),
  ...(doc.ownerStrategy?.factDecisions?.length?{factDecisions:doc.ownerStrategy.factDecisions}:{}),
  ...(Object.keys(doc.ownerStrategy?.evidenceLinks||{}).length?{evidenceLinks:doc.ownerStrategy.evidenceLinks,researchEvidence:strategyEvidence(doc).map(({id,sourceUrl,quote})=>({id,sourceUrl,quote}))}:{})};
}
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
export function strategyConfirmed(doc){
 const s=doc.ownerStrategy;
 return Boolean(s&&businessFactsReviewed(doc)&&strategyEvidenceCurrent(doc)&&Object.keys(strategyFields).every(k=>typeof s[k]==='string'&&(k==='positioning'||s[k].trim()))&&
  canonical(s.confirmedContext)===canonical(strategyContext(doc)));
}
export function editOwnerStrategy(doc,key,value){
 if(!Object.hasOwn(strategyFields,key)||typeof value!=='string'||value.length>strategyFields[key])throw new TypeError('Invalid strategy field');
 return {...doc,ownerStrategy:{...doc.ownerStrategy,[key]:value,confirmedContext:null}};
}
/** Changing intent retains historical work, but requires fresh owner review. */
export function editCampaignGoal(doc,goal){
 if(!BUSINESS_GOALS.some(item=>item.id===goal))throw new TypeError('Choose a supported campaign goal');
 if(doc.goal===goal)return doc;
 return {...doc,goal,
  ...(doc.ownerStrategy?{ownerStrategy:{...doc.ownerStrategy,confirmedContext:null}}:{}),
  posts:doc.posts.map(post=>({...post,status:'draft'})),
  creatives:doc.creatives.map(creative=>({...creative,status:'draft'}))};
}
export function confirmOwnerStrategy(doc){
 if(!businessFactsReviewed(doc))throw new TypeError('Review each website observation: confirm, correct or exclude it before confirming your strategy');
 if(!strategyEvidenceCurrent(doc))throw new TypeError('Update or remove each changed source link before confirming your strategy');
 const next={...doc,ownerStrategy:{...doc.ownerStrategy,confirmedContext:strategyContext(doc)}};
 if(!strategyConfirmed(next))throw new TypeError('Complete the audience, offer, next step and constraints before confirming');
 return next;
}
/** Exact owner wording for an introduction, separate from internal planning notes. */
export function confirmedBriefPostCopy(doc){
 if(!strategyConfirmed(doc))throw new TypeError('Confirm the current business strategy first');
 const {offer,positioning,callToAction}=doc.ownerStrategy;
 return {copyDraft:[doc.business,offer,positioning].join('\n\n'),callToAction};
}
/** Explicit replacement of one unreviewed post; never regenerates the calendar. */
export function useConfirmedBriefForPost(doc,day){
 const copy=confirmedBriefPostCopy(doc);
 const post=doc.posts.find(item=>item.day===day);
 if(!post)throw new TypeError('Post not found');
 if(post.status==='copy_reviewed')throw new TypeError('Reviewed posts are preserved; choose an unreviewed day');
 if(post.copyDraft===copy.copyDraft&&post.callToAction===copy.callToAction)return doc;
 return {...editMarketingPost(doc,day,copy),canPublish:false,canSpend:false};
}
function requireCalendar(doc){
 if(!strategyConfirmed(doc))throw new TypeError('Confirm the current business strategy first');
 if(!/^20[2-8]\d-\d{2}-\d{2}$/.test(doc.calendarStartDate||'')||Number.isNaN(Date.parse(doc.calendarStartDate+'T00:00:00Z'))||new Date(doc.calendarStartDate+'T00:00:00Z').toISOString().slice(0,10)!==doc.calendarStartDate)throw new TypeError('Choose a calendar start date first');
}
function strategyPost(doc,day,previous){
 const s=doc.ownerStrategy,{theme,direction}=calendarDirection(doc.goal,day);
 return {...previous,day,theme,channel:previous?.channel||'Instagram',format:previous?.format||(day%3===2?'Carousel':'Image post'),objective:doc.goal,
  copyDraft:`Draft direction: ${direction}\nOwner constraints: ${s.constraints}\nFor: ${s.audience}\nOffer: ${s.offer}\nPositioning: ${s.positioning}`,
  callToAction:s.callToAction,status:'draft',scheduled:false,published:false};
}
/** Preview uses exactly the same task and brief as fill/replace, without writes. */
export function strategyCalendarPreview(doc){
 if(!strategyConfirmed(doc))return [];
 const existing=new Map(doc.posts.map(post=>[post.day,post]));
 return Array.from({length:30},(_,index)=>{
  const day=index+1,previous=existing.get(day);
  return {...strategyPost(doc,day,previous),direction:calendarDirection(doc.goal,day).direction,
   action:!previous?'new':previous.status==='copy_reviewed'?'preserved':'replaceable'};
 });
}
export function completeStrategyCalendar(doc){
 requireCalendar(doc);
 const existing=new Map(doc.posts.map(p=>[p.day,p]));
 return {...doc,posts:Array.from({length:30},(_,i)=>existing.get(i+1)||strategyPost(doc,i+1)),canPublish:false,canSpend:false};
}
/** Explicitly replace chosen unreviewed drafts; reviewed copy and other days survive. */
export function refreshStrategyCalendar(doc,days){
 requireCalendar(doc);
 if(!Array.isArray(days)||!days.length||new Set(days).size!==days.length||days.some(day=>!Number.isInteger(day)||day<1||day>30))throw new TypeError('Choose valid calendar days');
 const selected=new Set(days);
 if(days.some(day=>!doc.posts.some(p=>p.day===day)))throw new TypeError('Calendar day not found');
 if(doc.posts.some(p=>selected.has(p.day)&&p.status==='copy_reviewed'))throw new TypeError('Reviewed posts are preserved; choose an unreviewed day');
 return {...doc,posts:doc.posts.map(p=>selected.has(p.day)?strategyPost(doc,p.day,p):p),canPublish:false,canSpend:false};
}

/** Fresh campaign from saved context, never a clone of delivery preparation. */
export function prepareNextStrategyCampaign(source,{goal,startDate}){
 if(!strategyConfirmed(source))throw new TypeError('Confirm the saved business strategy before reusing it');
 if(!['awareness','enquiries','bookings','education','offers'].includes(goal))throw new TypeError('Choose a supported marketing goal');
 // Reuse the existing date validator without confirming the new goal.
 requireCalendar({...source,calendarStartDate:startDate});
 const brief=source.ownerStrategy;
 const next=createMarketingDocument({business:source.business,goal,sourceUrl:source.sourceUrl,
  observedFacts:structuredClone(source.observedFacts||[]),
  ...(source.observedFactSources?{observedFactSources:[...source.observedFactSources]}:{}),
  websiteAuditText:source.websiteAuditText,websiteImages:structuredClone(source.websiteImages||[]),
  editorialShortlist:structuredClone(source.editorialShortlist||null),
  suggestedStrategy:{...structuredClone(brief),confirmedContext:null},
  plan:{posts:[{day:1,theme:'Review the reused brief',channel:'Instagram',format:'Image post',objective:goal}]},
  creative:{prompt:['Reused business brief; review for this campaign goal.',source.business,
   'Goal: '+goal,'Offer: '+brief.offer,'Audience: '+brief.audience,
   'Positioning: '+brief.positioning,'Constraints: '+brief.constraints].join('\n'),ctaDraft:brief.callToAction}});
 next.name=(source.business+' — '+goal+' — '+startDate).slice(0,120);
 next.calendarStartDate=startDate;
 if(source.brandKit)next.brandKit=structuredClone(source.brandKit);
 next.creatives=next.creatives.filter(item=>item.format!=='video_ad');
 next.posts=Array.from({length:30},(_,index)=>strategyPost(next,index+1));
 return next;
}
