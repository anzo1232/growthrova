/**
 * Layout copy from corroborated website evidence only. No inventing offers.
 * Explicitly separate this reference from any final image generation.
 */
const safe=(v,limit=110)=>String(v||'').replace(/\s+/g,' ').trim().slice(0,limit);
export function editorialLayout(candidate, business){
 if(!candidate||typeof candidate!=='object'||!candidate.evidence?.quote)
  throw new TypeError('Sourced direction required before visual composition');
 const evidence=safe(candidate.evidence.quote,240).toLowerCase();
 const hook=safe(candidate.hook);
 const subject=safe(business,35).split(/[|:]/)[0].trim();
 const known=[
  {match:/\bmangal\b/i,requires:/\bmangal\b/i,headline:'THE MANGAL.',eyebrow:'CHARCOAL · CRAFT'},
  {match:/\bsangak\b/i,requires:/\bsangak\b/i,headline:'SANGAK.',eyebrow:'BAKED ON HOT STONES'},
  {match:/\btehran\b/i,requires:/\btehran\b/i,headline:'FROM TEHRAN.',eyebrow:'THE KABAB HOUSE TRADITION'},
  {match:/\bkoobideh\b/i,requires:/\bkoobideh\b/i,headline:'KOOBIDEH.',eyebrow:'PERSIAN KABAB TRADITION'},
  {match:/\bjujeh\b/i,requires:/\bjujeh\b/i,headline:'JUJEH.',eyebrow:'PERSIAN KABAB TRADITION'},
  {match:/\bmezze\b|\bmazeh\b/i,requires:/\bmezze\b|\bmazeh\b/i,headline:'MAZEH.',eyebrow:'THE SHARING TABLE'},
  {match:/\bconcierge\b/i,requires:/\bconcierge\b/i,headline:'CONSIDERED.',eyebrow:'A PERSONAL SERVICE'},
  {match:/\brenovation\b/i,requires:/\brenovation\b/i,headline:'THE CRAFT.',eyebrow:'BUILDING WITH CARE'}
 ];
 const selected=known.find(x=>x.match.test(hook)&&x.requires.test(evidence));
 const fallback=hook.split(/[.:]/)[0].replace(/[!?]/g,'').trim();
 const shortHeadline=selected?.headline||safe(fallback,28).toUpperCase()||'THE EXPERIENCE.';
 return {brand:subject||'BUSINESS',headline:shortHeadline,eyebrow:selected?.eyebrow||'FROM THE BUSINESS STORY',
  sourceQuote:safe(candidate.evidence.quote,100),
  status:'visual-reference-only',publishApproved:false,rightsVerified:false,modelCreditsUsed:0};
}
