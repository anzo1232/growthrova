import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';

const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaCreativePlans.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];

test('one saved-plan check recovers the lost More ideas acknowledgement before checking the older selected set',async()=>{
  const document=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',
    observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
  const original={operationId:'a'.repeat(32),state:'proposed',creativePlan:{mode:'initial'},concepts:Array.from({length:6},(_,i)=>({id:'old'+i,headline:'Saved direction '+i,buyerMotivation:'A reviewed customer need',visualDirection:'An illustrative scene',callToAction:'Enquire',evidence:[]})),
    sourceContext:writingContext(document),brandKit:document.brandKit??null,issues:[],material:{evidence:[]},selectedConceptIds:[]};
  let cursor=0,refIndex=0;const states=[{available:true,conceptPlans:[original]}],refs=[];
  const hooks={...React,useEffect:()=>{},useState:initial=>{const i=cursor++;
    if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
    return[states[i],value=>states[i]=typeof value==='function'?value(states[i]):value];},
    useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
  const module={exports:{}};
  new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
  let submission,submissions=0;const checks=[];
  const api=async(url,options)=>{
    if(url==='/writing/concept-plans'){
      submissions++;submission=options.data;
      throw Error('Synthetic lost acknowledgement');
    }
    const recovered={...original,operationId:submission.operationId,creativePlan:submission.creativePlan,
      state:'pending',backgroundPlan:true,providerResponseId:'resp_saved12345'};
    if(url==='/writing')return {available:true,conceptPlans:[recovered,original]};
    checks.push(url);
    return {...recovered,state:'proposed',concepts:Array.from({length:6},(_,i)=>({id:'new'+i,headline:'A different saved direction '+i,
      buyerMotivation:'A distinct customer need',visualDirection:'An illustrative service scene',callToAction:'Enquire',evidence:[]}))};
  };
  const props={api,url:'/writing',record:{id:'synthetic-qa',revision:1,document},onApply:()=>assert.fail('Recovery must preserve owner work')};
  const render=()=>{cursor=0;refIndex=0;return flatten(module.exports.default(props));};
  const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
  // Retain a previously selected completed set, as when requesting More ideas.
  states[3]=original.operationId;
  assert.equal(button(render(),'More ideas').props.disabled,false);
  await button(render(),'More ideas').props.onClick();
  assert.equal(submissions,1);
  assert.ok(render().some(n=>n.props.role==='alert'));
  await button(render(),'Check saved concept plans').props.onClick();
  assert.deepEqual(checks,['/writing/'+submission.operationId+'/refresh'],
    'The saved operation with the lost acknowledgement must be checked, not its completed parent');
  assert.ok(render().some(n=>n.type==='h4'&&n.props.children==='A different saved direction 0'));
  assert.equal(render().some(n=>n.props.role==='status'&&String(n.props.children).includes('acknowledgement pending')),false);
  assert.equal(states[0].conceptPlans[0].concepts.length,6);
  assert.equal(states[0].conceptPlans[1],original,'The previous set stays unchanged');
  assert.equal(submissions,1,'Recovery must not resubmit inference');
  assert.equal(button(render(),'Check saved concept plans').props.disabled,false);
});

test('reopening retains saved concepts when checking the pending provider response fails, then recovers without submission',async()=>{
  const document=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',
    observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
  const original={operationId:'a'.repeat(32),state:'proposed',creativePlan:{mode:'initial'},concepts:[],
    sourceContext:writingContext(document),brandKit:document.brandKit??null,issues:[],material:{evidence:[]},selectedConceptIds:[]};
  const pending={...original,operationId:'b'.repeat(32),state:'pending',backgroundPlan:true,
    creativePlan:{mode:'more_ideas'},issues:['Check this same saved response.']};
  const saved={available:true,message:'Saved planning is available.',conceptPlans:[pending,original]};
  let cursor=0,refIndex=0;const states=[],refs=[];
  const hooks={...React,useEffect:()=>{},useState:initial=>{const i=cursor++;
    if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
    return[states[i],value=>states[i]=typeof value==='function'?value(states[i]):value];},
    useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
  const module={exports:{}};
  new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
  let checks=0;const api=async(url,options)=>{
    if(url==='/writing'){assert.equal(options,undefined);return saved;}
    assert.equal(url,'/writing/'+pending.operationId+'/refresh','Only the existing response may be checked');
    assert.equal(options.method,'POST');assert.deepEqual(options.data,{});
    if(++checks===1)throw Error('Synthetic status check unavailable');
    return {...pending,state:'proposed',concepts:Array.from({length:6},(_,i)=>({id:'new'+i,headline:'Recovered service direction '+i,
      buyerMotivation:'A reviewed need',visualDirection:'An illustrative service scene',callToAction:'Enquire',evidence:[]})),issues:[]};
  };
  const props={api,url:'/writing',record:{id:'synthetic-qa',revision:1,document},onApply:()=>assert.fail('No owner work changes')};
  const render=()=>{cursor=0;refIndex=0;return flatten(module.exports.default(props));};
  const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
  await button(render(),'Check saved concept plans').props.onClick();
  assert.ok(render().some(n=>n.type==='select'&&n.props['aria-label']==='Saved concept set'),
    'A failed provider status check must not hide successfully loaded history');
  assert.deepEqual(states[0].conceptPlans,[pending,original]);
  assert.ok(render().some(n=>n.props.role==='alert'&&n.props.children==='Synthetic status check unavailable'));
  assert.equal(button(render(),'Check saved concept plans').props.disabled,false);
  assert.equal(button(render(),'Propose six visual concepts').props.disabled,true);
  await button(render(),'Check saved concept plans').props.onClick();
  assert.equal(checks,2);
  assert.equal(states[0].conceptPlans[0].concepts.length,6);
  assert.equal(states[0].conceptPlans[1],original);
  assert.deepEqual(saved.conceptPlans,[pending,original],'Do not mutate the saved snapshot during refresh');
  assert.equal(render().some(n=>n.props.role==='alert'),false);
});
