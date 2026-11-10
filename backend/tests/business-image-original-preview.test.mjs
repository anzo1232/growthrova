import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import React from 'react';
const require=createRequire(import.meta.url);
const bundle=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,
 format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let index=0,refIndex=0,states=[],refs=[];
const hooks={...React,useEffect:()=>{},useState:initial=>{const i=index++;if(!(i in states))states[i]=typeof initial==='function'?initial():initial;return[states[i],v=>states[i]=typeof v==='function'?v(states[i]):v];},useRef:initial=>{const i=refIndex++;return refs[i]||(refs[i]={current:initial});}};
const module={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const flatten=node=>!node||typeof node!=='object'||node.props?.hidden?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];
// Real local synthetic JPEG pixels; no network, model or business media.
const jpeg=Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAYACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDhqKKKzOMKKKKACiiigAooooA//9k=','base64');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
let record={id:'local-qa',revision:1,document:{posts:[{day:1}],creatives:[]}};
let blob,calls=[],pauseOriginal=null;
const api=async(url,options)=>{calls.push({url,options});assert.equal(url,'/images/'+'a'.repeat(32)+'/original');assert.deepEqual(options,{responseType:'blob'});if(pauseOriginal)await pauseOriginal;return blob;};
const render=()=>{index=0;refIndex=0;return flatten(module.exports.default({api,url:'/images',record}));};
const link=nodes=>nodes.find(n=>n.type==='a'&&n.props.children==='Download generated background');
async function inspect({bytes=jpeg,type='image/jpeg',mimeType='image/jpeg',sha256=digest(bytes),state='proposed',renderingMode}={}){
 states=[];refs=[];calls=[];blob=new Blob([bytes],{type});
 const candidate={operationId:'a'.repeat(32),origin:'generated',state,day:1,revision:1,sha256,issues:[],...(renderingMode?{renderingMode,advertCopy:{businessName:'Synthetic Workshop',headline:'Bicycle servicing',supportingLine:'At our workshop.',callToAction:'Contact us'}}:{}),...(mimeType?{mimeType}:{})};
 states[0]={available:false,candidates:[candidate],selection:{selectedIds:[],version:0}};
 await render().find(n=>n.type==='button'&&n.props.children===(renderingMode==='complete_advert'?'Inspect complete advert':'Inspect generated background')).props.onClick();
 return render();
}
let nodes=await inspect();
assert.ok(link(nodes),'A retained valid JPEG must open for inspection without generation');
assert.equal(link(nodes).props.download,'growthrova-generated-background-day-1.jpg');
assert.ok(nodes.some(n=>n.type==='img'&&n.props.src===link(nodes).props.href));
assert.equal(calls.length,1,'Inspecting originals must only read saved bytes');
nodes=await inspect({state:'held'});
assert.ok(link(nodes),'Held JPEG must remain inspectable without clearing its hold');
assert.ok(nodes.some(n=>n.type==='p'&&JSON.stringify(n.props.children).includes('held')));
nodes=await inspect({bytes:png,type:'image/png',mimeType:null});
assert.equal(link(nodes)?.props.download,'growthrova-generated-background-day-1.png','Legacy PNG without MIME metadata remains readable');
for(const bad of [{sha256:'b'.repeat(64)},{type:'image/svg+xml'}, {mimeType:'image/png'}, {bytes:Buffer.alloc(0)}, {bytes:Buffer.alloc(16*1024*1024+1)}]){
 nodes=await inspect(bad);
 assert.equal(link(nodes),undefined,'Invalid/mismatched original must not become downloadable');
 assert.ok(nodes.some(n=>n.props.role==='alert'),'Original failure needs an actionable error');
 assert.equal(calls.length,1,'Invalid originals cannot trigger generation');
}
// A failed read can recover in place using the same saved candidate and hash.
nodes=await inspect({bytes:png,sha256:digest(jpeg)});
assert.equal(link(nodes),undefined);
blob=new Blob([jpeg],{type:'image/jpeg'});
await nodes.find(n=>n.type==='button'&&n.props.children==='Inspect generated background').props.onClick();
nodes=render();assert.ok(link(nodes));assert.equal(calls.length,2);
assert.equal(nodes.some(n=>n.props.role==='alert'),false);

// Review context is part of the inspection, even when the original bytes stay identical.
for(const change of ['brand','revision','disabled']){
 nodes=await inspect();
 const oldRecord=record;
 const form=nodes.find(n=>n.props.candidate?.operationId==='a'.repeat(32)&&typeof n.props.onSave==='function');
 assert.ok(form,'Inspected original exposes background observations');
 if(change==='brand')record={...record,document:{...record.document,brandKit:{name:'Changed brand'}}};
 if(change==='revision')record={...record,revision:2};
 const changed=change==='disabled';
 index=0;refIndex=0;
 nodes=flatten(module.exports.default({api,url:'/images',record,disabled:changed}));
 assert.equal(link(nodes),undefined,change+': old inspection must not appear current');
 assert.equal(nodes.some(n=>n.props.candidate?.operationId==='a'.repeat(32)&&n.props.onSave),false);
 const reads=calls.length;
 await assert.rejects(()=>form.props.onSave({sha256:digest(jpeg)}),/inspect|context|changed/i);
 assert.equal(calls.length,reads,'Stale observations must be blocked before an API write');
 record=oldRecord;
}

// An in-flight original read cannot recreate inspection controls after a context change.
nodes=await inspect();
let release;
pauseOriginal=new Promise(resolve=>{release=resolve;});
const late=nodes.find(n=>n.type==='button'&&n.props.children==='Inspect generated background').props.onClick();
const originalRecord=record;
record={...record,document:{...record.document,brandKit:{name:'Another brand'}}};
render();
release();await late;pauseOriginal=null;
assert.equal(link(render()),undefined,'Late bytes must not restore a stale inspection');
record=originalRecord;
// A deliberate reinspection recovers the same bytes without generating an alternative.
nodes=render();
await nodes.find(n=>n.type==='button'&&n.props.children==='Inspect generated background').props.onClick();
assert.ok(link(render()));

// A complete provider design is downloaded unchanged, without template composition.
record={...record,document:{...record.document,posts:[{day:1,objective:'Service enquiries',destinationUrl:'https://example.org/book-a-service'}]}};
nodes=await inspect({renderingMode:'complete_advert'});
const customerContext=nodes.filter(n=>n.type==='p').map(n=>React.Children.toArray(n.props.children).join('')).join('\n');
assert.match(customerContext,/Post objective: Service enquiries/,'Review must show the selected advert post’s objective');
assert.match(customerContext,/CTA destination: https:\/\/example.org\/book-a-service/,'Review must expose the exact saved destination');
assert.match(customerContext,/not verified or connected to an ad button/);
assert.match(customerContext,/Requested business name: Synthetic Workshop/,'Exact generated brand wording needs a visible comparison source');
const advert=nodes.find(n=>n.type==='a'&&n.props.children==='Download complete advert draft');
assert.ok(advert,'Complete-advert original remains directly downloadable');
assert.ok(nodes.some(n=>n.type==='p'&&String(JSON.stringify(n.props.children)).includes('At our workshop.')));
assert.equal(advert.props.download,'growthrova-advert-draft-day-1.jpg');
assert.equal(nodes.some(n=>n.type==='button'&&n.props.children==='Compose branded static draft'),false);
assert.ok(nodes.some(n=>n.type==='p'&&String(JSON.stringify(n.props.children)).includes('not verified transcription')));
assert.equal(calls.length,1,'Inspect/download complete advert cannot call generation or renderer');
assert.ok(nodes.some(n=>n.type==='button'&&n.props.children==='Preview with my exact logo'&&!n.props.disabled),
 'A complete advert needs an explicit free exact-logo export beside the retained original');
nodes=await inspect({renderingMode:'complete_advert',state:'held'});
assert.equal(nodes.some(n=>n.type==='button'&&n.props.children==='Preview with my exact logo'&&!n.props.disabled),false,
 'Held originals remain downloadable but cannot be composed');
record={...record,document:{...record.document,posts:[{day:1}]}};
nodes=await inspect({renderingMode:'complete_advert'});
assert.ok(nodes.some(n=>n.type==='p'&&React.Children.toArray(n.props.children).join('').includes('CTA destination: Not supplied')),
 'Missing destination must be explicit rather than an inferred booking link');
