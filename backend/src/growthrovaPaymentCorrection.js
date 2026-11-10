import {saleCurrencies} from './growthrovaSales.js';

const fields=['amount','currency','date','sourceReference','state','correctionNote'];
const sameSale=(a,b)=>Boolean(a&&b&&fields.every(key=>a[key]===b[key]));
const minor=value=>typeof value==='string'&&/^(0|[1-9][0-9]{0,8})\.[0-9]{2}$/.test(value)
  ?Number(value.split('.')[0])*100+Number(value.split('.')[1]):null;
const money=value=>Math.floor(value/100)+'.'+String(value%100).padStart(2,'0');

// This prepares ordinary owner edits only. The existing revisioned save remains
// authoritative; evidence and original purchase history are never rewritten.
export function paymentCorrection(receipt,data){
  const blocked=reason=>({reason});
  const initial=receipt?.initial,check=receipt?.latest;
  if(!check)return blocked('Save a later refund check before preparing a correction.');
  if(check.needsRecheck)return blocked('Incoming payment evidence needs a current status check before preparing a correction.');
  if(check.disputed!==false)return blocked('Review the dispute manually; its outcome is not established by this check.');
  const current=receipt.purchaseKey==='sale'?data?.sale:data?.purchases?.find(item=>item.id===receipt.purchaseKey);
  if(receipt.ownerChanged||!sameSale(current,initial)||!sameSale(receipt.current,initial)||initial?.state!=='recorded')
    return blocked('This purchase has changed. Review its correction and history manually.');
  const captured=minor(initial.amount),refunded=minor(check.refundedAmount);
  if(captured===null||captured<=0||refunded===null||refunded<=0||refunded>captured
      ||!saleCurrencies.includes(initial.currency)||check.fullyRefunded!==(captured===refunded)
      ||!Number.isFinite(check.checkedAt)||check.checkedAt<=0||check.checkedAt>8640000000000
      ||!/^ch_[A-Za-z0-9]{1,100}$/.test(receipt.chargeId))
    return blocked('No supported positive refund correction is available from this evidence.');
  const full=refunded===captured;
  const sale={...current,amount:full?initial.amount:money(captured-refunded),state:full?'voided':'recorded',
    correctionNote:`Owner reviewed Stripe charge ${receipt.chargeId}: refund ${check.refundedAmount} ${initial.currency} of initial capture ${initial.amount} ${initial.currency}, checked ${new Date(check.checkedAt*1000).toISOString()}. ${full?'Fully refunded; record voided.':'Recorded value reduced by the observed refund.'}`};
  return {sale,full,patch:receipt.purchaseKey==='sale'?{sale}:{purchases:data.purchases.map(item=>item.id===receipt.purchaseKey?sale:item)}};
}
