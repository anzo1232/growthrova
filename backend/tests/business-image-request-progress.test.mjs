import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};
function fixture(model){
 let index=0,refIndex=0;const states=[],refs=[],reads=[],posts=[];
 const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
 const module={exports:{}};
 new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const parent={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64),issues:[],size:'square_2k',quality:'standard',visualBrief:'An illustrative workshop scene with space for the saved headline.'};
 const status=candidate=>({available:true,model,candidates:candidate?[candidate,parent]:[parent],selection:{selectedIds:[parent.operationId],version:1}});
 states[0]=status();
 const record={id:'c'.repeat(32),revision:1,document:{posts:[{day:1,copyDraft:'Preserve the full caption.'}],creatives:[]}};
 const snapshot=structuredClone(record);
 const api=async(url,options)=>{if(url.endsWith('/estimate'))return{state:'available',reservationMicrousd:45000};const call={...deferred(),url,options};(options?posts:reads).push(call);return call.promise;};
 const render=()=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/campaign/images',record}));};
 const button=label=>render().find(n=>n.type==='button'&&n.props.children===label);
 const prepare=async()=>{
  render().find(n=>n.props['aria-label']==='Plan alternative for '+parent.operationId).props.onClick();
  render().find(n=>n.props['aria-label']==='Alternative visual direction').props.onChange({target:{value:'An illustrative workshop scene with a warm wall and more room on the left.'}});
  await button('Check alternative cost').props.onClick();
 };
 const start=()=>button('Generate alternative background').props.onClick();
 return{render,button,prepare,start,reads,posts,parent,status,record,snapshot};
}

test('read progress during a single alternative request without unlocking or duplicating it',async()=>{
 const f=fixture();await f.prepare();const request=f.start();
 assert.equal(f.button('Check saved image requests').props.disabled,false,'Checking saved progress must work during generation');
 const checking=f.button('Check saved image requests').props.onClick();
 assert.equal(f.reads.length,1);
 const duplicate=f.button('Check saved image requests').props.onClick();
 assert.equal(f.reads.length,1,'Repeated checks share one status read');
 const pending={...f.parent,...f.posts[0].options.data,state:'pending'};
 f.reads[0].resolve(f.status(pending));await checking;await duplicate;
 assert.equal(f.button('Generate alternative background').props.disabled,true,'A read cannot acknowledge the original POST');
 await f.button('Generate alternative background').props.onClick();assert.equal(f.posts.length,1);
 assert.equal(f.render().filter(n=>n.type==='article').length,2,'Retain original alongside pending progress');
 f.posts[0].reject(Error('Response lost'));await request;
 const recovery=f.button('Check saved image requests').props.onClick();
 f.reads[1].resolve(f.status(pending));await recovery;
 assert.equal(f.button('Generate alternative background').props.disabled,true,'Saved pending outcome must retain the submission hold');
 const finish=f.button('Check saved image requests').props.onClick();
 f.reads[2].resolve(f.status({...pending,state:'proposed'}));await finish;
 assert.equal(f.button('Cancel alternative').props.disabled,false,'Completed saved result restores editing');
 assert.equal(f.posts.length,1);assert.deepEqual(f.record,f.snapshot);
});

test('a progress response started before POST completion cannot replace its completed candidate',async()=>{
 const f=fixture();await f.prepare();const request=f.start();
 const checking=f.button('Check saved image requests').props.onClick();
 assert.equal(f.reads.length,1,'Status read must actually start during generation');
 const completed={...f.parent,...f.posts[0].options.data,state:'proposed'};
 f.posts[0].resolve(completed);await new Promise(setImmediate);
 f.reads[0].resolve(f.status({...completed,state:'pending'}));await checking;await request;
 const articles=f.render().filter(n=>n.type==='article');
 const text=node=>typeof node==='string'?node:!node?'':React.Children.toArray(node.props?.children).map(text).join(' ');
 assert.match(text(articles[0]),/proposed/,'A late pending read must not overwrite completed bytes');
 assert.equal(f.button('Generate alternative background').props.disabled,false);
 assert.equal(f.posts.length,1);assert.deepEqual(f.record,f.snapshot);
});

test('failed progress check preserves the outstanding request and allows another read',async()=>{
 const f=fixture();await f.prepare();const request=f.start();
 const checking=f.button('Check saved image requests').props.onClick();
 assert.equal(f.reads.length,1);
 f.reads[0].reject(Error('Status temporarily unavailable'));await checking;
 assert.equal(f.button('Check saved image requests').props.disabled,false);
 assert.equal(f.button('Generate alternative background').props.disabled,true);
 assert.ok(f.render().some(n=>n.props.role==='alert'&&n.props.children==='Status temporarily unavailable'));
 f.posts[0].resolve({...f.parent,...f.posts[0].options.data,state:'proposed'});await request;
 assert.equal(f.posts.length,1);
});

test('an idempotent POST replay returning pending is progress, not a completed acknowledgement',async()=>{
 const f=fixture();await f.prepare();const request=f.start();
 const pending={...f.parent,...f.posts[0].options.data,state:'pending'};
 f.posts[0].resolve(pending);await request;
 assert.equal(f.button('Generate alternative background').props.disabled,true,'A saved pending replay cannot unlock another inference');
 const checking=f.button('Check saved image requests').props.onClick();
 f.reads[0].resolve(f.status({...pending,state:'proposed'}));await checking;
 assert.equal(f.button('Generate alternative background').props.disabled,false);
 assert.equal(f.posts.length,1);
});

test('saved Runway progress refreshes the same task without another generation',async()=>{
 const f=fixture();
 const checking=f.button('Check saved image requests').props.onClick();
 const pending={...f.parent,state:'pending',provider:'runway',providerTaskId:'12345678-1234-1234-1234-123456789abc'};
 f.reads[0].resolve(f.status(pending));
 await new Promise(setImmediate);
 assert.equal(f.posts.length,1,'Saved Runway task must be refreshed');
 assert.equal(f.posts[0].url,'/campaign/images/'+pending.operationId+'/refresh');
 assert.equal(f.posts[0].options.method,'POST');
 f.posts[0].resolve({...pending,state:'proposed'});
 await new Promise(setImmediate);
 f.reads[1].resolve(f.status({...pending,state:'proposed'}));
 await checking;
 assert.equal(f.posts.length,1,'Only a non-billable refresh is sent');
});

test('Runway campaigns offer complete advert design rather than forcing background mode',()=>{
 const f=fixture('gemini_image3_pro');
 assert.ok(f.render().some(n=>n.props['aria-label']==='Image design mode'));
});
