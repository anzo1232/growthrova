// Calendar dates are deliberately UTC, without an inferred appointment time.
export const followThroughDefaults={responsiblePerson:'',nextAction:'',actionDueDate:'',actionState:'open',followUpChannel:'unspecified',followUpDraft:''};
export const actionStates={open:'Open',done:'Done',cancelled:'Cancelled'};
export const followUpChannels={unspecified:'Not chosen',email:'Email',whatsapp:'WhatsApp',phone:'Phone',other:'Other'};
export const todayUTC=(now=Date.now())=>new Date(now).toISOString().slice(0,10);
export function actionTiming(data,today=todayUTC()){
  if(!data.nextAction?.trim()||(data.actionState||'open')!=='open')return '';
  if(!data.actionDueDate)return 'No due date';
  if(data.actionDueDate<today)return 'Overdue';
  return data.actionDueDate===today?'Due today':'Upcoming';
}
