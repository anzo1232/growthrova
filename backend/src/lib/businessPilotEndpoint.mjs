/** Development-only API origin. Never point the unauthenticated local pilot at
 * a cloud API or send its control headers outside this computer. */
export function resolvePilotApi(value){
  if(value===undefined||value==='')return 'http://127.0.0.1:4192';
  if(typeof value!=='string')throw new TypeError('Invalid local pilot endpoint');
  let url;try{url=new URL(value);}catch{throw new TypeError('Invalid local pilot endpoint');}
  if(url.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(url.hostname)||
     url.username||url.password||url.pathname!=='/'||url.search||url.hash)
    throw new TypeError('The Business pilot API must be a loopback HTTP origin');
  return url.origin;
}
