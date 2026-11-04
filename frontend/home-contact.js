// Compose an enquiry in the visitor's mail app; no contact data is uploaded.
export function quoteMail(form){
 const data=new FormData(form);
 const games=data.getAll('games');
 if(!games.length)return null;
 const value=name=>String(data.get(name)||'').trim();
 const body=[
  'Hello PokerFill,','',
  'I would like to discuss my requirements and receive a custom quote.','',
  `Contact: ${value('contact_name')}`,
  `Work email: ${value('contact_email')}`,
  `Poker site / company: ${value('site')}`,
  `Platform / software: ${value('platform')}`,
  `Estimated bots needed: ${value('bots')}`,
  `Game formats: ${games.join(', ')}`,
  `Preferred stakes: ${value('stakes')||'To discuss'}`,
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
 form.addEventListener('input',()=>{status.hidden=true;link.hidden=true;error.hidden=true;});
 form.addEventListener('submit',event=>{
  event.preventDefault();
  const href=quoteMail(form);
  if(!href){error.hidden=false;status.hidden=true;form.querySelector('[name="games"]').focus();return;}
  error.hidden=true;link.href=href;link.hidden=false;
  status.textContent='Your email draft is ready. Open it, review your requirements and send it to support@pokerfill.com.';
  status.hidden=false;
  link.click();
 });
}
