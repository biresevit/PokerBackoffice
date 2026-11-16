// The public tour displays supplied screenshots; it does not access customer APIs.
const screens=[
 {key:'overview',label:'Overview',title:'Your operation, in one view.',description:'Compare scheduled targets with confirmed activity, follow ring and tournament entries, and check machine health.',file:'overview.png',width:2086,height:1750,alt:'PokerFill overview showing activity totals and a scheduled-versus-running entries graph'},
 {key:'profiles',label:'Player settings',title:'Define how each account plays.',description:'Choose a strategy profile, preferred stakes, session lengths, break intervals and other playing preferences for each bot.',file:'player_profile.png',width:973,height:1473,alt:'Player settings with strategy profile, playing frequency, session duration and randomized break settings'},
 {key:'schedule',label:'Weekly schedule',title:'Plan the rhythm of your lobby.',description:'Set targets by day, time and game format. The weekly timeline makes quiet periods, peak hours and entry levels easy to see.',file:'weekly_schedule.png',width:2098,height:1444,alt:'Weekly poker schedule with colored time windows and entry targets across seven days'},
 {key:'lobby',label:'Live lobby',title:'See where play is happening.',description:'Browse cash games, SNGs and MTTs, see seated bots and players, then open an individual table for a closer look.',file:'live_tables.png',width:2346,height:1345,alt:'Live lobby with cash table seat diagrams and registering or running tournaments'},
 {key:'manual',label:'Manual control',title:'Take a closer look. Take the next action.',description:'Watch a selected hero at the table and switch to manual control when needed, with fold, call, raise and bet-sizing controls.',file:'live_table_manual_control_on.png',width:1495,height:1528,alt:'Live poker table showing hero cards and manual fold, call, raise and bet-sizing controls'},
 {key:'chat',label:'Table chat',title:'Keep your team in the conversation.',description:'Read table conversations, receive human-message notifications and send a reply through a bot seated at the selected table.',file:'chat.png',width:2097,height:1648,alt:'Table chat page with a table list, conversation history, bot selector and message composer'},
 {key:'accounts',label:'Account mix',title:'Build variety across your accounts.',description:'Configure distributions for strategy profiles, stakes, playing frequency and daily playtime, then apply your preferred mix across accounts.',file:'Accounts_distributions.png',width:2350,height:1372,alt:'Account distributions for player profiles, stake tiers, playing frequency and daily playtime preferences'},
 {key:'replay',label:'Hand replay',title:'Review the play, hand by hand.',description:'Replay recorded hands with cards, bets, stacks and the board. Step through the action to understand the decisions being made.',file:'hand_history_replay.png',width:1494,height:1288,alt:'Hand history replay with player cards, stacks, board, pot and previous/next action controls'}
];
const tabs=document.querySelector('#screenshot-tabs'),main=document.querySelector('#screenshot-image');
if(tabs&&main){
 let index=0;
 const dialog=document.querySelector('#screenshot-dialog'),full=document.querySelector('#screenshot-full'),viewport=document.querySelector('#screenshot-viewport'),zoom=document.querySelector('#screenshot-zoom');
 const source=screen=>`/product-shots/${screen.file}`;
 const setZoom=enabled=>{viewport.classList.toggle('is-zoomed',enabled);zoom.setAttribute('aria-pressed',String(enabled));zoom.textContent=enabled?'Fit to screen':'Zoom in';viewport.scrollTo(0,0);};
 const updateDialog=()=>{const screen=screens[index];full.src=source(screen);full.alt=screen.alt;document.querySelector('#screenshot-dialog-title').textContent=screen.label;document.querySelector('#screenshot-position').textContent=`${index+1} / ${screens.length}`;setZoom(false);};
 function select(next,focus=false){
  index=(next+screens.length)%screens.length;const screen=screens[index];
  [...tabs.children].forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1;});
  main.src=source(screen);main.alt=screen.alt;main.width=screen.width;main.height=screen.height;
  document.querySelector('#screenshot-title').textContent=screen.title;
  document.querySelector('#screenshot-description').textContent=screen.description;
  document.querySelector('#screenshot-panel').setAttribute('aria-labelledby',`screen-tab-${screen.key}`);
  document.querySelector('#screenshot-open').setAttribute('aria-label',`Enlarge ${screen.label.toLowerCase()} screenshot`);
  if(focus)tabs.children[index].focus();
  if(dialog.open)updateDialog();
 }
 screens.forEach((screen,i)=>{
  const tab=document.createElement('button');tab.type='button';tab.role='tab';tab.id=`screen-tab-${screen.key}`;tab.textContent=screen.label;tab.setAttribute('aria-controls','screenshot-panel');
  tab.addEventListener('click',()=>select(i));
  tab.addEventListener('keydown',event=>{
   const moves={ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:screens.length-1};
   if(event.key in moves){event.preventDefault();select(moves[event.key],true);}
  });tabs.append(tab);
 });
 document.querySelector('#screenshot-open').addEventListener('click',()=>{updateDialog();dialog.showModal();document.documentElement.classList.add('screenshot-modal-open');});
 document.querySelector('#screenshot-close').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{document.documentElement.classList.remove('screenshot-modal-open');document.querySelector('#screenshot-open').focus();});
 document.querySelector('#screenshot-prev').addEventListener('click',()=>select(index-1));
 document.querySelector('#screenshot-next').addEventListener('click',()=>select(index+1));
 zoom.addEventListener('click',()=>setZoom(zoom.getAttribute('aria-pressed')!=='true'));
 dialog.addEventListener('keydown',event=>{
  if(viewport.classList.contains('is-zoomed'))return;
  if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();select(index+(event.key==='ArrowRight'?1:-1));}
 });
 select(0);
}
