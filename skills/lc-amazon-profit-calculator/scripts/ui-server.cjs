'use strict';
// Loopback editor. The durable snapshot is authoritative; derived exports are rebuilt on restart.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),crypto=require('node:crypto');
const {spawn}=require('node:child_process'),Q=require('./quick.js'),{report,prepareInput}=require('./quick-cli.cjs');
const clone=x=>JSON.parse(JSON.stringify(x));
function fault(message,status=400){return Object.assign(new Error(message),{status});}
function object(x){return x!==null&&typeof x==='object'&&!Array.isArray(x);}
function keys(x,allowed){if(!object(x)||Object.keys(x).some(k=>!allowed.includes(k)))throw fault('包含不可编辑的字段');}
function scalar(x){if(x!==null&&typeof x!=='string'&&typeof x!=='number')throw fault('字段格式无效');if(typeof x==='string'&&x.length>1000)throw fault('字段过长');return x;}
function editable(input){const p=input.product;return {product:{price:p.price,category:p.category,packQuantity:p.packQuantity,variant:p.variant,packaging:p.packaging},scenario:input.scenario,logistics:input.logistics};}
function mergeEditable(input,patch){
 keys(patch,['product','scenario','logistics']);const next=clone(input);next.fieldMeta||={};
 const changed=(key,value)=>{next.fieldMeta[key]={origin:'user',note:'HTML 本次修改'};return value;};
 const assign=(dest,src,prefix)=>{for(const[k,v]of Object.entries(src)){scalar(v);if(JSON.stringify(dest[k])!==JSON.stringify(v))dest[k]=changed(prefix+'.'+k,v);}};
 if(patch.scenario){keys(patch.scenario,['purchaseCny','returnRate','adRatio','unsellableRatio','ageDays','channel']);assign(next.scenario,patch.scenario,'scenario');}
 if(patch.product){keys(patch.product,['price','category','packQuantity','variant','packaging']);const{packaging,variant,...rest}=patch.product;assign(next.product,rest,'product');
  if(Object.hasOwn(patch.product,'variant')){if(typeof variant!=='string'&&variant!==null&&JSON.stringify(variant)!==JSON.stringify(input.product.variant))throw fault('变体请使用文字');if(JSON.stringify(variant)!==JSON.stringify(next.product.variant))next.product.variant=changed('product.variant',variant);}
  if(packaging){keys(packaging,['cm','kg','basis']);if(Object.hasOwn(packaging,'basis')&&!['package','proxy'].includes(packaging.basis))throw fault('请选择包装参数依据');const{cm,...other}=packaging;assign(next.product.packaging,other,'product.packaging');if(Object.hasOwn(packaging,'cm')){if(cm!==null&&(!Array.isArray(cm)||cm.length!==3))throw fault('长宽高需三个值');cm?.forEach(scalar);if(JSON.stringify(cm)!==JSON.stringify(next.product.packaging.cm))next.product.packaging.cm=changed('product.packaging.cm',cm);}}
 }
 if(patch.logistics){keys(patch.logistics,Object.keys(Q.CHANNELS));const logistics={};for(const[k,v]of Object.entries(patch.logistics)){keys(v,['pricePerKg','divisor','currency']);for(const value of Object.values(v))scalar(value);logistics[k]={pricePerKg:v.pricePerKg??null,divisor:v.divisor??Q.CHANNELS[k][1],currency:'CNY'};if(v.currency&&v.currency!=='CNY')throw fault('头程使用人民币');if(JSON.stringify(logistics[k])!==JSON.stringify(next.logistics[k]))changed('logistics.'+k,logistics[k]);}next.logistics=logistics;if(!Object.hasOwn(logistics,next.scenario.channel))next.scenario.channel=null;}
 return next;
}
function atomic(file,data){const tmp=file+'.'+crypto.randomBytes(6).toString('hex')+'.tmp';try{fs.writeFileSync(tmp,typeof data==='string'?data:JSON.stringify(data,null,2)+'\n',{mode:0o600});fs.renameSync(tmp,file);}finally{if(fs.existsSync(tmp))fs.unlinkSync(tmp);}}
function persist(out,state){
 const result=Q.calculate(state.input),html=report(state.input);fs.mkdirSync(out,{recursive:true});
 const entries=[['input.json',state.input],['result.json',result],['report.html',html],['ui-state.json',state]];
 const staged=[],committed=[];
 try{
  for(const[name,value]of entries){const file=path.join(out,name);if(fs.existsSync(file)&&!fs.lstatSync(file).isFile())throw Error('输出目标必须是普通文件');const previous=fs.existsSync(file)?fs.readFileSync(file):null;const temp=file+'.'+crypto.randomBytes(6).toString('hex')+'.tmp';staged.push({file,temp,previous});fs.writeFileSync(temp,typeof value==='string'?value:JSON.stringify(value,null,2)+'\n',{mode:0o600});}
  for(const entry of staged){fs.renameSync(entry.temp,entry.file);committed.push(entry);}
 }catch(e){for(const entry of committed.reverse()){if(entry.previous===null)fs.unlinkSync(entry.file);else atomic(entry.file,entry.previous.toString());}throw e;}
 finally{for(const entry of staged){if(fs.existsSync(entry.temp))fs.unlinkSync(entry.temp);}}
 return result;
}
async function startSession(initial,out,{idleMs=30*60*1000,save=persist,token=crypto.randomBytes(32).toString('hex')}={}){
 out=path.resolve(out);const stateFile=path.join(out,'ui-state.json');let state;
 if(fs.existsSync(stateFile)){state=JSON.parse(fs.readFileSync(stateFile));if(state.input.product.site!==initial.product.site||state.input.product.asin!==initial.product.asin)throw fault('输出目录已有另一商品，请使用新目录');}
 else state={sessionVersion:1,revision:0,input:initial,savedAt:new Date().toISOString()};
 let currentResult=save(out,state),lastActivity=Date.now(),queue=Promise.resolve(),origin;
 const server=http.createServer(async(req,res)=>{
  const send=(status,data,type='application/json')=>{res.writeHead(status,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'});res.end(type==='application/json'?JSON.stringify(data):data);};
  try{
   if(req.headers.host!==new URL(origin).host)throw fault('Host 不匹配',403);
   if(req.headers.origin&&req.headers.origin!==origin)throw fault('仅允许同源访问',403);
   if(req.method==='GET'&&req.url==='/'){lastActivity=Date.now();send(200,report(state.input,{revision:state.revision}),'text/html');return;}
   if(req.headers['x-session-token']!==token)throw fault('会话令牌无效',403);
   if(req.method==='GET'&&req.url==='/api/state'){lastActivity=Date.now();send(200,{...state,result:currentResult});return;}
   if(req.method!=='POST'||req.url!=='/api/save'){send(404,{error:'不存在的接口'});return;}
   if(req.headers.origin!==origin)throw fault('保存需要同源请求',403);
   if(!/^application\/json(?:;|$)/i.test(req.headers['content-type']||''))throw fault('需要 JSON 请求',415);
   let size=0,parts=[];for await(const chunk of req){size+=chunk.length;if(size>128*1024)throw fault('请求过大',413);parts.push(chunk);}let body;try{body=JSON.parse(Buffer.concat(parts).toString());}catch{throw fault('JSON 无效');}keys(body,['revision','editable']);lastActivity=Date.now();
   const operation=queue.then(()=>{if(!Number.isSafeInteger(body.revision)||body.revision!==state.revision)throw fault('页面版本已变化，请刷新后重新修改；当前输入未覆盖已保存版本',409);const next={sessionVersion:1,revision:state.revision+1,input:mergeEditable(state.input,body.editable),savedAt:new Date().toISOString()};const result=save(out,next);state=next;currentResult=result;return {revision:state.revision,result,savedAt:state.savedAt};});
   queue=operation.catch(()=>{});send(200,await operation);
  }catch(e){send(e.status||500,{error:e.status?e.message:'保存失败，请保留当前输入并重试'});}
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});origin='http://127.0.0.1:'+server.address().port;
 const timer=setInterval(()=>{if(Date.now()-lastActivity>=idleMs)server.close();},Math.min(idleMs,60000));timer.unref();server.on('close',()=>clearInterval(timer));
 return {server,origin,token,url:origin+'/#token='+token,out,close:()=>new Promise(resolve=>server.close(resolve))};
}
function runtimePaths(out){const dir=path.join(os.tmpdir(),'lc-amazon-profit-ui');fs.mkdirSync(dir,{recursive:true,mode:0o700});const base=path.join(dir,crypto.createHash('sha256').update(path.resolve(out)).digest('hex'));return {info:base+'.json',lock:base+'.lock'};}
function sourceIdentity(file){const source=JSON.parse(fs.readFileSync(file)),E=require('./engine.js'),raw=Q.unwrap(source.raw);require('./cli.cjs').privacy(source);if(source.schemaVersion&&source.schemaVersion!==Q.VERSION)throw Error('ui 使用 v2 输入；旧 v1 请用原 calculate/report 命令');return source.schemaVersion===Q.VERSION?source.product:E.parseIdentity(source.url||source.product?.url||raw.asinUrl||raw.asin,source.product?.site||(raw.marketplace==='GB'?'UK':raw.marketplace));}
async function launch(file,out,{offline=false}={}){
 if(!file||!out||out.startsWith('--'))throw Error('用法：ui <bundle或v2-input.json> <任务输出目录> [--offline]');
 const paths=runtimePaths(out);let prior;
 try{prior=JSON.parse(fs.readFileSync(paths.info));const response=await fetch(prior.origin+'/api/state',{headers:{'X-Session-Token':prior.token},signal:AbortSignal.timeout(1500)});if(response.ok){const existing=await response.json();const identity=sourceIdentity(file);if(identity.asin!==existing.input.product.asin||identity.site!==existing.input.product.site)throw fault('输出目录正在用于另一商品，请使用新目录',409);console.log(JSON.stringify({status:'ready',reused:true,url:prior.origin+'/#token='+prior.token,output:path.resolve(out)}));return;}}catch(e){if(e.status===409)throw e;}
 const child=spawn(process.execPath,[__filename,path.resolve(file),path.resolve(out),...(offline?['--offline']:[])],{detached:true,stdio:['ignore','pipe','pipe']});let ready='',errors='';child.stderr.on('data',x=>{errors+=x;});
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{child.kill();reject(Error('页面服务启动超时：'+errors));},120000);child.once('error',e=>{clearTimeout(timer);reject(e);});child.once('exit',code=>{clearTimeout(timer);if(!ready.includes('\n'))reject(Error(errors||'页面服务退出 '+code));});child.stdout.on('data',chunk=>{ready+=chunk;if(ready.includes('\n')){clearTimeout(timer);console.log(ready.trim());child.stdout.destroy();child.stderr.destroy();child.unref();resolve();}});});
}
async function serve(){const[file,out,...flags]=process.argv.slice(2),paths=runtimePaths(out);let lock;
 try{lock=fs.openSync(paths.lock,'wx',0o600);}catch(e){if(e.code!=='EEXIST')throw e;let alive=false;try{process.kill(Number(fs.readFileSync(paths.lock,'utf8')),0);alive=true;}catch{}if(alive)throw Error('同一任务的服务正在启动，请稍后重试 ui');fs.unlinkSync(paths.lock);lock=fs.openSync(paths.lock,'wx',0o600);}
 fs.writeFileSync(lock,String(process.pid));fs.closeSync(lock);let session;
 const cleanup=()=>{try{fs.unlinkSync(paths.lock);}catch{}try{fs.unlinkSync(paths.info);}catch{}};
 try{const existed=fs.existsSync(path.join(out,'ui-state.json'));const identity=sourceIdentity(file);const initial=existed?{product:identity}:await prepareInput(file,{offline:flags.includes('--offline')});session=await startSession(initial,out);atomic(paths.info,{origin:session.origin,token:session.token,pid:process.pid});session.server.on('close',cleanup);process.once('SIGTERM',()=>session.server.close());process.once('SIGINT',()=>session.server.close());console.log(JSON.stringify({status:'ready',reused:existed,url:session.url,output:session.out}));}catch(e){cleanup();throw e;}
}
module.exports={startSession,launch,mergeEditable,editable,persist};
if(require.main===module)serve().catch(e=>{console.error(e.message);process.exitCode=1;});
