/** Local preparation descriptions; never execution or spending authority. */
export function metaBudgetLines(plan){
  const schedule=plan.budgetSchedule;
  if(schedule)return [
    `Proposed ad-set lifetime budget: ${plan.currency} ${schedule.totalBudget||'not set'}.`,
    `Proposed dates: ${schedule.startDate||'not set'} through ${schedule.endDate||'not set'} (inclusive). Account timezone: ${schedule.accountTimezone||'not confirmed'}.`,
    'Whole account-local days: start 00:00:00, end 23:59:59. Paused creation requires separately reviewed lifetime-budget eligibility and the exact account timezone, using new resources. These dates do not establish the UTC launch expiry or a hard daily spending ceiling; Growthrova activation remains unavailable.'
  ];
  const cents=/^\d+(\.\d{1,2})?$/.test(plan.dailyBudget)?Math.round(Number(plan.dailyBudget)*100):0;
  return [
    `Proposed average daily budget: ${plan.currency} ${plan.dailyBudget||'not set'} · ${plan.durationDays} days.`,
    `Planning total: ${plan.currency} ${(cents*plan.durationDays/100).toFixed(2)}. This arithmetic is not a platform spending cap or delivery forecast.`
  ];
}
