// Reference equality is only a review aid, not payment identity or deduplication.
// Index the full saved snapshot so filters never hide a conflicting record.
export function saleReferenceReview(sales){
  const references=new Map();
  for(const record of sales){
    const reference=(record.data.sale.sourceReference||'').trim();
    if(!reference)continue;
    const group=references.get(reference)||{count:0,recorded:0,voided:0};
    group.count++;
    if(record.data.sale.state==='recorded')group.recorded++;
    if(record.data.sale.state==='voided')group.voided++;
    references.set(reference,group);
  }
  return {
    repeatedGroups:[...references.values()].filter(group=>group.count>1).length,
    rows:sales.map(record=>{
      const reference=(record.data.sale.sourceReference||'').trim();
      return {record,reference,group:references.get(reference)||{count:0,recorded:0,voided:0}};
    }),
  };
}

export function filterSaleReview(rows,filters){
  if(filters.from&&filters.through&&filters.from>filters.through)return [];
  const query=(filters.query||'').normalize('NFKC').toLocaleLowerCase().trim();
  return rows.filter(({record,reference,group})=>{
    const sale=record.data.sale;
    return (!filters.state||sale.state===filters.state)&&(!filters.currency||sale.currency===filters.currency)
      &&(!filters.from||sale.date>=filters.from)&&(!filters.through||sale.date<=filters.through)
      &&(!filters.reference||filters.reference===reference)
      &&(!filters.repeated||group.count>1)
      &&(!query||[record.data.name,record.campaignName,reference].some(value=>(value||'').normalize('NFKC').toLocaleLowerCase().includes(query)));
  }).sort((a,b)=>b.record.data.sale.date.localeCompare(a.record.data.sale.date)
    ||b.record.updated-a.record.updated||a.record.campaignId.localeCompare(b.record.campaignId)
    ||a.record.id.localeCompare(b.record.id)||a.record.saleKey.localeCompare(b.record.saleKey));
}
