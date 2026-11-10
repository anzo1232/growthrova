import test from 'node:test';
import assert from 'node:assert/strict';
import {postApprovalReadiness} from '../src/lib/businessPostApprovalReadiness.mjs';

const post={day:1,channel:'Instagram',format:'Image advert'};
const review={...post,status:'awaiting_human_creative_review',issues:[]};
const manifest={fileSHA256:{'creative-quality-report.json':'a'.repeat(64)}};
const state={post,qualityReport:{posts:[review]},manifest};

test('owner review becomes available for the matching saved static post only',()=>{
 assert.equal(postApprovalReadiness(state).ready,true);
});

test('loading, failed and malformed quality responses never enable approval',()=>{
 for(const qualityReport of [null,undefined,{}, {posts:null}, {posts:[]}, {posts:[review,review]}]){
  assert.equal(postApprovalReadiness({...state,qualityReport}).ready,false);
 }
 for(const changed of [{manifest:null},{manifest:{}},{manifest:{fileSHA256:{}}}]){
  assert.equal(postApprovalReadiness({...state,...changed}).ready,false);
 }
});

test('rejected, unrecognised and incomplete review results keep approval unavailable',()=>{
 for(const change of [
  {status:'rejected_by_preflight',issues:['real_video_required_not_a_static_graphic']},
  {status:'not_checked'},{issues:undefined},{issues:['weak_or_generic_hook']},
  {channel:'TikTok'},{day:2},{format:'Carousel'}
 ])assert.equal(postApprovalReadiness({...state,qualityReport:{posts:[{...review,...change}]}}).ready,false);
});

test('one PNG cannot approve a Reel, Story, carousel or unknown deliverable format',()=>{
 for(const format of ['Reel concept','Video advert','Story','Carousel','Unknown format']){
  const changedPost={...post,format};
  assert.equal(postApprovalReadiness({...state,post:changedPost,
   qualityReport:{posts:[{...review,format}]}}).ready,false);
 }
});
