import {organicStatuses,currentOrganicReference} from './businessOrganicQueue.mjs';

/** Editor preparation only. Saved identities are supplied by the private route. */
export function organicWorkMarkdown(doc,{saved,itemIds}={}){
  const work=doc.organicWork||[];
  if(itemIds!==undefined&&(!Array.isArray(itemIds)||!itemIds.length||itemIds.length>30||
    itemIds.some(id=>typeof id!=='string'||!/^[A-Za-z0-9_-]{1,64}$/.test(id))||
    new Set(itemIds).size!==itemIds.length||itemIds.some(id=>!work.some(item=>item.id===id)))){
    throw new TypeError('Choose distinct website work items retained in this campaign');
  }
  // Keep saved campaign order even when a caller selected items in another order.
  const items=itemIds===undefined?work:work.filter(item=>itemIds.includes(item.id));
  if(!items.length)throw new TypeError('No website work is retained in this campaign');
  return ['# Organic work — preparation only','',`Business: ${doc.business}`,
    ...(saved?[`Campaign: ${saved.id}`,`Revision: ${saved.revision}`,
      `Saved update: ${saved.updated}`,`Website: ${doc.sourceUrl||'Not supplied'}`]:[]),
    'Owner-written drafts based on retained research. Claims need review. No site edits or publication performed. Rankings, indexing and AI-search citations are unmeasured.','',
    ...items.flatMap(item=>[`## ${item.title}`,
      ...(saved?[`Work item: ${item.id}`]:[]),
      `Type: ${item.kind}; preparation: ${organicStatuses[item.status]}`,
      `Research ${item.reference.kind==='search'?'is a historical Search Console snapshot; not current website verification':currentOrganicReference(doc,item.reference)?'matches the saved campaign':'has changed since this item was created; recheck'}`,
      `Source: ${item.reference.sourceUrl||'Exact page was not retained'}`,
      ...(saved&&item.reference.kind==='search'?[`Saved search read: ${item.reference.readId}`]:[]),
      `Original research (${item.reference.kind}): ${item.reference.quote}`,'','### Brief',item.brief,
      '','### Draft for review',item.draft,'','### Next action',item.nextAction,''])].join('\n');
}
