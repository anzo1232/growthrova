import {strategyConfirmed} from './businessOwnerStrategy.mjs';
import {editMarketingPost} from './businessMarketingDocument.mjs';

// Editorial starting points only: no account, audience or performance inference.
const plans={
  awareness:[['Instagram','Introduce the offer visually and give people a reason to learn more.'],['Facebook','Explain the offer with practical details and an invitation to ask questions.']],
  enquiries:[['Facebook','Explain the offer and the confirmed next step for an enquiry.'],['Instagram','Show an accurate visual introduction and direct interested people to the next step.']],
  bookings:[['Facebook','Explain what someone needs to know before requesting a booking.'],['Instagram','Introduce the experience or service and explain how to request availability.']],
  education:[['LinkedIn','Prepare a useful explanation; first confirm that your intended customers use this channel.'],['Instagram','Break a supported explanation into a visual post or carousel.'],['Facebook','Explain one customer question and invite a discussion.']],
  offers:[['Instagram','Introduce the confirmed offer visually without adding discounts or urgency.'],['Facebook','Explain the confirmed scope and next step without inventing availability.']],
};
export function channelSuggestions(doc){
  if(!strategyConfirmed(doc))return [];
  return (plans[doc.goal]||[]).map(([channel,reason])=>({channel,reason}));
}
export function channelPlanEligible(post){
  return post.status!=='copy_reviewed'&&['image post','carousel'].includes(String(post.format).trim().toLowerCase());
}
/** Keep calendar order deterministic even if a saved document stores days out of order. */
export function proposedChannelPlan(doc){
  const choices=channelSuggestions(doc);
  if(!choices.length)return [];
  return [...doc.posts].filter(channelPlanEligible).sort((a,b)=>a.day-b.day)
    .map((post,index)=>({day:post.day,previous:post.channel,channel:choices[index%choices.length].channel}));
}
export function applySuggestedChannel(doc,day,channel){
  if(!channelSuggestions(doc).some(choice=>choice.channel===channel))throw new TypeError('Confirm the current strategy and choose a suggested channel');
  const post=doc.posts.find(item=>item.day===day);
  if(!post||!channelPlanEligible(post))throw new TypeError('Choose an unreviewed image post or carousel');
  const next=editMarketingPost(doc,day,{channel});
  return next===doc?doc:{...next,canPublish:false,canSpend:false};
}
/** Recompute inside the board update, against the current document and goal. */
export function applyChannelPlan(doc){
  const plan=proposedChannelPlan(doc);
  if(!plan.length)throw new TypeError('Confirm your strategy and prepare an unreviewed image post or carousel first');
  return plan.reduce((current,item)=>applySuggestedChannel(current,item.day,item.channel),doc);
}
