import {editMarketingCreative,editMarketingPost} from './businessMarketingDocument.mjs';
import {writingContext,validateWriting} from './growthrovaWriting.mjs';
import schema from './growthrovaConceptSchema.json' with {type:'json'};

const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
// Website extraction can preserve literal JSON unicode escapes in an older saved
// plan while the campaign later holds the same decoded characters. Normalise
// that representation only for freshness checks; saved evidence stays intact.
const normaliseEscapes=value=>Array.isArray(value)?value.map(normaliseEscapes):value&&typeof value==='object'?
  Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normaliseEscapes(item)])):
  typeof value==='string'?value.replace(/\\u([0-9a-f]{4})/gi,(_,hex)=>String.fromCharCode(parseInt(hex,16))):value;
// Historical three/six-card plans have no structured proposition. Validate
// their original shape without rewriting them or erasing saved post wording.
function validateConcept(words){
  const spec=schema.properties.concepts.items;
  if(Object.hasOwn(words,'heroVisual')||Object.hasOwn(words,'conceptLogic'))return validateWriting(words,spec);
  const legacyOptional=new Set(['supportingLine','heroVisual','conceptLogic']);
  const absent=new Set([...legacyOptional].filter(key=>!Object.hasOwn(words,key)));
  const properties=Object.fromEntries(Object.entries(spec.properties).filter(([key])=>!absent.has(key)));
  return validateWriting(words,{...spec,properties,required:spec.required.filter(key=>!absent.has(key))});
}
const comparableBrand=value=>value?{...value,default_cta:value.default_cta??''}:null;
export function conceptPlanMatches(document,plan){
  return Boolean(plan?.creativePlan&&equal(normaliseEscapes(writingContext(document)),normaliseEscapes(plan.sourceContext))&&
    equal(comparableBrand(document.brandKit),comparableBrand(plan.brandKit)));
}
export function applyConceptDirection(document,plan,conceptId,targetId,edits,day=undefined){
  if(plan?.state!=='proposed')throw Error('Choose a proposed concept; held output cannot replace your draft.');
  if(!conceptPlanMatches(document,plan))throw Error('Saved business context or brand changed. Request current concepts before replacing drafts.');
  const concept=plan.concepts.find(item=>item.id===conceptId);
  const target=document.creatives.find(item=>item.id===targetId&&item.format==='image_ad');
  if(!concept||!target)throw Error('Choose a saved concept and an existing image draft.');
  const {id,parentConceptId,...words}=concept;
  const proposed={...words,headline:edits.headline,callToAction:edits.callToAction,visualDirection:edits.visualDirection,
    ...(Object.hasOwn(edits,'supportingLine')?{supportingLine:edits.supportingLine}:{})};
  validateConcept(proposed);
  // Older callers can still develop an image direction alone. A post binding is
  // explicit: static composition reads post words, never creative titles.
  if(day!==undefined&&(!Number.isInteger(day)||!document.posts.some(p=>p.day===day)))throw Error('Choose an existing post for these graphic words.');
  const next=editMarketingCreative(document,targetId,{title:edits.headline,brief:edits.visualDirection,callToAction:edits.callToAction});
  return day===undefined?next:editMarketingPost(next,day,{graphicText:edits.headline,callToAction:edits.callToAction,
    ...(Object.hasOwn(proposed,'supportingLine')?{supportingLine:proposed.supportingLine}:{})});
}

// Applying a retained background's words changes only its explicit target post.
// The image and plan remain immutable; saving uses the board's normal mutation.
export function applyImageConceptCopy(document,candidate){
  const binding=candidate?.conceptBinding,concept=binding?.concept;
  if(candidate?.origin!=='generated'||candidate.state!=='proposed'||candidate.compositionHeld||
    !/^[a-f0-9]{64}$/.test(candidate.sha256)||!concept||concept.id!==candidate.conceptId||
    !conceptPlanMatches(document,{...binding,creativePlan:{}}))throw Error('This background has no current concept binding. Review the saved business and brand before applying words.');
  const {id,parentConceptId,...words}=concept;
  validateConcept(words);
  if(!Number.isInteger(candidate.day)||!document.posts.some(p=>p.day===candidate.day))throw Error('The intended post is no longer available.');
  return editMarketingPost(document,candidate.day,{graphicText:concept.headline,callToAction:concept.callToAction,
    ...(Object.hasOwn(concept,'supportingLine')?{supportingLine:concept.supportingLine}:{})});
}
