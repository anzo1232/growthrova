/** Transparent editorial suggestions; never infer footage contents or measured results. */
const OBJECTIVES={
 awareness:{label:'Build awareness',purpose:'Introduce the business to potential customers.',next:'Check the business and its distinguishing feature are visible.'},
 enquiries:{label:'Generate enquiries',purpose:'Help viewers decide whether to ask for more information.',next:'Confirm the service and use an approved enquiry call to action.'},
 bookings:{label:'Encourage bookings',purpose:'Give viewers a credible reason to book.',next:'Confirm the experience shown and use an approved booking link.'},
 education:{label:'Build trust through education',purpose:'Help viewers learn something useful.',next:'Check the explanation is complete and accurate.'},
 offers:{label:'Explain an approved offer',purpose:'Help viewers understand a confirmed offer.',next:'Check all prices, availability and deadlines with the business.'}
};
const INDUSTRY={
 hospitality:{label:'Restaurant / hospitality',use:'Reels or Shorts showing a complete dish, genuine reaction or venue experience.',check:'Confirm the finished food or experience is shown; do not invent reviews or menu claims.'},
 property:{label:'Property',use:'A listing highlight or walkthrough that preserves a sense of the space.',check:'Check important rooms remain in frame and verify every stated feature.'},
 wellness:{label:'Beauty / wellness',use:'A consent-approved service introduction or educational clip.',check:'Verify client consent, treatment details and regulated claims before publishing.'},
 consulting:{label:'Consulting / coaching',use:'One complete answer or practical takeaway for LinkedIn or Shorts.',check:'Check the advice makes sense without missing context or caveats.'},
 agency:{label:'Agency',use:'A client-approved case-study moment, process explanation or portfolio highlight.',check:'Confirm client permission and any results before including them.'},
 other:{label:'General business',use:'A short social post or website highlight linked to the stated campaign objective.',check:'Review content, rights, message and call to action.'}
};
export function customerDecision(profile={}){
 const safe=x=>typeof x==='string'?x.trim().slice(0,160):'';
 return {audience:safe(profile.audience),desire:safe(profile.desire),objection:safe(profile.objection),proof:safe(profile.proof)};
}
export function clipPurpose(scene={},goal='awareness',industry='other',customer={}){
 const buyer=customerDecision(customer);
 const intent=OBJECTIVES[goal]||OBJECTIVES.awareness;
 const sector=INDUSTRY[industry]||INDUSTRY.other;
 const start=Number(scene.start_s),end=Number(scene.end_s);
 const duration=Number.isFinite(start)&&Number.isFinite(end)&&end>start?end-start:null;
 const original=typeof scene.title==='string'?scene.title.trim():'';
 const title=original&&!/^visual scene\s*\d+$/i.test(original)
   ?original.slice(0,100):`Footage to review · ${Number.isFinite(start)&&start>=0?start.toFixed(0):'0'}s`;
 const durationWarning=duration!==null&&duration<15?
   'This short window may be B-roll rather than a complete standalone post. Review the surrounding footage.':
   duration!==null&&duration>60?'Check pacing and consider a tighter cut without losing context.':'';
 return {title,objective:intent.label,industry:sector.label,
   customerAudience:buyer.audience||'Customer not defined',
   buyingMotivation:buyer.desire||'Find out what customers value before choosing a hook.',
   buyerObjection:buyer.objection||'Discover the biggest hesitation before building a conversion edit.',
   evidenceNeeded:buyer.proof||'Identify genuine evidence in the footage and verify it.',
   intendedBenefit:intent.purpose,proposedUse:sector.use,
   reviewAction:`${sector.check} ${intent.next}`,
   durationWarning,evidence:'Editorial suggestion only — footage, suitability and marketing outcomes not verified',verified:false};
}
