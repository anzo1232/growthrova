import test from 'node:test';import assert from 'node:assert/strict';
import {buildHeroSet} from '../src/lib/businessHeroSet.mjs';
import {alternativesFor,requestCreativeRevision} from '../src/lib/businessCreativeAlternatives.mjs';
const sectors=['restaurant','beauty','construction','concierge'];
test('two distinct photorealistic alternatives in each of four real business sectors, no charges',()=>{
 for(const sector of sectors){const hero=buildHeroSet({business:'Example '+sector,offer:'Confirmed local services',audience:'Interested customers',sector,ownerConfirmed:true});
  for(const item of hero.items){const variants=alternativesFor(item);assert.equal(variants.length,2);assert.notEqual(variants[0].prompt,variants[1].prompt);
   assert.ok(variants.every(v=>v.prompt.includes('Photorealistic only')&&!v.charged&&!v.published&&v.approval==='not_approved'));
  }
 }
});
test('owner feedback generates a new unapproved direction but no provider calls',()=>{
 const base=alternativesFor(buildHeroSet({business:'Example Restaurant',offer:'Dining bookings',audience:'Local diners',ownerConfirmed:true}).items[0])[0];
 const revised=requestCreativeRevision(base,'Show more recognisable dining atmosphere, with a closer angle.');
 assert.equal(revised.parentId,base.id);assert.equal(revised.charged,false);assert.match(revised.prompt,/closer angle/);
 assert.throws(()=>requestCreativeRevision(base,'short'));
});
