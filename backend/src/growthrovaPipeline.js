// Current saved state, shared by enquiry filters and review recommendations.
export function pipelineReview(lead,now){
  const data=lead.data;
  const active=['new','contacted','qualified','booked'].includes(data.status);
  return {
    active,
    stale:['new','contacted'].includes(data.status)&&now-lead.updated>=7*86400,
    unplanned:active&&!(data.nextAction?.trim()&&(data.actionState??'open')==='open'),
  };
}
