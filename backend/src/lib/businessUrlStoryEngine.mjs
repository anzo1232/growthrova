/** Website-specific editorial research; planning only, no publishing or spending. */
const clean=(x,max=400)=>{
 if(typeof x!=='string')return '';
 const value=x.replace(/\s+/g,' ').trim();
 if(value.length<=max)return value;
 const portion=value.slice(0,max);
 return (/\S/.test(value[max])?portion.replace(/\s+\S*$/,''):portion).trimEnd();
};
export const DATE_SENSITIVE_SOURCE_WARNING='Date-sensitive source: current dates and availability are unknown. Confirm with the owner before using this wording.';
// Keep quotes as exact substrings for provenance checks. A source can itself be
// clipped by extraction; never turn its final partial word into finished copy.
function excerpt(value,max=240,topic,preferred,topics=[]){
 // A short paragraph can still cover several different services. Quote the
 // relevant sentence in that case, rather than repeating the whole paragraph
 // for each direction. Keep single-topic context and qualifications together.
 const multipleTopics=topics.filter(pattern=>pattern.test(value)).length>1;
 if(value.length<=max&&!multipleTopics)return value;
 // Keep the sentence that earned this service direction, rather than replacing
 // a useful later detail with a generic greeting at the start of the paragraph.
 const sentences=(value.match(/.*?[.!?](?:\s+|$)|.+$/g)||[]).map(x=>x.trim());
 value=sentences.find(x=>preferred?.test(x))||sentences.find(x=>topic?.test(x))||value;
 if(value.length<=max)return value;
 const sentence=value.match(/^.*?[.!?](?=\s|$)/)?.[0];
 if(sentence&&sentence.length<=max)return sentence;
 const portion=value.slice(0,max+1);
 const boundary=portion.search(/\s+\S*$/);
 return (boundary>0?portion.slice(0,boundary):value.slice(0,max)).trimEnd();
}
function restaurantLabel(evidence){
 // Quote the actual phrase rather than guessing whether it is a venue name,
 // cuisine or location. Never turn "Thai restaurant" into a verified brand.
 const phrase=evidence.match(/\b(?:[Oo]ur |[Tt]he )?(\p{Lu}[\p{L}\p{N}'’&-]*(?: \p{Lu}[\p{L}\p{N}'’&-]*){0,3}) restaurant\b/u);
 // Leave room for the question within the persisted 160-character hook limit.
 return phrase&&phrase[0].length<=100&&!/^(Our|The|This|A|An)$/.test(phrase[1])?phrase[0]:'';
}
function clubHook(key,evidence,fallback){
 if(key==='membership'&&/types of membership|membership options/i.test(evidence))return 'Membership options: what should you compare?';
 if(key==='dining'){
  const label=restaurantLabel(evidence);
  if(label)return '“'+label+'”: what would you like to explore?';
 }
 if(key==='spa'&&/\b(?:facials?|massages?|body treatments?)\b/i.test(evidence))return 'Spa treatments: which options would you like to discuss?';
 if(key==='fitness'&&/group exercise classes/i.test(evidence))return 'Group exercise classes: what fits your routine?';
 return fallback;
}
function tradeHook(key,evidence,fallback){
 // Literal service labels focus a question without promising the work, price
 // or availability. Sparse evidence keeps the neutral category question.
 const labels={
  repairs:/\b(?:plumbing (?:repairs?|inspections?|services?)|(?:leak|drain|pipe) (?:repairs?|inspections?|detection|clearance|cleaning))\b/i,
  heating:/\b(?:boiler|heating) (?:servicing|repairs?|installation|maintenance|checks?|services?)\b/i,
  scope:/\b(?:(?:written|itemised|detailed) )?(?:quotes?|quotations?|estimates?)\b/i
 };
 const label=labels[key]?.exec(evidence)?.[0];
 return label?'“'+label+'”: what should you ask?':fallback;
}
const patterns={
 country_club:[
  ['membership',/member|joining/i,'Questions before joining the club.'],
  ['fitness',/fitness|gym|classes|training/i,'Explore the fitness options.'],
  ['spa',/\b(?:spa|treatments?|wellness)\b/i,'What to ask about the spa.'],
  ['dining',/dining|restaurant|menu/i,'Explore dining at the club.']],
 plumbing:[
  ['repairs',/plumb|leak|drain/i,'Describe the plumbing issue before enquiring.'],
  ['heating',/heating|boiler/i,'Questions about heating work.'],
  ['scope',/\b(?:quotations?|quotes?|estimates?)\b|contact|enquir/i,'Clarify the scope before agreeing work.']],
 concierge:[
  ['message',/one message|brief message|one enquiry|one inquiry/i,'One message. Consider the possibilities.'],
  ['travel',/private aviation|travel|villa|hotel|yacht/i,'Travel arranged around the request.'],
  ['events',/exclusive events|concerts|formula 1|ringside|paddock/i,'Experiences worth planning for.'],
  ['dining',/dining|restaurants|last-minute table/i,'Private dining, considered.'],
  ['transfers',/transfers|chauffeur|fleet of transfers/i,'From the venue to the journey there.'],
  ['service',/concierge|handle every detail|zero stress/i,'The concierge behind the occasion.']],
 restaurant:[
  ['cuisine',/lebanese|italian|japanese|thai|indian|vietnamese|turkish|greek|persian|iranian|tehran/i,'From the cuisine to the table.'],
  ['heritage',/family recipes|grandmother|mother|heritage|traditional recipes|iranian childhood|hole.in.the.wall|tehran kabab/i,'The recipes and places behind the food.'],
  ['sharing',/sharing|share|mezze|ma[z|zh]eh|small plates/i,'A table built for sharing.'],
  ['dish',/kebbeh|shish taouk|pasta|pizza|pho|sushi|tandoori|koobideh|jujeh|kashk.e.bademjoon|mirza ghasemi|khoresht/i,'Get to know the dishes.'],
  ['bread',/taftoon|sangak|naan|fresh bread|flatbread|tandoor/i,'The bread is part of the experience.'],
  ['method',/charcoal|tandoor|grill|kabab house|kabab shop/i,'Watch the craft and the fire.'],
  ['hospitality',/restaurant|dining|booking|book a table/i,'The table is yours to discover.'],
  ['catering',/catering|private events/i,'Bring the experience together.']],
 beauty:[['consultation',/consultation|assessment|skin analysis/i,'Understand your options first.'],['services',/facial|treatment|skin|laser|massage/i,'A closer look at the treatment.'],['trust',/qualified|certified|clinician|professional/i,'What to ask before booking.']],
 renovation:[['craft',/renovation|construction|craft|builders|carpentry/i,'The craft behind the detail.'],['project',/kitchen|bathroom|extension|refurbishment/i,'Plan the project, not just the finish.'],['trust',/quotation|quote|consultation|scope/i,'Questions before the first quotation.']],
 roofing:[['issues',/roof|gutter|slate|tile|leak/i,'A problem worth understanding.'],['weather',/storm|rain|weather/i,'What to check after bad weather.'],['scope',/quote|estimate|inspection|repair/i,'Questions for an inspection.']],
 other:[['offer',/service|product|event|experience|course/i,'Understand the actual offering.']]
};
export function buildWebsiteStory(o={},sector='other',pages=[]){
 const pageFields=(o,sourceUrl='',freshness={})=>[
  {where:'description',value:o.meta_description},
  ...(Array.isArray(o.headings)?o.headings.slice(0,24).map((value,i)=>({where:'heading '+(i+1),value})):[]),
  ...(Array.isArray(o.visible_paragraphs)?o.visible_paragraphs.slice(0,40).map((value,i)=>({where:'paragraph '+(i+1),value})):[]),
  ...(Array.isArray(o.service_links)?o.service_links.slice(0,20).map((item,i)=>({where:'service link '+(i+1),value:item?.label})):[])
 // Search the bounded source paragraph before choosing the short display quote.
 // The extractor and research import already share a 1,200-character ceiling.
 ].map(x=>({...x,sourceUrl,value:clean(x.value,1200),
  // Use the extractor's bounded findings, not a second date/expiry heuristic.
  // Match the original field: a short quote may omit its seasonal caveat.
  sourceDateSensitive:Array.isArray(freshness?.seasonal_excerpts)&&freshness.seasonal_excerpts.slice(0,8)
   .some(quote=>typeof quote==='string'&&clean(quote,1200)===clean(x.value,1200))
 })).filter(x=>x.value.length>=12);
 // Use each bounded page independently: a full homepage must not crowd out
 // secondary evidence or attribute it to the homepage after merging.
 const fields=pages.length?pages.slice(0,4).flatMap(page=>pageFields(page.observations||{},page.source_url,page.freshness)):pageFields(o);
 const differentiators=[];
 const richestToken={
  membership:/types of membership|membership options/i,
  dining:/\brestaurant\b[^.!?]*\b(?:brings|serves|offers|influences|menu)\b|\b(?:lunch|dinner|tasting|seasonal|sharing) menu\b/i,
  scope:/\b(?:quotations?|quotes?|estimates?)\b/i,
  bread:/taftoon|sangak|tandoor/i,
  dish:/koobideh|jujeh|kebbeh|shish taouk/i,
  heritage:/tehran|family recipes|iranian childhood/i,
  sharing:/ma[z|zh]eh|mezze|sharing plates/i
 };
 const directions=patterns[sector]||patterns.other;
 // Contact/enquiry wording can qualify the same service; only explicit
 // quotation wording counts as a separate scope topic for sentence selection.
 const topics=directions.map(([key,pattern])=>key==='scope'?richestToken.scope:pattern);
 for(const [key,pattern,hook] of directions){
  const pathTerms={membership:/member|join/i,fitness:/fitness|gym|class|training/i,spa:/spa|treatment/i,dining:/dine|dining|food|restaurant/i,repairs:/plumb|leak|drain/i,heating:/heat|boiler/i};
  const pathScore=item=>{
   try{return pathTerms[key]?.test(new URL(item.sourceUrl).pathname)?1:0;}catch{return 0;}
  };
  const matching=fields.filter(x=>pattern.test(x.value)).sort((a,b)=>pathScore(b)-pathScore(a));
  // A dedicated service page should inform its own direction before generic homepage copy.
  const bestScore=matching.length?pathScore(matching[0]):0;
  const specific=bestScore?matching.filter(x=>pathScore(x)===bestScore):matching;
  const preferred=richestToken[key];
  const item=specific.find(x=>x.where.startsWith('paragraph')&&preferred?.test(x.value))||
    specific.find(x=>x.where.startsWith('paragraph')&&x.value.length>=65)||specific.find(x=>x.where.startsWith('paragraph'))||specific[0];
  if(item){
   const evidence=excerpt(item.value,240,pattern,preferred,topics);
   const sourceHook=sector==='country_club'?clubHook(key,evidence,hook):sector==='plumbing'?tradeHook(key,evidence,hook):hook;
   differentiators.push({key,hook:sourceHook,
    sourceLabel:item.where,sourceUrl:item.sourceUrl,evidence,evidenceShortened:evidence!==item.value,sourceDateSensitive:item.sourceDateSensitive,ownerConfirmed:false});
  }
 }
 if(!differentiators.length&&fields[0]){
  const evidence=excerpt(fields[0].value);
  differentiators.push({key:'source_positioning',hook:'What this business says it offers',sourceLabel:fields[0].where,sourceUrl:fields[0].sourceUrl,evidence,evidenceShortened:evidence!==fields[0].value,sourceDateSensitive:fields[0].sourceDateSensitive,ownerConfirmed:false});
 }
 const first=differentiators[0];
 const familiar=differentiators.find(x=>['heritage','dish','transfers','services'].includes(x.key))||differentiators[1]||first;
 const chooser=differentiators.find(x=>['travel','cuisine','project'].includes(x.key))||differentiators[2]||familiar;
 const angle=(type,reason,item)=>item?{audience:type,purpose:reason,hook:item.hook,evidence:item.evidence,evidenceShortened:item.evidenceShortened,sourceDateSensitive:item.sourceDateSensitive,sourceUrl:item.sourceUrl,visualRule:'Show the actual service category; label synthetic footage as illustrative'}:null;
 const selected=[];
 const select=(type,purpose,item)=>{
  if(item&&!selected.some(x=>x.key===item.key))selected.push({key:item.key,...angle(type,purpose,item)});
 };
 select('First-time customer','Make the service legible',first);
 select('Familiar customer','Show depth, not generic aesthetics',familiar);
 select('Ready to enquire','Explain one real next step',chooser);
 for(const item of differentiators)select('Service-specific',item.key,item);
 const angles=selected.map(({key,...data})=>data);
 // Three non-identical question-led variations only when sufficient evidence exists.
 if(angles.length>=3){
  angles.push({...angle('First-time customer','Before you enquire',first),hook:'What should your first enquiry include?',
   visualRule:'Show the first contact process; never show fictional confirmed bookings'});
  angles.push({...angle('Experienced customer','Consideration',familiar),hook:'Which details matter most to you?',
   visualRule:'Show a different factual service detail, not a repeated hero'});
  angles.push({...angle('Ready to enquire','Next step',chooser),hook:'What happens after you get in touch?',
   visualRule:'Show the stated service process; avoid unsupported promises'});
 }
 return {
  title:clean(o.title,120),sector,evidenceStatus:differentiators.length?'website_evidence_unconfirmed':'insufficient_website_evidence',
  differentiators,angles:angles.filter(Boolean).slice(0,9),generatedAssets:0,published:false,spendAuthorised:false,
  rules:['Check every website claim with the owner before publishing','Write separate first-time and knowledgeable-audience angles',
   'Vary subject, shot and copy, not just a background template',
   'Never imply illustrative scenes are actual jobs, venues, dishes, customers or outcomes',
   'Never treat examples in a portfolio as confirmed bookable access']
 };
}
/** Display boundaries stay separate from the literal quote used for source matching. */
export function websiteExcerptText(item){
 return 'Website excerpt (unconfirmed'+(item.evidenceShortened?'; shortened':'')+'): “'+item.evidence+'”'+
  (item.sourceDateSensitive?'\n'+DATE_SENSITIVE_SOURCE_WARNING:'');
}
export function storyMarkdown(s){
 return ['## URL-specific creative research (owner review needed)',
  'Website claims are unconfirmed and are not automatically usable as advertising proof.',
  ...s.differentiators.map(x=>'- '+x.hook+' — '+x.sourceLabel+(x.sourceUrl?' ('+x.sourceUrl+')':'')+': '+websiteExcerptText(x)),
  '### Distinct audience hooks',
  ...s.angles.slice(0,6).map(x=>'- '+x.audience+': '+x.hook),
  '### Safeguards',...s.rules.map(x=>'- '+x)].join('\n').slice(0,5600);
}
