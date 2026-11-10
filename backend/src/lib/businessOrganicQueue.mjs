export const organicStatuses={planned:'Planned',drafting:'Drafting',ready_for_review:'Ready for review',handed_off:'Handed to editor',parked:'Parked'};

export function currentOrganicReference(doc,ref){
  if(ref.kind==='search')return true; // Historical immutable snapshot, never current website verification.
  return ref.kind==='fact'
    ? doc.observedFacts?.[ref.index]===ref.quote&&(doc.observedFactSources?.[ref.index]||'')===ref.sourceUrl
    : doc.sourceUrl===ref.sourceUrl&&Boolean(doc.websiteAuditText?.includes(ref.quote));
}

/** Saved preparation only; do not infer delivery from an owner's work status. */
export function organicQueue(records){
  const items=[],empty=[];
  for(const record of records){
    const doc=record.document,base={campaignId:record.id,revision:record.revision,name:doc.name};
    if(!doc.organicWork?.length)empty.push(base);
    for(const item of doc.organicWork||[]){
      items.push({...base,id:item.id,title:item.title,kind:item.kind,status:item.status,
        evidence:item.reference.kind==='search'?'historical':currentOrganicReference(doc,item.reference)?'retained':'changed',
        missingDraft:item.kind==='content'&&!item.draft.trim(),missingAction:!item.nextAction.trim()});
    }
  }
  // Preparation order, then stable campaign/item order; no invented due dates.
  const order=Object.keys(organicStatuses);
  items.sort((a,b)=>order.indexOf(a.status)-order.indexOf(b.status)||a.name.localeCompare(b.name)||a.campaignId.localeCompare(b.campaignId)||a.id.localeCompare(b.id));
  return {items,empty};
}

export function filterOrganicQueue(items,{status='',kind='',review=''}={}){
  return items.filter(item=>(!status||item.status===status)&&(!kind||item.kind===kind)&&
    (!review||(review==='missing_draft'?item.missingDraft:review==='missing_action'?item.missingAction:item.evidence===review)));
}
