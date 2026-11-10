import test from 'node:test';import assert from 'node:assert/strict';
import {normalizeConfirmedProfile} from '../src/lib/businessRepository.mjs';
const example={business_description:'Independent mobile detailing business',offer:'Premium car detailing',audience:'Vehicle owners',source_type:'description',owner_confirmed:true};
test('works without any website and requires affirmative owner confirmation',()=>{
 assert.equal(normalizeConfirmedProfile(example).source_type,'description');
 assert.throws(()=>normalizeConfirmedProfile({...example,owner_confirmed:false}));
});
test('rejects malformed and oversized fields',()=>{
 assert.throws(()=>normalizeConfirmedProfile({...example,audience:'x'.repeat(300)}));
 assert.throws(()=>normalizeConfirmedProfile({...example,source_type:'hidden'}));
});
