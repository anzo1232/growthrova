import {repeatPurchaseReview} from './growthrovaSales.js';
import {pipelineReview} from './growthrovaPipeline.js';
import {actionTiming,todayUTC} from './growthrovaFollowThrough.js';

// Shared with the register filters so review buttons open exactly the cited set.
export function matchesLeadReview(lead,filter,now=Date.now()/1000){
  const data=lead.data,today=todayUTC(now*1000),timing=actionTiming(data,today);
  if(filter==='repeat'||filter==='repeat-retention'){
    const review=repeatPurchaseReview(data,today);
    return filter==='repeat'?review.repeat:review.withoutOpenRetention;
  }
  if(filter==='care')return ['retention','review'].some(key=>{
    const task=data.customerCare?.[key];
    return task?.action?.trim()&&task.state==='open'&&task.dueDate&&task.dueDate<=today;
  });
  if(filter==='unassigned')return Boolean(timing)&&!data.responsiblePerson?.trim();
  if(['active','stale','unplanned'].includes(filter))return pipelineReview(lead,now)[filter];
  if(filter==='permission')return data.emailPermission==='unknown'&&data.whatsappPermission==='unknown';
  return filter==='all'||(filter==='open'?Boolean(timing):timing===filter);
}

export function enquiryRecommendations(leads,now){
  const rules=[
    ['Overdue','Review overdue human actions','Check the saved next step and agree a new date or record what happened.'],
    ['Due today','Review today’s human actions','Open the saved action before deciding whether to contact anyone.'],
    ['unassigned','Assign responsibility','Choose a responsible person for each open action. Saving a name does not notify them.'],
    ['care','Review due retention and review tasks','Check the booking outcome, wording and permission before separately approving any delivery.'],
    ['repeat-retention','Review repeat-purchase follow-through','Use the saved purchases and current circumstances to decide whether to prepare a retention task. Review permission before any separate delivery approval.'],
    ['stale','Review enquiries awaiting an update','Confirm the current situation of New or Contacted enquiries without an update for seven days.'],
    ['unplanned','Review active enquiries without a next step','Check the enquiry history and decide whether to prepare a human action or update its status. A missing action may be intentional.'],
    ['permission','Clarify follow-up permission','Record what permission was actually given. Unknown permission does not authorise contact.'],
  ];
  return rules.flatMap(([target,title,action])=>{
    const count=leads.filter(lead=>matchesLeadReview(lead,target,now)).length;
    return count?[{id:target,title,action,target,evidence:`${count} matching saved enquiries in this campaign, across all loaded recording dates. UTC review date: ${todayUTC(now*1000)}.`,limit:'Current owner-recorded state only. Groups can overlap; counts are not conversions or completed contact.'}]:[];
  });
}

function missingDates(from,to,dates){
  const returned=new Set(dates);
  let missing=0;
  // All source windows are bounded by the server (at most 100 dates).
  for(let at=Date.parse(from+'T00:00:00Z'),end=Date.parse(to+'T00:00:00Z');at<=end;at+=86400000){
    if(!returned.has(new Date(at).toISOString().slice(0,10)))missing++;
  }
  return missing;
}

export function paidRecommendations(reports,{from='',to='',platform='all'}={}){
  if(from&&to&&from>to)return [];
  const selected=reports.filter(report=>platform==='all'||report.data.platform===platform);
  const result=[];
  for(const report of selected){
    const rows=report.data.rows.filter(row=>(!from||row.date>=from)&&(!to||row.date<=to));
    const source=`${report.data.platform==='meta'?'Meta':'Google'} · account ${report.data.accountId} · campaign ${report.data.campaignId} · report ${report.id} v${report.revision} · ${report.data.timezone} · ${report.provenance==='provider_read'?'approved account read':'owner-supplied export'} · ${report.data.sourceReference}`;
    const observation=report.observation;
    if(observation){
      const start=from&&from>observation.requestedFrom?from:observation.requestedFrom;
      const end=to&&to<observation.requestedTo?to:observation.requestedTo;
      const missing=missingDates(start,end,observation.returnedDates);
      if(missing)result.push({id:report.id+'-coverage',target:report.id,title:'Check missing reporting dates',
        evidence:`${source}. Requested coverage within the filter: ${start} to ${end}; ${missing} dates not returned. Read at ${new Date(observation.observedAt*1000).toISOString()}.`,
        action:'Review this source report and the saved read before preparing another refresh.',limit:'Omitted dates are unmeasured, not zero performance. A new read requires its own review.'});
    }
    const impressions=rows.reduce((sum,row)=>sum+row.impressions,0),clicks=rows.reduce((sum,row)=>sum+row.clicks,0);
    if(impressions>0&&clicks===0)result.push({id:report.id+'-clicks',target:report.id,title:'Review reported impressions without clicks',
      evidence:`${source}. ${rows.length} returned dates (${rows[0].date} to ${rows.at(-1).date}): ${impressions} impressions and 0 reported clicks.`,
      action:'Check the original metric definitions and destination before deciding on any campaign change.',
      limit:'These counts do not identify a cause, a losing advert or a reason to change spend.'});
    if(clicks>0)result.push({id:report.id+'-outcomes',target:report.id,title:'Check the enquiry path and source records',
      evidence:`${source}. ${rows.length} returned dates (${rows[0].date} to ${rows.at(-1).date}): ${clicks} reported clicks.`,
      action:'Review this campaign’s destination and compare actual enquiry source references separately in the register.',
      limit:'Click counts are not unique people or enquiries. No link to bookings, sales or advertising return has been established.'});
  }
  return result;
}

export function searchRecommendations(read){
  if(read?.state!=='completed'||!read.result||read.request.mode==='page_query')return [];
  const {rows,observedAt}=read.result,{from,to,account}=read.request;
  const source=`${account.propertyId} · snapshot ${read.id} · ${from} to ${to} (Pacific dates) · observed ${new Date(observedAt*1000).toISOString()}`;
  const missing=missingDates(from,to,rows.map(row=>row.date));
  const clicks=rows.reduce((sum,row)=>sum+row.clicks,0),impressions=rows.reduce((sum,row)=>sum+row.impressions,0);
  const result=[];
  if(missing)result.push({id:'search-coverage',title:'Check search observation coverage',evidence:`${source}. ${missing} requested dates were not returned.`,
    action:'Review the selected property and date window before comparing this snapshot with other evidence.',limit:'Missing dates are unmeasured; a sparse or empty response is not proof of absent visibility.'});
  if(impressions>0&&clicks===0)result.push({id:'search-clicks',title:'Review search presentation',evidence:`${source}. ${impressions} impressions and 0 reported clicks across ${rows.length} returned dates.`,
    action:'Prepare a review of relevant page titles and descriptions using the saved website evidence.',limit:'Property totals do not identify a particular page, search query, cause or ranking. No website change is made.'});
  if(clicks>0)result.push({id:'search-outcomes',title:'Check how search visitors can enquire',evidence:`${source}. ${clicks} reported clicks across ${rows.length} returned dates.`,
    action:'Review the website enquiry or booking path and retain source references for actual enquiries.',limit:'Search clicks are not unique visitors, enquiries or sales; this snapshot is not linked to CRM outcomes.'});
  return result;
}

/** Read-only recovery signals. Never turn uncertain delivery into a retry. */
export function socialRecoveryRecommendations(progress){
  if(!progress)return [];
  const result=[];
  const rules=[
    {key:'uncertain',title:'Check missing delivery confirmations',count:row=>row.savedState==='uncertain'?row.count:0,
      action:'Use Check delivery confirmation for each uncertain version. This only looks up its existing delivery; keep it for recovery and do not approve a replacement while its outcome is unknown.',
      limit:'Missing confirmation does not prove failure. A replacement post could create a duplicate; unavailable reconciliation needs operator help.'},
    {key:'held',title:'Review held social delivery',count:row=>['blocked','failed','paused'].includes(row.savedState)?row.count:0,
      action:'Read each saved channel reason. Paused work stays paused unless you separately choose to approve it. For blocked work, review the saved version, destination and current eligibility before any approval.',
      limit:'These counts do not identify the cause or authorise a retry. No connection, worker availability or platform permission has been verified here.'},
    {key:'approval',title:'Review older unstarted approvals',count:row=>['scheduled','claimed','paused','blocked'].includes(row.savedState)?row.olderApprovalJobs:0,
      action:'Check scheduling and pause any unstarted work you no longer want. Inspect current artwork and captions, then save and separately approve a new posting draft if appropriate.',
      limit:'A campaign revision change does not prove the artwork changed. Completed, cancelled and in-flight jobs are excluded from this suggestion; their receipts and uncertain outcomes must be preserved.'},
    {key:'elapsed',title:'Check jobs past their planned time',count:row=>['scheduled','claimed'].includes(row.savedState)?row.waitingPastScheduledTime:0,
      action:'Check scheduling for the saved version and review connection and worker availability. Pause unstarted work if the planned time is no longer appropriate; review a new time separately.',
      limit:'Elapsed time alone does not establish failed delivery or its cause. This overview does not query a provider, start a worker or resubmit a post.'},
  ];
  // Rule order puts every uncertain outcome ahead of other delivery suggestions.
  for(const rule of rules){
    for(const campaign of progress.campaigns||[]){
      for(const mode of ['live','simulation']){
        const rows=(campaign.jobs||[]).filter(row=>row.mode===mode&&rule.count(row)>0);
        if(!rows.length)continue;
        const count=rows.reduce((sum,row)=>sum+rule.count(row),0);
        const label=mode==='live'?'Live delivery':'Rehearsal';
        result.push({id:`social-${rule.key}-${mode}-${campaign.campaignId}`,target:campaign.campaignId,
          title:`${label}: ${rule.title.toLowerCase()}`,
          evidence:`Snapshot ${new Date(progress.observedAt*1000).toISOString()}. Campaign ${campaign.campaignId}, saved version ${campaign.revision}. ${count} matching channel jobs across all saved dates: ${rows.map(row=>`${row.channel} / ${row.savedState}: ${rule.count(row)}`).join('; ')}.`,
          action:'Open Saved posting drafts, use Check saved posting drafts, then Check scheduling on the relevant saved versions. '+rule.action,
          limit:`${rule.limit} Saved states may be stale; refresh saved results after reviewing. Groups can overlap. ${mode==='simulation'?'These are rehearsal jobs; they do not publish to a social account.':'No new publication or approval is inferred.'}`});
      }
    }
  }
  return result;
}

/** Contact-free business snapshot only; never join clicks to enquiry outcomes. */
export function businessRecommendations(report){
  const recovery=socialRecoveryRecommendations(report.planProgress);
  const result=recovery.filter(item=>item.id.startsWith('social-uncertain-'));
  const loaded=`Snapshot ${new Date(report.observedAt*1000).toISOString()}.`;
  for(const campaign of report.pipeline?.campaigns||[]){
    for(const [key,title,filter] of [
      ['stale','Review enquiries awaiting an update','New or Contacted without an update for seven days'],
      ['unplanned','Review active enquiries without a next step','Active enquiries without an open human action'],
    ]){
      if(campaign[key]>0)result.push({id:`pipeline-${key}-${campaign.campaignId}`,target:campaign.campaignId,title,
        evidence:`${loaded} Campaign ${campaign.campaignId}: ${campaign[key]} matching current enquiries, across all saved dates.`,
        action:`Open Leads and results, then choose “${filter}”. Review the saved history before editing a next step or status.`,
        limit:'Last saved updates do not establish response times. Missing actions may be intentional; groups overlap. No conversion, completed contact or permission is inferred.'});
    }
  }
  for(const campaign of [...report.campaigns].sort((a,b)=>b.overdueActions-a.overdueActions||a.campaignId.localeCompare(b.campaignId))){
    if(campaign.overdueActions>0)result.push({id:'actions-'+campaign.campaignId,target:campaign.campaignId,
      title:'Review overdue human actions',
      evidence:`${loaded} Campaign ${campaign.campaignId}: ${campaign.overdueActions} open actions overdue before ${report.throughDate} (UTC), across all recording dates.`,
      action:'Open Leads and results, then use the Overdue filter to review the saved next steps and record what happened.',
      limit:'Current saved plans only; no reminder, contact or completed follow-up is inferred.'});
  }
  for(const campaign of report.repeatPurchases?.campaigns||[]){
    if(campaign.withoutOpenRetention>0)result.push({id:'repeat-retention-'+campaign.campaignId,target:campaign.campaignId,
      title:'Review repeat-purchase follow-through',
      evidence:`${loaded} Campaign ${campaign.campaignId}: ${campaign.withoutOpenRetention} enquiries with two or more current recorded purchases through ${report.repeatPurchases.throughDate} (UTC) and no open prepared retention task, across all saved dates.`,
      action:'Open Leads and results, then choose Repeat purchases without an open retention task. Review the saved purchases and current circumstances before preparing a task.',
      limit:'Enquiries are not unique customers. Voided purchases are excluded. A missing open task may be intentional; completed tasks remain in history. No payment, loyalty, contact permission or advertising attribution is established; nothing is sent.'});
  }
  result.push(...recovery.filter(item=>!item.id.startsWith('social-uncertain-')));
  for(const [kind,items] of [['paid',report.measurement?.paid||[]],['search',report.measurement?.search||[]]]){
    for(const item of items){
      const paid=kind==='paid';
      const source=paid?`${item.platform==='meta'?'Meta':'Google'} account ${item.accountId}, platform campaign ${item.platformCampaignId}, report ${item.reportId} v${item.revision}`:
        `Search property ${item.propertyId}, snapshot ${item.snapshotId}`;
      const evidence=`${loaded} Campaign ${item.campaignId} · ${source}. Overview ${item.fromDate||'all saved dates'} to ${item.throughDate} (${item.timezone}); ${item.returnedDates.length} returned dates.`;
      const base={target:item.campaignId,evidence};
      const id=kind+'-'+(item.reportId||item.snapshotId);
      if(item.missingDates>0||!item.returnedDates.length)result.push({...base,id:id+'-coverage',title:'Review observation coverage',
        evidence:evidence+(item.missingDates>0?` ${item.missingDates} requested dates in this period were not returned.`:''),
        action:paid?'Open Leads and results and review the saved paid report and requested dates.':'Open What we found and review the saved Search Console snapshot and date window.',
        limit:'Missing observations are unmeasured, not zero activity. Reviewing a campaign does not refresh any source.'});
      if(item.clicks>0)result.push({...base,id:id+'-path',title:'Review the enquiry path',
        evidence:evidence+` ${item.clicks} reported clicks in the returned rows.`,
        action:'Review the saved destination and actual enquiry source references in this campaign before preparing changes.',
        limit:'Clicks are not unique people, enquiries or sales. These observations have no established link to CRM outcomes; no winning advert or spend change is recommended.'});
    }
  }
  return result;
}
