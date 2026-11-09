// Side panel of the live table window: manual Join / Leave tasks for this table, and its chat.
// Tasks and chat messages go through the normal APIs, so the bot's PC executes them like the scheduler's own.
export function installLivePanel({$, esc, siteApi, toast, state, date}) {
 let tableId = null, open = false, timer = null, busy = false, lastChatId = 0;
 const chatSupported = () => state.site?.platform !== 'BluffPokerPlatform';
 const root = document.createElement('aside');
 root.className = 'live-panel';
 root.hidden = true;
 root.innerHTML = `<div class="live-panel-head"><strong>Bots &amp; chat</strong><button class="icon-button" id="live-panel-close" aria-label="Close">×</button></div>
  <section><h3>Our bots at this table</h3><div id="live-panel-seated" class="live-panel-list"><p class="sub">Loading…</p></div></section>
  <section><h3>Join this table</h3><div id="live-panel-join"></div></section>
  <section class="live-panel-chat"><h3>Chat</h3><div id="live-panel-chat"></div></section>`;
 document.body.appendChild(root);
 const button = document.createElement('button');
 button.className = 'button small live-panel-toggle';
 button.textContent = 'Bots & chat';
 button.onclick = () => toggle(!open);
 root.querySelector('#live-panel-close').onclick = () => toggle(false);

 function toggle(value) {
  open = value; root.hidden = !open; button.classList.toggle('active', open);
  clearInterval(timer);
  if (open) { refresh(); timer = setInterval(refresh, 4000); }
 }

 async function task(kind, accountId) {
  try {
   const r = await siteApi('tasks', 'POST', {kind, account_id: accountId, table_id: tableId});
   toast(`${kind === 'join' ? 'Join' : 'Leave'} task created for ${r.bot}; its PC carries it out shortly.`);
   refresh();
  } catch (error) { toast(error.message); }
 }

 async function refresh() {
  if (busy || !open || !tableId) return;
  busy = true;
  try {
   const options = await siteApi('tasks/options');
   const seated = [], joinable = [];
   for (const s of options.sessions) {
    const here = s.tables.find(e => String(e.table_id) === String(tableId));
    if (here) seated.push({s, e: here});
    else if ((s.join_tables || []).map(String).includes(String(tableId))) joinable.push(s);
   }
   $('#live-panel-seated').innerHTML = seated.length ? seated.map(({s, e}) => `<div class="live-panel-row"><span><strong>${esc(s.username)}</strong><span class="sub">${esc(e.status)}${e.leaving ? ' · leaving' : ''}</span></span>${e.leaving || !['seated', 'sitting_out'].includes(e.status) ? '' : `<button class="button small" data-leave="${s.id}">Leave</button>`}</div>`).join('') : '<p class="sub">None of our bots sits at this table.</p>';
   $('#live-panel-join').innerHTML = joinable.length
    ? `<div class="live-panel-form"><select id="live-panel-join-bot">${joinable.map(s => `<option value="${s.id}">${esc(s.username)} · ${esc(s.tier)} · ${s.tables.length}/${s.max_tables} tables${s.machine_ready ? '' : ' · PC offline'}</option>`).join('')}</select><button class="button small primary" id="live-panel-join-go">Join</button></div>`
    : '<p class="sub">No bot can join now: a bot needs an open session, this table\'s stake tier and game, a free seat and a table below its maximum. Start a session on the Sessions page.</p>';
   root.querySelectorAll('[data-leave]').forEach(b => b.onclick = () => task('leave', +b.dataset.leave));
   const go = $('#live-panel-join-go');
   if (go) go.onclick = () => task('join', +$('#live-panel-join-bot').value);
   await refreshChat(seated);
  } catch (error) {
   $('#live-panel-seated').innerHTML = `<p class="notice error">${esc(error.message)}</p>`;
  } finally { busy = false; }
 }

 async function refreshChat(seated) {
  const box = $('#live-panel-chat');
  if (!chatSupported()) { box.innerHTML = '<p class="sub">Table chat is not available on BluffPoker.</p>'; return; }
  const [d, summary] = await Promise.all([siteApi(`chat/${encodeURIComponent(tableId)}`), siteApi('chat')]);
  const bots = ((summary.items || []).find(t => String(t.table_id) === String(tableId))?.bots || []).filter(b => b.chat_ready);
  const draft = $('#live-panel-chat-text')?.value || '';
  const latest = d.items.length ? d.items[d.items.length - 1].id : 0;
  box.innerHTML = `<div class="live-panel-messages" id="live-panel-messages">${d.items.map(m => `<p class="${m.is_human ? 'human' : 'bot'}"><strong>${esc(m.author)}</strong> ${esc(m.body)}<span class="sub">${date(m.received || m.posted)}</span></p>`).join('') || '<p class="sub">No messages yet.</p>'}</div>`
   + (bots.length ? `<form class="live-panel-form" id="live-panel-chat-form"><select id="live-panel-chat-bot">${bots.map(b => `<option value="${esc(b.entry_id)}">${esc(b.bot)}</option>`).join('')}</select><input id="live-panel-chat-text" maxlength="2000" placeholder="Message as this bot" value="${esc(draft)}"><button class="button small primary">Send</button></form>`
    : `<p class="sub">${seated.length ? 'Our bots here are not connected to chat yet.' : 'A bot must sit at this table to send a message.'}</p>`);
  const list = $('#live-panel-messages');
  if (latest !== lastChatId) { list.scrollTop = list.scrollHeight; lastChatId = latest; }
  const form = $('#live-panel-chat-form');
  if (form) form.onsubmit = async e => {
   e.preventDefault();
   const text = $('#live-panel-chat-text').value.trim();
   if (!text) return;
   try {
    await siteApi(`chat/${encodeURIComponent(tableId)}/send`, 'POST', {request_id: crypto.randomUUID(), entry_id: $('#live-panel-chat-bot').value, text});
    $('#live-panel-chat-text').value = '';
    toast('Message queued; the bot sends it at the table.');
    refresh();
   } catch (error) { toast(error.message); }
  };
 }

 return {
  button,
  setTable(id) { if (id && String(id) !== String(tableId)) { tableId = id; if (open) refresh(); } },
  close() { toggle(false); root.remove(); },
 };
}
