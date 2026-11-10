import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import React from 'react';
const require=createRequire(import.meta.url);
const built=await build({entryPoints:['src/GrowthrovaAdAgent.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
const flatten=n=>!n||typeof n!=='object'?[]:[n,...React.Children.toArray(n.props?.children).flatMap(flatten)];
function fixture(){
 let i=0,j=0;const states=[{available:true,runs:[],imageReservationMicrousd:200000,planningCapMicrousd:500000}],refs=[],calls=[];
 const hooks={...React,useEffect:()=>{},useState:init=>{const k=i++;if(!(k in states))states[k]=init;return[states[k],v=>states[k]=typeof v==='function'?v(states[k]):v];},useRef:init=>refs[j++]||(refs[j-1]={current:init})};
 const module={exports:{}};
 new Function('require','module','exports',built.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
 const api=async(url,options)=>{calls.push({url,options});if(options)return{...options.data,runId:options.data.runId,state:'planned',expectedRevision:2,concepts:[],artifacts:[]};return states[0];};
 const render=()=>{i=0;j=0;return flatten(module.exports.default({api,url:'/campaign/ad-agent',record:{revision:2},day:1,size:'portrait_2k',disabled:false,onRefresh:async()=>{},onInspect:()=>{}}));};
 return {render,calls,states};
}
test('agent action creates a bounded saved run and labels count and progress',async()=>{
 const f=fixture();const n=f.render();
 assert.ok(n.some(x=>x.props['aria-label']==='Advert draft count'));
 await n.find(x=>x.type==='button'&&x.props.children==='Create advert drafts').props.onClick();
 assert.equal(f.calls[0].url,'/campaign/ad-agent');
 assert.equal(f.calls[0].options.data.count,3);
 assert.equal(f.calls[0].options.data.size,'portrait_2k');
 assert.equal(f.calls[0].options.data.expectedRevision,2);
 assert.ok(f.render().some(x=>x.props.role==='status'));
});
test('reopened completed run offers review rather than another generation',()=>{
 const f=fixture();
 f.states[0].runs=[{runId:'a'.repeat(32),expectedRevision:2,state:'completed',stage:'Ready for your review',count:1,completedCount:1,concepts:[{id:'c',headline:'Specific draft headline'}],artifacts:[{operationId:'b'.repeat(32),advertCopy:{headline:'Specific draft headline'},state:'proposed'}]}];
 const n=f.render();
 assert.ok(n.some(x=>x.type==='button'&&React.Children.toArray(x.props.children).join('')==='Inspect advert 1'));
 assert.equal(n.some(x=>x.type==='button'&&x.props.children==='Resume ad agent'),false);
 assert.equal(f.calls.length,0);
});
