// Current saved appointments only. Enquiry status and recording dates are independent.
import {bookingConflicts,bookingIdentity} from './growthrovaBookingConflicts.js';
export const bookingStates={confirmed:'Confirmed booking',attended:'Attended',cancelled:'Cancelled',no_show:'Did not attend'};

export function bookingTiming(booking,today){
  if(booking.state!=='confirmed')return bookingStates[booking.state]||'';
  if(!booking.scheduledDate)return 'Date missing';
  if(booking.scheduledDate<today)return 'Past date · review outcome';
  return booking.scheduledDate===today?'Scheduled today':'Upcoming';
}

export function bookingAgenda(leads,{from='',through='',state='all',overlaps=false}={},today,conflicts=bookingConflicts(leads)){
  const recorded=leads.filter(lead=>Object.hasOwn(bookingStates,lead.data.customerCare?.booking?.state));
  const review=lead=>lead.data.customerCare.booking.state==='confirmed'&&Boolean(lead.data.customerCare.booking.scheduledDate)&&lead.data.customerCare.booking.scheduledDate<today;
  const invalidRange=Boolean(from&&through&&from>through);
  const rows=invalidRange?[]:recorded.filter(lead=>{
    const booking=lead.data.customerCare.booking;
    return (!overlaps||conflicts.byBooking.has(bookingIdentity(lead)))&&
      (!from||booking.scheduledDate>=from)&&(!through||Boolean(booking.scheduledDate)&&booking.scheduledDate<=through)&&
      (state==='all'||state==='review'&&review(lead)||booking.state===state);
  }).sort((a,b)=>(a.data.customerCare.booking.scheduledDate||'\uffff').localeCompare(b.data.customerCare.booking.scheduledDate||'\uffff')||
    (a.data.customerCare.booking.appointment?.utcStart||'\uffff').localeCompare(b.data.customerCare.booking.appointment?.utcStart||'\uffff')||
    a.data.name.localeCompare(b.data.name)||a.id.localeCompare(b.id));
  return {rows,invalidRange,conflicts,total:recorded.length,awaitingReview:recorded.filter(review).length,
    today:recorded.filter(lead=>lead.data.customerCare.booking.state==='confirmed'&&lead.data.customerCare.booking.scheduledDate===today).length};
}

export function bookingHandoff(rows,filters,exportedAt){
  return {format:'growthrova-booking-handoff-v1',exportedAt,filters:{...filters},count:rows.length,
    notice:'Private owner-recorded current bookings. Contains contact details and booking evidence. Report dates are UTC days. Optional appointment times retain the recorded local start/end and timezone; date-only bookings have no inferred time. No calendar sync, reminder, delivery, permission grant or advertising attribution. Saved snapshots only; earlier bookings and unsaved edits excluded.',
    bookings:rows.map(lead=>({id:lead.id,campaignId:lead.campaignId,revision:lead.revision,updated:lead.updated,
      contact:{name:lead.data.name,email:lead.data.email,phone:lead.data.phone},
      booking:{...Object.fromEntries(['state','scheduledDate','outcomeDate','reference','evidence'].map(key=>[key,lead.data.customerCare.booking[key]])),
        ...(lead.data.customerCare.booking.appointment?{appointment:{...lead.data.customerCare.booking.appointment}}:{})}}))};
}
