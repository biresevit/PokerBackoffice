export function installChat({$,esc,state,pages,render,pill,siteApi,date,toast,empty}) {
 const drafts=new Map(),lastHuman=new Map();
 let selectedTable=null,siteForSelection=null,notificationBusy=false;
 const desktopEnabled=()=>localStorage.getItem('chat-desktop-alerts')==='true';
 const statusLabel={queued:'Queued',claimed:'Sending',sent:'Confirmed',failed:'Failed',uncertain:'Unconfirmed',expired:'Expired'};
 const notify=async()=>{
  if(notificationBusy||!state.site)return;notificationBusy=true;const siteId=state.site.id;
  try{
   const d=await siteApi('chat');if(state.site.id!==siteId)return;
   const label=d.unread?`Chat (${d.unread} new)`:'Chat';
   const alert=$('#chat-alert');if(alert){alert.textContent=label;alert.classList.toggle('has-unread',d.unread>0);}
   const badge=$('#chat-nav-badge');if(badge){badge.textContent=d.unread;badge.hidden=!d.unread;}
   const latest=d.latest_human,previous=lastHuman.get(siteId);
   if(latest&&previous!==undefined&&latest.id>previous){
    if(state.page!=='chat'||selectedTable!==latest.table_id)toast(`New human chat from ${latest.author} at ${latest.table_name}. Open Chat to reply.`);
    if(desktopEnabled()&&'Notification' in window&&Notification.permission==='granted'&&(document.hidden||state.page!=='chat')){
     const n=new Notification('New table chat',{body:`${latest.author} at ${latest.table_name}`,tag:`chat-${siteId}-${latest.table_id}`});
     n.onclick=()=>{window.focus();selectedTable=latest.table_id;if(state.page==='chat')pages.chat(++state.generation).catch(error=>toast(error.message));else location.hash='chat';n.close();};
    }
   }
   lastHuman.set(siteId,latest?.id||0);
  }catch(error){/* Other pages remain usable while chat is temporarily unavailable. */}
  finally{notificationBusy=false;}
 };
 pages.chat=async gen=>{
  const siteId=state.site.id;
  if(siteForSelection!==siteId){selectedTable=null;siteForSelection=siteId;}
  let summary=await siteApi('chat'),messages=[],before=null,olderLoaded=false,initial=true,busy=false,sending=false,active=null,botSignature='';
  if(!render(gen,'Read table conversations and send a reply through a bot seated at that table.',`<div class="chat-toolbar"><span>Human messages appear here and in the Chat notification badge.</span><button class="button small" id="chat-desktop">Enable desktop alerts</button></div><div class="chat-layout"><section class="card chat-conversations"><div class="card-head"><h2>Tables</h2></div><div id="chat-tables"></div></section><section class="card chat-conversation"><div class="card-head"><div><h2 id="chat-title">Select a table</h2><span class="sub" id="chat-connection"></span></div></div><button class="button small chat-older" id="chat-older" hidden>Load earlier messages</button><div id="chat-messages" class="chat-messages" role="log" aria-label="Table messages" aria-relevant="additions"></div><form id="chat-compose" class="chat-compose"><label class="field"><span>Send as bot</span><select id="chat-bot" required></select></label><label class="field"><span>Message</span><textarea id="chat-text" rows="3" maxlength="2000" placeholder="Write a reply to the table" required></textarea></label><div class="chat-send-row"><span class="sub" id="chat-compose-note"></span><button class="button primary" id="chat-send">Send to table</button></div><p class="dialog-error" id="chat-error" role="alert"></p></form><div id="chat-requests" class="chat-requests"></div></section></div>`))return;
  const current=()=>gen===state.generation&&state.site.id===siteId;
  const desktop=$('#chat-desktop');
  const updateDesktop=()=>{desktop.textContent=!('Notification' in window)?'Desktop alerts unavailable':Notification.permission==='denied'?'Desktop alerts blocked':desktopEnabled()?'Disable desktop alerts':'Enable desktop alerts';desktop.disabled=!('Notification' in window)||Notification.permission==='denied';};
  updateDesktop();desktop.onclick=async()=>{if(desktopEnabled())localStorage.setItem('chat-desktop-alerts','false');else if(await Notification.requestPermission()==='granted')localStorage.setItem('chat-desktop-alerts','true');updateDesktop();};
  const compose=$('#chat-compose'),text=$('#chat-text'),bot=$('#chat-bot'),send=$('#chat-send');
  const updateSend=()=>{const allowed=state.customer.role==='operator',ready=active?.bots.some(b=>b.chat_ready&&b.entry_id===bot.value);send.disabled=sending||!allowed||!ready||!text.value.trim();bot.disabled=sending||!allowed;text.disabled=sending||!allowed;$('#chat-compose-note').textContent=!allowed?'Your account has view-only access.':`${text.value.length} / 2000 characters`;};
  text.oninput=()=>{if(active)drafts.set(`${siteId}:${active.table_id}`,text.value);updateSend();};bot.onchange=updateSend;
  const drawTables=()=>{
   $('#chat-tables').innerHTML=summary.items.length?summary.items.map(t=>`<button class="chat-table ${t.table_id===selectedTable?'selected':''}" data-chat-table="${esc(t.table_id)}"><span><strong>${esc(t.name)}</strong>${t.unread?`<b class="chat-unread">${t.unread}</b>`:''}</span><small>${t.bots.length} seated bots</small><p>${t.body?`${esc(t.author)}: ${esc(t.body.slice(0,90))}`:'No messages received yet'}</p></button>`).join(''):empty('No table conversations','Conversations appear when a bot is seated at a table.');
   document.querySelectorAll('[data-chat-table]').forEach(button=>button.onclick=()=>selectTable(button.dataset.chatTable));
  };
  const drawBots=()=>{
   if(!active)return;
   const signature=JSON.stringify(active.bots.map(b=>[b.entry_id,b.chat_ready]));
   if(signature!==botSignature){const previous=bot.value;bot.innerHTML=active.bots.map(b=>`<option value="${esc(b.entry_id)}" ${b.chat_ready?'':'disabled'}>${esc(b.bot)}${b.chat_ready?'':' - chat offline'}</option>`).join('');bot.value=active.bots.find(b=>b.entry_id===previous&&b.chat_ready)?.entry_id||active.bots.find(b=>b.chat_ready)?.entry_id||'';botSignature=signature;}
   $('#chat-title').textContent=active.name;
   $('#chat-connection').textContent=active.bots.some(b=>b.chat_ready)?'Chat connected':active.bots.length?'Chat offline. Start the updated PokerController worker on the machine.':'No bot is currently seated here. You can still read the conversation.';
   compose.hidden=!active.bots.length;updateSend();
  };
  const drawMessages=async(data,older=false)=>{
   const list=$('#chat-messages'),height=list.scrollHeight,atBottom=initial||list.scrollHeight-list.scrollTop-list.clientHeight<60;
   const byId=new Map([...messages,...data.items].map(m=>[m.id,m]));messages=[...byId.values()].sort((a,b)=>a.id-b.id);
   if(older||!olderLoaded)before=data.before;
   list.innerHTML=messages.length?messages.map(m=>`<article class="chat-message ${m.is_human?'human':'bot'}" data-message="${m.id}"><div><strong>${esc(m.author)}</strong>${pill(m.is_human?'Human':'Bot',m.is_human?'orange':'green')}<time>${date(m.posted||m.received)}</time>${m.historical?'<small class="sub">History</small>':''}</div><p>${esc(m.body)}</p></article>`).join(''):empty('No messages yet','Table chat will appear when the connected bot receives it.');
   if(older)list.scrollTop=list.scrollHeight-height;else if(atBottom)list.scrollTop=list.scrollHeight;
   $('#chat-older').hidden=!before;
   $('#chat-requests').innerHTML=data.commands.length?`<details ${data.commands.some(c=>c.status!=='sent')?'open':''}><summary>Recent sends</summary>${data.commands.map(c=>`<div class="chat-request"><strong>${esc(c.bot)}</strong> ${pill(statusLabel[c.status]||c.status,c.status==='sent'?'green':['failed','uncertain','expired'].includes(c.status)?'orange':'blue')}<p>${esc(c.body)}</p><small>${esc(c.detail||({queued:'Waiting for the bot to send.',claimed:'Waiting for the table to confirm.',expired:'The message was not sent before its deadline.',uncertain:'Check table chat before trying again.'})[c.status]||'')}</small></div>`).join('')}</details>`:'';
   if(!older&&atBottom&&messages.length&&document.visibilityState==='visible'){
    await siteApi(`chat/${encodeURIComponent(selectedTable)}/read`,'POST',{last_id:messages.at(-1).id});
   }
   initial=false;
  };
  const refresh=async()=>{
   if(busy||!current())return;busy=true;
   try{
    summary=await siteApi('chat');if(!current())return;drawTables();active=summary.items.find(t=>t.table_id===selectedTable);drawBots();
    if(active){const table=selectedTable,data=await siteApi(`chat/${encodeURIComponent(table)}`);if(current()&&table===selectedTable)await drawMessages(data);}
   }catch(error){if(current())$('#chat-error').textContent=error.message;}
   finally{busy=false;if(current())updateSend();}
  };
  const selectTable=async id=>{
   selectedTable=id;active=summary.items.find(t=>t.table_id===id);messages=[];before=null;olderLoaded=false;initial=true;botSignature='';text.value=drafts.get(`${siteId}:${id}`)||'';$('#chat-error').textContent='';drawTables();drawBots();await refresh();
  };
  $('#chat-older').onclick=async()=>{if(!before||busy)return;busy=true;const id=selectedTable;try{const data=await siteApi(`chat/${encodeURIComponent(id)}?before=${before}`);if(current()&&selectedTable===id){olderLoaded=true;await drawMessages(data,true);}}catch(error){if(current())$('#chat-error').textContent=error.message;}finally{busy=false;}};
  let pendingRequest=null;
  compose.onsubmit=async event=>{
   event.preventDefault();if(send.disabled||!active)return;
   const id=selectedTable,entry=bot.value,value=text.value.trim(),signature=`${id}:${entry}:${value}`;
   if(pendingRequest?.signature!==signature)pendingRequest={signature,id:crypto.randomUUID()};
   sending=true;updateSend();$('#chat-error').textContent='';
   try{
    await siteApi(`chat/${encodeURIComponent(id)}/send`,'POST',{request_id:pendingRequest.id,entry_id:entry,text:value});
    pendingRequest=null;drafts.delete(`${siteId}:${id}`);if(current()&&selectedTable===id)text.value='';toast('Message queued for the selected bot.');
   }catch(error){if(current())$('#chat-error').textContent=error.message;}
   finally{sending=false;if(current()){updateSend();await refresh();}}
  };
  if(!summary.items.some(t=>t.table_id===selectedTable))selectedTable=summary.items.find(t=>t.unread)?.table_id||summary.items[0]?.table_id||null;
  drawTables();if(selectedTable)await selectTable(selectedTable);else{compose.hidden=true;$('#chat-messages').innerHTML=empty('Select a table','Your table conversations will be listed on the left.');}
  clearInterval(state.poll);state.poll=setInterval(refresh,3000);
 };
 return ()=>{clearInterval(state.chatPoll);notify();state.chatPoll=setInterval(notify,5000);};
}
