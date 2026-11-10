export const prospectStatuses={researching:'Researching',drafting:'Drafting wording',ready_for_review:'Ready for human review',parked:'Parked'};

export const qualificationLabels={unreviewed:'Not reviewed',pursue:'Pursue',hold:'On hold',not_fit:'Not a fit'};

export function qualificationDecision(item){return item.qualification?.decision||'unreviewed';}

export function prospectOutreachAllowed(item){
  return item.status==='ready_for_review'&&!['hold','not_fit'].includes(qualificationDecision(item));
}

// Preparation checks describe the owner's current inputs, never verified facts
// or sender availability. Actual saved email approval remains a separate step.
export function prospectPreparationGaps(item){
  const gaps=[];
  for(const [key,label] of [['sourceUrl','source page'],['sourceQuote','quotation'],['observedOn','observation date'],
    ['fit','fit hypothesis'],['outreachDraft','draft wording'],['nextAction','next human action']]){
    if(!item[key]?.trim())gaps.push(label);
  }
  return gaps;
}

export function matchesProspectReview(item,{query='',decision='all',preparation='all'}={}){
  if(decision!=='all'&&qualificationDecision(item)!==decision)return false;
  if(preparation==='missing'&&!prospectPreparationGaps(item).length)return false;
  if(preparation==='review'&&(item.status!=='ready_for_review'||['hold','not_fit'].includes(qualificationDecision(item))))return false;
  const search=query.trim().toLowerCase();
  return !search||[item.name,item.sourceUrl,item.fit,item.nextAction,item.qualification?.reason]
    .some(value=>value?.toLowerCase().includes(search));
}
