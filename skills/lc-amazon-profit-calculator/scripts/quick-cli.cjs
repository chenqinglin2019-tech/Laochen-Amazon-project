'use strict';
const fs=require('node:fs'),path=require('node:path'),E=require('./engine.js'),Q=require('./quick.js'),Cache=require('./cache.cjs');
const ROOT=path.join(__dirname,'..');
function report(input,session=null){const {safeJSON,privacy}=require('./cli.cjs');privacy(input);let html=fs.readFileSync(path.join(ROOT,'assets/quick-report.html'),'utf8');for(const [token,file]of [['__DECIMAL__','vendor/decimal.js'],['__ENGINE__','scripts/engine.js'],['__QUICK__','scripts/quick.js'],['__APP__','assets/quick-report-app.js']])html=html.replace(token,()=>fs.readFileSync(path.join(ROOT,file),'utf8'));return html.replace('__DATA__',()=>safeJSON(input)).replace('__SESSION__',()=>safeJSON(session));}
function write(file,x){fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,typeof x==='string'?x:JSON.stringify(x,null,2)+'\n');}
async function main(args){const [command,file,out,...flags]=args;const offline=flags.includes('--offline')||out==='--offline';
 if(command==='refresh'){const site=file;if(!E.SITES[site])throw Error('用法：refresh US [output.json]');const r=await Cache.resources(site);if(out&&out!=='--offline')write(out,r);else console.log(JSON.stringify({site,...r.cache},null,2));return;}
 if(!file)throw Error('用法：prepare <bundle.json> <input.json> | run <bundle-or-v2.json> <output-dir> [--offline]');
 const input=await prepareInput(file,{offline}),resources={cache:input.cache},start=performance.now();
 const result=Q.calculate(input);
 if(command==='prepare'){if(!out)throw Error('请指定 input.json 路径');write(out,input);console.log(JSON.stringify({input:out,missingItems:result.missingItems,cache:input.cache},null,2));if(result.missingItems.length)process.exitCode=2;return;}
 if(command!=='run')throw Error('未知快速命令');if(!out||out.startsWith('--'))throw Error('请指定输出目录');
 write(path.join(out,'input.json'),input);write(path.join(out,'report.html'),report(input));result.timing={localComputeAndReportMs:performance.now()-start,networkMs:resources.cache.networkMs||0};write(path.join(out,'result.json'),result);
 console.log(JSON.stringify({status:result.status,output:path.resolve(out),missingItems:result.missingItems,timing:result.timing},null,2));if(!result.scenarios||result.missingItems.length)process.exitCode=2;
}
async function prepareInput(file,{offline=false}={}){
 const bundle=JSON.parse(fs.readFileSync(file,'utf8'));require('./cli.cjs').privacy(bundle);
 const now=bundle.asOf||new Date().toISOString(),raw=Q.unwrap(bundle.raw),identity=bundle.schemaVersion===Q.VERSION?bundle.product:E.parseIdentity(bundle.url||bundle.product?.url||raw.asinUrl||raw.asin,bundle.product?.site||(raw.marketplace==='GB'?'UK':raw.marketplace));
 // An explicitly frozen v2 input is reproducible; new collection bundles use current caches.
 const resources=bundle.schemaVersion===Q.VERSION?{feePack:bundle.feePack,fx:bundle.fx,cache:{mode:'frozen',networkMs:0}}:await Cache.resources(identity.site,{now,offline});
 const input=Q.prepare(bundle,resources);input.cache=resources.cache;
 if(resources.cache.rates&&['review-required','fetch-failed'].includes(resources.cache.rates))input.notes.push('已自动检查费率来源，需要 Agent 复核变更；本次沿用标注日期的缓存作条件参考。');
 return input;
}
module.exports={main,report,prepareInput};
if(require.main===module)main(process.argv.slice(2)).catch(e=>{console.error(e.message);process.exitCode=1;});
