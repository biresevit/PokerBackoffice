export function installCasinoSettings({$,esc,state,pages,render,siteApi,toast,select}){
 pages.settings=async gen=>{
  const d=await siteApi('settings'),s=d.settings,nl=String.fromCharCode(10);
  const toggles=(label,name,value)=>select(label,name,String(value),[['false','Off'],['true','On']]);
  const amount=(label,name,value,help)=>`<div><label class="field"><span>${label}</span><input name="${name}" type="number" min="0" step="any" placeholder="Every stake" value="${esc(value??'')}"></label><p class="sub">${help}</p></div>`;
  const players=(name,value,what)=>`<label class="field span-all"><span>Listed players, one per line</span><textarea name="${name}" rows="4" placeholder="player1${nl}player2">${esc((value||[]).join(nl))}</textarea><small>While ${what} is on, it is used in every hand with a listed player, in ring games, SNGs and MTTs at any blind level or buy-in. Names are matched ignoring case, the same way as the winner list.</small></label>`;
  const feature=(title,switchLabel,switchName,help,prefix,what)=>`<div class="form-section"${prefix==='help'?' style="margin-top:0;padding-top:0;border-top:0"':''}><h3>${title}</h3><div class="form-grid">
     <div>${toggles(switchLabel,switchName,s[switchName])}<p class="sub">${help}</p></div>
     ${amount('Minimum big blind (ring games)',prefix+'_min_big_blind',s[prefix+'_min_big_blind'],'In table currency. Ring games with a smaller big blind do not use it. Empty: every stake.')}
     ${amount('Minimum buy-in (SNG and MTT)',prefix+'_min_buy_in',s[prefix+'_min_buy_in'],'Tournaments with a smaller buy-in do not use it. Empty: every buy-in.')}
     ${players(prefix+'_players',s[prefix+'_players'],what)}
    </div></div>`;
  const body=`<form id="casino-settings-form"><section class="card"><div class="card-head"><h2>Decision settings for ${esc(d.casino)}</h2></div><div class="card-body">
   <p>These settings apply to ${esc(state.customer.name)}’s bots on ${esc(d.casino)}. Each customer has separate settings for every poker site. PDecision picks up saved changes during its normal refresh, usually within ${d.refresh_minutes} minutes. No restart is needed.</p>
   ${!d.exists?'<div class="notice">No casino settings have been saved. PDecision currently uses its built-in rules. Save this form to set explicit values for this casino.</div>':''}
   ${state.customer.role==='viewer'?'<p class="sub">Your account has view-only access.</p>':''}
   <fieldset ${!d.editable?'disabled':''} style="border:0;padding:0;margin:24px 0 0">
    ${feature('Card sharing','Card sharing (UseHelp)','use_help','Use the hole cards of other bots at the same table when making decisions. When on, it is used from the minimums below and always against listed players.','help','card sharing')}
    ${feature('Use solver strategy vs humans','Use solver strategy vs humans','solver_vs_humans','Play the solver strategy instead of the account profiles against humans. When on, it is used from the minimums below and always against listed players. Off: account profiles against every human.','solver','the solver strategy')}
   </fieldset><p class="sub">${s.updated?`Last saved: ${esc(new Date(s.updated).toLocaleString(undefined,{timeZone:state.site.timezone}))}`:'No saved values yet.'}</p>
   <p class="dialog-error" role="alert"></p></div><div class="card-footer">${d.editable?'<button class="button primary" type="submit">Save settings</button>':'<span class="sub">Settings are read-only.</span>'}</div></section></form>`;
  if(!render(gen,'Configure the strategy settings used by PDecision.',body))return;
  $('#casino-settings-form').onsubmit=async e=>{
   e.preventDefault();if(!d.editable)return;
   const form=e.currentTarget,v=new FormData(form),button=$('button[type=submit]',form),error=$('.dialog-error',form);
   const names=key=>String(v.get(key)||'').split(/\r?\n/).map(n=>n.trim()).filter(Boolean);
   const min=key=>v.get(key)||null;
   button.disabled=true;error.textContent='';
   try{
    const result=await siteApi('settings','PUT',{version:d.version,
     use_help:v.get('use_help')==='true',help_min_big_blind:min('help_min_big_blind'),help_min_buy_in:min('help_min_buy_in'),help_players:names('help_players'),
     solver_vs_humans:v.get('solver_vs_humans')==='true',solver_min_big_blind:min('solver_min_big_blind'),solver_min_buy_in:min('solver_min_buy_in'),solver_players:names('solver_players')});
    d.version=result.version;toast('Settings saved. PDecision will pick them up during its next refresh.');await pages.settings(gen);
   }catch(err){error.textContent=err.message;}finally{button.disabled=false;}
  };
 };
}
