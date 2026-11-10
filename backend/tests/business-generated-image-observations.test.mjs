import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageObservations.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let cursor=0,states=[],refs=[],refIndex=0,effects=[];
const hooks={...React,useEffect:callback=>effects.push(callback),useState:initial=>{const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
function flatten(node){return !node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
let calls=[],fail=true,resolve;
const save=async data=>{calls.push(data);await new Promise(r=>resolve=r);if(fail)throw Error('Lost acknowledgement');};
const candidate={operationId:'a'.repeat(32),sha256:'b'.repeat(64),reviewVersion:0};
const render=(extra={})=>{cursor=0;refIndex=0;return flatten(module.exports.default({candidate,revision:4,onSave:save,...extra}));};
const get=(nodes,type,label)=>nodes.find(n=>n.type===type&&(n.props['aria-label']===label||n.props.children===label));
let nodes=render();
assert.ok(get(nodes,'button','Save background observation').props.disabled,'A note/check is required');
get(nodes,'select','Visual quality observation').props.onChange({target:{value:'needs_changes'}});
get(nodes,'textarea','Background observation notes').props.onChange({target:{value:'The synthetic wheel shape is distorted; keep the original for comparison.'}});
nodes=render();
const submit=get(nodes,'button','Save background observation');
const first=submit.props.onClick();
await submit.props.onClick();
assert.equal(calls.length,1,'Double click cannot append two reviews');
assert.equal(calls[0].sha256,candidate.sha256);
assert.equal(calls[0].expectedRevision,4);
assert.equal(calls[0].expectedReviewVersion,0);
assert.equal(calls[0].checks.visual,'needs_changes');
assert.equal(calls[0].checks.factual,'not_reviewed');
resolve();await first;
nodes=render();
const retry=get(nodes,'button','Retry saving same observation');assert.ok(retry);
assert.ok(get(nodes,'textarea','Background observation notes').props.disabled,'Unacknowledged payload is preserved');
fail=false;const second=retry.props.onClick();resolve();await second;
assert.deepEqual(calls[1],calls[0],'Retry reuses exact identity/payload without a provider request');
nodes=render({candidate:{...candidate,compositionHeld:true,observations:[{reviewId:'c'.repeat(32),version:1,current:false,outcome:'needs_changes',note:'Original rejected; preserve it.',checks:{visual:'needs_changes'}}]}});
const text=JSON.stringify(nodes.map(n=>n.props.children));
assert.match(text,/Original rejected; preserve it/);
assert.match(text,/Context changed/);
assert.match(text,/independent approval/i);
// A GET that recovers the exact acknowledged review must unlock the form and
// clear the transient lost-acknowledgement error, without resubmitting anything.
fail=true;nodes=render();
get(nodes,'select','Visual quality observation').props.onChange({target:{value:'checked'}});
get(nodes,'textarea','Background observation notes').props.onChange({target:{value:'A second background inspection after checking the original.'}});
nodes=render();const lost=get(nodes,'button','Save background observation').props.onClick();resolve();await lost;
const acknowledged={...candidate,reviewVersion:2,observations:[{reviewId:calls.at(-1).reviewId,version:2,current:true,outcome:'observed',checks:calls.at(-1).checks,note:calls.at(-1).note}]};
render({candidate:acknowledged});for(const effect of effects.splice(0))effect();
nodes=render({candidate:acknowledged});
assert.equal(nodes.some(n=>n.props.role==='alert'),false,'Recovered saved observation clears lost-acknowledgement error');
assert.equal(get(nodes,'textarea','Background observation notes').props.disabled,false,'History recovery unlocks new observations');
assert.equal(calls.length,3,'GET acknowledgement recovery makes no extra POST');
// A sibling/caption save must not remount the inspected-background form and
// erase an unfinished owner note. React uses this actual child key as identity.
const parentBuild=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let parentIndex=0;
const parentHooks={...React,useEffect:()=>{},useRef:value=>({current:value}),useState:initial=>{
  const i=parentIndex++;return[i===7?{url:'blob:synthetic',candidate}:typeof initial==='function'?initial():initial,()=>{}];}};
const parentModule={exports:{}};
new Function('require','module','exports',parentBuild.outputFiles[0].text)(name=>name==='react'?parentHooks:require(name),parentModule,parentModule.exports);
function reviewIdentity(revision){parentIndex=0;const tree=parentModule.exports.default({api:async()=>{},url:'/images',record:{revision,document:{posts:[{day:1}],creatives:[]}}});return flatten(tree).find(n=>typeof n.type==='function'&&n.props.candidate===candidate).key;}
assert.equal(reviewIdentity(4),reviewIdentity(5),'Saving another document revision preserves the in-progress observation form');

// Word accuracy is separate from readable type; legacy checks cannot imply it.
states=[];refs=[];effects=[];calls=[];fail=false;
nodes=render({mode:'advert'});
const wording=get(nodes,'select','Requested wording accuracy observation');
assert.ok(wording,'Complete advert review must separately expose requested-word accuracy');
wording.props.onChange({target:{value:'needs_changes'}});
get(nodes,'select','Text legibility observation').props.onChange({target:{value:'checked'}});
get(nodes,'textarea','Advert observation notes').props.onChange({target:{value:'Readable headline omits one requested word; preserve this original.'}});
nodes=render({mode:'advert'});
const wordSave=get(nodes,'button','Save advert observation').props.onClick();resolve();await wordSave;
assert.equal(calls[0].checks.wording,'needs_changes');
assert.equal(calls[0].checks.legibility,'checked');
nodes=render({mode:'advert',candidate:{...candidate,observations:[{reviewId:'e'.repeat(32),version:1,current:true,
 outcome:'observed',checks:{legibility:'checked'},note:'Legacy observation with no word accuracy check.'}]}});
const legacyLabels=nodes.filter(n=>n.type==='dt').map(n=>n.props.children);
const legacyValues=nodes.filter(n=>n.type==='dd').map(n=>n.props.children);
assert.equal(legacyValues[legacyLabels.indexOf('Requested wording accuracy')],'Not reviewed');
nodes=render({mode:'background'});
assert.equal(get(nodes,'select','Requested wording accuracy observation'),undefined);
states=[];refs=[];effects=[];calls=[];
nodes=render({mode:'artwork'});
get(nodes,'select','Requested wording accuracy observation').props.onChange({target:{value:'needs_changes'}});
get(nodes,'select','Text legibility observation').props.onChange({target:{value:'checked'}});
get(nodes,'textarea','Artwork observation notes').props.onChange({target:{value:'Readable exported design omits supporting words; preserve exact pixels.'}});
nodes=render({mode:'artwork'});
const finalSave=get(nodes,'button','Save artwork observation').props.onClick();resolve();await finalSave;
assert.equal(calls[0].checks.wording,'needs_changes');
assert.equal(calls[0].checks.legibility,'checked');
assert.equal(calls[0].sha256,candidate.sha256,'Final wording observation binds exact artwork bytes');
nodes=render({mode:'artwork',candidate:{...candidate,observations:[{reviewId:'f'.repeat(32),version:1,current:true,
 outcome:'observed',checks:{legibility:'checked'},note:'Legacy final artwork inspected for readability only.'}]}});
const finalLabels=nodes.filter(n=>n.type==='dt').map(n=>n.props.children);
const finalValues=nodes.filter(n=>n.type==='dd').map(n=>n.props.children);
assert.equal(finalValues[finalLabels.indexOf('Requested wording accuracy')],'Not reviewed',
 'Old artwork observations must not imply word verification');
