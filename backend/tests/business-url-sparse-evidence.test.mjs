import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
test('metadata-only research cannot silently become a generic campaign',()=>{
 const audit={source_url:'https://example.org/',status:'extracted_unconfirmed',
  evidence:{status:'insufficient'},observations:{title:'Example business',meta_description:'A wonderful business for everyone',headings:[],visible_paragraphs:[],service_links:[]}};
 assert.throws(()=>prepareUrlCampaign(audit),/insufficient business evidence/i);
});
