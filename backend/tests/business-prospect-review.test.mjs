import test from 'node:test';
import assert from 'node:assert/strict';
import {matchesProspectReview,prospectPreparationGaps,prospectOutreachAllowed} from '../src/growthrovaProspectReview.mjs';

test('qualification and preparation review preserve legacy research and separate withheld outreach',()=>{
  const legacy={name:'Local partner',status:'ready_for_review',sourceUrl:'https://example.org',
    sourceQuote:'Owner-retained quotation',observedOn:'2026-11-05',fit:'Owner fit hypothesis',
    outreachDraft:'Owner wording',nextAction:''};
  assert.equal(matchesProspectReview(legacy,{decision:'unreviewed'}),true);
  assert.deepEqual(prospectPreparationGaps(legacy),['next human action']);
  assert.equal(matchesProspectReview(legacy,{preparation:'missing'}),true);
  assert.equal(matchesProspectReview({...legacy,nextAction:'Review claims'},{preparation:'missing'}),false);
  assert.equal(prospectOutreachAllowed(legacy),true); // not permission or approval
  for(const decision of ['hold','not_fit']){
    const held={...legacy,qualification:{decision,reason:'Needs a named reviewer'}};
    assert.equal(matchesProspectReview(held,{decision,query:'NAMED reviewer'}),true);
    assert.equal(matchesProspectReview(held,{decision:'pursue'}),false);
    assert.equal(matchesProspectReview(held,{preparation:'review'}),false);
    assert.equal(prospectOutreachAllowed(held),false);
  }
  assert.equal(prospectOutreachAllowed({...legacy,status:'parked'}),false);
});
