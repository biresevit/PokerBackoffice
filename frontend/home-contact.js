// Email draft is a fallback if direct website delivery cannot be confirmed.
export function quoteMail(form){
 const data=new FormData(form);
 const games=data.getAll('games');
 if(!games.length)return null;
 const value=name=>String(data.get(name)||'').trim();
 const body=[
  'Hello PokerFill,','',
  'I would like to discuss my requirements and receive a custom quote.','',
  `Email: ${value('contact_email')}`,
  `Poker site: ${value('site')||'Not provided'}`,
  `Estimated bots needed: ${value('bots')}`,
  `Game formats: ${games.join(', ')}`,
  `Preferred testing start: ${value('preferred_start')?value('preferred_start').replace('T',' ')+' ('+Intl.DateTimeFormat().resolvedOptions().timeZone+')':'To discuss'}`,
  `Interested in the one-month free trial: ${data.has('trial')?'Yes':'Not at this stage'}`,
  '', 'Traffic plan, timezone and other requirements:', value('notes')||'To discuss',
  '', 'I understand the trial is subject to compatibility review and that I provide and fund the bot accounts.'
 ].join('\r\n');
 return 'mailto:support@pokerfill.com?subject='+encodeURIComponent('PokerFill quote and trial enquiry')+'&body='+encodeURIComponent(body);
}
const form=document.querySelector('#quote-form');
if(form){
 const status=document.querySelector('#quote-status');
 const error=document.querySelector('#quote-error');
 const link=document.querySelector('#quote-email-draft');
 const button=form.querySelector('[type="submit"]');
 const buttonText=button.textContent;
 const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
 document.querySelector('#quote-timezone').textContent=`Time zone: ${timezone}. We’ll confirm availability with you.`;
 form.addEventListener('input',()=>{status.hidden=true;link.hidden=true;error.hidden=true;});
 form.addEventListener('submit',async event=>{
  event.preventDefault();
  if(button.disabled)return;
  const href=quoteMail(form);
  if(!href){error.textContent='Select at least one game format.';error.hidden=false;status.hidden=true;form.querySelector('[name="games"]').focus();return;}
  const values=new FormData(form);
  const payload=Object.fromEntries(values);
  payload.games=values.getAll('games');payload.trial=values.has('trial');
  payload.timezone=timezone;
  error.hidden=true;link.hidden=true;status.hidden=false;
  status.textContent='Sending your enquiry…';
  button.disabled=true;button.textContent='Sending…';form.setAttribute('aria-busy','true');
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),25000);
  try{
   const result=await fetch('/api/contact',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'PokerFill'},body:JSON.stringify(payload),signal:controller.signal});
   const data=await result.json();
   if(!result.ok||data.sent!==true)throw new Error(data.error||'We could not confirm delivery. Please use the email link below.');
   status.textContent='Thank you! Your enquiry has been sent to support@pokerfill.com. We’ll reply to your email address.';
   form.reset();
  }catch(reason){
   status.hidden=true;error.hidden=false;
   error.textContent=reason.name==='AbortError'?'Delivery could not be confirmed. Please email us directly using the link below.':reason.message||'We could not confirm delivery. Please email us directly.';
   link.href=href;link.hidden=false;
  }finally{
   clearTimeout(timer);button.disabled=false;button.textContent=buttonText;form.removeAttribute('aria-busy');
  }
 });
}
