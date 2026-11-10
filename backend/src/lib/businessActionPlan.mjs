/** Conversion-oriented planning, never claims execution or verified outcomes. */
export function businessActionPlan(audit){
 if(!audit||!Array.isArray(audit.opportunities))throw new TypeError('Opportunity audit required');
 const hasDescription=Boolean(audit.businessDescription&&audit.businessDescription!=='Business type not supplied');
 const tasks=[
  {id:'profile',priority:1,title:'Confirm business profile',why:'Avoid irrelevant content and invented business claims.',requires:['Business description','Confirmed products or services','Ideal customer','Approved offer'],ready:hasDescription,approval:'Business owner'},
  {id:'cta',priority:2,title:`Define a ${audit.goal||'customer enquiry'} conversion path`,why:'Content should guide customers towards a meaningful next step.',requires:['Verified booking, enquiry or checkout URL','Owner-approved CTA'],ready:false,approval:'Business owner'},
  {id:'assets',priority:3,title:'Prepare source material',why:'Authentic footage and testimonials are needed for credible marketing.',requires:['Rights-cleared videos or images','Brand kit','Testimonial consent where relevant'],ready:false,approval:'Business owner'},
  {id:'campaign',priority:4,title:'Draft first campaign',why:'Produce a useful week of content from the confirmed strategy.',requires:['Validated customer brief','Reviewed footage','Approved claims'],ready:false,approval:'Editor and business owner'},
  {id:'publish',priority:5,title:'Connect and schedule approved channels',why:'Make delivery consistent without unapproved posts.',requires:['Connected social accounts','Final content approval','Publishing dates'],ready:false,approval:'Account owner'},
  {id:'measure',priority:6,title:'Measure actual customer actions',why:'Compare content with enquiries or bookings, not views alone.',requires:['Connected analytics','Appropriate conversion tracking'],ready:false,approval:'Account owner'}
 ];
 return {version:1,tasks,readyCount:tasks.filter(t=>t.ready).length,status:'Proposed action plan — nothing has been published or connected',nextTask:tasks.find(t=>!t.ready)?.id||null};
}
