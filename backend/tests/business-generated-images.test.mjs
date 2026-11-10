import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
import fs from 'node:fs';
const require=createRequire(import.meta.url);

// Check the actual existing board wiring before introducing a parallel screen.
const board=fs.readFileSync('src/BusinessMarketingBoard.jsx','utf8');
assert.match(board,/<GrowthrovaImageCandidates\b/,'Saved campaigns need the real image capability action');
const styles=fs.readFileSync('src/GrowthrovaWorkspace.css','utf8');
assert.match(styles,/\.growthrova-image-candidates\s*\{[^}]*font-size:\s*16px/s,'Image review needs readable body text');
const bundle=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,
 format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
function render(status){
 let index=0;
 const hooks={...React,useState:initial=>[index++===0?status:typeof initial==='function'?initial():initial,()=>{}],
  useEffect:()=>{},useRef:value=>({current:value})};
 const module={exports:{}};
 new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const tree=module.exports.default({api:async()=>{throw Error('No network during render');},url:'/images',
  record:{revision:1,document:{posts:[{day:1}],creatives:[{id:'creative-1',format:'image_ad',title:'Abstract wheel',brief:'Abstract wheel arcs with room for exact words.'}]}}});
 function flatten(node){if(!node||typeof node!=='object')return [];return [node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
 return flatten(tree);
}
function text(nodes){return nodes.map(node=>React.Children.toArray(node.props?.children).filter(x=>typeof x==='string').join('')).join(' ');}
let nodes=render({available:false,message:'Separate image spending is not authorised.',candidates:[]});
assert.match(text(nodes),/Separate image spending/);
const generate=nodes.find(n=>n.type==='button'&&n.props.children==='Generate selected background');
assert.ok(generate);assert.equal(generate.props.disabled,true);
assert.match(text(nodes),/not a finished advert/i);
nodes=render({available:true,message:'Synthetic HTTP only',candidates:[]});
assert.equal(nodes.find(n=>n.type==='button'&&n.props.children==='Generate selected background').props.disabled,true,
 'Provider availability alone cannot authorise an unchecked individual image cost');
assert.equal(nodes.find(n=>n.type==='button'&&n.props.children==='Check background cost').props.disabled,false);
nodes=render({available:false,message:'Disabled',candidates:[{operationId:'a'.repeat(32),day:1,state:'uncertain',origin:'generated',issues:['No automatic retry']} ]});
assert.match(text(nodes),/No automatic retry/);
assert.equal(nodes.filter(n=>n.type==='button'&&n.props.children==='Inspect generated background').length,0);
nodes=render({available:false,message:'Generation held',candidates:[{operationId:'a'.repeat(32),day:1,state:'proposed',origin:'generated',issues:[]}]});
assert.ok(nodes.find(n=>n.type==='button'&&n.props.children==='Compose branded static draft'),
 'Saved generated candidates need the existing brand/copy composition path even when new generation is held');

nodes=render({available:true,message:'Nano Banana Pro',candidates:[],
 sizes:['square_2k','portrait_2k','landscape_2k'],qualities:['standard']});
const selects=nodes.filter(n=>n.type==='select');
const canvas=selects.find(n=>React.Children.toArray(n.props.children).some(child=>child.props?.value==='square_2k'));
assert.ok(canvas,'Provider-specific frames must replace unsupported legacy pixel settings');
assert.equal(canvas.props.value,'square_2k','The first supported frame is selected when old local state is unsupported');
assert.deepEqual(React.Children.toArray(canvas.props.children).map(child=>child.props.value),
 ['square_2k','portrait_2k','landscape_2k']);
const quality=selects.find(n=>n.props.value==='standard');
assert.ok(quality,'Pro uses its actual fixed 2K setting, not a fake low/medium/high control');
assert.equal(React.Children.toArray(quality.props.children).length,1);
// Free planning must let an unfunded owner choose the post and frame.
nodes=render({available:false,message:'Unfunded',candidates:[]});
assert.equal(nodes.find(n=>n.type==='fieldset'&&React.Children.toArray(n.props.children).some(c=>c.type==='legend'&&c.props.children==='Choose a generated visual')).props.disabled,false,
 'Post/frame planning cannot be locked behind paid-provider availability');
assert.equal(nodes.find(n=>n.type==='button'&&n.props.children==='Generate selected background').props.disabled,true);

const bound={operationId:'a'.repeat(32),day:1,state:'proposed',origin:'generated',sha256:'b'.repeat(64),issues:[],conceptId:'concept-1',
 conceptBinding:{concept:{id:'concept-1',headline:'A wheel worth servicing',callToAction:'Contact the workshop'}}};
nodes=render({available:false,candidates:[bound]});
assert.ok(nodes.find(n=>n.type==='details'&&n.props['aria-label']==='Compare background concept words '+bound.operationId),
 'Background must show the exact saved concept versus current post before manual replacement');
assert.ok(nodes.find(n=>n.type==='button'&&n.props.children==='Use these concept words for day 1'),
 'Saved concept words need an explicit application action, independent from paid image availability');
