import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {confirmOwnerStrategy,editOwnerStrategy} from '../src/lib/businessOwnerStrategy.mjs';
import {paidStrategySuggestions,applyPaidStrategyField} from '../src/lib/businessPaidStrategy.mjs';

function source(){
  return confirmOwnerStrategy({business:'Harbour Cycles',goal:'bookings',sourceUrl:'https://cycles.example/services',observedFacts:[],
    ownerStrategy:{audience:'Local cyclists',offer:'Bicycle servicing',positioning:'Repairs discussed with you',callToAction:'Ask about servicing',constraints:'Confirm availability'},
    paidCampaign:{objective:'sales',audience:'',primaryText:'Old copy',headline:'',callToAction:'',destinationUrl:'',currency:'GBP',dailyBudget:'12',durationDays:7,asset:null},
    googleCampaign:{objective:'sales',audience:'',location:'',language:'',destinationUrl:'',currency:'GBP',dailyBudget:'12',durationDays:7,keywordMatch:'phrase',headlines:[],descriptions:[],keywords:[],negativeKeywords:[]}});
}

test('explicit field copies preserve other preparation and survive server normalisation',()=>{
  const original=source(),before=structuredClone(original);
  let doc=original;
  for(const platform of ['meta','google'])for(const field of paidStrategySuggestions(doc,platform)){
    if(!field.blocked)doc=applyPaidStrategyField(doc,platform,field.key);
  }
  assert.deepEqual(original,before);
  assert.equal(doc.paidCampaign.objective,'leads');
  assert.equal(doc.googleCampaign.objective,'leads');
  assert.equal(doc.paidCampaign.primaryText,'Harbour Cycles\n\nBicycle servicing\n\nRepairs discussed with you');
  assert(!doc.paidCampaign.primaryText.includes('Confirm availability'));
  assert.deepEqual(doc.googleCampaign.descriptions,['Bicycle servicing','Repairs discussed with you']);
  for(const key of ['paidCampaign','googleCampaign']){
    assert.equal(doc[key].dailyBudget,'12');assert.equal(doc[key].currency,'GBP');
    assert.equal(doc[key].destinationUrl,original.sourceUrl);
  }
  assert.deepEqual(doc.googleCampaign.keywords,[]);
  const result=spawnSync('.venv-business-tests/bin/python',['-c',
    'import json,sys; from business_paid_campaign import normalise,normalise_google; d=json.load(sys.stdin); print(json.dumps([normalise(d["paidCampaign"]),normalise_google(d["googleCampaign"])]))'],
    {input:JSON.stringify(doc),encoding:'utf8',timeout:20000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  assert.equal(result.status,0,result.stderr);
  assert.deepEqual(JSON.parse(result.stdout),[doc.paidCampaign,doc.googleCampaign]);
});

test('stale strategy, oversize exact wording and unsupported destinations never silently copy',()=>{
  const doc=source();
  assert.throws(()=>applyPaidStrategyField(editOwnerStrategy(doc,'offer','Changed'),'meta','headline'),/Confirm/);
  const long=confirmOwnerStrategy(editOwnerStrategy(doc,'offer','Service '.repeat(30)));
  const field=paidStrategySuggestions(long,'google').find(f=>f.key==='headlines');
  assert.equal(field.blocked,true);assert.equal(field.value[1],long.ownerStrategy.offer);
  assert.throws(()=>applyPaidStrategyField(long,'google','headlines'),/length/);
  const unsafe=confirmOwnerStrategy({...doc,sourceUrl:'https://person:password@example.com'});
  assert(!paidStrategySuggestions(unsafe,'meta').some(f=>f.key==='destinationUrl'));
  const offers=confirmOwnerStrategy({...doc,goal:'offers'});
  assert(!paidStrategySuggestions(offers,'google').some(f=>f.key==='objective'));
  const next=applyPaidStrategyField(doc,'meta','audience');
  assert.equal(next.paidCampaign.objective,'sales');assert.equal(next.paidCampaign.primaryText,'Old copy');
  assert.equal(next.googleCampaign,doc.googleCampaign);
});
