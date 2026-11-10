/** Category-neutral customer decision model. Business input is hypothesis, never proof. */
const JOURNEY=Object.freeze({
 discover:{label:'Discover',question:'Why should I pay attention?',evidence:'A clear problem, outcome or distinctive first impression'},
 consider:{label:'Consider',question:'Is this relevant to me?',evidence:'A useful demonstration, explanation or relatable use case'},
 trust:{label:'Trust',question:'Can I believe this?',evidence:'Genuine demonstration, permissioned testimony or verifiable proof'},
 decide:{label:'Decide',question:'Why choose this business?',evidence:'Specific differentiator, transparent terms and objections addressed'},
 act:{label:'Act',question:'What should I do next?',evidence:'Correct contact, booking, enquiry or purchase path'}
});
const safe=v=>typeof v==='string'?v.trim().slice(0,160):'';
export function decisionFramework(input={}){
 const stage=Object.hasOwn(JOURNEY,input.stage)?input.stage:'consider';
 const step=JOURNEY[stage];
 const action=safe(input.action);
 const offer=safe(input.offer);
 const differentiator=safe(input.differentiator);
 const audience=safe(input.audience);
 return {stage,label:step.label,customerQuestion:step.question,
   evidenceToSeek:step.evidence,action:action||'Choose a clear next step',
   offer:offer||'Describe the actual product or service',
   differentiator:differentiator||'Identify a genuine differentiator',
   audience:audience||'Specify the intended customer',
   status:'Business-supplied strategy — not independently verified'};
}
export const CUSTOMER_JOURNEY_STAGES=Object.entries(JOURNEY).map(([id,x])=>({id,label:x.label}));
