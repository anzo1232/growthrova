import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {prepareOwnerCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {confirmOwnerStrategy} from '../src/lib/businessOwnerStrategy.mjs';
const require=createRequire(import.meta.url);
async function render(value,disabled=false){
 const bundle=await build({entryPoints:['src/BusinessCampaignBrand.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
 const module={exports:{}};
 new Function('require','module','exports',bundle.outputFiles[0].text)(require,module,module.exports);
 return renderToStaticMarkup(React.createElement(module.exports.default,{value,disabled}));
}
test('empty branding asks for explicit settings with no inferred logo or palette',async()=>{
 const html=await render(undefined);
 for(const label of ['Brand name','Primary brand colour','Secondary brand colour','Brand typography'])assert.ok(html.includes(label));
 assert.match(html,/No brand settings applied/);
 assert.match(html,/logo.*not connected/i);
 assert.match(html,/Apply brand settings/);
 assert.doesNotMatch(html,/<img|background-color:/);
});
test('exact stored colours remain visible with actionable contrast warning and locked controls',async()=>{
 const value={name:'Workshop & Co',primary_color:'#123abc',secondary_color:'#123abc',font_style:'classic'};
 const html=await render(value,true);
 assert.match(html,/value="#123abc"/);
 assert.match(html,/value="Workshop &amp; Co"/);
 assert.match(html,/enough contrast/);
 assert.match(html,/<fieldset disabled=""/);
 assert.match(html,/not a rendered post/);
});

test('typing unapplied brand settings retains and pauses mounted unsaved media work',async()=>{
 const document=confirmOwnerStrategy(createMarketingDocument(prepareOwnerCampaign({business:'Synthetic Workshop',sourceUrl:'https://example.org/',
  goal:'enquiries',offer:'Bicycle servicing.',audience:'Local commuters',positioning:'',callToAction:'Ask about appointments.'})));
 document.calendarStartDate='2026-11-01';
 const record={id:'e'.repeat(32),revision:1,document};
 const bundle=await build({entryPoints:['src/BusinessMarketingBoard.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',loader:{'.css':'empty'},external:['react','react/jsx-runtime'],logLevel:'silent'});
 function descendants(element){
  if(!element||typeof element!=='object')return [];
  return [element,...React.Children.toArray(element.props?.children).flatMap(descendants)];
 }
 for(const [pending,mediaPending] of [[false,true],[true,true],[true,false],[false,false]]){
  // Seed a real board render at the saved-record checkpoint, with media
  // changes still mounted. Effects/network/child components do not execute.
  const states=[record,JSON.stringify(document),null,false,mediaPending,pending];
  let index=0;
  const changes=[],confirmations=[];
  const hooks={...React,useState:initial=>[index<states.length?states[index++]:initial,value=>changes.push(value)],
   useRef:initial=>({current:initial}),useEffect:()=>{}};
  const module={exports:{}};
  new Function('require','module','exports','window',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports,
   {confirm:message=>{confirmations.push(message);return false;}});
  const tree=module.exports.default({api:()=>{},mediaRequest:()=>{},scope:'synthetic'});
  const nodes=descendants(tree);
  const posting=nodes.find(node=>node.type?.name==='GrowthrovaSocialDrafts');
  assert.equal(posting.props.disabled,pending||mediaPending,'Posting revisions pause while brand/media changes are unsaved');
  assert.ok(nodes.some(node=>node.type?.name==='BusinessPhotoIntake'),'Brand typing must not unmount and erase pending media');
  const brand=nodes.find(node=>node.type?.name==='BusinessCampaignBrand');
  if(mediaPending){
   brand.props.onApply({name:'Explicit brand',primary_color:'',secondary_color:'',font_style:''});
   assert.equal(confirmations.length,1,'Brand application must retain the existing media-leave confirmation');
   assert.match(confirmations[0],/Save media candidates and observations first/);
   assert.deepEqual(changes,[],'Cancelling must preserve the campaign and mounted media work');
  }
  const controls=nodes.find(node=>node.type==='fieldset'&&node.props.className==='bmb-media-controls');
  assert.equal(controls.props.disabled,pending,'Pause media actions while retaining the mounted intake');
  const replace=nodes.find(node=>node.type==='button'&&node.props.children==='Create a separate 30-day calendar from this strategy');
  assert.equal(replace.props.disabled,pending||mediaPending,'A new calendar must not discard unapplied brand work');
 }
});
