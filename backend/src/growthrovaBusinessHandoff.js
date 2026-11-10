import {enquiryHandoff} from './growthrovaLeadRegister.js';

const key=row=>JSON.stringify([row.campaignId,row.id]);
const changed=()=>new Error('Selected enquiries changed or are no longer accessible. Close this handoff, refresh saved contacts and choose the export again.');

/** Sequential private reads, with no writes or retained full-record cache. */
export async function businessHandoff({api,endpoint,contacts,filters,observedAt,active,onProgress}){
  if(!contacts.length||contacts.length>1000||new Set(contacts.map(key)).size!==contacts.length)throw changed();
  const selected=new Map(contacts.map(row=>[key(row),row]));
  const loaded=new Map();
  const campaigns=[...new Set(contacts.map(row=>row.campaignId))];
  for(const campaign of campaigns){
    if(!active())return null;
    const value=await api(endpoint+'/'+encodeURIComponent(campaign)+'/leads');
    if(!active())return null;
    if(!Array.isArray(value.leads))throw changed();
    for(const row of value.leads){
      const expected=selected.get(key(row));
      if(!expected)continue;
      if(row.campaignId!==campaign||!Number.isInteger(row.revision)||row.revision!==expected.revision||!row.data||loaded.has(key(row)))throw changed();
      loaded.set(key(row),row);
    }
    onProgress(loaded.size,contacts.length);
  }
  if(loaded.size!==contacts.length)throw changed();
  // Check current business access and selected revisions once more. This is a
  // checked collection of saved versions, not an atomic multi-campaign backup.
  const latest=await api(endpoint+'/contacts');
  if(!active())return null;
  if(!Array.isArray(latest.contacts))throw changed();
  const current=new Map(latest.contacts.map(row=>[key(row),row]));
  if(contacts.some(row=>current.get(key(row))?.revision!==row.revision))throw changed();
  const handoff=enquiryHandoff(contacts.map(row=>loaded.get(key(row))),filters,new Date().toISOString());
  return {...handoff,selectionObservedAt:observedAt,
    notice:handoff.notice+' Business-filtered selection from the saved contact snapshot; later arrivals are excluded. Each selected revision was checked again before preparation. This is not an atomic snapshot across campaigns.'};
}
