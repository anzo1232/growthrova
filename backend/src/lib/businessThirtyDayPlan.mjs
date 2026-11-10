/** An evidence-conscious editorial draft planner. Never treat derived copy as
 * a verified business claim, publish permission, or completed media. */
const clean=(value,limit=300)=>{
 const candidate=String(value||'').replace(/\s+/g,' ').trim();
 if(candidate.length<=limit)return candidate;
 const portion=candidate.slice(0,limit);
 const boundary=portion.lastIndexOf(' ');
 return (boundary>=limit*0.6?portion.slice(0,boundary):portion).replace(/[,:;\s]+$/,'')+'…';
};
const sectors={
 country_club:{subject:'club membership and facilities',service:'club enquiry',client:'someone exploring club facilities',consideration:'membership terms, facility access and current timetables',proof:'current facility details and genuine club photographs'},
 plumbing:{subject:'a plumbing or heating issue',service:'plumbing enquiry',client:'someone seeking help with a property issue',consideration:'the symptoms, scope, access and quotation process',proof:'verified service information and permissioned work photographs'},
 concierge:{subject:'a memorable experience',service:'concierge enquiry',client:'someone planning something important',consideration:'timing, preferences and the details that matter',proof:'real, permissioned service imagery'},
 restaurant:{subject:'your next meal out',service:'table enquiry',client:'someone choosing where to dine',consideration:'the current menu, setting and availability',proof:'current menu details and real food photography'},
 beauty:{subject:'your next beauty or wellbeing appointment',service:'treatment enquiry',client:'someone comparing services',consideration:'suitability, expectations and qualifications',proof:'verified treatment information and permissioned imagery'},
 renovation:{subject:'your next home project',service:'project quotation',client:'a homeowner weighing up a project',consideration:'scope, timings, materials and past work',proof:'permissioned photographs of actual completed projects'},
 roofing:{subject:'a damaged or ageing roof',service:'roof inspection or repair enquiry',client:'a homeowner worried about a roof issue',consideration:'visible symptoms, weather, urgency and professional assessment',proof:'real customer-approved roof photos'},
 other:{subject:'the service you need',service:'service enquiry',client:'someone weighing up the options',consideration:'scope, expectations and the next steps',proof:'verified examples or approved reference imagery'}
};
const cycle={
 concierge:['Instagram','Instagram','Website','Instagram','Email','Facebook','Instagram','Instagram','Website','Instagram'],
 restaurant:['Instagram','Facebook','Instagram','Website','Instagram','TikTok','Instagram','Facebook','Email','Instagram'],
 beauty:['Instagram','Facebook','Instagram','Website','Instagram','Facebook','Instagram','TikTok','Email','Instagram'],
 renovation:['Facebook','Instagram','Website','Facebook','Instagram','LinkedIn','Facebook','Instagram','Email','Facebook'],
 roofing:['Facebook','Instagram','Facebook','Instagram','Website','Facebook','Instagram','Facebook','Email','Instagram'],
 other:['Instagram','Facebook','Website','Instagram','Email','Facebook','Instagram','Website','LinkedIn','Instagram']
};
const formats={
 Instagram:['Image advert','Carousel','Reel concept','Story'],Facebook:['Image advert','Carousel','Video advert','Story'],
 Website:['Website feature','FAQ article'],Email:['Email campaign'],TikTok:['Short video concept','Educational video'],
 LinkedIn:['Text and image post','Educational graphic']
};
const angleNames=[
 'What the brand represents','The decision before the decision','A useful place to begin','What matters most','Questions worth asking','A detail that changes the experience','Our positioning in plain English',
 'What the service covers','Choosing with confidence','Understand the process','Common misconceptions','Planning ahead','The difference between promise and proof','Invitation to explore',
 'What good service looks like','Real examples to request','Getting the details right','What to expect before enquiring','Build confidence before choosing','An honest FAQ','The practical checklist',
 'Where to start today','A closer look at the offer','Make the most of your enquiry','The service in three steps','Questions before committing','The role of personal preference','Find the right next step',
 'A final question to consider','Your invitation to enquire'
];
function copies({brand,positioning,subject,service,client,consideration,proof}){
 const quote=`${brand} describes its positioning this way: “${positioning}”`;
 return [
  `Meet ${brand}. ${quote}. Here is the starting point for understanding what the business actually offers, before making an enquiry.`,
  `Before making plans for ${subject}, decide what matters most to you. Is it flexibility, simplicity, timing or a particular outcome? A clearer brief leads to a more useful first conversation.`,
  `Start with one question: what would make ${subject} feel right for you? Write down the priorities, then explore whether ${brand} offers a suitable approach.`,
  `The smallest details can shape the bigger picture. When considering ${subject}, look beyond the headline and ask about ${consideration}.`,
  `Three questions worth asking before you commit: what is included, what depends on availability, and what happens next? Save these for your next ${service}.`,
  `A good decision isn't only about how something looks. Think about the timing, the practical details and whether the proposed service genuinely fits what you need.`,
  `The wording behind ${brand} matters. ${quote}. Explore the business's current services and decide which details you would like clarified.`,
  `What does the service actually cover? Start with the published description, then ask about the scope, any exclusions and the available options. Clear answers make planning easier.`,
  `Choosing with confidence starts with information you can verify. Look at the current services, check the terms that matter, and don't hesitate to ask for specifics before deciding.`,
  `What should the first conversation look like? Explain what you're trying to achieve, share any relevant timing, and ask what the business needs to recommend a sensible next step.`,
  `One misconception to avoid: that the most impressive-looking option is automatically the best fit. Work backwards from your priorities, your expectations and the information available.`,
  `Planning ahead? Make a short list of your requirements and the questions you'd like answered. That turns an open-ended enquiry into a much more productive conversation.`,
  `A beautiful photograph can spark interest, but it shouldn't replace evidence. Ask to see ${proof} before relying on a visual as a real example of this business's work.`,
  `Curious about ${brand}? Browse the information available on its website, note what appeals to you, then get in touch to clarify the details that aren't explained there.`,
  `What should good service feel like to you? It might be straightforward communication, clear expectations or attention to detail. Use your own definition when weighing up options.`,
  `Looking for examples? Ask for ${proof}. Real references help you understand what is actually offered, without relying on an illustrative concept.`,
  `Get specific about ${subject}. Define your must-haves and nice-to-haves, then ask which choices would make the greatest difference to the experience.`,
  `Before sending a message, consider what you'd want to know about the process: who to contact, what information is needed and when a response might be expected.`,
  `Trust is built through details that can be checked. Start with the service description, look for supporting information, and ask direct questions where something is unclear.`,
  `A quick FAQ worth keeping handy: what is available, what is included, what preparation is needed, and how do I take the next step? Confirm the answers with ${brand}.`,
  `Your short checklist for ${subject}: purpose, timing, requirements, the questions you still have and the most useful way to make contact. Keep it simple and specific.`,
  `Ready to explore your options? Begin with the outcome you want, then compare that with ${brand}'s published positioning rather than assuming every service works the same way.`,
  `${quote}. If those priorities resonate with you, explore the real service details and ask what they mean for your particular requirements.`,
  `Make your enquiry work harder. Share your priorities, relevant dates and any constraints up front so the next conversation can focus on suitable options rather than guesswork.`,
  `A useful first-enquiry framework: explain what you need; confirm what can be provided; agree the sensible next step. Keep the conversation practical and specific.`,
  `Before making a commitment, ask about the essentials: scope, timescales, any conditions and which details still need confirmation. Good questions make better decisions.`,
  `There's no single right answer for ${subject}. Personal preferences matter. Use the current website information as a starting point, then ask about choices that fit your situation.`,
  `Not sure what to do next? Start by identifying your biggest unanswered question. If ${brand} looks relevant, ask for the information needed to make an informed choice.`,
  `One final thing to consider: does the option you're looking at meet your actual priorities, or just make a strong first impression? Check the details before going further.`,
  `Have something specific in mind? Send a clear enquiry to ${brand} with what you're looking for and the questions that matter most. Let the conversation start with your real requirements.`
 ];
}
const roofingTopics=[
 ['Noticed a leak?','Water staining on your ceiling? A roof leak can have several causes. Keep clear of unsafe roof access and ask a qualified roofer to inspect the problem.'],
 ['Missing roof tiles','Spotted a slipped or missing tile from ground level? An early professional inspection can help you understand the extent of the damage.'],
 ['Gutters overflowing','Water spilling from your gutters during rain? Blockages and damaged guttering are worth checking before they cause further problems.'],
 ['Flat roof worries','A flat roof showing ponding, bubbling or cracks needs a proper assessment. Ask a roofer what is happening rather than guessing from a photo.'],
 ['What does a roof inspection involve?','Before you book an inspection, ask which areas will be checked and whether you will receive a clear explanation of the findings.'],
 ['Storm damage?','If bad weather has affected your roof, stay clear of loose materials. Take photos safely from the ground and contact a suitable professional.'],
 ['Get a clear quote','A useful roofing quote should explain the proposed work, materials, timeline and what is or is not included.'],
 ['Repair or replace?','Not every roof issue means a whole new roof. A proper inspection helps you understand the options available for your situation.'],
 ['What to tell your roofer','When enquiring, describe what you have noticed, where it is, when it started and any relevant photos taken safely from the ground.'],
 ['Is a stain always a roof leak?','Damp patches have different possible causes. Describe the symptoms and seek a professional diagnosis before choosing a repair.'],
 ['What makes a good roof quote?','Compare the scope of work, specifications, materials and what happens if additional problems are found.'],
 ['Roof maintenance matters','Visible loose materials, overflowing gutters and damaged flashing may be worth getting checked before the next spell of bad weather.'],
 ['Flat roof materials','Thinking about flat roofing? Ask about the material options, expected maintenance and what is suitable for your property.'],
 ['Before and after photos','Want to see the standard of a roofer’s work? Ask for genuine, permissioned photos of relevant completed projects.'],
 ['Your roof and heavy rain','Heavy rain can make problems easier to notice. If water appears indoors, prioritise safety and ask for advice about protecting the property.'],
 ['What is flashing?','Flashing helps weatherproof roof junctions. Visible gaps or damage around these areas are worth discussing with a qualified roofer.'],
 ['Why roof ventilation matters','Ventilation and moisture can affect a roof space. Ask your roofer what they inspect and whether any changes are actually needed.'],
 ['Choosing the right repair','A good repair should address the underlying problem. Ask your roofer to explain the proposed solution in everyday language.'],
 ['When should I ask for help?','A new leak, loose roof material or signs of storm damage are good reasons to seek a professional assessment. Do not climb onto a damaged roof.'],
 ['Three questions to ask','What is causing the issue? What work is proposed? What should I expect during and after the repair?'],
 ['Keeping gutters working','Gutters carry rainwater away from your home. If they regularly overflow, it may be time for a professional check.'],
 ['Planning a new roof','If you are considering replacement, ask about materials, insulation considerations, duration and disruption before deciding.'],
 ['What happens after an inspection?','You should be able to understand the findings, the available options and the next step before committing to work.'],
 ['Do you need a roof quote?','Tell the roofing company what you have noticed and which type of help you think you need. They can discuss suitable next steps.'],
 ['Watch for tile movement','Loose or slipped roof tiles can be a warning sign. View the roof safely from the ground and ask a roofer to assess the problem.'],
 ['Avoid guesswork','A photo can help describe a problem, but it cannot always show its cause. A professional inspection is more reliable than an assumption.'],
 ['What about a small leak?','Even a small amount of water can be a sign that attention is needed. Ask for an assessment rather than waiting for the problem to grow.'],
 ['Ask about timings','Need roofing work? Ask about lead times, weather dependencies and how the proposed schedule will be communicated.'],
 ['Roof care: what to keep an eye on','After severe weather, look from ground level for visible damage and watch for changes indoors. Seek specialist help for concerns.'],
 ['Ready to get a roofing quote?','Have a roof concern or a planned project? Describe the job and ask the business what information it needs to provide a useful quotation.']
];
export function buildThirtyDayPlan({business,offer,audience,goal='enquiries',sector='other'}={}){
 if(![business,offer,audience].every(x=>typeof x==='string'&&x.trim().length>=2))throw new TypeError('Business, offer and an audience hypothesis are required');
 const brand=clean(business,100),positioning=clean(offer,300),terms=sectors[sector]||sectors.other;
 const drafts=sector==='roofing'?roofingTopics.map(([topic,body])=>body):copies({brand,positioning,...terms});
 const route=cycle[sector]||cycle.other;
 const posts=angleNames.map((generalTheme,i)=>{
  const theme=sector==='roofing'?roofingTopics[i][0]:generalTheme;
  const channel=route[i%route.length],options=formats[channel];
  return {day:i+1,week:Math.floor(i/7)+1,theme,channel,
   format:options[Math.floor(i/options.length)%options.length],
   objective:i<7?'awareness':i<14?'consideration':i<21?'trust':goal,
   copyDraft:drafts[i],callToAction:i<14?'Explore the website':i<21?'Learn about the service':'Make an enquiry',
   proofNeeded:i===0||i===6||i===22?'Verify the extracted website description':i===12||i===15?`Confirm and licence ${terms.proof}`:'Confirm business-specific claims, images, current availability and CTA destination before approval',
   status:'draft',scheduled:false,published:false};
 });
 return {status:'draft_not_scheduled',posts,reviewRequired:true,source:'Website or owner-supplied description with unverified audience assumptions; no social or analytics integration'};
}
export function recommendBusinessServices({goal='enquiries',hasWebsite=false,hasBookingUrl=false,hasAnalytics=false}={}){
 return [
  {service:'Conversion path',priority:!hasBookingUrl?'high':'review',reason:hasBookingUrl?'Review the verified conversion journey':'Verify a customer enquiry or booking destination'},
  {service:'SEO and website content',priority:hasWebsite?'review':'optional',reason:hasWebsite?'Audit actual web pages before making claims':'A website is optional; consider a focused landing page'},
  {service:'Paid advertising',priority:'optional',reason:'Prepare creatives for review; never spend without owner approval'},
  {service:'Email marketing',priority:'optional',reason:'Create an opt-in nurture sequence using permissioned contacts'},
  {service:'Lead and performance reporting',priority:hasAnalytics?'review':'setup',reason:'Measure real enquiries and bookings with connected, consented data'}
 ];
}
