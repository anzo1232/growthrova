import test from 'node:test';import assert from 'node:assert/strict';
import {prepareUrlCampaign,attachGeneratedAsset} from '../src/lib/businessUrlCampaignPipeline.mjs';
const audit={source_url:'https://example.org/',observations:{title:'Example restaurant',meta_description:'Seasonal dining in our local restaurant',headings:['Our menu','Book a table']}};
test('one URL audit automatically yields a plan and distinct creative without spending',()=>{
 const result=prepareUrlCampaign(audit);
 assert.equal(result.sector,'restaurant');assert.equal(result.plan.posts.length,30);
 assert.ok(result.creative.prompt.includes('Seasonal dining'));
 assert.equal(result.canSpend,false);assert.equal(result.canPublish,false);assert.equal(result.creative.assetUrl,null);
 assert.ok(result.plan.posts.every(p=>!p.scheduled&&!p.published));
});
test('short site evidence never becomes fake complete campaign',()=>{
 const result=prepareUrlCampaign({...audit,observations:{title:'Example salon',meta_description:'Spa'}});
 assert.equal(result.status,'needs_more_website_evidence');assert.equal(result.plan,null);
});
test('no fake generated assets, duplicate jobs or automatic approval',()=>{
 const campaign=prepareUrlCampaign(audit);
 assert.throws(()=>attachGeneratedAsset(campaign,{status:'completed',url:'https://example.org/result.png',jobId:'abc'}));
 const attached=attachGeneratedAsset(campaign,{status:'completed',url:'https://example.org/result.png',jobId:'abc'},{verifiedProvider:true});
 assert.equal(attached.canPublish,false);assert.equal(attached.creative.approvalStatus,'awaiting_owner_review');
 assert.throws(()=>attachGeneratedAsset(attached,{status:'completed',url:'https://example.org/result2.png',jobId:'def'},{verifiedProvider:true}));
 assert.throws(()=>attachGeneratedAsset(campaign,{status:'pending',url:'https://example.org/result.png',jobId:'abc'},{verifiedProvider:true}));
});
test('rich website evidence identifies a roofer and uses actual paragraph facts when meta description is missing',()=>{
 const rich=prepareUrlCampaign({source_url:'https://roofing.example.org/',observations:{
  title:'Harbour Roofing Portsmouth',meta_description:'',headings:['Repair your roof'],
  visible_paragraphs:['Roof tile replacement, leaking roof repair, gutter clearing and flat roof inspections in Portsmouth.'],
  service_links:[{url:'https://roofing.example.org/services/roof-repairs',label:'Roof repairs'}],
  image_candidates:[{url:'https://roofing.example.org/roof-work.jpg',alt:'Roof tiling work',rights_confirmed:false}]
 }});
 assert.equal(rich.sector,'roofing');assert.equal(rich.plan.posts.length,30);
 assert.match(rich.creative.prompt,/gutter clearing/i);
 assert.ok(rich.observedFacts.some(x=>/tile replacement/i.test(x)));
 assert.equal(rich.websiteImages.length,1);assert.equal(rich.websiteImages[0].rights_confirmed,false);
 assert.equal(rich.canPublish,false);
});

test('Cedar Portsmouth cannot silently inherit a different London restaurant website',()=>{
 const london={source_url:'https://www.thecedarrestaurant.co.uk/',observations:{
  title:'The Cedar Restaurant',meta_description:'Authentic Lebanese cuisine in London',
  visible_paragraphs:['Our locations are in London. Our family recipes have been here since 1997.']}};
 assert.throws(()=>prepareUrlCampaign(london,{expectedLocation:'Portsmouth'}),/identity mismatch/i);
 assert.throws(()=>prepareUrlCampaign(london,{expectedDomain:'cedarportsmouth.co.uk'}),/identity mismatch/i);
 const londonByCorrectLocation=prepareUrlCampaign(london,{expectedLocation:'London',expectedDomain:'thecedarrestaurant.co.uk'});
 assert.equal(londonByCorrectLocation.canPublish,false);
});
test('Portsmouth Cedar facts remain independent of the London brand',()=>{
 const portsmouth={source_url:'https://cedarportsmouth.co.uk/',observations:{
  title:'Cedar Portsmouth',meta_description:'Lebanese restaurant at 49 Albert Road, Southsea, Portsmouth',
  visible_paragraphs:['Join us for mezze and Lebanese tea in Portsmouth, contact us to book.']}};
 const prepared=prepareUrlCampaign(portsmouth,{expectedLocation:'Portsmouth',expectedDomain:'cedarportsmouth.co.uk'});
 assert.equal(prepared.business,'Cedar Portsmouth');
 assert.equal(prepared.canSpend,false);assert.equal(prepared.canPublish,false);
 assert.ok(prepared.plan.posts.length===30);
});

test('deep club evidence reaches distinct unconfirmed calendar directions with exact page provenance',()=>{
 const root={source_url:'https://club.example.org/',status:'extracted_unconfirmed',observations:{
  title:'Synthetic Country Club',meta_description:'Discover dining at our country club.',
  headings:Array.from({length:12},(_,i)=>'Welcome to our club '+i),
  visible_paragraphs:Array.from({length:12},(_,i)=>'Explore our club and find out more about us '+i)}};
 const page=(path,quote)=>({source_url:root.source_url+path,status:'extracted_unconfirmed',observations:{headings:[],visible_paragraphs:[quote]}});
 const expanded={...root,page_reports:[root,page('membership','Membership enquiries start with a conversation about your interests.'),
  page('spa','Our spa treatment descriptions explain the consultation process.'),page('fitness','Fitness classes include guided group sessions; ask about the current timetable.')]};
 const before=prepareUrlCampaign(root),after=prepareUrlCampaign(expanded);
 assert.equal(after.sector,'country_club');
 assert.notDeepEqual(after.plan.posts,before.plan.posts);
 for(const [path,word] of [['membership','Membership enquiries'],['spa','spa treatment'],['fitness','Fitness classes']]){
  const post=after.plan.posts.find(p=>p.copyDraft.includes(word));
  assert.ok(post,word+' missing from downstream directions');
  assert.ok(post.copyDraft.includes(root.source_url+path));
  assert.ok(post.copyDraft.startsWith('Draft direction: '));
  assert.match(post.copyDraft,/unconfirmed|confirm/i);
 }
 assert.ok(after.editorialShortlist.candidates.length===3);
 assert.ok(after.editorialShortlist.candidates.some(c=>c.evidence.sourceUrl?.endsWith('/membership')));
 assert.equal(after.canPublish,false);assert.equal(after.canSpend,false);
 const foreign={...expanded,page_reports:[root,page('membership','Membership enquiries welcome.'),{...page('spa','Our spa treatment descriptions explain consultation.'),source_url:'https://foreign.example.org/spa'}]};
 assert.throws(()=>prepareUrlCampaign(foreign),/same.*site|source/i);
});
test('trade service evidence is distinct from club and dining plans',()=>{
 const result=prepareUrlCampaign({source_url:'https://trade.example.org/',observations:{title:'Synthetic Plumbing',
  meta_description:'Plumbing and heating services. Contact us to discuss repairs.',visible_paragraphs:[
   'Plumbing repairs start with a description of the water leak.',
   'Heating and boiler enquiries need details of the equipment.',
   'Contact the team to discuss a quotation for the proposed work.']}});
 assert.equal(result.sector,'plumbing');
 assert.ok(result.plan.posts.some(p=>p.copyDraft.includes('water leak')));
 assert.ok(result.plan.posts.some(p=>p.copyDraft.includes('boiler')));
 assert.ok(result.editorialShortlist.candidates.length===3);
 assert.ok(result.unverifiedInferences.includes('Target audience'));
});
