import test from 'node:test';import assert from 'node:assert/strict';
import {auditBusinessWebsite,siteAuditMarkdown} from '../src/lib/businessSiteAudit.mjs';
const base={source_url:'https://harbour.example.org/',observations:{title:'Harbour Roofing Portsmouth',meta_description:'Roofing repairs and guttering for Portsmouth homes.',headings:['Roof repairs','Services'],service_links:[{label:'Roof repairs',url:'https://harbour.example.org/services/roof-repairs'}],image_candidates:[{url:'https://harbour.example.org/photo.jpg',alt:'Roof tiles'}]}};
test('website audit identifies missing enquiry route and specific evidence',()=>{
 const result=auditBusinessWebsite(base);
 assert.equal(result.sourceUrl,'https://harbour.example.org/');
 assert.ok(result.actions.some(x=>x.id==='contact_route'&&x.priority==='high'));
 assert.ok(result.observations.some(x=>/roof repairs/i.test(x)));
 assert.ok(!JSON.stringify(result).includes('Google position'));
 assert.ok(!result.searchConsoleConnected);
 assert.match(siteAuditMarkdown(result),/Website improvement/);
});
test('no meta description or headings produces actionable warnings, not invented scores',()=>{
 const r=auditBusinessWebsite({source_url:'https://x.example/',observations:{title:'Test',meta_description:'',headings:[]}});
 assert.ok(r.actions.some(x=>x.id==='description'));
 assert.ok(r.actions.some(x=>x.id==='heading'));
 assert.equal(r.rankingsMeasured,false);
 assert.equal(r.coreWebVitalsMeasured,false);
});
test('stronger evidence reduces obvious recommendations without implying launch readiness',()=>{
 const good={...base,observations:{...base.observations,headings:['Roof repairs','Contact'],service_links:[{label:'Get a free quote',url:'https://harbour.example.org/contact'}]}};
 const r=auditBusinessWebsite(good);
 assert.ok(!r.actions.some(x=>x.id==='contact_route'));
 assert.equal(r.readyForPublishing,false);
});
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
test('url-to-marketing-document preserves site-specific SEO audit without claiming measured rankings',()=>{
 const c=prepareUrlCampaign(base);
 const doc=createMarketingDocument(c);
 assert.match(doc.websiteAuditText,/Roof repairs/);
 assert.match(doc.websiteAuditText,/enquiry or booking action/i);
 assert.match(doc.websiteAuditText,/not been tested/i);
 assert.equal(doc.canPublish,false);
});
test('expanded research exposes actual coverage, omissions and seasonal uncertainty in saved audit',()=>{
 const report={...base,page_reports:[{...base,status:'extracted_unconfirmed'},{source_url:'https://harbour.example.org/services/',status:'extracted_unconfirmed',freshness:{seasonal_excerpts:['Start the year with us']}}],coverage:{omitted_urls:['https://harbour.example.org/about/']},enrichment_warnings:['booking: secondary read failed']};
 const campaign=prepareUrlCampaign(report),doc=createMarketingDocument(campaign);
 assert.match(doc.websiteAuditText,/Pages read:.*services\//);
 assert.match(doc.websiteAuditText,/Not read within the page budget:.*about\//);
 assert.match(doc.websiteAuditText,/Failed page reads: booking/);
 assert.match(doc.websiteAuditText,/Start the year with us/);
 assert.match(doc.websiteAuditText,/current validity is unknown/);
 assert.equal(campaign.reviewRequired,true);assert.equal(campaign.canSpend,false);
});
