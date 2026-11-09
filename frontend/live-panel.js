// Live table window side panels: Tasks (left: manual Leave / Join for this table) and Chat (right).
// Each refreshes only its data; inputs and selections are built once, so typing is never interrupted.
export function installLivePanel({$, esc, siteApi, toast, state, date}) {
 let tableId = null;
 const chatSupported = () => state.site?.platform !== 'BluffPokerPlatform';

 const panels = [];
 function drawer(side, title, body) {
  const root = document.createElement('aside');
  root.className = `live-panel live-panel-${side}`;
  root.hidden = true;
  root.innerHTML = `<div class="live-panel-head"><strong>${title}</strong><button class="icon-button" aria-label="Close">×</button></div>${body}`;
  document.body.appendChild(root);
  const button = document.createElement('button');
  button.className = `button small live-panel-toggle live-panel-toggle-${side}`;
  button.textContent = title;
  const panel = {root, button, open: false, timer: null, refresh: async () => {}};
  panel.toggle = value => {
   if (value) panels.filter(other => other !== panel && other.open).forEach(other => other.toggle(false));  // one panel at a time
   panel.open = value; root.hidden = !value; button.classList.toggle('active', value);
   clearInterval(panel.timer);
   if (value) { panel.refresh(); panel.timer = setInterval(() => panel.refresh(), 4000); }
  };
  button.onclick = () => panel.toggle(!panel.open);
  root.querySelector('.live-panel-head button').onclick = () => panel.toggle(false);
  panels.push(panel);
 return panel;
 }

 // ---- Tasks ----------------------------------------------------------------------------------------------------
 const tasks = drawer('right', 'Tasks', `<section><h3>Our bots at this table</h3><div id="live-tasks-seated" class="live-panel-list"><p class="sub">Loading…</p></div></section>
  <section><h3>Join this table</h3><div class="live-panel-form"><select id="live-tasks-join-bot" hidden></select><button class="button small primary" id="live-tasks-join-go" hidden>Join</button></div><p class="sub" id="live-tasks-join-note">Loading…</p></section>`);
 let tasksBusy = false;
 async function task(kind, accountId) {
  try {
   const r = await siteApi('tasks', 'POST', {kind, account_id: accountId, table_id: tableId, start_session: kind === 'join'});
   toast(`${kind === 'join' ? 'Join' : 'Leave'} task created for ${r.bot}; its PC carries it out shortly.`);
   tasks.refresh();
  } catch (error) { toast(error.message); }
 }
 $('#live-tasks-join-go').onclick = () => task('join', +$('#live-tasks-join-bot').value);
 tasks.refresh = async () => {
  if (tasksBusy || !tasks.open || !tableId) return;
  tasksBusy = true;
  try {
   const [options, candidates] = await Promise.all([siteApi('tasks/options'), siteApi(`tasks/join-candidates?table_id=${encodeURIComponent(tableId)}`)]);
   const seated = [];
   for (const s of options.sessions) {
    const here = s.tables.find(e => String(e.table_id) === String(tableId));
    if (here) seated.push({s, e: here});
   }
   $('#live-tasks-seated').innerHTML = seated.length ? seated.map(({s, e}) => `<div class="live-panel-row"><span><strong>${esc(s.username)}</strong><span class="sub">${esc(s.profile || '')} · ${esc(s.tier)} · ${esc(e.status)}${e.leaving ? ' · leaving' : ''}</span></span>${e.leaving || !['seated', 'sitting_out'].includes(e.status) ? '' : `<button class="button small" data-leave="${s.id}">Leave</button>`}</div>`).join('') : '<p class="sub">None of our bots sits at this table.</p>';
   tasks.root.querySelectorAll('[data-leave]').forEach(b => b.onclick = () => task('leave', +b.dataset.leave));
   const accounts = candidates.accounts || [], select = $('#live-tasks-join-bot'), chosen = select.value;
   const html = accounts.map(a => `<option value="${a.id}">${esc(a.username)} · ${esc(a.profile)} · ${esc(a.stake)}</option>`).join('');
   if (select.dataset.html !== html) {   // only when the list changed: an open list or a choice is not reset
    select.innerHTML = html; select.dataset.html = html;
    if (accounts.some(a => String(a.id) === chosen)) select.value = chosen;
   }
   select.hidden = $('#live-tasks-join-go').hidden = !accounts.length;
   $('#live-tasks-join-note').textContent = accounts.length ? '' : (candidates.reason || 'No bot can join this table now.');
  } catch (error) {
   $('#live-tasks-join-note').textContent = error.message;
  } finally { tasksBusy = false; }
 };

 // ---- Chat -------------------------------------------------------------------------------------------------------
 const chat = drawer('right', 'Chat', `<div id="live-chat-body"><div class="live-panel-messages live-chat-messages" id="live-chat-messages"><p class="sub">Loading…</p></div>
  <form class="live-chat-form" id="live-chat-form"><label><span class="sub">Send as</span><select id="live-chat-bot"></select></label><textarea id="live-chat-text" maxlength="2000" rows="3" placeholder="Message" autocomplete="off"></textarea><button class="button small primary">Send</button></form>
  <p class="sub" id="live-chat-note"></p></div>`);
 let chatBusy = false, lastChatId = null;
 $('#live-chat-form').onsubmit = async e => {
  e.preventDefault();
  const input = $('#live-chat-text'), text = input.value.trim();
  if (!text || !$('#live-chat-bot').value) return;
  try {
   await siteApi(`chat/${encodeURIComponent(tableId)}/send`, 'POST', {request_id: crypto.randomUUID(), entry_id: $('#live-chat-bot').value, text});
   input.value = '';
   toast('Message queued; the bot sends it at the table.');
   chat.refresh();
  } catch (error) { toast(error.message); }
 };
 // Enter sends, Shift+Enter starts a new line.
 $('#live-chat-text').onkeydown = e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#live-chat-form').requestSubmit(); }
 };
 chat.refresh = async () => {
  if (chatBusy || !chat.open || !tableId) return;
  if (!chatSupported()) {
   $('#live-chat-body').innerHTML = '<p class="sub">Table chat is not available on BluffPoker.</p>';
   return;
  }
  chatBusy = true;
  try {
   const [d, summary] = await Promise.all([siteApi(`chat/${encodeURIComponent(tableId)}`), siteApi('chat')]);
   const latest = d.items.length ? d.items[d.items.length - 1].id : 0;
   if (latest !== lastChatId) {   // new messages only: the list is not redrawn while nothing changed
    const list = $('#live-chat-messages'), atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 20 || lastChatId === null;
    list.innerHTML = d.items.map(m => `<p class="${m.is_human ? 'human' : 'bot'}"><strong>${esc(m.author)}</strong> ${esc(m.body)}<span class="sub">${date(m.received || m.posted)}</span></p>`).join('') || '<p class="sub">No messages yet.</p>';
    if (atBottom) list.scrollTop = list.scrollHeight;
    lastChatId = latest;
   }
   const bots = ((summary.items || []).find(t => String(t.table_id) === String(tableId))?.bots || []).filter(b => b.chat_ready);
   const select = $('#live-chat-bot'), chosen = select.value;
   const html = bots.map(b => `<option value="${esc(b.entry_id)}">${esc(b.bot)}</option>`).join('');
   if (select.dataset.html !== html) {
    select.innerHTML = html; select.dataset.html = html;
    if (bots.some(b => b.entry_id === chosen)) select.value = chosen;
   }
   $('#live-chat-form').hidden = !bots.length;
   $('#live-chat-note').textContent = bots.length ? '' : 'A bot of ours must sit at this table, connected to chat, to send a message.';
  } catch (error) {
   $('#live-chat-note').textContent = error.message;
  } finally { chatBusy = false; }
 };

 return {
  tasksButton: tasks.button,
  chatButton: chat.button,
  setTable(id) {
   if (!id || String(id) === String(tableId)) return;
   tableId = id; lastChatId = null;
   tasks.refresh(); chat.refresh();
  },
 };
}
