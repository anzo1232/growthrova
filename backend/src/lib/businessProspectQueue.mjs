import {qualificationDecision,prospectPreparationGaps,matchesProspectReview} from '../growthrovaProspectReview.mjs';

/** Saved preparation only. Separate records never imply unique businesses or enquiries. */
export function prospectQueue(records){
  const items=[];
  for(const record of records){
    for(const item of record.document.prospects||[]){
      items.push({campaignId:record.id,revision:record.revision,campaignName:record.document.name,
        id:item.id,name:item.name,status:item.status,sourceUrl:item.sourceUrl,observedOn:item.observedOn,
        fit:item.fit,nextAction:item.nextAction,decision:qualificationDecision(item),
        qualification:{decision:qualificationDecision(item),reason:item.qualification?.reason||''},
        gaps:prospectPreparationGaps(item)});
    }
  }
  return {campaignCount:records.length,items:items.sort((a,b)=>a.name.localeCompare(b.name)||
    a.campaignName.localeCompare(b.campaignName)||a.campaignId.localeCompare(b.campaignId)||a.id.localeCompare(b.id))};
}

export function filterProspectQueue(items,{query='',decision='all',preparation='all',status=''}={}){
  return items.filter(item=>{
    if(status&&item.status!==status)return false;
    // The queue deliberately omits contact details and wording. Reuse qualification
    // and search semantics, but use gaps computed from the complete saved record.
    if(!matchesProspectReview(item,{decision}))return false;
    if(preparation==='missing'&&!item.gaps.length)return false;
    if(preparation==='review'&&!matchesProspectReview(item,{preparation:'review'}))return false;
    return item.campaignName.toLowerCase().includes(query.trim().toLowerCase())||matchesProspectReview(item,{query});
  });
}
