import {assessCreativeReadiness} from './businessCreativeQuality.mjs';
/** AI-first marketing creative specifications; no images or video fabricated. */
const text=(value,max=160)=>typeof value==='string'?value.trim().slice(0,max):'';
export function creativeBlueprint({business='',offer='',audience='',goal='enquiries',differentiator='',brandTone='professional',confirmed=false}={}){
 const name=text(business,120),product=text(offer),customer=text(audience),difference=text(differentiator);
 if(!name||!product||!customer)throw new TypeError('Business name, offer and audience must be confirmed');
 const stages=[
  {id:'hook',title:'Problem-to-solution',format:'9:16 video ad',aim:'Help the audience recognise a problem and see the approved offer.'},
  {id:'proof',title:'Evidence-led carousel',format:'4:5 carousel',aim:'Address purchase hesitations with real, verifiable evidence.'},
  {id:'explain',title:'Educational graphic',format:'4:5 informational post',aim:'Explain how the product or service works without unsupported promises.'},
  {id:'action',title:'Conversion creative',format:'9:16 video or static ad',aim:'Present the approved offer with a clear, genuine next step.'}
 ];
 return {business:name,offer:product,audience:customer,goal:text(goal,30)||'enquiries',
  mode:'AI-generated creative briefs',approval:'Business approval required before generation or publishing',
  profileConfirmed:Boolean(confirmed),generationEnabled:false,
  creatives:stages.map((stage,index)=>({...stage,id:`creative-${index+1}`,
    brief:`Create a ${stage.format} for ${name}, offering ${product} to ${customer}. Tone: ${text(brandTone,60)}. ${difference?`Positioning supplied by the business: ${difference}.`:''} ${stage.aim} Use approved brand assets only. Do not depict real clients, testimonials, performance statistics or credentials without verified source material.`,
    needsApproval:['Business claims and offer','Brand visuals and identity','Any depicted people or testimonials','Final CTA'],
    status:'brief_only_not_generated',verifiedClaims:false}))};
}
