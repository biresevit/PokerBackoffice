// Answers are always rendered as escaped text, including model and evidence strings.
export function installDiagnostics({$,esc,state,pages,render,siteApi}){
 pages.diagnostics=async gen=>{
  const d=await siteApi('diagnostics');
  const active=()=>gen===state.generation;
  let selected=null,busy=false;
  if(!render(gen,'Ask about ring, SNG and MTT operations. Each answer uses read-only evidence for the selected site.',`
   <div class="diagnostics-layout"><aside class="card diagnosis-history"><h2>Your requests</h2><p>Private to you and this site.</p><div id="diagnosis-history"></div></aside>
   <section><div class="card diagnosis-compose"><span class="pill" id="diagnosis-mode">${d.mode==='recorded'?'Recorded demonstration · no live data':'Live diagnosis'}</span>
   <h2>What would you like to investigate?</h2><form id="diagnosis-form"><label for="diagnosis-prompt">Your question</label><textarea id="diagnosis-prompt" rows="4" maxlength="2000" required placeholder="Why are fewer ring entries running than scheduled?"></textarea>
   <div class="diagnosis-examples"><button type="button" data-example="Why are fewer ring entries running than scheduled?">Ring shortfall</button><button type="button" data-example="Are SNG bots following their schedule?">SNG health</button><button type="button" data-example="Why are bots not registering for an MTT? Check plans, lobby freshness and recent results.">MTT registration</button></div>
   <button class="button primary" id="diagnosis-submit">Investigate</button><p class="sub">Diagnosis only. The agent cannot change settings, register bots, move funds or restart workers.</p></form><p id="diagnosis-error" role="alert"></p></div>
   <div id="diagnosis-answer" aria-live="polite"><div class="card diagnosis-answer"><h2>Evidence before conclusions</h2><p>Ask a question or open an earlier request. Answers distinguish confirmed facts, probable causes and missing evidence.</p></div></div></section></div>`))return;
  function history(items){
   $('#diagnosis-history').innerHTML=items.length?items.map(r=>`<button type="button" class="diagnosis-history-item ${r.id===selected?'active':''}" data-diagnosis="${esc(r.id)}"><strong>${esc(r.prompt)}</strong><small>${esc(new Date(r.created_utc).toLocaleString())} · ${esc(r.status)}</small></button>`).join(''):'<p>No requests yet.</p>';
   document.querySelectorAll('[data-diagnosis]').forEach(b=>b.onclick=()=>open(b.dataset.diagnosis));
  }
  function answer(r){
   if(!active())return;
   const result=r.result,report=result?.report;
   $('#diagnosis-answer').innerHTML=`<div class="card diagnosis-answer"><p class="sub">${esc(r.status)} · ${esc(new Date(r.created_utc).toLocaleString())}</p><h2>${esc(r.prompt)}</h2>${r.error?`<p role="alert">${esc(r.error)}</p>`:''}${!report&&!r.error?'<p><span class="spinner"></span> Gathering evidence and preparing your diagnosis…</p>':''}${report?`<p class="diagnosis-summary">${esc(report.summary)}</p>${report.findings.map(f=>`<article><span class="pill">${esc(f.certainty)}</span><h3>${esc(f.title)}</h3><p>${esc(f.explanation)}</p><small>Evidence: ${f.evidence_ids.map(esc).join(', ')}</small></article>`).join('')}<h3>Evidence gaps and limitations</h3><ul>${report.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><details><summary>Evidence collected (${result.evidence.length})</summary>${result.evidence.map(e=>`<details><summary>${esc(e.id)} · ${esc(e.source)} · ${esc(e.captured_utc)}</summary><pre>${esc(JSON.stringify(e,null,2))}</pre></details>`).join('')}</details><p class="sub">${result.mode==='recorded'?'Recorded fixture. No live data or model call.':`${Number(result.usage.total_tokens||0).toLocaleString()} model tokens used`}</p>`:''}</div>`;
  }
  async function refresh(){if(!active())return;const list=await siteApi('diagnostics');if(active())history(list.items);}
  async function open(id){
   if(!active())return;selected=id;clearInterval(state.poll);let terminal=false;
   async function poll(){
    if(!active()||selected!==id||busy)return;busy=true;
    try{const r=await siteApi('diagnostics/'+id);if(!active()||selected!==id)return;answer(r);terminal=['completed','failed'].includes(r.status);if(terminal){clearInterval(state.poll);await refresh();}}
    catch(e){if(active()&&selected===id){$('#diagnosis-error').textContent=e.message;clearInterval(state.poll);terminal=true;}}finally{busy=false;}
   }
   await poll();if(active()&&selected===id&&!terminal)state.poll=setInterval(poll,2000);
  }
  history(d.items);
  document.querySelectorAll('[data-example]').forEach(b=>b.onclick=()=>{$('#diagnosis-prompt').value=b.dataset.example;$('#diagnosis-prompt').focus();});
  $('#diagnosis-form').onsubmit=async e=>{
   e.preventDefault();const button=$('#diagnosis-submit'),prompt=$('#diagnosis-prompt').value.trim();
   button.disabled=true;$('#diagnosis-error').textContent='';
   try{const r=await siteApi('diagnostics','POST',{prompt,request_id:crypto.randomUUID()});if(!active())return;await refresh();await open(r.id);}
   catch(error){if(active())$('#diagnosis-error').textContent=error.message;}
   finally{if(active())button.disabled=false;}
  };
 };
}
