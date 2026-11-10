// Saved CRM snapshots only. Explicit nested fields prevent new transport fields
// from silently entering a downloaded file. This is a handoff, not a restore.
const fields=names=>Object.fromEntries(names.split(' ').map(key=>[key,null]));
const task=fields('action responsiblePerson dueDate state channel wording');
const sale=fields('amount currency date sourceReference state correctionNote');
const rule=fields('enabled startDate intervalDays action responsiblePerson channel wording');
const progress=fields('ruleFingerprint dueDate count');
const schema={
  ...fields('name email phone source sourceReference status qualification booking notes emailPermission whatsappPermission permissionNotes responsiblePerson nextAction actionDueDate actionState followUpChannel followUpDraft'),
  customerCare:{
    booking:{...fields('state scheduledDate outcomeDate reference evidence'),
      appointment:fields('localStart localEnd timeZone utcStart utcEnd')},
    retention:task,review:task,repeatRules:{retention:rule,review:rule},
    repeatProgress:{retention:progress,review:progress},
    background:fields('enabled throughDate maxOccurrences'),
  },
  sale,purchases:[{id:null,...sale}],
  prospectOrigin:fields('prospectId name sourceUrl sourceQuote observedOn responseNote campaignRevision'),
  providerOrigin:fields('platform verification accountId formId eventId submittedAt campaignReference'),
};
function project(value,shape){
  if(shape===null)return value===null||['string','number','boolean'].includes(typeof value)?value:undefined;
  if(Array.isArray(shape))return Array.isArray(value)?value.map(item=>project(item,shape[0])):undefined;
  if(!value||typeof value!=='object'||Array.isArray(value))return undefined;
  return Object.fromEntries(Object.entries(shape).filter(([key])=>Object.hasOwn(value,key))
    .map(([key,child])=>[key,project(value[key],child)]).filter(([,item])=>item!==undefined));
}
export const handoffData=data=>project(data,schema);

// Quote every cell and use CRLF. Apostrophes guard formula prefixes (including
// leading whitespace/control characters); JSON retains the exact original text.
function cell(value){
  let text=value===null||value===undefined?'':String(value);
  if(/^[\s\u0000-\u001f\u007f]*[=+@-]/u.test(text)||/^[\t\r\n]/.test(text))text="'"+text;
  return '"'+text.replaceAll('"','""')+'"';
}
const identity=['campaignId','enquiryId','revision','createdUnix','updatedUnix','name','email','phone','emailPermission','whatsappPermission','permissionNotes'];
const base=lead=>({campaignId:lead.campaignId,enquiryId:lead.id,revision:lead.revision,createdUnix:lead.created,updatedUnix:lead.updated,
  ...Object.fromEntries(identity.slice(5).map(key=>[key,lead.data[key]]))});
const contactFields=['source','sourceReference','status','qualification','booking','notes'];
const bookingFields=['state','scheduledDate','outcomeDate','reference','evidence'];
const appointmentFields=['localStart','localEnd','timeZone','utcStart','utcEnd'];
const taskFields=Object.keys(task);
const saleFields=Object.keys(sale);
export const enquiryCsvViews={enquiries:'Enquiries and bookings',tasks:'Prepared human tasks',purchases:'Recorded and voided purchases'};

export function enquirySpreadsheet(handoff,view='enquiries'){
  let columns,rows=[];
  if(view==='enquiries'){
    columns=[...identity,...contactFields,...bookingFields.map(key=>'booking.'+key),...appointmentFields.map(key=>'appointment.'+key)];
    rows=handoff.enquiries.map(lead=>({...base(lead),
      ...Object.fromEntries(contactFields.map(key=>[key,lead.data[key]])),
      ...Object.fromEntries(bookingFields.map(key=>['booking.'+key,lead.data.customerCare?.booking?.[key]])),
      ...Object.fromEntries(appointmentFields.map(key=>['appointment.'+key,lead.data.customerCare?.booking?.appointment?.[key]]))}));
  }else if(view==='tasks'){
    columns=[...identity,'taskKind',...taskFields];
    for(const lead of handoff.enquiries){
      const data=lead.data;
      const tasks={followThrough:{action:data.nextAction,responsiblePerson:data.responsiblePerson,dueDate:data.actionDueDate,
        state:data.actionState,channel:data.followUpChannel,wording:data.followUpDraft},
        retention:data.customerCare?.retention,review:data.customerCare?.review};
      for(const [taskKind,item] of Object.entries(tasks))if(item?.action?.trim())rows.push({...base(lead),taskKind,...item});
    }
  }else if(view==='purchases'){
    columns=[...identity,'purchaseKey',...saleFields];
    for(const lead of handoff.enquiries){
      if(lead.data.sale)rows.push({...base(lead),purchaseKey:'original',...lead.data.sale});
      for(const purchase of lead.data.purchases||[])rows.push({...base(lead),purchaseKey:'purchase:'+purchase.id,...purchase});
    }
  }else throw new Error('Choose a supported enquiry spreadsheet.');
  // Provenance accompanies every row without mixing metadata into the table.
  columns=['exportedAt',...columns];
  return {count:rows.length,content:'\uFEFF'+[columns,...rows.map(row=>columns.map(key=>key==='exportedAt'?handoff.exportedAt:row[key]))]
    .map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n'};
}
