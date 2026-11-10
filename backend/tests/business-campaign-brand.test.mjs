import test from 'node:test';
import assert from 'node:assert/strict';
import * as brand from '../src/lib/businessCampaignBrand.mjs';

test('explicit brand edits preserve exact palette, incomplete work and checked copy',()=>{
 const original={business:'Workshop',posts:[{day:1,status:'copy_reviewed',copyDraft:'Your saved words.'}],creatives:[],canPublish:false,canSpend:false};
 const snapshot=structuredClone(original);
 let doc=brand.editCampaignBrand(original,{name:'Workshop & Co',primary_color:'#123abc'});
 assert.deepEqual(doc.brandKit,{name:'Workshop & Co',primary_color:'#123abc',secondary_color:'',font_style:''});
 doc=brand.editCampaignBrand(doc,{secondary_color:'#123abc',font_style:'classic'});
 assert.equal(doc.brandKit.secondary_color,'#123abc','Exact low-contrast brand colours can be saved; readability is a separate warning.');
 assert.equal(brand.editCampaignBrand(doc,{name:'Workshop & Co'}),doc);
 assert.equal(doc.posts,original.posts);
 assert.deepEqual(original,snapshot);
 assert.equal(doc.canPublish,false);
});

test('brand boundary refuses invented rights, logo paths and malformed palette without losing work',()=>{
 const doc={brandKit:{name:'Workshop',primary_color:'#123ABC',secondary_color:'#FFFFFF',font_style:'modern'}};
 const before=structuredClone(doc);
 for(const patch of [{primary_color:'red'},{secondary_color:'#fff'},{font_style:'unknown'},
  {name:'a'.repeat(39)},{name:'Name\nNew line'},{logo_path:'/tmp/logo.png'},{locked:true},{rights_confirmed:true},null,[]])
  assert.throws(()=>brand.editCampaignBrand(doc,patch));
 assert.deepEqual(doc,before);
});
