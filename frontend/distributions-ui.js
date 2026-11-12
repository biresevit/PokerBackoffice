// Value distributions for account settings (Accounts page): the share of accounts per value.
// New accounts follow them automatically; existing accounts change only when you apply them.
import {SETTING_GROUPS as GROUPS} from './accounts-ui.js?v=20261112.accounts2';
export function installDistributions({$,esc,siteApi,modal,toast,table,card,navigate}){
 const pct=p=>`${Number(p).toLocaleString(undefined,{maximumFractionDigits:2})}%`;
 const label=(f,v)=>{const c=(f.choices||[]).find(([k])=>String(k)===String(v));return c?c[1]:String(v);};
 const summary=f=>f.options.length?f.options.map(o=>`${pct(o.percent)} ${esc(label(f,o.value))}`).join(' · '):'<span class="muted">Not set · new accounts use the built-in defaults</span>';
 const now=(f,total)=>!total?'—':f.kind==='choice'?f.current.map(c=>`${pct(c.count*100/total)} ${esc(label(f,c.value))}`).join(' · '):
  f.distinct===1?esc(f.current[0].value):`${f.distinct} different values`;

 function editor(f,version){
  const choice=f.kind==='choice';
  const step=f.kind==='chance'?'0.00001':'1',bounds=f.kind==='chance'?'min="0" max="1"':`min="${f.min}" max="${f.max}"`;
  const row=(value='',percent='')=>choice?'':`<div class="dist-row"><input name="dist-value" type="number" step="${step}" ${bounds} value="${esc(value)}" aria-label="Value" required><input name="dist-percent" type="number" step="0.01" min="0.01" max="100" value="${esc(percent)}" aria-label="Share of accounts (%)" required><span>%</span><button type="button" class="icon-button dist-remove" aria-label="Remove value">×</button></div>`;
  const given=new Map(f.options.map(o=>[String(o.value),o.percent]));
  const body=choice
   ?`<div class="dist-rows">${f.choices.map(([k,v])=>`<div class="dist-row"><span class="dist-choice">${esc(v)}</span><input name="dist-percent" data-value="${esc(k)}" type="number" step="0.01" min="0" max="100" value="${esc(given.get(String(k))??'')}" placeholder="0" aria-label="${esc(v)} share (%)"><span>%</span></div>`).join('')}</div>`
   :`<div class="dist-rows" id="dist-rows">${(f.options.length?f.options:[{value:'',percent:100}]).map(o=>row(o.value,o.percent)).join('')}</div><button type="button" class="button small" id="dist-add">+ Add value</button>`;
  modal(f.label,`<p class="sub">Share of accounts for each value. Percentages must total 100%.${f.kind==='chance'?' Values are chances from 0 to 1, e.g. 0.33.':''}</p>${body}<p class="dist-total" id="dist-total"></p>${f.options.length?'<button type="button" class="button small danger" id="dist-clear">Remove this distribution</button>':''}`,async()=>{
   const options=[...document.querySelectorAll('#dialog .dist-row')].map(r=>{const p=$('[name=dist-percent]',r);return {value:choice?p.dataset.value:$('[name=dist-value]',r).value,percent:Number(p.value||0)};}).filter(o=>o.percent>0);
   if(!options.length)throw Error('Give at least one value a share above 0%');
   await siteApi(`accounts/distributions/${f.field}`,'PUT',{options,version});toast(`${f.label} distribution saved`);await navigate();
  },'Save distribution');
  const total=()=>{const t=[...document.querySelectorAll('#dialog [name=dist-percent]')].reduce((s,i)=>s+Number(i.value||0),0);const ok=Math.abs(t-100)<1e-9;$('#dist-total').textContent=`Total ${pct(t)}${ok?'':' — must be 100%'}`;$('#dist-total').classList.toggle('dist-bad',!ok);};
  const wire=()=>{document.querySelectorAll('#dialog [name=dist-percent]').forEach(i=>i.oninput=total);document.querySelectorAll('#dialog .dist-remove').forEach(b=>b.onclick=()=>{if(document.querySelectorAll('#dialog .dist-row').length>1){b.closest('.dist-row').remove();total();}});};
  if(!choice)$('#dist-add').onclick=()=>{$('#dist-rows').insertAdjacentHTML('beforeend',row());wire();total();};
  if($('#dist-clear'))$('#dist-clear').onclick=async()=>{await siteApi(`accounts/distributions/${f.field}`,'PUT',{options:[],version});$('#dialog').close();toast(`${f.label} distribution removed`);await navigate();};
  wire();total();
 }

 // only: apply just this one setting (the row's Apply button); otherwise choose among all defined settings.
 function apply(d,only=null){
  const set=d.fields.filter(f=>f.options.length&&(!only||f.field===only));
  if(!set.length){toast('Define a distribution first');return;}
  let preview=null;
  const intro=only
   ?`<p>${esc(set[0].label)} is reassigned on all ${d.accounts} accounts so that each value gets exactly its share, chosen at random. No other setting changes.</p><span hidden><input type="checkbox" name="dist-field" value="${set[0].field}" checked></span>`
   :`<p>Every ticked setting is reassigned on all ${d.accounts} accounts so that each value gets exactly its share, chosen at random. Settings you don't tick stay as they are.</p><fieldset class="dist-fields">${set.map(f=>`<label class="checkbox-line"><input type="checkbox" name="dist-field" value="${f.field}" checked> ${esc(f.label)} <span class="sub">${summary(f)}</span></label>`).join('')}</fieldset>`;
  modal(only?`Apply ${set[0].label} to existing accounts`:'Apply distributions to existing accounts',`${intro}<button type="button" class="button" id="dist-preview" ${only?'hidden':''}>Preview</button><div id="dist-preview-out"></div>`,async()=>{
   const fields=[...document.querySelectorAll('#dialog [name=dist-field]:checked')].map(i=>i.value);
   if(!preview||preview.key!==fields.join())throw Error('Preview the ticked settings first');
   const r=await siteApi('accounts/distributions/apply','POST',{fields,token:preview.token,version:d.version});
   toast(`${r.changed} values changed across ${r.accounts} accounts`);await navigate();
  },'Apply to accounts');
  $('#dist-preview').onclick=async()=>{
   const fields=[...document.querySelectorAll('#dialog [name=dist-field]:checked')].map(i=>i.value);
   try{$('.dialog-error').textContent='';const p=await siteApi('accounts/distributions/preview','POST',{fields});preview={...p,key:fields.join()};
    $('#dist-preview-out').innerHTML=p.fields.map(f=>{const def=d.fields.find(x=>x.field===f.field);return `<h3 class="dist-preview-title">${esc(f.label)}</h3>`+table(['Value','Share','Accounts'],f.values.map(v=>`<tr><td>${esc(label(def,v.value))}</td><td>${pct(v.percent)}</td><td>${v.accounts}</td></tr>`));}).join('');
   }catch(e){preview=null;$('.dialog-error').textContent=e.message;}
  };
  if(only)$('#dist-preview').click();
 }

 return async function draw(root){
  const d=await siteApi('accounts/distributions');
  const byField=Object.fromEntries(d.fields.map(f=>[f.field,f])),listed=new Set(GROUPS.flatMap(g=>g[1]));
  const groups=[...GROUPS,['Other',d.fields.map(f=>f.field).filter(f=>!listed.has(f))]];
  const row=f=>`<tr><td><strong>${esc(f.label)}</strong></td><td class="break-word">${summary(f)}</td><td class="break-word muted small">${now(f,d.accounts)}</td><td class="right nowrap"><span class="edit-action dist-actions"><button class="button small" data-dist="${f.field}">Edit</button><button class="button small" data-dist-apply="${f.field}">Apply</button></span></td></tr>`;
  // Defined distributions first, by group; settings without one fold into a single line per group.
  const sections=groups.map(([title,fields])=>{
   const items=fields.map(f=>byField[f]).filter(Boolean);if(!items.length)return '';
   const set=items.filter(f=>f.options.length),unset=items.filter(f=>!f.options.length);
   return `<h3 class="dist-group">${esc(title)}</h3>${set.length?`<div class="dist-section">${table(['Setting','Distribution','Now',''],set.map(row))}</div>`:''}${unset.length?`<p class="dist-unset">No distribution yet (new accounts use the built-in defaults): ${unset.map(f=>`<button class="link-button" data-dist="${f.field}">${esc(f.label)}</button>`).join(' · ')}</p>`:''}`;
  }).join('');
  root.innerHTML=card('Value distributions',
   `<p class="card-intro">How account settings are spread across your ${d.accounts} accounts. New accounts follow these automatically; existing accounts change only when you apply them.</p>`+sections,
   '<span class="edit-action"><button class="button" id="apply-distributions">Apply to existing accounts…</button></span>');
  root.querySelectorAll('[data-dist]').forEach(b=>b.onclick=()=>editor(byField[b.dataset.dist],d.version));
  root.querySelectorAll('[data-dist-apply]').forEach(b=>b.onclick=()=>apply(d,b.dataset.distApply));
  $('#apply-distributions').onclick=()=>apply(d);
 };
}
