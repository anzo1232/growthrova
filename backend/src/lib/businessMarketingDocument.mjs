/** Editable campaign drafts. Copy review never authorises media, publishing or spend. */
import {marketingCopyIssue} from './businessCopyReadiness.mjs';
const FORMATS=[
  ['image_ad','Hero image advert','4:5','Lead with one authentic business benefit and a clear visual focal point.'],
  ['video_ad','Short video campaign','9:16','Show the customer problem, the relevant service and a clear next step.'],
  ['carousel','Customer-question carousel','4:5','Answer one genuine customer question across a coherent sequence.'],
  ['graphic','Informational brand graphic','4:5','Explain the service accurately with controlled, readable typography.'],
  ['image_ad','Customer problem advert','4:5','Show the relevant customer problem in one immediately understandable, believable scene. Distinguish this from the aspirational hero by focusing on the problem, not invented outcomes. No text, no invented client photos or testimonials.'],
  ['image_ad','Real service detail advert','4:5','Close-up editorial illustration of materials, tools, ingredients or surroundings genuinely associated with the actual service; do not claim that synthetic image depicts completed business work. Not a repeat of the main hero.'],
  ['image_ad','Enquiry invitation advert','4:5','Show a simple credible next-step setting that encourages contacting the business. Art direction should differ from the problem scene and the close-up materials scene; keep negative space for readable CTA added separately.'],
];
export const MARKETING_POST_COPY_LIMIT=3000;
export const MARKETING_CREATIVE_COPY_LIMIT=2000;
export const MARKETING_GRAPHIC_TEXT_LIMIT=500;
const POST_FIELDS={theme:200,channel:50,format:80,objective:60,copyDraft:MARKETING_POST_COPY_LIMIT,graphicText:MARKETING_GRAPHIC_TEXT_LIMIT,supportingLine:180,callToAction:240,destinationUrl:512};
const CREATIVE_FIELDS={title:180,brief:6000,copyDraft:MARKETING_CREATIVE_COPY_LIMIT,callToAction:240};
function patchFields(patch,fields){
  if(!patch||typeof patch!=='object'||Array.isArray(patch))throw new TypeError('Invalid edit');
  for(const [key,value] of Object.entries(patch))
    if(!Object.hasOwn(fields,key)||typeof value!=='string'||value.length>fields[key])
      throw new TypeError('Invalid editable field: '+key);
  return patch;
}
export function createMarketingDocument(campaign){
  if(!campaign?.business||!campaign.plan?.posts?.length||!campaign.creative?.prompt)
    throw new TypeError('A prepared website campaign with a content plan is required');
  return {version:1,name:(campaign.business+' — 30-day campaign').slice(0,120),business:campaign.business,calendarStartDate:'',
    sourceUrl:campaign.sourceUrl,goal:campaign.goal,observedFacts:campaign.observedFacts||[],
    ...(campaign.observedFactSources?{observedFactSources:[...campaign.observedFactSources]}:{}),
    ...(campaign.suggestedStrategy?{ownerStrategy:structuredClone(campaign.suggestedStrategy)}:{}),
    websiteAuditText:typeof campaign.websiteAuditText==='string'?campaign.websiteAuditText.slice(0,12000):'',
    editorialShortlist:campaign.editorialShortlist||null,
    ...(campaign.brandIdentity?{brandIdentity:structuredClone(campaign.brandIdentity)}:{}),
    ...(campaign.brandKit?{brandKit:structuredClone(campaign.brandKit)}:{}),
    websiteImages:(campaign.websiteImages||[]).slice(0,8).map(image=>({url:image.url,alt:String(image.alt||'').slice(0,160),rights_confirmed:false,authenticity_verified:false})),
    posts:campaign.plan.posts.map(p=>({day:p.day,theme:p.theme,channel:p.channel,format:p.format,
      objective:p.objective,copyDraft:p.copyDraft||'',callToAction:p.callToAction||'',
      status:'draft',scheduled:false,published:false})),
    creatives:FORMATS.map(([format,title,ratio,direction],i)=>({id:`creative-${i+1}`,format,title,ratio,
      brief:(campaign.creative.prompt+'\nFormat-specific direction: '+direction).slice(0,6000),
      copyDraft:campaign.business,callToAction:campaign.creative.ctaDraft||'Enquire for details',
      status:'draft',assetUrl:null,mediaStatus:'not_generated',approved:false,published:false})),
    canPublish:false,canSpend:false,sourceStatus:'website_observations_require_owner_confirmation'};
}
export function addSupportingImageConcepts(document){
 if(!document||document.version!==1||!Array.isArray(document.creatives))throw new TypeError('Saved campaign required');
 const existing=new Set(document.creatives.map(c=>c.id));
 const hero=document.creatives.find(c=>c.id==='creative-1');
 if(!hero||typeof hero.brief!=='string')throw new TypeError('A saved hero brief is required');
 const base=hero.brief.split('\nFormat-specific direction:')[0];
 const added=FORMATS.slice(4).map(([format,title,ratio,direction],i)=>{
  const id='creative-'+(i+5);
  if(existing.has(id))return null;
  return {id,format,title,ratio,brief:(base+'\nFormat-specific direction: '+direction).slice(0,6000),
   copyDraft:document.business,callToAction:hero.callToAction||'Make an enquiry',
   status:'draft',assetUrl:null,mediaStatus:'not_generated',approved:false,published:false};
 }).filter(Boolean);
 if(!added.length)return document;
 if(document.creatives.length+added.length>8)throw new TypeError('Too many creative concepts');
 return {...document,creatives:[...document.creatives,...added],canPublish:false,canSpend:false};
}
export function editMarketingPost(document,day,patch){
  patchFields(patch,POST_FIELDS);
  const post=document.posts.find(p=>p.day===day);
  if(!post)throw new TypeError('Post not found');
  if(Object.entries(patch).every(([key,value])=>post[key]===value))return document;
  return {...document,posts:document.posts.map(p=>p.day===day?{...p,...patch,status:'draft',scheduled:false,published:false}:p)};
}
export function editMarketingCreative(document,id,patch){
  patchFields(patch,CREATIVE_FIELDS);
  const creative=document.creatives.find(p=>p.id===id);
  if(!creative)throw new TypeError('Creative not found');
  const changed=Object.keys(patch).filter(key=>creative[key]!==patch[key]);
  if(!changed.length)return document;
  // Video briefs also contain voiceover and on-screen words. Their unstructured
  // edits require review again; image-only instructions preserve word review.
  const status=creative.format!=='video_ad'&&changed.every(key=>key==='brief')?creative.status:'draft';
  return {...document,creatives:document.creatives.map(p=>p.id===id?{...p,...patch,status,approved:false,published:false}:p)};
}
/** Explicit owner action: transfer words only, with no inferred claims or media rights. */
export function usePostWordsForCreative(document,id,day){
  const post=document.posts.find(item=>item.day===day);
  const creative=document.creatives.find(item=>item.id===id);
  if(!post)throw new TypeError('Post not found');
  if(!creative)throw new TypeError('Creative not found');
  if(!post.copyDraft.trim())throw new TypeError('Choose a post with words before copying it into this creative.');
  if(post.copyDraft.length>MARKETING_CREATIVE_COPY_LIMIT)
    throw new TypeError('Shorten the post to '+MARKETING_CREATIVE_COPY_LIMIT+' characters or fewer before copying it. Your creative words have been kept.');
  if(creative.copyDraft===post.copyDraft)return document;
  return editMarketingCreative(document,id,{copyDraft:post.copyDraft});
}
export function reviewMarketingCopy(document,type,id){
  const field=type==='post'?'posts':type==='creative'?'creatives':null;
  if(!field)throw new TypeError('Unknown review type');
  const item=document[field].find(p=>(type==='post'?p.day:p.id)===id);
  if(!item)throw new TypeError('Review the copy and call to action first');
  const issue=marketingCopyIssue(item,document.business);
  if(issue)throw new TypeError(issue);
  return {...document,[field]:document[field].map(p=>p===item?{...p,status:'copy_reviewed'}:p),canPublish:false,canSpend:false};
}
export function marketingPlanCsv(document){
  const cell=value=>{
    let s=String(value??'').replace(/[\u0000-\u001f\u007f]/g,' ');
    if(/^[\s\u200b-\u200d\ufeff]*[=+\-@]/u.test(s))s="'"+s;
    return '"'+s.replaceAll('"','""')+'"';
  };
  const rows=[['Business','Day','Channel','Format','Theme','Objective','Copy','Call to action','Copy review','Publishing','Graphic words','Advert supporting line']];
  for(const p of document.posts)rows.push([document.business,p.day,p.channel,p.format,p.theme,p.objective,p.copyDraft,p.callToAction,
    p.status==='copy_reviewed'&&marketingCopyIssue(p,document.business)?'draft':p.status,'Not scheduled',p.graphicText||'',p.supportingLine||'']);
  return '\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
}
/** A readable handoff of one creative's exact text; never a media/rights approval. */
export function marketingCreativeText(document,id){
  const creative=document.creatives.find(item=>item.id===id);
  if(!creative)throw new TypeError('Creative not found');
  return [
    'Creative draft — '+creative.title,
    'Business: '+document.business,
    'Source website: '+document.sourceUrl,
    'Format: '+creative.format+' · '+creative.ratio,
    'Copy review: '+(creative.status==='copy_reviewed'&&!marketingCopyIssue(creative,document.business)?'Owner marked words checked; not independent verification.':'Not checked.'),
    '',
    'Draft text and instructions only. No rendered image or video is included.',
    'Website claims and any date-sensitive details still require owner review in source context.',
    'Media rights, final creative approval, publishing and spend are not granted by this download.',
    '', 'Words', creative.copyDraft,
    '', 'Call to action', creative.callToAction,
    '', 'Picture instructions', creative.brief, '',
  ].join('\n');
}
