import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';
import {applyConceptDirection} from '../src/lib/growthrovaCreativePlans.mjs';
const doc=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
const target=doc.creatives.find(c=>c.format==='image_ad');
const concept={id:'a'.repeat(32)+'-1',parentConceptId:'',buyerMotivation:'Discuss a leaking pipe',headline:'A leak needs attention',
 callToAction:'Enquire about plumbing',visualDirection:'Illustrative pipe and a single droplet, quiet left side for exact editable words.',evidence:[{id:'brief-offer',quote:'Plumbing enquiries for local homes.'}]};
const plan={state:'proposed',creativePlan:{mode:'initial'},concepts:[concept],sourceContext:writingContext(doc),brandKit:doc.brandKit??null};
const before=structuredClone(doc);
const next=applyConceptDirection(doc,plan,concept.id,target.id,{headline:'Plumbing for your home',callToAction:concept.callToAction,visualDirection:concept.visualDirection});
assert.deepEqual(doc,before,'Never mutate original owner work');
assert.deepEqual(next.posts,doc.posts);
assert.deepEqual(next.creatives.filter(c=>c.id!==target.id),doc.creatives.filter(c=>c.id!==target.id));
assert.equal(next.creatives.find(c=>c.id===target.id).brief,concept.visualDirection);
assert.equal(next.creatives.find(c=>c.id===target.id).copyDraft,target.copyDraft,'Caption stays separate from graphic headline');
assert.equal(next.creatives.find(c=>c.id===target.id).title,'Plumbing for your home');
assert.throws(()=>applyConceptDirection(doc,{...plan,state:'held'},concept.id,target.id,concept),/proposed/i);
assert.throws(()=>applyConceptDirection({...doc,goal:'Changed'},plan,concept.id,target.id,concept),/context/i);
const require=createRequire(import.meta.url);
const bundle=await build({entryPoints:['src/GrowthrovaCreativePlans.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0;
const hooks={...React,useState:initial=>[index++===0?{available:false,message:'Writer unavailable; saved concepts retained.',conceptPlans:[]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const module={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const tree=module.exports.default({api:()=>{},url:'/writing',record:{revision:1,document:doc},onApply:()=>{}});
function flatten(node){return !node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
const nodes=flatten(tree);
const propose=nodes.find(n=>n.type==='button'&&n.props.children==='Propose six visual concepts');
assert.ok(propose);assert.equal(propose.props.disabled,true);
assert.ok(nodes.some(n=>n.type==='button'&&n.props.children==='Check saved concept plans'));

// Two clicks in one render must share the in-flight guard, before React rerenders.
let slot=0,calls=0,resolveRequest,sentRequest,sentUrl;
const activeHooks={...React,useState:initial=>[slot++===0?{available:true,conceptPlans:[]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const activeModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?activeHooks:require(name),activeModule,activeModule.exports);
const activeTree=activeModule.exports.default({api:(url,options)=>{sentUrl=url;sentRequest=options.data;calls++;return new Promise(resolve=>{resolveRequest=resolve;});},url:'/writing',record:{revision:1,document:doc},onApply:()=>{}});
const action=flatten(activeTree).find(n=>n.type==='button'&&n.props.children==='Propose six visual concepts');
action.props.onClick();action.props.onClick();
assert.equal(sentRequest.creativePlan.conceptCount,6);
assert.equal(sentUrl,'/writing/concept-plans','Initial planning must return a durable background receipt instead of waiting for complete output');
assert.equal(calls,1,'Repeated clicks before rerender must not submit a second request');
resolveRequest({operationId:'a'.repeat(32),concepts:[]});

// More ideas needs the same durable acknowledgement as an initial six-card set.
let ideasSlot=0,ideasUrl;
const ideasPlan={...plan,operationId:'a'.repeat(32),concepts:Array(6).fill(concept),selectedConceptIds:[],selectionRevision:0,issues:[],material:{evidence:[]}};
const ideasHooks={...React,useState:initial=>[ideasSlot++===0?{available:true,conceptPlans:[ideasPlan]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const ideasModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?ideasHooks:require(name),ideasModule,ideasModule.exports);
const ideasTree=ideasModule.exports.default({api:(url,options)=>{ideasUrl=url;assert.equal(options.data.creativePlan.parentOperationId,ideasPlan.operationId);return Promise.resolve({...ideasPlan,state:'pending'});},url:'/writing',record:{revision:1,document:doc},onApply:()=>assert.fail('Planning preserves campaign content')});
await flatten(ideasTree).find(n=>n.type==='button'&&n.props.children==='More ideas').props.onClick();
assert.equal(ideasUrl,'/writing/concept-plans','More ideas must not wait for a synchronous six-concept response');

// Reopen/check a slow response, never another inference request. Pending plans
// cannot be applied or replaced while the provider is still working.
let pendingSlot=0;const pendingCalls=[],pendingUpdates=[];
const slowPlan={...plan,operationId:'e'.repeat(32),state:'pending',backgroundPlan:true,
  concepts:[],issues:['Concept planning in progress.'],selectedConceptIds:[]};
const pendingHooks={...React,useState:initial=>[pendingSlot++===0?{available:true,conceptPlans:[slowPlan]}:typeof initial==='function'?initial():initial,value=>pendingUpdates.push(value)],useEffect:()=>{},useRef:value=>({current:value})};
const pendingModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?pendingHooks:require(name),pendingModule,pendingModule.exports);
const pendingNodes=flatten(pendingModule.exports.default({api:async(url,options)=>{pendingCalls.push([url,options]);return options?{...slowPlan,state:'held'}:{available:true,conceptPlans:[slowPlan]};},url:'/writing',record:{revision:1,document:doc},onApply:()=>assert.fail('Pending output cannot apply')}));
assert.equal(pendingNodes.find(n=>n.type==='button'&&n.props.children==='Propose six visual concepts').props.disabled,true);
await pendingNodes.find(n=>n.type==='button'&&n.props.children==='Check saved concept plans').props.onClick();
assert.deepEqual(pendingCalls,[['/writing',undefined],['/writing/'+slowPlan.operationId+'/refresh',{method:'POST',data:{}}]]);
assert.ok(pendingUpdates.some(value=>value?.conceptPlans?.[0]?.state==='held'),'Checked state must replace pending receipt without changing its operation ID');

// Editorial advice is visible, explained and separate from a favourite.
let adviceIndex=0;
const advised={...plan,operationId:'a'.repeat(32),material:{evidence:[]},issues:[],selectedConceptIds:[],selectionRevision:0,
 recommendations:[{conceptId:concept.id,reason:'Connects the reviewed plumbing offer to a recognisable household need.'}]};
const adviceHooks={...React,useState:initial=>[adviceIndex++===0?{available:false,conceptPlans:[advised]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const adviceModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?adviceHooks:require(name),adviceModule,adviceModule.exports);
const adviceNodes=flatten(adviceModule.exports.default({api:()=>{},url:'/writing',record:{revision:1,document:doc},onApply:()=>{}}));
assert.ok(adviceNodes.some(n=>n.props?.['aria-label']==='Editorial recommendation'&&JSON.stringify(n.props.children).includes(advised.recommendations[0].reason)), 'Specific editorial reason must be visible');
assert.equal(adviceNodes.find(n=>n.type==='input'&&n.props.type==='checkbox').props.checked,false);

// A complete held proposal can be compared and explicitly replanned. It must
// remain ineligible for favourites, applying, or scoped variants.
for(const [state,count,goal,available,canReplan] of [
  ['held',6,doc.goal,true,true],['held',3,doc.goal,true,true],
  ['uncertain',6,doc.goal,true,false],['uncertain',0,doc.goal,true,false],['held',0,doc.goal,true,false],
  ['held',6,'Changed goal',true,false],['held',6,doc.goal,false,false],
]){
  let cursor=0,recoveryCalls=0;
  const recoveryPlan={...advised,state,concepts:Array.from({length:count},(_,i)=>({...concept,id:'c'+i})),
    issues:[state==='uncertain'?'The writing provider timed out; its final outcome is unknown. This saved request remains reserved for operator reconciliation. No automatic retry; do not submit a replacement.':'Similar saved scene requires review.'],diversityReview:{comparedOperationIds:['a'.repeat(32)],method:'wording_similarity_only'}};
  const recoveryHooks={...React,useState:initial=>[cursor++===0?{available,conceptPlans:[recoveryPlan]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
  const recoveryModule={exports:{}};
  new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?recoveryHooks:require(name),recoveryModule,recoveryModule.exports);
  const recoveryNodes=flatten(recoveryModule.exports.default({api:(url,options)=>{recoveryCalls++;assert.equal(options.data.creativePlan.mode,'more_ideas');assert.equal(options.data.creativePlan.parentOperationId,recoveryPlan.operationId);return Promise.resolve({...recoveryPlan,operationId:'d'.repeat(32)});},url:'/writing',record:{revision:1,document:{...doc,goal}},onApply:()=>assert.fail('Held plan cannot apply')}));
  const more=recoveryNodes.find(n=>n.type==='button'&&n.props.children==='More ideas');
  assert.ok(recoveryNodes.some(n=>n.props?.role==='status'&&n.props.children===recoveryPlan.issues[0]),'Saved failure reason remains visible, including zero-concept timeout');
  assert.equal(more.props.disabled,!canReplan,`Explicit recovery: ${state}/${count}/${goal}/${available}`);
  if(canReplan){more.props.onClick();more.props.onClick();assert.equal(recoveryCalls,1);}
  for(const button of recoveryNodes.filter(n=>n.type==='button'&&typeof n.props.children==='string'&&n.props.children.startsWith('Edit and use ')))assert.equal(button.props.disabled,true);
  for(const checkbox of recoveryNodes.filter(n=>n.type==='input'&&n.props.type==='checkbox'))assert.equal(checkbox.props.disabled,true);
  assert.ok(recoveryNodes.some(n=>n.type==='p'&&JSON.stringify(n.props.children).includes('different wording does not prove')),'Limit of wording checks must be visible');
}

// Rejection is reversible saved editorial feedback, separate from image selection.
let feedbackSlot=0,feedbackRequests=[];
const feedbackHooks={...React,useState:initial=>[feedbackSlot++===0?{available:true,conceptPlans:[advised]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const feedbackModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?feedbackHooks:require(name),feedbackModule,feedbackModule.exports);
const feedbackNodes=flatten(feedbackModule.exports.default({api:(url,options)=>{feedbackRequests.push({url,...options});return Promise.resolve({...advised,...options.data});},url:'/writing',record:{revision:1,document:doc},onApply:()=>assert.fail('Feedback must never apply content')}));
const reject=feedbackNodes.find(n=>n.type==='input'&&n.props['aria-label']==='Reject '+concept.headline);
assert.ok(reject,'Owner can explicitly reject a direction without deleting it');
assert.equal(reject.props.checked,false);
reject.props.onChange({target:{checked:true}});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(feedbackRequests.length,1);
assert.equal(feedbackRequests[0].method,'PUT');
assert.deepEqual(feedbackRequests[0].data.rejectedConceptIds,[concept.id]);
assert.deepEqual(feedbackRequests[0].data.selectedConceptIds,[]);
assert.ok(feedbackNodes.some(n=>n.type==='button'&&n.props.children==='Reset preferences for this set'));
assert.ok(feedbackNodes.some(n=>n.type==='details'&&n.props['aria-label']==='Saved preference guidance'));

// A reason editor belongs to its saved set; switching cannot apply it to a sibling set.
let switchSlot=0;const switchUpdates=[];
const switchHooks={...React,useState:initial=>{const i=switchSlot++;return [i===0?{available:true,conceptPlans:[advised]}:i===10?{id:concept.id,aspect:'tone',reason:'Quiet'}:typeof initial==='function'?initial():initial,value=>switchUpdates.push([i,value])];},useEffect:()=>{},useRef:value=>({current:value})};
const switchModule={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?switchHooks:require(name),switchModule,switchModule.exports);
const switchNodes=flatten(switchModule.exports.default({api:()=>assert.fail('Switching sets never writes feedback'),url:'/writing',record:{revision:1,document:doc},onApply:()=>{}}));
switchNodes.find(n=>n.type==='select'&&n.props['aria-label']==='Saved concept set').props.onChange({target:{value:'b'.repeat(32)}});
assert.ok(switchUpdates.some(([slot,value])=>slot===10&&value===null),'Switching set must dismiss its unsaved preference reason');

// An uncertain saved request must be identifiable for support without a new call
// or exposing its prompt, provider body, credential, or arbitrary diagnostic text.
for(const legacy of [false,true]){
  let supportSlot=0;
  const failed={...advised,state:'uncertain',concepts:[],providerDiagnostic:legacy?undefined:{
    clientRequestId:'gw_'+'c'.repeat(32),requestId:'req_saved123',responseId:'resp_saved123',
    rawBody:'PRIVATE BODY',key:'PRIVATE KEY'},
    providerCheckDiagnostic:{requestId:'req_lastcheck',error:'PRIVATE EXCEPTION'}};
  const supportHooks={...React,useState:initial=>[supportSlot++===0?{available:false,conceptPlans:[failed]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
  const supportModule={exports:{}};
  new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?supportHooks:require(name),supportModule,supportModule.exports);
  const supportNodes=flatten(supportModule.exports.default({api:()=>assert.fail('Reading a support reference must not submit or check a request'),url:'/writing',record:{revision:1,document:doc},onApply:()=>assert.fail('Owner work stays exact')}));
  const details=supportNodes.find(n=>n.type==='details'&&n.props['aria-label']==='Concept request support reference');
  assert.ok(details,'Uncertain requests need a visible expandable support reference');
  const text=JSON.stringify(details.props.children);
  assert.ok(text.includes(advised.operationId),'Legacy and current operations must remain identifiable');
  if(!legacy){for(const id of ['gw_'+'c'.repeat(32),'req_saved123','resp_saved123','req_lastcheck'])assert.ok(text.includes(id));}
  for(const privateText of ['PRIVATE BODY','PRIVATE KEY','PRIVATE EXCEPTION'])assert.equal(text.includes(privateText),false);
}

// A durable pending receipt progresses without another click or inference.
// Exercise the compiled component's effect and real load/refresh boundary with
// a controlled clock; the first effect remains the ordinary history load.
async function automaticChecks({complete=false,fail=false,disabled=false}={}){
  let cursor=0;const effects=[],timers=new Map(),requests=[],updates=[];
  let serial=0;
  const autoHooks={...React,useState:initial=>[cursor++===0?{available:true,conceptPlans:[slowPlan]}:typeof initial==='function'?initial():initial,value=>updates.push(value)],
    useEffect:effect=>effects.push(effect),useRef:value=>({current:value})};
  const autoModule={exports:{}};
  new Function('require','module','exports','setTimeout','clearTimeout',bundle.outputFiles[0].text)(
    name=>name==='react'?autoHooks:require(name),autoModule,autoModule.exports,
    (fn,delay)=>{assert.equal(delay,15000);timers.set(++serial,fn);return serial;},id=>timers.delete(id));
  autoModule.exports.default({api:async(url,options)=>{
    requests.push([url,options]);
    if(fail)throw Error('Status temporarily unavailable');
    return options?{...slowPlan,state:complete?'proposed':'pending'}:{available:true,conceptPlans:[slowPlan]};
  },url:'/writing',record:{revision:1,document:doc},disabled,onApply:()=>assert.fail('Checking cannot alter the campaign')});
  const cleanup=effects[1]?.();
  return {timers,requests,updates,cleanup,async tick(){
    assert.equal(timers.size,1,'Exactly one bounded automatic status timer');
    const [id,fn]=timers.entries().next().value;timers.delete(id);await fn();
  }};
}
const autoComplete=await automaticChecks({complete:true});
assert.equal(autoComplete.timers.size,1,'Pending saved concepts must be checked without another owner click');
await autoComplete.tick();
assert.deepEqual(autoComplete.requests,[['/writing',undefined],['/writing/'+slowPlan.operationId+'/refresh',{method:'POST',data:{}}]]);
assert.equal(autoComplete.timers.size,0,'Completion stops checks');
assert.ok(autoComplete.updates.some(value=>value?.conceptPlans?.[0]?.state==='proposed'));
const autoPending=await automaticChecks();
for(let i=0;i<40;i++)await autoPending.tick();
assert.equal(autoPending.timers.size,0,'Stop after forty checks; leave manual recovery available');
assert.equal(autoPending.requests.length,80);
const autoFailure=await automaticChecks({fail:true});await autoFailure.tick();
assert.equal(autoFailure.timers.size,0,'A failed check stops automatic requests');
const autoDisabled=await automaticChecks({disabled:true});assert.equal(autoDisabled.timers.size,0,'Unsaved or changed business scope cannot be polled');
const autoUnmount=await automaticChecks();autoUnmount.cleanup();assert.equal(autoUnmount.timers.size,0,'Leaving or changing scope clears the timer');

// Availability belongs to the saved campaign, even if the owner starts an
// unsaved edit while its GET is in flight. The submission guard stays strict.
async function delayedAvailability(change){
  let cursor=0,refCursor=0,resolveHistory;
  const states=[],refs=[],effects=[],requests=[];
  const raceHooks={...React,
    useState:initial=>{const i=cursor++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
      return [states[i],value=>{states[i]=typeof value==='function'?value(states[i]):value;}];},
    useRef:initial=>refs[refCursor++]??(refs[refCursor-1]={current:initial}),
    useEffect:effect=>effects.push(effect)};
  const raceModule={exports:{}};
  new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?raceHooks:require(name),raceModule,raceModule.exports);
  const props={api:(url,options)=>{requests.push([url,options]);return new Promise(resolve=>{resolveHistory=resolve;});},
    url:'/writing',record:{id:'saved-campaign',revision:1,document:doc},onApply:()=>assert.fail('Loading cannot edit owner work')};
  function render(overrides={}){cursor=0;refCursor=0;return flatten(raceModule.exports.default({...props,...overrides}));}
  const initial=render();const captured=initial.find(n=>n.type==='button'&&n.props.children==='Propose six visual concepts');
  const loading=initial.find(n=>n.type==='button'&&n.props.children==='Check saved concept plans').props.onClick();
  render(change(props));
  resolveHistory({available:true,conceptPlans:[]});await loading;
  await captured.props.onClick();
  assert.equal(requests.length,1,'A stale submission control must never dispatch');
  return states[0];
}
assert.equal((await delayedAvailability(()=>({disabled:true})))?.available,true,
  'A temporary editing lock must not discard saved availability');
assert.equal((await delayedAvailability(props=>({record:{...props.record,document:{...doc,name:'Unsaved name'}}})))?.available,true,
  'An unsaved document edit must not discard saved availability');
assert.equal(await delayedAvailability(()=>({url:'/another-business/writing'})),null,
  'History from a different saved scope must be discarded before any follow-on refresh');
