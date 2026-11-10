import {handoffData} from './growthrovaEnquiryHandoff.js';
import {followThroughDefaults} from './growthrovaFollowThrough.js';

export const blankEnquiry=()=>({name:'',email:'',phone:'',source:'',sourceReference:'',status:'new',qualification:'',booking:'',
  notes:'',emailPermission:'unknown',whatsappPermission:'unknown',permissionNotes:'',...followThroughDefaults});
// Local views of the existing scoped, saved enquiry response. No dispatch.
const normal=value=>String(value||'').normalize('NFKC').toLowerCase();
const phoneDigits=value=>String(value||'').replace(/\D/g,'');

export function matchesEnquiry(lead,{query='',status='',source=''}={}){
  const data=lead.data;
  if(status&&data.status!==status||source&&data.source!==source)return false;
  const terms=normal(query).trim().split(/\s+/).filter(Boolean);
  const searchable=[data.name,data.email,data.phone,data.source,data.sourceReference,data.responsiblePerson].map(normal).join('\n');
  if(terms.every(term=>searchable.includes(term)))return true;
  // Accept pasted formatted phone numbers without broadening mixed text searches.
  const digits=phoneDigits(query);
  return Boolean(digits.length>=3&&/^[+\d\s().-]+$/.test(query.trim())&&phoneDigits(data.phone).includes(digits));
}

export function enquiryHandoff(leads,filters,exportedAt){
  return {
    format:'growthrova-enquiry-handoff-v2',exportedAt,filters:{...filters},
    notice:'Saved campaign enquiries only. Contains personal contact details. Permission records are observations, not authority to send messages. Includes current structured bookings, purchases (including voided records), customer-care tasks and saved preparation rules. No history, delivery receipts or unsaved edits are included. Not a backup/restore format; recorded sales do not verify payment or attribution.',
    count:leads.length,
    enquiries:leads.map(lead=>({id:lead.id,campaignId:lead.campaignId,revision:lead.revision,created:lead.created,updated:lead.updated,
      data:handoffData(lead.data)}))
  };
}
