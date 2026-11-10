/** Bounded public HTML observations, never measured SEO rankings or speed. */
export const websiteRecommendations = audit => [...String(audit||'').matchAll(/^###\s+(HIGH|MEDIUM|LOW):\s+([^\r\n]+)\s*\n([^\r\n]+)\s*\n([^\r\n]+)/gm)]
  .map(([,priority,headline,why,fix],id)=>({id,priority,headline,why,fix}));
const trim=(v,max=180)=>typeof v==='string'?v.replace(/\s+/g,' ').trim().slice(0,max):'';
const fact=(value)=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};
export function auditBusinessWebsite(site){
 if(!site||typeof site!=='object'||typeof site.source_url!=='string'||!site.source_url.startsWith('https://'))throw new TypeError('A verified HTTPS source URL is required');
 const o=fact(site.observations);const title=trim(o.title,200),desc=trim(o.meta_description,500);
 const heads=Array.isArray(o.headings)?o.headings.filter(x=>typeof x==='string').slice(0,18).map(x=>trim(x,120)):[];
 const links=Array.isArray(o.service_links)?o.service_links.slice(0,20):[];
 const images=Array.isArray(o.image_candidates)?o.image_candidates.slice(0,8):[];
 const action=(id,priority,headline,reason,how)=>({id,priority,headline,reason,how});
 const actions=[];
 const pages=Array.isArray(site.page_reports)?site.page_reports.slice(0,4):[site];
 const coverage=pages.map(page=>trim(page?.source_url,500)).filter(Boolean);
 const seasonal=pages.flatMap(page=>Array.isArray(page?.freshness?.seasonal_excerpts)?page.freshness.seasonal_excerpts.slice(0,8).map(quote=>`${trim(page.source_url,500)} — ${trim(quote,280)}`):[]).slice(0,6);
 const excerpts=pages.slice(1).map(page=>({url:trim(page?.source_url,500),quote:trim(page?.observations?.visible_paragraphs?.[0]||page?.observations?.meta_description||page?.observations?.headings?.[0],280)})).filter(item=>item.quote);
 const omitted=Array.isArray(site.coverage?.omitted_urls)?site.coverage.omitted_urls.slice(0,10).map(url=>trim(url,500)):[];
 const warnings=Array.isArray(site.enrichment_warnings)?site.enrichment_warnings.slice(0,3).map(item=>trim(item,160)):[];
 if(seasonal.length)actions.push(action('freshness','high','Check seasonal wording and offer dates','Source copy contains seasonal or date-sensitive wording; its current validity is unknown.',seasonal.join(' / ')+' Confirm current dates and availability before using this wording.'));

 if(!title||title.length<12)actions.push(action('title','medium','Make your page title clearer','The scanned title is missing or too short.','Write a specific page title describing the main service and service area.'));
 if(!desc)actions.push(action('description','medium','Add a short page description','The page did not expose a meta description.','Write a truthful summary of the service in plain English, ideally around 120–160 characters.'));
 else if(desc.length<60)actions.push(action('description','low','Add useful detail to the page description','The website description has very little information.','Explain the service, who it helps and the next step without stuffing keywords.'));
 if(!heads.length)actions.push(action('heading','high','Add a clear main page heading','No heading was found in the source extracted from this page.','Use a visible heading that immediately explains the service.'));
 const relevant=[...heads,...links.map(x=>trim(x?.label,110))].join(' ').toLowerCase();
 if(!/(contact|enquir|quote|book|reserv|appointment|call us|get in touch)/.test(relevant))
  actions.push(action('contact_route','high','Make it obvious how to contact you','The scanned headings and links do not clearly show an enquiry or booking action.','Add a prominent contact, booking or quote link that reaches a genuine business-controlled destination.'));
 if(!links.length)actions.push(action('service_links','medium','Explain what services are available','No labelled service links were found in this single-page extract.','List your main services and link to pages that explain each one.'));
 if(images.length>0&&images.every(x=>!trim(x.alt)))actions.push(action('image_descriptions','low','Describe important website pictures','The image candidates did not include meaningful alternative text.','Add simple alternative descriptions to genuine, informative photos.'));
 const observations=[title&&`Page title: ${title}`,desc&&`Website description: ${desc}`,heads.length&&`Headings found: ${heads.join(' / ')}`,links.length&&`Service links found: ${links.map(x=>trim(x?.label,100)).filter(Boolean).join(' / ')}`,images.length&&`Picture candidates: ${images.length}`].filter(Boolean);
 return {coverage,excerpts,omitted,warnings,sourceFreshness:'Unknown; fetching a page does not establish current validity',sourceUrl:site.source_url,pageScope:coverage.length+' public HTML page(s); partial coverage',observations,actions,
  searchConsoleConnected:false,rankingsMeasured:false,coreWebVitalsMeasured:false,backlinksMeasured:false,readyForPublishing:false,
  limitations:'This is a bounded public HTML review. Omitted, blocked, external, unlinked and JavaScript-only pages are not assessed. Website claims and promotions remain unconfirmed. Search rankings, load speed, indexing, ownership and actual conversion rates were not measured.'};
}
export function siteAuditMarkdown(audit){
 if(!audit||!Array.isArray(audit.actions))throw new TypeError('Site audit required');
 const lines=['# Website improvements for your business','',`Page checked: ${audit.sourceUrl}`,'',
  '**What this checks:** Website wording, visible service links, basic enquiry clarity and pictured references from bounded public HTML pages.','',
  '## What Growthrova found',...audit.observations.map(x=>'- '+x),'','## What to improve next'];
 lines.push('',`Pages read: ${(audit.coverage||[audit.sourceUrl]).join(' / ')}`,`Freshness: ${audit.sourceFreshness||'Unknown'}`);
 for(const item of audit.excerpts||[])lines.push('Unconfirmed page excerpt: '+item.url+' — '+item.quote);
 if(audit.omitted?.length)lines.push('Not read within the page budget: '+audit.omitted.join(' / '));
 if(audit.warnings?.length)lines.push('Failed page reads: '+audit.warnings.join(' / '));
 if(!audit.actions.length)lines.push('No obvious issues were detected in this limited check. A proper technical and conversion audit is still needed.');
 else for(const item of audit.actions){lines.push('',`### ${item.priority.toUpperCase()}: ${item.headline}`,item.reason,item.how);}
 lines.push('','## What has not been tested',audit.limitations,'','No SEO ranking improvements or customer enquiries are guaranteed. No changes were made to the website.');
 return lines.join('\n');
}
/** A copyable search title draft. The service descriptors must appear in page evidence. */
export function suggestWebsiteTitle(site){
 if(!site||typeof site!=='object')throw new TypeError('Website evidence is required');
 const o=fact(site.observations),name=trim(o.title,100);
 if(!name)return '';
 const raw=[o.meta_description,...(Array.isArray(o.headings)?o.headings.slice(0,8):[])].filter(x=>typeof x==='string').join(' ').toLowerCase();
 const categories=[
  [/roof repairs?/,'Roof Repairs'],[/gutter/,'Guttering'],[/flat roof/,'Flat Roofing'],
  [/plumb/,'Plumbing'],[/restaurant|dining/,'Dining'],[/concierge/,'Concierge'],
  [/curated experience/,'Curated Experiences'],[/beauty/,'Beauty Treatments']
 ].filter(([expr])=>expr.test(raw)).map(([,title])=>title);
 const unique=[...new Set(categories)].slice(0,2);
 if(!unique.length)return name.slice(0,65);
 const result=name+' | '+unique.join(' & ');
 return result.length<=65?result:name.slice(0,Math.max(20,65-3-unique[0].length))+' | '+unique[0];
}
