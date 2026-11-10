// Saved UTC intervals only: this cannot determine staff/resource availability.
export const bookingIdentity=lead=>JSON.stringify([lead.campaignId,lead.id]);

function savedInstant(value){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$/.test(value))return null;
  const stamp=Date.parse(value);
  return Number.isFinite(stamp)&&new Date(stamp).toISOString()===value.slice(0,-1)+':00.000Z'?stamp:null;
}

export function bookingConflicts(leads){
  const intervals=[],byBooking=new Map(),seen=new Set();
  let withoutTimes=0,unusableTimes=0,pairs=0;
  for(const lead of leads){
    const key=bookingIdentity(lead),booking=lead.data.customerCare?.booking;
    if(seen.has(key)||booking?.state!=='confirmed')continue;
    seen.add(key);
    if(!booking.appointment){withoutTimes++;continue;}
    const start=savedInstant(booking.appointment.utcStart),end=savedInstant(booking.appointment.utcEnd);
    if(start===null||end===null||end<=start||end-start>7*86400000){unusableTimes++;continue;}
    intervals.push({lead,key,start,end});
  }
  intervals.sort((a,b)=>a.start-b.start||a.end-b.end||a.key.localeCompare(b.key));
  function add(own,other){
    let entry=byBooking.get(own.key);
    if(!entry){entry={count:0,examples:[]};byBooking.set(own.key,entry);}
    entry.count++;
    // Bounded preview even when every saved booking overlaps every other one.
    if(entry.examples.length<3)entry.examples.push(other.lead);
  }
  let active=[];
  for(const item of intervals){
    active=active.filter(other=>other.end>item.start);
    for(const other of active){pairs++;add(item,other);add(other,item);}
    active.push(item);
  }
  return {byBooking,pairs,overlapping:byBooking.size,checked:intervals.length,withoutTimes,unusableTimes};
}
