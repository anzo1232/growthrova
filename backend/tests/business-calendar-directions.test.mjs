// Retained for the later audit; build-first development does not run this suite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {strategyFields,editOwnerStrategy,confirmOwnerStrategy,completeStrategyCalendar,refreshStrategyCalendar,strategyCalendarPreview,prepareNextStrategyCampaign} from '../src/lib/businessOwnerStrategy.mjs';
import {marketingPlanCsv} from '../src/lib/businessMarketingDocument.mjs';

function brief(goal){
  let doc={business:'Owner studio',goal,calendarStartDate:'2026-11-05',posts:[],creatives:[]};
  for(const [key,limit] of Object.entries(strategyFields))doc=editOwnerStrategy(doc,key,key.padEnd(limit,'x'));
  return confirmOwnerStrategy(doc);
}
test('goal-specific preview matches filled and refreshed calendar without changing other work',()=>{
  const agendas=[];
  for(const goal of ['awareness','enquiries','bookings','education','offers']){
    const doc=brief(goal),preview=strategyCalendarPreview(doc),filled=completeStrategyCalendar(doc);
    agendas.push(preview.map(post=>post.theme).join('|'));
    assert.equal(new Set(preview.map(post=>post.theme)).size,30);
    assert.equal(doc.posts.length,0);
    for(let i=0;i<30;i++){
      const {action,direction,...post}=preview[i];
      assert.equal(action,'new');assert.deepEqual(filled.posts[i],post);
      assert.ok(post.copyDraft.startsWith('Draft direction: '+direction+'\n'));
      assert.ok(post.copyDraft.length<=3000);
      for(const key of ['audience','offer','positioning','constraints'])assert.ok(post.copyDraft.includes(doc.ownerStrategy[key]));
    }
    const reviewed={...filled.posts[0],status:'copy_reviewed',copyDraft:'Owner reviewed copy'};
    const draft={...filled.posts[1],channel:'LinkedIn',format:'Carousel',mediaReference:'preserve-original',copyDraft:'Old words'};
    const current={...filled,posts:[reviewed,draft,...filled.posts.slice(2)]};
    const proposed=strategyCalendarPreview(current);
    assert.equal(proposed[0].action,'preserved');assert.equal(proposed[1].action,'replaceable');
    const next=refreshStrategyCalendar(current,[2]);
    assert.equal(next.posts[0],reviewed);assert.equal(next.posts[2],current.posts[2]);
    for(const key of ['theme','copyDraft','callToAction','channel','format'])assert.equal(next.posts[1][key],proposed[1][key]);
    assert.equal(next.posts[1].mediaReference,draft.mediaReference);
    assert.equal(completeStrategyCalendar(current).posts[1],draft);
    assert.throws(()=>refreshStrategyCalendar(current,[1]),/Reviewed/);
    assert.ok(marketingPlanCsv(next).includes(next.posts[1].theme));
    const changed=editOwnerStrategy(current,'offer','Changed owner offer');
    assert.deepEqual(strategyCalendarPreview(changed),[]);
    assert.throws(()=>refreshStrategyCalendar(changed,[2]),/Confirm/);
    const reused=prepareNextStrategyCampaign(current,{goal,startDate:'2026-12-01'});
    assert.equal(reused.posts[1].theme,preview[1].theme);
  }
  assert.equal(new Set(agendas).size,5);
});
