import assert from 'node:assert/strict';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';
import * as plans from '../src/lib/growthrovaCreativePlans.mjs';
const doc=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
const concept={id:'a'.repeat(32)+'-1',headline:'A leak needs attention',buyerMotivation:'Discuss a leaking pipe',callToAction:'Enquire about plumbing',visualDirection:'Illustrative pipe with space for exact editable words.',evidence:[{id:'brief-offer',quote:'Plumbing enquiries for local homes.'}],parentConceptId:''};
const candidate={operationId:'b'.repeat(32),day:2,state:'proposed',origin:'generated',sha256:'c'.repeat(64),conceptId:concept.id,
 conceptBinding:{planOperationId:'a'.repeat(32),concept,sourceContext:writingContext(doc),brandKit:doc.brandKit??null}};
assert.equal(typeof plans.applyImageConceptCopy,'function','Saved background needs explicit copy binding without developing an unrelated creative');
const before=structuredClone(doc);
const next=plans.applyImageConceptCopy(doc,candidate);
assert.equal(next.posts[1].graphicText,concept.headline);
assert.equal(next.posts[1].callToAction,concept.callToAction);
assert.equal(next.posts[1].copyDraft,before.posts[1].copyDraft);
assert.deepEqual(next.posts.filter(p=>p.day!==2),before.posts.filter(p=>p.day!==2));
assert.deepEqual(next.creatives,before.creatives);
assert.deepEqual(doc,before);
assert.deepEqual(plans.applyImageConceptCopy(next,candidate),next);
for(const change of [c=>delete c.conceptBinding,c=>c.conceptId='foreign',c=>c.day=31,c=>c.state='uncertain',c=>c.conceptBinding.sourceContext.goal='Changed',c=>c.conceptBinding.brandKit={name:'Foreign'},c=>c.conceptBinding.concept.headline='']){
 const invalid=structuredClone(candidate);change(invalid);assert.throws(()=>plans.applyImageConceptCopy(doc,invalid));
}

// Exercise the real card handler through the same functional mutation as board.
const {build}=await import('esbuild');
const {createRequire}=await import('node:module');
const React=(await import('react')).default;
const require=createRequire(import.meta.url);
const bundle=await build({entryPoints:['src/GrowthrovaImageCandidates.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let slot=0,applied;
const hooks={...React,useState:initial=>[slot++===0?{available:false,candidates:[{...candidate,issues:[]}]}:typeof initial==='function'?initial():initial,()=>{}],useEffect:()=>{},useRef:value=>({current:value})};
const module={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const tree=module.exports.default({api:()=>{throw Error('Manual copy cannot call API');},url:'/images',record:{id:'d'.repeat(32),revision:1,document:doc},onApply:fn=>{applied=fn(doc);}});
function flatten(node){return !node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
const action=flatten(tree).find(n=>n.type==='button'&&n.props.children==='Use these concept words for day 2');
assert.ok(action);assert.equal(Boolean(action.props.disabled),false);
action.props.onClick();assert.deepEqual(applied,next);
