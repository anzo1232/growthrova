import {calendarEventText as text,foldCalendarLine as fold} from './businessPublicationCalendar.mjs';

const iso=date=>date.toISOString().slice(0,10);
function firstOfMonth(month){
 if(!/^20\d{2}-(0[1-9]|1[0-2])$/.test(month))throw new TypeError('Choose a valid planning month');
 return new Date(month+'-01T00:00:00Z');
}
export function shiftPlanningMonth(month,offset){
 const date=firstOfMonth(month);date.setUTCMonth(date.getUTCMonth()+offset);
 return iso(date).slice(0,7);
}
/** Monday-first rows include empty dates; neighboring-month cells stay blank. */
export function contentCalendarWeeks(month,items){
 const first=firstOfMonth(month),offset=(first.getUTCDay()+6)%7;
 const next=new Date(first);next.setUTCMonth(next.getUTCMonth()+1);
 const days=Math.round((next-first)/86400000),weeks=[];
 const byDate=new Map();
 for(const item of items){
  if(!byDate.has(item.date))byDate.set(item.date,[]);
  byDate.get(item.date).push(item);
 }
 for(let cell=0;cell<Math.ceil((offset+days)/7)*7;cell++){
  if(cell%7===0)weeks.push([]);
  const day=cell-offset+1;
  const date=day>=1&&day<=days?month+'-'+String(day).padStart(2,'0'):'';
  weeks.at(-1).push({date,day,items:byDate.get(date)||[]});
 }
 return weeks;
}

/** RFC 5545, saved-only all-day reminders. No METHOD, attendees, alarms or sync.
 * Use the existing single-campaign event identity so switching export scope
 * doesn't invent a second event. Calendar-client import/update behavior varies.
 */
export function contentAgendaIcs(items){
 if(!Array.isArray(items)||!items.length||items.length>3000)throw new TypeError('Choose 1–3000 saved planning items');
 const seen=new Set(),lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Growthrova//Saved Content Plan//EN','CALSCALE:GREGORIAN'];
 for(const item of items){
  if(!/^[a-f0-9]{32}$/.test(item.campaignId)||!Number.isInteger(item.revision)||item.revision<1||item.revision>2147483648||
    !Number.isInteger(item.day)||item.day<1||item.day>30||!Number.isFinite(item.updated)||item.updated<=0||item.updated>=253402300800)
   throw new TypeError('Refresh saved plans before exporting calendar reminders');
  const date=new Date(item.date+'T00:00:00Z');
  if(!/^20\d{2}-\d{2}-\d{2}$/.test(item.date)||!Number.isFinite(date.getTime())||iso(date)!==item.date)
   throw new TypeError('A saved planning date is invalid');
  const digits=item.date.replaceAll('-',''),uid=`draft-${item.campaignId}-${item.day}-${digits}@growthrova.com`;
  if(seen.has(uid))throw new TypeError('Duplicate saved planning item');
  seen.add(uid);
  const stamp=new Date(Math.floor(item.updated)*1000).toISOString().replace(/[-:]/g,'').replace('.000','');
  const end=iso(new Date(date.getTime()+86400000)).replaceAll('-','');
  const description=[`Campaign: ${item.name}`,`Saved revision: ${item.revision}`,`Goal: ${item.goal}`,`Plan day: ${item.day}`,
   `Copy: ${item.reviewed?'Reviewed':'Needs review'}`,'Planning reminder only. This does not schedule or publish content. Review wording, artwork and separate delivery approval in Growthrova.'].join('\n');
  lines.push('BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,'LAST-MODIFIED:'+stamp,'SEQUENCE:'+(item.revision-1),
   'DTSTART;VALUE=DATE:'+digits,'DTEND;VALUE=DATE:'+end,'SUMMARY:'+text(`DRAFT ${item.channel}: ${item.theme||'Untitled post'}`),
   'DESCRIPTION:'+text(description,4096),'STATUS:TENTATIVE','TRANSP:TRANSPARENT','END:VEVENT');
 }
 return [...lines,'END:VCALENDAR'].map(fold).join('\r\n')+'\r\n';
}
