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

 function chart(series){
  const points=series.filter(p=>p.decisions||p.missed);
  if(points.length<2)return '<p class="sub card-body">Not enough hours with data for a chart yet.</p>';
  const W=900,H=240,L=56,R=48,T=16,B=30,first=+new Date(points[0].at),span=Math.max(3600e3,+new Date(points.at(-1).at)-first);
  const x=p=>L+(+new Date(p.at)-first)/span*(W-L-R);
  const maxMs=Math.max(100,...points.map(p=>p.avg_ms||0))*1.15,maxMissed=Math.max(1,...points.map(p=>p.missed));
  const y=v=>H-B-(v/maxMs)*(H-T-B),ym=v=>H-B-(v/maxMissed)*(H-T-B)*.5;
  const line=points.filter(p=>p.avg_ms!=null).map((p,i)=>`${i?'L':'M'}${x(p).toFixed(1)},${y(p.avg_ms).toFixed(1)}`).join('');
  const bar=Math.max(2,(W-L-R)/Math.max(points.length,24)*.6);
  const label=v=>new Date(v).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit'});
  return `<div class="monitor-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Average decision time and missed actions per hour">
   ${[0,.25,.5,.75,1].map(f=>`<line x1="${L}" x2="${W-R}" y1="${y(maxMs*f)}" y2="${y(maxMs*f)}"/><text x="${L-6}" y="${y(maxMs*f)+4}" class="end">${esc(ms(Math.round(maxMs*f)))}</text>`).join('')}
   ${points.filter(p=>p.missed).map(p=>`<rect class="missed" x="${(x(p)-bar/2).toFixed(1)}" y="${ym(p.missed).toFixed(1)}" width="${bar.toFixed(1)}" height="${(H-B-ym(p.missed)).toFixed(1)}"><title>${esc(label(p.at))}: ${p.missed} missed</title></rect>`).join('')}
   <path class="avg" d="${line}"/>
   ${points.filter(p=>p.avg_ms!=null).map(p=>`<circle class="avg" cx="${x(p).toFixed(1)}" cy="${y(p.avg_ms).toFixed(1)}" r="3"><title>${esc(label(p.at))}: average ${esc(ms(p.avg_ms))}, slowest ${esc(ms(p.max_ms))}, ${p.decisions} decisions</title></circle>`).join('')}
   <text x="${W-R+6}" y="${ym(maxMissed)+4}">${maxMissed}</text><text x="${W-R+6}" y="${H-B+4}">0</text>
   <text x="${L}" y="${H-8}">${esc(label(points[0].at))}</text><text x="${(L+W-R)/2}" y="${H-8}" class="middle">${esc(label(points[Math.floor(points.length/2)].at))}</text><text x="${W-R}" y="${H-8}" class="end">${esc(label(points.at(-1).at))}</text>
  </svg><div class="monitor-legend"><span><i class="avg"></i>Average decision time per hour</span><span><i class="missed"></i>Missed actions per hour (right axis)</span></div></div>`;
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
   ${card('Per hour',chart(d.series))}
   ${card('By street',table(['Street','Decisions','Average','Half under','90% under','Slowest','2 s or more'],d.streets.map(s=>`<tr><td><strong>${esc(s.name)}</strong></td><td>${s.decisions.toLocaleString()}</td><td>${esc(ms(s.avg_ms))}</td><td>${s.decisions?esc(under(s.p50_under_ms).replace('under ','')):'—'}</td><td>${s.decisions?esc(under(s.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(s.max_ms))}</td><td>${pct(s.slow_share)}</td></tr>`)))}
   ${card('By PC',d.per_machine.length?table(['PC','Decisions','Average','90% under','Slowest','Unplanned sit-outs','Acted by the clock'],d.per_machine.map(p=>`<tr><td><strong>${esc(p.name)}</strong></td><td>${p.decisions.toLocaleString()}</td><td>${esc(ms(p.avg_ms))}</td><td>${p.decisions?esc(under(p.p90_under_ms).replace('under ','')):'—'}</td><td>${esc(ms(p.max_ms))}</td><td>${p.sit_out}</td><td>${p.clock_acted}</td></tr>`)):'<div class="card-body">'+empty('No data in this range','The PCs write decision times and missed actions every 5 minutes (release 2026.11.13.8 or later).')+'</div>')}
   ${card(`Missed actions <span class="sub">${m.total}</span>`,m.recent.length?table(['Time','Bot','Table','PC','What happened'],m.recent.map(t=>`<tr><td>${esc(when(t.at))}</td><td>${esc(t.username||'—')}</td><td>${esc(t.table_name||t.table_id||'—')}</td><td>${esc(t.machine_name||t.machine)}</td><td>${t.kind==='clock_acted'?'The site acted when the bot’s time ran out':'Sat out by the table without a planned break'}</td></tr>`))+(m.total>m.recent.length?`<p class="sub card-body">The latest ${m.recent.length} of ${m.total} are listed.</p>`:''):'<div class="card-body"><p class="sub">No missed actions in this range.</p></div>')}`;
  if(!render(gen,'How long PDecision takes to decide, and how often bots miss their turn. Decision time is the answer from PDecision only, without the human-like pause before acting. Times are in your browser’s time zone.',body))return;
  $('#monitor-filters').onsubmit=e=>{e.preventDefault();const v=Object.fromEntries(new FormData(e.target));if(new Date(v.from)>=new Date(v.to)){toast('The start must be before the end',true);return;}filters={...filters,...v};h.navigate();};
  $('#monitor-reset').onclick=()=>{filters=defaults();h.navigate();};
 }
 return {page};
}
