/** Reconcile an authoritative list with saves completed since its request began. */
export function reconcileCampaignList(incoming, current, atRequest) {
  const before=new Map(atRequest.map(item=>[item.id,item.revision]));
  const fetched=new Map(incoming.map(item=>[item.id,item.revision]));
  const saved=current.filter(item=>item.revision>(before.get(item.id)||0)
    &&item.revision>(fetched.get(item.id)||0));
  const retained=new Set(saved.map(item=>item.id));
  return [...saved,...incoming.filter(item=>!retained.has(item.id))];
}
