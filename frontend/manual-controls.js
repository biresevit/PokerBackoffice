const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chips=n=>(Number(n)/100).toFixed(2);

export class ManualControls {
 constructor(root,requestId,api){this.root=root;this.requestId=requestId;this.api=api;this.busy=false;this.amount='';this.key=null;this.data=null;this.error='';}
 update(data){this.data=data;const key=data.payload?.manual?.turn_key;if(key!==this.key){this.key=key;this.amount='';this.error='';}this.draw();}
 disconnected(){this.error='Connection interrupted. Actions are disabled until fresh table state arrives.';this.data=null;this.draw();}
 async post(kind,body){this.busy=true;this.error='';this.draw();try{return await this.api(`tables/live/${encodeURIComponent(this.requestId)}/${kind}`,'POST',body);}catch(e){this.error=e.message;return null;}finally{this.busy=false;this.draw();}}
 draw(){
  const d=this.data,m=d?.manual||{},o=d?.payload?.manual||{},supported=!!o.supported;
  const raw=d?.captured,stamp=raw?Date.parse(raw+( /Z$|[+-]\d\d:\d\d$/.test(raw)?'':'Z')):0,fresh=stamp&&Date.now()-stamp<5000;
  const on=!!m.enabled,ack=on&&o.enabled&&o.request_id===this.requestId,latest=m.last_action;
  const pending=o.submitted||(latest&&latest.turn_key===o.turn_key&&['queued','submitted','sent','uncertain','expired','failed'].includes(latest.status));
  const allowed=ack&&fresh&&o.turn_key&&!pending&&!this.busy;
  let note=!supported?'Manual control requires the latest PokerController release.':!fresh?'Waiting for fresh table state.':m.other_window?'This hero is controlled in another live window.':!on?'Automatic play is on.':!ack?'Waiting for the bot to acknowledge manual control.':pending?'Action submitted; waiting for the table.':!o.turn_key?'Manual control is on. Waiting for hero’s turn.':'Your turn. Choose an action.';
  if(latest&&latest.turn_key===o.turn_key&&latest.detail)note=latest.detail;
  const readonly=!!m.read_only;
  const actions=o.actions||[],wager=actions.includes('raise')?'raise':actions.includes('bet')?'bet':null;
  if(!this.amount)this.amount=chips(o.min_target_minor||0);
  const focused=this.root.querySelector('input[name="manual-amount"]')===document.activeElement;
  // Polls must not replace a focused amount field or discard an unfinished edit.
  if(focused&&!this.busy&&this.renderKey===`${on}:${ack}:${allowed}:${o.turn_key}:${pending}`){const n=this.root.querySelector('.manual-note');if(n)n.textContent=this.error||note;return;}
  this.renderKey=`${on}:${ack}:${allowed}:${o.turn_key}:${pending}`;
  this.root.innerHTML=`<section class="manual-control"><label class="manual-switch"><input type="checkbox" role="switch" aria-label="Take manual control of hero at this table" ${on?'checked':''} ${this.busy||readonly||!supported||m.other_window||!fresh?'disabled':''}><strong>Manual control of ${escape(d?.hero||'hero')}</strong></label><p class="manual-note" role="status">${escape(this.error||note)}</p>${on?'<p class="sub">Automatic decisions are paused for this hero at this table. Closing this window returns control to automatic play within 45 seconds.</p>':''}${allowed?`<div class="manual-actions">${actions.includes('fold')?'<button class="button manual-fold" data-action="fold">Fold</button>':''}${actions.includes('check')?'<button class="button" data-action="check">Check</button>':actions.includes('call')?`<button class="button" data-action="call">Call ${chips(o.call_minor)}</button>`:''}${wager?`<button class="button primary" data-action="${wager}">${wager==='bet'?'Bet':'Raise to'} ${escape(this.amount)}</button>`:''}</div>${wager?`<div class="manual-sizing"><label>${wager==='bet'?'Bet total':'Raise to total'}<span class="manual-amount-row"><button class="button" data-adjust="-1" aria-label="Decrease bet">−</button><input name="manual-amount" type="number" step="0.01" min="${chips(o.min_target_minor)}" max="${chips(o.max_target_minor)}" value="${escape(this.amount)}" inputmode="decimal"><button class="button" data-adjust="1" aria-label="Increase bet">+</button></span></label><span class="sub">Min ${chips(o.min_target_minor)} · Max ${chips(o.max_target_minor)}</span><div class="manual-shortcuts">${[[1/3,'1/3'],[2/3,'2/3'],[3/4,'3/4'],[1,'Pot size']].map(([f,label])=>`<button class="button small" data-fraction="${f}">${label}</button>`).join('')}</div></div>`:''}`:''}</section>`;
  this.root.querySelector('[role="switch"]').onchange=async e=>{const enabled=e.target.checked;const r=await this.post('manual',{enabled});if(r&&this.data){this.data.manual={...this.data.manual,enabled};this.draw();}};
  const input=this.root.querySelector('[name="manual-amount"]');
  const set=v=>{this.amount=chips(Math.max(o.min_target_minor,Math.min(o.max_target_minor,Math.round(v))));if(input)input.value=this.amount;this.root.querySelector(`[data-action="${wager}"]`).textContent=`${wager==='bet'?'Bet':'Raise to'} ${this.amount}`;};
  if(input)input.oninput=()=>{this.amount=input.value;this.root.querySelector(`[data-action="${wager}"]`).textContent=`${wager==='bet'?'Bet':'Raise to'} ${this.amount}`;};
  this.root.querySelectorAll('[data-adjust]').forEach(b=>b.onclick=()=>set(Number(this.amount)*100+Number(b.dataset.adjust)*o.step_minor));
  this.root.querySelectorAll('[data-fraction]').forEach(b=>b.onclick=()=>set(o.hero_bet_minor+o.call_minor+Number(b.dataset.fraction)*(o.pot_minor+(d.payload.seats||[]).reduce((sum,s)=>sum+Math.round(Number(s.bet||0)*100),0)+o.call_minor)));
  this.root.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{const r=await this.post('action',{turn_key:o.turn_key,action:b.dataset.action,amount:this.amount});if(r&&this.data){this.data.manual.last_action={turn_key:o.turn_key,status:r.status,detail:'Action queued for this turn.'};this.draw();}});
 }
}
