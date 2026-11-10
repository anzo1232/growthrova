import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../src/lib/businessMarketingDocument.mjs';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
const campaign=()=>prepareUrlCampaign({source_url:'https://example.org/',observations:{
  title:'Example restaurant',meta_description:'Seasonal dining and table enquiries',headings:['Our menu']}});

test('optional advert supporting line edits only its saved post and revokes word review',()=>{
 const doc=model.createMarketingDocument(campaign());
 doc.posts[0].status='copy_reviewed';
 const before=structuredClone(doc);
 const next=model.editMarketingPost(doc,1,{supportingLine:'Seasonal dining and table enquiries.'});
 assert.equal(next.posts[0].supportingLine,'Seasonal dining and table enquiries.');
 assert.equal(next.posts[0].status,'draft');
 assert.equal(next.posts[0].copyDraft,doc.posts[0].copyDraft);
 assert.deepEqual(next.posts.slice(1),doc.posts.slice(1));
 assert.deepEqual(doc,before);
 assert.equal(model.editMarketingPost(next,1,{supportingLine:next.posts[0].supportingLine}),next);
 assert.equal(model.editMarketingPost(next,1,{supportingLine:''}).posts[0].supportingLine,'');
 assert.throws(()=>model.editMarketingPost(next,1,{supportingLine:'x'.repeat(181)}));
 assert.ok(model.marketingPlanCsv(next).includes('Seasonal dining and table enquiries.'));
 const notes=model.editMarketingPost(next,1,{copyDraft:'Explore our seasonal dining.',callToAction:'Enquire about a table',graphicText:'Seasonal dining',supportingLine:'Draft direction: add an offer here'});
 assert.throws(()=>model.reviewMarketingCopy(notes,'post',1),/internal research or planning notes/);
});

test('post destination edits preserve caption and siblings and invalidate copy review',()=>{
 const doc=model.createMarketingDocument(campaign());
 doc.posts[0]={...doc.posts[0],copyDraft:'Explore the seasonal menu.',callToAction:'Book a table',status:'copy_reviewed'};
 const before=structuredClone(doc);
 const changed=model.editMarketingPost(doc,1,{destinationUrl:'https://example.org/book'});
 assert.equal(changed.posts[0].destinationUrl,'https://example.org/book');
 assert.equal(changed.posts[0].status,'draft');
 assert.equal(changed.posts[0].copyDraft,doc.posts[0].copyDraft);
 assert.deepEqual(changed.posts.slice(1),doc.posts.slice(1));
 assert.deepEqual(doc,before);
 assert.equal(model.editMarketingPost(changed,1,{destinationUrl:'https://example.org/book'}),changed);
});

test('picture-only revision preserves checked words; unchanged edits preserve the document',()=>{
 let doc=model.createMarketingDocument(campaign());
 doc=model.editMarketingCreative(doc,'creative-1',{copyDraft:'Explore our seasonal menu.'});
 doc=model.reviewMarketingCopy(doc,'creative','creative-1');
 const before=structuredClone(doc);
 assert.equal(model.editMarketingCreative(doc,'creative-1',{copyDraft:doc.creatives[0].copyDraft}),doc);
 assert.equal(model.editMarketingPost(doc,1,{copyDraft:doc.posts[0].copyDraft}),doc);
 assert.equal(model.editMarketingCreative(doc,'creative-1',{}),doc);
 const revised=model.editMarketingCreative(doc,'creative-1',{brief:'Leave clear space around the authorised logo.'});
 assert.equal(revised.creatives[0].status,'copy_reviewed');
 assert.equal(revised.creatives[0].copyDraft,doc.creatives[0].copyDraft);
 assert.equal(revised.creatives[0].callToAction,doc.creatives[0].callToAction);
 assert.deepEqual(revised.creatives.slice(1),doc.creatives.slice(1));
 assert.deepEqual(revised.posts,doc.posts);
 assert.equal(model.editMarketingCreative(revised,'creative-1',{callToAction:'Book a table'}).creatives[0].status,'draft');
 assert.equal(model.editMarketingCreative(revised,'creative-1',{copyDraft:'New customer words.'}).creatives[0].status,'draft');
 assert.equal(model.editMarketingCreative(revised,'creative-1',{title:'New context'}).creatives[0].status,'draft');
 assert.equal(revised.creatives[0].approved,false);
 assert.equal(revised.canPublish,false);
 assert.deepEqual(doc,before);
});

test('generated research directions cannot be recorded as checked customer copy',()=>{
 const c=prepareUrlCampaign({source_url:'https://example.org/',observations:{
  title:'Example country club',meta_description:'Club membership and spa treatments.',
  visible_paragraphs:['Viewings of the Club are by advance appointment only.']}});
 const doc=model.createMarketingDocument(c);
 assert.match(doc.posts[0].copyDraft,/Draft direction:/);
 const before=structuredClone(doc);
 assert.throws(()=>model.reviewMarketingCopy(doc,'post',1),/internal research or planning notes/);
 const transferred=model.usePostWordsForCreative(doc,'creative-1',1);
 assert.throws(()=>model.reviewMarketingCopy(transferred,'creative','creative-1'),/internal research or planning notes/);
 const legacy={...doc,posts:[{...doc.posts[0],status:'copy_reviewed'}]};
 assert.ok(!model.marketingPlanCsv(legacy).includes('copy_reviewed'));
 assert.equal(legacy.posts[0].status,'copy_reviewed','Export must not mutate the saved legacy record');
 assert.deepEqual(doc,before);
});

test('a website campaign becomes an editable full plan and four distinct concepts',()=>{
  assert.equal(typeof model.createMarketingDocument,'function');
  const doc=model.createMarketingDocument(campaign());
  assert.equal(doc.posts.length,30);assert.equal(doc.creatives.length,7);
  assert.deepEqual(doc.creatives.map(c=>c.format),['image_ad','video_ad','carousel','graphic','image_ad','image_ad','image_ad']);
  assert.ok(doc.creatives.every(c=>c.assetUrl===null&&c.mediaStatus==='not_generated'));
  assert.equal(doc.canPublish,false);
});
test('editing one post leaves other days unchanged and revokes only its copy review',()=>{
  const before=model.createMarketingDocument(campaign());before.posts[2].status='copy_reviewed';
  const after=model.editMarketingPost(before,3,{copyDraft:'New copy',callToAction:'View the menu'});
  assert.equal(after.posts[2].copyDraft,'New copy');assert.equal(after.posts[2].status,'draft');
  assert.deepEqual(after.posts[1],before.posts[1]);assert.notEqual(after.posts[2],before.posts[2]);
  assert.throws(()=>model.editMarketingPost(before,3,{published:true}));
  assert.throws(()=>model.editMarketingPost(before,31,{copyDraft:'Outside plan'}));
});
test('creative text can be reviewed but cannot acquire media or publication approval',()=>{
  const doc=model.createMarketingDocument(campaign());
  const edited=model.editMarketingCreative(doc,'creative-1',{copyDraft:'Read our menu'});
  const reviewed=model.reviewMarketingCopy(edited,'creative','creative-1');
  assert.equal(reviewed.creatives[0].status,'copy_reviewed');
  assert.equal(reviewed.creatives[0].assetUrl,null);assert.equal(reviewed.canPublish,false);
  assert.throws(()=>model.editMarketingCreative(doc,'creative-1',{assetUrl:'https://arbitrary.example/a.png'}));
});
test('export preserves editable fields and escapes spreadsheet formulas',()=>{
  const doc=model.createMarketingDocument(campaign());doc.posts[0].copyDraft='=HYPERLINK("x")';
  const csv=model.marketingPlanCsv(doc);
  assert.ok(csv.includes("'=HYPERLINK"));assert.ok(csv.includes('Call to action'));
  assert.ok(csv.includes('Not scheduled'));assert.ok(csv.includes('Example restaurant'));
});
test('website images enter editable document as unverified references, not approved brand assets',()=>{
 const c=campaign();c.websiteImages=[{url:'https://example.org/real-roof.jpg',alt:'Photo of roof tiling',rights_confirmed:true,authenticity_verified:true}];
 const doc=model.createMarketingDocument(c);
 assert.equal(doc.websiteImages.length,1);assert.equal(doc.websiteImages[0].rights_confirmed,false);
 assert.equal(doc.websiteImages[0].authenticity_verified,false);
 assert.equal(doc.canPublish,false);
});
test('a real campaign includes three clearly distinct supporting image briefs',()=>{
 const doc=model.createMarketingDocument(campaign());
 assert.equal(doc.creatives.length,7);
 const images=doc.creatives.filter(c=>c.format==='image_ad');
 assert.equal(images.length,4);
 assert.equal(new Set(images.map(c=>c.brief)).size,4);
 assert.ok(images.every(c=>!c.approved&&!c.published&&c.assetUrl===null));
 assert.ok(images.some(c=>/problem|question/i.test(c.title)));
});
test('an older four-concept campaign can be extended without losing edits or charging',()=>{
 const original=model.createMarketingDocument(campaign());
 const old={...original,creatives:original.creatives.slice(0,4)};
 old.creatives[0].copyDraft='Keep this approved headline draft';
 const upgraded=model.addSupportingImageConcepts(old);
 assert.equal(upgraded.creatives.length,7);
 assert.deepEqual(upgraded.creatives.slice(0,4),old.creatives);
 assert.equal(upgraded.creatives[4].id,'creative-5');
 assert.equal(upgraded.creatives[4].format,'image_ad');
 assert.equal(upgraded.canSpend,false);assert.equal(upgraded.canPublish,false);
 assert.deepEqual(model.addSupportingImageConcepts(upgraded),upgraded);
 assert.equal(old.creatives.length,4);
});
test('the owner can save and reuse a plan start date without granting publishing rights',()=>{
 const doc=model.createMarketingDocument(campaign());
 assert.equal(doc.calendarStartDate,'');
 doc.calendarStartDate='2026-11-02';
 assert.equal(doc.canPublish,false);
 assert.equal(doc.posts[0].published,false);
});
test('a calendar post replaces only the selected creative words, retaining exact source text',()=>{
 const doc=model.createMarketingDocument(campaign());
 doc.posts[1].copyDraft='Draft: explore membership.\nSource (unconfirmed): https://example.org/membership';
 doc.creatives[0].status='copy_reviewed';
 const before=structuredClone(doc);
 const next=model.usePostWordsForCreative(doc,'creative-1',2);
 assert.equal(next.creatives[0].copyDraft,doc.posts[1].copyDraft);
 assert.equal(next.creatives[0].status,'draft');
 assert.equal(next.creatives[0].approved,false);
 assert.equal(next.creatives[0].brief,doc.creatives[0].brief);
 assert.equal(next.creatives[0].callToAction,doc.creatives[0].callToAction);
 assert.deepEqual(next.posts,doc.posts);
 assert.deepEqual(next.creatives.slice(1),doc.creatives.slice(1));
 assert.deepEqual(doc,before);
 assert.equal(model.usePostWordsForCreative(next,'creative-1',2),next);
 assert.equal(next.canSpend,false);assert.equal(next.canPublish,false);
});
test('copying a post rejects missing, empty and oversized text without truncating or changing owner work',()=>{
 const doc=model.createMarketingDocument(campaign());
 assert.throws(()=>model.usePostWordsForCreative(doc,'creative-1',31),/Post not found/);
 assert.throws(()=>model.usePostWordsForCreative(doc,'missing',1),/Creative not found/);
 for(const copy of ['', '  ', 'x'.repeat(model.MARKETING_CREATIVE_COPY_LIMIT+1)]){
  doc.posts[0].copyDraft=copy;
  const before=structuredClone(doc);
  assert.throws(()=>model.usePostWordsForCreative(doc,'creative-1',1),/Choose a post with words|Shorten the post/);
  assert.deepEqual(doc,before);
 }
});

test('a readable creative download preserves the selected saved words and scoped revision without changing owner work',()=>{
 const doc=model.createMarketingDocument(campaign());
 doc.creatives[0].copyDraft='Keep this other creative';
 doc.creatives[1].copyDraft='Explore membership.\nWebsite excerpt (unconfirmed): “Tours by appointment.”\nSource: https://example.org/membership';
 doc.creatives[1].brief='Use only authorised footage.\nKeep the logo clear.';
 doc.creatives[1].callToAction='Enquire about a visit';
 doc.creatives[1].status='copy_reviewed';
 const before=structuredClone(doc);
 const content=model.marketingCreativeText(doc,'creative-2');
 assert.ok(content.includes('Business: '+doc.business));
 assert.ok(content.includes('Source website: '+doc.sourceUrl));
 assert.ok(content.includes('Words\n'+doc.creatives[1].copyDraft+'\n\nCall to action\n'+doc.creatives[1].callToAction));
 assert.ok(content.includes('Picture instructions\n'+doc.creatives[1].brief));
 assert.ok(content.includes('Copy review: Not checked.'));
 assert.ok(content.includes('Draft text and instructions only. No rendered image or video is included.'));
 assert.ok(content.includes('Media rights, final creative approval, publishing and spend are not granted by this download.'));
 assert.ok(!content.includes('Keep this other creative'));
 assert.deepEqual(doc,before);
 const revised=model.editMarketingCreative(doc,'creative-2',{brief:'Revised framing only. <script>literal text</script>'});
 const reopened=JSON.parse(JSON.stringify(revised));
 const next=model.marketingCreativeText(reopened,'creative-2');
 assert.ok(next.includes(reopened.creatives[1].copyDraft));
 assert.ok(next.includes('Revised framing only. <script>literal text</script>'));
 assert.ok(next.includes('Copy review: Not checked.'));
 assert.ok(!next.includes('Keep the logo clear.'));
 assert.deepEqual(reopened.posts,doc.posts);
 assert.throws(()=>model.marketingCreativeText(doc,'missing'),/Creative not found/);
});

test('basic copy checks reject notes, bare questions and quotes but allow an explained hook',()=>{
 const doc=model.createMarketingDocument(campaign());
 for(const copyDraft of [doc.business,'  DRAFT DIRECTION: Explain our offer.','Ready to join? What matters to you?',
  '“Viewings are by appointment.”','Explore the club.\nSource (unconfirmed): https://example.org/']){
  const edited=model.editMarketingPost(doc,1,{copyDraft});
  assert.throws(()=>model.reviewMarketingCopy(edited,'post',1));
 }
 const copyDraft='Planning a visit? Talk to our team about a club viewing.';
 const edited=model.editMarketingPost(doc,1,{copyDraft,callToAction:'Enquire about a viewing'});
 assert.equal(model.reviewMarketingCopy(edited,'post',1).posts[0].status,'copy_reviewed');
 assert.equal(edited.posts[0].status,'draft');
 assert.deepEqual(edited.posts.slice(1),doc.posts.slice(1));
 assert.throws(()=>model.reviewMarketingCopy(model.editMarketingPost(edited,1,{callToAction:' '}),'post',1),/call to action/);
});


test('graphic words are scoped owner edits that preserve the full caption and export',()=>{
 const doc=model.createMarketingDocument(campaign());
 doc.posts[0].copyDraft='Complete caption. '.repeat(90);
 doc.posts[0].status='copy_reviewed';
 const original=structuredClone(doc);
 const after=model.editMarketingPost(doc,1,{graphicText:'Make room for your next project.'});
 assert.equal(after.posts[0].graphicText,'Make room for your next project.');
 assert.equal(after.posts[0].copyDraft,original.posts[0].copyDraft);
 assert.equal(after.posts[0].callToAction,original.posts[0].callToAction);
 assert.equal(after.posts[0].status,'draft');
 assert.deepEqual(after.posts.slice(1),original.posts.slice(1));
 assert.deepEqual(after.creatives,original.creatives);
 assert.deepEqual(doc,original);
 assert.equal(model.editMarketingPost(after,1,{graphicText:after.posts[0].graphicText}),after);
 assert.match(model.marketingPlanCsv(after),/Graphic words/);
 assert.match(model.marketingPlanCsv(after),/Make room for your next project/);
 assert.throws(()=>model.editMarketingPost(after,1,{graphicText:'x'.repeat(501)}));
 const notes=model.editMarketingPost(after,1,{graphicText:'Draft direction: Show a workshop'});
 assert.throws(()=>model.reviewMarketingCopy(notes,'post',1),/planning notes/);
});
