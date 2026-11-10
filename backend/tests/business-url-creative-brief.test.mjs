import test from 'node:test';import assert from 'node:assert/strict';
import {creativeFromWebsiteFindings,inferCreativeSector} from '../src/lib/businessUrlCreativeBrief.mjs';
test('each of four distinct website types creates a bounded art-directed prompt',()=>{
 for(const type of ['concierge','restaurant','beauty','renovation']){
  const result=creativeFromWebsiteFindings({sourceUrl:'https://example.org/',businessType:type,observations:{title:'Sample company',meta_description:'Real service information',headings:['Book a service']}});
  assert.equal(result.status,'prompt_ready_not_generated');assert.equal(result.ownerConfirmationRequired,true);
  assert.match(result.prompt,/Never render words or logos/);assert.match(result.prompt,/NOT an authentic photo/);
  assert.ok(result.prompt.length>400);
 }
});
test('no scraped evidence or unsafe URL fails closed',()=>{
 assert.throws(()=>creativeFromWebsiteFindings({sourceUrl:'https://example.org',observations:{}}));
 assert.throws(()=>creativeFromWebsiteFindings({sourceUrl:'http://localhost',observations:{title:'fake'}}));
});

test('website evidence identifies different campaign approaches without asking category',()=>{
 assert.equal(inferCreativeSector({title:'Encore',meta_description:'Private aviation and luxury concierge'}),'concierge');
 assert.equal(inferCreativeSector({headings:['Seasonal plates and dining']}),'restaurant');
 assert.equal(inferCreativeSector({title:'Beauty Salon and Massage'}),'beauty');
 assert.equal(inferCreativeSector({title:'Kitchen fitting and property renovations'}),'renovation');
});

test('premium access and curated experiences are interpreted as concierge positioning',()=>{
 assert.equal(inferCreativeSector({title:'Example',meta_description:'A premium access platform built around exclusivity and curated experiences.'}),'concierge');
});
test('a roofing company is treated as a trades business, not generic luxury',()=>{
 assert.equal(inferCreativeSector({title:'Harbour Roofing',meta_description:'Roof repairs, guttering, new roofs and roof inspections in Portsmouth'}),'roofing');
 const brief=creativeFromWebsiteFindings({sourceUrl:'https://harbour.example.org/',businessType:'roofing',observations:{title:'Harbour Roofing',meta_description:'Roof repairs, guttering and roof inspections'}});
 assert.match(brief.prompt,/roof/i);
 assert.doesNotMatch(brief.prompt,/luxury hotel|private aviation/i);
 assert.match(brief.ctaDraft,/quote/i);
});
