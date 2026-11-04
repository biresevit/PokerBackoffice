// Public product illustrations use local example data, never customer APIs.
const profiles=[
 ['Maniac','MA',[60,40,20,80]],['Agro Fish','AF',[40,30,12,70]],
 ['Calling Station','CS',[60,10,3,30]],['Passive Fish','PF',[40,10,5,40]],
 ['Strong Balanced','SB',[28,20,8,50]],['Strong Tight','ST',[25,18,6,40]],
 ['Strong Loose','SL',[30,25,12,65]],['Strong Mix','SM',[26,20,5,70]]
];
const metrics=['VPIP','PFR','3-BET','C-BET'];
const catalog=document.querySelector('#profile-catalog');
if(catalog)catalog.innerHTML=profiles.map(([name,initials,values])=>`<article class="profile-card"><div class="profile-identity"><span>${initials}</span><h3>${name}</h3></div><div class="profile-rings" aria-hidden="true"><svg viewBox="0 0 112 112">${values.map((v,i)=>`<circle class="ring-track" cx="56" cy="56" r="${46-i*10}"/><circle class="metric-${i}" cx="56" cy="56" r="${46-i*10}" pathLength="100" stroke-dasharray="${v} 100"/>`).join('')}</svg><b>${initials}</b></div><dl>${values.map((v,i)=>`<div class="metric-${i}"><dt>${metrics[i]}</dt><dd>${v}%</dd></div>`).join('')}</dl></article>`).join('');

const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
document.querySelectorAll('[data-mtt-bots]').forEach(button=>button.addEventListener('click',()=>{
 const bots=Number(button.dataset.mttBots);
 document.querySelectorAll('[data-mtt-bots]').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));
 document.querySelector('[data-mtt-field]').textContent=20+bots;
 document.querySelector('[data-mtt-pool]').textContent=money((20+bots)*10);
 document.querySelector('[data-mtt-funding]').textContent=money(bots*10);
 document.querySelector('[data-mtt-count]').textContent=bots;
}));

const tabs=[...document.querySelectorAll('[data-tour-tab]')];
function selectTab(tab){
 tabs.forEach(other=>{const selected=other===tab;other.setAttribute('aria-selected',String(selected));other.tabIndex=selected?0:-1;document.getElementById(other.getAttribute('aria-controls')).hidden=!selected;});
}
tabs.forEach((tab,index)=>{
 tab.addEventListener('click',()=>selectTab(tab));
 tab.addEventListener('keydown',event=>{
  let next;
  if(event.key==='ArrowRight')next=(index+1)%tabs.length;
  if(event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;
  if(event.key==='Home')next=0;
  if(event.key==='End')next=tabs.length-1;
  if(next!==undefined){event.preventDefault();selectTab(tabs[next]);tabs[next].focus();}
 });
});
const manual=document.querySelector('#demo-manual');
if(manual)manual.addEventListener('change',()=>{
 document.querySelector('#demo-action-controls').hidden=!manual.checked;
 document.querySelector('#demo-manual-status').textContent=manual.checked?'Your turn. Choose an action in this preview.':'Automatic play. Switch on manual control to preview the actions.';
});
document.querySelectorAll('[data-demo-action]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelector('#demo-manual-status').textContent=`Preview: ${button.dataset.demoAction} selected. No live action is sent.`;
}));
const chatForm=document.querySelector('#demo-chat-form');
if(chatForm)chatForm.addEventListener('submit',event=>{
 event.preventDefault();const input=document.querySelector('#demo-chat-text');const text=input.value.trim();if(!text)return;
 const message=document.createElement('div');message.className='preview-message bot-message';
 const sender=document.createElement('strong');sender.textContent='Bot A · Operator reply';
 const content=document.createElement('p');content.textContent=text;message.append(sender,content);
 const thread=document.querySelector('#demo-chat-thread');thread.append(message);while(thread.children.length>6)thread.firstElementChild.remove();thread.scrollTop=thread.scrollHeight;
 input.value='';document.querySelector('#demo-chat-status').textContent='Reply added to this illustration only. Nothing was sent to a table.';
});
