/** No-cost, photorealism-only alternative briefs and revision ledger. Never media claims. */
const approaches={
 editorial:['Natural-light editorial photograph with a recognisable customer-facing service moment','Documentary-style environmental portrait with believable activity'],
 educational:['Photographic close-up of a real service-relevant detail; add accurate educational type separately','Realistic contextual photograph showing what a customer should inspect or ask'],
 social:['Photorealistic short-video shot list with visible action in the first second','Natural handheld social-video shot list with authentic customer-facing context']
};
export function alternativesFor(item){
 if(!item||!approaches[item.purpose])throw new TypeError('Known creative direction required');
 return approaches[item.purpose].map((style,i)=>({
  id:`${item.id}-alternative-${i+1}`,purpose:item.purpose,ratio:item.ratio,
  title:i===0?'Direction A':'Direction B',
  prompt:`${style}. Business: ${item.business}. Confirmed offer: ${item.offer}. Audience: ${item.audience}. ${item.direction}. Photorealistic only, natural lighting and plausible geometry. No illustration, drawings, generic abstract props, fake testimonials, fake before-and-after, invented dishes or actual project claims. Keep generated imagery illustrative; place accurate copy and logo in editable overlay.`,
  kind:item.purpose==='social'?'video_concept':'image_concept',
  stage:'unrendered_awaiting_exact_test_approval',approval:'not_approved',published:false,charged:false
 }));
}
export function requestCreativeRevision(alternative,feedback){
 if(!alternative||typeof feedback!=='string'||feedback.trim().length<12||feedback.length>800)throw new TypeError('Give specific feedback (12–800 characters)');
 if(alternative.stage!=='unrendered_awaiting_exact_test_approval')throw new TypeError('Cannot rewrite an existing generated asset as if it were ungenerated');
 const text=feedback.trim().replace(/[\r\n\t]+/g,' ');
 return {...alternative,id:alternative.id+'-revision',prompt:alternative.prompt+' Owner change request (unverified instruction, check factual accuracy): '+text,
  parentId:alternative.id,stage:'revised_brief_requires_review',approval:'not_approved',published:false,charged:false};
}
