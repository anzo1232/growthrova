import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';

if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,
  format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];

function fixture({advert=false}={}){
  let index=0,refIndex=0,states=[],refs=[],effects=[],pause=null,failNext=false;
  const hooks={...React,useEffect:(effect,deps)=>effects.push({effect,deps}),useState:initial=>{
    const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;
    return[states[i],value=>states[i]=typeof value==='function'?value(states[i]):value];
  },useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
  const module={exports:{}};
  new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
  const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
  const candidate={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64),issues:[]};
  const post={day:1,copyDraft:'Keep the full caption.',graphicText:'Bicycle servicing',callToAction:'Contact us'};
  const record={id:'c'.repeat(32),revision:2,document:{posts:[post],creatives:[],brandKit:{name:'Workshop'}}};
  const manifest={schemaVersion:1,purpose:'unapproved_generated_static_post',origin:'generated',draftId:record.id,
    operationId:candidate.operationId,day:1,revision:2,backgroundSha256:candidate.sha256,post,brandKit:record.document.brandKit,
    layout:{copy:post.graphicText,callToAction:post.callToAction},width:1080,height:1350,frameFit:'contain',
    logoIncluded:false,logoCandidate:null,requiresIndependentQC:true,requiresOwnerApproval:true,
    approved:false,canPublish:false,canSpend:false,hostedStorageVerified:false,previewBytes:bytes.length,
    previewSha256:createHash('sha256').update(bytes).digest('hex')};
  const logo={assetId:'logo',sourceSha256:'d'.repeat(64),previewSha256:'e'.repeat(64),observationSha256:'f'.repeat(64)};
  if(advert){
    Object.assign(candidate,{renderingMode:'complete_advert',sha256:manifest.previewSha256,width:1792,height:2400,
      advertCopy:{businessName:'Workshop',headline:'Original advert headline',supportingLine:'Original service proposition.',callToAction:'Original advert CTA'}});
    Object.assign(manifest,{backgroundSha256:candidate.sha256,advertCopy:{...candidate.advertCopy},width:1792,height:2400,frameFit:'original',logoIncluded:true,
      logoCandidate:{...logo,approved:false,canPublish:false,canSpend:false,hostedStorageVerified:false,
        requiresIndependentQC:true,requiresOwnerApproval:true,candidateEdit:{assetId:logo.assetId,wholeOriginal:true}},
      layout:{layout:'logo-only',copy:candidate.advertCopy.headline,callToAction:candidate.advertCopy.callToAction}});
  }
  const calls=[],saves=[];
  let review={observations:[],version:0,needsChanges:false,independentReview:'pending',approved:false,canPublish:false};
  const api=async (path,options)=>{
    calls.push(path);
    if(path.endsWith('/original'))return new Blob([bytes],{type:'image/png'});
    if(path.endsWith('/static-observations')){
      saves.push(options);
      review={...review,version:1,needsChanges:true,observations:[{...options.data,version:1,current:true,outcome:'needs_changes'}]};
      return review;
    }
    if(path.includes('static-preview')){
      if(failNext){failNext=false;throw Error('Composition interrupted');}
      if(pause)await pause;
      return {manifest,previewBase64:bytes.toString('base64'),artworkReview:review};
    }
    if(path.endsWith('/media'))return advert?{revision:2,assets:[{...logo,consentStatus:'owner_asserted'}],
      selection:{postAssignments:[{day:1,staticLogoAssetId:logo.assetId}],reviewNotes:[{...logo,day:1,outcome:'usable_candidate'}]}}:{selection:{postAssignments:[]}};
    if(path==='/campaign')return record;
    throw Error('Unexpected request: '+path);
  };
  states[0]={available:false,candidates:[candidate]};
  const render=(extra={})=>{index=0;refIndex=0;effects=[];return flatten(module.exports.default({api,url:'/campaign/images',record,...extra}));};
  const compose=nodes=>nodes.find(n=>n.type==='button'&&n.props.children==='Compose branded static draft').props.onClick();
  const downloads=nodes=>nodes.filter(n=>n.type==='a'&&n.props.children==='Download generated static draft');
  return {record,candidate,bytes,api,calls,saves,manifest,render,compose,downloads,effects:()=>effects,effectFor:value=>effects.find(e=>e.deps?.length===1&&e.deps[0]===value)?.effect,fail(){failNext=true;},
    delay(){let release;pause=new Promise(resolve=>release=resolve);return release;}};
}

test('saved revision, campaign and API scope changes immediately hide a previous composed download',async()=>{
  const f=fixture();await f.compose(f.render());assert.equal(f.downloads(f.render()).length,1);
  for(const props of [{record:{...f.record,revision:3}},
    {record:{...f.record,id:'d'.repeat(32)}},{url:'/other/images'},
    {api:async()=>{throw Error('Different authenticated scope');}},{disabled:true}]){
    assert.equal(f.downloads(f.render(props)).length,0,'Previous composition must not be offered in a changed context');
  }
  assert.equal(f.calls.length,3,'Invalidation must not regenerate or compose automatically');
});

test('logo export review shows retained advert wording separately from later post edits',async()=>{
  const f=fixture({advert:true});
  const before=structuredClone(f.record.document);
  const button=(nodes,name)=>nodes.find(n=>n.type==='button'&&n.props.children===name);
  await button(f.render(),'Inspect complete advert').props.onClick();
  await button(f.render(),'Preview with my exact logo').props.onClick();
  const panel=f.render().find(n=>n.props['aria-label']==='Generated branded static inspection');
  assert.ok(panel,'Exact-logo artwork must remain inspectable');
  const text=flatten(panel).filter(n=>n.type==='p').map(n=>React.Children.toArray(n.props.children).join('')).join('\n');
  for(const words of ['Requested business name: Workshop','Requested headline: Original advert headline',
    'Requested supporting line: Original service proposition.','Requested CTA: Original advert CTA'])assert.ok(text.includes(words),words);
  assert.match(text,/not verified transcription/,'Requested wording is not OCR verification');
  assert.ok(!text.includes('Requested headline: Bicycle servicing'),'Later post words must not replace retained advert words');
  assert.deepEqual(f.record.document,before,'Inspection must preserve current caption and edits');
  assert.equal(f.downloads(f.render()).length,1);
  assert.equal(f.calls.length,4,'Only original, composition, media and saved campaign reads; no inference');
});

test('a composition arriving after the campaign changed cannot reappear as current',async()=>{
  for(const change of ['saved','dirty_then_restored','auth']){
    const f=fixture(),release=f.delay();
    const pending=f.compose(f.render());
    let current={};
    if(change==='saved')current={record:{...f.record,revision:3}};
    if(change==='auth')current={api:async()=>{throw Error('Different authenticated scope');}};
    if(change==='dirty_then_restored'){
      f.render({disabled:true,record:{...f.record,document:structuredClone(f.record.document)}});
    }
    f.render(current);release();await pending;
    assert.equal(f.downloads(f.render(current)).length,0,'Late pixels cannot become the current download: '+change);
    assert.equal(f.calls.length,1,'Stop stale composition before further context reads');
  }
});

test('same-context failed recompose keeps the inspected draft and never invokes image generation',async()=>{
  const f=fixture();await f.compose(f.render());
  const original=f.downloads(f.render())[0].props.href;
  f.fail();await f.compose(f.render());
  assert.equal(f.downloads(f.render())[0].props.href,original,'Failed free composition preserves the same inspected bytes');
  assert.ok(f.render().some(n=>n.props.role==='alert'&&n.props.children==='Composition interrupted'));
  assert.ok(f.calls.every(path=>!path.endsWith('/images')),'Composition must not request inference');
});

test('artwork word editing changes only its bound post and uses the normal campaign mutation',async()=>{
  const f=fixture();
  f.record.document.posts.push({day:2,copyDraft:'Keep the second caption.',graphicText:'Other graphic',callToAction:'Visit us'});
  const before=structuredClone(f.record.document),applied=[];
  const onApply=update=>applied.push(update(f.record.document));
  await f.compose(f.render({onApply}));
  const button=(nodes,name)=>nodes.find(n=>n.type==='button'&&n.props.children===name);
  const edit=button(f.render({onApply}),'Edit this artwork’s words');
  assert.ok(edit,'Owner must be able to revise headline and CTA beside the inspected advert');
  edit.props.onClick();
  let nodes=f.render({onApply});
  const field=name=>nodes.find(n=>n.props['aria-label']===name);
  assert.equal(field('Artwork headline').props.value,before.posts[0].graphicText);
  field('Artwork headline').props.onChange({target:{value:'Ready for your next ride?'}});
  nodes=f.render({onApply});
  field('Artwork CTA').props.onChange({target:{value:'Book a service'}});
  nodes=f.render({onApply});
  const apply=button(nodes,'Apply artwork words to day 1');
  apply.props.onClick();apply.props.onClick();
  assert.equal(applied.length,1);
  assert.deepEqual(applied[0].posts[0],{...before.posts[0],graphicText:'Ready for your next ride?',callToAction:'Book a service',status:'draft',scheduled:false,published:false});
  assert.deepEqual(applied[0].posts[1],before.posts[1]);
  assert.deepEqual(f.record.document,before,'Applying words must not mutate the saved input');
  assert.equal(f.calls.length,3,'Editing words must not compose, save or infer automatically');
  assert.equal(f.render({onApply}).some(n=>n.props['aria-label']==='Artwork headline'),false);
});

test('artwork editing preserves unfinished words when an observation updates the same pixels',async()=>{
  const f=fixture(),onApply=()=>{};
  await f.compose(f.render({onApply}));
  f.render({onApply}).find(n=>n.type==='button'&&n.props.children==='Edit this artwork’s words').props.onClick();
  f.render({onApply}).find(n=>n.props['aria-label']==='Artwork headline').props.onChange({target:{value:'Unfinished owner headline'}});
  const form=f.render({onApply}).find(n=>n.props.mode==='artwork');
  await form.props.onSave({sha256:f.manifest.previewSha256});
  const field=f.render({onApply}).find(n=>n.props['aria-label']==='Artwork headline');
  assert.equal(field?.props.value,'Unfinished owner headline','Saving an observation must not discard headline work');
});

test('cancel and stale artwork word controls preserve owner work without provider requests',async()=>{
  for(const change of ['cancel','context','disabled','recompose']){
    const f=fixture(),applied=[],onApply=update=>applied.push(update(f.record.document));
    await f.compose(f.render({onApply}));
    const button=(nodes,name)=>nodes.find(n=>n.type==='button'&&n.props.children===name);
    const edit=button(f.render({onApply}),'Edit this artwork’s words');
    assert.ok(edit,'Scoped artwork editor is required');edit.props.onClick();
    const apply=button(f.render({onApply}),'Apply artwork words to day 1');
    assert.equal(apply.props.disabled,true,'Unchanged words must not create a mutation');
    const field=f.render({onApply}).find(n=>n.props['aria-label']==='Artwork headline');
    field.props.onChange({target:{value:'A different headline'}});
    const stale=button(f.render({onApply}),'Apply artwork words to day 1');
    if(change==='cancel')button(f.render({onApply}),'Cancel artwork word edits').props.onClick();
    if(change==='recompose')await f.compose(f.render({onApply}));
    f.render({onApply,...(change==='context'?{record:{...f.record,revision:3}}:change==='disabled'?{disabled:true}:{})});
    stale.props.onClick();
    assert.equal(applied.length,0,change+': obsolete controls must not change a post');
    assert.equal(f.calls.length,change==='recompose'?6:3,'Only explicit free composition may make read requests');
  }
});


test('final artwork observation controls save exact composed hash and preserve the inspected draft',async()=>{
  const f=fixture();await f.compose(f.render());
  const nodes=f.render(),original=f.downloads(nodes)[0].props.href;
  const form=nodes.find(n=>n.props.mode==='artwork'&&typeof n.props.onSave==='function');
  assert.ok(form,'The composed preview needs actual final-artwork observation controls');
  assert.equal(form.props.candidate.sha256,f.manifest.previewSha256,'Review the composed image, not its background');
  assert.equal(form.props.candidate.reviewVersion,0);
  const data={reviewId:'d'.repeat(32),expectedRevision:2,expectedReviewVersion:0,
    sha256:f.manifest.previewSha256,checks:{legibility:'needs_changes'},note:'Words need more breathing room.'};
  await form.props.onSave(data);
  assert.deepEqual(f.saves,[{method:'POST',data}]);
  const updated=f.render();
  assert.equal(f.downloads(updated)[0].props.href,original,'Observation keeps exact pixels available as an unapproved draft');
  const saved=updated.find(n=>n.props.mode==='artwork');
  assert.equal(saved.props.candidate.reviewVersion,1);
  assert.equal(saved.props.candidate.observations[0].current,true);
  assert.ok(updated.some(n=>typeof n.props.children==='string'&&/Artwork needs changes/.test(n.props.children)));
  assert.ok(f.calls.every(path=>path.includes('static-')||path.endsWith('/media')||path==='/campaign'),
    'Recording an observation must never call the image-generation route');
});

test('old artwork observation callback cannot write into a changed scope',async()=>{
  const f=fixture();await f.compose(f.render());
  const form=f.render().find(n=>n.props.mode==='artwork');
  assert.ok(form,'Artwork observation form required');
  f.render({disabled:true});
  await assert.rejects(()=>form.props.onSave({}),/changed|Save|Reopen/i);
  assert.equal(f.saves.length,0,'An old form cannot save against a changed document');
});

test('square layout is free, invalidates a portrait download immediately and scopes its review',async()=>{
 const f=fixture();await f.compose(f.render());
 const select=f.render().find(n=>n.type==='select'&&n.props['aria-label']==='Static export shape');
 assert.ok(select,'Owner needs an explicit export shape control');
 select.props.onChange({target:{value:'square'}});
 assert.equal(f.downloads(f.render()).length,0,'Changing shape hides old download before any response');
 f.manifest.height=1080;
 await f.compose(f.render());
 assert.ok(f.calls.some(path=>path.endsWith('&frame=square')));
 const download=f.downloads(f.render())[0];assert.ok(download);
 assert.match(download.props.download,/square/);
 const review=f.render().find(n=>n.props.mode==='artwork');
 await review.props.onSave({reviewId:'e'.repeat(32),sha256:f.manifest.previewSha256});
 assert.equal(f.saves[0].data.exportFrame,'square','Review must validate the actual chosen layout');
 assert.equal(f.calls.filter(path=>path==='/campaign/images').length,0,'No layout inference');
});

test('portrait response arriving after a square choice cannot restore stale pixels',async()=>{
 const f=fixture(),release=f.delay();
 const pending=f.compose(f.render());
 const select=f.render().find(n=>n.type==='select'&&n.props['aria-label']==='Static export shape');
 assert.ok(select);
 select.props.onChange({target:{value:'square'}});f.render();
 release();await pending;
 assert.equal(f.downloads(f.render()).length,0);
});

test('story control replaces square pixels and scopes review without inference',async()=>{
 const f=fixture();await f.compose(f.render());
 const select=f.render().find(n=>n.type==='select'&&n.props['aria-label']==='Static export shape');
 assert.ok(flatten(select).some(n=>n.type==='option'&&n.props.value==='story'),'Story must be a real owner-facing choice');
 select.props.onChange({target:{value:'story'}});
 assert.equal(f.downloads(f.render()).length,0);
 f.manifest.height=1920;
 await f.compose(f.render());
 assert.ok(f.calls.some(path=>path.endsWith('&frame=story')));
 assert.match(f.downloads(f.render())[0].props.download,/story/);
 await f.render().find(n=>n.props.mode==='artwork').props.onSave({reviewId:'e'.repeat(32),sha256:f.manifest.previewSha256});
 assert.equal(f.saves[0].data.exportFrame,'story');
 assert.ok(f.calls.every(path=>path.includes('static-')||path.endsWith('/media')||path==='/campaign'));
});


test('saved image sets open the exact retained original through the existing hash-checked inspector',async()=>{
  const f=fixture(),reads=[];
  f.candidate.sha256=createHash('sha256').update(f.bytes).digest('hex');
  const before=structuredClone(f.record);
  let corrupt=false;
  const api=async(path,options)=>{
    reads.push({path,options});
    if(path.endsWith('/observations'))return {...f.candidate,reviewVersion:1,compositionHeld:true};
    assert.equal(path,'/campaign/images/'+f.candidate.operationId+'/original');
    assert.equal(options.responseType,'blob');
    return new Blob([corrupt?Buffer.from('wrong pixels'):f.bytes],{type:'image/png'});
  };
  const batch=props=>f.render(props).find(n=>typeof n.type==='function'&&n.props.onRefresh&&n.props.status);
  const props={api};
  assert.equal(typeof batch(props).props.onInspect,'function','Saved sets must connect to the real inspector');
  assert.equal(f.render({...props,disabled:true}).find(n=>n.type==='button'&&n.props.children==='Inspect generated background').props.disabled,true,
    'Direct inspection must show the same disabled scope as set inspection');
  await batch({...props,disabled:true}).props.onInspect(f.candidate);
  assert.equal(reads.length,0,'Disabled campaign cannot begin an inspection');
  await batch(props).props.onInspect(f.candidate);
  const inspection=f.render(props).find(n=>n.props['aria-label']==='Generated background inspection');
  assert.ok(inspection,'The set action must display the actual original, not just metadata');
  assert.equal(reads.length,1);
  const href=flatten(inspection).find(n=>n.type==='a').props.href;
  assert.deepEqual(Buffer.from(await (await fetch(href)).arrayBuffer()),f.bytes);
  assert.equal(inspection.props.tabIndex,-1,'Inspection panel must receive keyboard focus');
  let focused=0;
  inspection.ref.current={focus:()=>focused++};
  const showInspection=f.effectFor(href);
  assert.equal(typeof showInspection,'function','Opening original pixels must move focus to the inspection below');
  showInspection();assert.equal(focused,1);
  const previousEffects=f.effects();
  const observer=flatten(inspection).find(n=>typeof n.type==='function'&&n.props.onSave&&n.props.candidate);
  await observer.props.onSave({note:'Keep the original; review the composition.'});
  f.render(props);
  // React cleans up an effect when any dependency changes. Simulate only
  // changed effects, so unrelated mount/load effects do not run here.
  f.effects().forEach((effect,i)=>{
    const previous=previousEffects[i];
    if(previous?.deps?.some((dep,j)=>!Object.is(dep,effect.deps?.[j]))){
      const cleanup=previous.effect();if(typeof cleanup==='function')cleanup();
    }
  });
  assert.deepEqual(Buffer.from(await (await fetch(href)).arrayBuffer()),f.bytes,
    'Saving an observation must not revoke the displayed original or its download');
  corrupt=true;
  await batch(props).props.onInspect(f.candidate);
  assert.ok(f.render(props).some(n=>n.props.role==='alert'&&/do not match/.test(n.props.children)));
  assert.equal(reads.length,3);
  assert.deepEqual(f.record,before,'Inspecting a batch must preserve words, siblings and saved context');
});
