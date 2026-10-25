#!/usr/bin/env node
'use strict';
const fs=require('node:fs');const path=require('node:path');const E=require('./engine.js');
const [command,inputPath,outputPath]=process.argv.slice(2);
function safeJSON(v){return JSON.stringify(v).replace(/</g,'\\u003c').replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029');}
function privacy(v){
  if(!v||typeof v!=='object')return;
  for(const [k,x]of Object.entries(v)){
    if(/^(api[_-]?key|access[_-]?token|refresh[_-]?token|password|cookie|authorization|tax[_-]?(id|number)|vat[_-]?(id|number))$/i.test(k))throw new Error('请先移除私密字段：'+k);
    privacy(x);
  }
}
function report(input){
  if(input.schemaVersion==='2.0')return require('./quick-cli.cjs').report(input);
  privacy(input);const root=path.join(__dirname,'..');
  let html=fs.readFileSync(path.join(root,'assets/report.html'),'utf8');
  for(const [token,body]of [['__DECIMAL__',fs.readFileSync(path.join(root,'vendor/decimal.js'),'utf8')],['__ENGINE__',fs.readFileSync(path.join(__dirname,'engine.js'),'utf8')],['__DECISION__',fs.readFileSync(path.join(__dirname,'decision.js'),'utf8')],['__APP__',fs.readFileSync(path.join(root,'assets/report-app.js'),'utf8')],['__DATA__',safeJSON(input)]])html=html.replace(token,()=>body);
  return html;
}
function main(){
  if(command==='ui')return require('./ui-server.cjs').launch(inputPath,outputPath,{offline:process.argv.includes('--offline')});
  if(['prepare','run','refresh'].includes(command))return require('./quick-cli.cjs').main(process.argv.slice(2));
  if(!['validate','calculate','report','identify'].includes(command))throw new Error('用法：node scripts/cli.cjs identify <URL> [站点] | validate <input.json> | calculate <input.json> [result.json] | report <input.json> <report.html>');
  if(command==='identify'){console.log(JSON.stringify(E.parseIdentity(inputPath,outputPath),null,2));return;}
  const input=JSON.parse(fs.readFileSync(inputPath,'utf8'));privacy(input);
  if(command==='report'){if(!outputPath)throw new Error('请指定 HTML 输出路径');fs.writeFileSync(outputPath,report(input),'utf8');console.log(outputPath);return;}
  if(input.schemaVersion==='2.0'){const result=require('./quick.js').calculate(input),text=JSON.stringify(result,null,2);if(outputPath)fs.writeFileSync(outputPath,text+'\n');else console.log(text);if(!result.scenarios||result.missingItems.length)process.exitCode=2;return;}
  const result=command==='validate'?{missingItems:E.validateBase(input),current:E.calculate(input)}:{...E.calculate(input),scenarioResults:{logistics:E.comparisons(input),sensitivity:E.sensitivity(input)}};
  const text=JSON.stringify(result,null,2);if(outputPath)fs.writeFileSync(outputPath,text+'\n','utf8');else console.log(text);
  if(!E.calculate(input).metrics)process.exitCode=2;
}
if(require.main===module){Promise.resolve().then(main).catch(e=>{console.error(e.message);process.exitCode=1;});}
module.exports={report,safeJSON,privacy};
