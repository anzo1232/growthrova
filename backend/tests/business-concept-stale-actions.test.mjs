import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';

// Exercise captured UI handlers across renders, before effect cleanup runs.
const require=createRequire(import.meta.url);
const bundle=await build({entryPoints:['src/GrowthrovaCreativePlans.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let stateIndex,refIndex,states,refs;
const hooks={...React,useEffect:()=>{},useState:initial=>{
  const i=stateIndex++;
  if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
  return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;}];
},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const document=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',
  observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
const concept={id:'c1',headline:'A leak needs attention',buyerMotivation:'Discuss a leaking pipe',
  visualDirection:'Illustrative pipe with a droplet and space for words.',callToAction:'Enquire about plumbing',
  evidence:[{id:'brief-offer',quote:'Plumbing enquiries for local homes.'}]};
const plan={operationId:'a'.repeat(32),state:'proposed',creativePlan:{mode:'initial'},
  concepts:[concept],sourceContext:writingContext(document),brandKit:document.brandKit??null,
  issues:[],material:{evidence:[]},selectedConceptIds:[],selectionRevision:0};
let calls,props;
const api=async(url,options)=>{calls.push({url,options});return {...plan,selectedConceptIds:options?.data?.selectedConceptIds||[]};};
function setup(){
  states=[{available:true,conceptPlans:[plan]}];refs=[];calls=[];
  props={api,url:'/campaign/writing',record:{id:'synthetic-qa',revision:1,document},onApply:()=>assert.fail('No content apply expected')};
}
function render(){stateIndex=0;refIndex=0;return flatten(module.exports.default(props));}
const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
for(const change of ['unsaved words','disabled','revision']){
  for(const operation of ['plan','feedback']){
    setup();const nodes=render();
    const handler=operation==='plan'?button(nodes,'More ideas').props.onClick:
      nodes.find(n=>n.type==='input'&&n.props['aria-label']==='Favourite '+concept.headline).props.onChange;
    if(change==='disabled')props={...props,disabled:true};
    else props={...props,record:{...props.record,...(change==='revision'?{revision:2}:
      {document:{...document,posts:document.posts.map((post,i)=>i===0?{...post,graphicText:'Owner edit in progress'}:post)}})}};
    render();
    await handler({target:{checked:true}});
    assert.equal(calls.length,0,`Captured ${operation} action must not submit after ${change}`);
  }
}
// Same saved inputs across an ordinary rerender remain usable.
setup();let nodes=render();const request=button(nodes,'More ideas').props.onClick;
props={...props,record:{...props.record}};render();await request();
assert.equal(calls.length,1);
assert.equal(calls[0].options.data.creativePlan.mode,'more_ideas');
setup();nodes=render();
await nodes.find(n=>n.type==='input'&&n.props['aria-label']==='Favourite '+concept.headline).props.onChange({target:{checked:true}});
assert.equal(calls.length,1);
assert.deepEqual(calls[0].options.data.selectedConceptIds,[concept.id]);
// The explicit compare/apply step must also preserve new owner edits.
setup();states[4]=concept;states[5]=true;states[7]='1';
let applied=0;props={...props,onApply:()=>{applied++;}};
const apply=button(render(),'Apply concept to this image draft');
assert.ok(apply);
props={...props,disabled:true};render();await apply.props.onClick();
assert.equal(applied,0,'Captured compare/apply cannot overwrite owner work after editing starts');
setup();states[4]=concept;states[5]=true;states[7]='1';
let updated;props={...props,onApply:change=>{updated=change(document);}};
await button(render(),'Apply concept to this image draft').props.onClick();
assert.equal(updated.posts[0].graphicText,concept.headline);
assert.equal(updated.posts[0].copyDraft,document.posts[0].copyDraft);
assert.deepEqual(updated.posts.slice(1),document.posts.slice(1));
assert.equal(calls.length,0,'Applying reviewed words never invokes a provider');
