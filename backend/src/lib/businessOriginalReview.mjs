// One bounded original at a time, through the caller's authenticated JSON
// transport. Never accept a server URL or render unverified returned bytes.
export function centeredPhotoCrop(crop, framing) {
  const width=crop?.photoWidth,height=crop?.photoHeight;
  if(!Number.isSafeInteger(width)||!Number.isSafeInteger(height)||width<16||height<16)
    throw Error('Photo dimensions unavailable; framing held.');
  if(framing==='original')return {...crop,left:0,top:0,width,height};
  const ratio=framing==='4:5'?[4,5]:framing==='1:1'?[1,1]:null;
  if(!ratio)throw Error('Choose a supported photo framing.');
  // Integer multiples preserve the exact aspect ratio in the existing pixel
  // crop contract. No stretching, resampling or saved document change here.
  const scale=Math.floor(Math.min(width/ratio[0],height/ratio[1]));
  const w=scale*ratio[0],h=scale*ratio[1];
  if(w<16||h<16)throw Error('Photo is too small for this framing. Keep the original or choose another photo.');
  return {...crop,left:Math.floor((width-w)/2),top:Math.floor((height-h)/2),width:w,height:h};
}

export function movePostMedia(assetIds, assetId, direction) {
  if(!Array.isArray(assetIds)||assetIds.length>5||new Set(assetIds).size!==assetIds.length||
     assetIds.some(id=>typeof id!=='string'||!id)||!assetIds.includes(assetId)||
     ![-1,1].includes(direction))throw Error('Choose an assigned original and an adjacent position.');
  const next=[...assetIds],from=next.indexOf(assetId),to=from+direction;
  if(to>=0&&to<next.length)[next[from],next[to]]=[next[to],next[from]];
  return next;
}

// Order is meaningful for candidates; crop/edit array order is not. Compare
// explicit fields so JSON key insertion order cannot hide a saved sequence.
export function postMediaChangesPending(saved, assetIds, photoCrops=[], videoEdits=[], staticLogoAssetId='', carouselSlides=[], carouselCaptions={}) {
  const oldCaptions=saved?.carouselCaptions||{};
  if(Object.keys(oldCaptions).length!==Object.keys(carouselCaptions).length||
     Object.entries(carouselCaptions).some(([channel,text])=>oldCaptions[channel]!==text))return true;
  const ids=saved?.assetIds||[];
  if((saved?.staticLogoAssetId||'')!==staticLogoAssetId)return true;
  if(ids.length!==assetIds.length||ids.some((id,i)=>id!==assetIds[i]))return true;
  const slides=carouselSlides.filter(s=>assetIds.includes(s.assetId)&&s.assetId!==staticLogoAssetId);
  const oldSlides=saved?.carouselSlides||[];
  if(slides.length!==oldSlides.length||slides.some(s=>{
    const prior=oldSlides.find(p=>p.assetId===s.assetId);
    return !prior||['graphicText','callToAction'].some(k=>prior[k]!==s[k]);
  }))return true;
  for(const [key,entries,fields] of [
    ['photoCrops',photoCrops,['assetId','left','top','width','height']],
    ['videoEdits',videoEdits,['assetId','startMs','endMs','muted']]]) {
    const current=entries.filter(e=>assetIds.includes(e.assetId)),previous=saved?.[key]||[];
    if(current.length!==previous.length||current.some(e=>{
      const prior=previous.find(p=>p.assetId===e.assetId);
      return !prior||fields.some(field=>prior[field]!==e[field]);
    }))return true;
  }
  return false;
}

// Assemble the existing saved previews sequentially, then recheck their shared
// context. No URLs, observations or approvals are created by this loader.
export async function loadSavedPostReview(library, day, request, active=()=>true) {
  const held=()=>{throw Error('Saved post changed or media permission is held. Reload before reviewing.');};
  const selection=library?.selection;
  const assignment=selection?.postAssignments?.find(a=>a.day===day);
  const post=library?.posts?.find(p=>p.day===day);
  if(!post||!assignment||selection.stale||library.hostedStorageVerified!==false||
     library.canSpend!==false||library.canPublish!==false||
     !Number.isInteger(library.revision)||!Number.isInteger(selection.selectionVersion)||
     !Array.isArray(assignment.assetIds)||assignment.assetIds.length<1||assignment.assetIds.length>5||
     new Set(assignment.assetIds).size!==assignment.assetIds.length)held();
  const candidates=[];let bytes=0;
  // Whole-original sizes are known before transfer. Avoid fetching a set that
  // cannot fit; rendered crops/excerpts are bounded again after byte checks.
  const knownBytes=assignment.assetIds.reduce((total,id)=>{
    const edited=['photoCrops','videoEdits'].some(key=>assignment[key]?.some(e=>e.assetId===id));
    return total+(edited?0:(library.assets.find(a=>a.assetId===id)?.sourceBytes||0));
  },0);
  if(knownBytes>25*1024*1024)throw Error('Saved post preview exceeds 25 MB. Inspect candidates individually.');
  for(const assetId of assignment.assetIds) {
    if(!active())return null;
    const asset=library.assets.find(a=>a.assetId===assetId);
    if(!asset||asset.permissionWithdrawn||asset.consentStatus!=='owner_asserted')held();
    const crop=assignment.photoCrops?.find(c=>c.assetId===assetId);
    const edit=assignment.videoEdits?.find(e=>e.assetId===assetId);
    if(crop&&edit)held();
    const expected={...asset,day,revision:library.revision,selectionVersion:selection.selectionVersion,
      ...(crop?{crop}:{}),...(edit?{edit}:{})};
    const path='/posts/'+day+'/'+encodeURIComponent(assetId)+'/'+(crop?'photo-preview':edit?'video-preview':'original-review');
    const query=new URLSearchParams({revision:expected.revision,selectionVersion:expected.selectionVersion});
    const result=await request(path+'?'+query);
    if(!active())return null;
    const blob=await (crop?photoCropPreviewBlob:edit?videoExcerptPreviewBlob:wholeOriginalReviewBlob)(result,expected);
    bytes+=blob.size;
    if(bytes>25*1024*1024)throw Error('Saved post preview exceeds 25 MB. Inspect candidates individually.');
    candidates.push({asset,blob,crop,edit,previewSha256:result.previewSha256,
      observation:selection.reviewNotes?.find(n=>n.day===day&&n.assetId===assetId)});
  }
  if(!active())return null;
  const current=await request('');
  if(!active())return null;
  requireCurrentPostContext(library,day,current);
  return {post,candidates,revision:library.revision,selectionVersion:selection.selectionVersion};
}

export function requireCurrentPostContext(library,day,current) {
  const selection=library.selection,post=library.posts.find(p=>p.day===day);
  const assignment=selection.postAssignments.find(a=>a.day===day);
  const candidates=assignment.assetIds.map(id=>({asset:library.assets.find(a=>a.assetId===id)}));
  const held=()=>{throw Error('Saved post changed or media permission is held. Reload before reviewing.');};
  if(current.revision!==library.revision||current.selection?.stale||
     current.selection?.selectionVersion!==selection.selectionVersion||
     current.selection?.reviewVersion!==selection.reviewVersion||
     current.hostedStorageVerified!==false||current.canSpend!==false||current.canPublish!==false||
     JSON.stringify(current.posts?.find(p=>p.day===day))!==JSON.stringify(post)||
     postMediaChangesPending(current.selection?.postAssignments?.find(a=>a.day===day),
       assignment.assetIds,assignment.photoCrops,assignment.videoEdits,assignment.staticLogoAssetId||'',assignment.carouselSlides,assignment.carouselCaptions)||
     candidates.some(({asset})=>{
       const latest=current.assets?.find(a=>a.assetId===asset.assetId);
       return !latest||latest.permissionWithdrawn||latest.consentStatus!=='owner_asserted'||
         latest.sourceSha256!==asset.sourceSha256;
     }))held();
}

// Actual composed bytes still require independent QC and owner approval. The
// final library read prevents attaching a result to a changed saved context.
export async function loadSavedPostComposition(library,day,request,active=()=>true,audioPolicy='silent_review') {
  const fail=()=>{throw Error('Composed preview changed or is held. Reload and inspect saved candidates.');};
  if(!['silent_review','saved_candidate_audio'].includes(audioPolicy))fail();
  const selection=library?.selection,assignment=selection?.postAssignments?.find(a=>a.day===day);
  if(!assignment||selection.stale||!assignment.assetIds.length||assignment.assetIds.length>5)fail();
  const notes=assignment.assetIds.map(id=>selection.reviewNotes?.find(n=>n.day===day&&n.assetId===id));
  if(notes.some(n=>!n||n.stale||n.outcome==='unsuitable'))fail();
  if(!active())return null;
  const query=new URLSearchParams({revision:library.revision,selectionVersion:selection.selectionVersion,
    reviewVersion:selection.reviewVersion});
  if(audioPolicy!=='silent_review')query.set('audioPolicy',audioPolicy);
  const result=await request('/posts/'+day+'/composition-preview?'+query);
  if(!active())return null;
  const m=result?.manifest,holds=x=>x&&x.approved===false&&x.canSpend===false&&x.canPublish===false&&
    x.hostedStorageVerified===false&&x.requiresIndependentQC===true&&x.requiresOwnerApproval===true;
  if(!holds(m)||m.schemaVersion!==1||m.purpose!=='unapproved_post_composition'||
     m.day!==day||m.revision!==library.revision||m.selectionVersion!==selection.selectionVersion||
     m.reviewVersion!==selection.reviewVersion||m.audioPolicy!==audioPolicy||m.frameFit!=='contain'||
     m.fps!==24||m.width!==720||m.height!==1280||m.photoDurationMs!==3000||
     !Number.isInteger(m.durationMs)||m.durationMs<1||m.durationMs>30000||
     JSON.stringify(m.post)!==JSON.stringify(library.posts.find(p=>p.day===day))||
     !Array.isArray(m.candidates)||m.candidates.length!==notes.length||
     !Array.isArray(m.timeline)||m.timeline.length!==notes.length)fail();
  let frame=0;
  for(let i=0;i<notes.length;i++) {
    const c=m.candidates[i],n=notes[i],t=m.timeline[i],id=assignment.assetIds[i];
    const asset=library.assets.find(a=>a.assetId===id);
    const edit=assignment.photoCrops?.find(e=>e.assetId===id)||assignment.videoEdits?.find(e=>e.assetId===id)||{assetId:id,wholeOriginal:true};
    if(!asset||asset.permissionWithdrawn||asset.consentStatus!=='owner_asserted'||!holds(c)||
       c.assetId!==id||c.day!==day||c.revision!==m.revision||c.selectionVersion!==m.selectionVersion||
       c.reviewVersion!==m.reviewVersion||c.sourceSha256!==asset.sourceSha256||
       c.observationSha256!==n.observationSha256||c.previewSha256!==n.previewSha256||
       c.ownerObservation?.note!==n.note||c.ownerObservation?.outcome!==n.outcome||
       JSON.stringify(c.ownerObservation?.revisionResponse)!==JSON.stringify(n.revisionResponse)||
       !c.candidateEdit||Object.keys(c.candidateEdit).length!==Object.keys(edit).length||
       Object.keys(edit).some(k=>edit[k]!==c.candidateEdit[k])||
       t?.assetId!==id||t.startFrame!==frame||!Number.isInteger(t.endFrame)||t.endFrame<=frame||t.endFrame>720||
       (asset.mediaKind==='photo'&&t.endFrame-frame!==72))fail();
    if(audioPolicy==='saved_candidate_audio'&&(typeof t.hasAudio!=='boolean'||
       ((asset.mediaKind==='photo'||edit.muted===true)&&t.hasAudio)))fail();
    frame=t.endFrame;
  }
  if(m.durationMs!==Math.round(frame/24*1000)||!Number.isInteger(m.previewBytes)||
     m.previewBytes<12||m.previewBytes>10*1024*1024||!/^[a-f0-9]{64}$/.test(m.previewSha256)||
     typeof result.previewBase64!=='string'||result.previewBase64.length!==4*Math.ceil(m.previewBytes/3)||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64))fail();
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==m.previewBytes||hash!==m.previewSha256||String.fromCharCode(...bytes.slice(4,8))!=='ftyp')fail();
  if(!active())return null;
  const current=await request('');
  if(!active())return null;
  requireCurrentPostContext(library,day,current);
  return {manifest:m,blob:new Blob([bytes],{type:'video/mp4'})};
}

// Static drafts reuse the observed catalogue selection, not creator export APIs.
export async function loadSavedStaticPost(library,day,request,active=()=>true){
  const fail=()=>{throw Error('Static draft changed or is held. Reload the saved brand, words and observed photo.');};
  const selection=library?.selection,assignment=selection?.postAssignments?.find(a=>a.day===day);
  const logoId=assignment?.staticLogoAssetId||'';
  const photoIds=assignment?.assetIds.filter(id=>id!==logoId)||[];
  if(!assignment||selection.stale||photoIds.length!==1||
    (logoId&&!assignment.assetIds.includes(logoId)))fail();
  const id=photoIds[0],asset=library.assets.find(a=>a.assetId===id);
  const note=selection.reviewNotes?.find(n=>n.day===day&&n.assetId===id);
  if(!asset||asset.mediaKind!=='photo'||asset.permissionWithdrawn||asset.consentStatus!=='owner_asserted'||
     !note||note.stale||note.outcome!=='usable_candidate')fail();
  if(!active())return null;
  const query=new URLSearchParams({revision:library.revision,selectionVersion:selection.selectionVersion,reviewVersion:selection.reviewVersion});
  const result=await request('/posts/'+day+'/static-preview?'+query);
  if(!active())return null;
  const m=result?.manifest,c=m?.candidates?.[0];
  const holds=x=>x&&x.approved===false&&x.canSpend===false&&x.canPublish===false&&
    x.hostedStorageVerified===false&&x.requiresIndependentQC===true&&x.requiresOwnerApproval===true;
  const edit=assignment.photoCrops?.find(e=>e.assetId===id)||{assetId:id,wholeOriginal:true};
  if(!holds(m)||!holds(c)||m.schemaVersion!==1||m.purpose!=='unapproved_static_post'||
    m.day!==day||m.revision!==library.revision||m.selectionVersion!==selection.selectionVersion||
    m.reviewVersion!==selection.reviewVersion||m.width!==1080||m.height!==1350||m.frameFit!=='contain'||
    m.logoIncluded!==Boolean(logoId)||m.candidates.length!==1||c.assetId!==id||c.sourceSha256!==asset.sourceSha256||
    c.observationSha256!==note.observationSha256||c.previewSha256!==note.previewSha256||
    JSON.stringify(m.post)!==JSON.stringify(library.posts.find(p=>p.day===day))||
    JSON.stringify(m.brandKit)!==JSON.stringify(library.brandKit)||
    m.layout?.copy!==(m.post?.graphicText?.trim()||m.post?.copyDraft)||m.layout?.callToAction!==m.post?.callToAction||
    !c.candidateEdit||Object.keys(c.candidateEdit).length!==Object.keys(edit).length||
    Object.keys(edit).some(k=>edit[k]!==c.candidateEdit[k])||
    !Number.isInteger(m.previewBytes)||m.previewBytes<8||m.previewBytes>10*1024*1024||
    !/^[a-f0-9]{64}$/.test(m.previewSha256)||typeof result.previewBase64!=='string'||
    result.previewBase64.length!==4*Math.ceil(m.previewBytes/3)||!/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64))fail();
  if(logoId){
    const logo=library.assets.find(a=>a.assetId===logoId);
    const logoNote=selection.reviewNotes?.find(n=>n.day===day&&n.assetId===logoId),lc=m.logoCandidate;
    if(!logo||logo.mediaKind!=='photo'||logo.permissionWithdrawn||logo.consentStatus!=='owner_asserted'||
      !logoNote||logoNote.stale||logoNote.outcome!=='usable_candidate'||!holds(lc)||lc.assetId!==logoId||
      lc.sourceSha256!==logo.sourceSha256||lc.previewSha256!==logoNote.previewSha256||
      lc.observationSha256!==logoNote.observationSha256||
      assignment.photoCrops?.some(c=>c.assetId===logoId)||
      lc.candidateEdit?.assetId!==logoId||lc.candidateEdit?.wholeOriginal!==true||
      Object.keys(lc.candidateEdit).length!==2)fail();
  }else if(m.logoCandidate)fail();
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==m.previewBytes||hash!==m.previewSha256||
    ![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))fail();
  if(!active())return null;
  const current=await request('');
  if(!active())return null;
  requireCurrentPostContext(library,day,current);
  if(JSON.stringify(current.brandKit)!==JSON.stringify(library.brandKit))fail();
  return {manifest:m,blob:new Blob([bytes],{type:'image/png'})};
}

export function verifyOriginalIntake(result, intakeId, originals, rightsStatement, consentStatus) {
  if(result?.intakeId!==intakeId || !/^[a-f0-9]{32}$/.test(intakeId) ||
     typeof result.replayed!=='boolean' || result.storage!=='offline_original_bytes' ||
     result.hostedStorageVerified!==false || !Array.isArray(result.assets) ||
     result.assets.length!==originals.length || new Set(result.assets.map(a=>a?.assetId)).size!==originals.length ||
     result.assets.some((asset,index)=>!asset || typeof asset.assetId!=='string' || !asset.assetId ||
       ['sourceSha256','sourceBytes','mimeType','originalName'].some(k=>asset[k]!==originals[index][k]) ||
       asset.rightsStatement!==rightsStatement || asset.consentStatus!==consentStatus ||
       asset.canSpend!==false || asset.canPublish!==false || asset.generationApproved!==false ||
       asset.verifiedRights!==false || asset.authenticityVerified!==false)) {
    throw Error('Import receipt did not match these originals. Keep this selection and retry, or inspect the library before leaving.');
  }
  return result.assets;
}

export async function originalReviewBlob(result, expected) {
  const item=result?.asset, encoded=result?.originalBase64;
  const types={photo:['image/png','image/jpeg','image/webp'],video:['video/mp4']};
  if(!item || item.assetId!==expected.assetId || item.sourceSha256!==expected.sourceSha256 ||
     item.sourceBytes!==expected.sourceBytes || item.mimeType!==expected.mimeType ||
     !types[item.mediaKind]?.includes(item.mimeType) ||
     !/^[a-f0-9]{64}$/.test(item.sourceSha256) ||
     !Number.isInteger(item.sourceBytes) || item.sourceBytes<1 || item.sourceBytes>10*1024*1024 ||
     typeof encoded!=='string' || encoded.length!==4*Math.ceil(item.sourceBytes/3) ||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded)) {
    throw Error('Saved original details changed or are invalid. Reload the library before reviewing.');
  }
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==item.sourceBytes || hash!==item.sourceSha256) {
    throw Error('Saved original failed its byte and SHA-256 check. Preview held.');
  }
  return new Blob([bytes],{type:item.mimeType});
}

export async function originalThumbnailBlob(result, expected) {
  if(!result || result.assetId!==expected.assetId || result.sourceSha256!==expected.sourceSha256 ||
     result.mediaKind!==expected.mediaKind || result.consentStatus!==expected.consentStatus ||
     expected.permissionWithdrawn || result.permissionWithdrawn!==false ||
     result.storage!=='offline_original_bytes' || result.hostedStorageVerified!==false ||
     result.approved!==false || result.canSpend!==false || result.canPublish!==false ||
     result.coverage!==(expected.mediaKind==='video'?'first_frame_only':'whole_photo_scaled') ||
     result.mimeType!=='image/png' || !/^[a-f0-9]{64}$/.test(result.previewSha256) ||
     !Number.isInteger(result.width)||!Number.isInteger(result.height)||
     result.width<1||result.height<1||result.width>320||result.height>320||
     typeof result.previewBase64!=='string'||!result.previewBase64.length||
     result.previewBase64.length>4*Math.ceil(512*1024/3)||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64))throw Error('Thumbnail changed or permission is held. Reload the library.');
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(hash!==result.previewSha256||bytes.length<24||
     [137,80,78,71,13,10,26,10].some((v,i)=>bytes[i]!==v))throw Error('Thumbnail failed its byte check.');
  const view=new DataView(bytes.buffer);
  if(view.getUint32(16)!==result.width||view.getUint32(20)!==result.height)throw Error('Thumbnail dimensions changed.');
  return new Blob([bytes],{type:'image/png'});
}

// A rendered preview is tied to a saved day, selection version and source hash.
export async function wholeOriginalReviewBlob(result, expected) {
  if(!result || ['assetId','sourceSha256','day','revision','selectionVersion'].some(k=>result[k]!==expected[k]) ||
     result.wholeOriginal!==true || result.previewSha256!==expected.sourceSha256 ||
     result.approved!==false || result.canSpend!==false || result.canPublish!==false ||
     typeof result.reviewReceipt!=='string' || !result.reviewReceipt.length || result.reviewReceipt.length>2400) {
    throw Error('Saved whole original changed. Reload before reviewing.');
  }
  return originalReviewBlob(result,expected);
}

export async function photoCropPreviewBlob(result, expected) {
  const cropKeys=['assetId','left','top','width','height'];
  if(!result || ['assetId','sourceSha256','day','revision','selectionVersion'].some(k=>result[k]!==expected[k]) ||
     !result.crop || cropKeys.some(k=>result.crop[k]!==expected.crop[k]) ||
     result.mimeType!=='image/png' || result.approved!==false || result.canPublish!==false || result.canSpend!==false ||
     !/^[a-f0-9]{64}$/.test(result.previewSha256) ||
     !Number.isInteger(result.width)||!Number.isInteger(result.height)||result.width<1||result.height<1||result.width>1200||result.height>1200||
     typeof result.previewBase64!=='string'||result.previewBase64.length>8*1024*1024||!result.previewBase64.length||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64)) {
    throw Error('Saved crop preview changed or is invalid. Reload before reviewing.');
  }
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(hash!==result.previewSha256 || bytes.length<24 ||
     [137,80,78,71,13,10,26,10].some((v,i)=>bytes[i]!==v))throw Error('Saved crop preview failed its byte check.');
  const view=new DataView(bytes.buffer);
  if(view.getUint32(16)!==result.width||view.getUint32(20)!==result.height)throw Error('Saved crop dimensions changed.');
  return new Blob([bytes],{type:'image/png'});
}

export async function videoExcerptPreviewBlob(result, expected) {
  const keys=['assetId','startMs','endMs','muted'];
  if(!result || ['assetId','sourceSha256','day','revision','selectionVersion'].some(k=>result[k]!==expected[k]) ||
     !result.edit || keys.some(k=>result.edit[k]!==expected.edit[k]) ||
     result.mimeType!=='video/mp4' || result.approved!==false || result.canSpend!==false || result.canPublish!==false ||
     !/^[a-f0-9]{64}$/.test(result.previewSha256) ||
     !Number.isInteger(result.previewBytes)||result.previewBytes<12||result.previewBytes>10*1024*1024||
     !Number.isInteger(result.durationMs)||Math.abs(result.durationMs-(expected.edit.endMs-expected.edit.startMs))>125||
     typeof result.hasAudio!=='boolean'||(expected.edit.muted&&result.hasAudio)||
     typeof result.previewBase64!=='string'||result.previewBase64.length!==4*Math.ceil(result.previewBytes/3)||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64)) {
    throw Error('Saved video review changed or is invalid. Reload before reviewing.');
  }
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==result.previewBytes||hash!==result.previewSha256||
     String.fromCharCode(...bytes.slice(4,8))!=='ftyp')throw Error('Saved video review failed its byte check.');
  return new Blob([bytes],{type:'video/mp4'});
}


// Called only after byte verification and browser display; the server separately
// checks the receipt, authenticated scope and current document/selection.
export function reviewNotePayload(context, reviewVersion, outcome, note, revisionResponse=null) {
  if(!context || typeof context.receipt!=='string' || !context.receipt.length || context.receipt.length>2400 ||
     !Number.isInteger(context.revision)||!Number.isInteger(context.selectionVersion)||
     !Number.isInteger(reviewVersion)||reviewVersion<0||
     !['usable_candidate','needs_changes','unsuitable'].includes(outcome)||
     typeof note!=='string'||note.trim().length<20||note.trim().length>1000) {
    throw Error('Inspect the current saved preview and describe what you observed before saving.');
  }
  if(revisionResponse && (!/^[a-f0-9]{64}$/.test(revisionResponse.observationSha256)||
     typeof revisionResponse.changeSummary!=='string'||revisionResponse.changeSummary.trim().length<20||
     revisionResponse.changeSummary.trim().length>1000))throw Error('Describe the saved edit before responding to this request.');
  return {revision:context.revision,selectionVersion:context.selectionVersion,reviewVersion,
          receipt:context.receipt,outcome,note:note.trim(),
          ...(revisionResponse?{revisionResponse:{observationSha256:revisionResponse.observationSha256,
            changeSummary:revisionResponse.changeSummary.trim()}}:{})};
}

export async function reviewPackageBlob(result, expected) {
  const manifest=result?.manifest;
  if(!manifest || ['assetId','sourceSha256','day','revision','selectionVersion','reviewVersion','observationSha256','previewSha256'].some(k=>manifest[k]!==expected[k]) ||
     manifest.schemaVersion!==1 || manifest.purpose!=='independent_qc_review' ||
     manifest.requiresIndependentQC!==true || manifest.requiresOwnerApproval!==true ||
     [result,manifest].some(x=>x.approved!==false||x.canSpend!==false||x.canPublish!==false||x.hostedStorageVerified!==false))throw Error('QC package changed. Reload the saved observation before downloading.');
  return packageBlob(result,11*1024*1024);
}

async function packageBlob(result,limit) {
  if(!/^[a-f0-9]{64}$/.test(result.packageSha256) ||
     !Number.isInteger(result.packageBytes)||result.packageBytes<4||result.packageBytes>limit||
     typeof result.packageBase64!=='string'||result.packageBase64.length!==4*Math.ceil(result.packageBytes/3)||
     !/^[A-Za-z0-9+/]*={0,2}$/.test(result.packageBase64))throw Error('QC package changed. Reload the saved observation before downloading.');
  const bytes=Uint8Array.from(atob(result.packageBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==result.packageBytes||hash!==result.packageSha256||
     [80,75,3,4].some((v,i)=>bytes[i]!==v))throw Error('QC package failed its byte check. Download held.');
  return new Blob([bytes],{type:'application/zip'});
}


export async function postReviewPackageBlob(result, expected) {
  const manifest=result?.manifest;
  const holds=x=>x&&x.approved===false&&x.canSpend===false&&x.canPublish===false&&
    x.hostedStorageVerified===false&&x.requiresIndependentQC===true&&x.requiresOwnerApproval===true;
  if(!manifest||manifest.schemaVersion!==1||manifest.purpose!=='independent_post_qc_review'||
     manifest.reviewPage?.file!=='REVIEW.html'||!Number.isInteger(manifest.reviewPage.bytes)||
     manifest.reviewPage.bytes<1||manifest.reviewPage.bytes>25*1024*1024||
     !/^[a-f0-9]{64}$/.test(manifest.reviewPage.sha256)||
     ['day','revision','selectionVersion','reviewVersion'].some(k=>manifest[k]!==expected[k])||
     !holds(manifest)||!holds({...result,requiresIndependentQC:true,requiresOwnerApproval:true})||
     !Array.isArray(expected.candidates)||!expected.candidates.length||expected.candidates.length>5||
     !Array.isArray(manifest.candidates)||manifest.candidates.length!==expected.candidates.length||
     new Set(expected.candidates.map(c=>c.assetId)).size!==expected.candidates.length||
     typeof manifest.containsOriginalMetadata!=='boolean'||
     manifest.containsOriginalMetadata!==manifest.candidates.some(c=>c?.containsOriginalMetadata===true)||
     manifest.candidates.some((candidate,i)=>!holds(candidate)||
       candidate.purpose!=='independent_qc_review'||candidate.schemaVersion!==1||
       ['day','revision','selectionVersion','reviewVersion'].some(k=>candidate[k]!==expected[k])||
       ['assetId','sourceSha256','observationSha256','previewSha256'].some(k=>candidate[k]!==expected.candidates[i][k])||
       !new RegExp('^media/'+String(i+1).padStart(2,'0')+'/candidate\\.(png|jpg|webp|mp4)$').test(candidate.candidateFile))) {
    throw Error('Post review package changed. Reload and observe every saved candidate before downloading.');
  }
  return packageBlob(result,25*1024*1024);
}
