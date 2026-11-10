import assert from 'node:assert/strict';
import {prepareUrlCampaign} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument} from '../src/lib/businessMarketingDocument.mjs';
import {writingContext} from '../src/lib/growthrovaWriting.mjs';
import {applyConceptDirection} from '../src/lib/growthrovaCreativePlans.mjs';

const doc=createMarketingDocument(prepareUrlCampaign({source_url:'https://example.org/',observations:{title:'Fictional Harbour Plumbing',meta_description:'Plumbing enquiries for local homes.'}}));
doc.posts[1]={...doc.posts[1],copyDraft:'Keep this full owner caption.',graphicText:'Previous headline',status:'copy_reviewed'};
const concept={id:'a'.repeat(32)+'-1',parentConceptId:'',buyerMotivation:'Discuss a leaking pipe',headline:'A leak needs attention',callToAction:'Enquire about plumbing',visualDirection:'Illustrative pipe with space for exact editable words.',evidence:[{id:'brief-offer',quote:'Plumbing enquiries for local homes.'}]};
const plan={state:'proposed',creativePlan:{mode:'initial'},material:{evidence:[]},concepts:[concept],sourceContext:writingContext(doc),brandKit:doc.brandKit??null};
const target=doc.creatives.find(c=>c.format==='image_ad');
const original=structuredClone(doc);
const next=applyConceptDirection(doc,plan,concept.id,target.id,concept,2);
assert.equal(next.posts[1].graphicText,concept.headline,'Selected concept must reach the static renderer post input');
assert.equal(next.posts[1].callToAction,concept.callToAction);
assert.equal(next.posts[1].copyDraft,original.posts[1].copyDraft,'Full caption is separate');
assert.equal(next.posts[1].status,'draft','Material graphic change requires fresh review');
assert.deepEqual(next.posts.filter(p=>p.day!==2),original.posts.filter(p=>p.day!==2));
assert.deepEqual(next.creatives.filter(c=>c.id!==target.id),original.creatives.filter(c=>c.id!==target.id));
assert.deepEqual(doc,original);
assert.deepEqual(plan.concepts,[concept]);
assert.deepEqual(applyConceptDirection(next,plan,concept.id,target.id,concept,2),next,'Repeated manual application is stable');
for(const invalid of [0,31,'2',null])assert.throws(()=>applyConceptDirection(doc,plan,concept.id,target.id,concept,invalid),/post/i);

// Render actual component with saved concepts and an open editor, before any day selection.
const {build}=await import('esbuild');
const {createRequire}=await import('node:module');
const React=(await import('react')).default;
const require=createRequire(import.meta.url);
const bundle=await build({entryPoints:['src/GrowthrovaCreativePlans.jsx'],bundle:true,write:false,format:'cjs',platform:'node',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
let slot=0;
const states=[{available:true,conceptPlans:[{...plan,operationId:'a'.repeat(32),issues:[],selectedConceptIds:[]}]},'',false,'',concept,false];
const hooks={...React,useState:initial=>{const i=slot++;return [i<states.length?states[i]:typeof initial==='function'?initial():initial,()=>{}];},useEffect:()=>{},useRef:value=>({current:value})};
const module={exports:{}};
new Function('require','module','exports',bundle.outputFiles[0].text)(name=>name==='react'?hooks:require(name),module,module.exports);
const tree=module.exports.default({api:()=>{},url:'/writing',record:{revision:1,document:doc},onApply:()=>{}});
function flatten(node){return !node||typeof node!=='object'?[]:[node,...React.Children.toArray(node.props?.children).flatMap(flatten)];}
const nodes=flatten(tree);
assert.ok(nodes.some(n=>n.type==='select'&&n.props['aria-label']==='Post to use this concept'),'Owner must choose a target post explicitly');
assert.equal(nodes.find(n=>n.type==='button'&&n.props.children==='Compare concept replacement').props.disabled,true);
const card=nodes.find(n=>n.type==='article');
assert.ok(!React.Children.toArray(card.props.children).some(n=>n?.type==='p'&&n.props.children===concept.visualDirection),'Full provider instructions stay in expandable details');
assert.ok(flatten(card).some(n=>n.type==='details'&&flatten(n).some(child=>child.props?.children===concept.visualDirection)));

// Contrasting prelaunch fixture: applying exact reviewed words must not turn a
// human-review offer into autonomous sending or rewrite the owner caption.
const startup=structuredClone(doc);
startup.business='Fictional SignalNest AI';
startup.posts[0].copyDraft='An AI assistant that helps small support teams draft replies grounded in their own help articles, for human review. Request early access.';
const startupConcept={...concept,headline:'Your knowledge. A draft to review.',callToAction:'Request early access',visualDirection:'Editorial illustration of help articles leading to a draft and a human review step. No fictional live interface or customer logos.'};
const startupPlan={...plan,concepts:[startupConcept],sourceContext:writingContext(startup)};
const startupNext=applyConceptDirection(startup,startupPlan,startupConcept.id,target.id,startupConcept,1);
assert.equal(startupNext.posts[0].graphicText,startupConcept.headline);
assert.equal(startupNext.posts[0].callToAction,'Request early access');
assert.equal(startupNext.posts[0].copyDraft,startup.posts[0].copyDraft);
assert.deepEqual(startupNext.posts.slice(1),startup.posts.slice(1));
