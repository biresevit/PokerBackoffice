export function installCasinoSettings({$,esc,state,pages,render,siteApi,toast,select}){
 pages.settings=async gen=>{
  const d=await siteApi('settings'),s=d.settings;
  const toggles=(label,name,value)=>select(label,name,String(value),[['false','Off'],['true','On']]);
  const body=`<form id="casino-settings-form"><section class="card"><div class="card-head"><h2>Decision settings for ${esc(d.casino)}</h2></div><div class="card-body">
   <p>These settings apply to all bots using this casino. PDecision picks up saved changes during its normal refresh, usually within ${d.refresh_minutes} minutes. No restart is needed.</p>
   ${!d.exists?'<div class="notice">No casino settings have been saved. PDecision currently uses its built-in rules. Save this form to set explicit values for this casino.</div>':''}
   ${d.shared?'<div class="notice">This casino is shared with another customer. Ask the main administrator to change its settings.</div>':''}
   ${state.customer.role==='viewer'?'<p class="sub">Your account has view-only access.</p>':''}
   <fieldset class="form-grid" ${!d.editable?'disabled':''} style="border:0;padding:0;margin:24px 0">
    <div>${toggles('Card sharing (UseHelp)','use_help',s.use_help)}<p class="sub">Use the hole cards of other bots at the same table when making decisions.</p></div>
    <div>${select('Use account profiles against humans','profile_vs_humans',s.profile_vs_humans,[['Everyone','Everyone'],['WeakHumans','Tables without known winners'],['Never','Never']])}<p class="sub">Outside this selection, bots use the strong strategy against humans. Known winners come from the casino’s winner list.</p></div>
    <div>${select('Maximum stake for account profiles','profile_max_stake',s.profile_max_stake??'',[['','All stakes'],['Micro','Micro'],['Low','Low'],['Mid','Mid'],['High','High']])}<p class="sub">Above this stake, bots use the strong strategy.</p></div>
    <div>${toggles('Use account profiles in SNG and MTT','profile_in_tournaments',s.profile_in_tournaments)}<p class="sub">When off, tournaments use the strong strategy.</p></div>
   </fieldset><p class="sub">${s.updated?`Last saved: ${esc(new Date(s.updated).toLocaleString(undefined,{timeZone:state.site.timezone}))}`:'No saved values yet.'}</p>
   <p class="dialog-error" role="alert"></p></div><div class="card-footer">${d.editable?'<button class="button primary" type="submit">Save settings</button>':'<span class="sub">Settings are read-only.</span>'}</div></section></form>`;
  if(!render(gen,'Configure the strategy settings used by PDecision.',body))return;
  $('#casino-settings-form').onsubmit=async e=>{
   e.preventDefault();if(!d.editable)return;
   const form=e.currentTarget,v=new FormData(form),button=$('button[type=submit]',form),error=$('.dialog-error',form);
   button.disabled=true;error.textContent='';
   try{
    const result=await siteApi('settings','PUT',{version:d.version,use_help:v.get('use_help')==='true',profile_vs_humans:v.get('profile_vs_humans'),profile_max_stake:v.get('profile_max_stake')||null,profile_in_tournaments:v.get('profile_in_tournaments')==='true'});
    d.version=result.version;toast('Settings saved. PDecision will pick them up during its next refresh.');await pages.settings(gen);
   }catch(err){error.textContent=err.message;}finally{button.disabled=false;}
  };
 };
}
