'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const E=require('./engine.js');
const ROOT=path.join(__dirname,'..'), FX_URL='https://open.er-api.com/v6/latest/CNY';
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
async function read(p){try{return JSON.parse(await fs.readFile(p,'utf8'));}catch(e){if(e.code==='ENOENT')return null;throw e;}}
async function save(p,x){await fs.mkdir(path.dirname(p),{recursive:true});const tmp=p+'.'+process.pid+'.tmp';await fs.writeFile(tmp,JSON.stringify(x,null,2)+'\n');await fs.rename(tmp,p);}
async function fetchBytes(url,fetcher=fetch){const u=new URL(url);if(u.protocol!=='https:'||/^(localhost|127\.|0\.|\[::1\])/.test(u.hostname))throw Error('只允许公开 HTTPS 来源');const r=await fetcher(url,{signal:AbortSignal.timeout(20000),headers:{'User-Agent':'AmazonProfitSkill/2.0 (rate verification)'}});if(!r.ok)throw Error('HTTP '+r.status);const b=Buffer.from(await r.arrayBuffer());if(b.length>10000000)throw Error('来源超过 10MB');return {body:b,url:r.url||url};}
async function refreshFx(existing,now,fetcher){
 if(existing&&Date.parse(now)-Date.parse(existing.checkedAt||existing.asOf)<86400000)return {value:existing,status:'cached'};
 try{const {body}=await fetchBytes(FX_URL,fetcher),x=JSON.parse(body);if(x.result!=='success'||x.base_code!=='CNY')throw Error('汇率响应不完整');
 const currencies=[...new Set(Object.values(E.SITES).map(x=>x[1]))],rates={CNY:'1',CNH:'1'};
 for(const c of currencies){const v=E.d(x.rates[c]);if(!v.gt(0))throw Error('无效汇率 '+c);rates[c]=new E.Decimal(1).div(v).toString();}
 const asOf=new Date(x.time_last_update_unix*1000).toISOString();if(!Number.isFinite(Date.parse(asOf)))throw Error('无效报价日期');
 return {status:'updated',value:{kind:'CNY',asOf,checkedAt:now,cnhPerCurrency:rates,source:{type:'thirdParty',locator:FX_URL,at:now},note:'公开 CNY 参考汇率；字段名 cnhPerCurrency 为向后兼容，不代表 CNH'}};
 }catch(e){return {status:'failed',error:e.message,value:existing};}
}
async function refreshRates(pack,now,fetcher){
 if(!pack)return {status:'missing',value:null};
 if(pack.invalidated||pack.validUntil&&Date.parse(now)>Date.parse(pack.validUntil+'T23:59:59Z'))return {status:'invalidated',value:pack};
 if(Date.parse(now)-Date.parse(pack.checkedAt)<7*86400000)return {status:'cached',value:pack};
 const urls=[...new Set([pack.source.locator,...(pack.sources||[])])];
 const responses=await Promise.allSettled(urls.map(async url=>{const x=await fetchBytes(url,fetcher);return {url,sha256:sha(x.body),bytes:x.body.length,redirectedTo:x.url};}));
 const observations=responses.map((r,i)=>r.status==='fulfilled'?r.value:{url:urls[i],error:r.reason.message});
 const unchanged=observations.every(x=>!x.error&&pack.sourceHashes?.[x.url]===x.sha256);
 if(unchanged)return {status:'unchanged',value:{...pack,checkedAt:now},observations};
 // Fetching successfully does not prove tariffs are unchanged. Agent reviews sources before committing a new pack.
 return {status:observations.some(x=>x.error)?'fetch-failed':'review-required',value:pack,observations};
}
async function resources(site,{now=new Date().toISOString(),offline=false,root=ROOT,fetcher=fetch}={}){
 if(!E.SITES[site])throw Error('未知站点');
 const packPath=path.join(root,'data/rates',site+'.json'),fxPath=path.join(root,'data/fx.json');
 const [pack,fx]=await Promise.all([read(packPath),read(fxPath)]);
 if(offline)return {feePack:pack,fx,cache:{mode:'offline',networkMs:0}};
 const start=performance.now();const [rateUpdate,fxUpdate]=await Promise.all([refreshRates(pack,now,fetcher),refreshFx(fx,now,fetcher)]);
 if(rateUpdate.status==='unchanged')await save(packPath,rateUpdate.value);
 if(fxUpdate.status==='updated')await save(fxPath,fxUpdate.value);
 if(rateUpdate.observations)await save(path.join(root,'data/pending',site+'.json'),{checkedAt:now,...rateUpdate,value:undefined});
 return {feePack:rateUpdate.value,fx:fxUpdate.value,cache:{networkMs:performance.now()-start,rates:rateUpdate.status,fx:fxUpdate.status,errors:[rateUpdate.error,fxUpdate.error].filter(Boolean)}};
}
module.exports={resources,refreshRates,refreshFx,save,sha};
