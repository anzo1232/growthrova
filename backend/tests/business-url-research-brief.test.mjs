import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {strategyConfirmed,businessFactsReviewed} from '../src/lib/businessOwnerStrategy.mjs';

const appointment='Viewings are by advance appointment only and are arranged as part of your membership enquiry.';
const dining='Our Willow restaurant serves mezze and charcoal-grilled dishes with fresh flatbreads baked in our tandoor.';
const membership='Club membership includes gym and spa access, with complimentary wellness reviews and reduced treatment rates.';
const home={title:'Example Country Club',meta_description:'Fitness and dining in the countryside.',
 headings:['About us','Explore','Welcome'],
 visible_paragraphs:['Welcome to a place to spend time together.','Discover a setting for your everyday plans.',
 'Make the most of time with friends and family.','Explore a place with something different to discover.',
 'We look forward to welcoming you to the club.'],service_links:[]};
const audit={source_url:'https://example.org/',observations:{...home,visible_paragraphs:[...home.visible_paragraphs,appointment,dining,membership]},
 page_reports:[{source_url:'https://example.org/',status:'extracted_unconfirmed',observations:home},
 {source_url:'https://example.org/membership',status:'extracted_unconfirmed',observations:{visible_paragraphs:[appointment,membership]}},
 {source_url:'https://example.org/dine',status:'extracted_unconfirmed',observations:{visible_paragraphs:[dining]}}]};

test('late dedicated-page details survive URL preparation intact for owner review',()=>{
 const campaign=prepareUrlCampaign(audit);
 assert.ok(campaign.observedFacts.includes(appointment),'appointment detail was discarded');
 assert.ok(campaign.observedFacts.includes(membership),'membership inclusions were discarded');
 assert.ok(campaign.observedFacts.includes(dining),'specific dining detail was discarded');
 assert.equal(campaign.observedFacts.filter(x=>x===appointment).length,1);
 assert.ok(campaign.observedFacts.length<=40);
 assert.ok(campaign.observedFacts.every(x=>x.length<=600));
});

test('new URL campaign proposes a source-specific editable brief without granting confirmation',()=>{
 const document=createMarketingDocument(prepareUrlCampaign(audit));
 const strategy=document.ownerStrategy;
 assert.ok(strategy,'URL research left all strategy fields blank');
 for(const field of ['audience','offer','positioning','callToAction','constraints'])assert.ok(strategy[field]?.trim(),field);
 assert.match(strategy.offer+'\n'+strategy.positioning,/Willow|advance appointment|membership/i);
 assert.equal(strategy.confirmedContext,null);
 assert.deepEqual(strategy.factDecisions,[]);
 assert.equal(strategyConfirmed(document),false);
 assert.equal(businessFactsReviewed(document),false);
 assert.equal(document.canPublish,false);
 assert.equal(document.canSpend,false);
});

test('form and cookie text cannot displace useful source detail in the review budget',()=>{
 const noisy={...audit,observations:{...home,visible_paragraphs:[...Array(35).fill('Upload a clear photo of your face, up to 6 MB. This is used as identification.'),'This website uses cookies','Our use of cookies',appointment,dining]},
 page_reports:undefined};
 const facts=prepareUrlCampaign(noisy).observedFacts;
 assert.ok(facts.includes(appointment));
 assert.ok(facts.includes(dining));
 assert.ok(!facts.some(x=>x.startsWith('Upload a clear photo')));
 assert.ok(!facts.some(x=>/cookies/i.test(x)));
});

test('long source paragraphs retain complete opening sentences rather than only their final sentence',()=>{
 const opening='Viewings are by advance appointment only.';
 const paragraph=opening+' '+('Ask about membership options during your visit. '.repeat(15))+' Enquire today.';
 assert.ok(paragraph.length>600);
 const campaign=prepareUrlCampaign({...audit,page_reports:undefined,
  observations:{...home,visible_paragraphs:[paragraph]}});
 const excerpt=campaign.observedFacts.find(value=>value.startsWith(opening));
 assert.ok(excerpt,'opening appointment requirement disappeared from owner review');
 assert.ok(paragraph.startsWith(excerpt),'review text must remain an exact source prefix');
 assert.ok(excerpt.length<=600);
 assert.match(excerpt,/[.!?]$/);
});

test('suggested brief separates readable directions with real line breaks',()=>{
 const campaign=prepareUrlCampaign(audit);
 assert.ok(campaign.editorialShortlist.candidates.length>=2,'fixture requires multiple sourced directions');
 const {offer,positioning}=createMarketingDocument(campaign).ownerStrategy;
 assert.ok(positioning.startsWith('Suggested directions to review:\n'));
 assert.ok(!offer.includes('\\n')&&!positioning.includes('\\n'),'literal escapes leaked into editable brief');
 for(const direction of campaign.editorialShortlist.candidates){
  assert.ok(positioning.split('\n').includes(direction.hook));
 }
});

test('long source paragraphs keep complete useful sentences rather than disappearing',()=>{
 const first='We provide pipe repairs and boiler servicing for homes across the city.';
 const long=first+' '+('Further service information is available when you enquire. '.repeat(15));
 const campaign=prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Example Plumbing',meta_description:'Pipe repairs and boiler servicing.',visible_paragraphs:[long]}});
 assert.ok(campaign.observedFacts.some(f=>f.startsWith(first)&&f.endsWith('.')),'complete opening detail was lost');
 assert.ok(campaign.observedFacts.every(f=>f.length<=600));
});

test('sparse but substantive research still proposes its actual service detail for review',()=>{
 const quote='We provide pipe repairs and boiler servicing for homes across the city.';
 const campaign=prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Example Plumbing',meta_description:'Plumbing and heating services.',visible_paragraphs:[quote]}});
 const document=createMarketingDocument(campaign);
 assert.match(document.ownerStrategy.offer,/pipe repairs/);
 assert.match(document.ownerStrategy.positioning,/pipe repairs/);
 assert.equal(document.ownerStrategy.confirmedContext,null);
});

test('sparse brief uses existing service evidence rather than mixing promotional observations into the offer',()=>{
 const campaign=prepareUrlCampaign({source_url:'https://example.org/',observations:{
  title:'Example Plumbing',meta_description:'Plumbing and heating services for local homes.',
  visible_paragraphs:['London’s No.1 – Repair. Maintain. Improve.',
   '10% off bathroom installations before Christmas.',
   'We provide pipe repairs and boiler servicing for homes across the city.']}});
 assert.match(campaign.suggestedStrategy.offer,/pipe repairs/);
 assert.ok(!campaign.suggestedStrategy.offer.includes('10%'));
 assert.ok(!campaign.suggestedStrategy.offer.includes('No.1'));
 assert.equal(campaign.suggestedStrategy.confirmedContext,null);
});

test('service-page descriptions remain reviewable when its body has no paragraph tags',()=>{
 const detail='Emergency plumbing repairs across London are available through our enquiry team.';
 const report={...audit,page_reports:[...audit.page_reports,{source_url:'https://example.org/repairs',status:'extracted_unconfirmed',observations:{meta_description:detail,visible_paragraphs:[]}}]};
 assert.ok(prepareUrlCampaign(report).observedFacts.includes(detail));
});

test('reviewed observations retain their exact page through document creation and confirmation context',()=>{
 const document=createMarketingDocument(prepareUrlCampaign(audit));
 assert.equal(document.observedFactSources?.length,document.observedFacts.length);
 for(const [quote,path] of [[appointment,'membership'],[dining,'dine'],[membership,'membership']]){
  const index=document.observedFacts.indexOf(quote);
  assert.equal(document.observedFactSources[index],'https://example.org/'+path);
 }
 // Merged audit observations are not evidence that a heading was on the home
 // page: page provenance comes from the validated page reports themselves.
 const extra=prepareUrlCampaign({...audit,observations:{...audit.observations,headings:['Merged-only heading']}});
 assert.ok(!extra.observedFacts.includes('Merged-only heading'));
});

test('page references cannot introduce credentials, fragments, whitespace or noncanonical backslashes',()=>{
 for(const source_url of ['https://example.org/dine#claim','https://example.org/di ne',
  'https://example.org/\\dine','https://user@example.org/dine']){
  assert.throws(()=>prepareUrlCampaign({...audit,page_reports:[{...audit.page_reports[1],source_url}]}),/source/i);
 }
});


test('rendered website identity initialises a source-bound brand kit without granting approval',()=>{
 const visual={status:'website_observed_unconfirmed',method:'rendered_computed_styles',
  roles:{background:'#0C0C0F',text:'#FFFFFF',accent:'#02FFB2'},
  colours:[{hex:'#FFFFFF',count:72},{hex:'#02FFB2',count:2}],
  fontFamilies:[{family:'Inter',count:26}],
  logoCandidates:[{kind:'image_url',url:'https://cdn.example.org/logo.png',description:'Organisation logo'}],
  suggestedBrandKit:{primary_color:'#0C0C0F',secondary_color:'#02FFB2',font_style:'modern'}};
 const branded={...audit,fetched_at:'2026-11-09T20:00:00+00:00',observations:{...audit.observations,visual_identity:visual}};
 const document=createMarketingDocument(prepareUrlCampaign(branded));
 assert.deepEqual(document.brandKit,{name:'Example Country Club',primary_color:'#0C0C0F',secondary_color:'#02FFB2',font_style:'modern'});
 assert.equal(document.brandIdentity.sourceUrl,'https://example.org/');
 assert.equal(document.brandIdentity.fontFamilies[0].family,'Inter');
 assert.equal(document.brandIdentity.logoCandidates[0].url,'https://cdn.example.org/logo.png');
 assert.equal(document.canPublish,false);
 assert.equal(document.canSpend,false);
});
