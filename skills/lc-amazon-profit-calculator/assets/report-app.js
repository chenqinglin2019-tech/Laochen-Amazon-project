(function () {
  'use strict';
  const E = ProfitEngine, D = ProfitDecision, $ = id => document.getElementById(id);
  const initial = JSON.parse($('dataset').textContent), openingResult = E.calculate(initial);
  let state = E.clone(initial), scenes = state.savedScenarios || [], toastTimer;
  const FIELD_DEFS = [
    ['成交价', 'product.price', 'number', 'currency', '已扣除优惠后的实际成交价。'],
    ['采购成本', 'scenario.purchaseCny', 'number', '元', '人民币，每个销售包装单位。'],
    ['广告占比', 'scenario.adRatio', 'percent', '%', '退款后去税净收入的占比，不是 ACOS。'],
    ['退货率', 'scenario.returnRate', 'percent', '%', '退款退货单位 ÷ 总发货单位。'],
    ['不可再售比例', 'scenario.unsellableRatio', 'percent', '%', '退回商品中无法再次销售的比例。'],
    ['平均库龄', 'scenario.ageDays', 'number', '天', '入仓到售出的平均停留天数。'],
    ['发货日期', 'scenario.shipDate', 'date', '', '按站点当地日期。'],
    ['入仓日期', 'scenario.entryDate', 'date', '', '渠道提供运输时效时，由发货日推算。'],
    ['代表出库日期', 'scenario.exitDate', 'date', '', '留空则按入仓日加平均库龄。'],
    ['包装毛重', 'product.packaging.kg', 'number', 'kg', '销售包装毛重，不是商品净重。'],
    ['包装长', 'product.packaging.cm.0', 'number', 'cm', ''],
    ['包装宽', 'product.packaging.cm.1', 'number', 'cm', ''],
    ['包装高', 'product.packaging.cm.2', 'number', 'cm', '']
  ];
  const SOURCE_LABELS = {product:'商品信息',price:'成交价格',packaging:'销售包装',purchase:'采购成本',advertising:'广告口径',returns:'退货参数',inventory:'库存日期',taxProfile:'税务资格',costBoundary:'成本包含范围'};
  const SOURCE_TYPES = {official:'官方资料',user:'用户确认',thirdParty:'第三方资料',fixture:'人工测试数据'};
  const RULE_LABELS = {commission:'销售佣金',fulfillment:'FBA 配送',inbound:'入库服务',importTax:'进口税费',otherTax:'其他税费',storage:'仓储费用',salesTax:'销售税',returnLoss:'退货损失',withholding:'所得税预扣'};
  const REVIEW_LABELS = {mediaFee:'媒介交易费',individualPlan:'销售计划',peakDelivery:'旺季配送费',lowInventory:'低库存费用',storageUtilization:'仓储使用率费用',agedInventory:'超龄库存费',inboundPlacement:'入库配置费',inboundDefect:'入库缺陷费',prepLabel:'预处理和贴标',partneredCarrier:'合作承运人费用',overseasAWD:'中转仓费用',digitalService:'数字服务费',promotion:'促销推广费',payoutFX:'收款与结汇费',epr:'合规分摊',serviceTax:'费用服务税',importTax:'进口税',withholding:'所得税预扣',returns:'退货费用'};
  const COST_GROUPS = [
    {name:'采购',keys:['C'],color:'#3455db'}, {name:'头程物流',keys:['H'],color:'#7e98d5'},
    {name:'平台与仓储',keys:['M','F','S','I'],color:'#b1c0df'}, {name:'广告',keys:['A'],color:'#d5deee'},
    {name:'退货损失',keys:['D'],color:'#c9b7a5'}, {name:'税费及其他',keys:['T','O'],color:'#8d9bad'}
  ];
  const get = (obj,path) => path.split('.').reduce((a,k)=>a?.[k],obj);
  function set(obj,path,value) { const keys=path.split('.');let parent=obj;for(const key of keys.slice(0,-1)){if(!parent[key]||typeof parent[key]!=='object')parent[key]={};parent=parent[key];}parent[keys.at(-1)]=value; }
  function el(tag,text,className) { const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node; }
  function clear(...ids) { ids.forEach(id=>$(id).replaceChildren()); }
  function numeric(v,places) { if(v===null||v===undefined)return '—';return E.d(v).toFixed(places??(state.product.currency==='JPY'?0:2)); }
  function money(v) { return v===null||v===undefined?'—':numeric(v)+' '+(state.product.currency||''); }
  function pct(v,places=2) { return E.d(v).times(100).toFixed(places)+'%'; }
  function signedMoney(v) { return (E.d(v).gt(0)?'+':'')+money(v); }
  function changed(path) { const a=get(state,path),b=get(initial,path);return (a===null||a===undefined?'':String(a))!==(b===null||b===undefined?'':String(b)); }
  function record(path,value,reason='在报告中调整参数') { const old=get(state,path);set(state,path,value);if(JSON.stringify(old)!==JSON.stringify(value))state.history.push({path,previous:old??null,current:value,at:new Date().toISOString(),reason}); }
  function message(text,isError=false) { clearTimeout(toastTimer);$('error').textContent=text;$('error').setAttribute('role',isError?'alert':'status');if(!isError)toastTimer=setTimeout(()=>$('error').textContent='',6000); }
  function badge(text,tone='') { return el('span',text,'badge '+tone); }
  function fieldName(path) {
    const exact=FIELD_DEFS.find(f=>f[1]===path);if(exact)return exact[0];
    if(path?.startsWith('logistics.'))return (E.CHANNELS[path.split('.')[1]]?.[0]||'物流')+'报价';
    if(path?.startsWith('rules.'))return RULE_LABELS[path.split('.')[1]]||'费用规则';
    if(path?.startsWith('feeReview.'))return REVIEW_LABELS[path.split('.')[1]]||'费用确认';
    if(path?.startsWith('provenance.'))return SOURCE_LABELS[path.split('.')[1]]||'数据来源';
    if(path?.includes('fx')||path==='汇率')return '汇率';
    return {'product':'商品资料','product.site':'站点与币种','product.asin':'商品变体','sellerProfile':'税务与销售资格','scenario.channel':'物流渠道','extraFees':'补充费用','assumptions':'测算假设','schemaVersion':'文件版本'}[path]||'测算资料';
  }
  function linkSource(parent,source) {
    if(!source){parent.append(el('span','未提供来源定位'));return;}
    let url;try{url=new URL(source.locator);}catch{}
    if(url&&['https:','http:'].includes(url.protocol)){const a=el('a','查看来源');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);}
    else parent.append(el('span',source.locator||'未提供来源定位'));
  }
  function fact(parent,label,value) { const row=el('div',undefined,'fact');row.append(el('dt',label),el('dd',value));parent.append(row); }
  function expandWorkbench(path) {
    $('bench-content').hidden=false;$('bench-toggle').setAttribute('aria-expanded','true');$('bench-toggle').textContent='收起调参';$('workbench').classList.remove('collapsed');
    const input=path==='target'?$('target'):document.querySelector('[data-path="'+path+'"]');
    if(input){const details=input.closest('details');if(details)details.open=true;input.focus();input.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
  }
  function targetControls() { const t=D.target(state);const raw=state.reportPreferences?.targetMargin;$('target').value=raw===undefined||raw===null||raw===''?'':t.status==='invalid'?String(Number(raw)*100):E.d(raw).times(100).toString(); }
  function controls() {
    clear('fields','advancedFields','extraFields');
    const extra=(state.editableParameters||[]).filter(x=>/^(ruleSnapshot\.rules\.[A-Za-z]+\.(expression|tax\.rate)|extraFees\.\d+\.rule\.expression)$/.test(x.path)&&typeof get(state,x.path)!=='object');
    [...FIELD_DEFS,...extra.map(x=>[x.label,x.path,x.type||'number',x.unit||'','按已确认的适用范围重算。'])].forEach((definition,index)=>{
      const [label,path,type,unit,help]=definition,container=index<6?$('fields'):index<FIELD_DEFS.length?$('advancedFields'):$('extraFields');
      const block=el('div',undefined,'field'),heading=el('div',undefined,'field-heading'),lab=el('label',label),mark=el('span',undefined,'changed-mark');
      const id='field-'+index;lab.htmlFor=id;mark.id='mark-'+index;heading.append(lab,mark);
      const wrap=el('div',undefined,'input-wrap'),input=el('input');input.id=id;input.type=type==='date'?'date':'number';input.step='any';input.dataset.path=path;
      const v=get(state,path);input.value=v===null||v===undefined?'':type==='percent'?E.d(v).times(100).toString():String(v);
      input.setAttribute('aria-describedby','help-'+index+' err-'+index);wrap.append(input);if(unit)wrap.append(el('span',unit==='currency'?state.product.currency:unit,'input-unit'));
      const hint=el('p',help,'field-help');hint.id='help-'+index;const error=el('p',undefined,'field-error');error.id='err-'+index;
      input.addEventListener('input',()=>{
        let value=input.value;if(type==='percent'&&value!=='')value=E.d(value).div(100).toString();record(path,value);
        if(path==='scenario.adRatio')delete state.scenario.adInput;
        if(path==='scenario.ageDays'){record('scenario.exitDate',null,'调整库龄后按入仓日重新推算出库');const exit=document.querySelector('[data-path="scenario.exitDate"]');if(exit)exit.value='';}
        render();
      });
      block.append(heading,wrap,hint,error);container.append(block);
    });
    if(!extra.length)$('extraFields').append(el('p','当前没有已授权直接调整的税费项目。需要变更税务资格或规则时，请回到 Skill 更新测算。','field-help note'));
    $('channel').replaceChildren(...Object.entries(E.CHANNELS).filter(([key])=>state.logistics?.[key]?.status!=='excluded').map(([key,value])=>{const option=el('option',value[0]);option.value=key;return option;}));$('channel').value=state.scenario.channel;
    $('scenes').replaceChildren(el('option',scenes.length?'选择已保存方案':'尚未保存方案'));$('scenes').firstChild.value='';scenes.forEach((scene,index)=>{const o=el('option',scene.name);o.value=String(index);$('scenes').append(o);});targetControls();
  }
  function refreshControlState(result) {
    FIELD_DEFS.forEach((f,i)=>{const mark=$('mark-'+i),input=$('field-'+i),error=$('err-'+i);mark.textContent=changed(f[1])?'已修改':'';const issue=result.missingItems?.find(x=>x.path===f[1]);input.setAttribute('aria-invalid',issue?'true':'false');error.textContent=issue?.message||'';});
    const count=FIELD_DEFS.filter(f=>changed(f[1])).length+(changed('scenario.channel')?1:0),feesChanged=['ruleSnapshot','sellerProfile','logistics','extraFees'].some(key=>JSON.stringify(state[key])!==JSON.stringify(initial[key]));$('changes').textContent=count?'较打开时修改 '+count+' 项'+(feesChanged?'，费用资料已更新':''):feesChanged?'费用资料已更新':'当前为打开时参数';
    const t=D.target(state);$('targetError').textContent=t.status==='invalid'?t.message:'';$('target').setAttribute('aria-invalid',t.status==='invalid'?'true':'false');
    const quote=state.logistics?.[state.scenario.channel],derivedEntry=quote?.transitDays!==undefined;
    $('field-7').disabled=derivedEntry;
    if(derivedEntry){$('field-7').value=result.dates?.entry||'';$('help-7').textContent='当前渠道时效 '+quote.transitDays+' 天，按发货日自动推算。';}
    else $('help-7').textContent=FIELD_DEFS[7][4];
    $('field-8').disabled=!!quote?.exitDate;$('field-5').disabled=!!quote?.exitDate;
    if(quote?.exitDate){$('field-8').value=quote.exitDate;$('field-5').value=result.dates?.ageDays||'';$('help-5').textContent='当前渠道已指定出库日期，按实际区间显示。';$('help-8').textContent='此日期属于已确认的渠道方案，请回到 Skill 更新。';}
    else {$('help-5').textContent=FIELD_DEFS[5][4];$('help-8').textContent=result.dates?'当前计算出库日 '+result.dates.exit+'；留空时按入仓日加库龄。':FIELD_DEFS[8][4];}
  }
  function renderIdentity(result) {
    $('title').textContent=state.product.title||'待补商品资料';$('identity').replaceChildren();
    for(const [name,value]of [['站点',state.product.site],['ASIN',state.product.asin],['币种',state.product.currency],['测算日期',state.scenario.calculationDate]]){const s=el('span',name);s.append(el('b',value||'待补充'));$('identity').append(s);}
    $('demo').hidden=!state.fixture;$('heroContext').textContent='当前方案 / '+(E.CHANNELS[state.scenario.channel]?.[0]||'待选择渠道');
    const displayed={可计算:'资料齐全',条件估算:'含估算条件',待补信息:'等待补充资料',需要更新规则:'规则需要更新'}[result.status]||result.status;
    $('status').textContent=displayed;$('status').className='badge '+(!result.metrics?'bad':result.status==='条件估算'?'warn':'');
  }
  function renderOverview(result) {
    clear('overviewContent','bridge','insights','conditions');const area=$('overviewContent');$('bridge').hidden=!result.metrics;$('insights').hidden=!result.metrics;
    if(!result.metrics){
      area.className='empty-state';area.append(el('h2',result.status==='需要更新规则'?'当前规则覆盖不到这次调整':'补齐资料后，再判断利润'),el('p','原结果已隐藏。处理以下问题后，报告会自动重新计算。'));
      const ul=el('ul',undefined,'issue-list');result.missingItems.forEach(issue=>{const li=el('li');li.append(el('b',fieldName(issue.path)),el('span',issue.message));if(FIELD_DEFS.some(f=>f[1]===issue.path)){const button=el('button','去填写','text-button');button.onclick=()=>expandWorkbench(issue.path);li.append(button);}ul.append(li);});area.append(ul);return;
    }
    area.className='';const m=result.metrics,g=E.d(m.grossProfit),margin=E.d(m.margin),goal=D.target(state);
    let headline=g.lt(0)?'当前方案亏损，先修复单件利润':'当前方案有毛利，尚未设置经营目标';
    if(goal.status==='set')headline=margin.gte(goal.value)?'当前方案达到你的毛利目标':'当前方案尚未达到你的毛利目标';
    area.append(el('h2',headline),el('p','按每个最终未退款的销售包装计算；以下结果已计入采购、物流、广告和退货等已确认成本。','hero-subtitle'));
    const row=el('div',undefined,'outcome-row'),main=el('div',undefined,'main-profit');main.append(el('span',g.lt(0)?'每件经营亏损':'每件经营毛利','metric-label'));
    const value=el('div',undefined,'profit-value '+(g.lt(0)?'negative':''));value.append(el('strong',numeric(g)),el('span',m.currency));main.append(value,el('div','人民币等值 '+numeric(m.cnyEquivalent,2)+' 元','metric-foot'));row.append(main);
    const rate=el('div',undefined,'secondary-metric');rate.append(el('span','经营毛利率','metric-label'),el('strong',pct(m.margin),g.lt(0)?'negative':''),el('div','以去税净收入为分母','metric-foot'));row.append(rate);
    const delta=el('div',undefined,'secondary-metric');const same=openingResult.metrics&&initial.product.asin===state.product.asin&&initial.product.site===state.product.site&&initial.product.currency===state.product.currency;
    delta.append(el('span','较打开时每件变化','metric-label'));
    if(same){const change=g.minus(openingResult.metrics.grossProfit);delta.append(el('strong',(change.gt(0)?'+':'')+numeric(change),change.gt(0)?'positive':change.lt(0)?'negative':''),el('div',m.currency+' / 留存销售单位','metric-foot'));}else delta.append(el('strong','—'),el('div','不同商品不直接对比','metric-foot'));row.append(delta);area.append(row);
    const target=el('div',undefined,'target-line');
    if(goal.status==='set'){const gap=margin.minus(goal.value),amount=E.d(m.revenue).times(goal.value).minus(g);target.append(el('span',gap.gte(0)?'目标 '+pct(goal.value)+'，当前高出 '+gap.times(100).toFixed(2)+' 个百分点。':'目标 '+pct(goal.value)+'，每件还需增加 '+money(amount)+' 毛利。'));}
    else target.append(el('span',goal.status==='invalid'?'目标毛利率无效，请修正；当前毛利仍按实际参数计算。':'还未设置毛利率目标。先填目标，再判断是否值得做。'));
    const targetButton=el('button',goal.status==='set'?'调整目标':'设置目标','text-button');targetButton.onclick=()=>expandWorkbench('target');target.append(targetButton);area.append(target);
    renderBridge(result);renderInsights(result,goal);
    if(result.assumptions.length){const details=el('details'),summary=el('summary','此结果包含 '+result.assumptions.length+' 项估算或排除，决策前请核对');const ul=el('ul');result.assumptions.forEach(x=>ul.append(el('li',x)));details.append(summary,ul);$('conditions').append(details);}
    const withheld=E.d(m.grossProfit).minus(m.afterUnrecoverableWithholding);if(withheld.gt(0))$('conditions').append(el('p','不可回收预扣 '+money(withheld)+'；扣除后的每件余额 '+money(m.afterUnrecoverableWithholding)+'。','negative'));
  }
  function renderBridge(result) {
    const m=result.metrics,net=E.d(m.revenue),profit=E.d(m.grossProfit),groups=COST_GROUPS.map(g=>({...g,amount:g.keys.reduce((sum,k)=>sum.plus(result.totals[k]),E.d(0))}));
    const cost=groups.reduce((sum,g)=>sum.plus(g.amount),E.d(0)),scale=E.Decimal.max(net,cost);
    const heading=el('div',undefined,'bridge-heading');heading.append(el('h3','一件商品的收入，留在哪里'),el('span','去税净收入 '+money(net)));$('bridge').append(heading);
    const track=el('div',undefined,'flow-track');track.setAttribute('role','img');track.setAttribute('aria-label','净收入 '+money(net)+'，总成本 '+money(cost)+'，毛利 '+money(profit));
    if(profit.gte(0))groups.push({name:'留下的毛利',amount:profit,color:'#187b58',profit:true});
    groups.forEach(group=>{if(group.amount.lte(0))return;const segment=el('div',undefined,'flow-segment');segment.style.width=group.amount.div(scale).times(100).toString()+'%';segment.style.background=group.color;segment.title=group.name+' '+money(group.amount)+'，占净收入 '+pct(group.amount.div(net));track.append(segment);});
    if(profit.lt(0)){const marker=el('i',undefined,'revenue-marker');marker.style.left=net.div(scale).times(100).toString()+'%';marker.title='净收入边界';track.append(marker);}
    $('bridge').append(track);const legend=el('div',undefined,'flow-legend');groups.forEach(group=>{const item=el('div',undefined,'legend-item '+(group.profit?'profit-legend':'')),label=el('span'),dot=el('i');dot.style.background=group.color;label.append(dot,document.createTextNode(group.name));item.append(label,el('b',numeric(group.amount)+' / '+pct(group.amount.div(net),1)));legend.append(item);});$('bridge').append(legend,el('p',profit.lt(0)?'成本超过净收入 '+money(profit.abs())+'；虚线标出收入边界。':'金额 / 占净收入比例。平台与仓储包含佣金、FBA 配送、仓储与入库服务。','flow-note'));
  }
  function renderInsights(result,goal) {
    const ad=goal.status==='invalid'?{status:'unavailable',reason:'先修正目标毛利率，再查看广告参考线。'}:D.adReference(state,goal.value||'0');
    const left=el('div',undefined,'insight');left.append(el('label',goal.status==='set'?'达到目标的广告参考线':'广告盈亏参考线'));
    if(ad.status==='available'){left.append(el('strong',pct(ad.ratio)));const headroom=E.d(ad.headroom);left.append(el('p',headroom.gte(0)?'当前 '+pct(state.scenario.adRatio)+'，距参考线 '+E.d(headroom).times(100).toFixed(2)+' 个百分点。':'当前 '+pct(state.scenario.adRatio)+'，已高出参考线 '+headroom.abs().times(100).toFixed(2)+' 个百分点。',headroom.lt(0)?'risk-copy':''),el('p','其他参数不变的模型临界点，并非建议广告预算。'));}
    else {left.append(el('strong',ad.status==='unreachable'?'仅降广告不足以达标':'暂无法确定'));left.append(el('p',ad.reason));}
    const costs=Object.entries(result.totals).filter(([,v])=>E.d(v).gt(0)).sort((a,b)=>E.d(b[1]).comparedTo(a[1]));const right=el('div',undefined,'insight');right.append(el('label','当前最大的单项成本'));
    if(costs.length){const [key,value]=costs[0];right.append(el('strong',E.LABELS[key]),el('p',money(value)+' / 件，占净收入 '+pct(E.d(value).div(result.metrics.revenue))+'。'));const button=el('button','查看成本明细','text-button');button.onclick=()=>{const details=$('costs').closest('details');details.open=true;details.scrollIntoView({block:'start',behavior:'smooth'});};right.append(button);}else right.append(el('strong','全部成本为零'),el('p','请核对零成本是否均有明确依据。'));
    $('insights').append(left,right);window.__adReference=ad;
  }
  function applyTrial(row) { record(row.path,row.value,'应用单因素试算：'+row.label);if(row.path==='scenario.adRatio')delete state.scenario.adInput;controls();render();message('已应用“'+row.label+'”，全部结果已重算。'); }
  function renderActions(result) {
    clear('opportunities','sensitivity');const rows=D.sensitivityRows(state),valid=rows.filter(x=>x.result.metrics);const improved=valid.filter(x=>E.d(x.delta).gt(0)).sort((a,b)=>E.d(b.delta).comparedTo(a.delta));$('actionCount').textContent=result.metrics?valid.length+' 项可试算':'等待资料';
    if(!result.metrics)$('opportunities').append(el('p','先完成当前方案，才能比较调整带来的收益。','muted'));
    else if(!improved.length)$('opportunities').append(el('p','当前可用试算中，没有提高单件毛利的调整。可展开下方查看限制原因。','muted'));
    improved.slice(0,3).forEach(row=>{const item=el('div',undefined,'opportunity'),title=el('div');title.append(el('div',row.label,'opportunity-title'));
      const newValue=row.path==='product.price'?money(row.value):row.path==='scenario.purchaseCny'?numeric(row.value,2)+' 元':pct(row.value);title.append(el('div','调整后 '+newValue,'opportunity-sub'));
      const profit=el('div',numeric(row.result.metrics.grossProfit),'opportunity-metric');profit.append(el('small','试算毛利 / '+state.product.currency));const gain=el('div','+'+numeric(row.delta),'opportunity-metric positive');gain.append(el('small','每件改善'));
      const button=el('button','试算','small-button');button.setAttribute('aria-label','应用试算：'+row.label);button.onclick=()=>applyTrial(row);item.append(title,profit,gain,button);$('opportunities').append(item);
    });
    rows.forEach(row=>{const tr=el('tr');tr.append(el('td',row.label),el('td',row.result.metrics?money(row.result.metrics.grossProfit):'—','numeric'),el('td',row.delta!==null?signedMoney(row.delta):'—','numeric '+(row.delta!==null&&E.d(row.delta).gt(0)?'positive':'')),el('td',row.fixedAdPerShipped?.metrics?money(row.fixedAdPerShipped.metrics.grossProfit):'—','numeric'));const status=el('td',row.result.metrics?row.result.status:'暂不可算');if(!row.result.metrics)status.append(el('small',row.result.missingItems?.map(x=>x.message).join('；')));tr.append(status);$('sensitivity').append(tr);});
  }
  function renderChannels(result) {
    clear('channels');const comparison=E.comparisons(state),active=Object.values(comparison.results).filter(x=>x.status!=='不参与'),complete=comparison.status==='可比较';
    $('comparisonStatus').textContent=complete?(active.length>1?'可完整比较':'仅一个参与渠道'):'报价待补齐';$('comparisonStatus').className='badge '+(complete?'neutral':'warn');
    let copy=active.length===1&&complete?'当前只有一个参与渠道；其余渠道由用户明确排除。':'同一商品、同一经营参数，比较各渠道最终单件毛利。';
    if(!complete)copy='报价或规则不完整，保留已知结果，暂不排名。';
    else if(active.length>1&&result.metrics&&comparison.ranking?.length){const best=comparison.results[comparison.ranking[0]],gap=E.d(best.metrics.grossProfit).minus(result.metrics.grossProfit);copy=gap.gt(0)?E.CHANNELS[comparison.ranking[0]][0]+'在已确认方案中单件毛利较高，比当前多 '+money(gap)+'。':'当前渠道在已确认方案中处于最高毛利水平。';if(best.status==='条件估算')copy+=' 比较包含估算条件。';}
    $('comparisonCopy').textContent=copy;
    Object.entries(comparison.results).forEach(([key,r])=>{const selected=key===state.scenario.channel,card=el('div',undefined,'channel '+(selected?'selected':r.status==='不参与'?'excluded':'')),name=el('div',undefined,'channel-name');name.append(document.createTextNode(E.CHANNELS[key][0]));if(selected)name.append(badge('当前','blue'));card.append(name);
      if(r.metrics){const value=el('div',numeric(r.metrics.grossProfit),'channel-profit '+(E.d(r.metrics.grossProfit).lt(0)?'negative':''));value.append(el('span',state.product.currency+' / 件毛利'));card.append(value);const dl=el('dl');for(const [label,value]of [['毛利率',pct(r.metrics.margin)],['头程',money(r.totals.H)],['到仓日',r.dates.entry]]){const line=el('div');line.append(el('dt',label),el('dd',value));dl.append(line);}card.append(dl);if(r.status==='条件估算')card.append(el('p','包含估算或排除项','muted'));const button=el('button',selected?'当前使用':'切换试算',selected?'small-button':'small-button primary');button.disabled=selected;button.onclick=()=>{record('scenario.channel',key,'切换物流方案');controls();render();message('已切换为'+E.CHANNELS[key][0]+'方案。');};card.append(button);}
      else if(r.status==='不参与'){card.append(badge('不参与','neutral'),el('p',r.reason||'已明确排除此渠道。'));}
      else {card.append(badge('待补资料','warn'),el('p',r.missingItems?.[0]?.message||'尚未提供有效报价。'),el('p','补齐后可比较','muted'));}
      $('channels').append(card);
    });
  }
  function renderAudit(result) {
    clear('costs','details','taxFacts','defaults','sources','history');
    if(result.metrics){const m=result.metrics;Object.entries(result.totals).sort((a,b)=>E.d(b[1]).comparedTo(a[1])).forEach(([key,value])=>{const tr=el('tr');tr.append(el('td',E.LABELS[key]),el('td',money(value),'numeric'),el('td',pct(E.d(value).div(m.revenue)),'numeric'));$('costs').append(tr);});
      result.feeItems.forEach(item=>{const detail=el('details',undefined,'fee-detail');detail.append(el('summary',E.LABELS[item.category]+'：'+money(item.amount)));detail.append(el('p',item.formula||'按已确认费用计算。'));if(item.serviceTax!==undefined)detail.append(el('p','不可抵扣服务税 '+money(item.serviceTax)+'；可抵扣税额 '+money(item.recoverableTax||'0')+'。'));const source=el('p');linkSource(source,item.source);detail.append(source);if(item.detail){const raw=el('details',undefined,'fee-detail');raw.append(el('summary','查看分摊过程'),el('pre',JSON.stringify(item.detail,null,2)));detail.append(raw);}$('details').append(detail);});
      for(const [label,value]of [['去税净收入',money(m.revenue)],['已还原的销售税',money(m.salesTax)],['可抵扣税额',money(m.recoverableTax)],['所得税预扣',money(m.withholding)],['扣除不可回收预扣后余额',money(m.afterUnrecoverableWithholding)],['库存区间',result.dates.entry+' 至 '+result.dates.exit],['计费停留天数',result.dates.ageDays+' 天（不含出库日）']])fact($('taxFacts'),label,value);
    }else{$('details').append(el('p','结果暂不可用，先处理顶部列出的缺项。'));}
    for(const [label,value]of [['销售单位','1 个包装包含 '+(state.product.unitsPerSale??'待确认')+' 件实物'],['销售计划',state.sellerProfile.salesPlan==='professional'?'专业销售计划':'个人销售计划'],['库存与买家','站点当地 FBA，本地普通消费者'],['广告分母','退款后、去税净销售额'],['快递体积重系数','5000（可由报价覆盖）'],['其他渠道体积重系数','6000（可由报价覆盖）'],['汇率快照',state.ruleSnapshot.fx?.quoteTime||state.ruleSnapshot.fx?.source?.at||'待补充']])fact($('defaults'),label,value);
    Object.entries(state.provenance||{}).forEach(([key,source])=>{const row=el('div',undefined,'source-row');row.append(el('strong',(SOURCE_LABELS[key]||'补充资料')+' / '+(SOURCE_TYPES[source.type]||'记录来源')));const text=el('p');linkSource(text,source);row.append(text,el('time',source.at||''));$('sources').append(row);});
    if(!state.history.length)$('history').append(el('p','尚未修改参数。'));state.history.slice().reverse().slice(0,50).forEach(h=>{const row=el('div',undefined,'source-row');row.append(el('strong',h.path==='reportPreferences.targetMargin'?'目标毛利率':fieldName(h.path)),el('p',(h.previous===null?'未填写':String(h.previous))+' 改为 '+String(h.current)+'；'+(h.reason||'参数修改')),el('time',h.at||''));$('history').append(row);});
    $('snapshot').textContent=JSON.stringify(state,null,2);
  }
  function render() {
    const started=performance.now(),result=E.calculate(state);renderIdentity(result);refreshControlState(result);renderOverview(result);renderActions(result);renderChannels(result);renderAudit(result);
    document.documentElement.dataset.lastRenderMs=String(performance.now()-started);window.__lastResult=result;
  }
  function restore() { state=E.clone(initial);state.savedScenarios=scenes;controls();render();message('已恢复打开时的方案，已保存方案仍保留。'); }
  $('channel').addEventListener('change',()=>{record('scenario.channel',$('channel').value);render();});
  $('target').addEventListener('input',()=>{const value=$('target').value;record('reportPreferences.targetMargin',value===''?'':E.d(value).div(100).toString(),'调整个人毛利率目标');render();});
  $('reset').onclick=restore;$('reset-top').onclick=restore;$('print').onclick=()=>window.print();
  $('bench-toggle').onclick=()=>{const open=$('bench-content').hidden;$('bench-content').hidden=!open;$('bench-toggle').setAttribute('aria-expanded',String(open));$('bench-toggle').textContent=open?'收起调参':'展开调参';$('workbench').classList.toggle('collapsed',!open);};
  $('export').onclick=()=>{const payload=E.clone(state);payload.savedScenarios=scenes;const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download='amazon-profit-'+state.product.asin+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已导出测算文件，包含当前参数、规则和保存的方案。');};
  $('save').onclick=()=>{$('save-error').textContent='';$('save-dialog').showModal();$('name').focus();};$('save-cancel').onclick=()=>$('save-dialog').close();
  function saveScene(){try{D.auditPreferences(state);const result=E.calculate(state);if(!result.metrics)throw new Error('先补齐当前方案的资料，再保存用于比较的方案。');const name=$('name').value.trim();if(!name)throw new Error('请填写方案名称。');const input=E.clone(state);delete input.savedScenarios;scenes.push({name,at:new Date().toISOString(),input});state.savedScenarios=scenes;controls();render();$('save-dialog').close();message('已保存“'+name+'”。关闭页面前请导出测算。');}catch(error){$('save-error').textContent=error.message;}}
  $('save-confirm').onclick=saveScene;$('name').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();saveScene();}});
  $('scenes').onchange=()=>{if($('scenes').value==='')return;const scene=scenes[Number($('scenes').value)];state=E.clone(scene.input);state.savedScenarios=scenes;controls();render();message('已切换到“'+scene.name+'”。');};
  $('import').onclick=()=>$('file').click();
  $('file').onchange=async()=>{const file=$('file').files[0];if(!file)return;const previous=state,previousScenes=scenes;try{if(file.size>5*1024*1024)throw new Error('文件超过 5 MiB');const next=E.auditImport(JSON.parse(await file.text()));D.auditPreferences(next);if(next.savedScenarios!==undefined&&!Array.isArray(next.savedScenarios))throw new Error('方案列表格式错误');for(const scene of next.savedScenarios||[]){if(typeof scene.name!=='string')throw new Error('方案缺少名称');E.auditImport(scene.input);D.auditPreferences(scene.input);}state=next;scenes=state.savedScenarios||[];controls();render();message('导入成功，已按保存的规则重新计算。');}catch(error){state=previous;scenes=previousScenes;controls();render();message('导入失败，当前数据已保留：'+error.message,true);}finally{$('file').value='';}};

  const navLinks=[...document.querySelectorAll('.nav-links a')];let scrollPending=false;
  function markNavigation(){const sections=navLinks.map(a=>document.querySelector(a.getAttribute('href')));let active=0;sections.forEach((section,index)=>{if(section.getBoundingClientRect().top<=125)active=index;});navLinks.forEach((a,index)=>{a.classList.toggle('active',index===active);if(index===active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});scrollPending=false;}
  window.addEventListener('scroll',()=>{if(!scrollPending){scrollPending=true;requestAnimationFrame(markNavigation);}},{passive:true});
  const mobileLayout=matchMedia('(max-width: 880px)');
  function syncWorkbenchLayout(){const open=!mobileLayout.matches;$('bench-content').hidden=!open;$('workbench').classList.toggle('collapsed',!open);$('bench-toggle').setAttribute('aria-expanded',String(open));$('bench-toggle').textContent=open?'收起调参':'展开调参';}
  mobileLayout.addEventListener('change',syncWorkbenchLayout);
  controls();syncWorkbenchLayout();render();
})();
