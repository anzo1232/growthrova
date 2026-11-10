import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto,createHash} from 'node:crypto';
import * as review from '../src/lib/businessOriginalReview.mjs';
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});

test('static download checks saved words, brand, exact observed source and final context',async()=>{
 const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
 const asset={assetId:'photo',mediaKind:'photo',sourceSha256:'a'.repeat(64),consentStatus:'owner_asserted'};
 const note={day:1,assetId:'photo',outcome:'usable_candidate',observationSha256:'b'.repeat(64),previewSha256:asset.sourceSha256};
 const post={day:1,copyDraft:'A complete post. '.repeat(100),graphicText:'Bicycle servicing at our workshop.',callToAction:'Explore the workshop'};
 const brandKit={name:'Workshop',primary_color:'#123456',secondary_color:'#FFFFFF',font_style:'modern'};
 const library={revision:1,posts:[post],brandKit,assets:[asset],hostedStorageVerified:false,canSpend:false,canPublish:false,
  selection:{stale:false,selectionVersion:1,reviewVersion:1,postAssignments:[{day:1,assetIds:['photo']}],reviewNotes:[note]}};
 const holds={approved:false,canSpend:false,canPublish:false,hostedStorageVerified:false,requiresIndependentQC:true,requiresOwnerApproval:true};
 const candidate={...holds,assetId:'photo',sourceSha256:asset.sourceSha256,previewSha256:note.previewSha256,
  observationSha256:note.observationSha256,candidateEdit:{assetId:'photo',wholeOriginal:true}};
 const manifest={...holds,schemaVersion:1,purpose:'unapproved_static_post',day:1,revision:1,selectionVersion:1,reviewVersion:1,
  post,brandKit,layout:{copy:post.graphicText,callToAction:post.callToAction},candidates:[candidate],width:1080,height:1350,frameFit:'contain',logoIncluded:false,
  previewBytes:bytes.length,previewSha256:createHash('sha256').update(bytes).digest('hex')};
 const result={manifest,previewBase64:bytes.toString('base64')};
 const paths=[];
 const loaded=await review.loadSavedStaticPost(library,1,async p=>{paths.push(p);return p?result:library;});
 assert.equal(loaded.blob.type,'image/png');
 assert.deepEqual(Buffer.from(await loaded.blob.arrayBuffer()),bytes);
 assert.deepEqual(paths,['/posts/1/static-preview?revision=1&selectionVersion=1&reviewVersion=1','']);
 for(const change of [m=>m.brandKit.name='Changed',m=>m.post.copyDraft='Other words',m=>m.approved=true,
  m=>m.candidates[0].sourceSha256='f'.repeat(64),m=>m.candidates[0].candidateEdit.left=3,
  m=>m.layout.copy='Different rendered words',m=>m.layout.callToAction='A different action',m=>m.logoIncluded=true,m=>m.previewSha256='f'.repeat(64)]){
  const changed=structuredClone(result);change(changed.manifest);
  await assert.rejects(()=>review.loadSavedStaticPost(library,1,async p=>p?changed:library));
 }
 const changed=structuredClone(library);changed.brandKit.name='New brand';
 await assert.rejects(()=>review.loadSavedStaticPost(library,1,async p=>p?result:changed));
 changed.brandKit=library.brandKit;changed.assets[0].permissionWithdrawn=true;
 await assert.rejects(()=>review.loadSavedStaticPost(library,1,async p=>p?result:changed));
 assert.equal(await review.loadSavedStaticPost(library,1,()=>{throw Error('No cancelled request');},()=>false),null);
 const withLogo=structuredClone(library);
 const logo={...asset,assetId:'logo',sourceSha256:'c'.repeat(64)};
 const logoNote={...note,assetId:'logo',previewSha256:logo.sourceSha256};
 withLogo.assets.push(logo);withLogo.selection.postAssignments[0].assetIds.push('logo');
 withLogo.selection.postAssignments[0].staticLogoAssetId='logo';withLogo.selection.reviewNotes.push(logoNote);
 const logoResult=structuredClone(result);
 Object.assign(logoResult.manifest,{logoIncluded:true,logoCandidate:{...candidate,assetId:'logo',
  sourceSha256:logo.sourceSha256,previewSha256:logoNote.previewSha256,candidateEdit:{assetId:'logo',wholeOriginal:true}}});
 const logoLoaded=await review.loadSavedStaticPost(withLogo,1,async p=>p?logoResult:withLogo);
 assert.equal(logoLoaded.blob.type,'image/png');
 for(const mutate of [m=>m.logoCandidate.sourceSha256='f'.repeat(64),m=>m.logoCandidate.approved=true,
  m=>m.logoCandidate.candidateEdit={assetId:'logo',left:0},m=>delete m.logoCandidate]){
  const bad=structuredClone(logoResult);mutate(bad.manifest);
  await assert.rejects(()=>review.loadSavedStaticPost(withLogo,1,async p=>p?bad:withLogo));
 }
 const removed=structuredClone(withLogo);removed.selection.postAssignments[0].staticLogoAssetId='';
 await assert.rejects(()=>review.loadSavedStaticPost(withLogo,1,async p=>p?logoResult:removed));
 assert.equal(review.postMediaChangesPending(withLogo.selection.postAssignments[0],['photo','logo'],[],[],''),true);
 assert.equal(review.postMediaChangesPending(withLogo.selection.postAssignments[0],['photo','logo'],[],[],'logo'),false);
});
