/** URL-first art direction: require observed site evidence, never invent claims. */
const trim=(x,n=180)=>typeof x==='string'?x.trim().slice(0,n):'';
const STYLES={
 concierge:{angle:'Discreet luxury editorial',visual:'a discreet fictional luxury hotel arrival at blue hour, sculptural stone and glass architecture, warm champagne interior lighting against deep midnight-blue sky, realistic subtle reflections, no named location or people, striking off-centre composition with clean negative space in the upper third',cta:'Enquire with the concierge'},
 restaurant:{angle:'Appetite and atmosphere',visual:'believable tactile food editorial, natural restaurant light, art-directed table setting',cta:'Explore the menu'},
 beauty:{angle:'Calm, premium self-care',visual:'elevated unbranded beauty still life, natural skin-safe warm light, restrained palette',cta:'Explore treatments'},
 renovation:{angle:'Craftsmanship and reassurance',visual:'credible finished interior materials, accurate architectural geometry and authentic daylight',cta:'Request a consultation'},
 roofing:{angle:'Reliable roofing made simple',visual:'architecturally accurate pitched and flat roof textures, detailed natural slate and roof tile surfaces, practical home context, overcast British weather, restrained credible editorial composition, no invented real completed jobs or workers',cta:'Ask for a roofing quote'},
 other:{angle:'Authentic service value',visual:'considered editorial art direction, believable service or product environment',cta:'Enquire for details'}
};
export function inferCreativeSector(observations={}){
 const text=[observations.title,observations.meta_description,...(Array.isArray(observations.headings)?observations.headings:[]),...(Array.isArray(observations.visible_paragraphs)?observations.visible_paragraphs.slice(0,6):[])].filter(x=>typeof x==='string').join(' ').toLowerCase();
 if(/country club|health club|fitness club/.test(text))return 'country_club';
 if(/plumb|boiler|heating engineer/.test(text))return 'plumbing';
 if(/roofing|roofer|roof repair|flat roof|guttering|roof tile|slate roof|roof inspection/.test(text))return 'roofing';
 if(/concierge|private aviation|luxury travel|exclusive event|premium access platform/.test(text))return 'concierge';
 if(/restaurant|dining|seasonal plates|menu|cafe/.test(text))return 'restaurant';
 if(/beauty|salon|laser clinic|massage|skincare/.test(text))return 'beauty';
 if(/renovation|construction|bathroom installation|kitchen fitting|building contractor/.test(text))return 'renovation';
 return 'other';
}
export function creativeFromWebsiteFindings({sourceUrl='',observations={},businessType='other',objective='enquiries'}={}){
 if(!/^https:\/\/[^\s/]+/i.test(sourceUrl))throw new TypeError('Verified HTTPS provenance required');
 const title=trim(observations.title,120),desc=trim(observations.meta_description,300);
 const headings=Array.isArray(observations.headings)?observations.headings.filter(x=>typeof x==='string').slice(0,8).map(x=>trim(x,130)):[];
 const paragraphs=Array.isArray(observations.visible_paragraphs)?observations.visible_paragraphs.filter(x=>typeof x==='string').slice(0,5).map(x=>trim(x,220)):[];
 const services=Array.isArray(observations.service_links)?observations.service_links.slice(0,7).map(x=>trim(x?.label,90)).filter(Boolean):[];
 if(!title&&(!desc||!headings.length))throw new TypeError('Insufficient extracted website evidence');
 const style=STYLES[businessType]||STYLES.other;
 const facts=[title,desc,...headings,...paragraphs,...services].filter(Boolean);
 const prompt=`Create ONE premium 4:5 commercial image CONCEPT, for internal creative review, from a website-derived brief. Brand page title: ${title||'unavailable'}. Business-described positioning: ${desc||'unavailable'}. Page headings: ${headings.join(' / ')||'unavailable'}. Website body evidence: ${paragraphs.join(' | ')||'unavailable'}. Service-link labels: ${services.join(' | ')||'unavailable'}. Marketing objective: ${trim(objective,40)}. Art direction: ${style.angle}; ${style.visual}. Photographic realism, careful editorial framing, high-quality natural textures, professional negative space for separate editable typography. Never render words or logos inside the image. Do not depict real clients, testimonials, discounts, named establishments, offered stock, completed project results, or guaranteed access unless supplied in an explicitly licensed reference. Generated visual is illustrative, NOT an authentic photo of this business or proof of any service. Avoid generic glossy AI faces, plastic finishes, anatomically incorrect hands and exaggerated luxury props.`;
 return {sourceUrl,observedFacts:facts,provenance:'website_extracted_unconfirmed',ownerConfirmationRequired:true,
  type:businessType,objective:trim(objective,40),creativeAngle:style.angle,ctaDraft:style.cta,
  prompt,provider:'not_selected',format:'4:5',assetProvenance:'synthetic_concept',status:'prompt_ready_not_generated',
  reviewRequirements:['Confirm extracted business facts','Verify product and service imagery','Add authentic logo via controlled design layer','Approve claims and CTA','Approve final result before publishing']};
}
