import test from 'node:test';
import assert from 'node:assert/strict';
import {buildHeroSet} from '../src/lib/businessHeroSet.mjs';
const cfg={business:'A Real Business',offer:'Home renovation consultations',audience:'Local homeowners',ownerConfirmed:true,sourceFacts:['Offers bathroom renovations']};
test('three different social directions are never silently billed or approved',()=>{
 const result=buildHeroSet({...cfg,sector:'construction'});
 assert.deepEqual(result.items.map(x=>x.purpose),['editorial','educational','social']);
 assert.deepEqual(result.items.map(x=>x.ratio),['4:5','4:5','9:16']);
 assert.ok(result.items.every(x=>!x.spendAuthorised&&!x.retriesAllowed&&!x.approved&&!x.published));
 assert.equal(result.launchStatus,'concepts_not_finished_content');
});
test('restaurants, beauty, construction and concierge have different social art directions',()=>{
 const examples=['restaurant','beauty','construction','concierge'].map(sector=>buildHeroSet({...cfg,sector}).items.map(x=>x.direction));
 assert.equal(new Set(examples.map(x=>x.join('|'))).size,4);
});
test('invalid or unconfirmed claims cannot enter hero set',()=>{
 assert.throws(()=>buildHeroSet({...cfg,ownerConfirmed:false}));
 assert.throws(()=>buildHeroSet({...cfg,business:''}));
});
