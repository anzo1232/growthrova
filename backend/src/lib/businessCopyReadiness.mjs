import rules from './businessCopyReadiness.json' with {type:'json'};

/** Basic editorial blockers only, never a claim of writing quality or accuracy.
 * Shared rules are also enforced when the existing document store normalises saves.
 * Sources stay in the document; no automatic rewriting/removal of owner words. */
export function marketingCopyIssue(item,business){return wordingIssue(item,business,false);}

function wordingIssue(item,business,graphic){
 const copy=(item?.copyDraft||'').trim();
 const normalise=value=>value.replace(/\s+/g,' ').trim().toLowerCase();
 if(copy.length<3||normalise(copy)===normalise(business||''))return rules.messages.unwritten;
 if(copy.split(/\r?\n/).some(line=>rules.internalLinePrefixes.some(prefix=>line.trim().toLowerCase().startsWith(prefix))))return rules.messages.notes;
 if(!graphic&&/^(?:[^.!?]+\?\s*)+$/.test(copy))return rules.messages.question;
 if(/^[“"][^“”"]+[”"]\s*[.!]?$/.test(copy))return rules.messages.quotation;
 if(!item?.callToAction?.trim())return rules.messages.cta;
 for(const field of ['graphicText','supportingLine']){
  if(item?.[field]?.trim()){
   const issue=wordingIssue({copyDraft:item[field],callToAction:item.callToAction},business,true);
   if(issue)return issue;
  }
 }
 return '';
}
