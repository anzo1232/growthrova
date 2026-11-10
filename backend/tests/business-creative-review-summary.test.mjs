import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';

const require=createRequire(import.meta.url);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const bundle=entry=>build({entryPoints:[entry],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const load=(built,hooks)=>{
  const module={exports:{}};
  new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
  return module.exports.default;
};
const candidate={operationId:'a'.repeat(32),sha256:'b'.repeat(64),day:1,state:'proposed',renderingMode:'complete_advert',reviewVersion:0};

test('complete-advert inspection connects the saved pixel-bound review report',async()=>{
  let slot=0;
  const hooks={...React,useEffect:()=>{},useRef:value=>({current:value}),useState:initial=>[
    slot++===7?{url:'blob:synthetic',candidate}:typeof initial==='function'?initial():initial,()=>{}]};
  const Component=load(await bundle('src/GrowthrovaImageCandidates.jsx'),hooks);
  const nodes=flatten(Component({api:()=>assert.fail('Rendering must not request review'),url:'/campaign/images',
    record:{id:'c'.repeat(32),revision:2,document:{posts:[{day:1}],creatives:[]}}}));
  const summary=nodes.find(n=>typeof n.type==='function'&&n.props.url==='/campaign/images/'+candidate.operationId+'/creative-review');
  assert.ok(summary,'The actual advert inspection must expose its saved aggregate review');
  assert.equal(summary.props.candidate,candidate);
});

test('review summary uses one read, rejects mismatched pixels, recovers and hides stale results',async()=>{
  const built=await bundle('src/GrowthrovaCreativeReview.jsx');
  let cursor=0,refIndex=0;const states=[],refs=[];
  const hooks={...React,useEffect:()=>{},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});},
    useState:initial=>{const i=cursor++;if(!(i in states))states[i]=initial;return[states[i],value=>states[i]=typeof value==='function'?value(states[i]):value];}};
  const Component=load(built,hooks);
  let calls=0,release;
  const api=(url,options)=>{assert.equal(options,undefined,'Summary must only read the saved report');calls++;return new Promise(resolve=>release=resolve);};
  const props={api,url:'/campaign/images/'+candidate.operationId+'/creative-review',candidate,revision:2};
  const render=(extra={})=>{cursor=0;refIndex=0;return flatten(Component({...props,...extra}));};
  const check=nodes=>nodes.find(n=>n.type==='button'&&n.props.children==='Check recorded artwork review');
  const checks=Object.fromEntries(['visual','factual','brand','commercial','legibility','crop','cta','wording'].map(k=>[k,'checked']));
  const report={operationId:candidate.operationId,sha256:candidate.sha256,status:'reviewed_draft',checks,pixelsMatch:true,approved:false,canPublish:false,canSpend:false};
  const first=check(render()).props.onClick();await check(render()).props.onClick();
  assert.equal(calls,1,'Double click must not duplicate even a review read');
  release({...report,sha256:'d'.repeat(64)});await first;
  assert.ok(render().some(n=>n.props.role==='alert'),'Different image hash must never display a successful review');
  const retry=check(render()).props.onClick();release({...report,status:'held',checks:{...checks,wording:'needs_changes'}});await retry;
  const text=JSON.stringify(render().map(n=>n.props.children));
  assert.match(text,/Needs changes/);assert.match(text,/Requested wording/);assert.match(text,/independent/i);
  assert.equal(render({revision:3}).some(n=>n.type==='dl'),false,'Saved-context changes immediately hide the previous report');
  const changed=check(render({revision:3})).props.onClick();release(report);await changed;
  assert.equal(render({revision:3}).some(n=>n.type==='dl'),true);
  assert.equal(render({revision:3,candidate:{...candidate,state:'held',compositionHeld:true}}).some(n=>n.type==='dl'),false,
    'A new hold must hide an earlier review even when the original bytes are unchanged');
  assert.equal(check(render({disabled:true})).props.disabled,true);
  assert.equal(render({disabled:true}).some(n=>n.type==='dl'),false);
  assert.equal(calls,3,'Review uses reads only; no inference or observation mutation');
  const late=check(render({revision:4})).props.onClick();
  render({revision:5});release(report);await late;
  assert.equal(render({revision:5}).some(n=>n.type==='dl'),false,'A late report from the previous saved context cannot appear');
  const incomplete=check(render({revision:5})).props.onClick();
  release({...report,checks:{visual:'checked'}});await incomplete;
  assert.ok(render({revision:5}).some(n=>n.props.role==='alert'),'Missing criteria cannot imply complete review');
  assert.equal(render({revision:5}).some(n=>n.type==='dl'),false);
});
