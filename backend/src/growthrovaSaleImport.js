import {readImportCsv} from './growthrovaLeadImport.js';
import {blankSale,observedSales,saleCurrencies} from './growthrovaSales.js';

export const saleImportHeaders=['amount','currency','date','sourceReference'];

export function previewSaleCsv(text,data,today){
  const records=readImportCsv(text);
  if(records.length<2||records.length>51)throw Error('Include a header and between 1 and 50 purchase rows.');
  const headers=records.shift().map(value=>value.trim());
  if(headers.length!==4||new Set(headers).size!==4||headers.some(key=>!saleImportHeaders.includes(key)))
    throw Error('Use exactly these columns: '+saleImportHeaders.join(', ')+'.');
  const seen=new Set(observedSales(data).map(sale=>sale.sourceReference.trim()));
  return records.map((values,index)=>{
    const sale={...blankSale(),...Object.fromEntries(headers.map((key,i)=>[key,(values[i]||'').trim()]))};
    const errors=[];
    if(values.length!==headers.length)errors.push('Column count differs from header');
    if(!/^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$/.test(sale.amount)||!/[1-9]/.test(sale.amount))errors.push('Use a positive value up to 999999999.99 with up to two decimal places');
    else {const [whole,fraction='']=sale.amount.split('.');sale.amount=whole+'.'+fraction.padEnd(2,'0');}
    if(!saleCurrencies.includes(sale.currency))errors.push('Choose a supported currency');
    if(!/^\d{4}-\d{2}-\d{2}$/.test(sale.date)||sale.date.startsWith('0000')||!Number.isFinite(Date.parse(sale.date))||
      new Date(sale.date).toISOString().slice(0,10)!==sale.date||sale.date>today)errors.push('Use a real observed date through today (UTC)');
    if(!sale.sourceReference||[...sale.sourceReference].length>512||/[\x00-\x1f\x7f]/.test(sale.sourceReference))errors.push('Use a single-line order or receipt reference of up to 512 characters');
    if(seen.has(sale.sourceReference))errors.push('Source reference repeats an existing sale or earlier CSV row');
    if(!errors.length)seen.add(sale.sourceReference);
    return {number:index+1,sale,errors};
  });
}

export function prepareSaleImport(rows,data,today,newId){
  if(!rows.length)throw Error('Choose at least one valid purchase.');
  // Revalidate at the preparation boundary: local manual edits may have changed
  // after preview. The server still validates the eventual enquiry save.
  const seen=new Set(observedSales(data).map(sale=>sale.sourceReference.trim()));
  for(const row of rows){
    if(row.errors.length||seen.has(row.sale.sourceReference))throw Error('Purchase details changed or a source reference now repeats. Preview the CSV again.');
    if(row.sale.date>today)throw Error('Preview the CSV again to review its observed dates.');
    seen.add(row.sale.sourceReference);
  }
  const remaining=[...rows];
  const sale=data.sale||remaining.shift().sale;
  if((data.purchases?.length||0)+remaining.length>50)throw Error('This selection exceeds the 50 additional purchases allowed per enquiry. Select fewer rows.');
  return {sale,purchases:[...(data.purchases||[]),...remaining.map(row=>({...row.sale,id:newId()}))]};
}
