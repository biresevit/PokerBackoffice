// Schedule page, MTT tab: every MTT the lobby lists, grouped by its name without the date (a daily MTT is one row),
// and the plan for each: total bots, bots that rebuy / re-enter and take the add-on, the share registered before the
// start and how many hours before it early registration begins. A plan applies to every start of that MTT.
export function installMtts(h){
 const {$,esc,state,render,siteApi,toast,table,card,pill,modal}=h;
 let filters={q:'',planned:false};
 const when=(v,zone)=>v?new Intl.DateTimeFormat(undefined,{weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:zone}).format(new Date(v)):'—';
 const clock=(v,zone)=>v?new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',timeZone:zone}).format(new Date(v)):'—';
 const fromNow=v=>{const m=Math.round((new Date(v)-Date.now())/60000);if(Math.abs(m)<60)return m>=0?`in ${m} min`:`${-m} min ago`;const hrs=Math.round(m/60);return Math.abs(hrs)<48?(hrs>=0?`in ${hrs} h`:`${-hrs} h ago`):(hrs>=0?`in ${Math.round(hrs/24)} days`:`${Math.round(-hrs/24)} days ago`);};
 const yesNo=(v,label)=>v===true?pill(label,'green'):v===false?`<span class="sub">No ${esc(label.toLowerCase())}</span>`:'';
 const offers=info=>{const parts=[yesNo(info.rebuy,'Rebuy'),yesNo(info.reentry,'Re-entry'),yesNo(info.addon,'Add-on')].filter(Boolean);return parts.length?parts.join(' '):'<span class="sub" title="The site’s lobby does not publish rebuys, re-entries or add-ons">Not published</span>';};
 const lateReg=(info,zone)=>info.late_reg===true?`${pill('Late reg','blue')}${info.late_reg_until?` <span class="sub">until ${esc(clock(info.late_reg_until,zone))}</span>`:info.late_reg_level?` <span class="sub">level ${esc(info.late_reg_level)}</span>`:''}`:info.late_reg===false?'<span class="sub">No late reg</span>':'<span class="sub" title="Unknown: every planned bot registers before the start">Unknown</span>';
 const recurs=r=>r.recurring?`${pill(r.pattern==='daily'?'Daily':r.pattern==='weekly'?'Weekly':r.pattern,'')} <span class="sub">${r.count} starts seen</span>`:'<span class="sub">One-off</span>';
 const planText=p=>p&&p.total?`<strong>${p.total} bot${p.total===1?'':'s'}</strong><br><span class="sub">${p.rebuy} rebuy/re-entry · ${p.addon} add-on · ${p.early_percent}% from ${p.early_hours} h before</span>`:'<span class="sub">No bots</span>';
 const amount=(v,cur)=>Number(v)?`${Number(v).toLocaleString()} ${esc(cur)}`:'Freeroll';

 async function page(gen,tabs){
  const d=await siteApi('mtts');const zone=d.timezone;
  if(!render(gen,'Plan each MTT: how many bots register, rebuy or re-enter and take the add-on, and when they register. A plan applies to every start of that MTT.',tabs+`<div id="mtt-capacity"></div><div class="notice">Times in ${esc(zone)}. Before the start, ${d.defaults.early_percent}% of the bots register by default, spread over the ${d.defaults.early_hours} hours before it; the rest register during late registration. An MTT without late registration (or where the site does not say) gets every bot before the start. Only the planned number of bots rebuy, re-enter or take the add-on, each within its account’s limits. Changes save immediately.</div><div class="history-filters compact-filters"><label class="field"><span>Search</span><input id="mtt-search" placeholder="MTT name" value="${esc(filters.q)}"></label><label class="field checkbox-field"><input type="checkbox" id="mtt-planned" ${filters.planned?'checked':''}><span>Only MTTs with bots</span></label></div><div id="mtt-list"></div>`))return;
  document.querySelectorAll('[data-schedule-format]').forEach(b=>b.onclick=()=>{state.scheduleFormat=b.dataset.scheduleFormat;h.navigate();});
  const draw=()=>{
   const q=filters.q.trim().toLowerCase();
   const rows=d.series.filter(s=>(!q||s.series.toLowerCase().includes(q))&&(!filters.planned||s.plan&&s.plan.total));
   $('#mtt-list').innerHTML=card(`MTTs in the lobby <span class="sub">${d.series.length}</span>`,rows.length?table(['MTT','Next start','Recurs','Buy-in','Rebuy · re-entry · add-on','Late registration','Next start: players · bots','Plan',''],rows.map(s=>{
    const next=s.instances[0],ip=next.plan;
    const upcoming=s.instances.length>1?`<details class="mtt-starts"><summary>${s.instances.length} starts listed</summary><ul>${s.instances.map(i=>`<li>${esc(when(i.start,zone))} · ${esc(i.state)} · ${i.players} players · ${i.bots} bots${i.plan?` (${i.plan.target_now} due now)`:''}</li>`).join('')}</ul></details>`:'';
    return `<tr data-series="${esc(s.series)}"><td><strong>${esc(s.series)}</strong>${s.game&&s.game!=='NLH'?` ${pill(s.game,'orange')}`:''}${upcoming}</td><td>${esc(when(next.start,zone))}<br><span class="sub">${esc(fromNow(next.start))}${next.state==='running'?' · running':''}</span></td><td>${recurs(s.recurrence)}</td><td>${amount(s.buy_in,d.currency)}</td><td>${offers(s.info)}</td><td>${lateReg(next.info,zone)}</td><td>${next.players} · <strong>${next.bots}</strong>${ip?`<span class="sub"> / ${ip.early+ip.late}</span><br><span class="sub">${ip.target_now} due now</span>`:''}</td><td>${planText(s.plan)}</td><td><button class="button small edit-action" data-edit-mtt="${esc(s.series)}">${s.plan?'Edit':'Plan bots'}</button></td></tr>`;})):'<div class="card-body"><p class="sub">No MTT matches. The list shows the MTTs the bots’ lobby lists right now.</p></div>');
   document.querySelectorAll('[data-edit-mtt]').forEach(b=>b.onclick=()=>edit(d.series.find(s=>s.series===b.dataset.editMtt)));
   const unlisted=d.unlisted_plans.filter(p=>p.plan&&p.plan.total);
   if(unlisted.length)$('#mtt-list').insertAdjacentHTML('beforeend',card('Plans for MTTs not listed now',table(['MTT','Plan',''],unlisted.map(p=>`<tr><td>${esc(p.series)}</td><td>${planText(p.plan)}</td><td><button class="button small edit-action" data-remove-mtt="${esc(p.series)}">Remove plan</button></td></tr>`))+'<p class="sub card-body">These apply again when the MTT is listed.</p>'));
   document.querySelectorAll('[data-remove-mtt]').forEach(b=>b.onclick=()=>remove(b.dataset.removeMtt));
  };
  const capacity=async()=>{
   let accounts;try{accounts=(await siteApi('accounts')).items;}catch{return;}
   if(gen!==state.generation||!$('#mtt-capacity'))return;
   const cap=h.accountCapacity(accounts).MTT,peak=Math.max(0,...d.series.map(s=>s.plan?s.plan.total:0));
   $('#mtt-capacity').innerHTML=peak>cap.accounts?`<div class="notice error"><p><strong>An MTT plans ${peak} bots, but only ${cap.accounts} enabled account${cap.accounts===1?'':'s'} can play MTTs</strong> (game formats All, NLH only or SNG/MTT only). Each account registers once per MTT; MTTs that overlap share the accounts within each account’s MTT limit. Add accounts or allow MTTs on more of them on the <a href="#accounts">Accounts</a> page.</p></div>`:'';
  };
  $('#mtt-search').oninput=e=>{filters.q=e.target.value;draw();};
  $('#mtt-planned').onchange=e=>{filters.planned=e.target.checked;draw();};
  const reload=async()=>{const next=await siteApi('mtts');Object.assign(d,next);draw();capacity();};
  const remove=async series=>{try{await siteApi('mtts','DELETE',{series});toast('Plan removed');await reload();}catch(e){toast(e.message,true);}};
  const edit=s=>{
   const p=s.plan||{total:0,rebuy:0,addon:0,early_percent:d.defaults.early_percent,early_hours:d.defaults.early_hours};
   const next=s.instances[0],late=next.info.late_reg===true,known=k=>s.info[k]===false?' (this MTT has none)':'';
   const num=(label,name,value,extra,hint='')=>`<label class="field"><span>${label}</span><input name="${name}" type="number" value="${esc(value)}" ${extra} required>${hint?`<small class="sub">${hint}</small>`:''}</label>`;
   modal(`Plan bots · ${s.series}`,`<p class="sub">${s.recurrence.recurring?`Applies to every start of this ${esc(s.recurrence.pattern)} MTT.`:'Applies to this MTT and any later one with the same name.'} Next start ${esc(when(next.start,zone))}, buy-in ${amount(s.buy_in,d.currency)}.</p><div class="form-grid">${num('Total bots','total',p.total,'min="0" max="1000" step="1"','Bots that register for each start')}${num('Bots that rebuy / re-enter','rebuy',p.rebuy,'min="0" max="1000" step="1"','When they bust and it is offered'+(s.info.rebuy===false&&s.info.reentry===false?' (this MTT has neither)':''))}${num('Bots that take the add-on','addon',p.addon,'min="0" max="1000" step="1"','When it is offered'+known('addon'))}${num('Register early (%)','early_percent',p.early_percent,'min="0" max="100" step="1"',late?'The rest register during late registration':'No known late registration: every bot registers early')}${num('Early registration starts (hours before)','early_hours',p.early_hours,'min="0.25" max="72" step="0.25"')}</div><p id="mtt-preview" class="notice"></p>${s.plan?'<p><button type="button" class="button small ghost" id="mtt-remove">Remove this plan</button></p>':''}`,
    async v=>{await siteApi('mtts','PUT',{series:s.series,total:+v.total,rebuy:+v.rebuy,addon:+v.addon,early_percent:+v.early_percent,early_hours:+v.early_hours});toast('MTT plan saved');reload();},'Save plan');
   const dialog=$('#dialog'),form=$('form',dialog);
   const preview=()=>{const v=Object.fromEntries(new FormData(form)),total=+v.total||0,early=late?Math.min(total,Math.floor(total*(+v.early_percent||0)/100+.5)):total,from=new Date(new Date(next.start).getTime()-(+v.early_hours||0)*3600000);
    $('#mtt-preview').innerHTML=total?`Next start: <strong>${early}</strong> bot${early===1?'':'s'} register from ${esc(when(from,zone))} until 2 minutes before the start${late&&total-early?`, <strong>${total-early}</strong> during late registration${next.info.late_reg_until?` (until ${esc(clock(next.info.late_reg_until,zone))})`:''}`:''}. ${Math.min(+v.rebuy||0,total)} of them rebuy or re-enter and ${Math.min(+v.addon||0,total)} take the add-on.`:'No bots register for this MTT.';};
   form.addEventListener('input',preview);preview();
   if($('#mtt-remove'))$('#mtt-remove').onclick=async()=>{await remove(s.series);dialog.close();};
  };
  draw();capacity();
 }
 return {page};
}
