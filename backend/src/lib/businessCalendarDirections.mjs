// Editorial work to prepare, never customer-facing claims or generated artwork.
const goals={
  awareness:{purpose:'Help people recognise the business and understand its offer.',topics:[
    ['Meet the business','Introduce the business using the confirmed brief; request any missing introduction details.'],
    ['Who we help','Describe the confirmed audience without claiming universal suitability.'],
    ['What we do','Explain the confirmed offer in plain language without adding features.'],
    ['Our approach','Describe the owner-supplied positioning without superiority claims.'],
    ['A recognisable detail','Choose an authentic business detail or rights-cleared image; do not invent premises or products.'],
    ['Stay in touch','Use the confirmed next step to invite people to learn more without promising future content.'],
  ]},
  enquiries:{purpose:'Help interested people ask an informed question about the offer.',topics:[
    ['Start a conversation','Explain what someone can ask about the confirmed offer.'],
    ['Is this relevant to me?','Describe the intended audience and ask the owner to confirm any suitability limits.'],
    ['Explain the scope','Use the confirmed offer; request missing inclusions and exclusions before writing.'],
    ['A question before enquiring','Request a real customer question and an accurate answer; never invent an FAQ.'],
    ['Prepare an enquiry','Ask the owner which details help them respond; do not invent contact requirements.'],
    ['How to enquire','Use the confirmed call to action; verify the destination and avoid response-time promises.'],
  ]},
  bookings:{purpose:'Help people understand the service before requesting an available appointment.',topics:[
    ['What you are booking','Explain the confirmed service without inventing duration or availability.'],
    ['Before requesting a time','Ask the owner to confirm suitability and preparation requirements.'],
    ['The booking steps','Request the actual booking process and destination; do not invent a booking link.'],
    ['What to expect','Request a factual description of the appointment; avoid guaranteed outcomes.'],
    ['Practical booking questions','Ask the owner to confirm location, access and cancellation details before use.'],
    ['Request availability','Use the confirmed next step without inventing open slots, scarcity or confirmation.'],
  ]},
  education:{purpose:'Help people understand the offer through useful supported explanations.',topics:[
    ['Explain one term','Choose a term from the confirmed offer and request an accurate plain-language definition.'],
    ['How it works','Request supported process steps; leave unknown stages for owner review.'],
    ['A useful question','Request a real audience question and a source-supported answer.'],
    ['A practical checklist','Prepare questions that help someone understand the offer; verify any advice before use.'],
    ['Scope and limitations','Explain confirmed limits without inventing comparisons or professional advice.'],
    ['Learn from an example','Request a genuine example with rights and consent; describe only what it demonstrates.'],
  ]},
  offers:{purpose:'Explain the confirmed offer and terms so people can consider the next step.',topics:[
    ['Introduce the offer','Use the exact confirmed offer without adding discounts, prices or extras.'],
    ['Who the offer is for','Explain the intended audience and request any actual eligibility conditions.'],
    ['What is included','Ask the owner to verify scope, exclusions and any terms before using them.'],
    ['Understand the value','Explain the supplied positioning without invented savings or performance claims.'],
    ['Questions about the offer','Request accurate answers about terms; do not invent deadlines or stock levels.'],
    ['Take the next step','Use the confirmed call to action; verify any purchase or enquiry destination.'],
  ]},
};
const stages=[
  ['Introduction','Prepare a short introduction using only confirmed details.'],
  ['Explanation','Expand one supported detail into an explanation suitable for an image post or carousel.'],
  ['Evidence','Request a genuine supporting source or permitted visual; hold unsupported claims.'],
  ['Questions','Invite a relevant customer question; ask the owner to review any proposed answer.'],
  ['Next step','Recap the supported detail and connect it to the confirmed call to action without urgency or guarantees.'],
];
export function calendarGoalPurpose(goal){return goals[goal]?.purpose||'';}
export function calendarDirection(goal,day){
  if(!Object.hasOwn(goals,goal)||!Number.isInteger(day)||day<1||day>30)throw new TypeError('Choose a supported marketing goal and calendar day');
  const [topic,task]=goals[goal].topics[(day-1)%6];
  const [stage,action]=stages[Math.floor((day-1)/6)];
  return {day,theme:topic+' — '+stage,direction:task+' '+action};
}
