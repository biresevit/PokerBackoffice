const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chips=n=>(Number(n)/100).toFixed(2);
// Accept "1,25" as well as "1.25"; return minor units, or null when the text is not an amount.
export const parseMinor=text=>{const t=String(text??'').trim().replace(',','.');if(!/^\d+(\.\d{0,2})?$|^\.\d{1,2}$/.test(t))return null;return Math.round(Number(t)*100);};
export const amountProblem=(text,o,wager)=>{
 const label=wager==='bet'?'Bet':'Raise to',v=parseMinor(text);
 if(v===null)return `Enter a chip amount like ${chips(o.min_target_minor)}.`;
 if(v<o.min_target_minor||v>o.max_target_minor)return `${label} must be between ${chips(o.min_target_minor)} and ${chips(o.max_target_minor)}.`;
 return '';
};

// Sizing presets as on the table: multiples of the big blind (or of the bet faced) before the flop, pot fractions after.
const PREFLOP=[[2,'2BB'],[2.5,'2.5BB'],[3,'3BB'],['max','Max']],POSTFLOP=[[1/3,'33%'],[1/2,'50%'],[3/4,'75%'],[1,'Pot']];
export const presetTarget=(value,o,payload)=>{
 if(value==='max')return o.max_target_minor;
 const bets=(payload?.seats||[]).map(s=>Math.round(Number(s.bet||0)*100));
 if(payload?.street==='Preflop'){const bb=Math.round(Number(payload.big_blind||0)*100)||o.step_minor;return Math.round(value*Math.max(bb,...bets));}
 return Math.round(o.hero_bet_minor+o.call_minor+value*(o.pot_minor+bets.reduce((a,b)=>a+b,0)+o.call_minor));
};
const kbd=k=>`<kbd>${k}</kbd>`;

export class ManualControls {
 constructor(root,requestId,api){this.root=root;this.requestId=requestId;this.api=api;this.busy=false;this.amount='';this.key=null;this.data=null;this.error='';this.keys={};
  // Keyboard shortcuts work anywhere in the live window except while typing in another field.
  document.addEventListener('keydown',e=>{
   if(e.ctrlKey||e.altKey||e.metaKey||e.repeat)return;
   const typing=e.target.closest?.('input:not([type=checkbox]):not([type=range]),textarea,select'),amount=e.target.name==='manual-amount';
   if(typing&&!amount)return;
   const key=amount?({ArrowUp:'up',ArrowDown:'down'})[e.key]:({ArrowUp:'up',ArrowDown:'down'})[e.key]||e.key.toLowerCase();
   const run=key&&this.keys[key];if(run){e.preventDefault();run();}
  });}
 update(data){this.data=data;const key=data.payload?.manual?.turn_key;if(key!==this.key){this.key=key;this.amount='';this.error='';}this.draw();}
 disconnected(){this.error='Connection interrupted. Actions are disabled until fresh table state arrives.';this.data=null;this.draw();}
 async post(kind,body){this.busy=true;this.error='';this.draw();try{return await this.api(`tables/live/${encodeURIComponent(this.requestId)}/${kind}`,'POST',body);}catch(e){this.error=e.message;return null;}finally{this.busy=false;this.draw();}}
 draw(){
  const d=this.data,m=d?.manual||{},o=d?.payload?.manual||{},supported=!!o.supported;
  const raw=d?.captured,stamp=raw?Date.parse(raw+( /Z$|[+-]\d\d:\d\d$/.test(raw)?'':'Z')):0,fresh=stamp&&Date.now()-stamp<5000;
  // The bot reports the request id as SQL Server returns it (upper case); the page holds it lower case.
  const on=!!m.enabled,ack=on&&o.enabled&&String(o.request_id||'').toLowerCase()===String(this.requestId).toLowerCase(),latest=m.last_action;
  const pending=o.submitted||(latest&&latest.turn_key===o.turn_key&&['queued','submitted','sent','uncertain'].includes(latest.status));
  const refused=latest&&latest.turn_key===o.turn_key&&['failed','expired'].includes(latest.status);
  const allowed=ack&&fresh&&o.turn_key&&!pending&&!this.busy;
  const command=m.last_command,commandBusy=command&&['queued','submitted'].includes(command.status);
  let note=!supported?'Manual control requires the latest PokerController release.':!fresh?'Waiting for fresh table state.':m.other_window?'This hero is controlled in another live window.':!on?(o.away||o.on_break?(o.leaving?'The hero is sitting out while leaving the table.':o.on_break?`Taking a break${o.break_seconds!=null?` · back in about ${o.break_seconds>=90?Math.round(o.break_seconds/60)+' min':o.break_seconds+'s'}`:' after this hand'}.`:'The hero is sitting out. The bot will press I’m back automatically.'):'Automatic play is on.'):!ack?'Waiting for the bot to acknowledge manual control.':pending?'Action submitted; waiting for the table.':o.away?'The hero is sitting out. Press I’m back to play again.':!o.turn_key?(o.sit_out_pending?'The hero will sit out after this hand.':'Manual control is on. Waiting for hero’s turn.'):'Your turn. Choose an action.';
  if(latest&&latest.turn_key===o.turn_key&&latest.detail)note=latest.detail;
  if(command&&(commandBusy||(command.status!=='sent'&&command.age<30)))note=commandBusy?'Sending to the table…':command.detail||note;
  const problem=this.error||(refused||(command&&['failed','uncertain'].includes(command.status)&&command.age<30)?note:'');
  const readonly=!!m.read_only;
  const actions=o.actions||[],wager=actions.includes('raise')?'raise':actions.includes('bet')?'bet':null;
  if(!this.amount)this.amount=chips(o.min_target_minor||0);
  const sizing=wager&&allowed?amountProblem(this.amount,o,wager):'';
  const tableControls=on&&ack&&fresh&&o.table_commands&&!this.busy&&!commandBusy&&!readonly;
  const sit=tableControls?(o.away?'<button class="button primary" data-command="sit_in">I’m back</button>':!o.sit_out_pending?'<button class="button" data-command="sit_out">Sit out next hand</button>':''):'';
  const active=document.activeElement,focused=!!active&&this.root.contains(active)&&['manual-amount','manual-slider'].includes(active.name);
  const renderKey=`${on}:${ack}:${allowed}:${o.turn_key}:${pending}:${sit}`;
  // Polls must not replace a focused amount field or slider, or discard an unfinished edit.
  if(focused&&!this.busy&&this.renderKey===renderKey){this.note(allowed&&!problem?'':problem||note,!!problem);return;}
  this.renderKey=renderKey;
  const hero=escape(d?.hero||'hero'),wagerLabel=wager==='bet'?'Bet':'Raise',presets=d?.payload?.street==='Preflop'?PREFLOP:POSTFLOP;
  const switchTitle=on?`Manual control of ${hero} is on. Once you act on a hand, finish it here; turning this off or closing the window returns to automatic play from the next hand.`:`Take manual control of ${hero} at this table`;
  const sizingHtml=wager?`<div class="manual-sizing"><div class="manual-presets">${presets.map(([value,label],i)=>`<button class="button" data-preset="${value}">${label}${kbd(i+1)}</button>`).join('')}</div><div class="manual-amount"><input name="manual-amount" type="text" inputmode="decimal" autocomplete="off" value="${escape(this.amount)}" aria-label="${wager==='bet'?'Bet':'Raise to'} total" aria-describedby="manual-amount-error"><input name="manual-slider" type="range" min="${o.min_target_minor}" max="${o.max_target_minor}" step="1" value="${parseMinor(this.amount)??o.min_target_minor}" aria-label="${wager==='bet'?'Bet':'Raise to'} amount"></div></div><p class="manual-amount-error" id="manual-amount-error" role="alert">${escape(sizing)}</p>`:'';
  const actionsHtml=`<div class="manual-actions">${actions.includes('fold')?`<button class="manual-act fold" data-action="fold">Fold${kbd('F')}</button>`:''}${actions.includes('check')?`<button class="manual-act call" data-action="check">Check${kbd('C')}</button>`:actions.includes('call')?`<button class="manual-act call" data-action="call">Call ${chips(o.call_minor)}${kbd('C')}</button>`:''}${wager?`<button class="manual-act raise" data-action="${wager}" ${sizing?'disabled':''}><span>${wagerLabel} ${escape(this.amount)}</span>${kbd('R')}</button>`:''}</div>`;
  this.root.innerHTML=`<section class="manual-control ${on?'is-on':''}"><div class="manual-head"><label class="manual-switch" title="${escape(switchTitle)}"><input type="checkbox" role="switch" aria-label="${on?`Manual control of ${hero} is on`:`Take manual control of ${hero}`}" ${on?'checked':''} ${this.busy||readonly||!supported||m.other_window||!fresh?'disabled':''}><span class="manual-track"><span></span></span>${on?'':`<strong>Manual control of ${hero}</strong>`}</label><p class="manual-note" role="status"></p></div>${allowed?sizingHtml+actionsHtml:''}${sit?`<div class="manual-table-commands">${sit}</div>`:''}</section>`;
  this.note(allowed&&!problem?'':problem||note,!!problem);
  this.root.querySelector('[role="switch"]').onchange=async e=>{const enabled=e.target.checked;const r=await this.post('manual',{enabled});if(r&&this.data){this.data.manual={...this.data.manual,enabled};this.draw();}};
  const input=this.root.querySelector('[name="manual-amount"]'),slider=this.root.querySelector('[name="manual-slider"]'),button=wager&&this.root.querySelector(`[data-action="${wager}"]`),hint=this.root.querySelector('.manual-amount-error');
  const show=()=>{const issue=amountProblem(this.amount,o,wager);if(button){button.querySelector('span').textContent=`${wagerLabel} ${this.amount}`;button.disabled=!!issue;}if(hint)hint.textContent=issue;const v=parseMinor(this.amount);if(slider&&v!==null&&document.activeElement!==slider)slider.value=v;};
  const set=v=>{this.amount=chips(Math.max(o.min_target_minor,Math.min(o.max_target_minor,Math.round(v))));if(input)input.value=this.amount;show();};
  if(input){input.oninput=()=>{this.amount=input.value;show();};input.onblur=()=>{const v=parseMinor(this.amount);if(v!==null)set(v);};input.onkeydown=e=>{if(e.key==='Enter'&&button&&!button.disabled){e.preventDefault();button.click();}};}
  if(slider)slider.oninput=()=>set(Number(slider.value));
  const presetButtons=[...this.root.querySelectorAll('[data-preset]')];
  presetButtons.forEach(b=>b.onclick=()=>set(presetTarget(b.dataset.preset==='max'?'max':Number(b.dataset.preset),o,d.payload)));
  const click=sel=>()=>{const b=this.root.querySelector(sel);if(b&&!b.disabled)b.click();};
  const step=n=>()=>set((parseMinor(this.amount)??o.min_target_minor)+n*o.step_minor);
  this.keys=allowed?{f:click('[data-action="fold"]'),c:click('[data-action="check"],[data-action="call"]'),r:click('.manual-act.raise'),b:click('.manual-act.raise'),
   up:wager?step(1):null,down:wager?step(-1):null,...Object.fromEntries(presetButtons.map((b,i)=>[String(i+1),()=>b.click()]))}:{};
  this.root.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{
   const action=b.dataset.action;let amount=this.amount;
   if(action===wager){const issue=amountProblem(amount,o,wager);if(issue){this.error=issue;this.draw();return;}amount=chips(parseMinor(amount));}
   const r=await this.post('action',{turn_key:o.turn_key,action,amount});
   if(r&&this.data){this.data.manual.last_action={turn_key:o.turn_key,status:r.status,detail:'Action queued for this turn.'};this.draw();}});
  this.root.querySelectorAll('[data-command]').forEach(b=>b.onclick=async()=>{
   const action=b.dataset.command,r=await this.post('action',{action});
   if(r&&this.data){this.data.manual.last_command={action,status:r.status,detail:'',age:0};this.draw();}});
 }
 note(text,problem){const n=this.root.querySelector('.manual-note');if(n){n.textContent=text;n.classList.toggle('manual-problem',problem);n.setAttribute('role',problem?'alert':'status');}}
}
