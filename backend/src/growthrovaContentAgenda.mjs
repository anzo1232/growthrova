import {strategyConfirmed} from './lib/businessOwnerStrategy.mjs';
import {marketingCopyIssue} from './lib/businessCopyReadiness.mjs';

/** Saved planning dates only; never join them to delivery by date or caption. */
export function contentAgenda(records){
 const items=[],gaps=[];
 for(const record of records){
  const doc=record.document,base={campaignId:record.id,revision:record.revision,updated:record.updated,name:doc.name,goal:doc.goal};
  const date=doc.calendarStartDate||'';
  const start=/^20[2-8]\d-\d{2}-\d{2}$/.test(date)?new Date(date+'T00:00:00Z'):null;
  const valid=start&&!Number.isNaN(start.getTime())&&start.toISOString().slice(0,10)===date;
  const confirmed=strategyConfirmed(doc);
  if(!confirmed||!valid){
   gaps.push({...base,reason:!confirmed?'Review and confirm the business strategy':'Choose and save a calendar start date'});
   continue;
  }
  for(const post of doc.posts){
   const planned=new Date(start.getTime()+(post.day-1)*86400000).toISOString().slice(0,10);
   items.push({...base,day:post.day,date:planned,channel:post.channel,theme:post.theme,
    reviewed:post.status==='copy_reviewed'&&!marketingCopyIssue(post,doc.business)});
  }
 }
 items.sort((a,b)=>a.date.localeCompare(b.date)||a.name.localeCompare(b.name)||a.campaignId.localeCompare(b.campaignId)||a.day-b.day);
 return {items,gaps};
}

export function filterContentAgenda(items,{from='',through='',channel='',review='all'}={}){
 return items.filter(item=>(!from||item.date>=from)&&(!through||item.date<=through)&&
  (!channel||item.channel===channel)&&(review==='all'||item.reviewed===(review==='reviewed')));
}
