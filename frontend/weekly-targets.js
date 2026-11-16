const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock=m=>`${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;
const levels=[
 ['#f2f4ef','#53644e','#c9d2c1'],
 ['#e2edda','#234431','#9fb991'],
 ['#bfd5ad','#203f2c','#789768'],
 ['#8bb17c','#173322','#5a8051'],
 ['#46774f','#ffffff','#355e3c'],
 ['#204f3c','#ffffff','#173e2f'],
];

export function weeklyTargetChart(windows,days,timezone){
 const peak=Math.max(0,...windows.map(w=>Number(w.target)));
 const legend=[{color:levels[0][0],label:'0 / no entries'}];
 for(let i=1;i<=5;i++){
  const low=Math.floor((i-1)*peak/5)+1,high=Math.floor(i*peak/5);
  if(low<=high)legend.push({color:levels[i][0],label:low===high?`${low}`:`${low}–${high}`});
 }
 const rows=days.map((day,weekday)=>`<div class="day-row"><div class="day-label">${escape(day.slice(0,3))}</div><div class="day-track">${windows.map((w,index)=>{
  if(w.weekday!==weekday)return '';
  const duration=w.end_minute-w.start_minute,level=w.target>0?Math.min(5,Math.ceil(w.target/peak*5)):0;
  const [background,ink,border]=levels[level],start=clock(w.start_minute),end=clock(w.end_minute);
  const label=`${day}: ${start}–${end}, ${w.target} scheduled entries`;
  return `<button type="button" class="block ${duration<120?'short-window':''} ${duration<60?'tiny-window':''} ${duration<30?'very-short':''}" data-window="${index}" aria-label="${escape(label)}" title="${escape(label)}" style="left:${w.start_minute/14.4}%;width:${duration/14.4}%;--window-bg:${background};--window-ink:${ink};--window-border:${border}"><strong class="block-target">${w.target}</strong><span class="block-times"><span>${start}</span><span class="block-time-separator">–</span><span>${end}</span></span></button>`;
 }).join('')}</div></div>`).join('');
 return `<div class="weekly-targets"><div class="weekly-edit-toolbar"><button type="button" class="button small edit-action" data-edit-selected disabled>Edit window</button><button type="button" class="button small danger edit-action" data-remove-selected disabled>Remove</button><span class="sub">Select a window and click Edit, or double-click it.</span></div><div class="weekly-target-scroll" tabindex="0" aria-label="Weekly targets, local time ${escape(timezone)}"><div class="weekly-target-chart"><div class="weekly-axis-row"><span></span><div class="weekly-axis">${Array.from({length:13},(_,i)=>`<span class="weekly-time-tick ${i===0?'first':i===12?'last':''}" data-minute="${i*120}" style="left:${i/12*100}%">${clock(i*120)}</span>`).join('')}</div></div>${rows}</div></div><div class="weekly-scale"><span>Scheduled entries · lighter to darker:</span>${legend.map(item=>`<span class="weekly-scale-item"><i style="background:${item.color}"></i>${item.label}</span>`).join('')}<span class="sub">Peak: ${peak} · ${escape(timezone)}</span></div><div class="weekly-selection"><span class="weekly-selection-text" role="status">Hover or select a window for exact start and end times.</span></div></div>`;
}

export function bindWeeklyTargetChart(root,windows,days,onEdit,onRemove){
 let selected=null;
 const edit=root.querySelector('[data-edit-selected]'),remove=root.querySelector('[data-remove-selected]'),status=root.querySelector('.weekly-selection-text');
 const prompt=status.textContent;
 const show=index=>{
  if(index===null){status.textContent=prompt;return;}
  const w=windows[index];
  status.textContent=`${days[w.weekday]} · ${clock(w.start_minute)}–${clock(w.end_minute)} · ${w.target} scheduled entries`;
 };
 const select=button=>{
  selected=Number(button.dataset.window);
  root.querySelectorAll('[data-window]').forEach(b=>b.classList.toggle('is-selected',b===button));
  show(selected);
  edit.disabled=false;
  remove.disabled=!onRemove;
 };
 root.querySelectorAll('[data-window]').forEach(button=>{
  button.onmouseenter=button.onfocus=()=>show(Number(button.dataset.window));
  button.onmouseleave=button.onblur=()=>show(selected);
  button.onclick=()=>select(button);
  button.ondblclick=()=>{select(button);onEdit(selected);};
  button.onkeydown=event=>{if(event.key==='Enter'&&selected===Number(button.dataset.window)){event.preventDefault();onEdit(selected);}};
 });
 edit.onclick=()=>{if(selected!==null)onEdit(selected);};
 remove.onclick=async()=>{if(selected===null||!onRemove)return;const buttons=root.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);try{await onRemove(selected);}finally{buttons.forEach(b=>b.disabled=false);}};
}
