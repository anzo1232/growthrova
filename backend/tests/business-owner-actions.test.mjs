import test from 'node:test';import assert from 'node:assert/strict';
import {createPublicationCalendar,publicationCalendarIcs} from '../src/lib/businessPublicationCalendar.mjs';
import {auditBusinessWebsite,suggestWebsiteTitle} from '../src/lib/businessSiteAudit.mjs';

const posts=Array.from({length:30},(_,i)=>({day:i+1,channel:i%2?'Facebook':'Instagram',theme:'Roofing tip '+(i+1),copyDraft:'Check your roof safely. Ask for a proper inspection.',callToAction:'Request a roofing quote',status:'draft',published:false,scheduled:false}));
test('separate saved campaigns have distinct reminders and reopening retains their identities',()=>{
 const plan=createPublicationCalendar(posts,'2026-11-02');
 const ids=ics=>ics.replace(/\r\n /g,'').split('\r\n').filter(line=>line.startsWith('UID:'));
 const first=publicationCalendarIcs(plan,{business:'Harbour Roofing',campaignId:'a'.repeat(32),revision:1,updated:1793491200});
 const second=publicationCalendarIcs(plan,{business:'Harbour Roofing',campaignId:'b'.repeat(32),revision:1,updated:1793491200});
 assert.equal(new Set([...ids(first),...ids(second)]).size,60);
 const reopened=publicationCalendarIcs(JSON.parse(JSON.stringify(plan)),{business:'Harbour Roofing renamed',campaignId:'a'.repeat(32),revision:1,updated:1793491200});
 assert.deepEqual(ids(reopened),ids(first));
 assert.equal(publicationCalendarIcs(plan,{business:'Harbour Roofing',campaignId:'a'.repeat(32),revision:1,updated:1793491200}),first);
 assert.throws(()=>publicationCalendarIcs(plan,{business:'Harbour Roofing'}),/saved campaign/i);
 assert.throws(()=>publicationCalendarIcs(plan,{business:'Harbour Roofing',campaignId:'bad\r\nUID:injected'}),/saved campaign/i);
});
test('saved copy revisions keep reminder IDs but advance their revision and stored timestamp',()=>{
 const plan=createPublicationCalendar(posts,'2026-11-02');
 const meta={business:'Harbour Roofing',campaignId:'a'.repeat(32),revision:1,updated:1793491200};
 const first=publicationCalendarIcs(plan,meta).replace(/\r\n /g,'');
 const edited=plan.map(p=>p.day===1?{...p,caption:'Ask about gutter repairs',cta:'Contact the workshop'}:p);
 const next=publicationCalendarIcs(edited,{...meta,revision:2,updated:1793577600}).replace(/\r\n /g,'');
 const lines=(text,key)=>text.split('\r\n').filter(line=>line.startsWith(key+':'));
 assert.deepEqual(lines(next,'UID'),lines(first,'UID'));
 assert.deepEqual(lines(first,'SEQUENCE'),Array(30).fill('SEQUENCE:0'));
 assert.deepEqual(lines(next,'SEQUENCE'),Array(30).fill('SEQUENCE:1'));
 assert.deepEqual(lines(first,'DTSTAMP'),Array(30).fill('DTSTAMP:20261101T000000Z'));
 assert.deepEqual(lines(next,'LAST-MODIFIED'),Array(30).fill('LAST-MODIFIED:20261102T000000Z'));
 assert.ok(next.includes('Caption: Ask about gutter repairs\\nCTA: Contact the workshop'));
 assert.equal(publicationCalendarIcs(edited,{...meta,revision:2,updated:1793577600}).replace(/\r\n /g,''),next);
 for(const revision of [undefined,0,-1,1.5,'2',2147483649])assert.throws(()=>publicationCalendarIcs(plan,{...meta,revision}),/saved campaign revision/i);
 for(const updated of [undefined,null,'1793491200',NaN,Infinity,-1,253402300800])assert.throws(()=>publicationCalendarIcs(plan,{...meta,updated}),/saved campaign timestamp/i);
});
test('owner can make a calendar plan with thirty actual dates, no implied publishing',()=>{
 const plan=createPublicationCalendar(posts,'2026-11-02');
 assert.equal(plan.length,30);
 assert.equal(plan[0].date,'2026-11-02');assert.equal(plan[29].date,'2026-12-01');
 assert.equal(plan[0].status,'not_scheduled');
 assert.ok(plan.every(p=>p.status==='not_scheduled'&&!p.published));
});
test('long calendar reminders retain complete caption, CTA and source with legal Unicode folding',()=>{
 const caption='Owner direction: '+ 'é'.repeat(2900)+' END CAPTION';
 const cta='Ask about servicing; '+ 'c'.repeat(195)+' END CTA';
 const source='https://example.org/'+ 's'.repeat(460)+'?end=source';
 const plan=createPublicationCalendar(posts.map(p=>({...p,copyDraft:caption,callToAction:cta})),'2026-11-02');
 assert.equal(plan[0].caption,caption);
 const ics=publicationCalendarIcs(plan,{business:'Workshop',sourceUrl:source,campaignId:'a'.repeat(32),revision:1,updated:1793491200});
 for(const line of ics.split('\r\n'))assert.ok(Buffer.byteLength(line)<=75);
 const descriptions=ics.replace(/\r\n /g,'').split('\r\n').filter(line=>line.startsWith('DESCRIPTION:'));
 assert.equal(descriptions.length,30);
 for(const line of descriptions){
  assert.ok(line.includes(caption));
  assert.ok(line.includes('CTA: '+cta.replaceAll(';','\\;')));
  assert.ok(line.endsWith('Source: '+source));
 }
});
test('calendar export creates legal all-day events with safe description and explicit draft status',()=>{
 const plan=createPublicationCalendar(posts,'2026-11-02');
 const ics=publicationCalendarIcs(plan,{business:'Harbour Roofing',sourceUrl:'https://harbour.example.org',campaignId:'a'.repeat(32),revision:1,updated:1793491200});
 assert.match(ics,/BEGIN:VCALENDAR\r\nVERSION:2.0\r\n/);
 assert.equal((ics.match(/BEGIN:VEVENT/g)||[]).length,30);
 assert.match(ics,/DTSTART;VALUE=DATE:20261102/);
 assert.match(ics,/Draft only\\; NOT scheduled or published/i);
 assert.doesNotMatch(ics,/VALARM|RRULE|STATUS:CONFIRMED/);
});
test('calendar escapes untrusted website text, separates all-day dates and rejects invalid inputs',()=>{
 const bad=[...posts];bad[0]={...bad[0],theme:'Leaky roof; inspect, repair\\avoid\nclimbing'};
 const output=publicationCalendarIcs(createPublicationCalendar(bad,'2026-11-02'),{business:'Roofer',sourceUrl:'https://harbour.example.org',campaignId:'a'.repeat(32),revision:1,updated:1793491200});
 assert.match(output,/Leaky roof\\; inspect\\, repair/);
 assert.ok(output.includes('\\nclimbing'));
 assert.throws(()=>createPublicationCalendar(posts,'2026-02-30'));
 assert.throws(()=>createPublicationCalendar(posts,'2026-11-02\nEND:VEVENT'));
});
test('page title suggestion uses only observed brand and services',()=>{
 const info={source_url:'https://harbour.example.org',observations:{title:'Harbour Roofing',meta_description:'Roof repairs and guttering in Portsmouth for local homeowners.',headings:['Roof repairs and guttering']}};
 const suggestion=suggestWebsiteTitle(info);
 assert.match(suggestion,/Harbour Roofing/);
 assert.match(suggestion,/Roof Repairs/i);
 assert.ok(suggestion.length<=65);
 assert.doesNotMatch(suggestion,/best|number one|guaranteed/i);
 assert.equal(auditBusinessWebsite(info).rankingsMeasured,false);
});
