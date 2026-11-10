/** Same-origin API only. Fresh caller session for every request; no pilot fallback. */
export function createGrowthrovaTransport(client, userId, {fetchImpl=fetch}={}) {
  return async function request(path,{method='GET',data,body,headers={},responseType='json'}={}) {
    if(!['json','blob'].includes(responseType))throw Error('Unsupported Growthrova response type.');
    if(typeof path!=='string'||!path.startsWith('/api/growthrova/')||path.includes('\\')||path.includes('#')||path.includes('..')||
       !new URL(path,'https://growthrova.invalid').pathname.startsWith('/api/growthrova/'))
      throw Error('Invalid Growthrova request.');
    const {data:sessionData,error}=await client.auth.getSession();
    const session=sessionData?.session;
    if(error||!session?.access_token||session.user?.id!==userId)throw Error('Your session changed. Sign in again.');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),90000);
    try {
      const response=await fetchImpl(path,{method,credentials:'omit',redirect:'error',signal:controller.signal,
        headers:{...headers,Accept:'application/json',Authorization:'Bearer '+session.access_token,
          ...(data!==undefined?{'Content-Type':'application/json'}:{})},
        body:data!==undefined?JSON.stringify(data):body});
      const value=response.ok&&responseType==='blob'
        ?await response.blob():await response.json().catch(()=>null);
      // The body can finish after sign-out or account replacement. Discard it
      // before any caller can display/export it. Token refresh for this same
      // owner is allowed; an already dispatched server write cannot be undone.
      const {data:current,error:sessionError}=await client.auth.getSession();
      if(sessionError||!current?.session?.access_token||current.session.user?.id!==userId)
        throw Error('Your session changed. Sign in again.');
      if(!response.ok||!value){
        const failure=Error(value?.error||'Could not check Growthrova storage. Retry without creating a second save.');
        failure.status=response.status;failure.code=value?.code;throw failure;
      }
      return value;
    }catch(error){
      if(error.name==='AbortError')throw Error('The request timed out. Check the same save or import before retrying.');
      throw error;
    }finally{clearTimeout(timer);}
  };
}

export function growthrovaProjectConfig(url,key) {
  try {
    let publicKey=typeof key==='string'&&key.startsWith('sb_publishable_')&&key.length>15;
    if(!publicKey&&typeof key==='string'&&key.split('.').length===3){
      const payload=key.split('.')[1].replaceAll('-','+').replaceAll('_','/');
      publicKey=JSON.parse(atob(payload.padEnd(Math.ceil(payload.length/4)*4,'='))).role==='anon';
    }
    const parsed=new URL(url);
    if(parsed.protocol!=='https:'||!/^[-a-z0-9]+\.supabase\.co$/.test(parsed.hostname)||
       parsed.port||parsed.username||parsed.password||parsed.search||parsed.hash||parsed.pathname!=='/'||!publicKey)
      throw Error();
    return {url:parsed.origin,key};
  }catch{throw Error('The isolated Growthrova preview is not configured. An operator must provision its separate login and storage.');}
}
