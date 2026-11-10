import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const flatten=node=>!node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
function fixture(){
 let index=0,refIndex=0;const states=[],refs=[],calls=[];
 const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
 const module={exports:{}};
 new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const status={available:true,candidates:[],sourceChoice:{route:'create',version:0}};
 states[0]=status;
 const record={id:'c'.repeat(32),revision:1,document:{posts:[{day:1},{day:2}],creatives:[1,2].map(n=>({id:'visual-'+n,format:'image_ad',title:'Direction '+n,brief:'An illustrative service scene with room for the exact saved words '+n+'.'}))}};
 let quote={state:'available',reservationMicrousd:45000},wait=null;
 const api=async(url,options)=>{
  calls.push({url,options});
  if(url.endsWith('/estimate')){if(wait)await wait;return quote;}
  return {...options.data,state:'proposed',origin:'generated',issues:[]};
 };
 const render=()=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/campaign/images',record}));};
 const button=label=>{const found=render().find(n=>n.type==='button'&&n.props.children===label);assert.ok(found,'Missing '+label);return found;};
 const change=(label,value)=>render().find(n=>n.props['aria-label']===label).props.onChange({target:{value}});
 return{render,button,change,calls,record,status,setQuote:value=>quote=value,setWait:value=>wait=value};
}
test('single background requires a reviewed estimate and submits its exact operation once',async()=>{
 const f=fixture();
 assert.equal(f.button('Generate selected background').props.disabled,true,'An available provider alone is not a reviewed cost');
 await f.button('Generate selected background').props.onClick();assert.equal(f.calls.length,0);
 await f.button('Check background cost').props.onClick();
 const quote=f.calls[0];assert.equal(quote.url,'/campaign/images/estimate');
 assert.equal(f.button('Generate selected background').props.disabled,false);
 const estimate=f.render().find(n=>n.props['aria-label']==='Background cost estimate');
 const text=node=>typeof node==='string'?node:!node?'':React.Children.toArray(node.props?.children).map(text).join(' ');
 assert.match(text(estimate),/\$0\.045000/);assert.match(text(estimate),/not a customer price/i);
 assert.match(text(estimate),/Actual customer credits charged: 0/);
 const submit=f.button('Generate selected background').props.onClick;
 const request=submit();await submit();await request;
 assert.equal(f.calls.length,2,'Double submission must not duplicate inference');
 assert.deepEqual(f.calls[1].options.data,quote.options.data,'The checked post, direction, frame and operation must reach generation unchanged');
 assert.equal(f.button('Generate selected background').props.disabled,true,'A completed request must not look like an action to create another image on the old operation');
 await submit();assert.equal(f.calls.length,2,'A retained old handler cannot replay a consumed estimate after completion');
});
test('post, concept, frame, quality, source and saved-context changes invalidate both cost and stale callbacks',async()=>{
 const f=fixture();
 for(const [label,value] of [['Post for generated background',2],['Saved visual concept','visual-2'],['Provider canvas','1024x1536'],['Generation quality','high']]){
  await f.button('Check background cost').props.onClick();const stale=f.button('Generate selected background').props.onClick;
  f.change(label,value);
  assert.equal(f.button('Generate selected background').props.disabled,true,label);
  await stale();assert.ok(f.calls.every(c=>c.url.endsWith('/estimate')));
 }
 for(const mutate of [()=>f.record.revision++,()=>f.status.sourceChoice.version++]){
  await f.button('Check background cost').props.onClick();const stale=f.button('Generate selected background').props.onClick;
  mutate();assert.equal(f.button('Generate selected background').props.disabled,true);
  await stale();assert.ok(f.calls.every(c=>c.url.endsWith('/estimate')));
 }
 let finish;f.setWait(new Promise(resolve=>finish=resolve));
 const checking=f.button('Check background cost').props.onClick();
 const count=f.calls.length;await f.button('Check background cost').props.onClick();assert.equal(f.calls.length,count);
 f.change('Post for generated background',1);finish();await checking;
 assert.equal(f.button('Generate selected background').props.disabled,true,'Late response cannot authorise changed inputs');
});
test('unavailable, exhausted, malformed and failed estimates never enable inference or lose the campaign',async()=>{
 const f=fixture(),original=structuredClone(f.record);
 for(const quote of [{state:'unavailable',reservationMicrousd:null},{state:'unavailable'},{state:'budget_held',reservationMicrousd:45000},{state:'available',reservationMicrousd:0},null]){
  f.setQuote(quote);await f.button('Check background cost').props.onClick();
  assert.equal(f.button('Generate selected background').props.disabled,true);
  await f.button('Generate selected background').props.onClick();
  assert.ok(!JSON.stringify(f.render()).includes('$NaN'),'Malformed estimates cannot display an invented numeric price');
 }
 f.setWait(Promise.reject(Error('Cost service unavailable')));
 await f.button('Check background cost').props.onClick();
 assert.equal(f.button('Generate selected background').props.disabled,true);
 assert.ok(f.calls.every(c=>c.url.endsWith('/estimate')));assert.deepEqual(f.record,original);
 f.setWait(null);f.setQuote({state:'available',reservationMicrousd:45000});
 await f.button('Check background cost').props.onClick();assert.equal(f.button('Generate selected background').props.disabled,false,'Read-only cost checks can recover without an inference retry');
});

test('complete advert mode is costed explicitly and changing mode invalidates the authorisation',async()=>{
 const f=fixture();f.status.model='gemini-3-pro-image';
 const mode=f.render().find(n=>n.props['aria-label']==='Image design mode');
 assert.ok(mode,'Owner must choose complete advert versus editable background');
 assert.equal(mode.props.value,'complete_advert');
 await f.button('Check advert cost').props.onClick();
 assert.equal(f.calls[0].options.data.renderingMode,'complete_advert');
 const stale=f.button('Generate complete advert').props.onClick;
 f.change('Image design mode','background');
 assert.equal(f.button('Generate selected background').props.disabled,true);
 await stale();assert.equal(f.calls.length,1,'Changing design cannot reuse a previous cash estimate');
 await f.button('Check background cost').props.onClick();
 assert.equal(f.calls[1].options.data.renderingMode,undefined,'Legacy background request remains compatible');
});

test('advert cost review shows exact saved words and the selected action before inference',async()=>{
 const f=fixture();f.status.model='gemini-3-pro-image';
 f.record.document.brandKit={name:'Harbour QA'};
 Object.assign(f.record.document.posts[0],{graphicText:'Plan your next repair',supportingLine:'Plumbing enquiries for local homes.',callToAction:'Discuss your repair',objective:'Service enquiries',destinationUrl:'https://example.org/repairs'});
 Object.assign(f.record.document.posts[1],{graphicText:'Ask about heating',callToAction:'Ask a question'});
 const text=node=>typeof node==='string'?node:typeof node==='number'?String(node):!node?'':React.Children.toArray(node.props?.children).map(text).join('');
 const review=()=>text(f.render().find(n=>n.props['aria-label']==='Background cost estimate'));
 await f.button('Check advert cost').props.onClick();
 for(const expected of ['Day 1','Requested business name: Harbour QA','Requested headline: Plan your next repair','Requested supporting line: Plumbing enquiries for local homes.','Requested CTA: Discuss your repair','Post objective: Service enquiries','CTA destination: https://example.org/repairs'])assert.ok(review().includes(expected),expected);
 assert.match(review(),/not verified or connected to an ad button/);
 const stale=f.button('Generate complete advert').props.onClick;
 f.change('Post for generated background',2);
 assert.equal(review(),'','Changing the post must remove the previous words and cost authorisation');
 await stale();assert.equal(f.calls.length,1,'Reviewing/changing words must not generate an image');
 await f.button('Check advert cost').props.onClick();
 assert.ok(review().includes('Requested headline: Ask about heating'));
 assert.ok(review().includes('Requested supporting line: (none)'));
 assert.ok(review().includes('CTA destination: Not supplied'));
 assert.ok(!review().includes('example.org/repairs'),'Never borrow another post’s destination');
 delete f.record.document.brandKit;
 f.record.revision++;
 assert.equal(review(),'','Removing the saved brand invalidates its cost review');
 await f.button('Check advert cost').props.onClick();
 assert.ok(review().includes('Requested business name: Not recorded'));
 assert.ok(!review().includes('Harbour QA'),'A missing brand must not reuse the previous business name');
 assert.ok(f.calls.every(c=>c.url.endsWith('/estimate')));
});

test('complete advert alternative cost shows retained words and current action without borrowing edited copy',async()=>{
 const f=fixture();f.status.model='gemini-3-pro-image';
 const parent={operationId:'a'.repeat(32),day:1,revision:1,state:'proposed',sha256:'f'.repeat(64),issues:[],
  size:'portrait_2k',quality:'standard',renderingMode:'complete_advert',
  visualBrief:'An illustrative workshop detail with an integrated editorial hierarchy.',
  advertCopy:{businessName:'Harbour QA',headline:'Plan your repair',supportingLine:'Plumbing enquiries for local homes.',callToAction:'Discuss your repair'}};
 f.status.candidates.push(parent);
 Object.assign(f.record.document.posts[0],{graphicText:'Later edited headline',supportingLine:'Later edited proposition',callToAction:'Later edited CTA',objective:'Service enquiries',destinationUrl:'https://example.org/repairs'});
 const original=structuredClone(f.record);
 f.render().find(n=>n.props['aria-label']==='Plan alternative for '+parent.operationId).props.onClick();
 f.change('Alternative visual direction','A new illustrative workshop composition with tactile materials and natural light.');
 await f.button('Check alternative cost').props.onClick();
 const text=node=>typeof node==='string'?node:typeof node==='number'?String(node):!node?'':React.Children.toArray(node.props?.children).map(text).join('');
 const review=()=>text(f.render().find(n=>n.props['aria-label']==='Alternative cost estimate'));
 for(const expected of ['Requested business name: Harbour QA','Requested headline: Plan your repair','Requested supporting line: Plumbing enquiries for local homes.','Requested CTA: Discuss your repair','Post objective: Service enquiries','CTA destination: https://example.org/repairs'])assert.ok(review().includes(expected),expected);
 assert.ok(!review().includes('Later edited'),'A design alternative must not advertise new words as retained original wording');
 assert.equal(f.calls[0].options.data.parentOperationId,parent.operationId);
 assert.equal(f.calls[0].options.data.renderingMode,'complete_advert');
 const stale=f.button('Generate alternative background').props.onClick;
 f.record.revision++;f.record.document.posts[0].destinationUrl='https://example.org/new-action';
 assert.equal(review(),'','Saved action changes invalidate the cost and wording comparison');
 await stale();assert.equal(f.calls.length,1,'Stale review cannot initiate inference');
 await f.button('Check alternative cost').props.onClick();
 assert.ok(review().includes('https://example.org/new-action'));
 assert.ok(f.calls.every(c=>c.url.endsWith('/estimate')));
 assert.deepEqual(original.document.posts[0].graphicText,f.record.document.posts[0].graphicText);
 assert.deepEqual(f.status.candidates,[parent],'Reviewing an alternative preserves its original');
});
