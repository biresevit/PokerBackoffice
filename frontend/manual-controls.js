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

export class ManualControls {
 constructor(root,requestId,api){this.root=root;this.requestId=requestId;this.api=api;this.busy=false;this.amount='';this.key=null;this.data=null;this.error='';}
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
  let note=!supported?'Manual control requires the latest PokerController release.':!fresh?'Waiting for fresh table state.':m.other_window?'This hero is controlled in another live window.':!on?(o.away?(o.leaving?'The hero is sitting out while leaving the table.':'The hero is sitting out. The bot will press I’m back automatically.'):'Automatic play is on.'):!ack?'Waiting for the bot to acknowledge manual control.':pending?'Action submitted; waiting for the table.':o.away?'The hero is sitting out. Press I’m back to play again.':!o.turn_key?(o.sit_out_pending?'The hero will sit out after this hand.':'Manual control is on. Waiting for hero’s turn.'):'Your turn. Choose an action.';
  if(latest&&latest.turn_key===o.turn_key&&latest.detail)note=latest.detail;
  if(command&&(commandBusy||(command.status!=='sent'&&command.age<30)))note=commandBusy?'Sending to the table…':command.detail||note;
  const problem=this.error||(refused||(command&&['failed','uncertain'].includes(command.status)&&command.age<30)?note:'');
  const readonly=!!m.read_only;
  const actions=o.actions||[],wager=actions.includes('raise')?'raise':actions.includes('bet')?'bet':null;
  if(!this.amount)this.amount=chips(o.min_target_minor||0);
  const sizing=wager&&allowed?amountProblem(this.amount,o,wager):'';
  const tableControls=on&&ack&&fresh&&o.table_commands&&!this.busy&&!commandBusy&&!readonly;
  const sit=tableControls?(o.away?'<button class="button primary" data-command="sit_in">I’m back</button>':!o.sit_out_pending?'<button class="button" data-command="sit_out">Sit out next hand</button>':''):'';
  const focused=this.root.querySelector('input[name="manual-amount"]')===document.activeElement;
  const renderKey=`${on}:${ack}:${allowed}:${o.turn_key}:${pending}:${sit}`;
  // Polls must not replace a focused amount field or discard an unfinished edit.
  if(focused&&!this.busy&&this.renderKey===renderKey){this.note(problem||note,!!problem);return;}
  this.renderKey=renderKey;
  this.root.innerHTML=`<section class="manual-control"><label class="manual-switch"><input type="checkbox" role="switch" aria-label="Take manual control of hero at this table" ${on?'checked':''} ${this.busy||readonly||!supported||m.other_window||!fresh?'disabled':''}><strong>Manual control of ${escape(d?.hero||'hero')}</strong></label><p class="manual-note" role="status"></p>${on?'<p class="sub">Automatic decisions are paused for this hero at this table. Once you act on a hand, finish it here: turning this off or closing this window returns control to automatic play from the next hand.</p>':''}${allowed?`<div class="manual-actions">${actions.includes('fold')?'<button class="button manual-fold" data-action="fold">Fold</button>':''}${actions.includes('check')?'<button class="button" data-action="check">Check</button>':actions.includes('call')?`<button class="button" data-action="call">Call ${chips(o.call_minor)}</button>`:''}${wager?`<button class="button primary" data-action="${wager}" ${sizing?'disabled':''}>${wager==='bet'?'Bet':'Raise to'} ${escape(this.amount)}</button>`:''}</div>${wager?`<div class="manual-sizing"><label>${wager==='bet'?'Bet total':'Raise to total'}<span class="manual-amount-row"><button class="button" data-adjust="-1" aria-label="Decrease bet">−</button><input name="manual-amount" type="text" inputmode="decimal" autocomplete="off" value="${escape(this.amount)}" aria-describedby="manual-amount-error"><button class="button" data-adjust="1" aria-label="Increase bet">+</button></span></label><span class="sub">Min ${chips(o.min_target_minor)} · Max ${chips(o.max_target_minor)}</span><p class="manual-amount-error" id="manual-amount-error" role="alert">${escape(sizing)}</p><div class="manual-shortcuts">${[[1/3,'1/3'],[2/3,'2/3'],[3/4,'3/4'],[1,'Pot size']].map(([f,label])=>`<button class="button small" data-fraction="${f}">${label}</button>`).join('')}</div></div>`:''}`:''}${sit?`<div class="manual-table-commands">${sit}</div>`:''}</section>`;
  this.note(problem||note,!!problem);
  this.root.querySelector('[role="switch"]').onchange=async e=>{const enabled=e.target.checked;const r=await this.post('manual',{enabled});if(r&&this.data){this.data.manual={...this.data.manual,enabled};this.draw();}};
  const input=this.root.querySelector('[name="manual-amount"]'),button=wager&&this.root.querySelector(`[data-action="${wager}"]`),hint=this.root.querySelector('.manual-amount-error');
  const show=()=>{const issue=amountProblem(this.amount,o,wager);if(button){button.textContent=`${wager==='bet'?'Bet':'Raise to'} ${this.amount}`;button.disabled=!!issue;}if(hint)hint.textContent=issue;};
  const set=v=>{this.amount=chips(Math.max(o.min_target_minor,Math.min(o.max_target_minor,Math.round(v))));if(input)input.value=this.amount;show();};
  if(input){input.oninput=()=>{this.amount=input.value;show();};input.onblur=()=>{const v=parseMinor(this.amount);if(v!==null)set(v);};input.onkeydown=e=>{if(e.key==='Enter'&&button&&!button.disabled)button.click();};}
  this.root.querySelectorAll('[data-adjust]').forEach(b=>b.onclick=()=>set((parseMinor(this.amount)??o.min_target_minor)+Number(b.dataset.adjust)*o.step_minor));
  this.root.querySelectorAll('[data-fraction]').forEach(b=>b.onclick=()=>set(o.hero_bet_minor+o.call_minor+Number(b.dataset.fraction)*(o.pot_minor+(d.payload.seats||[]).reduce((sum,s)=>sum+Math.round(Number(s.bet||0)*100),0)+o.call_minor)));
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
