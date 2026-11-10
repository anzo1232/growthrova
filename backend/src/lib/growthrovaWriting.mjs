import schema from './growthrovaWriterSchema.json' with {type:'json'};
import {editMarketingPost,editMarketingCreative} from './businessMarketingDocument.mjs';

/** Same strict shape as the provider/server. Never infer semantic or rights approval. */
export function validateWriting(value,spec=schema){
  if(spec.type==='object'){
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join('|')!==Object.keys(spec.properties).sort().join('|'))throw Error('Invalid writing fields.');
    for(const [key,child] of Object.entries(spec.properties))validateWriting(value[key],child);
  }else if(spec.type==='array'){
    if(!Array.isArray(value)||value.length<spec.minItems||value.length>spec.maxItems)throw Error('Invalid writing item count.');
    for(const item of value)validateWriting(item,spec.items);
  }else if(spec.type==='string'){
    if(typeof value!=='string'||Array.from(value.trim()).length<spec.minLength||Array.from(value).length>spec.maxLength||/[\u0000-\u0008\u000b-\u001f\u007f]/u.test(value))throw Error('Invalid writing text.');
  }else if(spec.type==='integer'&&(!Number.isInteger(value)||value<spec.minimum||value>spec.maximum))throw Error('Invalid shot duration.');
  return value;
}
export function writingPostWords(post){return post.hook+'\n\n'+post.caption;}
/** Resolve citations against this saved proposal, never the current edited brief.
 * A linked page supplies context; owner corrections need not quote that page.
 */
export function writingEvidenceSources(proposal,item){
  return item.evidence.map(citation=>{
    const source=proposal.material.evidence.find(source=>source.id===citation.id);
    let sourceUrl='',label='Source missing or excerpt changed · review required';
    if(source&&source.quote.includes(citation.quote)){
      // Display-only links: never fetch a page or infer source/claim approval.
      try{
        const url=new URL(source.sourceUrl);
        if(url.protocol==='https:'&&!url.username&&!url.password)sourceUrl=url.href;
      }catch{/* A missing/invalid historical link leaves the excerpt readable. */}
      if(source.status==='owner_correction')label='Owner correction · '+(sourceUrl?'linked page is context, not verification':'source link unavailable');
      else if(source.status==='owner_reviewed_observation')label='Owner-reviewed observation · '+(sourceUrl?'not independently verified':'source link unavailable');
      else if(source.status==='owner_input')label='Owner input · no website source';
      else label='Unconfirmed website claim · cannot support proposed copy';
    }
    return {...citation,sourceUrl,label};
  });
}
export function writingReelBrief(reel){
  let second=0;
  return reel.shots.map(shot=>{
    const start=second;second+=shot.seconds;
    return `${start}–${second}s\nPicture: ${shot.visual}\nVoiceover: ${shot.voiceover}\nOn-screen words: ${shot.onScreen}`;
  }).join('\n\n');
}
export function writingContext(document){
  return {...Object.fromEntries(['business','goal','sourceUrl','observedFacts','ownerStrategy','editorialShortlist','brandIdentity'].map(key=>[key,document[key]??null])),
    ...(document.observedFactSources?{observedFactSources:document.observedFactSources}:{})};
}
const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
/** Read-only comparison of a scoped revision with its exact saved parent.
 * Missing history must not be replaced with a different version or current edits.
 */
export function writingRevisionComparison(proposal,proposals){
  if(!proposal?.revisionRequest)return null;
  const {target,instruction}=proposal.revisionRequest;
  const equal=(a,b)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
  const unavailable={target,instruction,error:'Original writing is unavailable for comparison. Check saved proposals again; do not assume the requested scope was preserved.'};
  const original=proposals.find(item=>item.operationId===proposal.repairOf);
  if(!original?.sample||!original.sourceContext||!proposal.sample||!equal(original.sourceContext,proposal.sourceContext))return unavailable;
  if(!['post-1','post-2','post-3','reel'].includes(target))return unavailable;
  try{validateWriting(original.sample);validateWriting(proposal.sample);}
  catch{return unavailable;}
  const index=Number(target.slice(-1))-1;
  const before=target==='reel'?original.sample.reel:original.sample.posts[index];
  const after=target==='reel'?proposal.sample.reel:proposal.sample.posts[index];
  const unrelated=target==='reel'?{...proposal.sample,reel:before}:
    {...proposal.sample,posts:proposal.sample.posts.map((item,i)=>i===index?before:item)};
  const contentKeys=['hook','caption','callToAction',...(target==='reel'?['shots']:[])];
  return {target,instruction,before,after,otherItemsUnchanged:equal(unrelated,original.sample),
    contentChanged:contentKeys.some(key=>!equal(before[key],after[key]))};
}
export function writingMatchesDocument(document,proposal){
  return Boolean(proposal?.sourceContext)&&JSON.stringify(canonical(writingContext(document)))===JSON.stringify(canonical(proposal.sourceContext));
}

/** Explicit single-target replacement uses the editor's existing invalidation rules. */
export function applyWriting(document,proposal,kind,target,index=0){
  if(proposal?.state!=='proposed'||proposal.independentReview!=='pending')throw Error('Held writing cannot replace a draft.');
  if(!writingMatchesDocument(document,proposal))throw Error('Business facts or strategy changed. Request writing from the current saved context.');
  validateWriting(proposal.sample);
  if(kind==='post'){
    const post=proposal.sample.posts[index];
    if(!post)throw Error('Choose a proposed post.');
    return editMarketingPost(document,target,{theme:post.angle,copyDraft:writingPostWords(post),callToAction:post.callToAction});
  }
  if(kind==='creative'){
    const creative=document.creatives.find(item=>item.id===target);
    if(!creative||!['image_ad','carousel','graphic'].includes(creative.format))
      throw Error('Choose an existing static creative draft for these words.');
    const post=proposal.sample.posts[index];
    if(!post)throw Error('Choose a proposed post.');
    // Caption/CTA only: preserve artwork, visual direction and title. The
    // creative editor enforces its shorter word limit and resets word review.
    return editMarketingCreative(document,target,{copyDraft:writingPostWords(post),callToAction:post.callToAction});
  }
  if(kind==='reel'){
    const creative=document.creatives.find(item=>item.id===target);
    if(creative?.format!=='video_ad'||creative.ratio!=='9:16')throw Error('Choose an existing portrait video concept for the storyboard.');
    const reel=proposal.sample.reel;
    return editMarketingCreative(document,target,{copyDraft:writingPostWords(reel),callToAction:reel.callToAction,brief:writingReelBrief(reel)});
  }
  throw Error('Choose a post, static creative or reel destination.');
}
/** Snapshot the exact destination for an explicit, non-mutating comparison. */
export function previewWritingReplacement(document,proposal,kind,target,index=0){
  const next=applyWriting(document,proposal,kind,target,index);
  const field=kind==='post'?'posts':'creatives',key=kind==='post'?'day':'id';
  return {kind,target,index,
    before:structuredClone(document[field].find(item=>item[key]===target)),
    after:structuredClone(next[field].find(item=>item[key]===target))};
}
export function applyWritingReplacement(document,proposal,preview){
  const current=previewWritingReplacement(document,proposal,preview.kind,preview.target,preview.index);
  if(JSON.stringify(canonical(current))!==JSON.stringify(canonical(preview)))
    throw Error('The destination or proposed writing changed. Cancel and compare again before replacing it.');
  return applyWriting(document,proposal,preview.kind,preview.target,preview.index);
}
export function writingText(proposal){
  validateWriting(proposal.sample);
  const blocks=proposal.sample.posts.map((post,i)=>`Post ${i+1}: ${post.angle}\n\n${writingPostWords(post)}\n\n${post.callToAction}`);
  blocks.push(`Reel\n\n${writingPostWords(proposal.sample.reel)}\n\n${proposal.sample.reel.callToAction}\n\n${writingReelBrief(proposal.sample.reel)}`);
  return ['Proposed campaign writing — '+proposal.material.business,
    'Goal (planning input): '+proposal.material.goal.value,
    'Audience (planning input): '+proposal.material.audience.value,
    'Independent review pending. No media rights, rendering, publication or spend approval.',
    'State: '+proposal.state,...blocks,'INTERNAL EVIDENCE — not publishable wording',
    JSON.stringify({evidence:proposal.material.evidence,posts:proposal.sample.posts.map(p=>p.evidence),reel:proposal.sample.reel.evidence,issues:proposal.issues,
      ...(proposal.revisionRequest?{revisionRequest:proposal.revisionRequest,repairOf:proposal.repairOf}:{})},null,2),''].join('\n\n');
}
