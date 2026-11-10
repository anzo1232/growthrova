import test from 'node:test';
import assert from 'node:assert/strict';
import {businessTypeStrategy} from '../src/lib/businessTypeStrategy.mjs';
test('many specific niches map to editing needs rather than a fixed dropdown',()=>{
 for(const [name,type] of [['mobile dog groomer','transformation'],['roof repair','trust'],['wedding venue','experience'],['used car dealership','showcase'],['cybersecurity consultant','expertise']]){
  const result=businessTypeStrategy({businessType:name});
  assert.equal(result.type,type,name);assert.equal(result.verified,false);
 }
});
test('unknown niches fail safe to a customised question, not an invented category',()=>{
 const r=businessTypeStrategy({businessType:'underwater drone inspection'});
 assert.equal(r.type,'custom');assert.match(r.source,/no reliable category/);
});
