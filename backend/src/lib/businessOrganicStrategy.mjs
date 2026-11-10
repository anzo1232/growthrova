import {strategyConfirmed,reviewedBusinessDetails} from './businessOwnerStrategy.mjs';
import {websiteRecommendations} from './businessSiteAudit.mjs';

const outlines={
 awareness:['Introduce the business','Introduce the supported detail. Explain its relationship to the confirmed offer and audience. Request any missing background before writing.'],
 enquiries:['Help readers prepare an enquiry','Explain the supported detail and the offer scope. Request a real customer question and an accurate answer. Verify how readers should enquire.'],
 bookings:['Help readers consider a booking','Explain the supported service detail. Request actual appointment steps, preparation and availability information. Verify the booking destination before use.'],
 education:['Explain a useful business detail','Explain the supported detail in plain language. Request a supported example and relevant limitations. Verify advice and definitions before use.'],
 offers:['Explain the offer and its terms','Connect the supported detail to the confirmed offer. Request actual inclusions, exclusions and terms. Do not add discounts, prices, scarcity or deadlines.'],
};
const sameSource=(a,b)=>a.kind===b.kind&&a.index===b.index&&a.quote===b.quote&&a.sourceUrl===b.sourceUrl;

/** Retain the saved audit exactly; preparation grants no website-edit authority. */
export function addWebsiteImprovement(doc,index){
 const task=websiteRecommendations(doc.websiteAuditText).find(item=>item.id===index);
 if(!task)throw new TypeError('Choose a recommendation from the saved audit');
 const reference={kind:'audit',index,quote:task.fix,sourceUrl:doc.sourceUrl||''};
 const items=doc.organicWork||[];
 if(items.some(item=>item.kind==='improvement'&&sameSource(item.reference,reference)))return doc;
 if(items.length>=30)throw new TypeError('Keep up to 30 organic work items per campaign');
 if(task.headline.length>200||task.fix.length>3000)throw new TypeError('Review the saved recommendation wording; no wording has been cut');
 return {...doc,organicWork:[...items,{id:crypto.randomUUID(),kind:'improvement',
  title:task.headline,brief:task.fix,draft:'',nextAction:'',status:'planned',reference}]};
}

/** Preparation wording only; original evidence and owner corrections stay separate. */
export function organicStrategySuggestions(doc){
 if(!strategyConfirmed(doc)||!Object.hasOwn(outlines,doc.goal))return [];
 const s=doc.ownerStrategy,[title,outline]=outlines[doc.goal];
 return reviewedBusinessDetails(doc).map(detail=>{
  const reference={kind:'fact',index:detail.index,quote:doc.observedFacts[detail.index],sourceUrl:doc.observedFactSources?.[detail.index]||''};
  const brief=[`Marketing goal: ${doc.goal}`,`Audience: ${s.audience}`,`Offer: ${s.offer}`,
   ...(s.positioning?[`Positioning: ${s.positioning}`]:[]),
   `${detail.decision==='corrected'?'Owner correction (use instead of the original observation)':'Owner-confirmed detail'}: ${detail.statement}`,
   `Outline to prepare: ${outline}`,`Proposed next step for readers: ${s.callToAction}`].join('\n\n');
  return {index:detail.index,title:`${title} — observation ${detail.index+1}`,brief,
   nextAction:s.constraints,reference,
   existingId:(doc.organicWork||[]).find(item=>item.kind==='content'&&sameSource(item.reference,reference))?.id,
   blocked:brief.length>3000||s.constraints.length>1000};
 });
}

/** Recompute at the guarded editor boundary; never apply a retained preview. */
export function addOrganicStrategyBrief(doc,index){
 const suggestion=organicStrategySuggestions(doc).find(item=>item.index===index);
 if(!suggestion)throw new TypeError('Confirm the current strategy and review this observation first');
 if(suggestion.existingId)return doc;
 if(suggestion.blocked)throw new TypeError('Shorten the strategy wording before preparing this brief; no wording has been cut');
 const items=doc.organicWork||[];
 if(items.length>=30)throw new TypeError('Keep up to 30 organic work items per campaign');
 const {title,brief,nextAction,reference}=suggestion;
 return {...doc,organicWork:[...items,{id:crypto.randomUUID(),kind:'content',title,brief,nextAction,reference,draft:'',status:'planned'}]};
}
