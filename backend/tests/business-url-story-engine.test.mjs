import test from 'node:test';import assert from 'node:assert/strict';
import {buildWebsiteStory,storyMarkdown} from '../src/lib/businessUrlStoryEngine.mjs';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
const make=(title,description,paragraphs=[],headings=[])=>({title,meta_description:description,headings,visible_paragraphs:paragraphs});
test('Encore concierge brief follows one-message experience and real site services',()=>{
 const o=make('ENCORE VIP','Bespoke experiences. Private aviation. Exclusive events.',
 ['From a last-minute table to a fleet of transfers — your concierge handles every detail.',
 'A brief message is all it takes. No lengthy forms, no back-and-forth.','We handle every detail']);
 const story=buildWebsiteStory(o,'concierge');
 assert.ok(story.differentiators.some(d=>d.key==='message'));
 assert.ok(story.differentiators.some(d=>d.key==='transfers'));
 assert.ok(story.differentiators.some(d=>d.key==='travel'));
 assert.match(story.angles[0].hook,/message/i);
 assert.equal(new Set(story.angles.map(x=>x.hook)).size,story.angles.length);
 assert.equal(story.spendAuthorised,false);
 assert.ok(!story.differentiators.some(d=>d.ownerConfirmed));
 const campaign=prepareUrlCampaign({source_url:'https://www.encorevip.uk/',observations:o});
 assert.match(campaign.plan.posts[0].theme,/message/i);
 assert.match(campaign.websiteAuditText,/URL-specific creative research/);
 assert.equal(campaign.canPublish,false);
});
test('Lebanese restaurant differentiates family recipes and dishes without falsely claiming another menu',()=>{
 const o=make('The Cedar Restaurant','Authentic Lebanese cuisine',
 ['Since 1997 our family recipes from Lebanon bring generations together with kebbeh and shish taouk.','We offer catering and dine-in.']);
 const s=buildWebsiteStory(o,'restaurant');
 assert.ok(s.differentiators.some(d=>d.key==='heritage'));
 assert.ok(s.differentiators.some(d=>d.key==='dish'));
 assert.match(s.angles[1].hook,/recipes|dishes/i);
 assert.doesNotMatch(storyMarkdown(s),/confirmed menu dishes/i);
});
test('Generic restaurant and beauty cannot acquire invented cuisine or clinical outcomes',()=>{
 const r=buildWebsiteStory(make('Example Cafe','Breakfast sandwiches and coffee',''.split('|')),'restaurant');
 assert.ok(!r.differentiators.some(d=>d.key==='cuisine' || d.key==='heritage'));
 const b=buildWebsiteStory(make('Beauty Salon','Facial consultations and skincare services'),'beauty');
 assert.ok(!b.differentiators.some(d=>d.evidence.includes('guaranteed results')));
});
test('Construction highlights project reality and preserves approval gate',()=>{
 const c=buildWebsiteStory(make('Marleo Construction','Home renovation and kitchen refurbishment enquiries'),'renovation');
 assert.ok(c.differentiators.some(d=>d.key==='craft'));
 assert.ok(c.differentiators.some(d=>d.key==='project'));
 assert.equal(c.generatedAssets,0);
});
test('No page facts never becomes verified creative evidence',()=>{
 const empty=buildWebsiteStory({title:'Example'},'concierge');
 assert.equal(empty.evidenceStatus,'insufficient_website_evidence');
 assert.equal(empty.angles.length,0);
});
