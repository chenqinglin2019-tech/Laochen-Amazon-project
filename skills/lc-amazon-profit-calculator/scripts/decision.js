/* Presentation-only decision aids. Every candidate is recalculated by the shared engine. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory(require('./engine.js'));else root.ProfitDecision=factory(root.ProfitEngine);})(typeof globalThis!=='undefined'?globalThis:this,function(E){
  'use strict';
  function target(input){
    const value=input.reportPreferences?.targetMargin;
    if(value===undefined||value===null||value==='')return {status:'unset',value:null};
    try{const v=E.d(value);if(v.lt(0)||v.gte(1))throw Error();return {status:'set',value:v.toString()};}
    catch{return {status:'invalid',value:null,message:'目标毛利率需在 0% 至 100% 之间，不包含 100%。'};}
  }
  function adReference(input,targetMargin='0'){
    const current=E.calculate(input);
    if(!current.metrics)return {status:'unavailable',reason:'先补齐当前方案资料，再查看广告参考线。'};
    let goal;try{goal=E.d(targetMargin);if(goal.lt(0)||goal.gte(1))throw Error();}catch{return {status:'unavailable',reason:'请先填写有效的目标毛利率。'};}
    const evaluate=ratio=>{const x=E.clone(input);x.scenario.adRatio=ratio.toString();delete x.scenario.adInput;const r=E.calculate(x);if(!r.metrics)return null;return {result:r,residual:E.d(r.metrics.grossProfit).minus(E.d(r.metrics.revenue).times(goal))};};
    const zero=evaluate(E.d(0)),probe=evaluate(E.d('.01'));
    if(!zero||!probe)return {status:'unavailable',reason:'规则未覆盖广告调整范围；请补充规则后再试算。'};
    const tolerance=E.d('0.00000001'),slope=probe.residual.minus(zero.residual).div('.01');
    if(slope.gte(0))return {status:'unavailable',reason:'当前费用规则不适合计算单一广告参考线。'};
    if(zero.residual.lt(tolerance.neg()))return {status:'unreachable',reason:'即使广告占比降至 0%，当前售价与成本仍无法达到此毛利目标。',zeroMargin:zero.result.metrics.margin};
    const ratio=E.Decimal.max(0,zero.residual.div(slope.neg()));
    if(ratio.gt(100))return {status:'unavailable',reason:'广告参考值超出合理试算范围，请检查费用数据。'};
    // Refuse nonlinear, out-of-scope or discontinuous snapshots rather than extrapolating a formula.
    for(const x of [E.d(input.scenario.adRatio),ratio.div(2),ratio,ratio.plus('.00001')]){
      const check=evaluate(x);if(!check)return {status:'unavailable',reason:'规则未覆盖临界值附近，暂不能确定广告参考线。'};
      if(check.residual.minus(zero.residual.plus(slope.times(x))).abs().gt(tolerance))return {status:'unavailable',reason:'规则包含非线性收费条件，暂不提供单一广告参考线。'};
    }
    return {status:'available',ratio:ratio.toString(),headroom:ratio.minus(input.scenario.adRatio).toString(),targetMargin:goal.toString(),atReference:evaluate(ratio).result};
  }
  function sensitivityRows(input){
    const current=E.calculate(input);if(!current.metrics)return [];
    const specs=[['售价','product.price'],['采购','scenario.purchaseCny'],['广告占比','scenario.adRatio'],['退货率','scenario.returnRate']];
    const labels=['售价下调 10%','售价上调 10%','采购成本降低 10%','采购成本提高 10%','广告占比降低 5 个百分点','广告占比提高 5 个百分点','退货率降低 5 个百分点','退货率提高 5 个百分点'];
    return E.sensitivity(input).map((row,i)=>({...row,path:specs[Math.floor(i/2)][1],label:labels[i],delta:row.result.metrics?E.d(row.result.metrics.grossProfit).minus(current.metrics.grossProfit).toString():null}));
  }
  function auditPreferences(input){const t=target(input);if(t.status==='invalid')throw new Error(t.message);return t;}
  return {target,adReference,sensitivityRows,auditPreferences};
});
