/** Export owner-visible draft dates; does not schedule or publish content. */
import {MARKETING_POST_COPY_LIMIT} from './businessMarketingDocument.mjs';
const LIMIT=2048;
function dateFrom(value){
 if(typeof value!=='string'||!/^(20[2-8][0-9])-([01][0-9])-([0-3][0-9])$/.test(value))throw new TypeError('Choose a valid calendar start date');
 const [yy,mm,dd]=value.split('-').map(Number);
 const date=new Date(Date.UTC(yy,mm-1,dd));
 if(date.getUTCFullYear()!==yy||date.getUTCMonth()+1!==mm||date.getUTCDate()!==dd)throw new TypeError('Invalid calendar date');
 return date;
}
export function isPublicationStartDate(value){
 try{dateFrom(value);return true;}catch{return false;}
}
function iso(date){return date.toISOString().slice(0,10);}
const safe=(value,max=LIMIT)=>String(value||'').replace(/[\x00-\x08\x0B-\x1F\x7F]/g,' ').trim().slice(0,max);
const eventText=(value,max=LIMIT)=>safe(value,max).replace(/\\/g,'\\\\').replace(/\r\n|\r|\n/g,'\\n').replace(/;/g,'\\;').replace(/,/g,'\\,');
const dayDigits=date=>date.replaceAll('-','');
function fold(line){
 // Each content line is <= 75 octets, preserving Unicode code-point boundaries.
 const lines=[];let row='',bytes=0;
 for(const codePoint of line){const size=new TextEncoder().encode(codePoint).length;if(bytes+size>74){lines.push(row);row=' '+codePoint;bytes=1+size;}else{row+=codePoint;bytes+=size;}}
 if(row)lines.push(row);
 return lines.join('\r\n');
}
// Shared wire formatting for the business-wide saved planning handoff.
export {eventText as calendarEventText,fold as foldCalendarLine};
export function createPublicationCalendar(posts,startDate){
 if(!Array.isArray(posts)||posts.length!==30||new Set(posts.map(x=>x?.day)).size!==30||posts.some(p=>!Number.isInteger(p?.day)||p.day<1||p.day>30))throw new TypeError('A complete 30-day plan is needed');
 const base=dateFrom(startDate);
 return [...posts].sort((a,b)=>a.day-b.day).map(p=>{
  const date=new Date(base.getTime()+(p.day-1)*86400000);
  const channel=safe(p.channel,50),theme=safe(p.theme,200),caption=safe(p.copyDraft,MARKETING_POST_COPY_LIMIT),cta=safe(p.callToAction,240);
  if(!channel||!theme||!caption)throw new TypeError('Incomplete calendar post');
  return {day:p.day,date:iso(date),channel,theme,caption,cta,status:'not_scheduled',published:false};
 });
}
export function publicationCalendarIcs(calendar,{business,sourceUrl,campaignId,revision,updated}={}){
 if(!Array.isArray(calendar)||calendar.length!==30)throw new TypeError('Select a complete calendar');
 if(typeof campaignId!=='string'||!/^[a-f0-9]{32}$/.test(campaignId))throw new TypeError('A saved campaign identity is required for calendar reminders');
 if(!Number.isInteger(revision)||revision<1||revision>2147483648)throw new TypeError('A saved campaign revision is required for calendar reminders');
 if(typeof updated!=='number'||!Number.isFinite(updated)||updated<=0||updated>=253402300800)throw new TypeError('A saved campaign timestamp is required for calendar reminders');
 // Persisted metadata makes unchanged re-exports deterministic. Never invent a
 // fresh save time on download; revision 1 is the initial (sequence 0) snapshot.
 const stamp=new Date(Math.floor(updated)*1000).toISOString().replace(/[-:]/g,'').replace('.000','');
 const name=safe(business,120),origin=safe(sourceUrl,512);
 if(!name)throw new TypeError('Business name required');
 const lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Clippr Business//Draft Content Plan//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:'+eventText(name+' — draft post ideas')];
 for(const entry of calendar){
  if(entry.status!=='not_scheduled'||entry.published!==false)throw new TypeError('Only unpublished drafts can be exported');
  const date=dateFrom(entry.date);
  const after=iso(new Date(date.getTime()+86400000));
  // Separate campaigns must never share event identities, even for the same
  // business and dates. Reopening/renaming a campaign keeps the same identity.
  const uid='draft-'+campaignId+'-'+entry.day+'-'+dayDigits(entry.date)+'@growthrova.com';
  // Bound each field independently; a total-description cut can remove the CTA
  // and source even when every individual field is valid.
  const desc=['Draft only; NOT scheduled or published.','Platform: '+safe(entry.channel,50),'Caption: '+safe(entry.caption,MARKETING_POST_COPY_LIMIT),'CTA: '+safe(entry.cta,240),origin?'Source: '+origin:''].filter(Boolean).join('\n');
  lines.push('BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,'LAST-MODIFIED:'+stamp,'SEQUENCE:'+(revision-1),
    'DTSTART;VALUE=DATE:'+dayDigits(entry.date),'DTEND;VALUE=DATE:'+dayDigits(after),
    'SUMMARY:'+eventText('DRAFT '+entry.channel+': '+entry.theme),
    'DESCRIPTION:'+eventText(desc,4096),'STATUS:TENTATIVE','TRANSP:TRANSPARENT','END:VEVENT');
 }
 lines.push('END:VCALENDAR');
 return lines.map(fold).join('\r\n')+'\r\n';
}
