'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
// Set PROFIT_SKILL_ROOT when copying this file to another test directory.
const root=process.env.PROFIT_SKILL_ROOT||path.resolve(__dirname,'..');
const E=require(path.join(root,'scripts/engine.js'));
const raw1=require(path.join(root,'examples/case-1.json'));
const raw2=require(path.join(root,'examples/case-2.json'));
const fixture=(n=2)=>E.clone(n===1?raw1:raw2);
const invalid=x=>assert.equal(E.calculate(x).metrics,null);
const close=(a,b)=>assert.ok(E.d(a).minus(b).abs().lt('1e-30'),`${a} != ${b}`);
function perKg(x){const q=x.logistics.express;Object.assign(q,{mode:'perKg',boxes:[{count:1,units:1,cm:['50','40','30'],kg:'8'}],compareScope:'box',roundScope:'box',dimShare:'1',roundStepKg:'0',minimumWeightKg:'0',minimumWeightScope:'box',pricePerKg:'1',minimumCharge:'0',minimumChargeScope:'box',surcharges:[]});return q;}
function weight(x){const r=E.calculate(x);assert.ok(r.metrics,JSON.stringify(r.missingItems));return r.feeItems.find(x=>x.id==='H').detail.weight;}
test('PRD two fixed formula cases',()=>{assert.equal(E.calculate(fixture(1)).metrics.grossProfit,'36.5');assert.equal(E.calculate(fixture(2)).metrics.grossProfit,'7.5');});
test('foreign currency sales tax converts before subtracting income',()=>{const x=fixture();Object.assign(x.ruleSnapshot.rules.salesTax,{currency:'CNY',expression:'7'});const r=E.calculate(x);assert.equal(r.metrics.salesTax,'1');assert.equal(r.metrics.grossProfit,'6.6');});
test('manual fixed commission cannot bind ASIN alone',()=>{const x=fixture();Object.assign(x.ruleSnapshot.rules.commission,{source:{type:'user',locator:'user input',at:'2026-10-24'},expression:'7.5',bindings:{'product.asin':x.product.asin}});x.product.price='500';invalid(x);});
test('supplemental cost cannot duplicate built-in commission',()=>{const x=fixture();x.extraFees.push({id:'commission2',category:'M',reason:'re-enter',uniqueCostKey:'commission',unit:'retained',rule:E.clone(x.ruleSnapshot.rules.commission)});invalid(x);});
test('included import tax cannot bypass duplicate check with empty coverage',()=>{const x=fixture();x.logistics.express.inclusions.duty='included';x.logistics.express.inclusions.importTax='included';x.ruleSnapshot.rules.importTax.covers=[];invalid(x);});
test('manual freight cannot disappear via notApplicable',()=>{const x=fixture();Object.assign(x.logistics.express.manualRule,{status:'notApplicable',reason:'do not consider freight'});invalid(x);});
test('storage tariff transition requires date confirmation even with same URL',()=>{const x=fixture();x.scenario.entryDate='2026-10-24';x.scenario.exitDate='2026-11-24';const a=E.clone(x.ruleSnapshot.rules.storage),b=E.clone(a);Object.assign(a,{validTo:'2026-10-31',volumeCm3PerUnit:'1000',expression:'1'});Object.assign(b,{validFrom:'2026-11-01',volumeCm3PerUnit:'1000',expression:'10'});x.ruleSnapshot.rules.storage={mode:'monthly',periods:[a,b]};invalid(x);x.scenario.dateBoundaryConfirmedAt='2026-10-24';assert.ok(E.calculate(x).metrics);});
test('recoverable service tax on shipped supplemental charges includes refunded orders',()=>{const x=fixture(1);x.extraFees=[{id:'extra-test',category:'O',uniqueCostKey:'independent-cost',reason:'test recoverable',unit:'shipped',rule:{...E.clone(x.ruleSnapshot.rules.commission),expression:'10',tax:{mode:'excluded',rate:'0.1',recoverable:true}}}];close(E.calculate(x).metrics.recoverableTax,E.d(1).div('0.9'));});
test('malformed editable UI parameters rejected before state replacement',()=>{const x=fixture();x.editableParameters={malformed:true};assert.throws(()=>E.auditImport(x));});
test('default express dimensional weight is 12 kg',()=>{const x=fixture(1);perKg(x);assert.equal(weight(x),'12');});
test('50 percent volumetric excess share gives 10 kg',()=>{const x=fixture(1);perKg(x).dimShare='0.5';assert.equal(weight(x),'10');});
test('box and shipment rounding differ: 33 vs 31 kg',()=>{const x=fixture(1),q=perKg(x);q.boxes=[{count:3,units:1,cm:[1,1,1],kg:'10.2'}];q.roundStepKg='1';assert.equal(weight(x),'33');q.roundScope='shipment';assert.equal(weight(x),'31');});
test('shipment minimum weight raises 12 to 21 kg',()=>{const x=fixture(1),q=perKg(x);q.minimumWeightScope='shipment';q.minimumWeightKg='21';assert.equal(weight(x),'21');});
test('zero quote is allowed, blank quote is not',()=>{const x=fixture(1),q=perKg(x);q.pricePerKg='0';assert.ok(E.calculate(x).metrics);q.pricePerKg='';invalid(x);});
test('missing comparison channel does not invalidate current completed channel',()=>{const x=fixture();delete x.logistics.air;assert.ok(E.calculate(x).metrics);assert.equal(E.comparisons(x).ranking,null);});
test('refund rate 100 percent blocks indicator; near 100 percent remains computable',()=>{const x=fixture();x.scenario.returnRate='1';invalid(x);x.scenario.returnRate='0.999';assert.ok(E.calculate(x).metrics);});
test('unrecoverable withholding changes parallel balance only',()=>{const x=fixture();x.ruleSnapshot.rules.withholding.expression='2';x.ruleSnapshot.rules.withholding.recoverable=false;const r=E.calculate(x);assert.equal(r.metrics.grossProfit,'7.5');assert.equal(r.metrics.afterUnrecoverableWithholding,'5.5');});
test('shipping-based F surcharge enters return loss exactly once',()=>{const x=fixture();x.ruleSnapshot.rules.returnLoss.expression={op:'add',args:[{ref:'F'},'1.5']};x.extraFees=[{id:'peak-add',category:'F',unit:'shipped',uniqueCostKey:'peakDelivery',reason:'seasonal delivery surcharge',rule:{...E.clone(x.ruleSnapshot.rules.fulfillment),expression:'1'}}];const r=E.calculate(x);assert.equal(r.metrics.grossProfit,'6.25');assert.equal(r.totals.D,'3.25');});
test('logistics pickup cost cannot resolve to an unrelated import tax item',()=>{const x=fixture();x.logistics.express.inclusions.pickup='excluded';x.logistics.express.resolvedComponents.pickup='importTax';invalid(x);});
