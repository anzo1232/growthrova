import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);

test('saved photo editor exposes static composition and explains its limits',async()=>{
 const bundle=await build({entryPoints:['src/BusinessPhotoIntake.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
 const library={revision:1,assets:[],posts:[{day:1}],selection:{assetIds:[],postAssignments:[],reviewNotes:[]}};
 let index=0;
 const hooks={...React,useState:initial=>[index++===4?library:initial,()=>{}],useEffect:()=>{},useRef:initial=>({current:initial})};
 const module={exports:{}};
 new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const tree=module.exports.default({scope:'synthetic',mediaUrl:'/media',mediaRequest:async()=>{}});
 function flatten(node){if(!node||typeof node!=='object')return [];return [node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
 const nodes=flatten(tree),text=nodes.map(n=>React.Children.toArray(n.props?.children).filter(x=>typeof x==='string').join('')).join(' ');
 const button=nodes.find(n=>n.type==='button'&&React.Children.toArray(n.props.children).join('')==='Compose static saved draft for day 1');
 assert.ok(button,'Actual media editor must expose a static draft action');
 assert.equal(button.props.disabled,true,'No saved assignment cannot render');
 assert.match(text,/one saved photo/i);
 const logoControl=nodes.find(n=>n.type==='select'&&n.props['aria-label']==='Static logo for day 1');
 assert.ok(logoControl,'Owner explicitly chooses the saved logo role');
 assert.equal(logoControl.props.value,'');
 assert.match(text,/whole original logo/i);
});

test('campaign editor chooses graphic words without replacing the social caption',async()=>{
 const {createMarketingDocument}=await import('../src/lib/businessMarketingDocument.mjs');
 const {prepareOwnerCampaign}=await import('../src/lib/businessUrlCampaignPipeline.mjs');
 const {confirmOwnerStrategy}=await import('../src/lib/businessOwnerStrategy.mjs');
 const document=confirmOwnerStrategy(createMarketingDocument(prepareOwnerCampaign({business:'Synthetic Workshop',sourceUrl:'https://example.org/',goal:'enquiries',offer:'Bicycle servicing.',audience:'Local commuters',positioning:'',callToAction:'Ask about appointments.'})));
 const record={id:'e'.repeat(32),revision:1,document};
 const states=[record,JSON.stringify(document)];let index=0;const changes=[];
 const hooks={...React,useState:initial=>[index<states.length?states[index++]:initial,value=>changes.push(value)],useEffect:()=>{},useRef:initial=>({current:initial})};
 const bundle=await build({entryPoints:['src/BusinessMarketingBoard.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',loader:{'.css':'empty'},external:['react','react/jsx-runtime'],logLevel:'silent'});
 const module={exports:{}};
 new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const tree=module.exports.default({api:async()=>{throw Error('No network in render');},mediaRequest:async()=>{}});
 function flatten(node){if(!node||typeof node!=='object')return [];return [node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
 const nodes=flatten(tree),control=nodes.find(n=>n.type==='textarea'&&n.props['aria-label']==='Words on the static graphic');
 assert.ok(control,'Actual campaign editor must expose separate graphic words');
 assert.equal(control.props.maxLength,500);assert.equal(control.props.value,'');
 control.props.onChange({target:{value:'Bicycle servicing at our workshop.'}});
 const next=changes.find(change=>typeof change==='function')(record);
 assert.equal(next.document.posts[0].graphicText,'Bicycle servicing at our workshop.');
 assert.equal(next.document.posts[0].copyDraft,document.posts[0].copyDraft);
 assert.deepEqual(next.document.posts.slice(1),document.posts.slice(1));
});
