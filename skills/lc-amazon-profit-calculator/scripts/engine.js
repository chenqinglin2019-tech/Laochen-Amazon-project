/* Shared deterministic engine: CommonJS and offline browser. No eval, network or storage. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('../vendor/decimal.js'));
  else root.ProfitEngine = factory(root.Decimal);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Decimal) {
  'use strict';
  const Dec = Decimal.clone({precision: 40, rounding: Decimal.ROUND_HALF_UP});
  const VERSION = '1.0';
  const SITES = {US:['amazon.com','USD'],JP:['amazon.co.jp','JPY'],UK:['amazon.co.uk','GBP'],DE:['amazon.de','EUR'],FR:['amazon.fr','EUR'],IT:['amazon.it','EUR'],ES:['amazon.es','EUR'],SA:['amazon.sa','SAR'],MX:['amazon.com.mx','MXN'],CA:['amazon.ca','CAD'],AU:['amazon.com.au','AUD']};
  const CHANNELS = {express:['快递','5000'],air:['普通空运','6000'],fastSea:['快船','6000'],slowSea:['慢船','6000']};
  const LABELS = {C:'采购与国内交货成本',H:'头程物流',M:'佣金与交易费用',F:'FBA 配送费用',S:'仓储费用',I:'入库服务费',A:'广告费用',D:'退货损失分摊',T:'其他不可抵扣目标国税费',O:'补充成本'};
  const REVIEW = ['mediaFee','individualPlan','peakDelivery','lowInventory','storageUtilization','agedInventory','inboundPlacement','inboundDefect','prepLabel','partneredCarrier','overseasAWD','digitalService','promotion','payoutFX','epr','serviceTax','importTax','withholding','returns'];
  const BOUNDARIES = ['pickup','clearance','duty','importTax','lastMile','overseasAWD','insurance'];
  class Issue extends Error {constructor(path,message,kind='missing'){super(message);this.path=path;this.kind=kind;}}
  function need(ok,path,message,kind){if(!ok) throw new Issue(path,message,kind);}
  function d(x,path='数值'){need((typeof x==='string'&&x.trim()!==''&&x.length<120)||typeof x==='number'||x instanceof Dec,path,'请补充有效数值（空白不等于零）');let n;try{n=new Dec(x);}catch{throw new Issue(path,'数值格式错误');}need(n.isFinite()&&n.abs().lt('1e30'),path,'数值必须有限且绝对值小于 10^30');return n;}
  function nonneg(x,p){const n=d(x,p);need(n.gte(0),p,'不允许负值');return n;}
  function positive(x,p){const n=d(x,p);need(n.gt(0),p,'必须大于零');return n;}
  function ratio(x,p,exclusive=false){const n=nonneg(x,p);need(exclusive?n.lt(1):n.lte(1),p,exclusive?'比例必须小于 100%':'比例不得超过 100%');return n;}
  function integer(x,p){const n=positive(x,p);need(n.isInteger(),p,'必须为正整数');return n;}
  function list(v,p){need(Array.isArray(v),p,'请明确提供列表，没有项目时提供空列表并记录确认');return v;}
  const sum = xs => xs.reduce((a,b)=>a.plus(b),new Dec(0));
  // Shared by legacy accounting and quick screening. Fees exclude refund principal.
  function allocateReturns(r,fees,u,invested){
    r=ratio(r,'退货率',true);u=ratio(u,'不可售比例');
    return r.isZero()?new Dec(0):r.times(nonneg(fees,'退货费用').plus(u.times(nonneg(invested,'已投入成本')))).div(new Dec(1).minus(r));
  }
  const clone = x => JSON.parse(JSON.stringify(x));
  function get(obj,path){need(typeof path==='string'&&!path.split('.').some(k=>['__proto__','prototype','constructor'].includes(k)),'字段','非法字段路径');return path.split('.').reduce((a,k)=>a&&Object.hasOwn(a,k)?a[k]:undefined,obj);}
  function date(x,p='日期'){need(typeof x==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x),p,'请提供 YYYY-MM-DD 日期');const t=Date.parse(x+'T00:00:00Z');need(Number.isFinite(t)&&new Date(t).toISOString().slice(0,10)===x,p,'无效日历日期');return t;}
  const iso=t=>new Date(t).toISOString().slice(0,10);
  function plusDays(x,n){return iso(date(x)+Number(nonneg(n,'停留天数'))*86400000);}
  function source(s,p){need(s&&['official','user','thirdParty','fixture'].includes(s.type)&&s.locator&&s.at,p,'缺少来源类型、定位或确认时间');need(typeof s.locator==='string'&&typeof s.at==='string',p,'来源格式错误');}
  function parseIdentity(text,site){
    let asin; let detected;
    if(/^[A-Z0-9]{10}$/i.test(text||'')){asin=text.toUpperCase();detected=site;}
    else {let u;try{u=new URL(text);}catch{throw new Issue('product.url','不能识别商品链接');}need(['https:','http:'].includes(u.protocol),'product.url','链接必须是 HTTP(S)');detected=Object.keys(SITES).find(k=>u.hostname===SITES[k][0]||u.hostname==='www.'+SITES[k][0]);asin=(u.pathname.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})(?:\/|$)/i)||[])[1]?.toUpperCase();}
    need(SITES[detected],'product.site','请明确提供受支持站点，不默认美国站');need(asin,'product.asin','请提供明确的子 ASIN');need(!site||site===detected,'product.site','站点与链接冲突');return {site:detected,asin,currency:SITES[detected][1]};
  }
  function matches(c,ctx){
    need(c&&typeof c==='object','规则条件','条件必须为数据对象');
    return Object.entries(c).every(([key,v])=>{const x=get(ctx,key);if(v&&typeof v==='object'&&!Array.isArray(v))return Object.entries(v).every(([op,b])=>{if(op==='in')return list(b,key).includes(x);const a=d(x,key),n=d(b,key);switch(op){case 'lt':return a.lt(n);case 'lte':return a.lte(n);case 'gt':return a.gt(n);case 'gte':return a.gte(n);case 'eq':return a.eq(n);default:throw new Issue(key,'未知条件操作符 '+op);}});return String(x)===String(v);});
  }
  function expr(e,ctx,depth=0){
    need(depth<40,'公式','公式嵌套过深');
    if(typeof e==='string'||typeof e==='number'||e instanceof Dec)return d(e,'公式数值');
    need(e&&typeof e==='object'&&!Array.isArray(e),'公式','缺少可计算公式');
    if(e.ref!==undefined)return d(get(ctx,e.ref),e.ref);
    if(e.op==='select'){const rows=list(e.rows,'公式分档').filter(r=>matches(r.when,ctx));need(rows.length===1,'公式分档',rows.length?'多个费率档位冲突':'规则快照未覆盖此条件','rules');return expr(rows[0].value,ctx,depth+1);}
    if(e.op==='tier'){
      const x=nonneg(expr(e.base,ctx,depth+1),'计费基数');let last=new Dec(0),out=new Dec(0),covered=false;
      need(['whole','progressive'].includes(e.mode),'分段','请明确整段或累计分段');
      for(const b of list(e.bands,'分段')){const upper=b.upTo===null?null:positive(b.upTo,'区间上限');need(!upper||upper.gt(last),'分段','分段上限必须递增');const rate=nonneg(b.rate,'费率');if(e.mode==='whole'&&(upper===null||x.lte(upper))){out=x.times(rate);covered=true;break;}if(e.mode==='progressive'){out=out.plus(Dec.max(0,(upper?Dec.min(x,upper):x).minus(last)).times(rate));if(upper===null||x.lte(upper)){covered=true;break;}}if(upper)last=upper;}
      need(covered,'分段','费表未覆盖计费基数','rules');return out;
    }
    const a=list(e.args,'公式参数').map(x=>expr(x,ctx,depth+1));
    switch(e.op){case 'add':return sum(a);case 'mul':return a.reduce((x,y)=>x.times(y),new Dec(1));case 'sub':need(a.length===2,'公式','sub 需要两个参数');return a[0].minus(a[1]);case 'div':need(a.length===2&&!a[1].isZero(),'公式','除数必须非零');return a[0].div(a[1]);case 'min':need(a.length>0,'公式','缺少参数');return Dec.min(...a);case 'max':need(a.length>0,'公式','缺少参数');return Dec.max(...a);case 'ceilStep':need(a.length===2&&a[1].gt(0),'公式','进位步长必须为正');return a[0].div(a[1]).ceil().times(a[1]);case 'round':need(a.length===1&&Number.isInteger(e.places)&&e.places>=0&&e.places<=12&&Number.isInteger(e.mode)&&e.mode>=0&&e.mode<=8,'舍入','需明确位数及 Decimal 舍入模式');return a[0].toDecimalPlaces(e.places,e.mode);default:throw new Issue('公式','不支持的公式操作 '+e.op);}
  }
  function scopeCheck(r,ctx,p,at){
    source(r.source,p+'.source');need(r.site===ctx.product.site,p,'规则站点不匹配','rules');
    date(r.validFrom,p+'.validFrom');date(r.validTo,p+'.validTo');
    if(at<r.validFrom||at>r.validTo){need(r.acceptedExtension&&r.acceptedExtension.confirmedAt&&at>=r.acceptedExtension.from&&at<=r.acceptedExtension.to,p,'日期不在规则快照范围内','rules');ctx.conditions.push(p+'：用户确认沿用范围外规则');}
    need(r.scope&&typeof r.scope==='object',p+'.scope','请记录规则适用资格与输入范围');
    need(matches(r.scope,ctx),p,'输入已超出快照适用范围；请回到 Skill 更新规则','rules');
    if(r.source.type==='user'&&(!r.dynamic||typeof r.expression!=='object')){
      const binds=r.bindings;need(binds&&Object.keys(binds).length,p+'.bindings','人工固定费用必须绑定当前输入条件');
      for(const key of ['product.site','product.asin','product.price','product.packaging','product.goodsType','product.feeCategory','sellerProfile','shipDate','entryDate','exitDate','scenario.purchaseCny','scenario.returnRate','scenario.ageDays'])need(Object.hasOwn(binds,key),p+'.bindings','人工金额缺少条件绑定：'+key);
      if(ctx.scenario.unsellableRatio!==undefined)need(Object.hasOwn(binds,'scenario.unsellableRatio'),p+'.bindings','人工金额缺少不可再售比例绑定');
      if(ctx.scenario.monthlyShipments!==undefined)need(Object.hasOwn(binds,'scenario.monthlyShipments'),p+'.bindings','人工金额缺少月发货量绑定');
      for(const [k,v] of Object.entries(binds))need(JSON.stringify(get(ctx,k))===JSON.stringify(v),p,'人工金额适用条件已改变：'+k,'rules');
    }
  }
  function rawRule(r,ctx,p,at){
    need(r&&typeof r==='object',p,'请补充费用规则或明确不适用');
    need(['active','notApplicable','excluded'].includes(r.status),p,'费用尚未确认');scopeCheck(r,ctx,p,at);
    if(r.status!=='active'){need(r.reason,p,'不适用或排除必须有理由');if(r.status==='excluded'){need(r.confirmedAt,p,'排除需要用户确认记录');ctx.conditions.push(p+'：排除 '+r.reason);}return new Dec(0);}
    return nonneg(expr(r.expression,ctx),p);
  }
  function convert(n,currency,ctx){const rate=ctx.ruleSnapshot.fx.cnhPerCurrency[currency];return n.times(positive(rate,'汇率 '+currency)).div(positive(ctx.ruleSnapshot.fx.cnhPerCurrency[ctx.product.currency],'站点汇率'));}
  function taxSplit(amount,tax,ctx,p){
    need(tax&&['none','included','excluded'].includes(tax.mode),p,'请明确费用是否含服务税');
    if(tax.mode==='none')return {net:amount,cost:new Dec(0),recoverable:new Dec(0)};
    const rate=nonneg(tax.rate,p+'.rate');need(typeof tax.recoverable==='boolean',p,'请确认服务税是否可抵扣');
    need(!(tax.recoverable&&ctx.sellerProfile.taxMethod==='simplified'),p,'简易计税不得重复享受进项抵扣');
    const net=tax.mode==='included'?amount.div(rate.plus(1)):amount,t=net.times(rate);
    return {net,cost:tax.recoverable?new Dec(0):t,recoverable:tax.recoverable?t:new Dec(0)};
  }
  function fee(r,ctx,p,at){const n=rawRule(r,ctx,p,at);if(r.status!=='active')return {net:n,cost:n,recoverable:n};need(r.currency,p+'.currency','缺少费用币种');const split=taxSplit(convert(n,r.currency,ctx),r.tax,ctx,p+'.tax');return split;}
  function logistics(q,ctx){
    const p='logistics.'+q.type;need(q.status==='active',p,'请补充报价或明确排除渠道');source(q.source,p+'.source');
    need(q.destination===ctx.product.site,p,'报价目的国不匹配');
    if(q.goodsType!==ctx.product.goodsType){need(q.acceptedGoodsMismatch?.confirmedAt,p,'报价货物属性不匹配');ctx.conditions.push(p+'：确认替代货物属性报价');}
    need(q.validFrom,p,'缺少报价起始日');date(q.validFrom);if(q.validTo===null){need(q.validityConfirmedAt,p,'报价有效期未注明，请确认本次仍有效');}else{date(q.validTo,p);if(ctx.shipDate<q.validFrom||ctx.shipDate>q.validTo){need(q.acceptedExpired?.confirmedAt,p,'报价已过期或尚未生效');ctx.conditions.push(p+'：确认沿用过期报价');}}
    need(q.inclusions&&BOUNDARIES.every(k=>['included','excluded','passThrough'].includes(q.inclusions[k])),p+'.inclusions','请逐项确认提货、清关、关税、进口税、派送、中转、保险包含范围');
    for(const k of BOUNDARIES)if(q.inclusions[k]!=='included')need(q.resolvedComponents?.[k],p+'.'+k,'未包含或实报实销的项目必须关联费用条目或明确不适用');
    let total,units,trace={};
    if(q.mode==='manual'){
      need(q.manualRule?.status==='active',p+'.manualRule','头程人工金额必须有效；明确为零时仍应填写有效的零金额');
      need(q.manualRule.currency===q.currency,p+'.manualRule','人工头程金额币种与报价币种冲突');
      scopeCheck(q.manualRule,ctx,p+'.manualRule',ctx.shipDate);total=rawRule(q.manualRule,ctx,p+'.manualRule',ctx.shipDate);units=new Dec(1);trace={method:'人工单销售单位金额',expression:q.manualRule.expression};
    }else{
      need(q.mode==='perKg',p,'复杂报价请提供确认的单件费用与适用条件');
      const boxes=list(q.boxes,p+'.boxes');need(boxes.length>0,p+'.boxes','请补充外箱资料');
      if(q.packageEstimate){need(q.packageEstimate.confirmedAt,p,'单件包装估算需明确确认');ctx.conditions.push(p+'：以单件包装估算，未计外箱和空隙');}
      const divisor=positive(q.divisor??CHANNELS[q.type][1],p+'.divisor');
      const rows=boxes.map((b,i)=>{const count=integer(b.count,p+'.箱数'),unit=integer(b.units,p+'.装箱数');const dims=list(b.cm,p+'.外箱尺寸');need(dims.length===3,p,'外箱需要三个尺寸');return {count,units:unit,actual:positive(b.kg,p+'.毛重'),vol:dims.reduce((n,x)=>n.times(positive(x,p+'.尺寸')),new Dec(1)).div(divisor)};});
      units=sum(rows.map(b=>b.units.times(b.count)));const boxCount=sum(rows.map(b=>b.count));
      need(['box','shipment'].includes(q.compareScope)&&['box','shipment'].includes(q.roundScope),p,'请明确比较和进位作用范围');
      need(!(q.compareScope==='shipment'&&q.roundScope==='box'),p,'整票比较后逐箱进位需提供货代的分配规则，改用人工金额');
      const share=ratio(q.dimShare,p+'.分泡客户承担比例');const base=(a,v)=>a.plus(Dec.max(0,v.minus(a)).times(share));
      const step=nonneg(q.roundStepKg,p+'.进位步长');const rounded=x=>step.isZero()?x:x.div(step).ceil().times(step);
      const minW=nonneg(q.minimumWeightKg,p+'.最低计费重');need(['box','shipment'].includes(q.minimumWeightScope),p,'请明确最低计费重作用范围');
      need(!(q.roundScope==='shipment'&&q.minimumWeightScope==='box'&&minW.gt(0)),p,'整票进位且逐箱最低重需明确分配规则，改用人工金额');
      let weight;
      if(q.compareScope==='shipment')weight=base(sum(rows.map(b=>b.actual.times(b.count))),sum(rows.map(b=>b.vol.times(b.count))));
      else weight=sum(rows.map(b=>{let w=base(b.actual,b.vol);if(q.roundScope==='box')w=rounded(w);if(q.minimumWeightScope==='box')w=Dec.max(w,minW);return w.times(b.count);}));
      if(q.roundScope==='shipment')weight=rounded(weight);if(q.minimumWeightScope==='shipment')weight=Dec.max(weight,minW);
      const unitPrice=nonneg(q.pricePerKg,p+'.每公斤单价'),minimum=nonneg(q.minimumCharge,p+'.最低收费');need(['box','shipment'].includes(q.minimumChargeScope),p,'请明确最低收费作用范围');
      let freight=weight.times(unitPrice);
      if(q.minimumChargeScope==='shipment')freight=Dec.max(freight,minimum);
      else if(minimum.gt(0)){
        need(q.compareScope==='box'&&q.roundScope==='box'&&(q.minimumWeightScope==='box'||minW.isZero()),p,'逐箱最低金额与整票重量组合需提供可复算分配规则，改用人工单件金额');
        freight=sum(rows.map(b=>Dec.max(Dec.max(rounded(base(b.actual,b.vol)),q.minimumWeightScope==='box'?minW:0).times(unitPrice),minimum).times(b.count)));
      }
      const surchargeCtx={...ctx,freight,weight,boxCount,units};const extras=list(q.surcharges,p+'.附加费');const ids=new Set();const surcharge=sum(extras.map(x=>{need(x.id&&!ids.has(x.id),p,'附加费 ID 重复或缺失');ids.add(x.id);return nonneg(expr(x.expression,surchargeCtx),p+'.附加费 '+x.id);}));
      total=freight.plus(surcharge);trace={divisor:divisor.toString(),boxes:rows.map(b=>Object.fromEntries(Object.entries(b).map(([k,v])=>[k,v.toString()]))),weight:weight.toString(),freight:freight.toString(),surcharge:surcharge.toString(),total:total.toString(),units:units.toString()};
    }
    const gross=convert(total.div(units),q.currency,ctx);const split=taxSplit(gross,q.tax,ctx,p+'.tax');
    const recovery=nonneg(q.includedImportTaxRecovery,p+'.已含进口税抵扣');
    if(recovery.gt(0)){need(q.inclusions.importTax==='included'&&q.importRecoveryEvidence?.ownImporter&&q.importRecoveryEvidence?.voucher&&ctx.sellerProfile.taxMethod!=='simplified',p,'报价已含进口税的抵扣须有自身进口主体、凭证及适用计税方式');need(recovery.lte(split.net),p,'抵扣额超过头程净额');split.net=split.net.minus(recovery);split.recoverable=split.recoverable.plus(recovery);}
    return {...split,trace};
  }
  function storage(r,ctx){
    if(r?.mode!=='monthly')return {...fee(r,ctx,'rules.storage',ctx.entryDate),segments:[]};
    let t=date(ctx.entryDate),end=date(ctx.exitDate),net=new Dec(0),cost=new Dec(0),recoverable=new Dec(0);const segments=[];const tariffKeys=new Set();
    while(t<end){const current=iso(t);const dt=new Date(t);const days=new Date(Date.UTC(dt.getUTCFullYear(),dt.getUTCMonth()+1,0)).getUTCDate();const rules=list(r.periods,'rules.storage.periods').filter(x=>current>=x.validFrom&&current<=x.validTo);need(rules.length===1,'rules.storage','仓储费表日期缺失或重叠','rules');const rr=rules[0];const stop=Math.min(end,Date.UTC(dt.getUTCFullYear(),dt.getUTCMonth()+1,1),date(rr.validTo)+86400000);const n=(stop-t)/86400000;const amount=fee(rr,ctx,'rules.storage',current);const unit=positive(rr.volumeCm3PerUnit,'仓储体积单位');const factor=ctx.volumeCm3.div(unit).times(n).div(days);net=net.plus(amount.net.times(factor));cost=cost.plus(amount.cost.times(factor));recoverable=recoverable.plus(amount.recoverable.times(factor));segments.push({from:current,to:iso(stop),days:n,monthDays:days,net:amount.net.times(factor).toString(),source:rr.source});t=stop;}
    for(const s of segments){const rr=r.periods.find(x=>s.from>=x.validFrom&&s.from<=x.validTo);tariffKeys.add(JSON.stringify([rr.expression,rr.currency,rr.tax,rr.volumeCm3PerUnit]));}
    if(tariffKeys.size>1)need(ctx.scenario.dateBoundaryConfirmedAt,'scenario.entryDate','库存区间跨费率边界，请确认入仓日期');
    return {net,cost,recoverable,segments};
  }
  function validateBase(input){
    const errors=[];const check=f=>{try{f();}catch(e){errors.push({path:e.path||'input',message:e.message,kind:e.kind||'missing'});}};
    check(()=>need(input?.schemaVersion===VERSION,'schemaVersion','不支持的格式版本，请保留原文件并迁移'));
    if(!input||typeof input!=='object')return errors;
    if(!input.fixture)check(()=>{const walk=(v,p)=>{if(!v||typeof v!=='object')return;need(v.type!=='fixture',p,'人工验收来源不可用于真实商品测算');for(const [k,x]of Object.entries(v))walk(x,p+'.'+k);};walk(input,'input');});
    const p=input.product||{},s=input.scenario||{},rs=input.ruleSnapshot||{};
    check(()=>need(SITES[p.site]&&SITES[p.site][1]===p.currency,'product.site','站点或币种不匹配'));
    check(()=>need(/^[A-Z0-9]{10}$/.test(p.asin||'')&&p.childConfirmed===true,'product.asin','请确认具体子 ASIN'));
    check(()=>need(p.title&&p.goodsType&&p.feeCategory,'product','请补充标题、货物属性和收费类别'));
    check(()=>integer(p.unitsPerSale,'product.unitsPerSale'));check(()=>positive(p.price,'product.price'));
    check(()=>{need(p.packaging?.cm?.length===3,'product.packaging.cm','请提供销售包装长宽高 cm');p.packaging.cm.forEach(x=>positive(x,'包装尺寸'));positive(p.packaging.kg,'包装毛重 kg');});
    check(()=>nonneg(s.purchaseCny,'scenario.purchaseCny'));check(()=>nonneg(s.adRatio,'scenario.adRatio'));check(()=>ratio(s.returnRate,'scenario.returnRate',true));
    check(()=>{if(d(s.returnRate).gt(0))ratio(s.unsellableRatio,'scenario.unsellableRatio');});
    check(()=>{const n=nonneg(s.ageDays,'scenario.ageDays');need(n.isInteger(),'scenario.ageDays','库龄按整天输入');});
    ['calculationDate','shipDate','entryDate'].forEach(k=>check(()=>date(s[k],'scenario.'+k)));if(s.exitDate)check(()=>date(s.exitDate,'scenario.exitDate'));
    check(()=>need(CHANNELS[s.channel],'scenario.channel','请选择当前物流渠道'));
    check(()=>{need(input.sellerProfile?.localFba===true,'sellerProfile','仅支持站点当地 FBA');need(['general','simplified','confirmedActual'].includes(input.sellerProfile.taxMethod),'sellerProfile.taxMethod','请确认计税方式');need(['professional','individual'].includes(input.sellerProfile.salesPlan),'sellerProfile.salesPlan','请明确销售计划');});
    check(()=>{need(rs.fx?.kind==='CNH','ruleSnapshot.fx','请提供离岸人民币汇率快照，不能以 CNY 冒充 CNH');source(rs.fx.source,'汇率来源');positive(rs.fx.cnhPerCurrency?.[p.currency],'汇率');need(d(rs.fx.cnhPerCurrency?.CNY).eq(1),'汇率','采购人民币成本基数必须为 1');});
    for(const key of ['product','price','packaging','purchase','advertising','returns','inventory','taxProfile','costBoundary'])check(()=>{const v=input.provenance?.[key];source(v,'provenance.'+key);need(!['missing','conflict','expired'].includes(v.status),'provenance.'+key,'该字段来源缺失、冲突或过期，请先核对');if(v.status==='acceptedEstimate')need(v.confirmedAt,'provenance.'+key,'替代参数尚未确认');});
    for(const key of REVIEW)check(()=>{const r=input.feeReview?.[key];need(r&&['included','notApplicable','excluded'].includes(r.status)&&r.reason&&r.confirmedAt,'feeReview.'+key,'请核对 '+key+'：费用、确认不适用或明确排除');if(r.status==='included')need(r.itemId,'feeReview.'+key,'适用费用须关联条目');});
    check(()=>list(input.assumptions,'assumptions').forEach(a=>need(a.text&&a.confirmedAt,'assumptions','估算假设须明确确认')));
    check(()=>list(input.extraFees,'extraFees'));check(()=>list(input.history,'history'));
    if(input.editableParameters!==undefined)check(()=>list(input.editableParameters,'editableParameters').forEach(x=>need(x&&typeof x.path==='string'&&typeof x.label==='string'&&(!x.type||['number','percent'].includes(x.type)),'editableParameters','可编辑参数结构错误')));
    if(input.savedScenarios!==undefined)check(()=>list(input.savedScenarios,'savedScenarios'));
    if(s.adInput)check(()=>need(s.adInput.confirmedAt&&s.adInput.normalizedRatio===s.adRatio,'scenario.adInput','原始广告口径需先确认并固化换算结果；编辑广告占比后须同步记录新口径'));
    return errors;
  }
  function calculate(input,channel){
    const errors=validateBase(input);if(errors.length)return {status:'待补信息',missingItems:errors,metrics:null};
    try{
      const ctx=clone(input);ctx.conditions=ctx.assumptions.map(a=>a.text);for(const [k,v]of Object.entries(ctx.provenance))if(v.status==='acceptedEstimate')ctx.conditions.push(k+'：用户确认替代参数');ctx.scenario.channel=channel||ctx.scenario.channel;
      const q=ctx.logistics?.[ctx.scenario.channel];need(q,'logistics.'+ctx.scenario.channel,'缺少渠道报价');q.type=ctx.scenario.channel;
      ctx.shipDate=ctx.scenario.shipDate;ctx.entryDate=q.transitDays!==undefined?plusDays(ctx.shipDate,integerOrZero(q.transitDays,'运输天数')):ctx.scenario.entryDate;
      ctx.exitDate=q.exitDate||ctx.scenario.exitDate||plusDays(ctx.entryDate,ctx.scenario.ageDays);need(date(ctx.exitDate)>=date(ctx.entryDate),'scenario.exitDate','出库日期不得早于入仓日期');
      ctx.ageDays=new Dec((date(ctx.exitDate)-date(ctx.entryDate))/86400000);ctx.price=d(ctx.product.price);ctx.r=d(ctx.scenario.returnRate);ctx.u=ctx.r.isZero()?new Dec(0):d(ctx.scenario.unsellableRatio);ctx.keep=new Dec(1).minus(ctx.r);
      const dims=ctx.product.packaging.cm.map(dv=>d(dv)).sort((a,b)=>b.comparedTo(a));ctx.longCm=dims[0];ctx.midCm=dims[1];ctx.shortCm=dims[2];ctx.volumeCm3=dims.reduce((a,b)=>a.times(b),new Dec(1));ctx.weightKg=d(ctx.product.packaging.kg);
      const rules={...ctx.ruleSnapshot.rules,...q.ruleOverrides};ctx.rules=rules;
      const salesTax=convert(rawRule(rules.salesTax,ctx,'rules.salesTax',ctx.exitDate),rules.salesTax.currency,ctx);need(rules.salesTax.status!=='excluded','rules.salesTax','核心销售税不能排除');ctx.R=ctx.price.minus(salesTax);need(ctx.R.gt(0),'净收入','扣税后的净收入必须大于零');
      ctx.C=convert(d(ctx.scenario.purchaseCny),'CNY',ctx);const h=logistics(q,ctx);ctx.H=h.net;
      const items=[{id:'C',category:'C',amount:ctx.C.toString(),formula:'人民币采购成本 ÷ 每单位站点货币对应 CNH',source:ctx.provenance.purchase},{id:'H',category:'H',amount:ctx.H.toString(),formula:'整箱或整票费用 ÷ 销售单位数 × 汇率，拆税后计入',source:q.source,detail:h.trace}];
      const totals=Object.fromEntries(Object.keys(LABELS).map(k=>[k,new Dec(0)]));totals.C=ctx.C;totals.H=ctx.H;totals.T=h.cost;let recoverable=h.recoverable;let inboundTax=new Dec(0),returnExtra=new Dec(0),extraInvested=new Dec(0);
      const ids=new Set(['C','H']);
      function record(id,category,res,rule,formula){need(!ids.has(id),'fees','同一费用 ID 重复：'+id);ids.add(id);totals[category]=totals[category].plus(res.net);totals.T=totals.T.plus(res.cost);recoverable=recoverable.plus(res.recoverable);items.push({id,category,amount:res.net.toString(),serviceTax:res.cost.toString(),recoverableTax:res.recoverable.toString(),formula,source:rule?.source,expression:rule?.expression,status:rule?.status,detail:res.segments});}
      for(const [k,c] of [['commission','M'],['fulfillment','F'],['inbound','I'],['importTax','T'],['otherTax','T']]){const at=k==='inbound'||k==='importTax'?ctx.entryDate:ctx.exitDate;const res=fee(rules[k],ctx,'rules.'+k,at);record(k,c,res,rules[k],'按快照公式与适用条件计算');ctx[c]=totals[c];if(k==='importTax')inboundTax=res.net.plus(res.cost);}
      if(rules.importTax.status==='active'&&d(expr(rules.importTax.expression,ctx)).gt(0))need(Array.isArray(rules.importTax.covers)&&rules.importTax.covers.length>0&&rules.importTax.covers.every(x=>['duty','importTax','customsLevy'].includes(x)),'rules.importTax.covers','正额进口税必须明确税种覆盖范围');
      if(q.inclusions.duty==='included'||q.inclusions.importTax==='included'){
        const covered=list(rules.importTax.covers,'rules.importTax.covers');for(const x of covered)need(q.inclusions[x]!=='included'||rules.importTax.status!=='active'||d(expr(rules.importTax.expression,ctx)).isZero(),'rules.importTax','物流已含进口税费，不得重复计入 '+x);
      }
      const st=storage(rules.storage,ctx);record('storage','S',st,rules.storage,'体积 × 月费率 × 当月占用天数 / 当月天数');ctx.S=totals.S;
      ctx.A=ctx.R.times(d(ctx.scenario.adRatio));const ad=taxSplit(ctx.A,ctx.scenario.adTax,ctx,'scenario.adTax');ctx.A=ad.net;record('advertising','A',ad,null,'净收入 × 已确认广告占比（费用含税时拆分）');
      for(const e of ctx.extraFees){
        need(e.id&&Object.keys(LABELS).includes(e.category)&&!['A','C','D'].includes(e.category),'extraFees','补充费用需唯一 ID 和正确归属');
        need(e.reason&&e.uniqueCostKey,'extraFees.'+e.id,'补充费用需用途与唯一支出标识');
        need(!['C','H','M','F','S','I','A','D','T','O','commission','fulfillment','storage','inbound','importTax','otherTax','returnLoss','withholding','advertising'].includes(e.uniqueCostKey),'extraFees.'+e.id,'补充费用与内置费用重叠；替代请修改原规则，追加须使用独立支出标识');
        need(!ctx.extraFees.some(o=>o!==e&&o.uniqueCostKey===e.uniqueCostKey),'extraFees','重复支出 '+e.uniqueCostKey);
        need(!['refundPrincipal','discountInPrice','advertisingIncluded','salesTax'].includes(e.uniqueCostKey),'extraFees','本金、已扣优惠、已含广告或销售税不能重复扣减');
        const res=fee(e.rule,ctx,'extraFees.'+e.id,e.dateBasis==='entry'?ctx.entryDate:e.dateBasis==='ship'?ctx.shipDate:ctx.exitDate);let factor=new Dec(1);
        if(e.unit==='shipment')factor=new Dec(1).div(integer(e.unitsPerShipment,'每票销售单位数'));else if(e.unit==='month')factor=new Dec(1).div(positive(ctx.scenario.monthlyShipments,'预计月发货量').times(ctx.keep));else if(e.unit==='oneTime')factor=new Dec(1).div(positive(e.allocationUnits,'分摊留存销量'));else need(['retained','shipped','inbound','ratio'].includes(e.unit),'extraFees.'+e.id,'计费单位无效');
        const normalized={net:res.net.times(factor),cost:res.cost.times(factor),recoverable:res.recoverable.times(factor)};
        if(e.unit==='shipped'){returnExtra=returnExtra.plus(normalized.net).plus(normalized.cost);recoverable=recoverable.plus(normalized.recoverable.times(ctx.r).div(ctx.keep));}
        if(e.unit==='inbound'||e.unit==='shipment')extraInvested=extraInvested.plus(normalized.net).plus(normalized.cost);
        record(e.id,e.category,normalized,e.rule,e.unit+'：金额 × 分摊系数 '+factor.toString());
      }
      for(const [k,v] of Object.entries(ctx.feeReview)){if(v.status==='included')need(ids.has(v.itemId)||['returnLoss','withholding'].includes(v.itemId),'feeReview.'+k,'费用审核关联条目不存在：'+v.itemId);if(v.status==='excluded')ctx.conditions.push(k+'：排除 '+v.reason);}
      for(const k of BOUNDARIES)if(q.inclusions[k]!=='included'){const id=q.resolvedComponents[k];need(ids.has(id),'logistics.'+q.type+'.'+k,'物流边界关联费用不存在：'+id);const item=items.find(x=>x.id===id);need(item?.category===(['duty','importTax'].includes(k)?'T':'H'),'logistics.'+q.type+'.'+k,'物流边界关联费用归属错误：'+k);if(['duty','importTax'].includes(k)&&rules.importTax.status==='active')need(rules.importTax.covers?.includes(k),'rules.importTax.covers','进口税费未覆盖所需税种：'+k);}
      ctx.invested=ctx.C.plus(ctx.H).plus(ctx.I).plus(ctx.S).plus(inboundTax).plus(extraInvested);
      // Inbound service taxes already paid and not recoverable are part of lost investment.
      ctx.invested=ctx.invested.plus(h.cost).plus(st.cost).plus(items.find(x=>x.id==='inbound')?.serviceTax||0);
      ctx.returnExtra=returnExtra;
      let L=new Dec(0),returnRecoverable=new Dec(0);
      if(ctx.r.gt(0)){const lr=fee(rules.returnLoss,ctx,'rules.returnLoss',ctx.exitDate);L=lr.net.plus(lr.cost).plus(returnExtra).plus(ctx.u.times(ctx.invested));returnRecoverable=lr.recoverable.times(ctx.r).div(ctx.keep);}
      totals.D=allocateReturns(ctx.r,L,0,0);items.push({id:'returnLoss',category:'D',amount:totals.D.toString(),formula:'r × (退货订单净费用 + 发货类补充费用 + u × 已投入成本) / (1-r)',detail:{L:L.toString(),invested:ctx.invested.toString(),returnExtra:returnExtra.toString(),u:ctx.u.toString()},source:rules.returnLoss?.source});
      // Return rule must contain u × disposal where applicable; excludes invested costs and principal.
      ctx.G=ctx.R.minus(sum(Object.values(totals)));const w=fee(rules.withholding,ctx,'rules.withholding',ctx.exitDate);need(w.cost.isZero(),'rules.withholding','所得税预扣不应作为服务税');need(typeof rules.withholding.recoverable==='boolean','rules.withholding','请确认预扣能否回收');
      const withholding=w.net,unrecoverable=rules.withholding.recoverable?new Dec(0):withholding;
      const precision=ctx.product.currency==='JPY'?0:2;const E=d(ctx.ruleSnapshot.fx.cnhPerCurrency[ctx.product.currency]);
      return {schemaVersion:VERSION,status:ctx.conditions.length?'条件估算':'可计算',missingItems:[],metrics:{revenue:ctx.R.toString(),grossProfit:ctx.G.toString(),margin:ctx.G.div(ctx.R).toString(),cnyEquivalent:ctx.G.times(E).toString(),afterUnrecoverableWithholding:ctx.G.minus(unrecoverable).toString(),withholding:withholding.toString(),recoverableTax:recoverable.plus(returnRecoverable).toString(),salesTax:salesTax.toString(),currency:ctx.product.currency,displayPrecision:precision},totals:Object.fromEntries(Object.entries(totals).map(([k,v])=>[k,v.toString()])),feeItems:items,assumptions:[...new Set(ctx.conditions)],dates:{ship:ctx.shipDate,entry:ctx.entryDate,exit:ctx.exitDate,ageDays:ctx.ageDays.toString()},sources:ctx.provenance,channel:ctx.scenario.channel};
    }catch(e){return {schemaVersion:VERSION,status:e.kind==='rules'?'需要更新规则':'待补信息',metrics:null,missingItems:[{path:e.path||'input',message:e.message,kind:e.kind||'missing'}]};}
  }
  function integerOrZero(x,p){const n=nonneg(x,p);need(n.isInteger(),p,'必须为非负整数');return n;}
  function normalizeAdvertising(input){const R=positive(input.netRevenue,'净收入'),r=ratio(input.returnRate,'退货率',true),keep=new Dec(1).minus(r);let A;
    if(input.kind==='budget')A=nonneg(input.budget,'预算').div(positive(input.retainedUnits,'同期留存销量'));
    else {let rate=nonneg(input.ratio,'原始广告比例');if(input.kind==='acos')rate=rate.times(ratio(input.adSalesShare,'同口径广告销售占比'));else need(input.kind==='ratio','广告口径','未知输入类型');need(typeof input.taxIncludedDenominator==='boolean'&&typeof input.refundsDeducted==='boolean','广告口径','请确认分母税价与退款口径');A=rate.times(input.taxIncludedDenominator?positive(input.price,'成交价'):R).div(input.refundsDeducted?1:keep);}
    return {adPerRetained:A.toString(),normalizedRatio:A.div(R).toString()};
  }
  function comparisons(input){const results={};let complete=true;for(const [k,v] of Object.entries(CHANNELS)){const q=input.logistics?.[k];if(q?.status==='excluded'&&q.confirmedAt&&q.reason){results[k]={status:'不参与',reason:q.reason};continue;}results[k]=calculate(input,k);if(!results[k].metrics)complete=false;}const rank=complete?Object.entries(results).filter(([,r])=>r.metrics).sort((a,b)=>d(b[1].metrics.grossProfit).comparedTo(a[1].metrics.grossProfit)).map(([k])=>k):null;return {status:complete?'可比较':'待补信息',results,ranking:rank};}
  function sensitivity(input){const base=calculate(input);if(!base.metrics)return [];const fields=[['售价','product.price','mul','0.9','1.1'],['采购','scenario.purchaseCny','mul','0.9','1.1'],['广告占比','scenario.adRatio','add','-0.05','0.05'],['退货率','scenario.returnRate','add','-0.05','0.05']];const out=[];for(const [name,path,op,...changes]of fields)for(const change of changes){const x=clone(input),parts=path.split('.'),v=d(get(x,path));x[parts[0]][parts[1]]=v[op==='mul'?'times':'plus'](change).toString();if(path==='scenario.adRatio')delete x.scenario.adInput;const row={name:name+' '+(op==='mul'?(d(change).minus(1).times(100).toString()+'%'):(d(change).times(100).toString()+' 个百分点')),value:get(x,path),result:calculate(x)};if(path==='scenario.returnRate'){const alternate=clone(x);if(d(x.scenario.returnRate).lt(1)&&d(x.scenario.returnRate).gte(0)){alternate.scenario.adRatio=d(input.scenario.adRatio).times(new Dec(1).minus(input.scenario.returnRate)).div(new Dec(1).minus(x.scenario.returnRate)).toString();delete alternate.scenario.adInput;row.fixedAdPerShipped=calculate(alternate);}}out.push(row);}return out;}
  function auditImport(value){need(value&&value.schemaVersion===VERSION,'schemaVersion','不支持此导入版本');const errors=validateBase(value);need(!errors.length,'导入',errors.map(x=>x.path+'：'+x.message).join('\n'));const current=calculate(value);need(current.metrics,'导入',current.missingItems.map(x=>x.path+'：'+x.message).join('\n'));return clone(value);}
  return {VERSION,SITES,CHANNELS,LABELS,REVIEW,BOUNDARIES,Decimal:Dec,d,date,expr,parseIdentity,normalizeAdvertising,validateBase,calculate,comparisons,sensitivity,auditImport,logistics,taxSplit,clone,allocateReturns};
});
