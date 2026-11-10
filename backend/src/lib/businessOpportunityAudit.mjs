import {businessTypeStrategy} from './businessTypeStrategy.mjs';
const clean=(v,n=160)=>typeof v==='string'?v.trim().slice(0,n):'';
export function businessOpportunityAudit({website='',description='',goal='enquiries'}={}){
 const desc=clean(description,500),url=clean(website,240);
 if(!desc&&!url)throw new TypeError('Describe your business or provide a website');
 let site='';
 if(url){
  let parsed;try{parsed=new URL(url.includes('://')?url:'https://'+url);}catch{throw new TypeError('Enter a valid website address');}
  if(!['https:','http:'].includes(parsed.protocol)||!parsed.hostname.includes('.')||parsed.username||parsed.password)throw new TypeError('Enter a public website address');
  site=parsed.hostname;
 }
 const strategy=businessTypeStrategy({businessType:desc});
 const goalText={bookings:'bookings',enquiries:'enquiries',awareness:'awareness',education:'trust',offers:'approved offers'}[goal]||'enquiries';
 const suggested=[
  {name:'Video content studio',task:strategy.focus,required:'Original authorised footage and review of the actual content'},
  {name:'Social content campaigns',task:'Prepare platform-specific hooks, captions and content plans.',required:'Approved brand voice, offers and channel access'},
  {name:'Customer conversion path',task:`Make the next step towards ${goalText} easy to understand.`,required:'Verified contact, booking or checkout destination'},
  {name:'Marketing calendar',task:'Plan a manageable publishing cadence across relevant channels.',required:'Publishing capacity and approved accounts'},
  {name:'Performance review',task:'Track genuine customer actions and learn which content performs.',required:'Connected analytics, lead or booking data'}
 ];
 return {website:site,businessDescription:desc||'Business type not supplied',goal:goalText,
  categoryMethod:desc?strategy.source:'Undetermined — website content has not been fetched',
  editingApproach:desc?strategy.focus:'Confirm business activities before choosing video edits',
  opportunities:suggested,verifiedWebsite:false,status:'Illustrative audit based on supplied information; website not scanned',
  review:'Confirm business activities and every offer or claim before use.'};
}
