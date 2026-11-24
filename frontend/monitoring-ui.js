// Monitoring page: how long PDecision takes to decide (per street, opponents in the hand and PC) and how often bots
// miss their turn. The PCs write these figures every 5 minutes; decision times are kept per hour.
export function installMonitoring(h){
 const {$,esc,state,render,siteApi,table,card,stats,select,empty,toast}=h;
 const pad=n=>String(n).padStart(2,'0');
 const local=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
 const ms=v=>v==null?'—':v<1000?`${v} ms`:`${(v/1000).toFixed(v<10000?2:1)} s`;
 const under=v=>v==null?'over 5 s':`under ${ms(v)}`;
 const pct=v=>v==null?'—':`${(v*100).toFixed(v<.01&&v>0?2:1)}%`;
 const when=v=>new Date(v).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
 const defaults=()=>{const to=new Date(),from=new Date(to-24*3600e3);return {from:local(from),to:local(to),machine:'all',opponents:'all',page_size:'20'};};
 let filters=null,pageNumber=1,contextKey=null,focusMissed=false;

 // One small chart per street showing average decision time, plus missed actions; hourly charts share the
 // time axis of the selected range, so the charts line up.
 const label=v=>new Date(v).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit'});
 function axis(range){const first=+new Date(range.from),last=+new Date(range.to),span=Math.max(3600e3,last-first);return {first,last,span};}
 function frame(ax,W,H,L,R,B,ticks){
  return `<text x="${L}" y="${H-6}">${esc(label(ax.first))}</text><text x="${(L+W-R)/2}" y="${H-6}" class="middle">${esc(label(ax.first+ax.span/2))}</text><text x="${W-R}" y="${H-6}" class="end">${esc(label(ax.last))}</text>${ticks}`;
 }
 function streetChart(s,ax){
  const pts=s.points;
  if(!pts.length)return `<div class="monitor-chart"><h3>${esc(s.name)}</h3><p class="sub">No decisions in this range.</p></div>`;
  const W=440,H=200,L=50,R=12,T=12,B=24,x=p=>L+(+new Date(p.at)-ax.first)/ax.span*(W-L-R);
  const top=Math.max(100,...pts.map(p=>p.avg_ms||0))*1.1,y=v=>H-B-(v/top)*(H-T-B);
  const path=(k)=>pts.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)},${y(p[k]).toFixed(1)}`).join('');
  const ticks=[0,.5,1].map(f=>`<line x1="${L}" x2="${W-R}" y1="${y(top*f)}" y2="${y(top*f)}"/><text x="${L-5}" y="${y(top*f)+4}" class="end">${esc(ms(Math.round(top*f)))}</text>`).join('');
  const total=pts.reduce((a,p)=>a+p.decisions,0),avg=Math.round(pts.reduce((a,p)=>a+p.avg_ms*p.decisions,0)/total);
  return `<div class="monitor-chart"><h3>${esc(s.name)} <span class="sub">${total.toLocaleString()} decisions · average ${esc(ms(avg))}</span></h3><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.name)}: average decision time per hour">${frame(ax,W,H,L,R,B,ticks)}
   ${pts.length>1?`<path class="avg" d="${path('avg_ms')}"/>`:''}
   ${pts.map(p=>`<circle class="avg" cx="${x(p).toFixed(1)}" cy="${y(p.avg_ms).toFixed(1)}" r="3"><title>${esc(label(p.at))}: average ${esc(ms(p.avg_ms))}, ${p.decisions} decisions</title></circle>`).join('')}
  </svg></div>`;
 }

 function dailyChart(points){
  if(!points.length)return '<p class="sub card-body">No missed actions in this range.</p>';
  const W=900,H=180,L=50,R=12,T=12,B=35,top=Math.max(1,...points.map(p=>p.missed));
  const slot=(W-L-R)/points.length,y=v=>H-B-v/top*(H-T-B);
  return `<div class="monitor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Missed actions per day">${[0,top].map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-5}" y="${y(v)+4}" class="end">${v}</text>`).join('')}${points.map((p,i)=>`<rect class="missed" x="${L+i*slot+slot*.15}" y="${y(p.missed)}" width="${slot*.7}" height="${H-B-y(p.missed)}"><title>${esc(p.date)}: ${p.missed} missed</title></rect>${points.length<=10||i%Math.ceil(points.length/8)===0?`<text x="${L+(i+.5)*slot}" y="${H-12}" class="middle">${esc(p.date.slice(5))}</text>`:''}`).join('')}</svg></div>`;
 }
 function missedChart(series,ax){
  const pts=series.filter(p=>p.missed);
  if(!pts.length)return '<p class="sub card-body">No missed actions in this range.</p>';
  const W=900,H=150,L=50,R=12,T=12,B=24,x=p=>L+(+new Date(p.at)-ax.first)/ax.span*(W-L-R);
  const top=Math.max(1,...pts.map(p=>p.missed)),y=v=>H-B-(v/top)*(H-T-B),bar=Math.max(3,(W-L-R)/Math.max(24,ax.span/3600e3)*.7);
  const ticks=[0,top].map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-5}" y="${y(v)+4}" class="end">${v}</text>`).join('');
  return `<div class="monitor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Missed actions per hour">${frame(ax,W,H,L,R,B,ticks)}${pts.map(p=>`<rect class="missed" x="${(x(p)-bar/2).toFixed(1)}" y="${y(p.missed).toFixed(1)}" width="${bar.toFixed(1)}" height="${(H-B-y(p.missed)).toFixed(1)}"><title>${esc(label(p.at))}: ${p.missed} missed</title></rect>`).join('')}</svg></div>`;
 }

 function inspectChart(svg,points,x,describe,bottom){
  if(!svg||!points.length)return;
  const ns='http://www.w3.org/2000/svg',line=document.createElementNS(ns,'line');
  line.setAttribute('y1','12');line.setAttribute('y2',String(bottom));
  line.setAttribute('stroke','#2d6553');line.setAttribute('stroke-dasharray','4 4');
  line.setAttribute('pointer-events','none');line.classList.add('monitor-crosshair');svg.append(line);
  const readout=document.createElement('div');readout.className='entry-readout monitor-readout';
  readout.setAttribute('role','status');readout.setAttribute('aria-live','polite');svg.after(readout);
  svg.setAttribute('tabindex','0');svg.style.cursor='crosshair';
  let index=points.length-1;
  const inspect=i=>{index=Math.max(0,Math.min(points.length-1,i));const px=x(points[index],index);
   line.setAttribute('x1',String(px));line.setAttribute('x2',String(px));readout.textContent=describe(points[index]);};
  const locate=event=>{const matrix=svg.getScreenCTM();if(!matrix)return;
   const px=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse()).x;
   let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(x(points[i],i)-px)<Math.abs(x(points[nearest],nearest)-px))nearest=i;
   inspect(nearest);};
  svg.onpointermove=locate;svg.onpointerdown=locate;
  svg.onkeydown=event=>{const next={ArrowLeft:index-1,ArrowRight:index+1,Home:0,End:points.length-1}[event.key];
   if(next!==undefined){event.preventDefault();inspect(next);}};
  inspect(index);
 }

 function humanChart(d,ax){
  const points=d.human_seats?.points||[],known=points.filter(p=>p.humans!=null);
  if(!known.length)return '<p class="sub card-body">No valid human-seat samples in this range. Human history cannot be reconstructed from current lobby data.</p>';
  const W=900,H=180,L=50,R=12,B=24,top=Math.max(1,...known.map(p=>p.maximum??p.humans))*1.1;
  const x=p=>L+(+new Date(p.at)-ax.first)/ax.span*(W-L-R),y=v=>H-B-v/top*(H-B-12);
  let started=false;
  const path=points.map(p=>{if(p.humans==null){started=false;return '';}
   const part=`${started?'L':'M'}${x(p).toFixed(1)},${y(p.humans).toFixed(1)}`;started=true;return part;}).join(' ');
  return `<div class="monitor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Human ring seats per hour">${frame(ax,W,H,L,R,B,[0,top].map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-5}" y="${y(v)+4}" class="end">${Math.round(v)}</text>`).join(''))}<path style="fill:none;stroke:#963d83;stroke-width:2.5" d="${path}"/>${known.map(p=>`<circle style="fill:#963d83" cx="${x(p)}" cy="${y(p.humans)}" r="3"/>`).join('')}</svg></div>`;
 }

 const humanValue=p=>p?.humans==null?'unknown':`${p.partial?'≥':''}${p.humans} average (range ${p.minimum}–${p.maximum}; ${p.known_samples}/${p.samples} received samples valid${p.partial?'; partial table coverage':''})`;

 function bindCharts(d){
  const ax=axis(d),time=at=>new Date(at).toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
  const humans=new Map((d.human_seats?.points||[]).map(p=>[+new Date(p.at),p]));
  document.querySelectorAll('.monitor-grid .monitor-chart').forEach((root,i)=>{
   const points=d.series_by_street[i].points;
   inspectChart(root.querySelector('svg'),points,p=>50+(+new Date(p.at)-ax.first)/ax.span*(440-50-12),
    p=>`${time(p.at)} | Average: ${ms(p.avg_ms)} | Decisions: ${p.decisions.toLocaleString()} | Human ring seats: ${humanValue(humans.get(+new Date(p.at)))}`,176);
  });
  inspectChart($('svg[aria-label="Human ring seats per hour"]'),d.human_seats?.points||[],
   p=>50+(+new Date(p.at)-ax.first)/ax.span*(900-50-12),p=>`${time(p.at)} | Human ring seats: ${humanValue(p)}`,156);
  inspectChart($('svg[aria-label="Missed actions per hour"]'),d.series.filter(p=>p.missed),
   p=>50+(+new Date(p.at)-ax.first)/ax.span*(900-50-12),p=>`${time(p.at)} | Missed actions: ${p.missed.toLocaleString()}`,126);
  inspectChart($('svg[aria-label="Missed actions per day"]'),d.missed_daily,
   (p,i)=>50+(i+.5)*(900-50-12)/d.missed_daily.length,
   p=>`${new Date(p.date+'T12:00:00').toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})} | Missed actions: ${p.missed.toLocaleString()}`,145);
 }

 async function page(gen){
  const key=`${state.customer?.id}/${state.site?.id}`;
  if(key!==contextKey){filters=null;pageNumber=1;contextKey=key;}
  filters=filters||defaults();
  const q=new URLSearchParams({from:new Date(filters.from).toISOString(),to:new Date(filters.to).toISOString(),machine:filters.machine,opponents:filters.opponents,page:String(pageNumber),page_size:filters.page_size,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone});
  const d=await siteApi(`monitoring?${q}`);
  const machineOptions=[['all','All PCs'],...d.machines.map(m=>[m.id,m.name])];
  const oppOptions=[['all','Any number'],['1','1 opponent'],['2','2 opponents'],['3','3 opponents'],['4','4 opponents'],['5','5 or more']];
  const o=d.overall,m=d.missed;
  pageNumber=m.page;
  const body=`<form id="monitor-filters" class="history-filters">
    <label class="field"><span>From</span><input type="datetime-local" name="from" value="${esc(filters.from)}" required></label>
    <label class="field"><span>To</span><input type="datetime-local" name="to" value="${esc(filters.to)}" required></label>
    ${select('PC','machine',filters.machine,machineOptions)}${select('Opponents in the hand','opponents',filters.opponents,oppOptions)}
    <button class="button primary">Apply filters</button><button type="button" class="button" id="monitor-reset">Last 24 hours</button></form>
   ${stats([['Decisions',o.decisions.toLocaleString(),'answered by PDecision'],['Average decision time',ms(o.avg_ms),`half ${under(o.p50_under_ms)}, 90% ${under(o.p90_under_ms)}`],['Slowest decision',ms(o.max_ms),`${pct(o.slow_share)} took 2 s or more`],['Missed actions',m.total.toLocaleString(),`${m.sit_out} unplanned sit-outs · ${m.clock_acted} acted by the site's clock`]])}
   ${card('Decision time per hour',`<div class="monitor-grid">${d.series_by_street.map(st=>streetChart(st,axis(d))).join('')}</div><div class="monitor-legend card-body"><span><i class="avg"></i>Average</span><small>Hover a point for its hour, average and number of decisions.</small></div>`)}
   ${card('Human ring seats per hour',humanChart(d,axis(d))+`<div class="card-body"><p class="sub">${esc(d.human_seats?.note||'')} ${filters.machine==='all'?'All observed ring tables on this site.':'Ring tables with seated bot entries on the selected PC; a shared table is counted once.'} Uses the date and PC filters. Opponent count applies to decision times only. Averages use valid sampled minutes; unsampled minutes are unknown. Decision times include all game formats. Presence alone does not establish a cause for slower decisions.</p></div>`)}
   ${card('Missed actions per hour',missedChart(d.series,axis(d)))}
   ${card('Missed actions per day',dailyChart(d.missed_daily))}
   ${card('By street',table(['Street','Decisions','Average','Half under','90% under','Slowest','2 s or more'],d.streets.map(s=>`<tr><td><strong>${esc(s.name)}</strong></td><td>${s.decisions.toLocaleString()}</td><td>${esc(ms(s.avg_ms))}</td><td>${s.decisions?esc(under(s.p50_under_ms).replace('under ','')):'—'}</td><td>${s.decisions?esc(under(s.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(s.max_ms))}</td><td>${pct(s.slow_share)}</td></tr>`)))}
   ${card('By PC',d.per_machine.length?table(['PC','Decisions','Average','90% under','Slowest','Unplanned sit-outs','Acted by the clock'],d.per_machine.map(p=>`<tr><td><strong>${esc(p.name)}</strong></td><td>${p.decisions.toLocaleString()}</td><td>${esc(ms(p.avg_ms))}</td><td>${p.decisions?esc(under(p.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(p.max_ms))}</td><td>${p.sit_out}</td><td>${p.clock_acted}</td></tr>`)):'<div class="card-body">'+empty('No data in this range','The PCs write decision times and missed actions every 5 minutes (release 2026.11.13.8 or later).')+'</div>')}
   ${card(`Missed actions <span class="sub">${m.total}</span>`,`<div class="card-body"><p class="sub">Uses the From, To and PC filters above. Opponent count applies to decision times.</p>${select('Rows per page','missed_page_size',filters.page_size,[['20','20'],['50','50'],['100','100']])}</div>`+`<div id="missed-rows">`+(m.recent.length?table(['Time','Bot','Table','PC','What happened'],m.recent.map(t=>`<tr><td>${esc(when(t.at))}</td><td>${esc(t.username||'—')}</td><td>${esc(t.table_name||t.table_id||'—')}</td><td>${esc(t.machine_name||t.machine)}</td><td>${t.kind==='clock_acted'?'The site acted when the bot’s time ran out':'Sat out by the table without a planned break'}</td></tr>`)):'<div class="card-body"><p class="sub">No missed actions in this range.</p></div>')+`</div><div class="card-body"><button type="button" class="button" id="missed-prev" ${m.page<=1?'disabled':''}>Previous</button> <span>Page ${m.page} of ${m.total_pages} · ${m.total?((m.page-1)*m.page_size+1):0}–${Math.min(m.page*m.page_size,m.total)} of ${m.total}</span> <button type="button" class="button" id="missed-next" ${m.page>=m.total_pages?'disabled':''}>Next</button></div>`)}`;
  if(!render(gen,'How long PDecision takes to decide, and how often bots miss their turn. Decision time is the answer from PDecision only, without the human-like pause before acting. Times are in your browser’s time zone.',body))return;
  bindCharts(d);
  $('#monitor-filters').onsubmit=e=>{e.preventDefault();const v=Object.fromEntries(new FormData(e.target));if(new Date(v.from)>=new Date(v.to)){toast('The start must be before the end',true);return;}filters={...filters,...v};pageNumber=1;h.navigate();};
  $('#monitor-reset').onclick=()=>{filters=defaults();pageNumber=1;h.navigate();};
  $('[name=missed_page_size]').onchange=e=>{filters.page_size=e.target.value;pageNumber=1;focusMissed=true;h.navigate();};
  $('#missed-prev').onclick=()=>{pageNumber--;focusMissed=true;h.navigate();};
  $('#missed-next').onclick=()=>{pageNumber++;focusMissed=true;h.navigate();};
  if(focusMissed){$('#missed-rows').scrollIntoView({block:'start'});focusMissed=false;}
 }
 return {page};
}
