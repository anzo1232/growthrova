import test from 'node:test';
import assert from 'node:assert/strict';
import {paymentCorrection} from '../src/growthrovaPaymentCorrection.js';
import {saleTotals} from '../src/growthrovaSales.js';

function fixture(key='sale'){
  const sale={amount:'123.45',currency:'USD',date:'2026-11-04',sourceReference:'Stripe charge ch_saved',state:'recorded',correctionNote:''};
  const data=key==='sale'?{sale}:{sale:{...sale,amount:'5.00',sourceReference:'Unrelated order'},purchases:[{...sale,id:key}]};
  return {data,receipt:{chargeId:'ch_saved',purchaseKey:key,initial:{...sale},current:{...sale},ownerChanged:false,
    latest:{checkedAt:1793872800,refundedAmount:'12.34',fullyRefunded:false,disputed:false}}};
}

test('partial refund prepares exact remaining value for existing totals, retaining original evidence',()=>{
  const {receipt,data}=fixture();
  const original=structuredClone({receipt,data});
  const prepared=paymentCorrection(receipt,data);
  assert.equal(prepared.sale.amount,'111.11');
  assert.equal(prepared.sale.date,data.sale.date);
  assert.equal(prepared.sale.sourceReference,data.sale.sourceReference);
  assert.match(prepared.sale.correctionNote,/12.34 USD of initial capture 123.45 USD/);
  const changed={...data,...prepared.patch};
  assert.equal(saleTotals([{data:changed}],'','2026-11-05').rows[0].amount,'111.11');
  assert.deepEqual({receipt,data},original);
  assert.equal(paymentCorrection(receipt,changed).patch,undefined); // Never subtract twice.
});

test('full refund voids the exact additional purchase and preserves unrelated sales',()=>{
  const {receipt,data}=fixture('a'.repeat(32));
  receipt.latest={...receipt.latest,refundedAmount:'123.45',fullyRefunded:true};
  const prepared=paymentCorrection(receipt,data);
  assert.equal(prepared.sale.state,'voided');
  assert.equal(prepared.sale.amount,'123.45');
  assert.equal(prepared.sale.id,receipt.purchaseKey);
  const changed={...data,...prepared.patch};
  assert.deepEqual(changed.sale,data.sale);
  const totals=saleTotals([{data:changed}],'','2026-11-05');
  assert.equal(totals.voided,1);
  assert.equal(totals.rows[0].amount,'5.00');
});

test('changed, missing, disputed or inconsistent evidence cannot prepare a correction',()=>{
  const {receipt,data}=fixture();
  for(const patch of [{latest:null},{ownerChanged:true},{current:{...receipt.current,amount:'100.00'}},
    ...[{disputed:true},{refundedAmount:'0.00'},{refundedAmount:'123.46'},
      {refundedAmount:'12.345'},{fullyRefunded:true},{checkedAt:NaN}]
      .map(latest=>({latest:{...receipt.latest,...latest}}))]){
    assert.equal(paymentCorrection({...receipt,...patch},data).patch,undefined);
  }
  assert.equal(paymentCorrection(receipt,{}).patch,undefined);
  assert.equal(paymentCorrection(receipt,{sale:{...data.sale,correctionNote:'Owner corrected'}}).patch,undefined);
});
