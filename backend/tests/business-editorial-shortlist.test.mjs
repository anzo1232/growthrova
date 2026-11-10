import test from 'node:test';import assert from 'node:assert/strict';
import {editorialShortlist} from '../src/lib/businessEditorialShortlist.mjs';
import {buildWebsiteStory} from '../src/lib/businessUrlStoryEngine.mjs';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';

function audit(brand='Berenjak'){
 return {source_url:'https://berenjak.com/',observations:{
 title:brand,
 meta_description:'Home-style Persian cuisine inspired by the hole-in-the-wall kabab houses of Tehran.',
 headings:['Persian food inspired by the kabab shops of Tehran','Noon o mazeh','Charcoal kababs'],
 visible_paragraphs:[
 'From Iranian childhood food traditions and family gatherings, the chef created the restaurant.',
 'We serve fresh taftoon and sangak bread prepared in the kitchen.',
 'Koobideh and jujeh are among the Persian kababs, and kashk-e bademjoon is among the mazeh dishes.',
 'The Soho restaurant is located at 27 Romilly Street.'],
 service_links:[{label:'See the restaurant menu',url:'https://berenjak.com/menus'}]
 }};
}
test('Berenjak now makes THREE distinct, evidence-linked preproduction concepts before 30 filler posts',()=>{
 const plan=prepareUrlCampaign(audit(),{expectedDomain:'berenjak.com'});
 const shortlisted=plan.editorialShortlist;
 assert.equal(plan.sector,'restaurant');assert.equal(shortlisted.candidates.length,3);
 assert.equal(shortlisted.status,'three_directions_ready_for_asset_intake');
 assert.equal(new Set(shortlisted.candidates.map(x=>x.evidence.kind)).size,3);
 assert.deepEqual(shortlisted.candidates.map(x=>x.media),['Reel','Carousel','Image']);
 assert.ok(shortlisted.candidates.some(x=>/bread|charcoal|persian|iranian|dish/i.test(x.evidence.quote)));
 assert.ok(shortlisted.candidates.every(x=>!x.publishApproved&&!x.spendApproved&&x.generationState==='unrendered'));
 assert.equal(plan.canPublish,false);assert.equal(plan.canSpend,false);
});
test('An empty café cannot produce three fake finished creatives',()=>{
 const o={title:'Random café',meta_description:'A friendly place for coffee and breakfast.'};
 const result=editorialShortlist(buildWebsiteStory(o,'restaurant'),{brand:'Random café',sourceUrl:'https://random-cafe.example'});
 assert.equal(result.status,'blocked_insufficient_unique_brand_evidence');
 assert.equal(result.candidates.length,0);assert.equal(result.approved,false);
 assert.ok(result.blockers.includes('fewer_than_three_distinct_evidence_categories'));
});
test('Source evidence cannot silently imply the restaurant offers dishes not listed',()=>{
 const o={title:'Berenjak',meta_description:'Persian food. Tehran inspired dining.',
   visible_paragraphs:['Bread is baked with a traditional taftoon method, and charcoal kababs are cooked in the kitchen.']};
 const story=buildWebsiteStory(o,'restaurant');
 const short=editorialShortlist(story,{brand:'Berenjak',sourceUrl:'https://berenjak.com/'});
 const corpus=JSON.stringify(short);
 assert.doesNotMatch(corpus,/shish taouk|baklava|falafel/i);
 assert.equal(short.approved,false);
});
test('No fabricated task or provider charge when no current images exist',()=>{
 const result=editorialShortlist(buildWebsiteStory(audit().observations,'restaurant'),{
  brand:'Berenjak',sourceUrl:'https://berenjak.com'});
 assert.equal(result.canGenerateAutomatically,false);
 assert.ok(result.blockers.includes('no_rights_cleared_actual_business_media'));
});
test('sparse dish and heritage sources do not acquire ingredients, people, places or cooking methods',()=>{
 const campaign=prepareUrlCampaign({source_url:'https://restaurant.example/',observations:{
  title:'Example Restaurant',meta_description:'A restaurant serving food inspired by family recipes.',
  visible_paragraphs:['Koobideh is listed on our restaurant menu.',
   'Our family recipes reflect childhood memories in Iran.',
   'Fresh sangak bread is prepared using stones.']}});
 const candidates=campaign.editorialShortlist.candidates;
 assert.equal(candidates.length,3);
 assert.ok(candidates.some(item=>/koobideh/i.test(item.hook)));
 assert.doesNotMatch(candidates.map(item=>item.hook).join(' '),/lamb|spice|mangal|Kian|Soho|river stones/i);
 assert.ok(candidates.every(item=>!item.publishApproved&&!item.spendApproved));
});
