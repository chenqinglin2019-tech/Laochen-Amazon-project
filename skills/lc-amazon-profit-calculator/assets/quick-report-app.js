(()=>{'use strict';
const Q=QuickProfit,E=ProfitEngine,original=JSON.parse(document.getElementById('data').textContent);
const session=JSON.parse(document.getElementById('session')?.textContent||'null');
const token=session?new URLSearchParams(location.hash.slice(1)).get('token'):null;
let input=E.clone(original),result,revision=session?.revision||0,editVersion=0,savedVersion=0,timer,saving=false,conflict=false,saveFailed=false;
const $=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:input.product.currency,minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(x));
const pct=x=>(Number(x)*100).toFixed(1)+'%';
function percentageValue(value){try{const n=E.d(value);return n.isFinite()?n.times(100).toString():'';}catch{return '';}}
const categories={footwear:'鞋靴',apparel:'服装',home:'家居',kitchen:'厨房',toys:'玩具',sports:'运动户外',pet:'宠物用品',office:'办公用品',electronicsAccessories:'电子配件'};
const names={'product.price':'售价','product.category':'商品类目','product.packQuantity':'每包装件数','product.variant':'当前变体','product.packaging.cm':'包装长宽高','product.packaging.kg':'包装重量','scenario.purchaseCny':'采购成本','scenario.returnRate':'退货率','scenario.adRatio':'广告占比','scenario.unsellableRatio':'退货不可售比例','scenario.ageDays':'仓储天数',logistics:'头程报价',fx:'人民币参考汇率',feePack:'站点费用规则'};
function labelFor(path){if(names[path])return names[path];if(path.startsWith('logistics.'))return (Q.CHANNELS[path.split('.')[1]]?.[0]||'头程')+(path.endsWith('divisor')?'体积系数':'单价');if(path.startsWith('feePack.')||path.startsWith('overrides.'))return '平台费用规则';if(path.startsWith('fx.'))return '参考汇率';return '商品资料';}
function get(path){return path.split('.').reduce((a,k)=>a?.[k],input);}
function set(path,value){const ks=path.split('.');let x=input;for(let i=0;i<ks.length-1;i++){const k=ks[i];if(x[k]===null||typeof x[k]!=='object')x[k]=/^\d+$/.test(ks[i+1])?[]:{};x=x[k];}x[ks.at(-1)]=value;input.fieldMeta||={};input.fieldMeta[path]={origin:'user',note:'本页本次修改'};}
function field(path,label,{percent=false,step='any',max,container='fields',type='number',options,hint}={}){
 const wrapper=document.createElement('label');wrapper.className='field';wrapper.textContent=label;
 const el=document.createElement(options?'select':'input');el.dataset.path=path;el.setAttribute('aria-label',label);
 if(options){if(path!=='product.packaging.basis')el.append(new Option('请选择',''));for(const [key,name]of Object.entries(options))el.append(new Option(name,key));el.value=get(path)??'';}
 else{el.type=type;if(type==='number'){el.min='0';if(max!==undefined)el.max=String(max);el.step=step;}const value=get(path);el.value=value==null?'':percent?percentageValue(value):typeof value==='object'?JSON.stringify(value):value;}
 const note=document.createElement('small');note.className='field-error';note.id='err-'+path;note.setAttribute('aria-live','polite');el.setAttribute('aria-describedby',note.id);
 el.addEventListener(options?'change':'input',()=>{let value=el.value===''?null:el.value;if(percent&&value!==null){try{value=E.d(value).div(100).toString();}catch{value=null;}}set(path,value);changed();});
 wrapper.append(el);if(hint){const h=document.createElement('span');h.className='field-hint';h.textContent=hint;wrapper.append(h);}wrapper.append(note);$(container).append(wrapper);return el;
}
function quoteControls(){
 $('quotes').replaceChildren();$('freight-advanced').replaceChildren();
 const entries=Object.entries(input.logistics||{});const rows=entries.length?entries:[['sea',{pricePerKg:null,divisor:'6000',currency:'CNY'}]];
 for(const [key,q]of rows){const row=document.createElement('div');row.className='quote-row';const select=document.createElement('select');select.setAttribute('aria-label','头程渠道');
 for(const [k,v]of Object.entries(Q.CHANNELS)){if(k===key||!input.logistics[k])select.append(new Option(v[0],k));}select.value=key;
 select.addEventListener('change',()=>{const next=select.value,current=input.logistics[key]||q;delete input.logistics[key];input.logistics[next]={...current,divisor:Q.CHANNELS[next][1]};if(input.scenario.channel===key)input.scenario.channel=next;quoteControls();changed();});
 const price=document.createElement('input');price.type='number';price.min='0';price.step='any';price.placeholder='元/kg';price.value=q.pricePerKg??'';price.dataset.path='logistics.'+key+'.pricePerKg';price.setAttribute('aria-label',Q.CHANNELS[key][0]+'单价（元/kg）');
 const priceBox=document.createElement('label');priceBox.className='field quote-price';const caption=document.createElement('span');caption.textContent='单价（元/kg）';const error=document.createElement('small');error.className='field-error';error.id='err-logistics-'+key;price.setAttribute('aria-describedby',error.id);priceBox.append(caption,price,error);
 price.addEventListener('input',()=>{if(!input.logistics[key])input.logistics[key]={...q};set('logistics.'+key+'.pricePerKg',price.value===''?null:price.value);changed();});
 const remove=document.createElement('button');remove.type='button';remove.className='remove';remove.textContent='删除';remove.setAttribute('aria-label','删除'+Q.CHANNELS[key][0]+'报价');remove.addEventListener('click',()=>{delete input.logistics[key];if(input.scenario.channel===key)input.scenario.channel=null;quoteControls();changed();});
 const channelBox=document.createElement('label');channelBox.className='field';channelBox.textContent='渠道';channelBox.append(select);row.append(channelBox,priceBox,remove);$('quotes').append(row);
 if(entries.length)field('logistics.'+key+'.divisor',Q.CHANNELS[key][0]+'体积系数',{container:'freight-advanced'});
 }
 $('add-quote').disabled=Object.keys(input.logistics||{}).length>=Object.keys(Q.CHANNELS).length;
}
function controls(){
 for(const id of ['fields','defaults','advanced'])$(id).replaceChildren();
 field('scenario.purchaseCny','采购成本（元 / 销售包装）',{hint:'包含一个完整销售包装；多件装填整包成本'});
 field('scenario.returnRate','预计退货率（%）',{percent:true,max:99.99,hint:'填 0 表示无退货，留空表示尚未提供'});
 field('scenario.adRatio','广告占比（%）',{percent:true,container:'defaults'});
 field('scenario.unsellableRatio','退货不可售（%）',{percent:true,max:100,container:'defaults'});
 field('scenario.ageDays','仓储天数',{container:'defaults'});
 field('product.price','公开售价（'+input.product.currency+'）',{container:'advanced'});
 field('product.variant','当前变体 / 规格',{type:'text',container:'advanced'});
 field('product.category','商品类目',{options:{...categories,...(input.product.category&&!categories[input.product.category]?{[input.product.category]:input.product.category}:{})},container:'advanced'});
 field('product.packQuantity','每销售包装件数',{step:'1',container:'advanced'});
 for(let i=0;i<3;i++)field('product.packaging.cm.'+i,['包装长','包装宽','包装高'][i]+'（cm）',{container:'advanced'});
 field('product.packaging.kg','包装重量（kg）',{container:'advanced'});
 field('product.packaging.basis','尺寸重量依据',{options:{package:'销售包装资料',proxy:'商品尺寸 / 净重近似'},container:'advanced'});
 quoteControls();
 const productMissing=Q.validate(input).some(x=>x.path.startsWith('product.'));if(productMissing)$('product-details').open=true;
}
function showIssues(issues){
 const ruleIssues=issues.filter(x=>x.kind==='rules'||x.path.startsWith('fx')||x.path==='product.site'||x.path==='product.asin');
 const userIssues=issues.filter(x=>!ruleIssues.includes(x));
 $('errors').classList.toggle('hidden',!ruleIssues.length);$('errors').innerHTML=ruleIssues.length?'<strong>平台资料待补充</strong><p>这些费用由 Codex 查询。当前结果未按零费用计算；已填写内容仍会保存。</p><ul>'+ruleIssues.map(x=>'<li>'+esc(labelFor(x.path))+'：'+esc(x.message)+'</li>').join('')+'</ul>':'';
 $('intake-summary').textContent=userIssues.length?'还需补齐 '+[...new Set(userIssues.map(x=>labelFor(x.path)))].join('、'):'经营参数已齐全，修改后同步更新结果';
 document.querySelectorAll('.field-error').forEach(x=>x.textContent='');document.querySelectorAll('[data-path]').forEach(el=>{const issue=userIssues.find(x=>x.path===el.dataset.path||el.dataset.path.startsWith(x.path+'.'));el.setAttribute('aria-invalid',issue?'true':'false');if(issue){const note=el.parentElement.querySelector('.field-error');if(note)note.textContent=issue.message;}});
 $('quote-hint').classList.toggle('negative',userIssues.some(x=>x.path==='logistics'));
 $('product-summary').textContent='已读取：售价 '+(input.product.price??'待补')+' '+input.product.currency+'；包装 '+(input.product.packaging.cm||[]).map(x=>x??'—').join(' × ')+' cm，'+(input.product.packaging.kg??'—')+' kg';
}
function editable(){const p=input.product;return E.clone({product:{price:p.price,category:p.category,packQuantity:p.packQuantity,variant:p.variant,packaging:{cm:[0,1,2].map(i=>p.packaging.cm?.[i]??null),kg:p.packaging.kg,basis:p.packaging.basis}},scenario:input.scenario,logistics:input.logistics});}
function status(message,bad=false){$('save-status').textContent=message;$('save-status').classList.toggle('negative',bad);}
function changed(){editVersion++;render();if(session){status(conflict?'版本冲突：请先导出当前参数，再刷新读取最新草稿':'尚未保存',conflict);clearTimeout(timer);timer=setTimeout(save,500);}else status('离线预览：修改仅保留在本页，可导出参数');}
async function save(){
 clearTimeout(timer);if(!session){render();status('离线预览：请导出参数保存修改');return;}if(saving||conflict)return;if(!token){status('保存失败：会话已失效，请重新运行 ui 命令',true);return;}
 const version=editVersion,payload=editable();saving=true;saveFailed=false;status('保存中…');
 try{const response=await fetch('/api/save',{method:'POST',signal:AbortSignal.timeout(15000),headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({revision,editable:payload})});const body=await response.json();if(response.status===409){conflict=true;throw Error('另一页面已修改此任务，请先导出当前参数，再刷新读取最新草稿');}if(!response.ok)throw Error(body.error||'本地服务无法保存，请重试');revision=body.revision;savedVersion=version;status((body.result?.scenarios?'已保存':'草稿已保存')+' · '+new Date(body.savedAt||Date.now()).toLocaleTimeString('zh-CN'));}
 catch(e){saveFailed=true;status(e.message.startsWith('保存失败')?e.message:'保存失败：'+e.message,true);}
 finally{saving=false;if(!saveFailed&&editVersion>savedVersion)save();}
}
function render(){const start=performance.now();result=Q.calculate(input);$('title').textContent=input.product.title;$('identity').textContent=[input.product.site,input.product.asin,input.product.referenceRole,typeof input.product.variant==='string'?input.product.variant:'',input.product.packQuantity+' 件/销售包装','每'+input.product.salesUnit].filter(Boolean).join(' · ');
const estimatedReturns=Number(input.scenario.returnRate)>0&&input.feePack?.returns?.some(x=>x.estimated&&(!x.categories||x.categories.includes(input.product.category)));$('basis-badge').textContent=estimatedReturns?'含第三方费用估计':input.product.packaging.basis==='proxy'?'含近似包装参数':'选品前期估算';$('basis-summary').textContent='默认值：广告 10%、退货不可售 20%、仓储 90 天。'+(input.product.packaging.basis==='proxy'?'估计值：包装采用商品尺寸或净重近似。':'包装：使用已取得的销售包装资料。')+(estimatedReturns?'费用估计：见下方退货费来源说明。':'')+'未包含项：单独列于计算口径中。';const issues=[...new Map([...(result.missingItems||[]),...(Q.preflight?.(input)||[])].map(x=>[x.path+'|'+x.message,x])).values()];showIssues(issues);const valid=!!result.scenarios&&!issues.length;$('results').classList.toggle('hidden',!valid);$('empty').classList.toggle('hidden',valid);
if(result.scenarios){const s=result.scenarios;for(const season of ['low','peak']){const x=s[season];$(season+'-profit').textContent=money(x.metrics.grossProfit);$(season+'-profit').classList.toggle('negative',Number(x.metrics.grossProfit)<0);$(season+'-margin').textContent=pct(x.metrics.margin);$(season+'-storage').textContent=money(x.totals.S);}const delta=E.d(s.difference);$('delta-label').textContent=delta.isZero()?'本站点基础仓储无季节差价':'旺季仓储使每单位毛利'+(delta.lt(0)?'减少':'增加');$('delta-value').textContent=money(delta.abs())+' · '+Math.abs((Number(s.peak.metrics.margin)-Number(s.low.metrics.margin))*100).toFixed(2)+' 个百分点';
$('channels').innerHTML=Object.entries(result.channels).map(([k,x])=>'<tr class="'+(k===result.channel?'active':'')+'"><td><button class="pick" data-channel="'+esc(k)+'">'+esc(Q.CHANNELS[k][0])+(k===result.channel?' · 当前':'')+'</button></td><td>'+money(x.low.totals.H)+'</td><td>'+money(x.low.metrics.grossProfit)+'</td><td>'+money(x.peak.metrics.grossProfit)+'</td></tr>').join('');$('channels').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{set('scenario.channel',b.dataset.channel);changed();}));
const labels={C:'采购',H:'头程',M:'佣金',F:'FBA 配送',S:'基础仓储',A:'广告',D:'退货损失分摊'};const max=Math.max(...Object.values(s.peak.totals).map(Number),1);$('costs').innerHTML='<div class="cost-row cost-head"><span>费用</span><span></span><span>淡季</span><span>旺季</span></div>'+Object.entries(labels).map(([k,v])=>'<div class="cost-row"><span>'+v+'</span><div class="bar"><i style="width:'+Math.min(100,Number(s.peak.totals[k])/max*100)+'%"></i></div><span>'+money(s.low.totals[k])+'</span><span>'+money(s.peak.totals[k])+'</span></div>').join('');$('economics').textContent='净收入 '+money(s.low.metrics.revenue)+' / '+input.product.salesUnit+'；保本广告占比：淡季 '+pct(s.low.metrics.adBreakEven)+'，旺季 '+pct(s.peak.metrics.adBreakEven)+'。';}
$('notes').innerHTML=[...(result.notes||input.notes||[]),input.fixture?'当前为人工验收数据，不能作为真实商品结论。':''].filter(Boolean).map(x=>'<li>'+esc(x)+'</li>').join('');$('excluded').innerHTML=Q.EXCLUDED.map(x=>'<li>本测算未包含：'+esc(x)+'</li>').join('');const urls=[input.product.url,input.fx?.source?.locator,...(input.feePack?.sources||[])].filter(Boolean);$('sources').innerHTML=[...new Set(urls)].map(u=>{try{const url=new URL(u);return /^https?:$/.test(url.protocol)?'<a class="source-link" href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+esc(u)+'</a>':'';}catch{return '';}}).join('');$('metadata').textContent=JSON.stringify({defaults:Q.DEFAULTS,fieldMeta:input.fieldMeta,package:input.product.packaging,variant:input.product.variant,feeCheckedAt:input.feePack?.checkedAt,fx:input.fx,detail:result.scenarios?.low.detail},null,2);const elapsed=performance.now()-start;window.lastRecalcMs=elapsed;$('live').textContent='本地更新 '+elapsed.toFixed(1)+' ms · '+(issues.length?'存在缺项':'已同步两种情景');}

$('add-quote').addEventListener('click',()=>{if(!Object.keys(input.logistics).length)input.logistics.sea={pricePerKg:null,divisor:'6000',currency:'CNY'};const key=['sea','air','express','fastSea','slowSea'].find(k=>!input.logistics[k]);if(!key)return;input.logistics[key]={pricePerKg:null,divisor:Q.CHANNELS[key][1],currency:'CNY'};quoteControls();changed();});
if(!session)$('save').textContent='重新计算';
$('save').addEventListener('click',()=>{render();save();});
$('reset').addEventListener('click',()=>{input=E.clone(original);controls();changed();});
$('download').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(input,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=input.product.asin+'-quick-v2.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('print').addEventListener('click',()=>window.print());
window.addEventListener('beforeunload',event=>{if(session&&(editVersion>savedVersion||saving)){event.preventDefault();event.returnValue='';}});
controls();render();status(session?(result.scenarios?'已读取保存的结果':'已读取保存的草稿'):'离线报告：修改仅保留在本页，可导出参数');
if(session){setInterval(()=>{if(token)fetch('/api/state',{headers:{'X-Session-Token':token}}).catch(()=>{});},60000);}
})();
