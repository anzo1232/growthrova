export const purchaseFields={amount:'Sale value',currency:'Currency',date:'Observed date (UTC)',
  sourceReference:'Source reference',state:'Record state',correctionNote:'Correction or void explanation'};

export function editablePurchases(data){
  return {sale:data.sale?{...data.sale}:undefined,purchases:(data.purchases||[]).map(item=>({...item}))};
}

// Compare saved identities, never array positions: removing an unsaved purchase
// must not relabel a different saved record as a correction.
export function purchaseReviewChanges(data,draft){
  if(!draft)return [];
  const records=[{key:'original',label:'First sale',before:data.sale,after:draft.sale},
    ...draft.purchases.map((after,index)=>({key:'purchase:'+after.id,label:'Additional purchase '+(index+1),
      before:data.purchases?.find(item=>item.id===after.id),after})),
    ...(data.purchases||[]).filter(item=>!draft.purchases.some(next=>next.id===item.id))
      .map(before=>({key:'purchase:'+before.id,label:'Saved purchase',before,after:undefined}))];
  return records.filter(row=>Boolean(row.before)!==Boolean(row.after)||
    Object.keys(purchaseFields).some(key=>row.before?.[key]!==row.after?.[key]))
    .map(row=>({...row,fields:Object.keys(purchaseFields).filter(key=>row.before?.[key]!==row.after?.[key])}));
}

export function reviewedPurchasePatch(data,draft){
  const changes=purchaseReviewChanges(data,draft);
  // Historically absent optional fields stay absent when other enquiry data is
  // saved. A discarded new record produces no patch.
  return {...(changes.some(row=>row.key==='original')?{sale:draft.sale}:{}),
    ...(changes.some(row=>row.key!=='original')?{purchases:draft.purchases}:{})};
}
