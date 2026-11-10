export const saleCurrencies=['USD','GBP','EUR','AUD','CAD','NZD','INR','SGD','ZAR','AED'];
export const blankSale=()=>({amount:'',currency:'',date:'',sourceReference:'',state:'recorded',correctionNote:''});

export const observedSales=data=>[...(data.sale?[data.sale]:[]),...(data.purchases||[])];

// Integer minor units avoid rounding when summing owner-entered decimal strings.
// The 1,000-contact / 51-sale / 999999999.99 bounds keep sums within safe integers.
export function saleTotals(leads,from,through){
  const totals=new Map();
  let voided=0;
  for(const lead of leads)for(const sale of observedSales(lead.data)){
    if(!sale||sale.date>through||(from&&sale.date<from))continue;
    if(sale.state==='voided'){voided++;continue;}
    if(sale.state!=='recorded'||!saleCurrencies.includes(sale.currency)||!/^\d{1,9}\.\d{2}$/.test(sale.amount))continue;
    const [whole,fraction]=sale.amount.split('.');
    const row=totals.get(sale.currency)||{currency:sale.currency,count:0,minor:0};
    row.count++;row.minor+=Number(whole)*100+Number(fraction);totals.set(sale.currency,row);
  }
  return {rows:[...totals.values()].sort((a,b)=>a.currency.localeCompare(b.currency)).map(row=>({
    currency:row.currency,count:row.count,amount:Math.floor(row.minor/100)+'.'+String(row.minor%100).padStart(2,'0'),
  })),voided};
}

// Same all-date current-snapshot rule as the private business overview.
export function repeatPurchaseReview(data,through){
  const purchases=observedSales(data).filter(sale=>sale?.state==='recorded'&&sale.date&&sale.date<=through&&saleCurrencies.includes(sale.currency));
  const task=data.customerCare?.retention;
  const repeat=purchases.length>=2;
  return {repeat,withoutOpenRetention:repeat&&!(task?.state==='open'&&task.action?.trim())};
}
