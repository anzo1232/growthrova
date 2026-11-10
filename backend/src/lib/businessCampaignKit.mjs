/** Channel-neutral campaign deliverables; drafts, not invented source facts. */
const bounded=(v,n=160)=>typeof v==='string'?v.trim().slice(0,n):'';
export function buildCampaignKit({business={},customer={},decision={},clips=[]}={}){
 if(!Array.isArray(clips)||clips.length<1||clips.length>24)throw new TypeError('Choose 1–24 clips');
 const name=bounded(business.name,100)||'Your business';
 const offer=bounded(decision.offer)||'the product or service';
 const audience=bounded(customer.audience)||'prospective customers';
 const action=bounded(decision.action)||'contact the business for details';
 const benefit=bounded(customer.desire)||'a reason to choose this business';
 const hesitation=bounded(customer.objection)||'a question before purchasing';
 const proof=bounded(customer.proof)||'authentic evidence from the original footage';
 const goal=bounded(business.goal)||'awareness';
 const base={status:'DRAFT — business approval required',noClaimsVerified:true,goal,audience,offer,action};
 const content=clips.map((clip,i)=>{
  const title=bounded(clip.title||clip.headline,100)||`Footage review ${i+1}`;
  const isSpoken=typeof clip.transcript==='string'&&clip.transcript.trim().length>0;
  return {index:i+1,source:bounded(clip.source_name||'Uploaded source'),start_s:clip.start_s,end_s:clip.end_s,
   title,role:isSpoken?'Potential educational or testimonial moment':'Visual footage requiring review',
   hookDraft:`For ${audience}: ${benefit}.`,captionDraft:`${name} — ${offer}. ${action}.`,
   publishingChannels:['Instagram Reels','TikTok','YouTube Shorts'],
   proofToCheck:proof,hesitationToAddress:hesitation,
   limitation:'Hook and caption reflect the business brief, not confirmed video content.'};
 });
 return {version:1,...base,deliverables:{clipPlans:content,
   socialCaptions:content.map(({index,captionDraft,proofToCheck})=>({clip:index,text:captionDraft,check:proofToCheck})),
   websiteSection:{heading:`Discover ${name}`,bodyDraft:`Explore ${offer} and see whether it fits your needs.`,ctaDraft:action},
   emailDraft:{subject:`Learn more about ${name}`,body:`Interested in ${offer}? See the details and ${action}.`},
   campaignChecklist:['Review footage and spoken context','Verify claims, pricing, permissions and consent',
     'Approve copy and call to action','Choose a channel and aspect ratio','Attach a real booking or enquiry destination',
     'Measure enquiries or bookings, not only video views']}};
}
