import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaSocialAccounts.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
let calls=0,fail=false,resolve;
const accounts=['instagram','facebook','linkedin','tiktok','x'].map(channel=>({channel,label:channel,state:channel==='tiktok'?'needs_reconnect':'reported',destination:{id:channel+'42',name:'Workshop '+channel,accountType:channel==='linkedin'?'company':'unknown'},canPublish:false}));
const api=async()=>{calls++;await new Promise(done=>resolve=done);if(fail)throw Error('Accounts unavailable');return {accounts,canPublish:false,message:'Reported details may be cached for 60 seconds.'};};
const render=(extra={})=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/org/one/social-accounts',...extra}));};
const button=nodes=>nodes.find(n=>n.type==='button');
const text=nodes=>nodes.filter(n=>typeof n.props.children==='string').map(n=>n.props.children).join(' ');
assert.equal(calls,0);
let pending=button(render()).props.onClick();
await button(render()).props.onClick();assert.equal(calls,1,'Repeat checks share one flight');
resolve();await pending;
let nodes=render();
for(const a of accounts){assert.ok(text(nodes).includes(a.destination.name));assert.ok(text(nodes).includes(a.destination.id));}
assert.ok(text(nodes).includes('company'),'LinkedIn company destination type is explicit');
assert.ok(text(nodes).includes('Reconnect required'),'Expired connection is actionable');
assert.ok(text(nodes).includes('Publishing unavailable'),'Linked account is never eligibility');
accounts[0].accountTypeCheck={state:'unsupported',message:'Instagram personal accounts cannot be used for publishing. Choose a Business or Creator account.'};
accounts[2].accountTypeCheck={state:'unverified',message:'LinkedIn destination type is unverified. Check whether this is your personal account or company Page.'};
nodes=render();
assert.ok(text(nodes).includes('Instagram personal accounts cannot be used for publishing.'),'Unsupported account reason is visible beside its identity');
assert.ok(text(nodes).includes('LinkedIn destination type is unverified.'),'Unknown company/member type must be actionable');

fail=true;pending=button(render()).props.onClick();
assert.ok(!text(render()).includes('Workshop linkedin'),'Old inventory cleared while rechecking');
resolve();await pending;
assert.ok(!text(render()).includes('Workshop linkedin'),'Old reported identity is not retained after failure');
assert.ok(render().some(n=>n.props.role==='alert'),'Failure visible; retry remains available');
fail=false;pending=button(render()).props.onClick();
render({url:'/org/two/social-accounts'});resolve();await pending;
assert.ok(!text(render({url:'/org/two/social-accounts'})).includes('Workshop linkedin'),'Old-business response cannot appear for a new business');
console.log('PASS read-only account identity, expiry, error recovery, repeat-click and tenant-switch controls');

states=[];refs=[];
let selected=null;
const choiceApi=async()=>({accounts,canPublish:false});
const choiceRender=()=>render({api:choiceApi,selectionChannels:['instagram','linkedin','tiktok'],
  onSelect:account=>{selected=account;}});
await button(choiceRender()).props.onClick();
nodes=choiceRender();
const choose=channel=>nodes.find(n=>n.type==='button'&&n.props['aria-label']==='Use '+channel+' destination');
assert.ok(choose('linkedin'),'Exact account can be explicitly chosen for a draft');
assert.equal(choose('linkedin').props.disabled,false);
choose('linkedin').props.onClick();
assert.equal(selected.destination.id,'linkedin42');
assert.equal(choose('instagram').props.disabled,true,'Unsupported personal account cannot be chosen');
assert.equal(choose('tiktok').props.disabled,true,'Expired account cannot be chosen');

// Link creation is explicit, never triggered by inventory, and remains business-scoped.
states=[];refs=[];
let linkCalls=0,finishLink;
const linkUrl='https://profile.ayrshare.com?session=ayr_ls_synthetic&domain=qa&logout=true';
const linkApi=async(url,options)=>{
  if(options){
    linkCalls++;
    assert.equal(url,'/org/one/social-accounts/link-session');
    assert.deepEqual(options,{method:'POST',data:{}});
    await new Promise(done=>finishLink=done);
    return {url:linkUrl,expiresAt:new Date(Date.now()+300000).toISOString(),canPublish:false};
  }
  return {accounts,canCreateLink:true,canPublish:false};
};
const linkRender=(extra={})=>render({api:linkApi,...extra});
await button(linkRender()).props.onClick();
const prepare=nodes=>nodes.find(n=>n.type==='button'&&n.props.children==='Prepare secure connection link');
assert.ok(prepare(linkRender()),'Enabled inventory offers explicit link preparation');
assert.equal(linkCalls,0,'Inventory never creates grants or link sessions');
pending=prepare(linkRender()).props.onClick();
await prepare(linkRender()).props.onClick();
assert.equal(linkCalls,1,'Repeated click cannot issue concurrent link sessions');
finishLink();await pending;
nodes=linkRender();
const anchor=nodes.find(n=>n.type==='a'&&n.props.children==='Open secure account connection');
assert.ok(anchor,'Prepared session is opened only by explicit customer action');
assert.equal(anchor.props.href,linkUrl);
assert.equal(anchor.props.rel,'noopener noreferrer');
assert.equal(anchor.props.referrerPolicy,'no-referrer');
assert.ok(text(nodes).includes('Check social destination accounts afterwards'),'Closing a provider page is not connection proof');
assert.ok(!linkRender({url:'/org/two/social-accounts'}).some(n=>n.type==='a'),'Business switch hides old link');

states=[];refs=[];
const brokenApi=async(url,options)=>{if(options)throw Error('Secure connection temporarily unavailable');return{accounts,canCreateLink:true};};
await button(render({api:brokenApi})).props.onClick();
await prepare(render({api:brokenApi})).props.onClick();
assert.ok(text(render({api:brokenApi})).includes('Secure connection temporarily unavailable'));
assert.ok(!render({api:brokenApi}).some(n=>n.type==='a'),'Failure never opens a provider page');
console.log('PASS explicit scoped secure-link creation, no automatic grant, duplicate-click and failure recovery');

states=[];refs=[];
let linkClock=Date.now();
const nativeNow=Date.now;
Date.now=()=>linkClock;
try{
  const expiringApi=async(url,options)=>options?{url:linkUrl,expiresAt:new Date(linkClock+300000).toISOString()}:{accounts,canCreateLink:true};
  const expiringRender=extra=>render({api:expiringApi,...extra});
  await button(expiringRender()).props.onClick();
  await prepare(expiringRender()).props.onClick();
  assert.ok(!expiringRender({disabled:true}).some(n=>n.type==='a'),'A parent draft hold hides a prepared link');
  let prevented=false;
  linkClock+=300001;
  expiringRender().find(n=>n.type==='a').props.onClick({preventDefault:()=>{prevented=true;}});
  assert.ok(prevented,'Expired link cannot be opened');
  assert.ok(!expiringRender().some(n=>n.type==='a'));
  assert.ok(text(expiringRender()).includes('This connection link expired'));
}finally{Date.now=nativeNow;}

// Disconnect is separate from inspection and requires exact visible confirmation.
states=[];refs=[];
let disconnectCalls=0,finishDisconnect,disconnectFailure=false;
const disconnectApi=async(url,options)=>{
  if(options){
    disconnectCalls++;
    assert.equal(url,'/org/one/social-accounts/disconnect');
    assert.deepEqual(options,{method:'POST',data:{channel:'linkedin',destinationId:'linkedin42'}});
    await new Promise(done=>finishDisconnect=done);
    if(disconnectFailure)throw Error('Disconnection could not be confirmed. Check accounts.');
    return {state:'disconnect_acknowledged',message:'Provider acknowledged disconnection. Check accounts again; details may be cached.'};
  }
  return {accounts,canDisconnect:true,canCreateLink:true};
};
const disconnectRender=extra=>render({api:disconnectApi,...extra});
const named=(nodes,label)=>nodes.find(n=>n.type==='button'&&n.props.children===label);
await button(disconnectRender()).props.onClick();
const startDisconnect=nodes=>nodes.find(n=>n.type==='button'&&n.props['aria-label']==='Disconnect linkedin account');
assert.ok(startDisconnect(disconnectRender()),'Enabled inspector offers a scoped disconnect action');
startDisconnect(disconnectRender()).props.onClick();
assert.equal(disconnectCalls,0,'First action only asks for exact-account confirmation');
assert.ok(text(disconnectRender()).includes('Workshop linkedin (linkedin42)'), 'Confirmation names exact destination');
named(disconnectRender(),'Keep account connected').props.onClick();
assert.ok(!named(disconnectRender(),'Confirm disconnection'));
startDisconnect(disconnectRender()).props.onClick();
pending=named(disconnectRender(),'Confirm disconnection').props.onClick();
await named(disconnectRender(),'Confirm disconnection').props.onClick();
assert.equal(disconnectCalls,1,'No concurrent duplicate disconnect request');
finishDisconnect();await pending;
assert.ok(text(disconnectRender()).includes('Provider acknowledged disconnection'));
assert.ok(!startDisconnect(disconnectRender()),'Must recheck inventory before a further disconnect');
assert.ok(!disconnectRender().some(n=>n.type==='a'),'Prepared links cleared on disconnect');
await button(disconnectRender()).props.onClick();
startDisconnect(disconnectRender()).props.onClick();
disconnectFailure=true;
pending=named(disconnectRender(),'Confirm disconnection').props.onClick();
finishDisconnect();await pending;
assert.ok(text(disconnectRender()).includes('Disconnection could not be confirmed'));
assert.ok(!startDisconnect(disconnectRender()),'Uncertain result requires account reinspection, not blind retry');
await button(disconnectRender()).props.onClick();
startDisconnect(disconnectRender()).props.onClick();
assert.ok(!named(disconnectRender({url:'/org/two/social-accounts'}),'Confirm disconnection'),'Business switch hides old confirmation');
console.log('PASS scoped disconnect confirmation, cancellation, acknowledgement, uncertainty, duplicate prevention and business switch');

states=[];refs=[];
await button(disconnectRender()).props.onClick();
assert.equal(startDisconnect(disconnectRender({disabled:true})).props.disabled,true,'Parent holds prevent disconnection');
startDisconnect(disconnectRender()).props.onClick();
assert.ok(!named(disconnectRender({disabled:true}),'Confirm disconnection'),'Parent holds hide confirmation');
assert.ok(text(disconnectRender()).includes('Prepare a secure connection link'),'Enabled linking gives truthful expired-permission recovery');
states=[];refs=[];
await button(render({api:choiceApi,selectionChannels:['linkedin'],onSelect:()=>{}})).props.onClick();
const heldChoice=render({api:choiceApi,selectionChannels:['linkedin'],onSelect:()=>{},disabled:true});
assert.equal(heldChoice.find(n=>n.props['aria-label']==='Use linkedin destination').props.disabled,true,'A held draft cannot select an account');
