/** Preparation wording only; no platform payloads or launch authority. */
export function googleBudgetLines(plan){
  const schedule=plan.budgetSchedule;
  if(schedule)return [
    `Proposed campaign total: ${plan.currency} ${schedule.totalBudget||'not set'}.`,
    `Proposed dates: ${schedule.startDate||'not set'} through ${schedule.endDate||'not set'} (inclusive). Account timezone: ${schedule.accountTimezone||'not confirmed'}.`,
    'Whole account-local days: start 00:00:00, end 23:59:59. These dates are not the UTC launch approval expiry.',
    'Requires a new campaign; existing daily-budget campaigns cannot change budget type. Paused creation requires separately reviewed account eligibility and timezone. No daily spending cap or Growthrova activation is available.'
  ];
  const cents=/^\d+(\.\d{1,2})?$/.test(plan.dailyBudget)?Math.round(Number(plan.dailyBudget)*100):0;
  return [
    `Proposed average daily budget: ${plan.currency} ${plan.dailyBudget||'not set'} · ${plan.durationDays} days.`,
    `Planning total: ${plan.currency} ${(cents*plan.durationDays/100).toFixed(2)}. This arithmetic is not a platform spending cap or delivery forecast.`
  ];
}

export function googleScheduleIssues(schedule,{minimumDays=3}={}){
  if(!schedule)return [];
  const issues=[];
  if(!/^(?:0|[1-9][0-9]{0,6})(?:\.\d{1,2})?$/.test(schedule.totalBudget)||Number(schedule.totalBudget)<=0)
    issues.push('Propose a positive total budget with at most two decimal places');
  const dates=['startDate','endDate'].map(key=>{
    const value=schedule[key];
    const timestamp=/^\d{4}-\d{2}-\d{2}$/.test(value)?Date.parse(value+'T00:00:00Z'):NaN;
    return Number.isFinite(timestamp)&&new Date(timestamp).toISOString().slice(0,10)===value?timestamp:NaN;
  });
  if(dates.some(value=>!Number.isFinite(value)))issues.push('Choose valid start and end calendar dates');
  else if((dates[1]-dates[0])/86400000+1<minimumDays||(dates[1]-dates[0])/86400000+1>90)
    issues.push(`Choose ${minimumDays} to 90 inclusive calendar days for the total-budget plan`);
  try{
    if(!schedule.accountTimezone.trim())throw new Error();
    new Intl.DateTimeFormat('en',{timeZone:schedule.accountTimezone}).format();
  }catch{issues.push('Confirm the account timezone name, such as Europe/London');}
  return issues;
}
