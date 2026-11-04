// Preserve links to the existing hash-routed workspace and live table windows.
const workspacePages=new Set(['overview','accounts','schedule','tables','chat','tasks','sessions','stakes','machines','updates','histories','winnings','settings','simulator','distributions']);
if(new URLSearchParams(location.search).has('live_request')||workspacePages.has(location.hash.slice(1))){
 location.replace('/backoffice'+location.search+location.hash);
}
document.querySelectorAll('[data-stake]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-stake]').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));
 document.querySelector('[data-demo-stake]').textContent=button.dataset.stake;
}));
