import test from 'node:test';
import assert from 'node:assert/strict';
import {rankClipEvidence} from '../src/lib/businessEvidenceRanking.mjs';
test('ranks timestamped spoken evidence but never infers visual facts',()=>{
 const clips=[
  {title:'Visual scene 2',start_s:0,end_s:42},
  {title:'Review',start_s:50,end_s:93,transcript:'Great value and quality of the burger, a really nice taste.'},
  {title:'Intro',start_s:100,end_s:143,transcript:'Welcome to the channel.'}];
 const output=rankClipEvidence(clips,{desire:'Great taste',objection:'unsure about quality',proof:'quality burger'});
 assert.equal(output[0].title,'Review');
 assert.equal(output[0].confidence,'keyword-match');
 assert.equal(output[0].verifiedOutcome,false);
 assert.equal(output[2].confidence,'unassessed');
 assert.equal(output[2].relevanceScore,null);
 assert.equal(output[0].evidenceMatches.some(x=>x.field==='proof'),true);
});
test('transcript absent never ranks from misleading titles',()=>{
 const output=rankClipEvidence([{title:'Best burger ever',start_s:0,end_s:10}],{desire:'burger'});
 assert.equal(output[0].relevanceScore,null);
 assert.match(output[0].editorialWarning,/completeness/);
});
