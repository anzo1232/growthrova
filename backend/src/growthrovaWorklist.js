import {actionTiming} from './growthrovaFollowThrough.js';

export const workKinds={human:'Human follow-through',retention:'Retention',review:'Review request'};
export function taskTiming(task,today){
  return actionTiming({nextAction:task.action,actionState:task.state,actionDueDate:task.dueDate},today);
}
export function worklistTasks(tasks,{state='open',timing='',kind='',assignment='',query=''}={},today){
  const terms=query.normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
  return tasks.filter(task=>{
    if(state&&task.state!==state||kind&&task.kind!==kind)return false;
    if(assignment==='unassigned'&&task.responsiblePerson||assignment==='assigned'&&!task.responsiblePerson)return false;
    const due=taskTiming(task,today);
    if(timing==='due'&&due!=='Overdue'&&due!=='Due today')return false;
    if(timing&&timing!=='due'&&due!==timing)return false;
    const text=[task.name,task.campaignName,task.action,task.responsiblePerson].join('\n').normalize('NFKC').toLowerCase();
    return terms.every(term=>text.includes(term));
  }).sort((a,b)=>{
    // Open work first, dated work before undated, then stable enquiry/kind IDs.
    return Number(a.state!=='open')-Number(b.state!=='open')||
      (a.dueDate||'9999-99-99').localeCompare(b.dueDate||'9999-99-99')||
      a.id.localeCompare(b.id)||a.kind.localeCompare(b.kind);
  });
}
