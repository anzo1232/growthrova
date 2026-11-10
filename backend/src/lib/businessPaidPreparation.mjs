import {googleScheduleIssues} from '../growthrovaGoogleBudget.js';

export const paidPlatforms={meta:'Meta',google:'Google Search'};
export const googlePreparationLists=[['headlines','Headline options',15,30],['descriptions','Description options',4,90],
  ['keywords','Search keyword intentions',50,80],['negativeKeywords','Searches to exclude',50,80]];

export function paidPlan(doc,platform){
  return platform==='meta'?doc.paidCampaign:platform==='google'?doc.googleCampaign:null;
}

/** Local preparation only. These checks confer no account or execution authority. */
export function paidPreparationIssues(plan,platform){
  if(!plan)return ['Start a campaign draft'];
  const schedule=plan.budgetSchedule;
  const cents=/^\d+(\.\d{1,2})?$/.test(plan.dailyBudget)?Math.round(Number(plan.dailyBudget)*100):0;
  if(platform==='meta')return [
    !plan.audience.trim()&&'Describe the audience',!plan.primaryText.trim()&&'Write the advert text',
    !plan.headline.trim()&&'Write a headline',!plan.callToAction.trim()&&'Choose a call to action',
    !plan.destinationUrl.trim()&&'Add the destination page',
    ...(schedule?googleScheduleIssues(schedule,{minimumDays:1}):[!cents&&'Propose a daily budget']),
    !plan.asset&&'Choose a saved image'
  ].filter(Boolean);
  if(platform!=='google')throw new TypeError('Choose a paid platform');
  return [
    !plan.location.trim()&&'Describe where customers should be located',
    !plan.language.trim()&&'Choose the language for the advert and destination',
    !plan.destinationUrl.trim()&&'Add a destination page',!schedule&&!cents&&'Propose an average daily budget',
    ...googleScheduleIssues(schedule),
    plan.headlines.filter(s=>s.trim()).length<3&&'Prepare at least three headline options',
    plan.descriptions.filter(s=>s.trim()).length<2&&'Prepare at least two description options',
    !plan.keywords.some(s=>s.trim())&&'Prepare search keyword intentions',
    googlePreparationLists.some(([key,,count,limit])=>plan[key].length>count||plan[key].some(s=>s.length>limit))&&'Shorten copy or keyword lists to the preparation limits'
  ].filter(Boolean);
}

function proposedBudget(plan,platform){
  if(!plan)return null;
  const schedule=plan.budgetSchedule;
  if(schedule){
    if(googleScheduleIssues(schedule,{minimumDays:platform==='meta'?1:3}).length)return null;
    return {currency:plan.currency,kind:platform==='meta'?'Meta lifetime total':'Google campaign total',
      cents:Math.round(Number(schedule.totalBudget)*100)};
  }
  if(!/^\d+(\.\d{1,2})?$/.test(plan.dailyBudget)||Number(plan.dailyBudget)<=0||
    !Number.isInteger(plan.durationDays)||plan.durationDays<1||plan.durationDays>90)return null;
  return {currency:plan.currency,kind:'Daily × planning duration',cents:Math.round(Number(plan.dailyBudget)*100)*plan.durationDays};
}

export function paidPreparationQueue(records){
  const items=[];
  for(const record of records)for(const platform of Object.keys(paidPlatforms)){
    const plan=paidPlan(record.document,platform),issues=paidPreparationIssues(plan,platform);
    items.push({campaignId:record.id,revision:record.revision,name:record.document.name,platform,
      stage:!plan?'not_started':issues.length?'incomplete':'filled',issues,budget:proposedBudget(plan,platform)});
  }
  return items.sort((a,b)=>a.name.localeCompare(b.name)||a.campaignId.localeCompare(b.campaignId)||a.platform.localeCompare(b.platform));
}

export function filterPaidPreparation(items,{platform='',stage=''}={}){
  return items.filter(item=>(!platform||item.platform===platform)&&(!stage||item.stage===stage));
}

export function paidPreparationTotals(items){
  const totals=new Map();
  for(const item of items){
    if(!item.budget)continue;
    const {currency,kind,cents}=item.budget,key=currency+':'+kind;
    const row=totals.get(key)||{currency,kind,cents:0,count:0};
    row.cents+=cents;row.count++;totals.set(key,row);
  }
  return [...totals.values()].sort((a,b)=>a.currency.localeCompare(b.currency)||a.kind.localeCompare(b.kind));
}
