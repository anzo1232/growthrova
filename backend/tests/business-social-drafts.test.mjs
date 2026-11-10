import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaSocialDrafts.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useMemo:fn=>fn(),useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
const record={id:'1'.repeat(32),revision:2};
const artwork={operationId:'3'.repeat(32),previewSha256:'f'.repeat(64),frameFit:'contain',day:1,post:{copyDraft:'Book a bicycle service at our workshop.'}};
let calls=[],resolve,fail=true;
const api=async(url,options)=>{calls.push({url,options});if(options?.method==='POST'){
 await new Promise(done=>resolve=done);if(fail)throw Error('Lost acknowledgement');
 return {draft:{draftId:options.data.draftId,state:'draft',artworkSha256:artwork.previewSha256}};
}return {drafts:[],canPublish:false};};
const render=(extra={})=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/social-drafts',record,artwork,frame:'portrait',...extra}));};
const button=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
const input=(nodes,label)=>nodes.find(n=>n.props['aria-label']===label);
// A destination chooser is mounted in the real draft, never a client-written account name.
let destinationNodes=render();
assert.ok(destinationNodes.some(n=>n.type==='p'&&String(n.props.children).includes('No destination account')));
const destinationChooser=destinationNodes.find(n=>typeof n.type==='function'&&n.props.selectionChannels);
assert.ok(destinationChooser,'Draft editor reuses account inspection for explicit destination choice');
destinationChooser.props.onSelect({channel:'instagram',destination:{id:'ig-42',name:'Workshop Instagram',accountType:'business'}});
let nodes=render();
for(const channel of ['instagram','facebook','linkedin','tiktok','x']){
 assert.ok(input(nodes,'Plan '+channel),'Owner can plan '+channel+' individually');
}
for(const channel of ['facebook','linkedin','tiktok','x'])input(nodes,'Plan '+channel).props.onChange();
assert.equal(button(nodes,'Save posting draft').props.disabled,true);
assert.ok(nodes.some(n=>n.type==='p'&&String(n.props.children).includes('Chosen account identities are not publishing approval')));
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-10-31T01:30'}});
input(nodes,'Posting timezone').props.onChange({target:{value:'Europe/London'}});
input(render(),'UTC offset in minutes').props.onChange({target:{value:'60'}});
nodes=render();
assert.equal(button(nodes,'Save posting draft').props.disabled,false);
const pending=button(nodes,'Save posting draft').props.onClick();
await button(render(),'Save posting draft').props.onClick();
assert.equal(calls.length,1,'Double clicks cannot submit twice');
assert.equal(calls[0].options.data.artworkSha256,artwork.previewSha256);
assert.equal(calls[0].options.data.utcOffsetMinutes,60);
assert.equal(calls[0].options.data.expectedRevision,2);
assert.deepEqual(calls[0].options.data.destinationAccounts,{instagram:'ig-42'},'Only exact IDs go to server verification');
assert.deepEqual(calls[0].options.data.channels,['instagram','facebook','linkedin','tiktok','x']);
assert.equal('approval' in calls[0].options.data,false);
resolve();await pending;nodes=render();
const retry=button(nodes,'Retry saving same draft');assert.ok(retry,'Lost acknowledgement must offer same-ID recovery');
const originalId=calls[0].options.data.draftId;
fail=false;const recovered=retry.props.onClick();resolve();await recovered;
assert.equal(calls[1].options.data.draftId,originalId);
assert.equal(calls.length,2);
assert.equal(button(render(),'Save posting draft').props.disabled,true,'Successful frozen draft cannot be repeated silently');
// Unsaved campaign blocks creation; no inferred publication approval.
states=[];refs=[];nodes=render({disabled:true});
assert.equal(button(nodes,'Save posting draft').props.disabled,true);
console.log('PASS disconnected draft controls, exact binding, double click and same-ID acknowledgement recovery');
// A definitive server timezone rejection still permits correction (for example, differing timezone databases).
states=[];refs=[];
let rejectedCalls=0;
const invalidApi=async()=>{rejectedCalls++;const error=Error('That local time does not exist.');error.status=400;throw error;};
const invalidRender=()=>render({api:invalidApi});
nodes=invalidRender();
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-03-28T02:30'}});
input(nodes,'Posting timezone').props.onChange({target:{value:'Europe/London'}});
assert.equal(input(invalidRender(),'UTC offset in minutes'),undefined,'Unambiguous times need no occurrence choice');
await button(invalidRender(),'Save posting draft').props.onClick();nodes=invalidRender();
assert.equal(rejectedCalls,1,'Client-valid times still receive authoritative server validation');
assert.equal(nodes.find(n=>n.type==='fieldset').props.disabled,false,'Known rejection must allow correcting date/time');
assert.equal(button(nodes,'Retry saving same draft'),undefined,'Invalid inputs need correction, not acknowledgement replay');

// Reopened drafts must display separate platform holds, including unsupported media.
states=[];refs=[];
const channelChecks=[{channel:'tiktok',label:'TikTok',state:'blocked',destinationAccount:null,
 format:'single_image',mediaType:'image/png',captionCheck:{characters:2201,preliminaryLimit:2200},reasons:[{code:'rendition_required',message:'TikTok requires a reviewed JPEG or WebP rendition; original PNG preserved.'}]},
 {channel:'linkedin',label:'LinkedIn',state:'blocked',destinationAccount:null,format:'single_image',mediaType:'image/png',
 reasons:[{code:'account_not_connected',message:'Connect an eligible LinkedIn destination before publishing.'}]}];
const historyApi=async()=>({drafts:[{draftId:'a'.repeat(32),day:1,state:'draft',current:true,
 channels:['tiktok','linkedin'],caption:artwork.post.copyDraft,channelChecks,
 schedule:{localTime:'2027-10-31T01:30',timezone:'Europe/London',utcOffsetMinutes:60,utcTime:'2027-10-31T00:30:00Z'}}]});
await button(render({api:historyApi,artwork:null}),'Check saved posting drafts').props.onClick();
nodes=render({api:historyApi,artwork:null});
const text=nodes.filter(n=>typeof n.props.children==='string').map(n=>n.props.children).join(' ');
assert.ok(text.includes(channelChecks[0].reasons[0].message),'TikTok media hold is visible without discarding draft');
assert.ok(text.includes(channelChecks[1].reasons[0].message),'Other destinations retain separate connection hold');
assert.ok(text.includes('Single image · image/png'),'Actual retained format is visible');
assert.ok(text.includes('Caption: 2201 characters · preliminary limit 2200'),'Exact saved caption count and preliminary limit visible');
assert.ok(text.includes('Length checks do not confirm publishing eligibility.'),'Passing a length boundary cannot imply approval');

// A normal date requires no owner-calculated offset, and changed timezone cannot reuse it.
states=[];refs=[];nodes=render();
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-07-15T09:00'}});
input(nodes,'Posting timezone').props.onChange({target:{value:'Europe/London'}});
nodes=render();
assert.equal(button(nodes,'Save posting draft').props.disabled,false,'Normal timezone offset is resolved for the owner');
assert.ok(nodes.some(n=>n.type==='p'&&String(n.props.children).includes('2027-07-15T08:00:00.000Z')),'Exact UTC instant is visible before saving');
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-10-31T01:30'}});
nodes=render();
assert.equal(button(nodes,'Save posting draft').props.disabled,true,'Repeated hour requires explicit occurrence selection');
input(nodes,'UTC offset in minutes').props.onChange({target:{value:'60'}});
assert.equal(button(render(),'Save posting draft').props.disabled,false);
input(render(),'Posting timezone').props.onChange({target:{value:'Made/Up'}});
assert.equal(button(render(),'Save posting draft').props.disabled,true,'Invalid timezone never inherits a previous offset');

// Automatic resolution is submitted exactly, without a hidden second provider operation.
states=[];refs=[];let automaticRequest;
const automaticApi=async(url,options)=>{automaticRequest=options.data;return {draft:{draftId:options.data.draftId,state:'draft',artworkSha256:artwork.previewSha256}};};
const automaticRender=()=>render({api:automaticApi});
nodes=automaticRender();
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-07-15T09:00'}});
input(nodes,'Posting timezone').props.onChange({target:{value:'Asia/Kathmandu'}});
await button(automaticRender(),'Save posting draft').props.onClick();
assert.equal(automaticRequest.utcOffsetMinutes,345);
assert.equal(automaticRequest.timezone,'Asia/Kathmandu');
assert.equal(automaticRequest.localTime,'2027-07-15T09:00');

// Per-channel copy is explicit and frozen into the same-ID retry, never the artwork's original caption.
states=[];refs=[];calls=[];fail=true;
nodes=render();
const originalCaption=artwork.post.copyDraft;
assert.ok(input(nodes,'Instagram caption'),'Selected channel has an editable caption');
input(nodes,'Instagram caption').props.onChange({target:{value:'Book a workshop visit. 😀'}});
input(nodes,'Plan facebook').props.onChange();
nodes=render();
assert.equal(input(nodes,'Facebook caption').props.value,originalCaption,'New channel starts with original copy');
input(nodes,'Facebook caption').props.onChange({target:{value:'Ask about a bicycle service.'}});
input(nodes,'Plan facebook').props.onChange();
assert.equal(input(render(),'Facebook caption'),undefined);
input(render(),'Plan facebook').props.onChange();
nodes=render();
assert.equal(input(nodes,'Facebook caption').props.value,'Ask about a bicycle service.','Toggle preserves channel edits');
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-07-15T09:00'}});
input(nodes,'Posting timezone').props.onChange({target:{value:'Europe/London'}});
const copyPending=button(render(),'Save posting draft').props.onClick();
assert.deepEqual(calls[0].options.data.channelCaptions,{instagram:'Book a workshop visit. 😀',facebook:'Ask about a bicycle service.'});
resolve();await copyPending;
assert.equal(input(render(),'Instagram caption').props.value,'Book a workshop visit. 😀');
fail=false;const copyRetry=button(render(),'Retry saving same draft').props.onClick();resolve();await copyRetry;
assert.deepEqual(calls[1].options.data,calls[0].options.data,'Lost acknowledgement replays exact per-channel wording');
assert.equal(artwork.post.copyDraft,originalCaption);
states=[];refs=[];
const captionHistory=async()=>({drafts:[{draftId:'b'.repeat(32),day:1,state:'draft',current:true,channels:['instagram','facebook'],
 caption:originalCaption,channelCaptions:{instagram:'Instagram saved words',facebook:'Facebook saved words'},
 channelChecks:['instagram','facebook'].map(channel=>({channel,label:channel,reasons:[]})),schedule:{}}]});
await button(render({api:captionHistory,artwork:null}),'Check saved posting drafts').props.onClick();
nodes=render({api:captionHistory,artwork:null});
assert.ok(nodes.some(n=>n.type==='p'&&n.props.children==='Instagram saved words'),'Reopen shows saved Instagram wording');
assert.ok(nodes.some(n=>n.type==='p'&&n.props.children==='Facebook saved words'),'Reopen shows saved Facebook wording');

// Invalid per-channel text gives a visible repair path without dropping any edits.
states=[];refs=[];nodes=render();
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-07-15T09:00'}});
input(nodes,'Instagram caption').props.onChange({target:{value:' '}});
nodes=render();
assert.equal(button(nodes,'Save posting draft').props.disabled,true);
assert.ok(nodes.some(n=>n.props.role==='alert'&&String(n.props.children).includes('Instagram caption')),'Invalid caption explains the blocked save');
input(nodes,'Instagram caption').props.onChange({target:{value:'😀'.repeat(3000)}});
assert.equal(button(render(),'Save posting draft').props.disabled,false,'Unicode code points use the same draft bound as backend');
input(render(),'Instagram caption').props.onChange({target:{value:'😀'.repeat(3001)}});
assert.equal(button(render(),'Save posting draft').props.disabled,true);

// History can correct frozen channel copy/time by creating a new exact-artwork draft.
states=[];refs=[];
const revisionPixels=new Blob(['retained PNG fixture bytes'],{type:'image/png'});
const revisionHash=Buffer.from(await crypto.subtle.digest('SHA-256',await revisionPixels.arrayBuffer())).toString('hex');
const originalDraft={draftId:'c'.repeat(32),operationId:artwork.operationId,revision:2,day:1,frame:'square',
 state:'draft',current:true,artworkSha256:revisionHash,manifest:{...artwork,previewSha256:revisionHash},
 caption:originalCaption,channels:['instagram','x'],channelCaptions:{instagram:'Original Instagram words',x:'Original X words'},
 destinationAccounts:{instagram:{id:'ig-saved',name:'Saved Workshop',accountType:'business'}},
 schedule:{localTime:'2027-10-31T01:30',timezone:'Europe/London',utcOffsetMinutes:0,utcTime:'2027-10-31T01:30:00Z'}};
const originalSnapshot=JSON.stringify(originalDraft);
const revisionCalls=[];
let corruptRevision=false,lostRevision=false;
const revisionApi=async(url,options)=>{
 revisionCalls.push({url,options});
 if(options?.responseType==='blob')return corruptRevision?new Blob(['wrong bytes']):revisionPixels;
 if(options?.method==='POST'){
   if(lostRevision)throw Error('Lost revised draft acknowledgement');
   return {draft:{...originalDraft,...options.data}};
 }
 return {drafts:[originalDraft]};
};
const revisionRender=()=>render({api:revisionApi,artwork:null});
await button(revisionRender(),'Check saved posting drafts').props.onClick();
let revise=button(revisionRender(),'Revise as new posting draft');
assert.ok(revise,'Saved history must offer correction without returning to generation');
await revise.props.onClick();
nodes=revisionRender();
assert.equal(input(nodes,'Instagram caption').props.value,'Original Instagram words');
assert.equal(input(nodes,'X (Twitter) caption').props.value,'Original X words');
assert.equal(input(nodes,'UTC offset in minutes').props.value,'0','Repeated-hour occurrence is restored exactly');
assert.ok(nodes.some(n=>n.type==='p'&&String(n.props.children).includes('Account ID: ig-saved')),'Restored editor shows exact saved destination');
assert.equal(button(nodes,'Revise as new posting draft').props.disabled,true,'Another selection cannot silently replace unsaved edits');
input(nodes,'Instagram caption').props.onChange({target:{value:'Corrected Instagram words'}});
input(nodes,'Planned local date and time').props.onChange({target:{value:'2027-11-02T09:00'}});
await button(revisionRender(),'Save posting draft').props.onClick();
const revisedRequest=revisionCalls.find(c=>c.options?.method==='POST').options.data;
assert.notEqual(revisedRequest.draftId,originalDraft.draftId);
assert.equal(revisedRequest.sourceDraftId,originalDraft.draftId,'Correction must retain its saved source across retries and reopen');
assert.equal(revisedRequest.frame,'square','The original inspected export frame is retained');
assert.equal(revisedRequest.operationId,originalDraft.operationId);
assert.equal(revisedRequest.artworkSha256,revisionHash);
assert.deepEqual(revisedRequest.channelCaptions,{instagram:'Corrected Instagram words',x:'Original X words'});
assert.deepEqual(revisedRequest.destinationAccounts,{instagram:'ig-saved'},'Revision explicitly retains the original destination ID');
assert.equal(revisedRequest.localTime,'2027-11-02T09:00');
assert.equal(JSON.stringify(originalDraft),originalSnapshot,'Original saved draft is untouched');
const linkedHistory=()=>render({artwork:null,api:async()=>({drafts:[{...originalDraft,...revisedRequest}]})});
// Read the new snapshot through history rather than relying on editor-only state.
states=[];refs=[];
await button(linkedHistory(),'Check saved posting drafts').props.onClick();
assert.ok(linkedHistory().some(n=>n.type==='p'&&String(n.props.children).includes('Revision of posting draft '+originalDraft.draftId)),
 'Reopened history identifies the original draft');
assert.ok(!('approval' in revisedRequest));
// Unknown save acknowledgement must keep exact same-ID recovery, not allow a new revision.
states=[];refs=[];lostRevision=true;
await button(revisionRender(),'Check saved posting drafts').props.onClick();
await button(revisionRender(),'Revise as new posting draft').props.onClick();
await button(revisionRender(),'Save posting draft').props.onClick();
const lostRequest=revisionCalls.at(-1).options.data;
assert.equal(button(revisionRender(),'Discard unsaved posting changes').props.disabled,true);
assert.equal(button(revisionRender(),'Revise as new posting draft').props.disabled,true);
lostRevision=false;
await button(revisionRender(),'Retry saving same draft').props.onClick();
assert.deepEqual(revisionCalls.at(-1).options.data,lostRequest);
await button(revisionRender(),'Close posting draft editor').props.onClick();
assert.equal(input(revisionRender(),'Instagram caption'),undefined);
await button(revisionRender(),'Revise as new posting draft').props.onClick();
input(revisionRender(),'Instagram caption').props.onChange({target:{value:'Unsaved alternative'}});
await button(revisionRender(),'Discard unsaved posting changes').props.onClick();
await button(revisionRender(),'Revise as new posting draft').props.onClick();
assert.equal(input(revisionRender(),'Instagram caption').props.value,'Original Instagram words','Explicit discard restores saved copy on next edit');
states=[];refs=[];corruptRevision=true;
await button(revisionRender(),'Check saved posting drafts').props.onClick();
await button(revisionRender(),'Revise as new posting draft').props.onClick();
assert.equal(input(revisionRender(),'Instagram caption'),undefined,'Corrupt bytes cannot seed a revision form');
assert.ok(revisionRender().some(n=>n.props.role==='alert'&&String(n.props.children).includes('integrity')));
states=[];refs=[];originalDraft.current=false;
await button(revisionRender(),'Check saved posting drafts').props.onClick();
assert.equal(button(revisionRender(),'Revise as new posting draft').props.disabled,true,'Stale context must be reviewed through current artwork');

// Exact export metadata is visible per channel, without claiming media approval.
states=[];refs=[];
const mediaHistory=async()=>({drafts:[{draftId:'e'.repeat(32),day:1,state:'draft',current:true,
 channels:['instagram'],caption:originalCaption,schedule:{},channelChecks:[{
 channel:'instagram',label:'Instagram',format:'single_image',mediaType:'image/png',
 mediaCheck:{width:1792,height:2400,bytes:8000001,state:'needs_rendition'},
 reasons:[{code:'image_width_unsupported',message:'Review a separate rendition. Original preserved.'}]}]}]});
await button(render({api:mediaHistory,artwork:null}),'Check saved posting drafts').props.onClick();
nodes=render({api:mediaHistory,artwork:null});
assert.ok(nodes.some(n=>n.type==='p'&&n.props.children==='Saved export: 1792 × 2400 px · 8000001 bytes'),'Show actual frozen export size');
assert.ok(nodes.some(n=>n.type==='p'&&n.props.children==='A separate rendition needs preview and approval. Original artwork preserved.'));
assert.ok(nodes.some(n=>n.type==='p'&&n.props.children==='Publishing blocked'));

// A definite stale-artwork rejection is a review hold, not an uncertain save.
for(const code of ['revision_conflict','artwork_changed']){
 states=[];refs=[];originalDraft.current=true;corruptRevision=false;
 let conflictCalls=0;
 const conflictApi=async(url,options)=>{
  if(options?.method==='POST'){
   conflictCalls++;
   throw Object.assign(Error('Inspect current artwork before saving.'),{status:409,code});
  }
  return revisionApi(url,options);
 };
 const conflictRender=()=>render({api:conflictApi,artwork:null});
 await button(conflictRender(),'Check saved posting drafts').props.onClick();
 await button(conflictRender(),'Revise as new posting draft').props.onClick();
 input(conflictRender(),'Instagram caption').props.onChange({target:{value:'Keep my unsaved channel words'}});
 await button(conflictRender(),'Save posting draft').props.onClick();
 nodes=conflictRender();
 assert.equal(button(nodes,'Retry saving same draft'),undefined,'Definite stale artwork must not offer an endless identical retry');
 assert.equal(button(nodes,'Save posting draft').props.disabled,true,'Stale artwork cannot be submitted as a fresh request');
 assert.equal(button(nodes,'Discard unsaved posting changes').props.disabled,false,'An explicit discard can leave a definitely rejected editor');
 assert.equal(input(nodes,'Instagram caption').props.value,'Keep my unsaved channel words','Review hold preserves owner edits');
 await button(nodes,'Check saved posting drafts').props.onClick();
 nodes=conflictRender();
 assert.ok(nodes.some(n=>n.props.role==='status'&&String(n.props.children).includes('Review current artwork')),'Review hold remains explained after checking saved history');
 await button(nodes,'Save posting draft').props.onClick();
 assert.equal(conflictCalls,1,'Even a stale captured handler cannot resubmit rejected artwork');
 await button(conflictRender(),'Discard unsaved posting changes').props.onClick();
 await button(conflictRender(),'Revise as new posting draft').props.onClick();
 assert.equal(button(conflictRender(),'Save posting draft').props.disabled,false,'Explicitly reopening inspected artwork resets the review hold');
 assert.equal(JSON.stringify(originalDraft),originalSnapshot,'Saved original remains intact');
}
// Unrecognised conflicts may conceal a previous acknowledgement: retain same-ID recovery.
states=[];refs=[];
const unknownConflictApi=async()=>{throw Object.assign(Error('Conflicting operation'),{status:409,code:'operation_conflict'});};
const unknownRender=()=>render({api:unknownConflictApi});
input(unknownRender(),'Planned local date and time').props.onChange({target:{value:'2027-07-15T09:00'}});
await button(unknownRender(),'Save posting draft').props.onClick();
assert.ok(button(unknownRender(),'Retry saving same draft'),'Do not classify all 409s as a safe new operation');
