export function installCasinoSettings({$,esc,state,pages,render,siteApi,toast,select}){
 pages.settings=async gen=>{
  const d=await siteApi('settings'),s=d.settings,nl=String.fromCharCode(10);
  const toggles=(label,name,value)=>select(label,name,String(value),[['false','Off'],['true','On']]);
  const minBlind=(name,value)=>`<label class="field"><span>Minimum big blind</span><input name="${name}" type="number" min="0" step="any" placeholder="Every stake" value="${esc(value??'')}"></label>`;
  const players=(name,value,what)=>`<label class="field span-all"><span>Listed players, one per line</span><textarea name="${name}" rows="4" placeholder="player1${nl}player2">${esc((value||[]).join(nl))}</textarea><small>Used when ${what} is set to listed players. Names are matched ignoring case, the same way as the winner list.</small></label>`;
  const body=`<form id="casino-settings-form"><section class="card"><div class="card-head"><h2>Decision settings for ${esc(d.casino)}</h2></div><div class="card-body">
   <p>These settings apply to ${esc(state.customer.name)}’s bots on ${esc(d.casino)}. Each customer has separate settings for every poker site. PDecision picks up saved changes during its normal refresh, usually within ${d.refresh_minutes} minutes. No restart is needed after the customer-scoped PDecision update.</p>
   ${!d.exists?'<div class="notice">No casino settings have been saved. PDecision currently uses its built-in rules. Save this form to set explicit values for this casino.</div>':''}
   ${state.customer.role==='viewer'?'<p class="sub">Your account has view-only access.</p>':''}
   <fieldset ${!d.editable?'disabled':''} style="border:0;padding:0;margin:24px 0 0">
    <div class="form-section" style="margin-top:0;padding-top:0;border-top:0"><h3>Card sharing</h3><div class="form-grid">
     <div>${toggles('Card sharing (UseHelp)','use_help',s.use_help)}<p class="sub">Use the hole cards of other bots at the same table when making decisions.</p></div>
     <div>${select('Use card sharing in','help_vs_humans',s.help_vs_humans,[['Everyone','Every hand'],['ListedPlayers','Only hands with a listed player']])}<p class="sub">A listed player must still be in the hand.</p></div>
     <div>${minBlind('help_min_big_blind',s.help_min_big_blind)}<p class="sub">Ring games with a smaller big blind (table currency) play without card sharing. Empty: every stake. Tournaments are not limited.</p></div>
     ${players('help_players',s.help_players,'Use card sharing in')}
    </div></div>
    <div class="form-section"><h3>Account profiles against humans</h3><div class="form-grid">
     <div>${select('Use account profiles against humans','profile_vs_humans',s.profile_vs_humans,[['Everyone','Everyone'],['WeakHumans','Tables without known winners'],['ListedPlayers','Only hands with a listed player'],['Never','Never']])}<p class="sub">Outside this selection, bots use the strong strategy against humans. Known winners come from the casino’s winner list.</p></div>
     <div>${minBlind('profile_min_big_blind',s.profile_min_big_blind)}<p class="sub">Ring games with a smaller big blind (table currency) use the strong strategy against humans. Empty: every stake.</p></div>
     <div>${select('Maximum stake for account profiles','profile_max_stake',s.profile_max_stake??'',[['','All stakes'],['Micro','Micro'],['Low','Low'],['Mid','Mid'],['High','High']])}<p class="sub">Above this stake, bots use the strong strategy.</p></div>
     <div>${toggles('Use account profiles in SNG and MTT','profile_in_tournaments',s.profile_in_tournaments)}<p class="sub">When off, tournaments use the strong strategy.</p></div>
     ${players('profile_players',s.profile_players,'Use account profiles against humans')}
    </div></div>
   </fieldset><p class="sub">${s.updated?`Last saved: ${esc(new Date(s.updated).toLocaleString(undefined,{timeZone:state.site.timezone}))}`:'No saved values yet.'}</p>
   <p class="dialog-error" role="alert"></p></div><div class="card-footer">${d.editable?'<button class="button primary" type="submit">Save settings</button>':'<span class="sub">Settings are read-only.</span>'}</div></section></form>`;
  if(!render(gen,'Configure the strategy settings used by PDecision.',body))return;
  $('#casino-settings-form').onsubmit=async e=>{
   e.preventDefault();if(!d.editable)return;
   const form=e.currentTarget,v=new FormData(form),button=$('button[type=submit]',form),error=$('.dialog-error',form);
   const names=key=>String(v.get(key)||'').split(/\r?\n/).map(n=>n.trim()).filter(Boolean);
   button.disabled=true;error.textContent='';
   try{
    const result=await siteApi('settings','PUT',{version:d.version,use_help:v.get('use_help')==='true',help_vs_humans:v.get('help_vs_humans'),
     help_min_big_blind:v.get('help_min_big_blind')||null,help_players:names('help_players'),
     profile_vs_humans:v.get('profile_vs_humans'),profile_max_stake:v.get('profile_max_stake')||null,
     profile_min_big_blind:v.get('profile_min_big_blind')||null,profile_players:names('profile_players'),
     profile_in_tournaments:v.get('profile_in_tournaments')==='true'});
    d.version=result.version;toast('Settings saved. PDecision will pick them up during its next refresh.');await pages.settings(gen);
   }catch(err){error.textContent=err.message;}finally{button.disabled=false;}
  };
 };
}
