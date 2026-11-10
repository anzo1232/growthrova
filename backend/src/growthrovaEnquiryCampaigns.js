/** Saved, scoped campaign choices for direct business enquiry intake. */
export function enquiryCampaigns(value){
  const records=value.documents||value.drafts;
  if(!Array.isArray(records))throw Error('Saved campaign choices are unavailable. Retry loading campaigns.');
  return records.filter(row=>/^[a-f0-9]{32}$/.test(row.id)&&Number.isInteger(row.revision)&&row.revision>0&&typeof row.document?.name==='string')
    .map(row=>({id:row.id,name:row.document.name}));
}
