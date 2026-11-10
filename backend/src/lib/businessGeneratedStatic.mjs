// Generated pixels never enter the genuine-original catalogue. Bind this
// review download to the saved candidate and current document/media context.
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)
  ?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const equal=(a,b)=>canonical(a)===canonical(b);
const frameHeights={portrait:1350,square:1080,story:1920};
const holds=x=>x?.approved===false&&x.canSpend===false&&x.canPublish===false&&
  x.hostedStorageVerified===false&&x.requiresIndependentQC===true&&x.requiresOwnerApproval===true;

export async function loadGeneratedStatic(record,candidate,request,active=()=>true,frame='portrait'){
  const fail=()=>{throw Error('Generated static draft changed or is held. Reopen your saved campaign and inspect again.');};
  const advert=candidate?.renderingMode==='complete_advert';
  if(advert?frame!=='original':!Object.hasOwn(frameHeights,frame))fail();
  if(candidate?.origin!=='generated'||candidate.state!=='proposed'||
     !/^[a-f0-9]{32}$/.test(candidate.operationId)||!/^[a-f0-9]{64}$/.test(candidate.sha256))fail();
  if(!active())return null;
  const result=await request('/images/'+candidate.operationId+'/static-preview?revision='+record.revision+(frame==='portrait'?'':'&frame='+frame));
  if(!active())return null;
  const m=result?.manifest,post=record.document.posts.find(p=>p.day===candidate.day);
  if(!holds(m)||m.schemaVersion!==1||m.purpose!=='unapproved_generated_static_post'||m.origin!=='generated'||
    m.draftId!==record.id||m.operationId!==candidate.operationId||m.day!==candidate.day||m.revision!==record.revision||
    m.backgroundSha256!==candidate.sha256||!equal(m.conceptBinding??null,candidate.conceptBinding??null)||!equal(m.post,post)||!equal(m.brandKit??null,record.document.brandKit??null)||
    m.layout?.copy!==(advert?candidate.advertCopy?.headline:(post?.graphicText?.trim()||post?.copyDraft))||
    m.layout?.callToAction!==(advert?candidate.advertCopy?.callToAction:post?.callToAction)||
    (advert?(!equal(m.advertCopy,candidate.advertCopy)||
      !Number.isSafeInteger(candidate.width)||!Number.isSafeInteger(candidate.height)||
      candidate.width<1||candidate.height<1||candidate.width*candidate.height>17000000||
      m.width!==candidate.width||m.height!==candidate.height||m.frameFit!=='original'||
      m.layout?.layout!=='logo-only'||m.logoIncluded!==true):
      (m.width!==1080||m.height!==frameHeights[frame]||m.frameFit!=='contain'))||typeof m.logoIncluded!=='boolean'||
    !Number.isInteger(m.previewBytes)||m.previewBytes<8||m.previewBytes>10*1024*1024||
    !/^[a-f0-9]{64}$/.test(m.previewSha256)||typeof result.previewBase64!=='string'||
    result.previewBase64.length!==4*Math.ceil(m.previewBytes/3)||!/^[A-Za-z0-9+/]*={0,2}$/.test(result.previewBase64))fail();
  const bytes=Uint8Array.from(atob(result.previewBase64),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==m.previewBytes||hash!==m.previewSha256||![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))fail();
  const library=await request('/media');
  if(!active())return null;
  const assignment=library.selection?.postAssignments?.find(a=>a.day===candidate.day);
  const logoId=assignment?.staticLogoAssetId||'';
  if(m.logoIncluded!==Boolean(logoId))fail();
  if(logoId){
    const asset=library.assets?.find(a=>a.assetId===logoId);
    const note=library.selection.reviewNotes?.find(n=>n.day===candidate.day&&n.assetId===logoId);
    const logo=m.logoCandidate;
    if(library.revision!==record.revision||library.selection.stale||!asset||asset.permissionWithdrawn||
      asset.consentStatus!=='owner_asserted'||!note||note.stale||note.outcome!=='usable_candidate'||!holds(logo)||
      logo.assetId!==logoId||logo.sourceSha256!==asset.sourceSha256||logo.previewSha256!==note.previewSha256||
      logo.observationSha256!==note.observationSha256||assignment.photoCrops?.some(c=>c.assetId===logoId)||
      !equal(logo.candidateEdit,{assetId:logoId,wholeOriginal:true}))fail();
  }else if(m.logoCandidate)fail();
  const current=await request('');
  if(!active())return null;
  if(current.id!==record.id||current.revision!==record.revision||!equal(current.document,record.document))fail();
  return {manifest:m,blob:new Blob([bytes],{type:'image/png'}),artworkReview:result.artworkReview};
}
