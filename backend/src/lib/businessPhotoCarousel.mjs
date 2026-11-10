import {requireCurrentPostContext} from './businessOriginalReview.mjs';

const limit=20*1024*1024;
function fail(){throw Error('Carousel changed or is held. Reload saved photos, words and observations before preparing it again.');}
async function bytesOf(encoded, size, sha, maximum){
  if(!Number.isSafeInteger(size)||size<8||size>maximum||!/^[a-f0-9]{64}$/.test(sha)||
    typeof encoded!=='string'||encoded.length!==4*Math.ceil(size/3)||!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded))fail();
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(bytes.length!==size||hash!==sha)fail();
  return bytes;
}

export async function loadPhotoCarousel(library,day,request,active=()=>true,previous=null){
  const selection=library?.selection,a=selection?.postAssignments?.find(a=>a.day===day);
  const ids=a?.assetIds.filter(id=>id!==a.staticLogoAssetId)||[];
  if(!a||selection.stale||ids.length<2||ids.length>5)fail();
  const query=new URLSearchParams({revision:library.revision,selectionVersion:selection.selectionVersion,reviewVersion:selection.reviewVersion});
  if(previous)query.set('package','1');
  if(!active())return null;
  const result=await request('/posts/'+day+'/carousel-preview?'+query);
  if(!active())return null;
  const m=result?.manifest;
  if(!m||m.schemaVersion!==1||m.purpose!=='unapproved_photo_carousel'||m.day!==day||
    m.revision!==library.revision||m.selectionVersion!==selection.selectionVersion||m.reviewVersion!==selection.reviewVersion||
    m.approved!==false||m.canSpend!==false||m.canPublish!==false||m.hostedStorageVerified!==false||
    m.requiresIndependentQC!==true||m.requiresOwnerApproval!==true||m.width!==1080||m.height!==1350||
    m.logoIncluded!==Boolean(a.staticLogoAssetId)||
    JSON.stringify(m.post)!==JSON.stringify(library.posts.find(p=>p.day===day))||
    JSON.stringify(m.brandKit)!==JSON.stringify(library.brandKit)||!Array.isArray(m.slides)||m.slides.length!==ids.length)fail();
  const captions=a.carouselCaptions||{},returned=m.channelCaptions||{};
  if(Object.keys(captions).length!==Object.keys(returned).length||
     Object.entries(captions).some(([channel,text])=>returned[channel]!==text))fail();
  let total=0;
  for(const [i,id] of ids.entries()){
    const slide=m.slides[i],words=a.carouselSlides?.find(s=>s.assetId===id);
    const asset=library.assets.find(a=>a.assetId===id),note=selection.reviewNotes.find(n=>n.day===day&&n.assetId===id);
    if(!slide||!words||!asset||asset.mediaKind!=='photo'||asset.permissionWithdrawn||asset.consentStatus!=='owner_asserted'||
      !note||note.stale||note.outcome!=='usable_candidate'||slide.assetId!==id||slide.file!==`slide-${String(i+1).padStart(2,'0')}.png`||
      slide.graphicText!==words.graphicText||slide.callToAction!==words.callToAction||
      slide.candidate?.sourceSha256!==asset.sourceSha256||slide.candidate?.previewSha256!==note.previewSha256||
      slide.candidate?.observationSha256!==note.observationSha256||
      slide.layout?.copy!==words.graphicText.trim()||slide.layout?.callToAction!==words.callToAction||
      !Number.isSafeInteger(slide.bytes)||slide.bytes<8||!/^[a-f0-9]{64}$/.test(slide.sha256))fail();
    total+=slide.bytes;
  }
  if(total>limit)fail();
  let packageBlob=null;const slides=[];
  if(previous){
    if(JSON.stringify(m)!==JSON.stringify(previous))fail();
    const bytes=await bytesOf(result.packageBase64,result.packageBytes,result.packageSha256,limit+128*1024);
    if(bytes[0]!==80||bytes[1]!==75||bytes[2]!==3||bytes[3]!==4)fail();
    packageBlob=new Blob([bytes],{type:'application/zip'});
  }else{
    if(!Array.isArray(result.slidesBase64)||result.slidesBase64.length!==ids.length)fail();
    for(const [i,s] of m.slides.entries()){
      if(!active())return null;
      const bytes=await bytesOf(result.slidesBase64[i],s.bytes,s.sha256,limit);
      if(![137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v))fail();
      slides.push({blob:new Blob([bytes],{type:'image/png'}),file:s.file});
    }
  }
  if(!active())return null;
  const current=await request('');
  if(!active())return null;
  requireCurrentPostContext(library,day,current);
  if(JSON.stringify(current.brandKit)!==JSON.stringify(library.brandKit))fail();
  return {manifest:m,slides,packageBlob,packageSha256:result.packageSha256};
}
