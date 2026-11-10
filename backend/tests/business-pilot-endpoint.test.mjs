import test from 'node:test';
import assert from 'node:assert/strict';
import {resolvePilotApi} from '../src/lib/businessPilotEndpoint.mjs';
 test('defaults to current pilot and permits a separate loopback test port',()=>{
  assert.equal(resolvePilotApi(), 'http://127.0.0.1:4192');
  assert.equal(resolvePilotApi('http://127.0.0.1:4219'), 'http://127.0.0.1:4219');
 });
 test('rejects remote endpoints, userinfo and path confusion',()=>{
  for(const url of ['https://api.clippr.org','http://127.0.0.1.evil.example','http://user:pass@127.0.0.1:4219','http://127.0.0.1:4219/api','http://127.0.0.1:4219/?token=x','https://127.0.0.1:4219','not a url'])
   assert.throws(()=>resolvePilotApi(url),url);
 });
