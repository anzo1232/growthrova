import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageBatches.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
let calls=[],release,refreshed=0,planningLost=false;
const plan={operationId:'a'.repeat(32),state:'proposed',creativePlan:{mode:'initial'},concepts:[1,2,3].map(n=>({id:'c'+n,headline:'Direction '+n}))};
const record={revision:1,document:{posts:[{day:1}],creatives:[]}};
plan.sourceContext=writingContext(record.document);
plan.brandKit=null;
const batch={batchId:'b'.repeat(32),expectedRevision:1,day:1,sourceChoice:{route:'create',version:0},state:'partial',slots:plan.concepts.map((concept,index)=>({index,concept,operationId:'d'.repeat(31)+index,funding:{state:'available',reservationMicrousd:40000},state:index===0?'proposed':'planned'}))};
let status={available:false,batches:[],sourceChoice:{route:'create',version:0}};
const api=async(url,options)=>{
 calls.push({url,options});
 if(!options)return {conceptPlans:[plan]};
 if(url.endsWith('/batches')){if(planningLost)throw Error('Planning acknowledgement lost');return batch;}
 await new Promise(resolve=>release=resolve);
 throw Error('Acknowledgement lost');
};
const render=(extra={})=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/campaign/images',record,status,day:1,size:'square_2k',quality:'standard',renderingMode:'complete_advert',disabled:false,onRefresh:async()=>{refreshed++;},...extra}));};
const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
const readText=node=>typeof node==='string'?node:typeof node==='number'?String(node):!node?'':React.Children.toArray(node.props?.children).map(readText).join('');
Object.assign(record.document.posts[0],{objective:'Service enquiries',destinationUrl:'https://example.org/repairs'});
const actionText=()=>readText(render().find(n=>n.props['aria-label']==='Image set action'));
assert.match(actionText(),/Day 1/,'Set selection must identify its target post before generating');
assert.match(actionText(),/Post objective: Service enquiries/);
assert.match(actionText(),/CTA destination: https:\/\/example.org\/repairs/);
assert.match(actionText(),/not verified or connected to an ad button/);
assert.equal(calls.length,0,'Showing the next step must not invoke the provider');
delete record.document.posts[0].destinationUrl;
assert.match(actionText(),/CTA destination: Not supplied/,'Never invent a destination for an incomplete brief');
let nodes=render();
assert.ok(button(nodes,'Load saved concept plans'),'Explicit existing-plan recovery control missing');
await button(nodes,'Load saved concept plans').props.onClick();nodes=render();
for(const n of [1,2,3]){render().find(x=>x.type==='input'&&x.props['aria-label']==='Generate Direction '+n).props.onChange({target:{checked:true}});}
nodes=render();
assert.equal(button(nodes,'Save selected image set').props.disabled,false,'No photos or funded provider needed for planning');
await button(nodes,'Save selected image set').props.onClick();
assert.equal(calls[1].options.data.renderingMode,'complete_advert','Saved set must carry the explicitly chosen design mode');assert.equal(calls[1].options.data.planOperationId,plan.operationId);assert.equal(refreshed,1);
status={...status,batches:[batch]};nodes=render();
assert.match(readText(nodes.find(n=>n.props['aria-label']==='Saved image set action')),/Post objective: Service enquiries/,
 'Saved sets must show their own target action beside the generation controls');
status={...status,batches:[{...batch,expectedRevision:0}]};
assert.equal(render().some(n=>n.props['aria-label']==='Saved image set action'),false,
 'A stale set must not present the current post action as its saved action');
status={...status,batches:[batch]};nodes=render();
assert.equal(button(nodes,'Generate direction 2').props.disabled,true,'Missing funding cannot generate');
status={...status,available:true};nodes=render();
const generate=button(nodes,'Generate direction 2');assert.equal(generate.props.disabled,false);
const pending=generate.props.onClick();await generate.props.onClick();assert.equal(calls.length,3,'Double-click cannot duplicate request');
assert.equal(calls[2].url,'/campaign/images/batches/'+batch.batchId+'/slots/1');
release();await pending;nodes=render();
assert.equal(button(nodes,'Generate direction 3').props.disabled,true,'Unacknowledged request holds further submission');
await button(nodes,'Check set progress').props.onClick();assert.equal(refreshed,2,'Recovery only reads existing status');
status={...status,batches:[{...batch,state:'reconciliation_required',slots:batch.slots.map((s,i)=>i===1?{...s,state:'uncertain'}:s)}]};nodes=render();
assert.equal(button(nodes,'Generate direction 3').props.disabled,true);
assert.equal(button(render({disabled:true}),'Save selected image set').props.disabled,true);
assert.equal(calls.filter(c=>c.url.includes('/slots/')).length,1,'Recovery never submits a provider request');
// A failed status read is not recovery. New submissions stay locked.
status={...status,batches:[batch]};
await button(render(),'Check set progress').props.onClick();
const deniedRefresh=async()=>false;
nodes=render({onRefresh:deniedRefresh});
const second=button(nodes,'Generate direction 2').props.onClick();
await Promise.resolve();release();await second;
await button(render({onRefresh:deniedRefresh}),'Check set progress').props.onClick();
assert.equal(button(render({onRefresh:deniedRefresh}),'Generate direction 3').props.disabled,true,'Failed status read must retain acknowledgement hold');

// Six cards: explicit batch selection is independent from saved favourites.
states=[];refs=[];status={...status,batches:[]};
plan.concepts=[1,2,3,4,5,6].map(n=>({id:'c'+n,headline:'Direction '+n}));
plan.selectedConceptIds=['c6'];
await button(render(),'Load saved concept plans').props.onClick();
assert.equal(button(render(),'Save selected image set').props.disabled,true,'Zero selections cannot submit');
const choose=n=>render().find(x=>x.type==='input'&&x.props['aria-label']==='Generate Direction '+n);
for(const n of [1,3,5]){assert.ok(choose(n));choose(n).props.onChange({target:{checked:true}});}
assert.equal(choose(2).props.disabled,true,'Fourth choice must be disabled');
assert.equal(choose(1).props.disabled,false,'Chosen direction must remain removable');
await button(render(),'Save selected image set').props.onClick();
assert.deepEqual(calls.at(-1).options.data.conceptIds,['c1','c3','c5']);
assert.deepEqual(plan.selectedConceptIds,['c6'],'Batch choice cannot rewrite favourites');

// A status read that finds the exact saved set releases only its planning lock.
planningLost=true;
await button(render(),'Save selected image set').props.onClick();
const unacknowledged=calls.at(-1).options.data;
assert.equal(render().find(n=>n.type==='fieldset').props.disabled,true);
status={...status,batches:[{...unacknowledged,sourceChoice:{route:'create',version:0},day:2,slots:[]}]};
assert.equal(render().find(n=>n.type==='fieldset').props.disabled,true,'A different snapshot is not an acknowledgement');
status={...status,batches:[{...unacknowledged,sourceChoice:{route:'create',version:0},slots:[]}]};
assert.equal(render().find(n=>n.type==='fieldset').props.disabled,false,'Exact GET recovery must allow another deliberate selection without reloading');

// Read-only funding checks are required before submitting an image request.
status={...status,available:true,batches:[{...batch,funding:{state:'budget_held',plannedReservationMicrousd:120000,reservedMicrousd:40000},
  slots:batch.slots.map(s=>({...s,funding:{state:s.state==='planned'?'budget_held':'retained',reservationMicrousd:40000}}))}]};
nodes=render();
assert.equal(button(nodes,'Generate direction 2').props.disabled,true,'A configured provider is not proof the cash cap can fund a request');
const words=nodes.filter(n=>n.type==='p').map(n=>React.Children.toArray(n.props.children).join(' ')).join(' ');
assert.match(words,/\$0\.120000/,'Display conservative planned cash reservation before submission');
assert.match(words,/\$0\.040000/,'Retained reservations include uncertain outcomes, not final billing');
assert.match(words,/not a customer price/i);

status={...status,batches:[batch]};
const unknownFunding={...batch,slots:batch.slots.map(({funding,...slot})=>slot)};
status={...status,batches:[unknownFunding]};
assert.equal(button(render(),'Generate direction 2').props.disabled,true,'Missing funding metadata must require a fresh status check');
const beforeUnchecked=calls.length;
await button(render(),'Generate direction 2').props.onClick();
assert.equal(calls.length,beforeUnchecked,'Stale handlers must enforce the same funding guard as disabled controls');

// The saved model must remain visible when configuration changes. No silent
// substitution, and old sets without a binding must explicitly require replanning.
status={...status,batches:[{...batch,model:'gemini-3-pro-image',
  funding:{state:'settings_changed'},slots:batch.slots.map(s=>({...s,
    funding:{state:s.state==='planned'?'settings_changed':'retained'}}))}]};
nodes=render();
const textOf=node=>typeof node==='string'?node:typeof node==='number'?String(node):!node?'':React.Children.toArray(node.props?.children).map(textOf).join(' ');
assert.match(nodes.map(textOf).join(' '),/Saved image model: gemini-3-pro-image/,'Show exact saved model even when unavailable');
assert.equal(button(nodes,'Generate direction 2').props.disabled,true);
status={...status,batches:[{...batch,funding:{state:'settings_changed'},slots:batch.slots.map(s=>({...s,funding:{state:'settings_changed'}}))}]};
assert.match(render().map(textOf).join(' '),/model was not recorded/i,'Legacy sets must not imply they adopted the current provider');

// A blocked direction is recoverable copy work, not a model configuration change.
status={...status,batches:[{...batch,funding:{state:'direction_held'},slots:batch.slots.map(s=>({...s,
  funding:{state:s.state==='planned'?'direction_held':'retained'}}))}]};
nodes=render();
assert.match(nodes.map(textOf).join(' '),/Remove internal labels or numeric layout coordinates/);
assert.match(nodes.map(textOf).join(' '),/originals.*preserved/i);
assert.equal(button(nodes,'Generate direction 2').props.disabled,true);
assert.doesNotMatch(nodes.map(textOf).join(' '),/saved model or request settings cannot be used/);

// Refresh during a still-running provider request is progress, not a timeout.
states=[];refs=[];
status={available:true,sourceChoice:{route:'create',version:0},batches:[{...batch,state:'generating',
 funding:{state:'pending',reservedMicrousd:40000,plannedReservationMicrousd:80000},
 slots:batch.slots.map((s,i)=>({...s,state:i===0?'pending':'planned',funding:{state:i===0?'retained':'pending',reservationMicrousd:40000}}))}]};
nodes=render();
const pendingWords=nodes.filter(n=>n.type==='p').map(n=>React.Children.toArray(n.props.children).join(' ')).join(' ');
assert.match(pendingWords,/still running|still pending/i,'Show progress instead of asking for reconciliation during the active request');
assert.equal(button(nodes,'Generate direction 2').props.disabled,true);
const callsBeforePendingCheck=calls.length;
await button(nodes,'Check set progress').props.onClick();
assert.equal(calls.length,callsBeforePendingCheck,'Checking a pending job cannot invoke the provider');
assert.equal(button(render(),'Generate direction 3').props.disabled,true);
assert.doesNotMatch(pendingWords,/request is uncertain|operator reconciliation is required/i,
 'A normal active request must not also show an uncertainty/reconciliation warning');

// Read-only progress stays available while the original POST is outstanding.
// A successful GET cannot unlock another billable operation before that POST
// settles, and repeated progress clicks cannot create overlapping status reads.
states=[];refs=[];
status={available:true,sourceChoice:{route:'create',version:0},batches:[batch]};
let finishRequest,finishProgress,progressReads=0,providerPosts=0;
const inFlightProps={api:async()=>{providerPosts++;await new Promise(resolve=>finishRequest=resolve);throw Error('Response lost');},
 onRefresh:async()=>{progressReads++;await new Promise(resolve=>finishProgress=resolve);}};
const activeRequest=button(render(inFlightProps),'Generate direction 2').props.onClick();
nodes=render(inFlightProps);
assert.equal(button(nodes,'Check set progress').props.disabled,false,'Read-only progress must work during the provider wait');
assert.match(nodes.map(textOf).join(' '),/request in progress/i);
assert.doesNotMatch(nodes.map(textOf).join(' '),/acknowledgement missing/i,'No missing-acknowledgement alarm during a normal request');
const progress=button(nodes,'Check set progress').props.onClick();
await button(nodes,'Check set progress').props.onClick();
assert.equal(progressReads,1,'Double-click must not overlap status reads');
assert.equal(button(render(inFlightProps),'Check set progress').props.disabled,true);
finishProgress();await progress;
assert.equal(button(render(inFlightProps),'Generate direction 3').props.disabled,true,'GET cannot release the active submission lock');
await button(render(inFlightProps),'Generate direction 3').props.onClick();
assert.equal(providerPosts,1);
finishRequest();await activeRequest;
assert.match(render(inFlightProps).map(textOf).join(' '),/acknowledgement missing/i);
assert.equal(button(render(inFlightProps),'Generate direction 3').props.disabled,true,'Lost acknowledgement still holds submissions');

// Completion during a manual status read needs a fresh read AFTER it, because
// the earlier GET may contain the pending snapshot. Do not overlap parent load.
states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[batch]};
let completePost,completeRead,readCount=0;
const finishingProps={api:async()=>new Promise(resolve=>completePost=resolve),onRefresh:async()=>{
 readCount++;if(readCount===1)await new Promise(resolve=>completeRead=resolve);return true;
}};
const completing=button(render(finishingProps),'Generate direction 2').props.onClick();
const reading=button(render(finishingProps),'Check set progress').props.onClick();
completePost();await new Promise(setImmediate);
assert.equal(readCount,1,'Post completion must wait for an earlier status read before loading its final outcome');
completeRead();await reading;await completing;
assert.equal(readCount,2,'Completion needs a fresh status read rather than accepting an older pending snapshot');
assert.doesNotMatch(render(finishingProps).map(textOf).join(' '),/acknowledgement missing/i);

// A partial set must take the owner directly to its exact retained pixels,
// including a held sibling. Candidate ordering is unrelated to slot ordering.
states=[];refs=[];
const retained=slot=>({operationId:slot.operationId,state:'proposed',origin:'generated',sha256:'f'.repeat(64),issues:[]});
const completed=retained(batch.slots[0]);
const held={...retained(batch.slots[1]),state:'held',issues:['Technical image review held: low_detail. Original retained for inspection.']};
status={available:false,sourceChoice:{route:'create',version:0},candidates:[held,completed],
 batches:[{...batch,slots:batch.slots.map((s,i)=>({...s,state:i===0?'proposed':i===1?'held':'uncertain'}))}]};
const inspected=[];
const reviewProps={onInspect:async candidate=>inspected.push(candidate)};
nodes=render(reviewProps);
assert.ok(button(nodes,'Inspect direction 1'),'Partial set needs direct inspection of its completed direction');
await button(nodes,'Inspect direction 1').props.onClick();
await button(render(reviewProps),'Inspect direction 2').props.onClick();
assert.deepEqual(inspected,[completed,held],'Inspection must use each slot’s exact retained candidate, never array position');
assert.match(nodes.map(textOf).join(' '),/Technical image review held: low_detail/,'Explain a held direction beside its own result');
assert.equal(button(nodes,'Inspect direction 3'),undefined,'Unknown pixels are never inspectable');
assert.equal(button(render({...reviewProps,disabled:true}),'Inspect direction 1').props.disabled,true);
const beforeLocked=inspected.length;
await button(render({...reviewProps,disabled:true}),'Inspect direction 1').props.onClick();
assert.equal(inspected.length,beforeLocked,'Handler must enforce mutation locks too');
status={...status,candidates:[held]};
assert.equal(button(render(reviewProps),'Inspect direction 1'),undefined,'Missing matching metadata must not open another candidate');
assert.match(render(reviewProps).map(textOf).join(' '),/Check set progress to load this retained background/i);
assert.equal(button(render(),'Inspect direction 2'),undefined,'No dead inspection button without the connected inspector');

// Reopening a changed saved brand must not offer an earlier plan for a new set.
// The old cards/selection stay in memory until the owner deliberately reloads.
states=[];refs=[];planningLost=false;status={available:false,batches:[],sourceChoice:{route:'create',version:0}};
await button(render(),'Load saved concept plans').props.onClick();
choose(1).props.onChange({target:{checked:true}});
const oldSave=button(render(),'Save selected image set').props.onClick;
const changedRecord={...record,revision:2,document:{...record.document,brandKit:{name:'Changed reviewed brand'}}};
nodes=render({record:changedRecord});
assert.equal(button(nodes,'Save selected image set').props.disabled,true,'Changed brand must invalidate a loaded plan before submission');
assert.match(nodes.map(textOf).join(' '),/business brief or brand changed.*load saved concept plans/i,'Explain how to recover without losing saved sets');
assert.equal(nodes.filter(n=>n.type==='input'&&n.props.type==='checkbox').length,0,'Outdated directions cannot be offered as current choices');
const beforeStaleSave=calls.length;
await oldSave();
assert.equal(calls.length,beforeStaleSave,'A captured save handler cannot submit the previous brand selection');

// A delayed read from the old campaign cannot replace current plan choices.
states=[];refs=[];
let finishOldPlans;
const lateApi=async()=>new Promise(resolve=>finishOldPlans=resolve);
const oldLoad=button(render({api:lateApi}),'Load saved concept plans').props.onClick();
render({record:changedRecord});
finishOldPlans({conceptPlans:[plan]});await oldLoad;
assert.equal(render({record:changedRecord}).filter(n=>n.type==='input'&&n.props.type==='checkbox').length,0,'Ignore plans arriving after campaign scope changed');
assert.equal(button(render({record:changedRecord}),'Save selected image set').props.disabled,true);

// Explicit reload can recover with a new plan, while restoring the exact prior
// brand can still recover the old selection without silently discarding it.
states=[];refs=[];
await button(render(),'Load saved concept plans').props.onClick();
choose(3).props.onChange({target:{checked:true}});
render({record:changedRecord});
assert.equal(choose(3).props.checked,true,'Restoring the previous context preserves its chosen direction');
const refreshedPlan={...plan,operationId:'e'.repeat(32),brandKit:changedRecord.document.brandKit};
const freshProps={record:changedRecord,api:async(path,options)=>{
  calls.push({url:path,options});return options?batch:{conceptPlans:[refreshedPlan]};
}};
await button(render(freshProps),'Load saved concept plans').props.onClick();
assert.equal(button(render(freshProps),'Save selected image set').props.disabled,true,'A fresh plan requires explicit choices');
render(freshProps).find(n=>n.type==='input'&&n.props['aria-label']==='Generate Direction 2').props.onChange({target:{checked:true}});
await button(render(freshProps),'Save selected image set').props.onClick();
assert.equal(calls.at(-1).options.data.planOperationId,refreshedPlan.operationId);
assert.equal(calls.at(-1).options.data.expectedRevision,2);
assert.deepEqual(calls.at(-1).options.data.conceptIds,['c2']);

// One explicit set action requests only its remaining directions, in order.
// Stable saved slot IDs, rather than a new batch, survive partial completion.
const remainingLabel='Generate 2 remaining directions';
const fundedBatch={...batch,funding:{state:'available',plannedReservationMicrousd:80000,reservedMicrousd:40000}};
states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[fundedBatch]};
let setPosts=[],setReads=0,finishFirst;
const setProps={api:async(path,options)=>{
 setPosts.push({path,data:options.data});
 if(setPosts.length===1)await new Promise(resolve=>finishFirst=resolve);
 return {operationId:fundedBatch.slots[setPosts.length].operationId,state:'proposed'};
},onRefresh:async()=>{setReads++;return true;}};
const runSet=button(render(setProps),remainingLabel);
assert.ok(runSet,'An explicitly selected set needs a single remaining-directions action');
assert.equal(runSet.props.disabled,false);
const completingSet=runSet.props.onClick();
await runSet.props.onClick();
assert.equal(setPosts.length,1,'Double-click cannot duplicate or overlap image requests');
assert.equal(button(render(setProps),'Generate direction 3').props.disabled,true);
finishFirst();await completingSet;
assert.deepEqual(setPosts.map(item=>item.path),[1,2].map(n=>'/campaign/images/batches/'+batch.batchId+'/slots/'+n));
assert.ok(setPosts.every(item=>item.data.expectedRevision===1));
assert.equal(setReads,2,'Read each durable outcome before continuing');
assert.equal(fundedBatch.slots[0].state,'proposed','Completed sibling stays untouched');

for(const outcome of ['held','uncertain','pending','wrong_operation','lost_ack','failed_read','changed_context','changed_source','dirty_campaign']){
 states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[fundedBatch]};
 let posts=0;
 const props={api:async()=>{
  posts++;
  if(outcome==='lost_ack')throw Error('Response lost');
  if(outcome==='changed_context')render({...props,record:changedRecord});
  if(outcome==='dirty_campaign')render({...props,disabled:true,campaignDisabled:true});
  if(outcome==='changed_source'){status={...status,sourceChoice:{route:'mix',version:1}};render(props);}
  return {operationId:outcome==='wrong_operation'?'x'.repeat(32):fundedBatch.slots[1].operationId,
   state:['held','uncertain','pending'].includes(outcome)?outcome:'proposed'};
 },onRefresh:async()=>outcome!=='failed_read'};
 await button(render(props),remainingLabel).props.onClick();
 assert.equal(posts,1,outcome+' must stop the remaining set without retrying or touching sibling slots');
 assert.ok(render(props).some(n=>n.props?.role==='alert'),outcome+' needs an actionable held/recovery message');
 if(['held','uncertain','pending'].includes(outcome))assert.doesNotMatch(render(props).map(textOf).join(' '),/acknowledgement missing/i,'A known '+outcome+' result is acknowledged, not a lost response');
}

// Only a wholly funded, current set may submit several requests. Partial cash
// availability still permits the existing explicit individual action.
for(const state of ['partial_budget','budget_held','unavailable','settings_changed']){
 states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[{...fundedBatch,funding:{state}}]};
 let posts=0;const props={api:async()=>{posts++;}};
 const heldAction=button(render(props),remainingLabel);
 assert.equal(heldAction.props.disabled,true,state);
 await heldAction.props.onClick();assert.equal(posts,0,state+' must be enforced in the handler');
}

// A fresh three-direction no-photo set completes sequentially. No planning,
// original-media upload, repeated request or extra provider route is involved.
states=[];refs=[];
const freshBatch={...fundedBatch,state:'planned',funding:{state:'available',plannedReservationMicrousd:120000,reservedMicrousd:0},
 slots:fundedBatch.slots.map(slot=>({...slot,state:'planned'}))};
status={available:true,sourceChoice:{route:'create',version:0},batches:[freshBatch]};
const freshPaths=[];
const freshSetProps={api:async(path)=>{
 freshPaths.push(path);const slot=freshBatch.slots[Number(path.split('/').at(-1))];
 return {operationId:slot.operationId,state:'proposed'};
},onRefresh:async()=>true};
await button(render(freshSetProps),'Generate 3 remaining directions').props.onClick();
assert.deepEqual(freshPaths,[0,1,2].map(n=>'/campaign/images/batches/'+batch.batchId+'/slots/'+n));
assert.doesNotMatch(render(freshSetProps).map(textOf).join(' '),/acknowledgement missing/i);
assert.match(render(freshSetProps).map(textOf).join(' '),/3\s+proposed standard image credits.*\$0\.120000/);

// Leaving the workspace cannot start another paid request in the background.
// The outstanding operation is retained server-side, not cancelled or retried.
states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[fundedBatch]};
let unmount=()=>{},finishBeforeLeaving,leftPosts=0;
hooks.useEffect=effect=>{unmount=effect()||(()=>{});};
const leavingProps={api:async()=>{
 leftPosts++;if(leftPosts===1)await new Promise(resolve=>finishBeforeLeaving=resolve);
 return {operationId:fundedBatch.slots[leftPosts].operationId,state:'proposed'};
},onRefresh:async()=>true};
const leaving=button(render(leavingProps),remainingLabel).props.onClick();
unmount();finishBeforeLeaving();await leaving;
assert.equal(leftPosts,1,'Unmounting must stop the next direction; an already submitted request is not repeated');

// A single-direction click needs the same current-context protection as a
// remaining-set run. Unsaved work is invisible to the server's revision check.
for(const change of ['dirty_campaign','record','source','funding','unmount']){
 states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[fundedBatch]};
 let posts=0,cleanup=()=>{};
 hooks.useEffect=effect=>{cleanup=effect()||(()=>{});};
 const props={api:async()=>{posts++;return {operationId:fundedBatch.slots[1].operationId,state:'proposed'};},onRefresh:async()=>true};
 const oldAction=button(render(props),'Generate direction 2').props.onClick;
 if(change==='dirty_campaign')render({...props,disabled:true,campaignDisabled:true});
 if(change==='record')render({...props,record:changedRecord});
 if(change==='source'){status={...status,sourceChoice:{route:'website',version:1}};render(props);}
 if(change==='funding'){
  status={...status,batches:[{...fundedBatch,slots:fundedBatch.slots.map(s=>({...s,funding:{state:'budget_held'}}))}]};render(props);
 }
 if(change==='unmount')cleanup();
 await oldAction();
 assert.equal(posts,0,change+': stale single-direction handler must not dispatch image inference');
}

// The same saved direction remains recoverable after returning to current,
// saved inputs: no retry, replacement set or discarded sibling is required.
states=[];refs=[];status={available:true,sourceChoice:{route:'create',version:0},batches:[fundedBatch]};
let recoveredPosts=0;
const recoveredProps={api:async()=>{recoveredPosts++;return {operationId:fundedBatch.slots[1].operationId,state:'proposed'};},onRefresh:async()=>true};
render({...recoveredProps,disabled:true,campaignDisabled:true});
await button(render(recoveredProps),'Generate direction 2').props.onClick();
assert.equal(recoveredPosts,1,'Fresh current action must still request its exact saved direction once');
assert.equal(fundedBatch.slots[0].state,'proposed','Recovery preserves successful siblings');
