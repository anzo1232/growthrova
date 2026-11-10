import {emptyCustomerCare} from './growthrovaCareTasks.js';

export const bookingReviewFields={state:'Booking outcome',scheduledDate:'Scheduled booking date (UTC)',
  outcomeDate:'Observed outcome date (UTC)',reference:'Booking reference',evidence:'Confirmation evidence',
  appointment:'Exact appointment times'};
export const editableBooking=care=>({... (care?.booking||emptyCustomerCare().booking)});
const localAppointment=value=>value?JSON.stringify([value.localStart,value.localEnd,value.timeZone]):'';
export function reviewedBooking(original,draft){
  const booking={...draft};
  // Reverting local edits must also retain the original saved UTC interpretation.
  if(booking.appointment&&localAppointment(booking.appointment)===localAppointment(original?.appointment))
    booking.appointment=original.appointment;
  return booking;
}
export function bookingReviewChanges(care,draft){
  if(!draft)return [];
  const original=editableBooking(care);
  return Object.keys(bookingReviewFields).filter(key=>key==='appointment'
    ?localAppointment(original.appointment)!==localAppointment(draft.appointment)
    :key==='scheduledDate'&&draft.appointment?false:original[key]!==draft[key])
    .map(key=>({key,before:original[key],after:draft[key]}));
}
export function appointmentReviewText(value){
  return value?`${value.localStart||'Start required'} to ${value.localEnd||'End required'} · ${value.timeZone||'Timezone required'}`:'No exact times';
}
