import {strategyConfirmed,confirmedBriefPostCopy} from './businessOwnerStrategy.mjs';

/** Exact owner wording only. Platform field bounds are preparation limits. */
export function paidStrategySuggestions(doc,platform){
  if(!['meta','google'].includes(platform))throw new TypeError('Choose a paid platform');
  if(!strategyConfirmed(doc))return [];
  const strategy=doc.ownerStrategy;
  const goal={enquiries:'leads',bookings:'leads',awareness:platform==='meta'?'awareness':'traffic',education:'traffic'}[doc.goal];
  const fields=[{key:'audience',label:'Audience',value:strategy.audience,limit:1000}];
  if(goal)fields.unshift({key:'objective',label:'Proposed paid goal',value:goal,
    note:doc.goal==='bookings'?'Enquiries is a preparation goal; booking tracking still needs setup.':
      doc.goal==='awareness'&&platform==='google'?'Website visits is a Search preparation choice, not an awareness objective.':''});
  let destination='';
  try{
    const url=new URL(doc.sourceUrl);
    if(url.protocol==='https:'&&!url.username&&!url.password&&!/[\\\s\x00-\x1f\x7f]/.test(doc.sourceUrl)&&doc.sourceUrl.length<=512)destination=doc.sourceUrl;
  }catch{/* Missing source is not an invented destination. */}
  if(destination)fields.push({key:'destinationUrl',label:'Website destination',value:destination,limit:512,
    note:'Saved research page only. Confirm this is the right landing page; it has not been checked again.'});
  if(platform==='meta')fields.push(
    {key:'primaryText',label:'Advert text',value:confirmedBriefPostCopy(doc).copyDraft,limit:3000},
    {key:'headline',label:'Headline',value:strategy.offer,limit:180},
    {key:'callToAction',label:'Call to action',value:strategy.callToAction,limit:80});
  else fields.push(
    {key:'headlines',label:'Headline options',value:[doc.business,strategy.offer].filter((v,i,a)=>v.trim()&&a.indexOf(v)===i),limit:30},
    {key:'descriptions',label:'Description options',value:[strategy.offer,strategy.positioning].filter((v,i,a)=>v.trim()&&a.indexOf(v)===i),limit:90});
  return fields.map(field=>({...field,blocked:(Array.isArray(field.value)?field.value:[field.value]).some(v=>field.limit&&v.length>field.limit)}));
}

/** Recompute against the current document, never a retained UI snapshot. */
export function applyPaidStrategyField(doc,platform,key){
  const property=platform==='meta'?'paidCampaign':platform==='google'?'googleCampaign':null;
  if(!property||!doc[property])throw new TypeError('Start the paid draft first');
  const field=paidStrategySuggestions(doc,platform).find(item=>item.key===key);
  if(!field||field.blocked)throw new TypeError('Confirm the current strategy and check the field length before copying');
  return {...doc,[property]:{...doc[property],[key]:structuredClone(field.value)}};
}
