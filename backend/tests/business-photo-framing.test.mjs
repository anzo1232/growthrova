import test from 'node:test';
import assert from 'node:assert/strict';
import * as review from '../src/lib/businessOriginalReview.mjs';

test('static framing fits exact social proportions inside the display-oriented original',()=>{
 assert.equal(typeof review.centeredPhotoCrop,'function');
 for(const [photoWidth,photoHeight] of [[1201,801],[801,1201],[64,48],[16,20]]){
  const original={photoWidth,photoHeight,left:1,top:2,width:16,height:16,assetId:'keep'};
  const before=structuredClone(original);
  for(const [ratio,x,y] of [['4:5',4,5],['1:1',1,1]]){
   const crop=review.centeredPhotoCrop(original,ratio);
   assert.equal(crop.width*y,crop.height*x);
   assert.ok(crop.width>=16&&crop.height>=16);
   assert.ok(crop.left>=0&&crop.top>=0);
   assert.ok(crop.left+crop.width<=photoWidth&&crop.top+crop.height<=photoHeight);
   assert.ok(Math.abs(crop.left-(photoWidth-crop.width)/2)<=0.5);
   assert.ok(Math.abs(crop.top-(photoHeight-crop.height)/2)<=0.5);
   assert.ok(crop.width+x>photoWidth||crop.height+y>photoHeight,'Use the largest exact-ratio crop');
   assert.equal(crop.assetId,'keep');
  }
  assert.deepEqual(review.centeredPhotoCrop(original,'original'),{...original,left:0,top:0,width:photoWidth,height:photoHeight});
  assert.deepEqual(original,before,'Presets must not mutate saved settings');
 }
});

test('invalid or undersized originals cannot create a misleading preset crop',()=>{
 assert.equal(typeof review.centeredPhotoCrop,'function');
 for(const dimensions of [{photoWidth:16,photoHeight:16},{photoWidth:NaN,photoHeight:400},
  {photoWidth:401.5,photoHeight:400},{photoWidth:0,photoHeight:400},null]){
  assert.throws(()=>review.centeredPhotoCrop(dimensions,'4:5'),/dimensions|too small/);
 }
 assert.throws(()=>review.centeredPhotoCrop({photoWidth:400,photoHeight:500},'9:16'),/framing/);
});
