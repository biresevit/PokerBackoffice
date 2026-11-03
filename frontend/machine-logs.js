export function installMachineLogs({$,esc,state,pages,render,siteApi,date,pill,toast}){
 pages.logs=async gen=>{
  const data=await siteApi('updates');let mid=data.machines.some(m=>m.id===state.logMachineId)?state.logMachineId:data.machines[0]?.id;
  if(!mid){render(gen,'Request and download diagnostic logs from a PC.','<div class="notice">No machines assigned.</div>');return;}
  const allowed=state.customer.role==='operator';
  if(!render(gen,'Collect diagnostic logs without stopping poker sessions.',`<section class="card"><div class="card-head"><h2>Request logs</h2></div><form id="logs-form" class="card-body"><div class="actions"><label class="field"><span>Machine</span><select id="logs-machine">${data.machines.map(m=>`<option value="${m.id}" ${m.id===mid?'selected':''}>${esc(m.name||m.id)}</option>`).join('')}</select></label><label class="field"><span>Recent files</span><select id="logs-hours"><option value="1">Last hour</option><option value="6">Last 6 hours</option><option value="24" selected>Last 24 hours</option><option value="72">Last 3 days</option><option value="168">Last 7 days</option></select></label>${allowed?'<button class="button primary" type="submit">Request logs</button>':''}</div><p class="sub">PokerController, PDecision and updater logs are compressed into a ZIP. Large files include their recent tail. Credentials and settings files are excluded. Downloads expire after seven days.</p><p id="logs-capability" class="sub"></p><p class="dialog-error" id="logs-error" role="alert"></p></form></section><section class="card"><div class="card-head"><h2>Log requests</h2></div><div id="logs-history"></div></section>`))return;
  const current=()=>gen===state.generation;
  const refresh=async()=>{
   const requestMid=mid;
   try{
    const d=await siteApi(`machines/${mid}/logs`);if(!current()||requestMid!==mid)return;
    const m=data.machines.find(m=>m.id===mid),heartbeat=m?.log_collector_heartbeat;
    $('#logs-capability').textContent=heartbeat?`Collector ${m.log_collector_version} last connected ${date(heartbeat)}.`:'Waiting for a diagnostic collector. PCs receive it with the new signed worker release or updater 1.0.14 and later. Requests wait until the collector connects.';
    $('#logs-history').innerHTML=d.items.length?`<div class="table-wrap"><table><thead><tr><th>Requested</th><th>History</th><th>Status</th><th>Details</th><th>Download</th></tr></thead><tbody>${d.items.map(r=>`<tr><td>${date(r.created)}</td><td>${r.hours} hours</td><td>${pill(r.status,r.status==='ready'?'green':r.status==='failed'?'red':'blue')}</td><td>${esc(r.detail||'Waiting for the PC to collect logs.')}${r.size_bytes?` · ${(r.size_bytes/1048576).toFixed(1)} MB`:''}</td><td>${r.status==='ready'?`<button class="button small" data-log-download="${esc(r.id)}">Download ZIP</button>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<p class="card-body">No log requests for this machine.</p>';
    document.querySelectorAll('[data-log-download]').forEach(button=>button.onclick=async()=>{try{const d=await siteApi(`machines/${mid}/logs/${button.dataset.logDownload}/download`);const a=document.createElement('a');a.href=d.url;a.rel='noopener';a.download=d.filename;a.click();}catch(e){$('#logs-error').textContent=e.message;}});
   }catch(e){if(current())$('#logs-error').textContent=e.message;}
  };
  $('#logs-machine').onchange=async e=>{mid=+e.target.value;state.logMachineId=mid;await refresh();};
  $('#logs-form').onsubmit=async e=>{e.preventDefault();if(!allowed)return;const b=$('[type=submit]',e.currentTarget);b.disabled=true;$('#logs-error').textContent='';try{await siteApi(`machines/${mid}/logs`,'POST',{hours:+$('#logs-hours').value});toast('Log collection requested.');await refresh();}catch(err){$('#logs-error').textContent=err.message;}finally{b.disabled=false;}};
  await refresh();state.poll=setInterval(refresh,5000);
 };
}
