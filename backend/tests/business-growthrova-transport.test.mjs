import assert from 'node:assert/strict';
import {createGrowthrovaTransport,growthrovaProjectConfig} from '../src/lib/growthrovaTransport.mjs';
const user={id:'synthetic-owner'};
let session={user,access_token:'synthetic-token'},calls=[];
const client={auth:{getSession:async()=>({data:{session}})}};
const request=createGrowthrovaTransport(client,user.id,{fetchImpl:async(path,options)=>{
  calls.push({path,options});return {ok:true,status:200,json:async()=>({documents:[]})};
}});
await request('/api/growthrova/organisations/org/marketing-documents',{method:'POST',data:{id:'synthetic-document'}});
assert.equal(calls[0].options.headers.Authorization,'Bearer synthetic-token');
assert.equal(calls[0].options.redirect,'error');assert.equal(calls[0].options.credentials,'omit');
for(const path of ['https://foreign.example','/offline/organisations/org','/api/pilot/media','/api/growthrova/../pilot','/api/growthrova/%2e%2e/creator'])
  await assert.rejects(()=>request(path));
session={user:{id:'other-owner'},access_token:'other-token'};
await assert.rejects(()=>request('/api/growthrova/anything'),/session changed/);
assert.equal(calls.length,1);
assert.throws(()=>growthrovaProjectConfig(undefined,undefined));
assert.throws(()=>growthrovaProjectConfig('https://example.supabase.co/path','public'));
assert.equal(growthrovaProjectConfig('https://synthetic.supabase.co','sb_publishable_synthetic').url,'https://synthetic.supabase.co');

assert.throws(()=>growthrovaProjectConfig('https://synthetic.supabase.co','sb_secret_not-allowed'));

// Response bodies may arrive after sign-out/account replacement, including
// original-media bytes encoded in JSON. Never hand them to the old caller.
for(const next of [null,{user:{id:'other-owner'},access_token:'other-token'}]){
  session={user,access_token:'synthetic-token'};
  let finish,bodyStarted=false;
  const body=new Promise(resolve=>{finish=resolve;});
  const delayed=createGrowthrovaTransport(client,user.id,{fetchImpl:async()=>({
    ok:true,status:200,json:()=>{bodyStarted=true;return body;}
  })});
  const loading=delayed('/api/growthrova/organisations/org/marketing-documents');
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(bodyStarted,true,'Request is waiting for the body before the account changes');
  session=next;
  finish({documents:[{id:'prior-account-private-draft'}]});
  await assert.rejects(()=>loading,/session changed/);
}
// Normal refresh for the same owner must not turn an acknowledged write into
// an uncertain save or trigger a duplicate retry.
session={user,access_token:'synthetic-token'};
const refreshed=createGrowthrovaTransport(client,user.id,{fetchImpl:async()=>({
  ok:true,status:200,json:async()=>{
    session={user,access_token:'synthetic-refreshed-token'};return {revision:2};
  }
})});
assert.deepEqual(await refreshed('/api/growthrova/anything'),{revision:2});

// Generated images use the same fresh-session checks as JSON. The transport
// must return actual bytes, rather than trying to parse a PNG as JSON.
const pixels=new Blob(['synthetic-png-bytes'],{type:'image/png'});
const binary=createGrowthrovaTransport(client,user.id,{fetchImpl:async()=>({
  ok:true,status:200,blob:async()=>pixels,json:async()=>{throw Error('PNG is not JSON');}
})});
assert.equal(await binary('/api/growthrova/images/original',{responseType:'blob'}),pixels);
for(const next of [null,{user:{id:'another-owner'},access_token:'another-token'}]){
 session={user,access_token:'synthetic-token'};
 const revoked=createGrowthrovaTransport(client,user.id,{fetchImpl:async()=>({
   ok:true,status:200,blob:async()=>{session=next;return pixels;}
 })});
 await assert.rejects(()=>revoked('/api/growthrova/images/original',{responseType:'blob'}),/session changed/);
}
