/** Offline API bridge to the same planner/document modules used by the UI. */
import fs from 'node:fs';
import {savedPlanReview} from '../src/lib/businessPlanReview.mjs';
import {organicQueue,filterOrganicQueue} from '../src/lib/businessOrganicQueue.mjs';
import {organicWorkMarkdown} from '../src/lib/businessOrganicExport.mjs';
import {marketingStrategyText} from '../src/lib/businessStrategyExport.mjs';
import {applyWriting,writingText,writingMatchesDocument,previewWritingReplacement,
  applyWritingReplacement} from '../src/lib/growthrovaWriting.mjs';
import {applyConceptDirection,applyImageConceptCopy,conceptPlanMatches} from '../src/lib/growthrovaCreativePlans.mjs';
import {editCampaignBrand} from '../src/lib/businessCampaignBrand.mjs';
import {prepareUrlCampaign,prepareOwnerCampaign,prepareLimitedResearchCampaign,prepareLimitedResearchContext} from '../src/lib/businessUrlCampaignPipeline.mjs';
import {createMarketingDocument,editMarketingPost,editMarketingCreative,
  addSupportingImageConcepts,usePostWordsForCreative,
  reviewMarketingCopy,marketingPlanCsv,marketingCreativeText} from '../src/lib/businessMarketingDocument.mjs';
import {applyChannelPlan,applySuggestedChannel} from '../src/lib/businessChannelPlan.mjs';
import {createPublicationCalendar,publicationCalendarIcs} from '../src/lib/businessPublicationCalendar.mjs';
import {contentAgenda,filterContentAgenda} from '../src/growthrovaContentAgenda.mjs';
import {contentAgendaIcs} from '../src/lib/businessContentCalendar.mjs';
import {applyPaidStrategyField} from '../src/lib/businessPaidStrategy.mjs';
import {paidPreparationIssues,paidPlan} from '../src/lib/businessPaidPreparation.mjs';
import {addOrganicStrategyBrief,addWebsiteImprovement} from '../src/lib/businessOrganicStrategy.mjs';
import {prepareNextStrategyCampaign, editOwnerStrategy, editCampaignGoal, reviewBusinessFact,
  linkStrategyEvidence, confirmOwnerStrategy, strategyConfirmed, strategyFields, completeStrategyCalendar,
  refreshStrategyCalendar, useConfirmedBriefForPost, appendReviewedBusinessDetail,
  appendReviewedCreativeDetail} from '../src/lib/businessOwnerStrategy.mjs';

try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const {report, goal, business, sourceUrl, ownerBrief} = input;
  if (Object.hasOwn(input,'limitedResearchContext')) {
    process.stdout.write(JSON.stringify(prepareLimitedResearchContext(report)));
  } else if (Object.hasOwn(input,'organicQueue')) {
    const current=[],historical=[];
    for(const record of input.organicQueue){
      if(record.document.business===input.business&&(record.document.sourceUrl||'')===(input.sourceUrl||''))current.push(record);
      else historical.push({campaignId:record.id,revision:record.revision,name:record.document.name,
        reason:'Review and save the current business context before preparing this website work.'});
    }
    const queue=organicQueue(current);
    process.stdout.write(JSON.stringify({...queue,items:filterOrganicQueue(queue.items,input.filters),historical}));
  } else if (Object.hasOwn(input,'contentAgenda')) {
    const current=[],historical=[];
    for(const record of input.contentAgenda){
      if(record.document.business===input.business&&(record.document.sourceUrl||'')===(input.sourceUrl||''))current.push(record);
      else historical.push({campaignId:record.id,revision:record.revision,updated:record.updated,
        name:record.document.name,goal:record.document.goal,
        reason:'Review and save the current business context before using these planning dates'});
    }
    const agenda=contentAgenda(current);
    const items=filterContentAgenda(agenda.items,input.filters);
    process.stdout.write(JSON.stringify({items,gaps:[...agenda.gaps,...historical],
      ...(input.agendaFormat==='calendar-ics'?{export:{filename:'growthrova-content-plan.ics',
        mediaType:'text/calendar;charset=utf-8',content:contentAgendaIcs(items)}}:{})}));
  } else if (Object.hasOwn(input,'planningWorklist')) {
    process.stdout.write(JSON.stringify(input.planningWorklist.map(record=>{
      const review=savedPlanReview(record.document);
      const count=(items,state)=>items.filter(item=>item.state===state).length;
      const contextMatches=record.document.business===input.business
        &&(record.document.sourceUrl||'')===(input.sourceUrl||'');
      const actions=[...review.actions];
      if(!contextMatches) actions.unshift({code:'review_business_context',surface:'prepare-research-refresh',
        updateBusinessContext:true,
        message:'Select saved findings for the current website and explicitly update this plan’s business context. Review retained words and historical work before saving.'});
      return {campaignId:record.id,revision:record.revision,savedAt:record.updated,
        name:record.document.name,goal:record.document.goal,contextMatches,
        factsPending:review.facts.pendingIndices.length,
        strategyConfirmation:review.strategy.confirmation,
        calendar:{startDate:review.calendar.startDate,validStartDate:review.calendar.validStartDate,
          missingDays:review.calendar.missingDays.length,incompleteDays:review.calendar.incompleteDays.length,
          reminderExportAvailable:review.calendar.reminderExportAvailable},
        copy:Object.fromEntries(['posts','creatives'].map(key=>[key,{
          total:review.copy[key].length,needsCopy:count(review.copy[key],'needs_copy'),
          needsReview:count(review.copy[key],'needs_review'),copyReviewed:count(review.copy[key],'copy_reviewed'),
        }])),nextAction:actions[0]||null,actions};
    })));
  } else if (Object.hasOwn(input,'planReview')) {
    process.stdout.write(JSON.stringify(savedPlanReview(input.sourceDocument)));
  } else if (input.exportPreparation?.format==='organic-markdown') {
    process.stdout.write(JSON.stringify({
      filename:'growthrova-organic-work.md',mediaType:'text/markdown;charset=utf-8',
      content:organicWorkMarkdown(input.sourceDocument,{
        saved:input.savedMetadata,itemIds:input.exportPreparation.itemIds}),
    }));
  } else if (input.exportPreparation?.format==='strategy-text') {
    process.stdout.write(JSON.stringify({
      filename:'growthrova-business-strategy.txt',mediaType:'text/plain;charset=utf-8',
      content:marketingStrategyText(input.sourceDocument,input.savedMetadata),
    }));
  } else if (input.exportPreparation?.format==='concept-plan-json') {
    const proposal=input.exportPreparation.proposal;
    const matchesCampaign=conceptPlanMatches(input.sourceDocument,proposal);
    const notice=(matchesCampaign?'Business context and brand match the selected saved campaign revision.':
      'Business context or brand differs from the selected saved campaign revision; review before reuse.')+
      ' Exporting does not approve, apply, generate images, publish or spend.';
    process.stdout.write(JSON.stringify({
      filename:'growthrova-concept-plan.json',mediaType:'application/json;charset=utf-8',
      operationId:proposal.operationId,state:proposal.state,matchesCampaign,
      content:JSON.stringify({exportReview:{matchesCampaign,notice},plan:proposal},null,2),
    }));
  } else if (input.exportPreparation?.format==='writing-text') {
    const proposal=input.exportPreparation.proposal;
    const matchesCampaign=writingMatchesDocument(input.sourceDocument,proposal);
    process.stdout.write(JSON.stringify({
      filename:'growthrova-proposed-writing.txt',mediaType:'text/plain;charset=utf-8',
      operationId:proposal.operationId,state:proposal.state,matchesCampaign,
      content:'Saved writing from its original business context. '+
        (matchesCampaign?'Context matches the selected saved campaign revision.':
          'Context differs from the selected saved campaign revision; review before reuse.')+
        '\nExporting does not approve, apply, render, publish or send this writing.\n\n'+writingText(proposal),
    }));
  } else if (Object.hasOwn(input,'exportPreparation')) {
    const preparation=input.exportPreparation;
    const csv=preparation.format==='calendar-csv';
    const ics=preparation.format==='calendar-ics';
    const doc=input.sourceDocument;
    process.stdout.write(JSON.stringify({
      filename:csv?'growthrova-marketing-plan.csv':ics?'growthrova-30-day-post-reminders.ics'
        :`growthrova-${preparation.creativeId}-draft.txt`,
      mediaType:csv?'text/csv;charset=utf-8':ics?'text/calendar;charset=utf-8':'text/plain;charset=utf-8',
      content:csv?marketingPlanCsv(doc):ics?publicationCalendarIcs(
        createPublicationCalendar(doc.posts,doc.calendarStartDate),
        {business:doc.business,sourceUrl:doc.sourceUrl,campaignId:input.savedMetadata.id,
          revision:input.savedMetadata.revision,updated:input.savedMetadata.updated})
        :marketingCreativeText(doc,preparation.creativeId),
    }));
  } else if (Object.hasOwn(input,'imageCopyPreparation')) {
    const doc=applyImageConceptCopy(input.sourceDocument,input.imageCopyPreparation);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'conceptDirectionPreparation')) {
    const {proposal,conceptId,targetId,edits,day}=input.conceptDirectionPreparation;
    const doc=applyConceptDirection(input.sourceDocument,proposal,conceptId,targetId,edits,day);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'writingCopyPreview')) {
    const {proposal,changes}=input.writingCopyPreview;
    process.stdout.write(JSON.stringify(changes.map(({day,creativeId,index})=>
      previewWritingReplacement(input.sourceDocument,proposal,creativeId===undefined?'post':'creative',
        creativeId===undefined?day:creativeId,index))));
  } else if (Object.hasOwn(input,'writingCopyPreparation')) {
    const {proposal,changes,comparisons}=input.writingCopyPreparation;
    let doc=input.sourceDocument;
    for (const [i,{day,creativeId,index}] of changes.entries()) doc=comparisons
      ?applyWritingReplacement(doc,proposal,comparisons[i]):applyWriting(doc,proposal,
        creativeId===undefined?'post':'creative',creativeId===undefined?day:creativeId,index);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'brandPreparation')) {
    const doc=editCampaignBrand(input.sourceDocument,input.brandPreparation);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'channelPlanPreparation')) {
    const preparation=input.channelPlanPreparation;
    let doc=input.sourceDocument;
    if (preparation.applyMix) doc=applyChannelPlan(doc);
    else for (const change of preparation.changes) doc=applySuggestedChannel(doc,change.day,change.channel);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'contentPlanPreparation')) {
    const preparation=input.contentPlanPreparation;
    let doc=input.sourceDocument;
    if (preparation.addSupportingIdeas) doc=addSupportingImageConcepts(doc);
    for (const change of preparation.changes) {
      if (change.type==='post') doc=editMarketingPost(doc,change.day,change.fields);
      else {
        doc=editMarketingCreative(doc,change.id,change.fields||{});
        if (Object.hasOwn(change,'copyFromDay')) doc=usePostWordsForCreative(doc,change.id,change.copyFromDay);
      }
    }
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'contentCopyPreparation')) {
    let doc=input.sourceDocument;
    for (const change of input.contentCopyPreparation) {
      const target=change.type==='post'?change.day:change.id;
      if (change.review===true) doc=reviewMarketingCopy(doc,change.type,target);
      else {
        // Apply explicit words first, then append current reviewed statements.
        // Any failure discards the entire unsaved document, including prior targets.
        if (change.fields) doc=change.type==='post' ? editMarketingPost(doc,target,change.fields)
          : editMarketingCreative(doc,target,change.fields);
        for (const index of change.appendFactIndices||[]) {
          doc=change.type==='post' ? appendReviewedBusinessDetail(doc,target,index)
            : appendReviewedCreativeDetail(doc,target,index);
        }
      }
    }
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'websiteImprovementPreparation')) {
    let doc=input.sourceDocument;
    for (const index of input.websiteImprovementPreparation.recommendationIndices) doc=addWebsiteImprovement(doc,index);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'organicPreparation')) {
    let doc=input.sourceDocument;
    for (const index of input.organicPreparation.observationIndices) doc=addOrganicStrategyBrief(doc,index);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'paidPreparation')) {
    const preparation=input.paidPreparation;
    const property=preparation.platform==='meta'?'paidCampaign':'googleCampaign';
    let doc=input.sourceDocument;
    if (Object.hasOwn(preparation,'plan')) doc={...doc,[property]:preparation.plan};
    if (!doc[property]) throw new TypeError('Start the platform draft');
    for (const key of preparation.strategyFields) doc=applyPaidStrategyField(doc,preparation.platform,key);
    process.stdout.write(JSON.stringify({document:{...doc,canPublish:false,canSpend:false},
      preparationIssues:paidPreparationIssues(paidPlan(doc,preparation.platform),preparation.platform)}));
  } else if (Object.hasOwn(input,'strategyReview')) {
    const review=input.strategyReview;
    let doc=input.sourceDocument;
    if (Object.hasOwn(review,'goal')) doc=editCampaignGoal(doc,review.goal);
    for (const [key,value] of Object.entries(review.strategy||{})) doc=editOwnerStrategy(doc,key,value);
    for (const fact of review.factReviews||[]) doc=reviewBusinessFact(doc,fact.index,fact.decision,fact.statement||'');
    for (const [key,id] of Object.entries(review.evidenceLinks||{})) doc=linkStrategyEvidence(doc,key,id);
    if (Object.hasOwn(review,'calendarStartDate')) doc={...doc,calendarStartDate:review.calendarStartDate};
    if (review.confirm===true) doc=confirmOwnerStrategy(doc);
    if (review.completeCalendar===true) doc=completeStrategyCalendar(doc);
    if (review.refreshDays) doc=refreshStrategyCalendar(doc,review.refreshDays);
    for (const day of review.briefCopyDays||[]) doc=useConfirmedBriefForPost(doc,day);
    process.stdout.write(JSON.stringify({...doc,canPublish:false,canSpend:false}));
  } else if (Object.hasOwn(input,'sourceDocument')) {
    process.stdout.write(JSON.stringify(prepareNextStrategyCampaign(input.sourceDocument,
      {goal, startDate:input.startDate})));
  } else {
    let initialStrategy=input.initialStrategy;
    if(Object.hasOwn(input,'strategyDocument')) {
      const source=input.strategyDocument;
      if(!strategyConfirmed(source)||source.business!==business||source.sourceUrl!==report?.source_url)
        throw new TypeError('Confirm the saved strategy for the current business website');
      // Reuse owner statements only. Fresh observations, decisions and review
      // belong to the new plan; no historical approval or work is cloned.
      initialStrategy=Object.fromEntries(Object.keys(strategyFields).map(key=>[key,source.ownerStrategy[key]]));
    }
    let campaign = Object.hasOwn(input,'ownerBrief')
      ? prepareOwnerCampaign({...ownerBrief, goal, business, sourceUrl})
      : report?.evidence?.status==='insufficient'&&initialStrategy?.offer
        ? prepareLimitedResearchCampaign(report,{business,goal,strategy:initialStrategy})
        : prepareUrlCampaign(report, {objective: goal, businessName:business});
    // Older retained extracts may lack an evidence classification and an offer.
    // Preserve working URL plans; only fill an absent plan from explicit input.
    if(!campaign.plan&&initialStrategy?.offer)
      campaign=prepareLimitedResearchCampaign(report,{business,goal,strategy:initialStrategy});
    let document=createMarketingDocument({...campaign, business});
    // Owner statements remain strategy input, never website observations.
    // Existing draft words are retained for review rather than silently rewritten.
    for (const [key,value] of Object.entries(initialStrategy||{}))
      document=editOwnerStrategy(document,key,value);
    // The owner date anchors the plan without granting review or execution
    // permissions. The authoritative normalizer checks the actual date.
    if(Object.hasOwn(input,'startDate')) document={...document,calendarStartDate:input.startDate};
    process.stdout.write(JSON.stringify(document));
  }
} catch {
  // Website details/stack traces do not belong in child-process diagnostics.
  process.exitCode = 2;
}
