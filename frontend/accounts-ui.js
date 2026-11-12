// Accounts page: the account list (first tab) with a capacity summary, filters, sorting and bulk edit,
// and the value distributions (second tab). The Details dialog groups the settings into sections.
export const GAME_LABELS={'NLH,PLO4,PLO5':'All formats','NLH':'NLH only','PLO4,PLO5':'PLO only','TOURNAMENTS':'SNG/MTT only'};
const gamesOf=a=>String(a.games||'NLH,PLO4,PLO5').split(',');
// The scheduler's rules: ring tables follow the formats; tournaments are NLH (All, NLH only, SNG/MTT only).
export const playsNlhRing=a=>gamesOf(a).includes('NLH');
export const playsPloRing=a=>gamesOf(a).some(g=>g.startsWith('PLO'));
export const playsRing=a=>playsNlhRing(a)||playsPloRing(a);
export const playsTournaments=a=>gamesOf(a).includes('NLH')||gamesOf(a).includes('TOURNAMENTS');
export const schedulable=a=>a.enabled&&!a.synthetic;

// What enabled accounts can hold at once, per format: the ceiling for the weekly schedule targets.
export function capacity(items){
 const on=items.filter(schedulable),sum=(list,key)=>list.reduce((n,a)=>n+(Number(a[key])||0),0);
 const nlh=on.filter(playsNlhRing),plo=on.filter(playsPloRing),ring=on.filter(playsRing),tour=on.filter(playsTournaments);
 return {enabled:on.length,ring:{accounts:ring.length,entries:sum(ring,'max_tables')},
  nlh:{accounts:nlh.length,entries:sum(nlh,'max_tables')},plo:{accounts:plo.length,entries:sum(plo,'max_tables')},
  SNG:{accounts:tour.length,entries:sum(tour,'max_sng_entries')},MTT:{accounts:tour.length,entries:sum(tour,'max_mtt_entries')}};
}

// Settings grouped the same way in the Details dialog, the bulk editor and the distributions tab.
export const SETTING_GROUPS=[
 ['Profile & stakes',['strategy','stake','frequency','games']],
 ['Playtime',['max_minutes']],
 ['Tables & tournaments',['max_tables','max_sng_entries','max_mtt_entries','max_sng_rebuys','max_mtt_rebuys','max_sng_reentries','max_mtt_reentries']],
 ['Behaviour at the table',['post_bb_chance','run_it_twice_chance','rebuy_ring_chance','rebuy_tournament_chance','show_cards_chance','addon_chance']],
];

export function installAccounts({$,esc,state,render,siteApi,modal,toast,table,card,pill,field,select,button,navigate,tiers,drawDistributions,importDialog}){
 const store=(key,value)=>{try{if(value===undefined)return localStorage.getItem(key);localStorage.setItem(key,value);}catch{return null;}};
 const time=v=>new Date(v).toLocaleTimeString([], {timeZone:state.site.timezone,hour:'2-digit',minute:'2-digit'});
 const ms=v=>v?new Date(v).getTime():null;
 const filters=()=>state.accountFilters||(state.accountFilters={q:'',status:'all',stake:'all',games:'all',activity:'all'});
 const sort=()=>state.accountSort||(state.accountSort={key:'now',dir:-1});
 const selected=()=>state.accountSelection||(state.accountSelection=new Set());
 const PAGE_SIZES=[10,20,50,100];
 const pageSize=()=>state.accountPageSize||(state.accountPageSize=PAGE_SIZES.includes(+store('accounts.pageSize'))?+store('accounts.pageSize'):20);

 function session(a){
  const now=Date.now(),end=ms(a.session_end);
  if(a.session_start&&end)return end>now?{text:`Session until ${time(a.session_end)}`,tone:'green'}:{text:`Session ended ${time(a.session_end)} · finishing`,tone:'orange'};
  const last=ms(a.last_session_end),until=last&&last+(a.session_cooldown_minutes||0)*60000;
  if(until&&until>now)return {text:`Break until ${time(new Date(until))}`,tone:''};
  return {text:'Not in a session',tone:''};
 }
 const tierRank=t=>tiers.indexOf(t);
 const sorters={username:a=>a.username.toLowerCase(),stake:a=>tierRank(a.stake),games:a=>GAME_LABELS[a.games]||a.games,
  limits:a=>a.max_tables,played:a=>a.played_seconds,now:a=>(a.active_entries||0)*1e13+(ms(a.session_end)||0),status:a=>a.enabled?0:1};
 const visible=items=>{
  const f=filters(),q=f.q.toLowerCase();
  const rows=items.filter(a=>(!q||a.username.toLowerCase().includes(q)||String(a.profile).toLowerCase().includes(q))
   &&(f.status==='all'||(f.status==='enabled')===!!a.enabled)
   &&(f.stake==='all'||a.stake===f.stake)
   &&(f.games==='all'||f.games==='nlh'&&playsNlhRing(a)||f.games==='plo'&&playsPloRing(a)||f.games==='tournaments'&&playsTournaments(a))
   &&(f.activity==='all'||f.activity==='playing'&&a.active_entries>0||f.activity==='session'&&a.session_start||f.activity==='idle'&&!a.active_entries&&!a.session_start));
  const {key,dir}=sort(),value=sorters[key];
  return rows.sort((x,y)=>{const a=value(x),b=value(y);return (a<b?-1:a>b?1:0)*dir||x.username.localeCompare(y.username);});
 };

 function summary(items){
  const c=capacity(items),playing=items.filter(a=>a.active_entries>0).length;
  const chip=(label,value,note)=>`<div class="capacity-chip"><span>${label}</span><strong>${value}</strong>${note?`<small>${note}</small>`:''}</div>`;
  return `<div class="capacity-strip">${chip('Accounts',items.length,`${c.enabled} enabled · ${playing} playing now`)}${chip('Ring NLH',c.nlh.accounts,`up to ${c.nlh.entries} tables`)}${chip('Ring PLO',c.plo.accounts,`up to ${c.plo.entries} tables`)}${chip('SNG',c.SNG.accounts,`${c.SNG.entries} at once`)}${chip('MTT',c.MTT.accounts,`${c.MTT.entries} at once`)}</div><p class="capacity-note">Enabled accounts only. An account plays the game formats set on it; SNGs and MTTs are NLH, so PLO-only accounts never register for them.</p>`;
 }

 function filterBar(){
  const f=filters(),opt=(name,value,list)=>`<select data-filter="${name}" aria-label="${name}">${list.map(([k,v])=>`<option value="${k}" ${k===value?'selected':''}>${v}</option>`).join('')}</select>`;
  return `<div class="toolbar account-toolbar"><input class="search" id="search" placeholder="Search username or profile…" value="${esc(f.q)}">
   ${opt('status',f.status,[['all','All statuses'],['enabled','Enabled'],['paused','Paused']])}
   ${opt('stake',f.stake,[['all','All stakes'],...tiers.map(t=>[t,t[0].toUpperCase()+t.slice(1)])])}
   ${opt('games',f.games,[['all','All game formats'],['nlh','Plays NLH ring'],['plo','Plays PLO ring'],['tournaments','Plays SNG/MTT']])}
   ${opt('activity',f.activity,[['all','Any activity'],['playing','Playing now'],['session','In a session'],['idle','Idle']])}
   <span class="account-count" id="account-count"></span>
   <span class="edit-action bulk-actions" id="bulk-actions" hidden><span id="bulk-count"></span><button class="button small" id="bulk-edit">Edit selected…</button><button class="button small ghost" id="bulk-clear">Clear</button></span></div>`;
 }

 function rows(items,d){
  const all_=visible(items),chosen=selected(),size=pageSize(),pages=Math.max(1,Math.ceil(all_.length/size));
  state.accountPage=Math.min(Math.max(1,state.accountPage||1),pages);
  const first=(state.accountPage-1)*size,list=all_.slice(first,first+size);
  for(const id of [...chosen])if(!items.some(a=>a.id===id))chosen.delete(id);
  const {key,dir}=sort(),head=(k,label)=>`<button class="sort-head${key===k?' active':''}" data-sort="${k}" aria-label="Sort by ${label}">${label}${key===k?(dir>0?' ↑':' ↓'):''}</button>`;
  const all=list.length&&list.every(a=>chosen.has(a.id));
  $('#account-count').textContent=all_.length===items.length?`${items.length} accounts`:`${all_.length} of ${items.length} accounts`;
  $('#account-rows').innerHTML=list.length?table([`<input type="checkbox" id="select-all" aria-label="Select all on this page" ${all?'checked':''}>`,head('username','Account'),head('stake','Stake'),head('games','Games'),head('limits','Limits'),head('played','Played today'),head('now','Now'),head('status','Status'),''],list.map(a=>{
   const s=session(a);
   return `<tr class="${chosen.has(a.id)?'selected':''}"><td><input type="checkbox" data-select="${a.id}" aria-label="Select ${esc(a.username)}" ${chosen.has(a.id)?'checked':''}></td>
    <td><strong>${esc(a.username)}</strong><span class="sub">${esc(a.profile)} · ${esc(a.frequency)} frequency</span>${a.synthetic?'<span class="sub">Simulation only</span>':''}</td>
    <td>${pill(a.stake)}</td><td>${esc(GAME_LABELS[a.games]||a.games)}</td>
    <td><span title="Maximum tables · SNG entries at once · MTT entries at once">${a.max_tables} tables</span><span class="sub">SNG ${a.max_sng_entries??1} · MTT ${a.max_mtt_entries??1}</span></td>
    <td>${Math.floor(a.played_seconds/60)} / ${a.max_minutes} min<div class="meter"><span style="width:${Math.min(100,a.played_seconds/60/Math.max(1,a.max_minutes)*100)}%"></span></div></td>
    <td><strong>${a.active_entries??0}</strong>${a.active_entries?`<span class="sub">${a.active_tables} ${a.active_tables===1?'table':'tables'} · ${a.active_tournaments} ${a.active_tournaments===1?'tournament':'tournaments'}</span>`:''}${a.unconfirmed_entries?`<span class="sub">${a.unconfirmed_entries} pending / unconfirmed</span>`:''}<span class="sub session-state ${s.tone}">${esc(s.text)}</span></td>
    <td>${pill(a.enabled?'Enabled':'Paused',a.enabled?'green':'orange')}</td><td class="right"><button class="button small" data-edit="${a.id}">Details</button></td></tr>`;})):
   `<div class="empty"><h3>No accounts match</h3><p>Change the search or the filters above.</p></div>`;
  $('#account-pager').innerHTML=all_.length?`<div class="pagination account-pagination"><label class="page-size">Rows per page <select id="account-page-size" aria-label="Rows per page">${PAGE_SIZES.map(n=>`<option value="${n}" ${n===size?'selected':''}>${n}</option>`).join('')}</select></label><button class="button small" id="account-prev" ${state.accountPage<=1?'disabled':''}>← Previous</button><span>${first+1}–${first+list.length} of ${all_.length} · page ${state.accountPage} of ${pages}</span><button class="button small" id="account-next" ${state.accountPage>=pages?'disabled':''}>Next →</button></div>`:'';
  if(all_.length){
   $('#account-prev').onclick=()=>{state.accountPage--;rows(items,d);};
   $('#account-next').onclick=()=>{state.accountPage++;rows(items,d);};
   $('#account-page-size').onchange=e=>{state.accountPageSize=+e.target.value;store('accounts.pageSize',e.target.value);state.accountPage=1;rows(items,d);};
  }
  const update=()=>{const n=chosen.size;$('#bulk-actions').hidden=!n;$('#bulk-count').textContent=`${n} selected`;};
  document.querySelectorAll('[data-select]').forEach(b=>b.onchange=()=>{const id=+b.dataset.select;b.checked?chosen.add(id):chosen.delete(id);b.closest('tr').classList.toggle('selected',b.checked);update();});
  if($('#select-all'))$('#select-all').onchange=e=>{list.forEach(a=>e.target.checked?chosen.add(a.id):chosen.delete(a.id));rows(items,d);};
  document.querySelectorAll('[data-sort]').forEach(b=>b.onclick=()=>{const s=sort();state.accountSort={key:b.dataset.sort,dir:s.key===b.dataset.sort?-s.dir:(b.dataset.sort==='username'||b.dataset.sort==='games'?1:-1)};state.accountPage=1;rows(items,d);});
  document.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>editAccount(items.find(a=>a.id===+b.dataset.edit),d.version));
  update();
 }

 async function bulkEdit(d){
  const ids=[...selected()],dist=await siteApi('accounts/distributions');
  const specs=Object.fromEntries(dist.fields.map(f=>[f.field,f]));
  const options=[['enabled','Scheduling (enabled / paused)'],...SETTING_GROUPS.flatMap(([group,fields])=>fields.filter(f=>specs[f]).map(f=>[f,`${group} · ${specs[f].label}`]))];
  const input=name=>{
   if(name==='enabled')return select('New value','value','true',[['true','Enabled'],['false','Paused']]);
   const f=specs[name];
   if(f.kind==='choice')return select('New value','value',f.choices[0][0],f.choices);
   return f.kind==='chance'?field('New value (chance 0–1)','value','','number','min="0" max="1" step="0.00001" required'):field('New value','value','','number',`min="${f.min}" max="${f.max}" step="1" required`);
  };
  modal(`Edit ${ids.length} account${ids.length===1?'':'s'}`,`<p class="sub">Sets one setting to the same value on every selected account. Other settings stay as they are.</p>${select('Setting','field','games',options)}<div id="bulk-value">${input('games')}</div><p class="sub" id="bulk-hint"></p>`,async v=>{
   const value=v.field==='enabled'?v.value==='true':v.value;
   const r=await siteApi('accounts/bulk','POST',{ids,field:v.field,value,version:d.version});
   toast(`${r.label} updated on ${r.accounts} account${r.accounts===1?'':'s'}`);selected().clear();await navigate();
  },'Apply to selected');
  const hint=()=>{$('#bulk-hint').textContent=$('#dialog [name=field]').value==='games'?'SNGs and MTTs are NLH: All formats, NLH only and SNG/MTT only register for them; PLO only never does. SNG/MTT only never joins a ring table.':'';};
  $('#dialog [name=field]').onchange=e=>{$('#bulk-value').innerHTML=input(e.target.value);hint();};hint();
 }

 function editAccount(a,version){
  const num=(label,name,value,extra)=>field(label,name,value,'number',extra);
  const chance=(label,name)=>num(label,name,a[name],'min="0" max="1" step="any" required');
  const section=(title,body,open=true,note='')=>`<details class="settings-section" ${open?'open':''}><summary>${title}</summary>${note?`<p class="sub">${note}</p>`:''}<div class="form-grid">${body}</div></details>`;
  modal(a.username,
   section('Profile & stakes',select('Profile','strategy',a.strategy,Object.entries(state.me.profiles))+select('Stake tier','stake',a.stake,tiers)+select('Playing frequency','frequency',a.frequency,tiers)
    +select('Game formats','games',a.games||'NLH,PLO4,PLO5',[['NLH,PLO4,PLO5','All formats'],['NLH','NLH only'],['PLO4,PLO5','PLO4 and PLO5 only'],['TOURNAMENTS','MTT/SNG only']])
    +`<label class="checkbox-line span-all"><input type="checkbox" name="enabled" ${a.enabled?'checked':''} ${a.synthetic?'disabled':''}> Enable scheduling</label>`,true,
    'Ring tables follow the game formats. SNGs and MTTs are NLH: All formats, NLH only and MTT/SNG only register for them; PLO4 and PLO5 only never does. MTT/SNG only never joins a ring table.')
   +section('Tables & tournaments',num('Maximum tables','max_tables',a.max_tables,'min="1" max="100" required')+num('Maximum SNG entries at once','max_sng_entries',a.max_sng_entries??1,'min="1" max="100" required')
    +num('Maximum MTT entries at once','max_mtt_entries',a.max_mtt_entries??1,'min="1" max="100" required')+num('Maximum rebuys per SNG','max_sng_rebuys',a.max_sng_rebuys??3,'min="0" max="100" required')
    +num('Maximum rebuys per MTT','max_mtt_rebuys',a.max_mtt_rebuys??3,'min="0" max="100" required')+num('Maximum re-entries per SNG','max_sng_reentries',a.max_sng_reentries??1,'min="0" max="100" required')
    +num('Maximum re-entries per MTT','max_mtt_reentries',a.max_mtt_reentries??1,'min="0" max="100" required'))
   +section('Playtime & sessions',num('Daily playtime preference (minutes)','max_minutes',a.max_minutes,'min="1" max="1440" required')+num('Between sessions (minutes)','session_cooldown_minutes',a.session_cooldown_minutes,'min="0" max="1440" required')
    +num('Session minimum (minutes)','session_min_minutes',a.session_min_minutes,'min="1" max="1440" required')+num('Session maximum (minutes)','session_max_minutes',a.session_max_minutes,'min="1" max="1440" required'),true,
    'Daily playtime is a preference: the scheduler can exceed it to meet the schedule.')
   +section('Breaks',num('Break every, at least (minutes of play)','break_every_min_minutes',a.break_every_min_minutes,'min="1" max="1440" required')+num('Break every, at most (minutes of play)','break_every_max_minutes',a.break_every_max_minutes,'min="1" max="1440" required')
    +num('Shortest break (seconds)','break_min_seconds',a.break_min_seconds,'min="10" max="300" required')+num('Longest break (seconds)','break_max_seconds',a.break_max_seconds,'min="10" max="300" required'),false,
    'During a break the bot sits out on all its tables after the current hand, keeps its seats and returns automatically; short breaks are more likely than long ones.')
   +section('Behaviour at the table',chance('Post big blind chance','post_bb_chance')+chance('Run it twice chance','run_it_twice_chance')+chance('Rebuy chance at ring tables','rebuy_ring_chance')
    +chance('Rebuy chance in SNG / MTT','rebuy_tournament_chance')+chance('Show cards chance (strong hands and won bluffs)','show_cards_chance')+chance('Add-on chance in tournaments','addon_chance'),false,'Chances from 0 to 1, e.g. 0.33.')
   +`<details class="settings-section"><summary>Buy-in weights</summary><label class="field"><span>Buy-in weights (% by big blinds; must total 100)</span><textarea name="weights" rows="3">${esc(JSON.stringify(a.buy_in_weights))}</textarea></label></details>`
   +`${a.synthetic?'<p class="sub">Synthetic accounts never log in.</p>':''}<button type="button" class="button danger edit-action" id="delete-account">Delete account</button>`,
   async(v,f)=>{await siteApi(`accounts/${a.id}`,'PUT',{...v,buy_in_weights:JSON.parse(v.weights),enabled:f.enabled.checked,version});toast('Account saved');await navigate();});
  // A closed section must still not hide an invalid field: open the section of the first one the browser rejects.
  document.querySelectorAll('#dialog input,#dialog select,#dialog textarea').forEach(i=>i.addEventListener('invalid',()=>{const box=i.closest('details');if(box)box.open=true;}));
  $('#delete-account').onclick=()=>{modal('Delete account?',`<p>Remove ${esc(a.username)} from this workspace? Active entries must be closed first.</p>`,async()=>{await siteApi(`accounts/${a.id}`,'DELETE',{version});toast('Account deleted');await navigate();},'Delete account');};
 }

 async function page(gen){
  let d=await siteApi('accounts');
  const tab=state.accountsTab||store('accounts.tab')||'list';
  const tabs=`<div class="section-tabs" role="tablist" aria-label="Accounts view"><button role="tab" data-accounts-tab="list" class="${tab==='list'?'active':''}" aria-selected="${tab==='list'}">Accounts (${d.items.length})</button><button role="tab" data-accounts-tab="distributions" class="${tab==='distributions'?'active':''}" aria-selected="${tab==='distributions'}">Value distributions</button></div>`;
  const body=tab==='list'?`<div id="account-summary">${summary(d.items)}</div>`+card('Your accounts',filterBar()+'<div id="account-rows"></div><div id="account-pager"></div>'):'<div id="account-distributions"></div>';
  if(!render(gen,'Manage profiles, playing preferences and account availability.',tabs+body,`<span class="edit-action">${button('Import CSV','import')}${button('+ Add account','add',true)}</span>`))return;
  document.querySelectorAll('[data-accounts-tab]').forEach(b=>b.onclick=()=>{state.accountsTab=b.dataset.accountsTab;store('accounts.tab',b.dataset.accountsTab);navigate();});
  $('#import').onclick=()=>importDialog(d.version);
  $('#add').onclick=()=>modal('Add account',field('Username','username','','text','required maxlength="100"')+select('Profile','profile','Strong Balanced',Object.values(state.me.profiles)),async v=>{const csv=`username,profile\n"${v.username.replaceAll('"','""')}",${v.profile}`;const p=await siteApi('accounts/import-preview','POST',{csv,mode:'upsert',version:d.version});await siteApi('accounts/import','POST',{csv,mode:'upsert',version:d.version,token:p.token});toast('Account added');await navigate();},'Add account');
  clearInterval(state.poll);
  if(tab==='distributions'){
   drawDistributions($('#account-distributions')).catch(e=>{if(gen===state.generation)$('#account-distributions').innerHTML=`<div class="notice error">${esc(e.message)}</div>`;});
   return;
  }
  const draw=()=>rows(d.items,d);draw();
  $('#search').oninput=e=>{filters().q=e.target.value;state.accountPage=1;draw();};
  document.querySelectorAll('[data-filter]').forEach(s=>s.onchange=()=>{filters()[s.dataset.filter]=s.value;state.accountPage=1;draw();});
  $('#bulk-edit').onclick=()=>bulkEdit(d).catch(e=>toast(e.message));
  $('#bulk-clear').onclick=()=>{selected().clear();draw();};
  let busy=false;
  state.poll=setInterval(async()=>{if(busy||gen!==state.generation||$('#dialog')?.open)return;busy=true;try{const latest=await siteApi('accounts');if(gen===state.generation){d=latest;$('#account-summary').innerHTML=summary(d.items);draw();}}catch{}finally{busy=false;}},15000);
 }
 return {page,editAccount};
}
