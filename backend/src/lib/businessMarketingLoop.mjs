/** A truthful readiness plan: stages never imply integrations ran. */
export function marketingLoop(audit){
 if(!audit||!Array.isArray(audit.opportunities))throw new TypeError('Business opportunity audit required');
 const steps=[
  {id:'learn',name:'Learn your business',description:'Confirm the services, customers, brand and desired business outcome.',needs:'Business description or verified website analysis',status:'brief_started'},
  {id:'research',name:'Research the market',description:'Review actual competitor evidence, customer questions and existing content gaps.',needs:'Authorised public-source research and provenance',status:'not_started'},
  {id:'create',name:'Create content',description:'Build useful video clips, graphics, captions and campaign drafts.',needs:'Approved footage, verified facts and brand assets',status:'not_started'},
  {id:'launch',name:'Publish approved campaigns',description:'Schedule approved organic posts and prepare ads within authorised budgets.',needs:'Connected accounts and explicit publishing approval',status:'not_started'},
  {id:'learn_again',name:'Measure and improve',description:'Connect real enquiries, bookings or sales and develop the next campaign.',needs:'Real channel and conversion analytics',status:'not_started'}
 ];
 if(!audit.businessDescription||audit.businessDescription==='Business type not supplied')steps[0].status='needs_business_details';
 return {version:1,steps,verifiedWebsite:false,publishingEnabled:false,analyticsConnected:false,
  nextAction:steps[0].status==='needs_business_details'?'Describe what your business sells.':'Confirm the customer, offer and brand before creating a campaign.',
  evidence:'A planning preview only. No research, content generation, publishing or campaign measurement has run.'};
}
