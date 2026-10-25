/* Offline screening: shared Decimal/rule interpreter/return allocation from engine.js. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./engine.js'));
  else root.QuickProfit=factory(root.ProfitEngine);
})(typeof globalThis!=='undefined'?globalThis:this,function(E){
  'use strict';
  const VERSION='2.0', D=E.Decimal;
  const DEFAULTS={adRatio:'0.10',unsellableRatio:'0.20',ageDays:'90'};
  const EXCLUDED=['广告及平台服务税的单独核算','外箱、装箱空隙和重量余量','入库配置及计划外服务','低库存、仓储利用率和超龄附加费','弃置及移除费','旺季配送附加费','提现、汇兑价差、企业所得税及其他账户费用'];
  const CHANNELS={...E.CHANNELS,sea:['海运','6000']};
  class Missing extends Error{constructor(path,message,kind='input'){super(message);this.path=path;this.kind=kind;}}
  function need(ok,path,msg,kind){if(!ok)throw new Missing(path,msg,kind);}
  function num(v,path,min=0,max=null){let n;try{n=E.d(v,path);}catch{throw new Missing(path,'请补充有效数值');}need(n.gte(min)&&(max===null||n.lte(max)),path,'数值超出允许范围');return n;}
  const copy=E.clone, str=v=>v===null||v===undefined?null:String(v);
  function unwrap(raw){
    if(typeof raw==='string')return unwrap(JSON.parse(raw));
    if(raw?.content){const t=raw.content.find(x=>x.type==='text');return t?unwrap(t.text):{};}
    if(raw?.data)return raw.data;return raw||{};
  }
  function decimalText(x){return String(x).replace(/(\d),(\d)/g,'$1.$2');}
  function dimensions(value){
    if(Array.isArray(value))return value.length===3?value.map(str):null;
    if(!value)return null;
    const s=decimalText(value),m=s.match(/(\d+(?:\.\d+)?)\s*(?:[x×*]|[Ll]\s*[x×])\s*(\d+(?:\.\d+)?)\s*(?:[x×*]|[Ww]\s*[x×])\s*(\d+(?:\.\d+)?)/);
    if(!m)return null;
    const factor=/inches|inch|in\b|英寸|pouces|zoll|pollici/i.test(s)?'2.54':/\bmm\b|ミリ|毫米/i.test(s)?'0.1':/\bcm\b|centim|厘米|センチ|сm/i.test(s)?'1':null;
    return factor?m.slice(1).map(x=>E.d(x).times(factor).toString()):null;
  }
  function weight(value){
    if(value===null||value===undefined)return null;
    const s=decimalText(value),m=s.match(/([\d.]+)/);if(!m)return null;
    const factor=/kg|kilogram|公斤|千克|キログラム/i.test(s)?'1':/pound|pfund|livres?|libras?|\blbs?\b|磅/i.test(s)?'0.45359237':/ounce|\boz\b|盎司/i.test(s)?'0.028349523125':/gram|\bg\b|グラム|克/i.test(s)?'0.001':null;
    return factor?E.d(m[1]).times(factor).toString():null;
  }
  function category(raw){
    const s=[raw.feeCategory,raw.nodeLabelPath,raw.category,raw.bsrLabel].filter(Boolean).join(':');
    const patterns=[['footwear',/shoes|footwear|pumps|court shoes|schuhe|chaussures|scarpe|zapatos|シューズ|靴|鞋/i],['apparel',/clothing|apparel|bekleidung|vêtements|abbigliamento|ropa|服/i],['home',/home|kitchen|küche|haushalt|cuisine|maison|casa|cocina|ホーム|キッチン|家居|厨房/i],['toys',/toy|spielzeug|jouet|giocattol|juguete|おもちゃ|玩具/i],['sports',/sport|outdoor|deporte|スポーツ|运动/i],['pet',/pet supplies|haustier|animaux|animali|mascotas|ペット/i],['office',/office|büro|bureau|ufficio|oficina|文房具/i],['electronicsAccessories',/electronic.*accessor|cable|computer.*accessor|kabel|ケーブル/i]];
    if(['footwear','apparel','home','kitchen','toys','sports','pet','office','electronicsAccessories'].includes(raw.feeCategory))return raw.feeCategory;
    return patterns.find(([,r])=>r.test(s))?.[0]||null;
  }
  function prepare(bundle,resources={}){
    if(bundle.schemaVersion===VERSION)return copy(bundle);
    const raw=copy(unwrap(bundle.raw)),u=bundle.user||{},p=bundle.product||{},meta={},notes=[];
    if(raw.marketplace==='GB')raw.marketplace='UK';
    const identity=E.parseIdentity(bundle.url||p.url||raw.asinUrl||raw.asin,p.site||raw.marketplace);
    need(!raw.asin||raw.asin===identity.asin,'product.asin','工具返回了不同 ASIN，请重新读取当前变体','collection');
    need(!raw.marketplace||raw.marketplace===identity.site,'product.site','工具返回了其他站点的数据','collection');
    const set=(key,value,origin,note)=>{meta[key]={origin,note:note||''};return value;};
    let cm=p.packaging?.cm||dimensions(raw.packageDimensions)||dimensions(raw.dimensions||raw.productDimensions);
    let kg=p.packaging?.kg??(raw.packageWeightKg!=null?str(raw.packageWeightKg):weight(raw.packageWeight)||weight(raw.weight||raw.itemWeight));
    const packageKnown=!!(p.packaging?.basis==='package'||raw.packageDimensions&&(raw.packageWeight||raw.packageWeightKg!=null));
    set('product.packaging',null,p.packaging?(p.packaging.origin||'user'):packageKnown?'extracted':'estimated',packageKnown?'销售包装资料':'页面尺寸/重量近似用于单销售包装，不增加外箱余量');
    if(!packageKnown)notes.push('尺寸与重量按页面资料近似用于单个销售包装。');
    const price=p.price??(raw.price>0?raw.price:null);
    let adjusted=price;
    if(p.price==null&&raw.unconditionalDiscount&&price!==null){const c=raw.unconditionalDiscount;need(['amount','percent'].includes(c.kind),'product.price','优惠类型无效');const v=num(c.value,'优惠数值',0,c.kind==='percent'?100:null);adjusted=c.kind==='percent'?E.d(price).times(new D(1).minus(v.div(100))).toString():E.d(price).minus(v).toString();notes.push('已扣除采集时明确识别的无条件公开优惠。');}
    else if(raw.coupon)notes.push('页面有优惠标识，尚未证明无条件适用，当前按公开单次购买价估算。');
    const scenario={};for(const k of ['purchaseCny','returnRate','adRatio','unsellableRatio','ageDays']){
      const fallback=k==='returnRate'?raw.returnRate:undefined;
      const value=u[k]??fallback??(Object.hasOwn(DEFAULTS,k)?resources.defaults?.[k]??DEFAULTS[k]:null);
      scenario[k]=str(set('scenario.'+k,value,u[k]!=null?'user':fallback!=null?'extracted':value!=null?'default':'missing'));
    }
    const logistics={};for(const [key,value]of Object.entries(u.logistics||bundle.logistics||{})){
      need(CHANNELS[key],'logistics.'+key,'未知物流渠道');if(value===null||value===undefined)continue;
      const q=typeof value==='object'?value:{pricePerKg:str(value)};
      logistics[key]={pricePerKg:str(q.pricePerKg),divisor:str(q.divisor??CHANNELS[key][1]),currency:q.currency||'CNY'};
    }
    scenario.channel=u.channel||null;
    let cat=p.category||category(raw);
    if(cat==='home'&&/kitchen|küche|cuisine|cocina|キッチン|厨房/i.test(raw.nodeLabelPath||raw.category||''))cat='kitchen';
    const now=bundle.asOf||new Date().toISOString();
    const product={...identity,title:p.title||raw.title||identity.asin,url:bundle.url||raw.asinUrl||'https://www.'+E.SITES[identity.site][0]+'/dp/'+identity.asin,
      price:str(set('product.price',adjusted,p.price!=null?(p.priceOrigin||'user'):'extracted')),category:cat,
      salesUnit:p.salesUnit||(cat==='footwear'?'双':'个销售包装'),packQuantity:p.packQuantity??raw.numberOfItems??Number((String(raw.title||'').match(/(?:pack of|pack de|packung mit|セット)\s*(\d+)/i)||[])[1]||1),
      packaging:{cm,kg:str(kg),basis:packageKnown?'package':'proxy'},goodsType:p.goodsType||raw.goodsType||'ordinary',
      referenceRole:'链接同款/同类型参考参数',variant:p.variant||raw.skuList||[],dataUpdatedAt:raw.updatedTime?new Date(raw.updatedTime).toISOString():bundle.collectedAt||now};
    if(Date.parse(now)-Date.parse(product.dataUpdatedAt)>30*86400000)notes.push('商品数据超过 30 天；售价需要商品页刷新，历史尺寸仍可作为近似参考。');
    return {schemaVersion:VERSION,kind:'screening',asOf:now,product,scenario,logistics,
      feePack:bundle.feePack||resources.feePack||null,fx:bundle.fx||resources.fx||null,overrides:bundle.overrides||{},
      fieldMeta:meta,notes,excluded:EXCLUDED,source:bundle.source||{type:'thirdParty',locator:product.url,at:bundle.collectedAt||now},fixture:bundle.fixture===true};
  }
  function packCheck(pack,site,asOf){
    need(pack&&pack.site===site,'feePack','缺少本站点费率包','rules');
    need(pack.source?.locator&&pack.checkedAt,'feePack.source','费率缺少来源或检查时间','rules');
    const t=Date.parse(asOf);need(Number.isFinite(t),'asOf','测算时间无效');
    need(!pack.invalidated&&(!pack.validUntil||t<=Date.parse(pack.validUntil+'T23:59:59Z')),'feePack','费率已知失效，需要更新','rules');
    need(!pack.effectiveFrom||t>=Date.parse(pack.effectiveFrom),'feePack','费率尚未生效','rules');
    need(Number.isFinite(Date.parse(pack.checkedAt)),'feePack.checkedAt','费率检查时间无效','rules');
  }
  function validate(input){
    const missing=[];const check=f=>{try{f();}catch(e){missing.push({path:e.path||'input',message:e.message,kind:e.kind||'input'});}};
    check(()=>need(input?.schemaVersion===VERSION&&input.kind==='screening','schemaVersion','不是快速测算格式'));
    if(!input||typeof input!=='object')return missing;
    const p=input.product||{},s=input.scenario||{};
    check(()=>need(E.SITES[p.site]&&E.SITES[p.site][1]===p.currency,'product.site','站点与币种无效'));
    check(()=>need(/^[A-Z0-9]{10}$/.test(p.asin||''),'product.asin','缺少明确的子 ASIN'));
    check(()=>num(p.price,'product.price','0.00000001'));check(()=>need(p.category,'product.category','需自动识别收费类目','collection'));
    check(()=>{need(p.packaging?.cm?.length===3,'product.packaging.cm','无法读取尺寸，请补充单销售包装长宽高');p.packaging.cm.forEach(x=>num(x,'product.packaging.cm','0.00000001'));});
    check(()=>num(p.packaging?.kg,'product.packaging.kg','0.00000001'));
    check(()=>num(s.purchaseCny,'scenario.purchaseCny'));check(()=>{const r=num(s.returnRate,'scenario.returnRate',0,1);need(r.lt(1),'scenario.returnRate','退货率必须小于 100%');});
    check(()=>num(s.adRatio,'scenario.adRatio'));check(()=>num(s.unsellableRatio,'scenario.unsellableRatio',0,1));check(()=>num(s.ageDays,'scenario.ageDays'));
    check(()=>{const q=num(p.packQuantity,'product.packQuantity',1);need(q.isInteger(),'product.packQuantity','销售包装数量须为正整数');});
    check(()=>need(input.logistics&&Object.keys(input.logistics).length,'logistics','请提供至少一条头程单价（元/kg）'));
    for(const [k,q]of Object.entries(input.logistics||{}))check(()=>{need(CHANNELS[k],'logistics.'+k,'未知渠道');num(q.pricePerKg,'logistics.'+k+'.pricePerKg');num(q.divisor,'logistics.'+k+'.divisor','0.00000001');need(q.currency==='CNY','logistics.'+k+'.currency','头程单价请转换为人民币/kg');});
    check(()=>{need(['CNH','CNY'].includes(input.fx?.kind)&&input.fx.source?.locator&&input.fx.asOf,'fx','缺少有来源的人民币参考汇率','collection');num(input.fx.cnhPerCurrency?.[p.currency],'fx.rate','0.00000001');need(Number.isFinite(Date.parse(input.fx.asOf)),'fx.asOf','汇率日期无效','collection');});
    check(()=>packCheck(input.feePack,p.site,input.asOf));
    if(!input.fixture)check(()=>need(!input.feePack?.fixture&&!input.fx?.fixture,'fixture','人工费率不可用于真实商品'));
    return missing;
  }
  function matchTier(t,p,ctx){
    if(t.categories&&!t.categories.includes(p.category))return false;
    if(t.excludeCategories?.includes(p.category))return false;
    if(t.minPrice!==undefined&&ctx.price.lt(t.minPrice))return false;
    if(t.maxPrice!==undefined&&ctx.price.gt(t.maxPrice))return false;
    if(t.priceBelow!==undefined&&ctx.price.gte(t.priceBelow))return false;
    if(t.maxCm&&t.maxCm.some((v,i)=>ctx.cm[i].gt(v)))return false;
    if(t.maxSumCm&&ctx.cm.reduce((a,b)=>a.plus(b),new D(0)).gt(t.maxSumCm))return false;
    if(t.maxKg&&ctx.weightKg.gt(t.maxKg))return false;
    if(t.minKg&&ctx.weightKg.lte(t.minKg))return false;
    if(t.maxDimKg&&ctx.volumeCm3.div(t.divisor||5000).gt(t.maxDimKg))return false;
    return true;
  }
  function override(input,key,ctx){
    const o=input.overrides?.[key];if(!o)return null;
    need(o.source?.locator&&o.note,'overrides.'+key,'固定费用需要来源与估计说明','rules');
    for(const field of ['site','category',...(key==='fulfillment'?['price','packaging']:key==='commission'?['price']:[])])need(JSON.stringify(o.bindings?.[field])===JSON.stringify(input.product[field]),'overrides.'+key,'费用估计适用条件已改变，请刷新费用','rules');
    return num(o.amount,'overrides.'+key);
  }
  function costs(input,channel,season){
    const p=input.product,s=input.scenario,pack=input.feePack;
    const cm=p.packaging.cm.map(x=>E.d(x)).sort((a,b)=>b.comparedTo(a));
    const ctx={price:E.d(p.price),weightKg:E.d(p.packaging.kg),cm,volumeCm3:cm.reduce((a,b)=>a.times(b),new D(1)),category:p.category,r:E.d(s.returnRate)};
    need(pack.goodsTypes?.includes(p.goodsType||'ordinary'),'product.goodsType','当前费率包未覆盖此货物属性','rules');
    const cr=pack.commissions[p.category];need(cr!==undefined&&cr!==null||input.overrides?.commission,'product.category','本站点费率包尚未覆盖此收费类目','rules');
    const tax=pack.salesTax[p.category]??pack.salesTax.default;need(tax!==undefined,'feePack.salesTax','缺少商品价内销售税规则','rules');
    ctx.R=ctx.price.div(new D(1).plus(E.d(tax)));
    const fx=E.d(input.fx.cnhPerCurrency[p.currency]);ctx.C=E.d(s.purchaseCny).div(fx);
    const q=input.logistics[channel];need(q,'scenario.channel','请选择已提供报价的渠道');
    const weight=D.max(ctx.weightKg,ctx.volumeCm3.div(q.divisor));ctx.H=weight.times(q.pricePerKg).div(fx);
    const round=x=>x.toDecimalPlaces(pack.feePrecision??2);
    ctx.M=override(input,'commission',ctx)??round(E.expr(cr,ctx));
    const tier=pack.fulfillment.find(t=>matchTier(t,p,ctx));
    const fixed=override(input,'fulfillment',ctx);
    need(tier||fixed!==null,'feePack.fulfillment','尺寸或重量超出费率包范围，需要读取对应档位','rules');
    ctx.shippingWeight=tier?.weightMode==='max'?D.max(ctx.weightKg,ctx.volumeCm3.div(tier.divisor)):ctx.weightKg;
    if(tier?.roundStepKg)ctx.shippingWeight=ctx.shippingWeight.div(tier.roundStepKg).ceil().times(tier.roundStepKg);
    ctx.F=fixed??round(E.expr(tier.expression,ctx).times(pack.fulfillmentMultiplier||1));
    if(tier?.returnProcessing!==undefined)ctx.returnProcessing=E.expr(tier.returnProcessing,ctx);
    const storage=(pack.storage||[]).find(x=>(!x.categories||x.categories.includes(p.category))&&(!x.size||x.size===tier?.storageSize));
    need(storage,'feePack.storage','缺少当前尺寸等级的基础仓储费','rules');
    ctx.S=ctx.volumeCm3.div(storage.volumeCm3PerUnit).times(storage[season]).times(s.ageDays).div(30);
    ctx.A=ctx.R.times(s.adRatio);
    let fees=new D(0);if(E.d(s.returnRate).gt(0)){
      const rr=pack.returns.find(x=>!x.categories||x.categories.includes(p.category));need(rr,'feePack.returns','缺少退款及退货费用依据','rules');
      fees=E.expr(rr.expression,ctx);if(rr.note)ctx.returnNote=rr.note;
    }
    const invested=ctx.C.plus(ctx.H).plus(ctx.S);
    const ret=E.allocateReturns(s.returnRate,fees,s.unsellableRatio,invested);
    const total={C:ctx.C,H:ctx.H,M:ctx.M,F:ctx.F,S:ctx.S,A:ctx.A,D:ret};
    for(const [k,v]of Object.entries(total))need(v.isFinite()&&v.gte(0),'feePack.'+k,'费用规则返回了无效金额','rules');
    const G=ctx.R.minus(Object.values(total).reduce((a,b)=>a.plus(b),new D(0)));
    return {metrics:{grossProfit:G.toString(),margin:G.div(ctx.R).toString(),cnyEquivalent:G.times(fx).toString(),revenue:ctx.R.toString(),beforeAdvertising:G.plus(ctx.A).toString(),adBreakEven:G.plus(ctx.A).div(ctx.R).toString()},totals:Object.fromEntries(Object.entries(total).map(([k,v])=>[k,v.toString()])),detail:{tier:tier?.id||'有来源的单件费用估计',shippingWeightKg:ctx.shippingWeight.toString(),freightWeightKg:weight.toString(),storageRate:storage[season],storageVolumeUnit:storage.volumeCm3PerUnit,volumeCm3:ctx.volumeCm3.toString(),returnFees:fees.toString(),returnNote:ctx.returnNote||null},channel,season};
  }
  function calculate(input){
    const missing=validate(input);if(missing.length)return {schemaVersion:VERSION,status:'待补信息',missingItems:missing,scenarios:null};
    const results={},issues=[];for(const channel of Object.keys(input.logistics)){
      try{results[channel]={low:costs(input,channel,'low'),peak:costs(input,channel,'peak')};results[channel].difference=E.d(results[channel].peak.metrics.grossProfit).minus(results[channel].low.metrics.grossProfit).toString();}
      catch(e){issues.push({path:e.path||'input',message:e.message,kind:e.kind||'rules',channel});}
    }
    const ranking=Object.keys(results).sort((a,b)=>E.d(results[b].low.metrics.grossProfit).comparedTo(results[a].low.metrics.grossProfit));
    const selected=results[input.scenario.channel]?input.scenario.channel:ranking[0];
    const notes=[...(input.notes||[]),...(input.feePack.notes||[])];
    if(input.fx.kind==='CNY')notes.push('采用公开 CNY 参考汇率，未将其冒称 CNH 结汇价；未计汇兑价差。');
    if(Date.parse(input.asOf)-Date.parse(input.feePack.checkedAt)>7*86400000)notes.push('费率超过 7 天未检查；当前仅作缓存费率参考，需执行 refresh。');
    if(Date.parse(input.asOf)-Date.parse(input.fx.asOf)>86400000)notes.push('汇率超过 24 小时；采用最近可得报价，需刷新汇率。');
    for(const r of Object.values(results))if(r.low.detail.returnNote)notes.push(r.low.detail.returnNote);
    return {schemaVersion:VERSION,status:ranking.length?'选品参考估算':'需要更新规则',missingItems:issues,channel:selected||null,scenarios:selected?results[selected]:null,channels:results,ranking:issues.length?null:ranking,notes:[...new Set(notes)],excluded:EXCLUDED,currency:input.product.currency};
  }
  // Probe platform coverage while operating inputs are blank; never use probe amounts as results.
  function preflight(input){
    const probe=copy(input);probe.scenario||={};
    for(const [key,value]of Object.entries({purchaseCny:'0',returnRate:'0.01',...DEFAULTS}))if(probe.scenario[key]===null||probe.scenario[key]===undefined||probe.scenario[key]==='')probe.scenario[key]=value;
    probe.logistics={sea:{pricePerKg:'0',divisor:'6000',currency:'CNY'}};probe.scenario.channel='sea';
    return calculate(probe).missingItems.filter(x=>x.kind==='rules'||x.path.startsWith('fx'));
  }
  function auditImport(input){need(input?.schemaVersion===VERSION,'schemaVersion','请选择快速测算 v2 JSON');const out=calculate(input);need(out.scenarios&&out.missingItems.length===0,'input','导入失败：'+out.missingItems.map(x=>x.message).join('；'));return copy(input);}
  return {VERSION,DEFAULTS,EXCLUDED,CHANNELS,prepare,validate,calculate,preflight,costs,dimensions,weight,category,unwrap,auditImport};
});
