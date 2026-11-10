import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
const root={source_url:'https://club.example.org/',status:'extracted_unconfirmed',observations:{title:'Home | Example Country Club',meta_description:'A country club with membership, fitness, spa and dining.',visible_paragraphs:['Our members enjoy fitness facilities and spa treatments with dining.']}};
test('dedicated page evidence changes club directions and keeps its exact source',()=>{
 const detail={source_url:'https://club.example.org/membership',status:'extracted_unconfirmed',observations:{visible_paragraphs:['Membership includes an introductory club tour and a discussion of the available joining options.']}};
 const first=prepareUrlCampaign(root),next=prepareUrlCampaign({...root,page_reports:[root,detail]});
 assert.equal(next.business,'Example Country Club');
 const membership=next.siteSpecificStory.differentiators.find(x=>x.key==='membership');
 assert.equal(membership.sourceUrl,detail.source_url);
 assert.match(membership.evidence,/introductory club tour/);
 assert.notDeepEqual(first.plan,next.plan);
 assert.equal(next.canPublish,false);
});
test('unconfirmed page requirement remains enforced',()=>{
 assert.throws(()=>prepareUrlCampaign({...root,page_reports:[{...root,status:'approved'}]}),/Invalid unconfirmed/);
});
test('long source paragraphs produce readable exact excerpts in downstream drafts',()=>{
 const sentence='Fitness classes include guided group sessions with a timetable available on request.';
 const paragraph=sentence+' '+('Ask about the current options and discuss your preferences with the team. ').repeat(5);
 const campaign=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[paragraph]}});
 const item=campaign.siteSpecificStory.differentiators.find(x=>x.key==='fitness');
 assert.equal(item.evidence,sentence);
 assert.ok(campaign.plan.posts.some(p=>p.copyDraft.includes(sentence)));
 assert.ok(!item.evidence.endsWith(' '));
 const noSentence='Fitness classes '+('provide a guided session for different interests ').repeat(8);
 const fallback=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[noSentence]}})
  .siteSpecificStory.differentiators.find(x=>x.key==='fitness').evidence;
 assert.ok(noSentence.includes(fallback));
 assert.ok(/\s/.test(noSentence[fallback.length]),'An incomplete source must stop between words');
 assert.ok(fallback.length<=240);
});
test('club directions use distinctive sourced service details instead of broad introductions',()=>{
 const membership='We offer two core types of membership to suit a variety of tastes. Viewings are by advance appointment only.';
 const dining='Our Fuzen restaurant brings together influences from across Asia and South America, with vibrant plates designed for sharing and enjoying.';
 const pages=[root,{source_url:root.source_url+'membership',status:'extracted_unconfirmed',observations:{visible_paragraphs:[
  'Membership is about more than access to a gym and a place to connect with people.',membership]}},
 {source_url:root.source_url+'dine',status:'extracted_unconfirmed',observations:{visible_paragraphs:[
  'Our dining philosophy is built on balance and enjoyment for every moment of the day.',dining]}}];
 const campaign=prepareUrlCampaign({...root,page_reports:pages});
 const members=campaign.siteSpecificStory.differentiators.find(x=>x.key==='membership');
 const food=campaign.siteSpecificStory.differentiators.find(x=>x.key==='dining');
 assert.match(members.evidence,/two core types/);
 assert.match(members.hook,/membership options/i);
 assert.equal(food.evidence,dining);
 assert.match(food.hook,/Fuzen/);
 assert.ok(campaign.plan.posts.some(p=>p.theme.includes('Fuzen')&&p.copyDraft.includes(dining)));
 assert.ok(campaign.editorialShortlist.candidates.some(c=>c.hook.includes('Fuzen')&&c.evidence.sourceUrl.endsWith('/dine')));
 assert.equal(campaign.canSpend,false);
 assert.ok(campaign.siteSpecificStory.differentiators.every(x=>x.ownerConfirmed===false));
});
test('long paragraphs retain the service sentence that justified the direction',()=>{
 const detail='Membership options include a club tour by appointment.';
 const paragraph='Welcome to our club and discover a different way to spend your day. '+detail+' '+
  'Please speak to the team about current availability and the facilities that interest you. '.repeat(3);
 const campaign=prepareUrlCampaign({...root,page_reports:[root,{
  source_url:root.source_url+'membership',status:'extracted_unconfirmed',
  observations:{visible_paragraphs:[paragraph]}}]});
 const item=campaign.siteSpecificStory.differentiators.find(x=>x.key==='membership');
 assert.equal(item.evidence,detail);
 assert.ok(paragraph.includes(item.evidence));
 assert.ok(campaign.plan.posts.some(post=>post.copyDraft.includes(detail)));
 assert.equal(item.ownerConfirmed,false);
 assert.equal(campaign.canPublish,false);
});
test('sentence selection does not expose a word cut by the field length bound',()=>{
 const prefix='Welcome '+('to our club ').repeat(26)+'. ';
 const paragraph=prefix+'Membership options include '+('personalised appointments ').repeat(10);
 const campaign=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[paragraph]}});
 const quote=campaign.siteSpecificStory.differentiators.find(x=>x.key==='membership').evidence;
 const end=paragraph.indexOf(quote)+quote.length;
 assert.ok(quote.includes('Membership options'));
 assert.ok(!/\w/.test(paragraph[end]),'Field clipping must not expose a partial source word');
});
test('service details beyond a long introduction reach source-linked calendar drafts',()=>{
 const detail='Membership options include a guided tour by appointment.';
 const paragraph='Discover our club and the spaces where you can spend your day. '.repeat(9)+detail;
 const url=root.source_url+'membership';
 const campaign=prepareUrlCampaign({...root,page_reports:[root,{
  source_url:url,status:'extracted_unconfirmed',observations:{visible_paragraphs:[paragraph]}}]});
 const item=campaign.siteSpecificStory.differentiators.find(x=>x.key==='membership');
 assert.equal(item.evidence,detail);
 assert.equal(item.sourceUrl,url);
 assert.ok(campaign.plan.posts.some(post=>post.copyDraft.includes(detail)&&post.copyDraft.includes(url)));
 assert.equal(item.ownerConfirmed,false);
 assert.equal(campaign.canPublish,false);
 assert.equal(campaign.canSpend,false);
});
test('ordinary spaces do not become evidence for a spa service',()=>{
 const campaign=prepareUrlCampaign({...root,observations:{title:root.observations.title,
  meta_description:'Explore the spaces at our country club.',visible_paragraphs:[
   'Discover our spaces and plan your visit to the club.',
   'Membership options include a guided tour by appointment.']}});
 assert.ok(!campaign.siteSpecificStory.differentiators.some(item=>item.key==='spa'));
 assert.ok(!campaign.plan.posts.some(post=>/What to ask about the spa/.test(post.theme)));
 const spa=prepareUrlCampaign({...root,observations:{...root.observations,
  visible_paragraphs:['Spa treatments and wellness consultations are described on our website.']}});
 assert.ok(spa.siteSpecificStory.differentiators.some(item=>item.key==='spa'));
});
test('dining detail selection follows the source rather than a benchmark restaurant name',()=>{
 for(const name of ['Orchard','Willow House']){
  const detail=`Our ${name} restaurant serves seasonal vegetable plates and offers a separate lunch menu.`;
  const url=root.source_url+'dine';
  const campaign=prepareUrlCampaign({...root,page_reports:[root,{
   source_url:url,status:'extracted_unconfirmed',observations:{visible_paragraphs:[
    'Our restaurant is a welcoming place to spend time together and enjoy the day.',detail]}}]});
  const dining=campaign.siteSpecificStory.differentiators.find(x=>x.key==='dining');
  assert.equal(dining.evidence,detail);
  assert.ok(dining.hook.includes(name));
  assert.equal(dining.sourceUrl,url);
  assert.ok(campaign.plan.posts.some(post=>post.theme.includes(name)&&post.copyDraft.includes(detail)&&post.copyDraft.includes(url)));
  assert.ok(campaign.editorialShortlist.candidates.some(item=>item.hook.includes(name)&&item.evidence.quote===detail));
  assert.equal(dining.ownerConfirmed,false);
  assert.equal(campaign.canPublish,false);
  assert.equal(campaign.canSpend,false);
 }
});
test('dining hooks quote observed labels without inventing a restaurant name',()=>{
 for(const [paragraph,phrase] of [
  ['Our Thai restaurant serves vegetable plates at lunch.','Our Thai restaurant'],
  ['The Willow House restaurant offers a separate lunch menu.','The Willow House restaurant'],
  ['Our restaurant serves vegetable plates at lunch.',''],
  ['Our '+ 'A'.repeat(130)+' restaurant serves vegetable plates at lunch.',''],
  ['The restaurant offers a separate lunch menu.','']]){
  const campaign=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[paragraph]}});
  const dining=campaign.siteSpecificStory.differentiators.find(item=>item.key==='dining');
  assert.equal(dining.evidence,paragraph);
  assert.equal(dining.hook,phrase?'“'+phrase+'”: what would you like to explore?':'Explore dining at the club.');
  assert.equal(dining.ownerConfirmed,false);
 }
});
test('spa questions follow treatment evidence rather than a supplier brand',()=>{
 for(const brand of ['ESPA','Example Brand']){
  const campaign=prepareUrlCampaign({...root,observations:{...root.observations,
   visible_paragraphs:[`Our spa offers ${brand} facials and massages; ask about current treatment availability.`]}});
  const spa=campaign.siteSpecificStory.differentiators.find(item=>item.key==='spa');
  assert.equal(spa.hook,'Spa treatments: which options would you like to discuss?');
  assert.equal(spa.ownerConfirmed,false);
  assert.ok(campaign.plan.posts.some(post=>post.theme===spa.hook&&post.copyDraft.includes(spa.evidence)));
 }
});
test('shortened evidence is visibly quoted as an excerpt in calendar and saved exports', async()=>{
 const {createMarketingDocument,marketingPlanCsv}=await import('../src/lib/businessMarketingDocument.mjs');
 const paragraph='Fitness classes '+('provide guided sessions for different interests and routines ').repeat(9);
 const campaign=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[paragraph]}});
 const item=campaign.siteSpecificStory.differentiators.find(x=>x.key==='fitness');
 const post=campaign.plan.posts.find(p=>p.theme===item.hook);
 assert.ok(paragraph.includes(item.evidence),'Stored evidence remains an exact substring');
 assert.ok(item.evidence.length<=240);
 assert.ok(post.copyDraft.includes('Website excerpt (unconfirmed; shortened): “'+item.evidence+'”\n'));
 assert.ok(post.copyDraft.includes('\nSource (unconfirmed): '+root.source_url+'\n'));
 assert.ok(campaign.websiteAuditText.includes('Website excerpt (unconfirmed; shortened): “'+item.evidence+'”'));
 const document=createMarketingDocument(campaign);
 assert.equal(document.posts.find(p=>p.theme===item.hook).copyDraft,post.copyDraft);
 assert.ok(marketingPlanCsv(document).includes('Website excerpt (unconfirmed; shortened): “'+item.evidence+'”'));
 assert.equal(document.canPublish,false);
 assert.equal(document.canSpend,false);
});
test('complete short source evidence is quoted without a false shortening warning',()=>{
 const paragraph='Fitness classes include guided group sessions.';
 const campaign=prepareUrlCampaign({...root,observations:{...root.observations,visible_paragraphs:[paragraph]}});
 const item=campaign.siteSpecificStory.differentiators.find(x=>x.key==='fitness');
 const post=campaign.plan.posts.find(p=>p.theme===item.hook);
 assert.ok(post.copyDraft.includes('Website excerpt (unconfirmed): “'+paragraph+'”\n'));
 assert.ok(!post.copyDraft.includes('shortened'));
});
test('fallback positioning marks omitted source text without altering evidence',()=>{
 const paragraph=('A welcoming place to spend time with people and enjoy the day ').repeat(8);
 const campaign=prepareUrlCampaign({source_url:root.source_url,observations:{title:'Example Place',meta_description:paragraph}});
 const item=campaign.siteSpecificStory.differentiators[0];
 assert.equal(item.key,'source_positioning');
 assert.equal(item.evidenceShortened,true);
 assert.ok(paragraph.includes(item.evidence));
 assert.ok(campaign.plan.posts[0].copyDraft.includes('Website excerpt (unconfirmed; shortened): “'+item.evidence+'”'));
});
test('date-sensitive source warnings follow the selected page into calendar, concepts and exports',async()=>{
 const {createMarketingDocument,marketingPlanCsv}=await import('../src/lib/businessMarketingDocument.mjs');
 const quote='Membership options include a guided tour by appointment. Start the year with a club visit.';
 const detail={source_url:root.source_url+'membership',status:'extracted_unconfirmed',
  observations:{visible_paragraphs:[quote]},freshness:{status:'unknown',seasonal_excerpts:[quote]}};
 const campaign=prepareUrlCampaign({...root,page_reports:[root,detail]});
 const member=campaign.siteSpecificStory.differentiators.find(item=>item.key==='membership');
 assert.equal(member.sourceDateSensitive,true);
 assert.equal(member.evidence,quote);
 const warning='Date-sensitive source: current dates and availability are unknown. Confirm with the owner before using this wording.';
 const post=campaign.plan.posts.find(item=>item.theme===member.hook);
 assert.ok(post.copyDraft.includes(warning));
 assert.ok(post.copyDraft.includes('\nSource (unconfirmed): '+detail.source_url+'\n'));
 assert.ok(campaign.editorialShortlist.candidates.find(item=>item.evidence.kind==='membership').direction.includes(warning));
 assert.ok(!campaign.plan.posts.find(item=>item.theme==='Explore dining at the club.').copyDraft.includes(warning),'Other pages must not inherit this warning');
 assert.ok(marketingPlanCsv(createMarketingDocument(campaign)).includes(warning));
 assert.equal(member.ownerConfirmed,false);
 assert.equal(campaign.canPublish,false);assert.equal(campaign.canSpend,false);
});
test('shortened and fallback quotes retain source seasonal uncertainty without declaring expiry',()=>{
 const quote='Fitness classes include guided sessions with a timetable available on request. '+
  'Please speak to the team about the facilities that interest you. '.repeat(5)+'Summer availability needs checking.';
 const page={...root,observations:{...root.observations,visible_paragraphs:[quote]},
  freshness:{seasonal_excerpts:[quote]}};
 const campaign=prepareUrlCampaign(page);
 const item=campaign.siteSpecificStory.differentiators.find(item=>item.key==='fitness');
 assert.equal(item.sourceDateSensitive,true);
 assert.ok(!item.evidence.includes('Summer'));
 assert.ok(campaign.plan.posts.find(post=>post.theme===item.hook).copyDraft.includes('Date-sensitive source:'));
 const fallback=prepareUrlCampaign({source_url:root.source_url,observations:{title:'Example Place',
  meta_description:'Start the year at a welcoming place to spend time together.'},
  freshness:{seasonal_excerpts:['Start the year at a welcoming place to spend time together.']}});
 assert.equal(fallback.siteSpecificStory.differentiators[0].sourceDateSensitive,true);
 assert.ok(fallback.plan.posts[0].copyDraft.includes('Date-sensitive source:'));
});
test('short multi-service paragraphs yield distinct relevant exact sentences and literal trade hooks',()=>{
 const sentences=['Plumbing repairs cover visible leaks.',
  'Boiler servicing includes a system check.',
  'Request a written quotation before agreeing work.'];
 const paragraph=sentences.join(' ');
 assert.ok(paragraph.length<240,'Reproduce the short-paragraph selection path');
 const url='https://workshop.example.org/';
 const campaign=prepareUrlCampaign({source_url:url,status:'extracted_unconfirmed',
  observations:{title:'Example Plumbing',meta_description:'Plumbing and heating services.',visible_paragraphs:[paragraph]}});
 for(const [index,key,label] of [[0,'repairs','Plumbing repairs'],[1,'heating','Boiler servicing'],[2,'scope','written quotation']]){
  const item=campaign.siteSpecificStory.differentiators.find(item=>item.key===key);
  assert.equal(item.evidence,sentences[index]);
  assert.equal(item.sourceLabel,'paragraph 1');
  assert.equal(item.sourceUrl,url);
  assert.equal(item.evidenceShortened,true);
  assert.equal(item.hook,'“'+label+'”: what should you ask?');
  assert.ok(campaign.plan.posts.some(post=>post.theme===item.hook&&post.copyDraft.includes(item.evidence)&&post.copyDraft.includes(url)));
  assert.ok(campaign.editorialShortlist.candidates.some(candidate=>candidate.hook===item.hook&&candidate.evidence.quote===item.evidence));
  assert.equal(item.ownerConfirmed,false);
 }
 assert.equal(campaign.canPublish,false);assert.equal(campaign.canSpend,false);
});
test('single-service context retains its qualification and absent trade labels keep neutral questions',()=>{
 const paragraph='Boiler servicing includes a system check. Contact the team as some models cannot be serviced.';
 const campaign=prepareUrlCampaign({source_url:'https://workshop.example.org/',
  observations:{title:'Example Plumbing',meta_description:'Heating enquiries.',visible_paragraphs:[paragraph]}});
 const heating=campaign.siteSpecificStory.differentiators.find(item=>item.key==='heating');
 assert.equal(heating.evidence,paragraph);
 assert.equal(heating.evidenceShortened,false);
 const sparse=prepareUrlCampaign({source_url:'https://workshop.example.org/',
  observations:{title:'Example Plumbing',meta_description:'Ask the team about your heating system.'}});
 assert.equal(sparse.siteSpecificStory.differentiators.find(item=>item.key==='heating').hook,'Questions about heating work.');
});
test('quotation directions prefer actual quotation wording over generic contact instructions',()=>{
 const quote='Request a detailed estimate before agreeing work.';
 const campaign=prepareUrlCampaign({source_url:'https://workshop.example.org/',
  observations:{title:'Example Plumbing',meta_description:'Plumbing and heating services.',visible_paragraphs:[
   'Contact the team to discuss your plumbing requirements and describe the affected fixture.',quote]}});
 const scope=campaign.siteSpecificStory.differentiators.find(item=>item.key==='scope');
 assert.equal(scope.evidence,quote);
 assert.equal(scope.sourceLabel,'paragraph 2');
 assert.equal(scope.hook,'“detailed estimate”: what should you ask?');
 assert.ok(campaign.plan.posts.some(post=>post.theme===scope.hook&&post.copyDraft.includes(quote)));
});
