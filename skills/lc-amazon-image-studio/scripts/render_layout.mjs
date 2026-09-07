#!/usr/bin/env node
// Trusted renderer entrypoint. User content is assigned with textContent, never HTML.
import path from 'node:path';
import {pathToFileURL} from 'node:url';

// Decode stdin before async iteration. Without this, a multi-byte Chinese
// character split over two pipe chunks can become two replacement glyphs.
process.stdin.setEncoding('utf8');
let raw='';
for await (const chunk of process.stdin) raw+=chunk;
const parseStart=performance.now();
const request=JSON.parse(raw);
const measureOnly=request.mode==='measure';
const payloadParseSeconds=(performance.now()-parseStart)/1000;
const batchStart=performance.now();
const {chromium}=await import(pathToFileURL(request.playwright));
const launchStart=performance.now();
const browser=await chromium.launch({executablePath:request.chromium,headless:true,args:['--disable-gpu']});
const browserLaunchSeconds=(performance.now()-launchStart)/1000;
const results={};

try {
 const page=await browser.newPage({viewport:{width:2000,height:2000},deviceScaleFactor:1});
 await page.route('**/*',route=>route.abort());
 const fontCSS=request.fonts.map(face=>`@font-face{font-family:"LC${face.family}";font-style:normal;font-weight:${face.weight};font-display:block;src:url("${face.uri}")}`).join('\n');
 const fontStart=performance.now();
 await page.setContent('<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\';img-src data:;font-src data:;style-src \'unsafe-inline\'">'+
  `<style>${fontCSS}
   *{box-sizing:border-box}html,body{margin:0;padding:0}body{font-synthesis:none}
   #stage{position:relative;overflow:hidden}#base{position:absolute;inset:0;width:100%;height:100%}
   .text{position:absolute;white-space:pre-wrap;word-break:normal;overflow-wrap:normal;line-break:strict;hyphens:manual;font-feature-settings:"locl" 1;letter-spacing:-.018em}
   .headline{font-weight:700;line-height:1.14}.body{font-weight:400;line-height:1.23;letter-spacing:0}.label{font-weight:700;line-height:1.25;letter-spacing:0}
   .text-group{position:absolute;display:flex;flex-direction:column;align-items:stretch}
   .text-group .text{position:relative;left:auto;top:auto;width:100%;height:auto}
   .faq-pair{display:flex;flex-direction:column}.surface{position:absolute;pointer-events:none}svg{overflow:visible}.icon{position:absolute}
   .evidence{position:absolute;object-fit:contain}.evidence.circle{object-fit:cover;border-radius:50%}
  </style></head><body><div id="stage"></div></body></html>`);
 await page.evaluate(async fonts=>{
   await Promise.all(fonts.map(face=>document.fonts.load(`${face.weight} 78px "LC${face.family}"`)));
   await document.fonts.ready;
 },request.fonts);
 const fontLoadSeconds=(performance.now()-fontStart)/1000;

 for (const job of request.jobs) {
  const start=performance.now();
  try {
   const [width,height]=job.geometry.canvas;
   await page.setViewportSize({width,height});
   const measures=await page.evaluate(async({job,icons})=>{
    const [w,h]=job.geometry.canvas;
    const stage=document.getElementById('stage');
    stage.replaceChildren();
    stage.style.width=w+'px';stage.style.height=h+'px';stage.lang=job.language;stage.dir=job.direction;
    const languageFamily=job.language.match(/^(zh|ja|ko)/)?'LCCJK,LCLatin,LCArabic':job.language.match(/^(ar|fa|ur)/)?'LCArabic,LCLatin,LCCJK':'LCLatin,LCCJK,LCArabic';
    stage.style.fontFamily=languageFamily;
    const pixels=b=>({x:b[0]*w,y:b[1]*h,width:b[2]*w,height:b[3]*h});
    const place=(el,b)=>{const r=pixels(b);Object.assign(el.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});return r;};
    const placePixels=(el,r)=>{Object.assign(el.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px'});return r;};
    const backdrop=document.createElement('canvas');backdrop.width=w;backdrop.height=h;
    const context=backdrop.getContext('2d',{willReadFrequently:true});
    if(job.version===3&&job.canvas_background){stage.style.background=job.canvas_background;context.fillStyle=job.canvas_background;context.fillRect(0,0,w,h);}
    else{stage.style.background='transparent';const base=document.createElement('img');base.id='base';base.src=job.base_image;stage.append(base);await base.decode();context.drawImage(base,0,0,w,h);}
    const layers=[],texts=[],lines=[],prechecks=[];
    const rgba=(hex,alpha)=>{
     const values=hex.match(/[a-f\d]{2}/gi).map(value=>parseInt(value,16));
     return `rgba(${values[0]},${values[1]},${values[2]},${alpha})`;
    };
    function legacySurface(box,id){
     if(job.surface==='transparent')return;
     const el=document.createElement('div');el.className='surface';const r=place(el,box);const rgb=job.theme.surface;
     if(job.surface==='solid'){el.style.background=rgb;context.fillStyle=rgb;}
     else {el.style.background=`linear-gradient(90deg,${rgb} 0%,${rgb}F2 80%,${rgb}00 100%)`;const gradient=context.createLinearGradient(r.x,0,r.x+r.width,0);gradient.addColorStop(0,rgb);gradient.addColorStop(.8,rgb+'F2');gradient.addColorStop(1,rgb+'00');context.fillStyle=gradient;}
     stage.append(el);context.fillRect(r.x,r.y,r.width,r.height);layers.push({id:'surface-'+id,kind:'surface',bbox:r});
    }
    const addLegacyText=(id,value,box,role,maxLines=2)=>{
     if(!value)return;
     legacySurface(box,id);
     const el=document.createElement('div');el.className='text '+role;el.dataset.id=id;el.textContent=value;const r=place(el,box);
     // Height is a measured limit, not CSS clipping. Failed previews reveal the overflow.
     el.style.height='auto';el.style.fontSize=job.sizes[role==='label'?'label':role]+'px';el.style.color=job.ink;el.style.textAlign=job.direction==='rtl'?'right':'left';
     stage.append(el);texts.push({el,id,role,limit:r,maxLines,flow:false});
    };
    const addFixedV2Text=(id,value,box,role,maxLines=2,align,ink)=>{
     if(!value||!box)return;
     const el=document.createElement('div');el.className='text '+role;el.dataset.id=id;el.textContent=value;const r=place(el,box);
     el.style.height='auto';el.style.fontSize=job.sizes[role==='label'?'label':role]+'px';el.style.color=ink||job.ink;
     el.style.fontWeight=role==='label'?String(job.label_weight??600):'400';el.style.textAlign=align||job.text_group?.align||(job.direction==='rtl'?'right':'left');
     stage.append(el);texts.push({el,id,role,limit:r,maxLines,flow:false,ink:ink||job.ink});
    };
    const icon=(id,key,box)=>{
     if(!key||!box)return;
     const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.classList.add('icon');
     const r=place(svg,box);const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',icons[key]);p.setAttribute('fill','none');p.setAttribute('stroke',job.theme.accent);p.setAttribute('stroke-width','1.65');p.setAttribute('stroke-linecap','round');p.setAttribute('stroke-linejoin','round');svg.append(p);stage.append(svg);layers.push({id,kind:'icon',bbox:r});
    };
    const raster=async(id,src,box,shape='rect',thinBorder=false)=>{
     if(!src||!box)return;
     const el=document.createElement('img');el.className='evidence '+shape;const r=place(el,box);el.src=src;
     if(thinBorder){el.style.border=`${Math.max(1,Math.min(2,w*.0007))}px solid ${job.theme.accent}`;}
     stage.append(el);await el.decode();layers.push({id,kind:'evidence',bbox:r});
    };
    const g=job.geometry;

    if(job.version===3){
     for(const panel of job.panels||[]){
      const source=new Image();source.src=panel.image;await source.decode();
      const layer=document.createElement('canvas');layer.width=w;layer.height=h;
      layer.style.position='absolute';layer.style.inset='0';
      const args=[...panel.placement.source,...panel.placement.destination];
      layer.getContext('2d').drawImage(source,...args);context.drawImage(source,...args);stage.append(layer);
      layers.push({id:'panel-'+panel.id,kind:'panel',bbox:pixels(panel.box)});
     }
     for(const panel of job.panels||[]){
      if(!panel.step_number)continue;
      const panelBox=pixels(panel.box),size=job.sizes.label*1.65,safe=Math.min(w,h)*.05;
      const badge={x:Math.max(safe+2,panelBox.x+w*.012),y:Math.max(safe+2,panelBox.y+h*.015),width:size,height:size};
      const background=document.createElement('div');background.className='surface';placePixels(background,badge);background.style.background=job.graphic_surface_color; background.style.borderRadius='50%';stage.append(background);
      context.fillStyle=job.graphic_surface_color;context.beginPath();context.arc(badge.x+size/2,badge.y+size/2,size/2,0,Math.PI*2);context.fill();
      layers.push({id:'step-surface-'+panel.id,kind:'surface',bbox:badge});
      addFixedV2Text('panel-step-'+panel.id,String(panel.step_number),[badge.x/w,(badge.y+(size-job.sizes.label*1.25)/2)/h,size/w,size/h],'label',1,'center',job.graphic_text_color);
     }
     for(const group of job.text_groups){
      const outerLimit=pixels(group.box),surfaceConfig=group.surface;
      const padding=surfaceConfig.kind==='transparent'?0:group.sizes.body*surfaceConfig.padding_em;
      const contentLimit={x:outerLimit.x+padding,y:outerLimit.y+padding,width:Math.max(1,outerLimit.width-padding*2),height:Math.max(1,outerLimit.height-padding*2)};
      const flow=document.createElement('div');flow.className='text-group';
      placePixels(flow,{...contentLimit,height:0});flow.style.height='auto';flow.style.gap=group.sizes.body*group.gap_em+'px';
      flow.style.textAlign=group.align;stage.append(flow);
      for(const [key,role,maxLines,weight] of [['headline','headline',2,group.headline_weight],['body','body',3,group.body_weight??400],['label','label',3,group.label_weight??600]]){
       if(!group[key])continue;
       const id=`group-${group.id}-${key}`,el=document.createElement('div');el.className='text '+role;el.dataset.id=id;el.textContent=group[key];
       el.style.fontSize=group.sizes[role]+'px';el.style.color=group.ink;el.style.fontWeight=String(weight);el.style.textAlign=group.align;
       el.style.fontFamily=key==='headline'&&group.headline_family==='serif'?`LCSerif,${languageFamily}`:languageFamily;
       if(key==='headline'){
        const treatment=group.headline_treatment||{kind:'plain'};
        if(treatment.kind==='outline'){
         el.style.webkitTextStroke=`${Math.max(1,group.sizes.headline*treatment.width_em)}px ${treatment.color}`;
         el.style.paintOrder='stroke fill';
        }else if(treatment.kind==='shadow'){
         const [x,y]=treatment.offset_em;
         el.style.textShadow=`${group.sizes.headline*x}px ${group.sizes.headline*y}px ${group.sizes.headline*treatment.blur_em}px ${rgba(treatment.color,treatment.opacity)}`;
        }
       }
       // Noto Sans Arabic has substantially taller glyph metrics. The Latin
       // line-height makes adjacent Arabic lines collide despite fitting CSS.
       if(job.language.match(/^(ar|fa|ur)/))el.style.lineHeight='2.15';
       flow.append(el);texts.push({el,id,role,limit:contentLimit,maxLines,flow:true,ink:group.ink});
      }
      await document.fonts.ready;
      const bounds=flow.getBoundingClientRect();
      prechecks.push({check:'text_group_fit',element:'group-'+group.id,passed:bounds.height<=contentLimit.height+1,actual_height:bounds.height,max_height:contentLimit.height});
      if(surfaceConfig.kind!=='transparent'){
       const outer={x:outerLimit.x,y:outerLimit.y,width:outerLimit.width,height:bounds.height+padding*2};
       const surface=document.createElement('div');surface.className='surface';placePixels(surface,outer);
       const color=surfaceConfig.color,alpha=surfaceConfig.opacity;
       if(surfaceConfig.kind==='solid'){surface.style.background=rgba(color,alpha);context.fillStyle=rgba(color,alpha);}
       else{
        const vertical=surfaceConfig.direction==='vertical',reverse=!vertical&&group.align==='right';
        surface.style.background=`linear-gradient(${vertical?'180deg':reverse?'270deg':'90deg'},${rgba(color,alpha)} 0%,${rgba(color,alpha*.8)} 60%,${rgba(color,0)} 100%)`;
        const gradient=context.createLinearGradient(reverse?outer.x+outer.width:outer.x,outer.y,vertical?outer.x:reverse?outer.x:outer.x+outer.width,vertical?outer.y+outer.height:outer.y);
        gradient.addColorStop(0,rgba(color,alpha));gradient.addColorStop(.6,rgba(color,alpha*.8));gradient.addColorStop(1,rgba(color,0));context.fillStyle=gradient;
       }
       stage.insertBefore(surface,flow);context.fillRect(outer.x,outer.y,outer.width,outer.height);
       layers.push({id:'surface-group-'+group.id,kind:'surface',bbox:outer,adaptive:true,owner_group:group.id});
      }
     }
     for(let i=0;i<job.items.length;i++){
      const item=job.items[i],slot=g.items[i]||{};
      if(item.image&&slot.image)await raster(`evidence-${i}`,item.image,slot.image,slot.image_shape||'rect',g.template==='detail');
      if(slot.number)addFixedV2Text(`step-${i}`,String(i+1).padStart(2,'0'),slot.number,'label',1,slot.align);
      if(item.icon&&slot.icon)icon(`icon-${i}`,item.icon,slot.icon);
      if(item.text&&slot.text)addFixedV2Text(`item-${i}`,item.text,slot.text,'label',3,slot.align);
     }
    }else if(job.version===2){
     const group=job.text_group;
     const outerLimit=pixels(group.box);
     const padding=group.padding_px||0;
     const contentLimit={x:outerLimit.x+padding,y:outerLimit.y+padding,
                         width:Math.max(1,outerLimit.width-padding*2),
                         height:Math.max(1,group.max_height_px-padding*2)};
     const flow=document.createElement('div');flow.className='text-group';flow.dataset.id='text-group';
     placePixels(flow,{x:contentLimit.x,y:contentLimit.y,width:contentLimit.width,height:0});
     flow.style.height='auto';flow.style.gap=(job.sizes.body*group.gap_em)+'px';flow.style.textAlign=group.align;
     stage.append(flow);
     const addFlowText=(parent,id,value,role,maxLines,fontFamily,fontWeight)=>{
      if(!value)return false;
      const el=document.createElement('div');el.className='text '+role;el.dataset.id=id;el.textContent=value;
      el.style.fontSize=job.sizes[role==='label'?'label':role]+'px';el.style.color=job.ink;el.style.fontFamily=fontFamily;
      el.style.fontWeight=String(fontWeight);el.style.textAlign=group.align;
      parent.append(el);texts.push({el,id,role,limit:contentLimit,maxLines,flow:true});return true;
     };
     const headlineFamily=job.headline_family==='serif'?`LCSerif,${languageFamily}`:languageFamily;
     let flowCount=0;
     flowCount+=addFlowText(flow,'headline',job.headline,'headline',2,headlineFamily,job.headline_weight)?1:0;
     flowCount+=addFlowText(flow,'body',job.body,'body',2,languageFamily,400)?1:0;
     for(let i=0;i<(job.faq||[]).length;i++){
      const pair=job.faq[i];const faq=document.createElement('div');faq.className='faq-pair';faq.style.gap=(job.sizes.body*.22)+'px';
      const question=addFlowText(faq,`faq-${i}-question`,pair.question,'label',2,languageFamily,600);
      const answer=addFlowText(faq,`faq-${i}-answer`,pair.answer,'body',3,languageFamily,400);
      if(question||answer){flow.append(faq);flowCount++;}
     }
     for(let i=0;i<job.items.length;i++){
      const item=job.items[i],slot=g.items[i]||{};
      if(item.text&&!slot.text)flowCount+=addFlowText(flow,`item-${i}`,item.text,'label',2,languageFamily,600)?1:0;
     }
     await document.fonts.ready;
     const flowRect=flow.getBoundingClientRect();
     if(flowCount){
      const flowBox={x:flowRect.x,y:flowRect.y,width:flowRect.width,height:flowRect.height};
      const groupOverflow=flowBox.height>contentLimit.height+1||flowBox.y+flowBox.height>outerLimit.y+(group.max_height_px||outerLimit.height)+1;
      prechecks.push({check:'text_group_fit',element:'text-group',passed:!groupOverflow,actual_height:Math.round(flowBox.height*10)/10,max_height:Math.round(contentLimit.height*10)/10,detail:groupOverflow?'Preserve approved copy: enlarge/recompose text_group or request confirmation; v2 does not shrink type.':''});
      if(job.surface!=='transparent'){
       const outer={x:contentLimit.x-padding,y:contentLimit.y-padding,width:contentLimit.width+padding*2,height:flowBox.height+padding*2};
       const surface=document.createElement('div');surface.className='surface';placePixels(surface,outer);const rgb=job.theme.surface;
       if(job.surface==='solid'){
        surface.style.background=rgb;context.fillStyle=rgb;
       }else{
        const reverse=group.align==='right';
        surface.style.background=`linear-gradient(${reverse?'270deg':'90deg'},${rgba(rgb,.98)} 0%,${rgba(rgb,.90)} 48%,${rgba(rgb,.42)} 76%,${rgba(rgb,0)} 100%)`;
        const gradient=context.createLinearGradient(reverse?outer.x+outer.width:outer.x,0,reverse?outer.x:outer.x+outer.width,0);
        gradient.addColorStop(0,rgba(rgb,.98));gradient.addColorStop(.48,rgba(rgb,.90));gradient.addColorStop(.76,rgba(rgb,.42));gradient.addColorStop(1,rgba(rgb,0));context.fillStyle=gradient;
        prechecks.push({check:'gradient_fade',element:'text-group',passed:true,detail:'soft alpha fade'});
       }
       stage.insertBefore(surface,flow);context.fillRect(outer.x,outer.y,outer.width,outer.height);layers.push({id:'surface-text-group',kind:'surface',bbox:outer,adaptive:true});
      }
     }
     for(let i=0;i<job.items.length;i++){
      const item=job.items[i],slot=g.items[i]||{};
      if(item.image&&slot.image)await raster(`evidence-${i}`,item.image,slot.image,slot.image_shape||item.image_shape||'rect',g.template==='detail');
      if(slot.number)addFixedV2Text(`step-${i}`,String(i+1).padStart(2,'0'),slot.number,'label',1,slot.align||item.align);
      if(item.icon&&slot.icon)icon(`icon-${i}`,item.icon,slot.icon);
      if(item.text&&slot.text)addFixedV2Text(`item-${i}`,item.text,slot.text,'label',g.template==='detail'||g.template==='components'?3:2,slot.align||item.align);
     }
     if(job.surface==='transparent')prechecks.push({check:'text_group_surface',element:'text-group',passed:!layers.some(layer=>layer.kind==='surface'),detail:'transparent v2 group has no frame'});
     else prechecks.push({check:'text_group_surface',element:'text-group',passed:layers.some(layer=>layer.id==='surface-text-group'&&layer.adaptive),detail:'one adaptive content surface'});
    }else{
     if(job.headline)addLegacyText('headline',job.headline,g.headline,'headline');
     if(job.body)addLegacyText('body',job.body,g.body,'body');
     for(let i=0;i<job.items.length;i++){
      const item=job.items[i],slot=g.items[i];
      if(item.image&&slot.image)await raster(`evidence-${i}`,item.image,slot.image);
      if(slot.number)addLegacyText(`step-${i}`,String(i+1).padStart(2,'0'),slot.number,'label',1);
      if(item.icon&&slot.icon)icon(`icon-${i}`,item.icon,slot.icon);
      addLegacyText(`item-${i}`,item.text,slot.text,'label',g.template==='detail'||g.template==='components'?3:2);
     }
    }

    for(const line of g.lines){
     const points=line.points.map(([x,y])=>[x*w,y*h]);
     const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
     svg.style.position='absolute';svg.style.inset='0';svg.style.width=w+'px';svg.style.height=h+'px';svg.setAttribute('viewBox',`0 0 ${w} ${h}`);
     const strokeWidth=line.thin?Math.max(1,Math.min(2,w*.0007)):Math.max(2,w*.0013);
     const polyline=document.createElementNS(svg.namespaceURI,'polyline');polyline.setAttribute('points',points.map(point=>point.join(',')).join(' '));polyline.setAttribute('stroke',job.theme.accent);polyline.setAttribute('stroke-width',String(strokeWidth));polyline.setAttribute('fill','none');svg.append(polyline);
     if(line.arrow){
      for(const [index,other] of [[0,1],[points.length-1,points.length-2]]){
       const [x,y]=points[index],dx=points[other][0]-x,dy=points[other][1]-y,length=Math.hypot(dx,dy),ux=dx/length,uy=dy/length,size=w*.007;
       const arrow=document.createElementNS(svg.namespaceURI,'polyline');arrow.setAttribute('points',`${x+ux*size-uy*size*.4},${y+uy*size+ux*size*.4} ${x},${y} ${x+ux*size+uy*size*.4},${y+uy*size-ux*size*.4}`);arrow.setAttribute('fill','none');arrow.setAttribute('stroke',job.theme.accent);arrow.setAttribute('stroke-width',String(strokeWidth));svg.append(arrow);
      }
     }else{
      const [x,y]=points.at(-1),circle=document.createElementNS(svg.namespaceURI,'circle');circle.setAttribute('cx',x);circle.setAttribute('cy',y);circle.setAttribute('r',line.thin?Math.max(1,w*.0025):w*.004);circle.setAttribute('fill',job.theme.accent);svg.append(circle);
     }
     stage.append(svg);lines.push({...line,points});
    }

    await document.fonts.ready;
    const checks=[...prechecks],bboxes=[];
    const overlapBoxes=(a,b)=>Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>1&&Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1;
    const luminance=rgb=>{const adjusted=rgb.map(value=>{value/=255;return value<=.04045?value/12.92:((value+.055)/1.055)**2.4});return adjusted[0]*.2126+adjusted[1]*.7152+adjusted[2]*.0722;};
    for(const item of texts){
     const foreground=(item.ink||job.ink).match(/[a-f\d]{2}/gi).map(value=>parseInt(value,16));const foregroundLuminance=luminance(foreground);
     const {el,id,role,limit,maxLines,flow}=item;const rect=el.getBoundingClientRect();const r={x:rect.x,y:rect.y,width:rect.width,height:rect.height};
     const range=document.createRange();range.selectNodeContents(el);const rects=Array.from(range.getClientRects()).filter(value=>value.width&&value.height);
     const tops=[...new Set(rects.map(value=>Math.round(value.top*10)/10))];
     const occupied=rects.length?{x:Math.min(...rects.map(value=>value.x)),y:Math.min(...rects.map(value=>value.y)),width:Math.max(...rects.map(value=>value.right))-Math.min(...rects.map(value=>value.x)),height:Math.max(...rects.map(value=>value.bottom))-Math.min(...rects.map(value=>value.y))}:r;
     bboxes.push({id,kind:'text',role,bbox:occupied,container:limit,line_count:tops.length,flow:!!flow});
     const horizontalOverflow=el.scrollWidth>limit.width+1||rects.some(value=>value.right>limit.x+limit.width+1||value.left<limit.x-1);
     const overflow=(flow?false:rect.height>limit.height+1)||horizontalOverflow||tops.length>maxLines;
     checks.push({check:'text_fit',element:id,passed:!overflow,line_count:tops.length,max_lines:maxLines,detail:overflow?'Reposition or widen the text region; preserve approved copy and mobile size':''});
     const samples=[];
     for(const lineRect of rects){
      for(let y=lineRect.y+lineRect.height*.2;y<lineRect.bottom;y+=Math.max(4,lineRect.height*.3)){
       for(let x=lineRect.x+3;x<lineRect.right;x+=Math.max(5,lineRect.width/24)){
        if(x<0||y<0||x>=w||y>=h)continue;
        const color=Array.from(context.getImageData(Math.floor(x),Math.floor(y),1,1).data).slice(0,3),backgroundLuminance=luminance(color);
        samples.push((Math.max(foregroundLuminance,backgroundLuminance)+.05)/(Math.min(foregroundLuminance,backgroundLuminance)+.05));
       }
      }
     }
     samples.sort((a,b)=>a-b);const ratio=samples.length?samples[Math.floor((samples.length-1)*.05)]:0;
     if(!job.typography_proof)checks.push({check:'text_contrast',element:id,passed:samples.length>0&&samples[0]>=4.5,ratio_min:Math.round((samples[0]||0)*100)/100,ratio_p05:Math.round(ratio*100)/100,minimum:4.5});
     const safe=Math.min(w,h)*.05;const safeBox=flow?occupied:r;
     checks.push({check:'safe_margin',element:id,passed:safeBox.x>=safe-1&&safeBox.y>=safe-1&&safeBox.x+safeBox.width<=w-safe+1&&safeBox.y+safeBox.height<=h-safe+1});
    }
    bboxes.push(...layers);
    const segmentHitsEvidenceInterior=(start,end,bbox)=>{
     const inset={x:bbox.x+1,y:bbox.y+1,width:bbox.width-2,height:bbox.height-2};
     if(inset.width<=0||inset.height<=0)return false;
     const dx=end[0]-start[0],dy=end[1]-start[1];let enter=0,exit=1;
     const clip=(p,q)=>{
      if(Math.abs(p)<1e-9)return q>0;
      const t=q/p;
      if(p<0){if(t>exit)return false;if(t>enter)enter=t;}
      else{if(t<enter)return false;if(t<exit)exit=t;}
      return true;
     };
     return clip(-dx,start[0]-inset.x)&&clip(dx,inset.x+inset.width-start[0])&&
      clip(-dy,start[1]-inset.y)&&clip(dy,inset.y+inset.height-start[1])&&enter<exit&&exit>0&&enter<1;
    };
    if(job.version>=2){
     const evidence=bboxes.filter(box=>box.kind==='evidence');
     for(const line of lines.filter(item=>item.source_evidence_id))for(const image of evidence){
      if(image.id===line.source_evidence_id)continue;
      if(line.points.some((point,index)=>index>0&&segmentHitsEvidenceInterior(line.points[index-1],point,image.bbox)))
       checks.push({check:'leader_evidence_collision',passed:false,elements:[line.id,image.id]});
     }
     if(!checks.some(check=>check.check==='leader_evidence_collision'))checks.push({check:'leader_evidence_collision',passed:true});
    }
    for(let i=0;i<bboxes.length;i++)for(let k=i+1;k<bboxes.length;k++){
     const a=bboxes[i],b=bboxes[k];
     if(a.kind==='panel'&&b.kind==='panel'&&overlapBoxes(a.bbox,b.bbox))checks.push({check:'panel_collision',passed:false,elements:[a.id,b.id]});
     for(const [surface,other] of [[a,b],[b,a]])if(surface.kind==='surface'&&surface.owner_group&&other.kind==='text'&&!other.id.startsWith('group-'+surface.owner_group+'-')&&overlapBoxes(surface.bbox,other.bbox))checks.push({check:'group_surface_collision',passed:false,elements:[surface.id,other.id]});
     if(a.kind==='surface'||b.kind==='surface'||a.kind==='panel'||b.kind==='panel')continue;
     if(overlapBoxes(a.bbox,b.bbox))checks.push({check:'element_collision',passed:false,elements:[a.id,b.id]});
    }
    for(const region of job.protected){
     const r=pixels(region.bbox);
     for(const element of bboxes)if(element.kind!=='panel'&&overlapBoxes(r,element.bbox))checks.push({check:'protected_region',passed:false,element:element.id,region:region.kind});
     // A leader may end on the product it labels; it may not cross a face/contact/detail exclusion.
     if(region.kind!=='product')for(const line of lines){
      let hit=false;
      for(let i=1;i<line.points.length;i++){
       const a=line.points[i-1],b=line.points[i],steps=Math.max(2,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/3));
       for(let k=0;k<=steps;k++){const t=k/steps,x=a[0]+(b[0]-a[0])*t,y=a[1]+(b[1]-a[1])*t;if(x>r.x&&x<r.x+r.width&&y>r.y&&y<r.y+r.height){hit=true;break;}}
      }
      if(hit)checks.push({check:'protected_leader',passed:false,element:line.id,region:region.kind});
     }
    }
    for(const line of lines)for(const text of bboxes.filter(box=>box.kind==='text')){
     let hit=false;
     for(let i=1;i<line.points.length;i++){
      const a=line.points[i-1],b=line.points[i],steps=Math.max(2,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/3));
      for(let k=0;k<=steps;k++){const t=k/steps,x=a[0]+(b[0]-a[0])*t,y=a[1]+(b[1]-a[1])*t,r=text.bbox;if(x>r.x&&x<r.x+r.width&&y>r.y&&y<r.y+r.height){hit=true;break;}}
     }
     if(hit)checks.push({check:'leader_text_collision',passed:false,elements:[line.id,text.id]});
    }
    if(!checks.some(check=>check.check==='element_collision'))checks.push({check:'element_collision',passed:true});
    if(!checks.some(check=>check.check==='protected_region'||check.check==='protected_leader'))checks.push({check:'protected_region',passed:true});
    checks.push({check:'fonts_loaded',passed:document.fonts.status==='loaded'});
    return {bboxes,checks,passed:checks.every(check=>check.passed),geometry:g,fingerprint:job.fingerprint,base_hash:job.base_hash};
   },{job,icons:request.icons});
   const layoutSeconds=(performance.now()-start)/1000;
   let outputPath=null,screenshotSeconds=0;
   if(!measureOnly){
    outputPath=path.join(request.output_dir,job.id+'.png');
    const screenshotStart=performance.now();
    await page.screenshot({path:outputPath,animations:'disabled',type:'png'});
    if(job.typography_proof){
     // Two bounded proof rasters reuse this browser and the exact glyph positions.
     const proofStyle=await page.addStyleTag({content:'.text{visibility:hidden!important}'});
     try{
      await page.screenshot({path:path.join(request.output_dir,job.id+'-background.png'),animations:'disabled',type:'png'});
      await proofStyle.evaluate(el=>{el.textContent='#stage{background:#000!important}#stage img,#stage canvas,#stage svg,.surface,.icon{visibility:hidden!important}.text-group{background:transparent!important;box-shadow:none!important}.text{visibility:visible!important;color:#fff!important;text-shadow:none!important;-webkit-text-stroke:0!important;background:transparent!important;opacity:1!important}';});
      await page.screenshot({path:path.join(request.output_dir,job.id+'-glyphs.png'),animations:'disabled',type:'png'});
     }finally{await proofStyle.evaluate(el=>el.remove());}
    }
    screenshotSeconds=(performance.now()-screenshotStart)/1000;
   }
   results[job.id]={...measures,output_path:outputPath,runtime:{...request.versions,render_seconds:Number(((performance.now()-start)/1000).toFixed(3)),
     layout_seconds:Number(layoutSeconds.toFixed(4)),screenshot_seconds:Number(screenshotSeconds.toFixed(4)),measurement_only:measureOnly}};
  }catch(error){
   results[job.id]={passed:false,output_path:null,bboxes:[],checks:[{check:'renderer',passed:false,detail:String(error)}],runtime:request.versions};
  }
 }
 const first=Object.values(results)[0];
 if(first)first.runtime.batch_metrics={payload_parse_seconds:Number(payloadParseSeconds.toFixed(4)),browser_launch_seconds:Number(browserLaunchSeconds.toFixed(4)),font_load_seconds:Number(fontLoadSeconds.toFixed(4)),browser_batch_seconds:Number(((performance.now()-batchStart)/1000).toFixed(4)),browser_launches:1};
}finally{
 await browser.close();
}
process.stdout.write(JSON.stringify(results));
