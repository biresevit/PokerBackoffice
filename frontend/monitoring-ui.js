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
 const defaults=()=>{const to=new Date(),from=new Date(to-24*3600e3);return {from:local(from),to:local(to),machine:'all',opponents:'all'};};
 let filters=null;

 // One small chart per street (average and slowest decision per hour) and one for missed actions; all share the
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
  const top=Math.max(100,...pts.map(p=>p.max_ms||0))*1.1,y=v=>H-B-(v/top)*(H-T-B);
  const path=(k)=>pts.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)},${y(p[k]).toFixed(1)}`).join('');
  const ticks=[0,.5,1].map(f=>`<line x1="${L}" x2="${W-R}" y1="${y(top*f)}" y2="${y(top*f)}"/><text x="${L-5}" y="${y(top*f)+4}" class="end">${esc(ms(Math.round(top*f)))}</text>`).join('');
  const total=pts.reduce((a,p)=>a+p.decisions,0),avg=Math.round(pts.reduce((a,p)=>a+p.avg_ms*p.decisions,0)/total);
  return `<div class="monitor-chart"><h3>${esc(s.name)} <span class="sub">${total.toLocaleString()} decisions · average ${esc(ms(avg))}</span></h3><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.name)}: average and slowest decision time per hour">${frame(ax,W,H,L,R,B,ticks)}
   ${pts.length>1?`<path class="max" d="${path('max_ms')}"/><path class="avg" d="${path('avg_ms')}"/>`:''}
   ${pts.map(p=>`<circle class="max" cx="${x(p).toFixed(1)}" cy="${y(p.max_ms).toFixed(1)}" r="2.5"><title>${esc(label(p.at))}: slowest ${esc(ms(p.max_ms))}</title></circle><circle class="avg" cx="${x(p).toFixed(1)}" cy="${y(p.avg_ms).toFixed(1)}" r="3"><title>${esc(label(p.at))}: average ${esc(ms(p.avg_ms))}, slowest ${esc(ms(p.max_ms))}, ${p.decisions} decisions</title></circle>`).join('')}
  </svg></div>`;
 }
 function missedChart(series,ax){
  const pts=series.filter(p=>p.missed);
  if(!pts.length)return '<p class="sub card-body">No missed actions in this range.</p>';
  const W=900,H=150,L=50,R=12,T=12,B=24,x=p=>L+(+new Date(p.at)-ax.first)/ax.span*(W-L-R);
  const top=Math.max(1,...pts.map(p=>p.missed)),y=v=>H-B-(v/top)*(H-T-B),bar=Math.max(3,(W-L-R)/Math.max(24,ax.span/3600e3)*.7);
  const ticks=[0,top].map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-5}" y="${y(v)+4}" class="end">${v}</text>`).join('');
  return `<div class="monitor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Missed actions per hour">${frame(ax,W,H,L,R,B,ticks)}${pts.map(p=>`<rect class="missed" x="${(x(p)-bar/2).toFixed(1)}" y="${y(p.missed).toFixed(1)}" width="${bar.toFixed(1)}" height="${(H-B-y(p.missed)).toFixed(1)}"><title>${esc(label(p.at))}: ${p.missed} missed</title></rect>`).join('')}</svg></div>`;
 }

 async function page(gen){
  filters=filters||defaults();
  const q=new URLSearchParams({from:new Date(filters.from).toISOString(),to:new Date(filters.to).toISOString(),machine:filters.machine,opponents:filters.opponents});
  const d=await siteApi(`monitoring?${q}`);
  const machineOptions=[['all','All PCs'],...d.machines.map(m=>[m.id,m.name])];
  const oppOptions=[['all','Any number'],['1','1 opponent'],['2','2 opponents'],['3','3 opponents'],['4','4 opponents'],['5','5 or more']];
  const o=d.overall,m=d.missed;
  const body=`<form id="monitor-filters" class="history-filters">
    <label class="field"><span>From</span><input type="datetime-local" name="from" value="${esc(filters.from)}" required></label>
    <label class="field"><span>To</span><input type="datetime-local" name="to" value="${esc(filters.to)}" required></label>
    ${select('PC','machine',filters.machine,machineOptions)}${select('Opponents in the hand','opponents',filters.opponents,oppOptions)}
    <button class="button primary">Apply filters</button><button type="button" class="button" id="monitor-reset">Last 24 hours</button></form>
   ${stats([['Decisions',o.decisions.toLocaleString(),'answered by PDecision'],['Average decision time',ms(o.avg_ms),`half ${under(o.p50_under_ms)}, 90% ${under(o.p90_under_ms)}`],['Slowest decision',ms(o.max_ms),`${pct(o.slow_share)} took 2 s or more`],['Missed actions',m.total.toLocaleString(),`${m.sit_out} unplanned sit-outs · ${m.clock_acted} acted by the site's clock`]])}
   ${card('Decision time per hour',`<div class="monitor-grid">${d.series_by_street.map(st=>streetChart(st,axis(d))).join('')}</div><div class="monitor-legend card-body"><span><i class="avg"></i>Average</span><span><i class="max"></i>Slowest</span><small>Hover a point for its hour, average, slowest and number of decisions.</small></div>`)}
   ${card('Missed actions per hour',missedChart(d.series,axis(d)))}
   ${card('By street',table(['Street','Decisions','Average','Half under','90% under','Slowest','2 s or more'],d.streets.map(s=>`<tr><td><strong>${esc(s.name)}</strong></td><td>${s.decisions.toLocaleString()}</td><td>${esc(ms(s.avg_ms))}</td><td>${s.decisions?esc(under(s.p50_under_ms).replace('under ','')):'—'}</td><td>${s.decisions?esc(under(s.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(s.max_ms))}</td><td>${pct(s.slow_share)}</td></tr>`)))}
   ${card('By PC',d.per_machine.length?table(['PC','Decisions','Average','90% under','Slowest','Unplanned sit-outs','Acted by the clock'],d.per_machine.map(p=>`<tr><td><strong>${esc(p.name)}</strong></td><td>${p.decisions.toLocaleString()}</td><td>${esc(ms(p.avg_ms))}</td><td>${p.decisions?esc(under(p.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(p.max_ms))}</td><td>${p.sit_out}</td><td>${p.clock_acted}</td></tr>`)):'<div class="card-body">'+empty('No data in this range','The PCs write decision times and missed actions every 5 minutes (release 2026.11.13.8 or later).')+'</div>')}
   ${card(`Missed actions <span class="sub">${m.total}</span>`,m.recent.length?table(['Time','Bot','Table','PC','What happened'],m.recent.map(t=>`<tr><td>${esc(when(t.at))}</td><td>${esc(t.username||'—')}</td><td>${esc(t.table_name||t.table_id||'—')}</td><td>${esc(t.machine_name||t.machine)}</td><td>${t.kind==='clock_acted'?'The site acted when the bot’s time ran out':'Sat out by the table without a planned break'}</td></tr>`))+(m.total>m.recent.length?`<p class="sub card-body">The latest ${m.recent.length} of ${m.total} are listed.</p>`:''):'<div class="card-body"><p class="sub">No missed actions in this range.</p></div>')}`;
  if(!render(gen,'How long PDecision takes to decide, and how often bots miss their turn. Decision time is the answer from PDecision only, without the human-like pause before acting. Times are in your browser’s time zone.',body))return;
  $('#monitor-filters').onsubmit=e=>{e.preventDefault();const v=Object.fromEntries(new FormData(e.target));if(new Date(v.from)>=new Date(v.to)){toast('The start must be before the end',true);return;}filters={...filters,...v};h.navigate();};
  $('#monitor-reset').onclick=()=>{filters=defaults();h.navigate();};
 }
 return {page};
}
