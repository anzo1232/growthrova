import React from 'react';import{createRoot}from'react-dom/client';
import BusinessHeroSet from '../src/BusinessHeroSet.jsx';
const target=window.__QA_BACKEND__||import.meta.env.VITE_BUSINESS_PILOT_API;
const query=new URL(window.location.href).searchParams;
const did=query.get('draft')||'a'.repeat(32);
const api=async(path,{method='GET',data,responseType='json'}={})=>{
 const resp=await fetch(target+path,{method,headers:{'X-Clippr-Pilot':'local-only',...(data?{'Content-Type':'application/json'}:{})},body:data?JSON.stringify(data):undefined});
 if(!resp.ok){const json=await resp.json().catch(()=>({}));throw Error(json.error||'QA HTTP error');}
 return responseType==='blob'?resp.blob():resp.json();
};
createRoot(document.getElementById('root')).render(<BusinessHeroSet api={api} draftId={did} revision={1} document={{business:'QA Restaurant',observedFacts:['Restaurant and local dining']}}/>);
