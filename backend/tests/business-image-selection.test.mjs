import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
let selection={selectedIds:[],version:0},calls=[],release,loseAck=true;
const candidates=['a','b'].map(value=>({operationId:value.repeat(32),day:1,revision:1,state:value==='a'?'proposed':'held',sha256:'f'.repeat(64),issues:[],origin:'generated',size:'1024x1024'}));
const api=async(url,options)=>{
 calls.push({url,options});
 if(!options)return {available:false,candidates,selection};
 assert.equal(url,'/images/selection');assert.equal(options.method,'PUT');
 await new Promise(resolve=>release=resolve);
 selection={selectedIds:options.data.selectedIds,version:options.data.expectedSelectionVersion+1};
 if(loseAck)throw Error('Selection acknowledgement lost');
 return selection;
};
const record={revision:1,document:{posts:[{day:1}],creatives:[]}};
const render=(extra={})=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/images',record,...extra}));};
const checkbox=(nodes,id)=>nodes.find(n=>n.type==='input'&&n.props['aria-label']==='Keep background '+id);
const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
states[0]={available:false,candidates,selection};
let nodes=render();
assert.ok(checkbox(nodes,candidates[0].operationId),'Missing connected favourite control');
assert.equal(checkbox(nodes,candidates[1].operationId).props.disabled,false,'Held original can remain a favourite without clearing hold');
const pending=checkbox(nodes,candidates[0].operationId).props.onChange();
await checkbox(nodes,candidates[1].operationId).props.onChange();
assert.equal(calls.length,1,'Selection writes cannot race');
release();await pending;
nodes=render();assert.equal(checkbox(nodes,candidates[1].operationId).props.disabled,true);
assert.ok(button(nodes,'Retry same background selection'));
await button(nodes,'Check saved image requests').props.onClick();
nodes=render();assert.equal(checkbox(nodes,candidates[0].operationId).props.checked,true);
assert.equal(button(nodes,'Retry same background selection'),undefined);
assert.equal(nodes.some(n=>n.props.role==='alert'),false);
loseAck=false;
const second=checkbox(nodes,candidates[1].operationId).props.onChange();release();await second;
nodes=render();assert.deepEqual(selection.selectedIds,candidates.map(c=>c.operationId));
assert.equal(checkbox(nodes,candidates[1].operationId).props.checked,true);
assert.equal(candidates[1].state,'held');
assert.equal(calls.filter(c=>c.options).length,2,'Selection cannot invoke image inference');
assert.equal(checkbox(render({disabled:true}),candidates[0].operationId).props.disabled,true);
// A fresh mount restores both selections from the actual GET contract.
states=[];refs=[];nodes=render();await button(nodes,'Check saved image requests').props.onClick();
nodes=render();for(const candidate of candidates)assert.equal(checkbox(nodes,candidate.operationId).props.checked,true);

// A control captured before a campaign change must not write the old source
// choice or favourites, even before effect cleanup runs. Provider availability
// is irrelevant: these free owner choices must remain scoped too.
for(const change of ['disabled','brand','revision','document','url','api']){
 for(const operation of ['source','favourite']){
  states=[{available:false,candidates,selection}];refs=[];
  const writes=[];
  const write=async(url,options)=>{writes.push({url,options});return operation==='source'
   ?{route:'upload',version:1}:{selectedIds:[],version:selection.version+1};};
  const original={api:write};
  const before=render(original);
  const captured=operation==='source'
   ?before.find(n=>n.type==='input'&&n.props['aria-label']==='Upload my own').props.onChange
   :checkbox(before,candidates[0].operationId).props.onChange;
  const changed={...original};
  if(change==='disabled')changed.disabled=true;
  if(change==='brand')changed.record={...record,document:{...record.document,brandKit:{name:'Changed brand'}}};
  if(change==='revision')changed.record={...record,revision:2};
  if(change==='document')changed.record={...record,id:'another-campaign'};
  if(change==='url')changed.url='/another-campaign/images';
  if(change==='api')changed.api=async()=>assert.fail('Old control cannot use a replacement session');
  render(changed);
  await captured();
  assert.equal(writes.length,0,`${change}: captured ${operation} must not persist an old campaign choice`);
 }
}
