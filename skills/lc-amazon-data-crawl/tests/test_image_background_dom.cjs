const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const src = fs.readFileSync(require('node:path').join(__dirname, '../scripts/image_background_dom.js'), 'utf8');
function el(text='', attrs={}) {
  return {innerText:text, textContent:text, id:'', className:'', parentElement:null,
    getAttribute:k=>attrs[k]||null, getClientRects:()=>[1], closest:()=>null,
    querySelector:()=>null,querySelectorAll:()=>[]};
}
function setup() {
  const root=el(), body=el(), image=el('',{'data-old-hires':'https://example.com/main.jpg'}), selected=el();
  selected.src='https://example.com/selected.jpg';
  const nodes={'#landingImage,#imgTagWrapperId img,#main-image':image,'ul.maintain-height .selected img':selected};
  const controls=[],cards=[];
  root.querySelectorAll=s=>s==='button,a,.el-dropdown-menu__item'?controls:[];
  const document={body,title:'Amazon',readyState:'complete',documentElement:{dataset:{}},scrollingElement:{scrollBy(){this.calls=(this.calls||0)+1;}},
    querySelector:s=>nodes[s]||null,
    querySelectorAll:s=>s==='#seller-sprite-extension-app'?[root]:s.includes('article.cellContainer')?cards:[]};
  const location={href:'https://www.amazon.com/dp/B000000001',pathname:'/dp/B000000001',assign(url){this.assigned=url;}};
  const timers=[];
  const context={setTimeout:fn=>timers.push(fn),document,location,URL,innerHeight:1000,getComputedStyle:()=>({visibility:'visible'})};
  vm.createContext(context);vm.runInContext(src,context);
  return {context,document,location,nodes,controls,cards,timers,run:args=>context.imageBackgroundDom({action:'snapshot',...args})};
}
{
  const f=setup();assert.equal(f.run().source_image,'https://example.com/selected.jpg');
  assert.equal(f.run().asin,'B000000001');
  f.run({action:'mark',id:'owned'});
  assert.ok(f.run({action:'navigate',documentId:'other',url:'bad'}).error);
  assert.equal(f.location.assigned,undefined);
  assert.ok(f.run({action:'scroll',expectedUrl:'https://www.amazon.com/s?k=user'}).error);
  assert.equal(f.document.scrollingElement.calls,undefined);
  f.run({action:'navigate',documentId:'owned',expectedUrl:f.location.href,url:'https://www.amazon.com/stylesnap?q=x'});
  assert.equal(f.location.assigned,undefined);
  assert.equal(f.timers.length,1);
  f.timers[0]();
  assert.equal(f.location.assigned,'https://www.amazon.com/stylesnap?q=x');
}
{
  const f=setup();f.controls.push(el('登录'));assert.equal(f.run().logged_in,false);
  f.controls.push(el('退出登录'));assert.equal(f.run().logged_in,true);
  f.controls[1].getClientRects=()=>[];assert.equal(f.run().logged_in,false);
}
{
  const f=setup();f.document.body.innerText='No styles found';
  assert.equal(f.run().empty,false); // Product page text cannot prove empty search results.
  f.location.href='https://www.amazon.com/stylesnap?q=x';f.location.pathname='/stylesnap';
  assert.equal(f.run().empty,true);
}
{
  const f=setup();f.location.href='https://www.amazon.com/stylesnap?q=x';f.location.pathname='/stylesnap';
  function card(asin){const c=el('Product',{'data-asin':asin}), img=el('',{src:'https://m.media-amazon.com/images/I/a.jpg'});
    const link={href:'https://www.amazon.com/dp/'+asin};
    c.querySelectorAll=s=>s==='a[href]'?[link]:s==='img'?[img]:[];
    return c;}
  const a=card('B000000002'),dup=card('B000000002'),cart=card('B000000003'),b=card('B000000004');
  cart.parentElement={id:'ewc-content',className:'',parentElement:null};
  f.cards.push(a,dup,cart,b);
  assert.deepEqual(Array.from(f.run().cards,x=>x.asin),['B000000002','B000000004']);
  const injected=card('B000000005');injected.closest=()=>({});f.cards.push(injected);
  assert.equal(f.run().cards.length,2);
}

{
  const f=setup();
  f.document.documentElement=null;
  const loading=f.run();
  assert.equal(loading.ready,false);
  assert.equal(loading.document_loading,true);
  assert.equal(loading.error,undefined);
  assert.ok(f.run({documentId:'owned'}).error);
  assert.ok(f.run({expectedUrl:'https://www.amazon.com/dp/OTHER'}).error);
}

console.log('Image DOM fixtures: 5 groups passed');
{
  const f=setup();f.run({action:'mark',id:'owned'});
  const expected=f.location.href+'?psc=1';
  f.location.href='https://www.amazon.com/Product-Title/dp/B000000001/ref=abc?ref_=test';
  assert.equal(f.run({expectedUrl:expected,documentId:'owned'}).adopted_url_rewrite,true);
  assert.ok(f.run({action:'scroll',expectedUrl:expected,documentId:'owned'}).error);
  assert.ok(f.run({expectedUrl:expected,documentId:'other'}).error);
  f.location.href='https://www.amazon.com/dp/B000000002';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  f.location.href='https://www.amazon.com/dp/B000000001?smid=OTHER';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  f.location.href='https://evil.example/dp/B000000001';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
}
{
  const f=setup();f.run({action:'mark',id:'owned'});
  const expected='https://www.amazon.com/stylesnap?q=https%3A%2F%2Fexample.com%2Fa.jpg';
  f.location.href='https://www.amazon.com/products?modes=stylesnap&q=https%3A%2F%2Fexample.com%2Fa.jpg&ref_=tracking';f.location.pathname='/products';
  assert.equal(f.run({expectedUrl:expected,documentId:'owned'}).adopted_url_rewrite,true);
  f.location.href+='&page=2';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  f.location.href='https://www.amazon.com/stylesnap?q=other';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
}
console.log('Additional canonical URL fixtures: 2 groups passed');
{
  const f=setup();f.run({action:'mark',id:'owned'});
  f.nodes['input#ASIN']={value:'B000000001'};
  const expected='https://www.amazon.com/dp/B000000001?psc=1';
  f.location.href='https://www.amazon.com/dp/B000000001?th=1';
  assert.equal(f.run({expectedUrl:expected,documentId:'owned'}).adopted_url_rewrite,true);
  assert.ok(f.run({action:'navigate',expectedUrl:expected,documentId:'owned',url:expected}).error);
  assert.equal(f.timers.length,0);
  assert.ok(f.run({expectedUrl:expected,documentId:'changed'}).error);
  f.nodes['input#ASIN'].value='B000000002';
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  delete f.nodes['input#ASIN'];
  assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  f.nodes['input#ASIN']={value:'B000000001'};
  for (const query of ['th=2','th=1&th=1','th=1&smid=OTHER']) {
    f.location.href='https://www.amazon.com/dp/B000000001?'+query;
    assert.ok(f.run({expectedUrl:expected,documentId:'owned'}).error);
  }
  f.location.href=expected;
  assert.equal(f.run({expectedUrl:'https://www.amazon.com/dp/B000000001?th=1',documentId:'owned'}).adopted_url_rewrite,true);
  f.location.href='https://www.amazon.com/stylesnap?q=x&th=1';f.location.pathname='/stylesnap';
  assert.ok(f.run({expectedUrl:'https://www.amazon.com/stylesnap?q=x',documentId:'owned'}).error);
  f.location.href='https://www.amazon.com/dp/B000000002?token=private#secret';
  const fail=f.run({expectedUrl:expected,documentId:'owned'});
  assert.equal(fail.page_identity.expected_url,expected);
  assert.equal(fail.page_identity.dom_asin,'B000000001');
  assert.equal(fail.page_identity.actual_document,'owned');
  assert.ok(!fail.page_identity.actual_url.includes('private'));
  assert.ok(!fail.page_identity.actual_url.includes('secret'));
}
console.log('Product th=1 rewrite and diagnostic fixtures passed');
