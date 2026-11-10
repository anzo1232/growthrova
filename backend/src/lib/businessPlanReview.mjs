/** Saved planning holds only. No provider eligibility or delivery authority. */
import {businessFactReview, strategyFields, strategyEvidenceState,
  strategyConfirmed} from './businessOwnerStrategy.mjs';
import {marketingCopyIssue} from './businessCopyReadiness.mjs';
import {createPublicationCalendar,isPublicationStartDate} from './businessPublicationCalendar.mjs';

export function savedPlanReview(doc) {
  const facts=(doc.observedFacts||[]).map((_,index)=>{
    const review=businessFactReview(doc,index);
    return {index,decision:review?.decision||'pending'};
  });
  const pendingFactIndices=facts.filter(item=>item.decision==='pending').map(item=>item.index);
  const missingFields=Object.keys(strategyFields).filter(key=>key!=='positioning'&&!doc.ownerStrategy?.[key]?.trim());
  const evidence=Object.keys(strategyFields).map(field=>({field,...strategyEvidenceState(doc,field)}))
    .map(({field,status})=>({field,status}));
  const staleEvidenceFields=evidence.filter(item=>item.status==='stale').map(item=>item.field);
  const confirmed=strategyConfirmed(doc);
  const missingDays=Array.from({length:30},(_,i)=>i+1).filter(day=>!doc.posts.some(post=>post.day===day));
  const incompleteDays=doc.posts.flatMap(post=>{
    const fields=['theme','channel'].filter(key=>!post[key]?.trim());
    return fields.length?[{day:post.day,fields}]:[];
  });
  const validStartDate=isPublicationStartDate(doc.calendarStartDate);
  let reminderExportAvailable=false;
  try { createPublicationCalendar(doc.posts,doc.calendarStartDate); reminderExportAvailable=true; }
  catch { /* Partial calendars can still be reviewed and saved. */ }
  const copy=(items,type)=>items.map(item=>{
    const issue=marketingCopyIssue(item,doc.business)||null;
    return {type,...(type==='post'?{day:item.day}:{id:item.id}),
      state:issue?'needs_copy':item.status==='copy_reviewed'?'copy_reviewed':'needs_review',issue};
  });
  const posts=copy(doc.posts,'post'),creatives=copy(doc.creatives,'creative');
  const actions=[];
  const add=(code,message,surface,details={})=>actions.push({code,message,surface,...details});
  if(pendingFactIndices.length) add('review_facts','Confirm, correct or exclude the remaining website observations.',
    'prepare-strategy-review',{indices:pendingFactIndices});
  if(missingFields.length) add('complete_strategy','Supply the missing business brief details.',
    'prepare-strategy-review',{fields:missingFields});
  if(staleEvidenceFields.length) add('review_source_links','Relink or remove changed website excerpts.',
    'prepare-strategy-review',{fields:staleEvidenceFields});
  if(!confirmed&&!pendingFactIndices.length&&!missingFields.length&&!staleEvidenceFields.length)
    add('confirm_strategy','Review and explicitly confirm the current business strategy.','prepare-strategy-review');
  if(!validStartDate) add('choose_calendar_date','Choose the starting date for this plan.','prepare-strategy-review');
  if(missingDays.length) add('complete_calendar','After confirming the strategy and date, prepare the missing calendar days.',
    'prepare-strategy-review',{days:missingDays});
  if(incompleteDays.length) add('complete_calendar_details','Supply the missing themes and channels for these days.',
    'prepare-content-plan',{targets:incompleteDays});
  for(const [type,items] of [['post',posts],['creative',creatives]]) {
    const needsCopy=items.filter(item=>item.state==='needs_copy');
    const needsReview=items.filter(item=>item.state==='needs_review');
    const targets=rows=>rows.map(item=>type==='post'?{day:item.day}:{id:item.id});
    if(needsCopy.length) add('complete_'+type+'_copy','Replace incomplete draft directions with words for customer review.',
      'prepare-content-copy',{type,targets:targets(needsCopy)});
    if(needsReview.length) add('review_'+type+'_copy','Review these saved words before explicitly marking copy reviewed.',
      'prepare-content-copy',{type,targets:targets(needsReview)});
  }
  return {scope:'saved_planning_only',facts:{items:facts,pendingIndices:pendingFactIndices},
    strategy:{confirmation:confirmed?'current':doc.ownerStrategy?.confirmedContext?'stale':'unconfirmed',
      missingFields,evidence,staleEvidenceFields},
    calendar:{startDate:doc.calendarStartDate||'',validStartDate,missingDays,incompleteDays,reminderExportAvailable},
    copy:{posts,creatives},nextAction:actions[0]||null,actions,
    limitations:'Saved planning review only. Website statements remain unverified. Copy review does not verify claims, '
      +'media rights, generated output quality, account readiness, scheduling, publication or spend. '
      +'Prepare changes for inspection, then explicitly save them at the selected revision.',
    canPublish:false,canSpend:false};
}
