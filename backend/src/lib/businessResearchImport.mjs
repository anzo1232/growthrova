import {evidenceFields,normalizeStrategyEvidence} from './businessStrategyEvidence.mjs';
const MAX_BYTES=180000;
function pageUrl(value){
 const u=new URL(value);
 if(u.protocol!=='https:'||u.username||u.password||u.port||!u.hostname.includes('.'))throw Error('Research requires an HTTPS page URL.');
 return u;
}
/** Imported files are untrusted data, never authenticated capture or instructions. */
export async function importWebsiteResearch(text,website,organisationId){
 if(typeof text!=='string'||new TextEncoder().encode(text).length>MAX_BYTES)throw Error('Research file must be at most 180 KB.');
 const site=pageUrl(website),report=JSON.parse(text);
 if(report?.status!=='extracted_unconfirmed')throw Error('Use a saved website research report.');
 const pages=report.page_reports||[report];
 if(!Array.isArray(pages)||!pages.length||pages.length>4)throw Error('Invalid research pages.');
 if(!report.page_reports&&report.audited_page_urls?.length>1)throw Error('This older report merges pages without excerpt provenance. Export a new report.');
 const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));
 const reportSha256=Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
 const candidates=[];
 for(const page of pages){
  const url=pageUrl(page.source_url);
  if(url.hostname!==site.hostname||page.status!=='extracted_unconfirmed')throw Error('Research pages must belong to the selected business website.');
  const o=page.observations;
  if(!o||!Array.isArray(o.headings)||!Array.isArray(o.visible_paragraphs)||o.headings.length>12||o.visible_paragraphs.length>12)throw Error('Invalid page excerpts.');
  for(const quote of [o.title,o.meta_description,...o.headings,...o.visible_paragraphs]){
   if(quote===undefined||quote==='')continue;
   if(typeof quote!=='string'||quote.length>1200)throw Error('Invalid or oversized page excerpt.');
   if(quote.trim()&&!candidates.some(c=>c.sourceUrl===url.href&&c.quote===quote))candidates.push({sourceUrl:url.href,quote,reportSha256});
  }
 }
 if(!candidates.length)throw Error('No source excerpts found.');
 return {organisationId,website:site.href,candidates};
}
export function linkResearchCandidate(profile,key,packet,index,organisationId,website){
 if(!evidenceFields.includes(key)||packet.organisationId!==organisationId||packet.website!==pageUrl(website).href)throw Error('Research scope changed. Import for this business again.');
 const candidate=packet.candidates[index];
 if(!candidate)throw Error('Select a research excerpt.');
 const evidence=normalizeStrategyEvidence({[key]:{...candidate,claim:profile[key]}});
 return {...profile,owner_confirmed:false,research_evidence:{...profile.research_evidence,...evidence}};
}
