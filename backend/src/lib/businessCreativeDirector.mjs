/** Deterministic, category-neutral creative direction and four-week planning.
 * This produces plans, NEVER generated media, verified results or connected posts.
 */
const clean=(value,limit=160)=>typeof value==='string'?value.trim().slice(0,limit):'';
const FORMATS=[
 {format:'image_ad',name:'Premium image advert',ratio:'4:5',angle:'Show the real offer with deliberate editorial art direction'},
 {format:'video_ad',name:'Cinematic short video',ratio:'9:16',angle:'Tell a concise customer-problem-to-solution story'},
 {format:'carousel',name:'Trust-building carousel',ratio:'4:5',angle:'Explain benefits and address a genuine buying objection'},
 {format:'graphic',name:'Educational brand graphic',ratio:'4:5',angle:'Teach a useful fact without unsupported claims'},
 {format:'image_ad',name:'Conversion image variation',ratio:'1:1',angle:'Show an approved differentiator with a clear next action'}
];
const MODEL_OPTIONS={
 image_ad:['higgsfield-marketing-image','brand-reference-image-provider'],
 video_ad:['higgsfield-marketing-video','runway-or-veo-benchmark'],
 carousel:['brand-layout-engine','higgsfield-marketing-image'],
 graphic:['brand-layout-engine','typography-specialist-provider']
};
export function creativeDirector({business='',offer='',audience='',goal='enquiries',differentiator='',assetMode='mixed',variationCount=4,confirmed=false}={}){
 const name=clean(business,120),product=clean(offer),customer=clean(audience),difference=clean(differentiator);
 if(!confirmed||!name||!product||!customer)throw new TypeError('Confirm the business, offer and audience before creating a campaign');
 if(!Number.isInteger(variationCount)||variationCount<3||variationCount>5)throw new TypeError('Choose 3–5 creative variations');
 if(!['mixed','authentic','generated'].includes(assetMode))throw new TypeError('Unknown asset mode');
 const formatSet=variationCount===3?[0,1,2]:variationCount===4?[0,1,2,3]:[0,1,2,3,4];
 const variations=formatSet.map((index,i)=>{
   const f=FORMATS[index];
   return {id:`variation-${i+1}`,format:f.format,title:f.name,ratio:f.ratio,angle:f.angle,
    sourcePolicy:assetMode==='authentic'?'AUTHENTIC_REFERENCE_REQUIRED':assetMode==='generated'?'SYNTHETIC_VISUALS_DISCLOSED':'AUTHENTIC_AND_SYNTHETIC_LABELED_SEPARATELY',
    brief:`Create ${f.name.toLowerCase()} for ${name}. Verified offer supplied by owner: ${product}. Audience: ${customer}. ${difference?`Business-supplied differentiator to verify: ${difference}.`:''} Creative angle: ${f.angle}. Design with considered composition, ample negative space, authentic product detail and precise typography; keep logos and factual text in controlled editable layout layers. Never invent testimonials, people, offers, ratings or outcomes.`,
    providerCandidates:MODEL_OPTIONS[f.format],providerSelection:'benchmark_pending_no_winner_claimed',
    qualityStatus:'awaiting_authentic_brand_assets_and_human_review',generated:false,published:false};
 });
 const weekly=[
  {week:1,theme:'Introduce the genuine offer',objective:'awareness',activities:['Verify the offer and brand assets','Create and review hero image creative','Prepare first approved social post']},
  {week:2,theme:'Explain why customers should care',objective:'consideration',activities:['Create an explanatory carousel','Clarify common customer questions','Review accuracy and approve educational copy']},
  {week:3,theme:'Build credible trust',objective:'trust',activities:['Find permissioned examples or product demonstrations','Publish only evidence-backed trust content','Review audience questions']},
  {week:4,theme:'Invite the next step and learn',objective:clean(goal,40)||'enquiries',activities:['Prepare booking or enquiry creative','Verify and approve call to action','Review real leads, bookings or other available outcomes']}
 ];
 return {version:1,positioning:'AI creative director',business:name,offer:product,audience:customer,assetMode,variations,
  marketingPlan:{durationWeeks:4,weekly,objective:clean(goal,40)||'enquiries',status:'draft_not_scheduled'},
  publication:'owner_approval_required',spend:'owner_approval_required',mediaGenerated:false,
  notice:'Model candidates are not quality rankings. No image, video, post, website audit or paid campaign has run.'};
}
