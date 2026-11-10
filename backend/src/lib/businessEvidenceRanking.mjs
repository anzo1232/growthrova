/** Conservative transcript-only relevance ranking. No visual or ROI claims. */
const STOP=new Set('the and for with that this from your have will they their what when where how who why are was were you our its into about just really very good want more than then them can could would should'.split(' '));
const terms=text=>new Set((typeof text==='string'?text:'').toLowerCase().match(/[a-z]{3,}/g)?.filter(t=>!STOP.has(t))||[]);
export function rankClipEvidence(clips,customer={}){
 if(!Array.isArray(clips))throw new TypeError('Clips required');
 const fields=['desire','objection','proof'];
 const target=Object.fromEntries(fields.map(k=>[k,terms(customer[k])]));
 return clips.map((clip,index)=>{
   // Transcript must be explicitly supplied and timestamp-aligned by the
   // caller; scene titles and generic descriptions are never evidence.
   const transcript=typeof clip.transcript==='string'?clip.transcript.trim():'';
   const words=terms(transcript);
   const matched=fields.map(field=>({field,hits:[...target[field]].filter(word=>words.has(word))}))
     .filter(x=>x.hits.length);
   const duration=Number(clip.end_s)-Number(clip.start_s);
   const coherent=Number.isFinite(duration)&&duration>=20&&duration<=65;
   const points=matched.reduce((n,x)=>n+Math.min(x.hits.length,3),0);
   return {...clip,sourceIndex:index,relevanceScore:transcript?Math.min(points,9):null,
     evidenceMatches:matched,confidence:!transcript?'unassessed':points>0?'keyword-match':'no-match',
     editorialWarning:!coherent?'Review clip completeness and context.':'',
     verifiedOutcome:false};
 }).sort((a,b)=>(b.relevanceScore??-1)-(a.relevanceScore??-1)||a.sourceIndex-b.sourceIndex);
}
