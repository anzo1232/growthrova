// These categories overlap. An owner correction does not resolve payment
// evidence, and a saved observation never proves the current provider state.
export function paymentReviewFlags(payment){
  const check=payment.latest;
  return {
    incoming:check?.needsRecheck===true,
    refund:check?.objectKind==='refund'||(typeof check?.refundedAmount==='string'&&Number(check.refundedAmount)>0),
    dispute:check?.objectKind==='dispute'||check?.disputed===true,
    changed:payment.ownerChanged===true,
    initial:!check,
  };
}

export function paymentReviewQueue(payments,filters={}){
  const counts={incoming:0,refund:0,dispute:0,changed:0,initial:0};
  const query=(filters.query||'').normalize('NFKC').toLocaleLowerCase().trim();
  const rows=payments.map(payment=>{
    const flags=paymentReviewFlags(payment);
    for(const key of Object.keys(counts))if(flags[key])counts[key]++;
    return {payment,flags};
  }).filter(({payment,flags})=>(!filters.review||flags[filters.review])
    &&(!filters.campaign||payment.campaignId===filters.campaign)
    &&(!query||[payment.name,payment.campaignName,payment.chargeId,payment.accountId]
      .some(value=>(value||'').normalize('NFKC').toLocaleLowerCase().includes(query))))
    .sort((a,b)=>Number(b.flags.incoming)-Number(a.flags.incoming)
      ||(b.payment.latest?.checkedAt||b.payment.initialCheckedAt)-(a.payment.latest?.checkedAt||a.payment.initialCheckedAt)
      ||a.payment.accountId.localeCompare(b.payment.accountId)||a.payment.chargeId.localeCompare(b.payment.chargeId));
  return {counts,rows};
}
