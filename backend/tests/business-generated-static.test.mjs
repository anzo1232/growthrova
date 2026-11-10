import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import * as images from '../src/lib/businessGeneratedStatic.mjs';
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});
test('native advert logo export binds original wording, dimensions and observed logo without redraw',async()=>{
 const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
 const candidate={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64),
  renderingMode:'complete_advert',width:1792,height:2400,
  advertCopy:{businessName:'Workshop',headline:'Original designed headline',supportingLine:'Bicycle servicing at our workshop.',callToAction:'Original CTA'}};
 const post={day:1,copyDraft:'Full caption stays separate.',graphicText:'Later post words',callToAction:'Later CTA'};
 const record={id:'c'.repeat(32),revision:2,document:{posts:[post],brandKit:{name:'Workshop'}}};
 const safety={requiresIndependentQC:true,requiresOwnerApproval:true,approved:false,canPublish:false,canSpend:false,hostedStorageVerified:false};
 const logo={...safety,assetId:'logo',sourceSha256:'d'.repeat(64),previewSha256:'e'.repeat(64),observationSha256:'f'.repeat(64),candidateEdit:{assetId:'logo',wholeOriginal:true}};
 const library={revision:2,assets:[{assetId:'logo',consentStatus:'owner_asserted',sourceSha256:logo.sourceSha256}],
  selection:{postAssignments:[{day:1,staticLogoAssetId:'logo'}],reviewNotes:[{day:1,assetId:'logo',outcome:'usable_candidate',previewSha256:logo.previewSha256,observationSha256:logo.observationSha256}]}};
 const manifest={...safety,schemaVersion:1,purpose:'unapproved_generated_static_post',origin:'generated',draftId:record.id,
  operationId:candidate.operationId,day:1,revision:2,backgroundSha256:candidate.sha256,post,brandKit:record.document.brandKit,
  advertCopy:structuredClone(candidate.advertCopy),
  layout:{copy:candidate.advertCopy.headline,callToAction:candidate.advertCopy.callToAction,layout:'logo-only'},
  width:1792,height:2400,frameFit:'original',logoIncluded:true,logoCandidate:logo,previewBytes:bytes.length,
  previewSha256:createHash('sha256').update(bytes).digest('hex')};
 const response={manifest,previewBase64:bytes.toString('base64')};
 const paths=[];
 const request=async path=>{paths.push(path);return path.includes('static-preview')?response:path==='/media'?library:record;};
 assert.ok(await images.loadGeneratedStatic(record,candidate,request,()=>true,'original'));
 assert.match(paths[0],/&frame=original$/);
 // The logo compositor retains original words even when the current post has
 // changed. A matching headline/CTA alone cannot bind the supporting claim.
 for(const mutate of [m=>delete m.advertCopy,
  m=>m.advertCopy.supportingLine='Guaranteed results in one day.',
  m=>m.advertCopy.businessName='Another business',
  m=>m.advertCopy.headline=post.graphicText,
  m=>m.advertCopy.callToAction=post.callToAction]){
  const bad=structuredClone(response);mutate(bad.manifest);
  await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,
   async path=>path.includes('static-preview')?bad:request(path),()=>true,'original'),
   'Retained advert wording must match the exact selected candidate');
 }
 // A logo-only export preserves a document without optional brand settings;
 // Python serialises that missing brand as null, rather than omitting the key.
 const savedBrand=record.document.brandKit;
 delete record.document.brandKit;manifest.brandKit=null;
 assert.ok(await images.loadGeneratedStatic(record,candidate,request,()=>true,'original'));
 manifest.brandKit=savedBrand;
 await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,request,()=>true,'original'),
  'An unexpected brand must still be rejected');
 record.document.brandKit=savedBrand;
 for(const mutate of [()=>manifest.width=1080,()=>manifest.layout.copy=post.graphicText,
  ()=>manifest.logoIncluded=false,()=>library.assets[0].permissionWithdrawn=true]){
  const before=structuredClone({manifest,library});mutate();
  await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,request,()=>true,'original'));
  Object.assign(manifest,before.manifest);Object.assign(library,before.library);
 }
 const before=paths.length;
 await assert.rejects(()=>images.loadGeneratedStatic(record,{...candidate,renderingMode:'background'},request,()=>true,'original'));
 assert.equal(paths.length,before,'An original-frame export is never a background-template request');
});
test('generated static inspection binds saved copy, candidate, bytes and current revision',async()=>{
 const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
 const candidate={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64),conceptBinding:{planOperationId:'d'.repeat(32),concept:{id:'concept-1',headline:'Bicycle servicing'}}};
 const post={day:1,copyDraft:'Complete retained caption.',graphicText:'Bicycle servicing',callToAction:'Contact us'};
 const record={id:'c'.repeat(32),revision:2,document:{posts:[post],brandKit:{name:'Workshop'}}};
 const manifest={schemaVersion:1,purpose:'unapproved_generated_static_post',origin:'generated',draftId:record.id,
  operationId:candidate.operationId,day:1,revision:2,backgroundSha256:candidate.sha256,post,brandKit:record.document.brandKit,
  layout:{copy:post.graphicText,callToAction:post.callToAction},width:1080,height:1350,frameFit:'contain',
  conceptBinding:candidate.conceptBinding,logoIncluded:false,logoCandidate:null,requiresIndependentQC:true,requiresOwnerApproval:true,
  approved:false,canPublish:false,canSpend:false,hostedStorageVerified:false,previewBytes:bytes.length,
  previewSha256:createHash('sha256').update(bytes).digest('hex')};
 const envelope={manifest,previewBase64:bytes.toString('base64')};
 const calls=[];
 const request=async p=>{calls.push(p);return p.includes('static-preview')?envelope:p==='/media'?{selection:{postAssignments:[]}}:record;};
 const output=await images.loadGeneratedStatic(record,candidate,request);
 assert.deepEqual(Buffer.from(await output.blob.arrayBuffer()),bytes);
 assert.ok(calls.includes('/images/'+candidate.operationId+'/static-preview?revision=2'));
 const reordered=structuredClone(envelope);
 reordered.manifest.post=Object.fromEntries(Object.entries(post).reverse());
 assert.ok(await images.loadGeneratedStatic(record,candidate,async p=>p.includes('static-preview')?reordered:request(p)),
  'JSON key order is not an owner edit');
 for(const mutate of [m=>m.post.graphicText='Other text',m=>m.brandKit.name='Other brand',m=>m.backgroundSha256='f'.repeat(64),
  m=>m.approved=true,m=>m.origin='genuine',m=>m.previewSha256='f'.repeat(64),m=>m.layout.copy='Wrong rendered words',
  m=>m.logoIncluded=true,m=>m.conceptBinding.concept.headline='Foreign concept']){
  const bad=structuredClone(envelope);mutate(bad.manifest);
  await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,async p=>p.includes('static-preview')?bad:request(p)));
 }
 await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,async p=>p===''?{...record,revision:3}:request(p)));
 assert.equal(await images.loadGeneratedStatic(record,candidate,()=>{throw Error('Cancelled');},()=>false),null);
});

test('square export requests and validates the chosen frame without image inference',async()=>{
 const candidate={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64)};
 const post={day:1,copyDraft:'A complete caption.',graphicText:'Bicycle servicing',callToAction:'Contact us'};
 const record={id:'c'.repeat(32),revision:2,document:{posts:[post],brandKit:{name:'Workshop'}}};
 const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
 const manifest={schemaVersion:1,purpose:'unapproved_generated_static_post',origin:'generated',draftId:record.id,
  operationId:candidate.operationId,day:1,revision:2,backgroundSha256:candidate.sha256,post,brandKit:record.document.brandKit,
  layout:{copy:post.graphicText,callToAction:post.callToAction},width:1080,height:1080,frameFit:'contain',
  logoIncluded:false,logoCandidate:null,requiresIndependentQC:true,requiresOwnerApproval:true,approved:false,
  canPublish:false,canSpend:false,hostedStorageVerified:false,previewBytes:bytes.length,
  previewSha256:createHash('sha256').update(bytes).digest('hex')};
 const paths=[];
 const request=async path=>{paths.push(path);return path.includes('static-preview')?{manifest,previewBase64:bytes.toString('base64')}:path==='/media'?{selection:{postAssignments:[]}}:record;};
 assert.ok(await images.loadGeneratedStatic(record,candidate,request,()=>true,'square'));
 assert.equal(paths[0],'/images/'+candidate.operationId+'/static-preview?revision=2&frame=square');
 assert.equal(paths.length,3);
 manifest.height=1350;
 await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,request,()=>true,'square'));
 const count=paths.length;
 await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,request,()=>true,'landscape'));
 assert.equal(paths.length,count,'Unsupported frame fails before network requests');
});

test('story export validates 9:16 pixels and never accepts a portrait response',async()=>{
 const candidate={operationId:'a'.repeat(32),day:1,origin:'generated',state:'proposed',sha256:'b'.repeat(64)};
 const post={day:1,copyDraft:'A complete caption.',graphicText:'Bicycle servicing',callToAction:'Contact us'};
 const record={id:'c'.repeat(32),revision:2,document:{posts:[post],brandKit:{name:'Workshop'}}};
 const bytes=Buffer.from([137,80,78,71,13,10,26,10,0]);
 const manifest={schemaVersion:1,purpose:'unapproved_generated_static_post',origin:'generated',draftId:record.id,
  operationId:candidate.operationId,day:1,revision:2,backgroundSha256:candidate.sha256,post,brandKit:record.document.brandKit,
  layout:{copy:post.graphicText,callToAction:post.callToAction},width:1080,height:1920,frameFit:'contain',
  logoIncluded:false,logoCandidate:null,requiresIndependentQC:true,requiresOwnerApproval:true,approved:false,
  canPublish:false,canSpend:false,hostedStorageVerified:false,previewBytes:bytes.length,
  previewSha256:createHash('sha256').update(bytes).digest('hex')};
 const paths=[];
 const request=async path=>{paths.push(path);return path.includes('static-preview')?{manifest,previewBase64:bytes.toString('base64')}:path==='/media'?{selection:{postAssignments:[]}}:record;};
 assert.ok(await images.loadGeneratedStatic(record,candidate,request,()=>true,'story'));
 assert.equal(paths[0],'/images/'+candidate.operationId+'/static-preview?revision=2&frame=story');
 assert.equal(paths.length,3);
 manifest.height=1350;
 await assert.rejects(()=>images.loadGeneratedStatic(record,candidate,request,()=>true,'story'));
});
