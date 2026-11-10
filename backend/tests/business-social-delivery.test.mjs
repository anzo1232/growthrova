import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaSocialDelivery.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let cursor=0,refCursor=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refCursor++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
const confirm=nodes=>nodes.find(n=>n.props['aria-label']==='Approve exact saved posting version');
const draft={draftId:'a'.repeat(32),revision:2,artworkSha256:'b'.repeat(64),current:true,state:'draft'};
let calls=[],resolve;
const jobs=[{jobId:'j1',channel:'linkedin',state:'scheduled',mode:'simulation',approvalCurrent:true}];
const api=async(url,options)=>{
  calls.push({url,options});
  if(url.endsWith('/approve')){await new Promise(done=>resolve=done);return {jobs,mode:'simulation',available:true};}
  return {jobs:[],mode:'simulation',available:true};
};
const render=(props={})=>{cursor=0;refCursor=0;return flatten(module.exports.default({api,url:'/saved/delivery',draft,...props}));};
let nodes=render();
assert.equal(button(nodes,'Approve and schedule rehearsal'),undefined,'Owner must check delivery availability first');
await button(nodes,'Check scheduling').props.onClick();
nodes=render();
assert.equal(confirm(nodes).props.disabled,true,'Exact artwork must be inspected');
confirm(nodes).props.onChange({target:{checked:true}});
assert.equal(button(render(),'Approve and schedule rehearsal').props.disabled,true);
nodes=render({inspected:true});
confirm(nodes).props.onChange({target:{checked:true}});
nodes=render({inspected:true});
assert.equal(button(nodes,'Approve and schedule rehearsal').props.disabled,false);
const retained=button(nodes,'Approve and schedule rehearsal').props.onClick;
render({inspected:true,disabled:true});
await retained();
assert.equal(calls.length,1,'Captured controls cannot dispatch after editing disables approval');
nodes=render({inspected:true});
const send=button(nodes,'Approve and schedule rehearsal').props.onClick();
await button(render({inspected:true}),'Approve and schedule rehearsal').props.onClick();
assert.equal(calls.length,2,'One in-flight approval only');
assert.deepEqual(calls[1].options.data,{expectedRevision:2,artworkSha256:draft.artworkSha256});
assert.equal(calls[1].url,'/saved/delivery/approve');
resolve();await send;
nodes=render({inspected:true});
assert.equal(button(nodes,'Approve and schedule rehearsal').props.disabled,true,'Scheduled jobs must not be sent again');
assert.ok(button(nodes,'Pause scheduled delivery'));
// Reopen unknown outcome: uncertainty is visible and never turned into a retry button.
states=[];refs=[];
const uncertainApi=async()=>({available:true,mode:'simulation',jobs:[{...jobs[0],state:'uncertain'}]});
await button(render({api:uncertainApi}),'Check scheduling').props.onClick();
nodes=render({api:uncertainApi,inspected:true});
assert.equal(button(nodes,'Approve and schedule rehearsal').props.disabled,true);
assert.ok(button(nodes,'Check delivery confirmation'),'Uncertain outcomes offer a lookup, never a resend');
assert.ok(nodes.some(n=>typeof n.props.children==='string'&&n.props.children.includes('posting again could create a duplicate')));
// A receipt from the controlled adapter must not be presented as publication.
states=[];refs=[];
const simulatedApi=async()=>({available:true,mode:'simulation',jobs:[{...jobs[0],state:'simulated',receipt:{id:'test-receipt'}}]});
await button(render({api:simulatedApi}),'Check scheduling').props.onClick();
nodes=render({api:simulatedApi});
assert.ok(nodes.some(n=>n.props.children==='Rehearsal completed. Nothing was published.'));
assert.ok(nodes.some(n=>n.props.children==='Rehearsal receipt: test-receipt'));
// Lost acknowledgement remains tied to the same saved version, with status recovery.
states=[];refs=[];
let attempts=0;
const lostApi=async(url,options)=>{
 if(options){attempts++;throw Error('Connection lost');}
 return {available:true,mode:'simulation',jobs:attempts?jobs:[]};
};
await button(render({api:lostApi,inspected:true}),'Check scheduling').props.onClick();
confirm(render({api:lostApi,inspected:true})).props.onChange({target:{checked:true}});
await button(render({api:lostApi,inspected:true}),'Approve and schedule rehearsal').props.onClick();
assert.ok(button(render({api:lostApi,inspected:true}),'Retry same approval'));
await button(render({api:lostApi,inspected:true}),'Check scheduling').props.onClick();
assert.equal(attempts,1);
assert.equal(button(render({api:lostApi,inspected:true}),'Approve and schedule rehearsal').props.disabled,true);
console.log('PASS exact-version scheduling, inspection, stale controls, single flight, status recovery and truthful rehearsal receipts');
// Inspecting artwork while a status read is pending changes the UI identity.
// Drop the stale result, but release the lock so the owner can check again.
states=[];refs=[];
let settleRead;
const delayedApi=()=>new Promise(done=>settleRead=done);
const read=button(render({api:delayedApi}),'Check scheduling').props.onClick();
render({api:delayedApi,disabled:true});
render({api:delayedApi,inspected:true});
settleRead({available:true,mode:'simulation',jobs});
await read;
nodes=render({api:delayedApi,inspected:true});
assert.equal(button(nodes,'Check scheduling').props.disabled,false,'Dropped status response must release the UI lock');
assert.equal(button(nodes,'Pause scheduled delivery'),undefined,'Stale response must not populate changed scope');
