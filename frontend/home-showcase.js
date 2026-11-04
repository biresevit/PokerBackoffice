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
