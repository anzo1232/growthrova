import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'||node.props?.hidden?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
const hash=createHash('sha256').update(png).digest('hex');
const parent={operationId:'a'.repeat(32),origin:'generated',day:1,revision:1,state:'held',sha256:hash,mimeType:'image/png',issues:[],renderingMode:'complete_advert'};
const alternative={...parent,operationId:'b'.repeat(32),state:'proposed',parentOperationId:parent.operationId,renderingMode:'complete_advert'};
let record,calls,wrongHash,wait,readFailure;
const api=async(url,options)=>{
  calls.push({url,options});
  if(url==='/images/selection'){
    assert.equal(options.method,'PUT');
    assert.equal(options.data.expectedRevision,record.revision);
    assert.equal(options.data.expectedSelectionVersion,states[0].selection.version);
    return {selectedIds:options.data.selectedIds,version:options.data.expectedSelectionVersion+1};
  }
  assert.deepEqual(options,{responseType:'blob'},'Comparison reads retained originals without generation');
  assert.ok([parent,alternative].some(c=>url==='/images/'+c.operationId+'/original'));
  if(url.includes(parent.operationId)){
    if(wait)await wait;
    if(readFailure)throw Error('Synthetic original read interrupted');
    if(wrongHash)return new Blob(['mismatched bytes'],{type:'image/png'});
  }
  return new Blob([png],{type:'image/png'});
};
const render=()=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/images',record}));};
const button=(nodes,text)=>nodes.find(n=>n.type==='button'&&n.props.children===text);
const panel=nodes=>nodes.find(n=>n.props['aria-label']==='Compare saved image designs');
async function open(){
  states=[];refs=[];calls=[];wrongHash=false;wait=null;readFailure=false;
  record={id:'synthetic-qa',revision:1,document:{posts:[{day:1}],creatives:[]}};
  states[0]={candidates:[alternative,parent],selection:{selectedIds:[parent.operationId],version:1}};
  await button(render(),'Inspect complete advert').props.onClick();
  const compare=button(render(),'Compare with original');
  assert.ok(compare,'A selected alternative needs an explicit original-pixel comparison');
  return compare;
}
let compare=await open();
await compare.props.onClick();
let nodes=render();
assert.ok(panel(nodes),'Both retained designs must be visible together');
const figures=flatten(panel(nodes)).filter(n=>n.type==='figure');
assert.equal(figures.length,2);
assert.match(JSON.stringify(figures[0].props.children),/Original design/);
assert.match(JSON.stringify(figures[1].props.children),/Alternative design/);
assert.equal(flatten(panel(nodes)).filter(n=>n.type==='img').length,2);
assert.deepEqual(states[0].selection.selectedIds,[parent.operationId],'Comparison must not choose or replace an image');
assert.equal(calls.length,2,'Reuse the already-inspected alternative; only read its parent');
assert.equal(calls[1].url,'/images/'+parent.operationId+'/original','Compare the exact lineage parent, never a sibling');
button(nodes,'Close image comparison').props.onClick();
assert.equal(panel(render()),undefined);
// A held original stays comparable. Interrupted or mismatched reads hold only
// comparison; the inspected alternative remains downloadable and retry works.
for(const failure of ['transport','hash']){
  compare=await open();readFailure=failure==='transport';wrongHash=failure==='hash';
  await compare.props.onClick();nodes=render();
  assert.equal(panel(nodes),undefined);
  assert.ok(nodes.some(n=>n.props.role==='alert'));
  assert.ok(nodes.some(n=>n.type==='a'&&n.props.children==='Download complete advert draft'));
  readFailure=false;wrongHash=false;
  await button(nodes,'Compare with original').props.onClick();
  assert.ok(panel(render()),'Retry uses the same originals without regenerating');
  assert.equal(calls.length,3);
}
// Context changes or a newly inspected design invalidate old callbacks and
// late reads. No stale comparison is allowed back into the new workspace.
compare=await open();let release;wait=new Promise(resolve=>release=resolve);
const pending=compare.props.onClick();
await compare.props.onClick();assert.equal(calls.length,2,'Double click cannot duplicate reads');
record={...record,revision:2};render();release();await pending;wait=null;
assert.equal(panel(render()),undefined);
const reads=calls.length;await compare.props.onClick();
assert.equal(calls.length,reads,'Old callbacks cannot reopen comparison after context changes');
compare=await open();await compare.props.onClick();
await render().filter(n=>n.type==='button'&&n.props.children==='Inspect complete advert')[1].props.onClick();
assert.equal(panel(render()),undefined,'Inspecting another image clears the previous pair');
// Missing parent bytes never substitutes a sibling or the latest generation.
await open();states[0]={...states[0],candidates:[alternative]};
assert.equal(button(render(),'Compare with original'),undefined);
assert.ok(render().some(n=>n.type==='p'&&String(n.props.children).includes('original is not in the loaded history')));

// Choose either or both designs while comparing, using only the saved selection
// contract. A held original remains held; choosing it is not approval.
compare=await open();await compare.props.onClick();
const keep=(nodes,label)=>flatten(panel(nodes)).find(n=>n.type==='input'&&n.props['aria-label']===label);
nodes=render();
assert.ok(keep(nodes,'Keep original design'),'Comparison needs an accessible choice beside each exact image');
assert.equal(keep(nodes,'Keep original design').props.checked,true);
assert.equal(keep(nodes,'Keep alternative design').props.checked,false);
await keep(nodes,'Keep alternative design').props.onChange();
nodes=render();
assert.deepEqual(states[0].selection.selectedIds,[parent.operationId,alternative.operationId]);
assert.equal(keep(nodes,'Keep original design').props.checked,true);
assert.equal(keep(nodes,'Keep alternative design').props.checked,true);
await keep(nodes,'Keep original design').props.onChange();
nodes=render();
assert.deepEqual(states[0].selection.selectedIds,[alternative.operationId]);
assert.equal(parent.state,'held');
assert.equal(flatten(panel(nodes)).filter(n=>n.type==='img').length,2,'Unkeeping must not remove either comparison image');
assert.ok(calls.every(c=>!c.options.method||c.url==='/images/selection'),'No generation or review write');
const staleKeep=keep(nodes,'Keep original design');
record={...record,revision:2};render();
const beforeStale=calls.length;
await staleKeep.props.onChange();
assert.equal(calls.length,beforeStale,'A stale comparison cannot change the next campaign selection');
// Existing maximum applies here too: unkeep remains available at capacity.
compare=await open();await compare.props.onClick();
states[0]={...states[0],selection:{selectedIds:[parent.operationId,...Array.from({length:19},(_,i)=>String(i).padStart(32,'0'))],version:1}};
nodes=render();
assert.equal(keep(nodes,'Keep alternative design').props.disabled,true);
assert.equal(keep(nodes,'Keep original design').props.disabled,false);
