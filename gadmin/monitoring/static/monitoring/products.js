(() => {
  'use strict';
  const form=document.querySelector('.product-filters');
  if(form){
    const button=form.querySelector('button[type="submit"]');
    form.addEventListener('submit',()=>{button.disabled=true;button.textContent='조회 중…';form.setAttribute('aria-busy','true');});
    window.addEventListener('pageshow',()=>{button.disabled=false;button.textContent='조회';form.removeAttribute('aria-busy');});
  }
  document.querySelector('.product-history .errornote')?.focus();
  const formatDate = value => new Date(value).toLocaleString('ko-KR', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  document.querySelectorAll('time.local-time').forEach(el => {el.textContent=formatDate(el.dateTime);});
  const canvas=document.getElementById('product-chart'), source=document.getElementById('product-price-data');
  if (!canvas || !source) return;
  const points=JSON.parse(source.textContent), detail=document.getElementById('product-chart-detail');
  const ns='http://www.w3.org/2000/svg';
  const node=(name, attrs, text) => {const el=document.createElementNS(ns,name);Object.entries(attrs||{}).forEach(([key,value])=>el.setAttribute(key,String(value)));if(text!==undefined)el.textContent=text;return el;};
  const draw=() => {
    canvas.replaceChildren();
    const w=Math.max(260,canvas.clientWidth), h=w<600?230:280, pad={l:70,r:14,t:22,b:32};
    const svg=node('svg',{viewBox:`0 0 ${w} ${h}`});
    const values=points.map(p=>Number(p.amount)), dates=points.map(p=>new Date(p.at).getTime());
    const lo=Math.min(...values),hi=Math.max(...values),margin=Math.max(1,(hi-lo)*.12,hi===lo?Math.abs(lo)*.02:0);
    const min=lo-margin,max=hi+margin,first=Math.min(...dates),last=Math.max(...dates);
    const x=value=>first===last?(w+pad.l-pad.r)/2:pad.l+(value-first)/(last-first)*(w-pad.l-pad.r);
    const y=value=>h-pad.b-(value-min)/(max-min)*(h-pad.t-pad.b);
    for(let i=0;i<4;i++){const value=min+(max-min)*i/3, py=y(value);svg.append(node('line',{x1:pad.l,x2:w-pad.r,y1:py,y2:py,class:'price-grid'}),node('text',{x:pad.l-8,y:py+4,'text-anchor':'end'},value.toLocaleString('ko-KR',{maximumFractionDigits:0})));}
    const label=value=>new Date(value).toLocaleDateString('ko-KR',{year:'2-digit',month:'2-digit',day:'2-digit'});
    svg.append(node('text',{x:pad.l,y:h-6},label(first)));
    if(first!==last)svg.append(node('text',{x:w-pad.r,y:h-6,'text-anchor':'end'},label(last)));
    svg.append(node('polyline',{points:points.map((p,i)=>`${x(dates[i])},${y(values[i])}`).join(' '),class:'price-line'}));
    points.forEach((p,i)=>{
      const description=`${formatDate(p.at)} · ${Number(p.amount).toLocaleString('ko-KR')} · ${p.title}`;
      const circle=node('g',{class:'price-dot',tabindex:0,role:'button','aria-label':description});
      circle.append(node('circle',{cx:x(dates[i]),cy:y(values[i]),r:12,fill:'transparent',stroke:'none'}));
      circle.append(node('circle',{cx:x(dates[i]),cy:y(values[i]),r:5}));
      circle.append(node('title',{},description));
      const show=()=>{detail.textContent=description;};
      circle.addEventListener('pointerenter',show);circle.addEventListener('focus',show);
      const reveal=()=>{show();document.getElementById(`price-${p.id}`)?.scrollIntoView({block:'nearest'});};
      circle.addEventListener('click',reveal);circle.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();reveal();}});
      svg.append(circle);
    });
    canvas.append(svg);
  };
  if ('ResizeObserver' in window) new ResizeObserver(draw).observe(canvas); else draw();
})();
