import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash,webcrypto} from 'node:crypto';
import {movePostMedia,postMediaChangesPending,originalReviewBlob,originalThumbnailBlob,verifyOriginalIntake} from '../src/lib/businessOriginalReview.mjs';
if(!globalThis.crypto)Object.defineProperty(globalThis,'crypto',{value:webcrypto});

test('saved post review loads ordered exact originals, rechecks context and stops cancelled work',async()=>{
  const {loadSavedPostReview}=await import('../src/lib/businessOriginalReview.mjs');
  const bytes=Buffer.from('owned fixture original');
  const asset={assetId:'photo',mediaKind:'photo',mimeType:'image/png',sourceBytes:bytes.length,
    sourceSha256:createHash('sha256').update(bytes).digest('hex'),consentStatus:'owner_asserted'};
  const library={assets:[asset],posts:[{day:1,copyDraft:'Saved post copy'}],revision:1,
    hostedStorageVerified:false,canSpend:false,canPublish:false,
    selection:{stale:false,selectionVersion:2,reviewVersion:0,
      postAssignments:[{day:1,assetIds:['photo']}],reviewNotes:[]}};
  const response={...asset,asset,day:1,revision:1,selectionVersion:2,wholeOriginal:true,
    previewSha256:asset.sourceSha256,originalBase64:bytes.toString('base64'),reviewReceipt:'signed-receipt',
    approved:false,canSpend:false,canPublish:false};
  const paths=[];
  const result=await loadSavedPostReview(library,1,async path=>{paths.push(path);return path?response:library;});
  assert.deepEqual(paths,['/posts/1/photo/original-review?revision=1&selectionVersion=2','']);
  assert.deepEqual(Buffer.from(await result.candidates[0].blob.arrayBuffer()),bytes);
  assert.equal(result.post.copyDraft,'Saved post copy');
  assert.equal(result.candidates[0].observation,undefined);
  for(const mutate of [l=>l.revision++,l=>l.selection.selectionVersion++,l=>l.selection.reviewVersion++,
    l=>l.selection.stale=true,l=>l.assets[0].permissionWithdrawn=true,
    l=>l.assets[0].consentStatus='not_confirmed',l=>l.assets[0].sourceSha256='f'.repeat(64),
    l=>l.selection.postAssignments=[],l=>l.posts[0].copyDraft='Changed copy',l=>l.canPublish=true]) {
    const changed=structuredClone(library);mutate(changed);
    await assert.rejects(()=>loadSavedPostReview(library,1,async path=>path?response:changed));
  }
  await assert.rejects(()=>loadSavedPostReview(library,1,async()=>({...response,selectionVersion:3})));
  let active=true,count=0;
  assert.equal(await loadSavedPostReview(library,1,async()=>{count++;active=false;return response;},()=>active),null);
  assert.equal(count,1);
  assert.equal(await loadSavedPostReview(library,1,async()=>{throw Error('must not request');},()=>false),null);
  for(const patch of [{stale:true},{postAssignments:[{day:1,assetIds:['photo','photo']}]},
    {postAssignments:[{day:1,assetIds:[]}]}]) {
    await assert.rejects(()=>loadSavedPostReview({...library,selection:{...library.selection,...patch}},1,
      async()=>{throw Error('must not request');}),/Saved post changed/);
  }
});

test('saved post review holds an oversized combined set and never returns partial media',async()=>{
  const {loadSavedPostReview}=await import('../src/lib/businessOriginalReview.mjs');
  const bytes=Buffer.from('owned small fixture'),encoded=bytes.toString('base64');
  const hash=createHash('sha256').update(bytes).digest('hex');
  const assets=['first','second','third'].map(assetId=>({assetId,mediaKind:'photo',mimeType:'image/png',
    sourceBytes:9*1024*1024,sourceSha256:hash,consentStatus:'owner_asserted'}));
  const library={assets,posts:[{day:1}],revision:1,hostedStorageVerified:false,canSpend:false,canPublish:false,
    selection:{stale:false,selectionVersion:1,reviewVersion:0,postAssignments:[{day:1,assetIds:assets.map(a=>a.assetId)}]}};
  let count=0;
  await assert.rejects(()=>loadSavedPostReview(library,1,async()=>{
    count++;throw Error('Oversized originals must be held before transfer');
  }),/exceeds 25 MB/);
  assert.equal(count,0);
  assets.forEach(asset=>{asset.sourceBytes=bytes.length;});
  await assert.rejects(()=>loadSavedPostReview(library,1,async()=>{
    if(++count===2)throw Error('Second candidate unavailable');
    const asset=assets[0];
    return {asset,...asset,day:1,revision:1,selectionVersion:1,wholeOriginal:true,
      previewSha256:hash,originalBase64:encoded,reviewReceipt:'signed-receipt',approved:false,canSpend:false,canPublish:false};
  }),/Second candidate unavailable/);
});

test('post sequencing preserves per-source edits and detects unsaved review context',()=>{
  const ids=['product','demo','portrait'],crop={assetId:'product',left:0,top:0,width:24,height:20};
  const edit={assetId:'demo',startMs:0,endMs:500,muted:true};
  const saved={assetIds:ids,photoCrops:[crop],videoEdits:[edit]};
  const next=movePostMedia(ids,'portrait',-1);
  assert.deepEqual(next,['product','portrait','demo']);
  assert.deepEqual(ids,['product','demo','portrait']);
  assert.equal(postMediaChangesPending(saved,next,[crop],[edit]),true);
  assert.equal(postMediaChangesPending(saved,movePostMedia(next,'portrait',1),[crop],[edit]),false);
  assert.equal(postMediaChangesPending(saved,ids,[{height:20,width:24,top:0,left:0,assetId:'product'}],[edit]),false);
  assert.equal(postMediaChangesPending(saved,ids,[crop],[{...edit,muted:false}]),true);
  assert.equal(postMediaChangesPending(saved,ids,[],[edit]),true);
  assert.equal(postMediaChangesPending(saved,ids.slice(1),[crop],[edit]),true);
  assert.equal(postMediaChangesPending(undefined,[],[],[]),false);
  assert.deepEqual(movePostMedia(ids,'product',-1),ids);
  assert.deepEqual(movePostMedia(ids,'portrait',1),ids);
  for(const args of [[ids,'foreign',1],[ids,'demo',2],[['a','a'],'a',1],
    [['a','b','c','d','e','f'],'a',1],[null,'a',1]])assert.throws(()=>movePostMedia(...args));
});

test('library thumbnails bind exact source, coverage, permission, PNG bytes and dimensions',async()=>{
  const bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZQAAAABJRU5ErkJggg==','base64');
  const expected={assetId:'owned-photo',sourceSha256:'a'.repeat(64),mediaKind:'photo',consentStatus:'not_confirmed',permissionWithdrawn:false};
  const result={...expected,previewSha256:createHash('sha256').update(bytes).digest('hex'),
    previewBase64:bytes.toString('base64'),width:1,height:1,mimeType:'image/png',
    coverage:'whole_photo_scaled',approved:false,canSpend:false,canPublish:false,
    storage:'offline_original_bytes',hostedStorageVerified:false};
  assert.equal((await originalThumbnailBlob(result,expected)).type,'image/png');
  for(const patch of [{assetId:'foreign'},{sourceSha256:'b'.repeat(64)},{mediaKind:'video'},
    {coverage:'full_video'},{consentStatus:'owner_asserted'},{permissionWithdrawn:true},
    {approved:true},{canSpend:true},{canPublish:true},{hostedStorageVerified:true},
    {mimeType:'text/html'},{width:321},{height:2},{previewBase64:'!!!!'},
    {previewSha256:'f'.repeat(64)}])await assert.rejects(()=>originalThumbnailBlob({...result,...patch},expected));
  await assert.rejects(()=>originalThumbnailBlob(result,{...expected,permissionWithdrawn:true}));
  const video={...expected,mediaKind:'video'};
  assert.equal((await originalThumbnailBlob({...result,...video,coverage:'first_frame_only'},video)).type,'image/png');
  await assert.rejects(()=>originalThumbnailBlob({...result,...video},video));
});

test('intake recovery accepts only the exact ordered receipt and retains all authority holds',()=>{
  const id='c'.repeat(32),rights=' Authored media with permission for marketing. ';
  const originals=[{sourceSha256:'a'.repeat(64),sourceBytes:80,mimeType:'image/png',originalName:'product.png'},
    {sourceSha256:'b'.repeat(64),sourceBytes:150,mimeType:'video/mp4',originalName:'studio.mp4'}];
  const assets=originals.map((x,i)=>({...x,assetId:'original-'+i,rightsStatement:rights,
    consentStatus:'owner_asserted',canSpend:false,canPublish:false,generationApproved:false,
    verifiedRights:false,authenticityVerified:false}));
  const result={intakeId:id,replayed:true,assets,storage:'offline_original_bytes',hostedStorageVerified:false};
  const verify=r=>verifyOriginalIntake(r,id,originals,rights,'owner_asserted');
  assert.equal(verify(result),assets);
  assert.equal(verify({...result,replayed:false}),assets);
  for(const patch of [{intakeId:'d'.repeat(32)},{replayed:undefined},{assets:assets.slice(0,1)},
    {assets:[...assets].reverse()},{assets:[assets[0],assets[0]]},{assets:[null,assets[1]]},
    {hostedStorageVerified:true},{storage:'hosted'}])assert.throws(()=>verify({...result,...patch}));
  for(const patch of [{sourceSha256:'f'.repeat(64)},{sourceBytes:81},{mimeType:'image/jpeg'},
    {originalName:'different.png'},{rightsStatement:rights.trim()},{consentStatus:'not_confirmed'},
    {canSpend:true},{canPublish:true},{generationApproved:true},{verifiedRights:true},{authenticityVerified:true}]){
    assert.throws(()=>verify({...result,assets:[{...assets[0],...patch},assets[1]]}));
  }
});

// Authored bytes exercise integrity/transport; decoder coverage lives in the
// real-byte Python intake tests. These are not visual-quality fixtures.
function envelope(bytes=Buffer.from('original fixture'),mimeType='image/png',mediaKind='photo') {
  const asset={assetId:'owned-original',sourceBytes:bytes.length,
    sourceSha256:createHash('sha256').update(bytes).digest('hex'),mimeType,mediaKind};
  return {asset,originalBase64:bytes.toString('base64')};
}
test('saved photo and video originals become typed blobs only after byte/hash checks',async()=>{
  for(const [mime,kind] of [['image/png','photo'],['video/mp4','video']]) {
    const result=envelope(undefined,mime,kind);
    const blob=await originalReviewBlob(result,result.asset);
    assert.equal(blob.type,mime);
    assert.deepEqual(Buffer.from(await blob.arrayBuffer()),Buffer.from('original fixture'));
  }
});
test('substituted identity, metadata, bytes and executable content hold preview',async()=>{
  const good=envelope();
  for(const result of [null,{}, {...good,asset:{...good.asset,assetId:'other'}},
    {...good,asset:{...good.asset,sourceSha256:'a'.repeat(64)}},
    {...good,asset:{...good.asset,sourceBytes:99}},
    {...good,asset:{...good.asset,mimeType:'text/html'}},
    {...good,asset:{...good.asset,mediaKind:'logo'}},
    {...good,originalBase64:Buffer.from('substitute bytes').toString('base64')},
    {...good,originalBase64:'!!!!'}, {...good,originalBase64:'https://invalid.example/file'}]) {
    await assert.rejects(()=>originalReviewBlob(result,good.asset));
  }
});
test('one bounded ten megabyte original is supported without unbounded decode',async()=>{
  const large=envelope(Buffer.alloc(10*1024*1024,42));
  assert.equal((await originalReviewBlob(large,large.asset)).size,10*1024*1024);
  const oversized={...large,asset:{...large.asset,sourceBytes:10*1024*1024+1}};
  await assert.rejects(()=>originalReviewBlob(oversized,oversized.asset));
});

test('whole original review binds exact bytes to saved day and selection without edits',async()=>{
  const {wholeOriginalReviewBlob}=await import('../src/lib/businessOriginalReview.mjs');
  for(const [mime,kind] of [['image/png','photo'],['video/mp4','video']]) {
    const original=envelope(undefined,mime,kind);
    const expected={...original.asset,day:9,revision:1,selectionVersion:2};
    const result={...original,...expected,wholeOriginal:true,previewSha256:expected.sourceSha256,
      reviewReceipt:'signed-whole-original',approved:false,canSpend:false,canPublish:false};
    assert.deepEqual(Buffer.from(await (await wholeOriginalReviewBlob(result,expected)).arrayBuffer()),Buffer.from('original fixture'));
    for(const patch of [{day:1},{revision:2},{selectionVersion:3},{wholeOriginal:false},
      {previewSha256:'f'.repeat(64)},{reviewReceipt:''},{canSpend:true},{canPublish:true},{approved:true},
      {originalBase64:Buffer.from('substituted').toString('base64')},
      {asset:{...original.asset,assetId:'other'}}]) {
      await assert.rejects(()=>wholeOriginalReviewBlob({...result,...patch},expected));
    }
  }
});

test('rendered photo crops are bound to saved source, day, version, instructions and PNG pixels',async()=>{
  const {photoCropPreviewBlob}=await import('../src/lib/businessOriginalReview.mjs');
  // Tiny authored PNG header verifies envelope integrity, not decoder/visual quality.
  const bytes=Buffer.alloc(24);Buffer.from([137,80,78,71,13,10,26,10]).copy(bytes);
  bytes.writeUInt32BE(24,16);bytes.writeUInt32BE(20,20);
  const expected={assetId:'original',sourceSha256:'a'.repeat(64),day:1,revision:2,selectionVersion:3,
    crop:{assetId:'original',left:8,top:4,width:24,height:20}};
  const result={...expected,width:24,height:20,mimeType:'image/png',approved:false,canSpend:false,canPublish:false,
    previewSha256:createHash('sha256').update(bytes).digest('hex'),previewBase64:bytes.toString('base64')};
  const blob=await photoCropPreviewBlob(result,expected);
  assert.equal(blob.type,'image/png');assert.deepEqual(Buffer.from(await blob.arrayBuffer()),bytes);
  for(const patch of [{day:9},{revision:3},{selectionVersion:4},{assetId:'other'},
    {sourceSha256:'b'.repeat(64)},{crop:{...expected.crop,left:0}},
    {mimeType:'text/html'},{approved:true},{canPublish:true},{canSpend:true},
    {previewSha256:'f'.repeat(64)},{previewBase64:'https://invalid.example/file'},
    {width:25},{height:1201},{previewBase64:'A'.repeat(8*1024*1024+1)}]) {
    await assert.rejects(()=>photoCropPreviewBlob({...result,...patch},expected));
  }
});

test('rendered video review checks saved edit, audio, duration, bounded MP4 bytes and hash',async()=>{
  const {videoExcerptPreviewBlob}=await import('../src/lib/businessOriginalReview.mjs');
  const bytes=Buffer.from('0000ftypisomfixture');
  const expected={assetId:'original',sourceSha256:'a'.repeat(64),day:1,revision:2,selectionVersion:3,
    edit:{assetId:'original',startMs:500,endMs:1000,muted:true}};
  const result={...expected,mimeType:'video/mp4',previewBytes:bytes.length,durationMs:500,hasAudio:false,
    approved:false,canSpend:false,canPublish:false,
    previewSha256:createHash('sha256').update(bytes).digest('hex'),previewBase64:bytes.toString('base64')};
  assert.deepEqual(Buffer.from(await (await videoExcerptPreviewBlob(result,expected)).arrayBuffer()),bytes);
  for(const patch of [{day:9},{revision:3},{selectionVersion:4},{assetId:'other'},
    {sourceSha256:'b'.repeat(64)},{edit:{...expected.edit,startMs:0}},
    {edit:{...expected.edit,muted:false}},{mimeType:'text/html'},{approved:true},{canPublish:true},
    {canSpend:true},{previewSha256:'f'.repeat(64)},{previewBytes:10*1024*1024+1},
    {previewBase64:'https://invalid.example/file'},{hasAudio:true},{durationMs:1000},
    {previewBase64:Buffer.alloc(bytes.length,42).toString('base64')}]) {
    await assert.rejects(()=>videoExcerptPreviewBlob({...result,...patch},expected));
  }
});

test('owner observation payload carries current versions and receipt without approval claims',async()=>{
  const {reviewNotePayload}=await import('../src/lib/businessOriginalReview.mjs');
  const context={revision:2,selectionVersion:3,receipt:'server-signed-preview'};
  const note='The product label is visible; remove unrelated foreground packaging.';
  assert.deepEqual(reviewNotePayload(context,4,'needs_changes','  '+note+'  '),
    {...context,reviewVersion:4,outcome:'needs_changes',note});
  for(const args of [[null,4,'needs_changes',note],[{...context,receipt:''},4,'needs_changes',note],
    [{...context,revision:true},4,'needs_changes',note],[context,true,'needs_changes',note],
    [context,4,'approved',note],[context,4,'usable_candidate','pass'],
    [context,4,'unsuitable','x'.repeat(1001)]])assert.throws(()=>reviewNotePayload(...args));
});

test('targeted revision response carries exact prior observation and bounded change description',async()=>{
  const {reviewNotePayload}=await import('../src/lib/businessOriginalReview.mjs');
  const context={revision:2,selectionVersion:3,receipt:'signed-new-preview'};
  const response={observationSha256:'a'.repeat(64),changeSummary:'  Moved the crop edge inward to remove the background.  '};
  const payload=reviewNotePayload(context,4,'usable_candidate','The label remains visible in the revised saved crop.',response);
  assert.deepEqual(payload.revisionResponse,{...response,changeSummary:response.changeSummary.trim()});
  assert.equal(payload.outcome,'usable_candidate');assert.equal(payload.approved,undefined);
  for(const patch of [{observationSha256:'invented'},{changeSummary:'done'},
    {changeSummary:'x'.repeat(1001)},{changeSummary:true}]) {
    assert.throws(()=>reviewNotePayload(context,4,'needs_changes','The label needs a different crop before further review.',{...response,...patch}));
  }
});

test('QC package download binds saved observation and verifies bounded ZIP bytes with all approval holds',async()=>{
  const {reviewPackageBlob}=await import('../src/lib/businessOriginalReview.mjs');
  // Envelope fixture only; Python integration opens a real ZIP and checks rendered media.
  const bytes=Buffer.from([80,75,3,4,42,12,9,1]);
  const expected={assetId:'original',sourceSha256:'a'.repeat(64),day:9,revision:2,
    selectionVersion:3,reviewVersion:4,observationSha256:'b'.repeat(64),previewSha256:'c'.repeat(64)};
  const holds={approved:false,canSpend:false,canPublish:false,hostedStorageVerified:false};
  const manifest={...expected,...holds,schemaVersion:1,purpose:'independent_qc_review',
    requiresIndependentQC:true,requiresOwnerApproval:true};
  const good={...holds,manifest,packageBytes:bytes.length,packageBase64:bytes.toString('base64'),
    packageSha256:createHash('sha256').update(bytes).digest('hex')};
  const blob=await reviewPackageBlob(good,expected);
  assert.equal(blob.type,'application/zip');assert.deepEqual(Buffer.from(await blob.arrayBuffer()),bytes);
  for(const key of Object.keys(expected)) {
    await assert.rejects(()=>reviewPackageBlob({...good,manifest:{...manifest,[key]:'changed'}},expected));
  }
  for(const patch of [{requiresIndependentQC:false},{requiresOwnerApproval:false},{schemaVersion:2},
    {purpose:'approved_export'},{approved:true},{canSpend:true},{canPublish:true},{hostedStorageVerified:true}]) {
    await assert.rejects(()=>reviewPackageBlob({...good,manifest:{...manifest,...patch}},expected));
  }
  for(const patch of [{approved:true},{canSpend:true},{canPublish:true},{hostedStorageVerified:true},
    {packageBytes:11*1024*1024+1},{packageBytes:0},{packageBytes:true},
    {packageSha256:'f'.repeat(64)},{packageBase64:'https://invalid.example/file'},
    {packageBase64:Buffer.alloc(bytes.length,42).toString('base64')}]) {
    await assert.rejects(()=>reviewPackageBlob({...good,...patch},expected));
  }
});

test('full post QC package binds complete ordered candidate set, versions, holds and ZIP bytes',async()=>{
  const {postReviewPackageBlob}=await import('../src/lib/businessOriginalReview.mjs');
  const bytes=Buffer.from([80,75,3,4,42,12,9,1]);
  const expected={day:9,revision:2,selectionVersion:3,reviewVersion:4,candidates:[
    {assetId:'video',sourceSha256:'a'.repeat(64),observationSha256:'b'.repeat(64),previewSha256:'c'.repeat(64)},
    {assetId:'photo',sourceSha256:'d'.repeat(64),observationSha256:'e'.repeat(64),previewSha256:'f'.repeat(64)}]};
  const holds={approved:false,canSpend:false,canPublish:false,hostedStorageVerified:false,
    requiresIndependentQC:true,requiresOwnerApproval:true};
  const manifest={...expected,...holds,schemaVersion:1,purpose:'independent_post_qc_review',
    reviewPage:{file:'REVIEW.html',bytes:5000,sha256:'a'.repeat(64)},
    containsOriginalMetadata:true,candidates:expected.candidates.map((c,i)=>({...c,...holds,
      day:9,revision:2,selectionVersion:3,reviewVersion:4,schemaVersion:1,purpose:'independent_qc_review',
      containsOriginalMetadata:i===1,candidateFile:`media/0${i+1}/candidate.${i?'png':'mp4'}`}))};
  const good={...holds,manifest,packageBytes:bytes.length,packageBase64:bytes.toString('base64'),
    packageSha256:createHash('sha256').update(bytes).digest('hex')};
  assert.deepEqual(Buffer.from(await (await postReviewPackageBlob(good,expected)).arrayBuffer()),bytes);
  for(const patch of [{day:1},{revision:3},{selectionVersion:4},{reviewVersion:5},
    {approved:true},{canPublish:true},{requiresIndependentQC:false},{requiresOwnerApproval:false},
    {purpose:'approved_export'},{candidates:manifest.candidates.slice(1)},
    {candidates:[...manifest.candidates].reverse()}, {candidates:[...manifest.candidates,manifest.candidates[0]]},
    {containsOriginalMetadata:false},{reviewPage:null},
    {reviewPage:{file:'https://example.org/review',bytes:5000,sha256:'a'.repeat(64)}},
    {reviewPage:{file:'REVIEW.html',bytes:true,sha256:'a'.repeat(64)}},
    {reviewPage:{file:'REVIEW.html',bytes:5000,sha256:'bad'}}]) {
    await assert.rejects(()=>postReviewPackageBlob({...good,manifest:{...manifest,...patch}},expected));
  }
  for(const patch of [{assetId:'other'},{sourceSha256:'9'.repeat(64)},{observationSha256:'9'.repeat(64)},
    {previewSha256:'9'.repeat(64)},{selectionVersion:4},{approved:true},{canPublish:true},
    {requiresOwnerApproval:false},{candidateFile:'../../candidate.mp4'}, {candidateFile:'media/02/candidate.mp4'}]) {
    await assert.rejects(()=>postReviewPackageBlob({...good,manifest:{...manifest,
      candidates:[{...manifest.candidates[0],...patch},manifest.candidates[1]]}},expected));
  }
  for(const patch of [{approved:true},{canPublish:true},{canSpend:true},{hostedStorageVerified:true},
    {packageBytes:25*1024*1024+1},{packageBytes:0},{packageSha256:'f'.repeat(64)},
    {packageBase64:'!!!!'},{packageBase64:Buffer.alloc(bytes.length,42).toString('base64')}]) {
    await assert.rejects(()=>postReviewPackageBlob({...good,...patch},expected));
  }
});

test('silent composition validates exact context, timeline, bytes, holds and final permission',async()=>{
  const {loadSavedPostComposition}=await import('../src/lib/businessOriginalReview.mjs');
  const bytes=Buffer.from([0,0,0,16,102,116,121,112,105,115,111,109,0,0,0,0]);
  const hash=createHash('sha256').update(bytes).digest('hex');
  const asset={assetId:'photo',mediaKind:'photo',sourceSha256:'a'.repeat(64),consentStatus:'owner_asserted'};
  const note={day:1,assetId:'photo',outcome:'needs_changes',stale:false,
    observationSha256:'b'.repeat(64),previewSha256:'c'.repeat(64)};
  const holds={approved:false,canSpend:false,canPublish:false,hostedStorageVerified:false,
    requiresIndependentQC:true,requiresOwnerApproval:true};
  const library={assets:[asset],posts:[{day:1,copyDraft:'Saved draft'}],revision:1,
    ...holds,selection:{stale:false,selectionVersion:2,reviewVersion:3,
      postAssignments:[{day:1,assetIds:['photo']}],reviewNotes:[note]}};
  const manifest={...holds,schemaVersion:1,purpose:'unapproved_post_composition',day:1,
    revision:1,selectionVersion:2,reviewVersion:3,audioPolicy:'silent_review',frameFit:'contain',
    fps:24,width:720,height:1280,photoDurationMs:3000,durationMs:3000,post:library.posts[0],
    candidates:[{...holds,day:1,revision:1,selectionVersion:2,reviewVersion:3,assetId:'photo',
      sourceSha256:asset.sourceSha256,observationSha256:note.observationSha256,
      previewSha256:note.previewSha256,ownerObservation:note,candidateEdit:{assetId:'photo',wholeOriginal:true}}],
    timeline:[{assetId:'photo',startFrame:0,endFrame:72}],previewBytes:bytes.length,previewSha256:hash};
  const response={manifest,previewBase64:bytes.toString('base64')};
  const paths=[];
  const loaded=await loadSavedPostComposition(library,1,async p=>{paths.push(p);return p?response:library;});
  assert.deepEqual(Buffer.from(await loaded.blob.arrayBuffer()),bytes);
  assert.deepEqual(paths,['/posts/1/composition-preview?revision=1&selectionVersion=2&reviewVersion=3','']);
  const audioResponse=structuredClone(response);
  audioResponse.manifest.audioPolicy='saved_candidate_audio';
  audioResponse.manifest.timeline[0].hasAudio=false;
  const audioPaths=[];
  assert.ok(await loadSavedPostComposition(library,1,async p=>{
    audioPaths.push(p);return p?audioResponse:library;
  },()=>true,'saved_candidate_audio'));
  assert.match(audioPaths[0],/audioPolicy=saved_candidate_audio/);
  for(const mutate of [r=>delete r.manifest.timeline[0].hasAudio,
    r=>r.manifest.timeline[0].hasAudio=true,r=>r.manifest.audioPolicy='silent_review']) {
    const changed=structuredClone(audioResponse);mutate(changed);
    await assert.rejects(()=>loadSavedPostComposition(library,1,async p=>p?changed:library,
      ()=>true,'saved_candidate_audio'));
  }
  await assert.rejects(()=>loadSavedPostComposition(library,1,async()=>response,()=>true,'invented'));
  for(const mutate of [r=>r.manifest.approved=true,r=>r.manifest.canSpend=true,
    r=>r.manifest.requiresIndependentQC=false,r=>r.manifest.audioPolicy='original',
    r=>r.manifest.candidates[0].sourceSha256='d'.repeat(64),
    r=>r.manifest.candidates[0].observationSha256='d'.repeat(64),
    r=>r.manifest.candidates[0].candidateEdit={assetId:'photo',left:0},
    r=>r.manifest.timeline[0].startFrame=1,r=>r.manifest.timeline[0].endFrame=71,
    r=>r.manifest.durationMs=4000,r=>r.manifest.reviewVersion=4,
    r=>r.manifest.post={day:1,copyDraft:'Changed'},r=>r.manifest.previewBytes=11*1024*1024,
    r=>r.previewBase64='AAAA',r=>r.manifest.previewSha256='e'.repeat(64)]) {
    const changed=structuredClone(response);mutate(changed);
    await assert.rejects(()=>loadSavedPostComposition(library,1,async p=>p?changed:library));
  }
  for(const mutate of [l=>l.selection.reviewVersion++,l=>l.selection.selectionVersion++,
    l=>l.assets[0].permissionWithdrawn=true,l=>l.assets[0].sourceSha256='d'.repeat(64),
    l=>l.selection.postAssignments=[],l=>l.posts[0].copyDraft='Changed']) {
    const changed=structuredClone(library);mutate(changed);
    await assert.rejects(()=>loadSavedPostComposition(library,1,async p=>p?response:changed));
  }
  for(const outcome of ['unsuitable','stale']) {
    const changed=structuredClone(library);
    if(outcome==='stale')changed.selection.reviewNotes[0].stale=true;
    else changed.selection.reviewNotes[0].outcome=outcome;
    await assert.rejects(()=>loadSavedPostComposition(changed,1,async()=>{throw Error('must not request');}));
  }
  let active=true;
  assert.equal(await loadSavedPostComposition(library,1,async()=>{active=false;return response;},()=>active),null);
  assert.equal(await loadSavedPostComposition(library,1,async()=>{throw Error('must not request');},()=>false),null);
});
