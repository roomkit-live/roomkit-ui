/* Local interaction prototype. No provider, microphone, camera or network calls. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const icons = {
  plus: '<path d="M12 5v14M5 12h14"/>', x: '<path d="m6 6 12 12M18 6 6 18"/>',
  search: '<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8" cy="8" r="1.5"/><path d="m3 16 5-5 5 5 3-3 5 5"/>',
  message: '<path d="M21 11a8 8 0 0 1-8 8H6l-3 3V11a9 9 0 0 1 18 0Z"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M9 22h6"/>',
  muted: '<path d="m3 3 18 18M9 9v3a3 3 0 0 0 5 2M9 5a3 3 0 0 1 6 0v5M5 10v2a7 7 0 0 0 12 5M19 10v2M12 19v3M9 22h6"/>',
  wave: '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
  screen: '<rect x="2" y="3" width="20" height="14" rx="3"/><path d="M12 17v4M7 21h10"/>',
  window: '<rect x="2" y="3" width="20" height="18" rx="3"/><path d="M2 8h20M6 5.5h.1M9 5.5h.1"/>',
  camera: '<path d="M4 6h4l2-3h4l2 3h4a2 2 0 0 1 2 2v11H2V8a2 2 0 0 1 2-2Z"/><circle cx="12" cy="12" r="4"/>',
  panel: '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M15 3v18"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  chevron: '<path d="m7 10 5 5 5-5"/>',
  'arrow-up': '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10Z"/>',
  layers: '<path d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>',
  settings: '<path d="m10 2-1 3-3 1-3-1-2 4 3 2v3l-3 2 2 4 3-1 3 1 1 3h4l1-3 3-1 3 1 2-4-3-2v-3l3-2-2-4-3 1-3-1-1-3Z" transform="translate(1 0) scale(.9)"/><circle cx="12" cy="12" r="3"/>',
  sparkles: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  disconnect: '<path d="m3 3 18 18M4 9a13 13 0 0 1 3-2m4-1a13 13 0 0 1 9 3M7 13a7 7 0 0 1 3-2m5 1 2 1M10 17a3 3 0 0 1 4 0M12 21h.1"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="3"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
  volume: '<path d="M3 9h4l5-5v16l-5-5H3V9ZM16 8a6 6 0 0 1 0 8M19 5a10 10 0 0 1 0 14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.sparkles}</svg>`;
function hydrate(root = document) { $$('[data-icon]', root).forEach(el => { el.innerHTML = icon(el.dataset.icon); }); }
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sample = {name:'conversation-settings.png',src:'../settings-redesign/native-conversation-light.png',detail:'Image · ready to send',sample:true};
const sketch = {name:'a-clearer-conversation.svg',src:'assets/conversation-sketch.svg',detail:'Layout study · sample visual response'};
const state = {messages:[],attachments:[],provider:'gemini',live:false,phase:'listening',sharing:null,panel:null,error:false,generating:false,scenario:'home',timer:null,reconnectTimer:null,dictationTimer:null,toastTimer:null,shareChoice:'window',thread:null,views:{}};
const phaseCopy = {
  listening:['Listening…','Take your time. I’m right here.'],
  thinking:['Thinking…','Putting the pieces together.'],
  speaking:['Speaking…','You can interrupt or keep typing.'],
  paused:['Microphone off','You can still type or add an image.'],
};
function showToast(text) { clearTimeout(state.toastTimer); $('#toast').textContent=text; $('#toast').hidden=false; state.toastTimer=setTimeout(()=>$('#toast').hidden=true,3800); }
function closeMenus() { for (const key of ['provider','attach']) { $(`#${key}-menu`).hidden=true; $(`#${key}-button`).setAttribute('aria-expanded','false'); } }
function toggleMenu(key) { const open=$(`#${key}-menu`).hidden; closeMenus(); $(`#${key}-menu`).hidden=!open; $(`#${key}-button`).setAttribute('aria-expanded',String(open)); }
function scrollBottom() { requestAnimationFrame(()=>{ const c=$('#conversation'); c.scrollTo({top:c.scrollHeight,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'}); }); }
function createThread(title) {
  state.thread=`conversation-${crypto.randomUUID()}`;
  $('#conversation-title').textContent=title;
  const entry=document.createElement('button');
  entry.dataset.thread=state.thread;
  entry.innerHTML=icon('message')+`<span>${esc(title)}<small>Created in this preview</small></span>`;
  $('.threads').prepend(entry);
  $('#thread-search').value='';
  $$('[data-thread]').forEach(b=>b.hidden=false);
  $('.thread-empty').hidden=true;
}
function saveThread() {
  const draft=$('#composer-input').value;
  if(!state.thread&&(draft.trim()||state.attachments.length))createThread(draft.trim().slice(0,46)||'A conversation in images');
  if(state.thread)state.views[state.thread]={messages:[...state.messages],draft,attachments:[...state.attachments],title:$('#conversation-title').textContent,provider:state.provider};
}
function cancelPending() { clearTimeout(state.timer); clearTimeout(state.reconnectTimer); clearTimeout(state.dictationTimer); state.dictationTimer=null; $('#dictation-button').innerHTML=icon('mic'); $('#dictation-button').setAttribute('aria-label','Dictate a message'); state.generating=false; $('#retry-button').textContent='Reconnect'; $('#retry-button').disabled=false; }
function resetSession() { cancelPending(); state.live=false; state.sharing=null; state.panel=null; state.error=false; state.phase='listening'; }
function newConversation() { saveThread(); resetSession(); state.messages=[]; state.attachments=[]; state.thread=null; $('#composer-input').value=''; $('#conversation-title').textContent='New conversation'; setScenario('home'); render(); $('#composer-input').focus(); }
function imageMessages() {
  return [
    {role:'user',text:'How would you bring text, images and voice together here?',images:[{...sample}]},
    {role:'assistant',kind:'review',text:'Let’s give the conversation more room.',visual:true},
  ];
}
function setScenario(name) { state.scenario=name; $$('[data-scenario]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.scenario===name))); }
function openScenario(name, restore=false) {
  saveThread(); resetSession(); state.attachments=[]; $('#composer-input').value=''; state.provider='gemini'; state.thread=name==='home'?null:name;
  const restored=restore&&state.views[name];
  if(name==='home'){state.messages=[];$('#conversation-title').textContent='New conversation';}
  else if(restored) {const old=state.views[name];state.messages=[...old.messages];state.attachments=[...old.attachments];state.provider=old.provider;$('#composer-input').value=old.draft;$('#conversation-title').textContent=old.title;}
  else if(name==='plan'){state.messages=[{role:'user',text:'Help me plan the next RoomKit release.'},{role:'assistant',text:'Start with one complete journey: write a message, attach an image, and continue by voice. Then verify that the conversation survives ending and restarting the voice session. A small, complete experience is easier to evaluate than several disconnected screens.'}];$('#conversation-title').textContent='Plan the next release';}
  else {state.messages=imageMessages();$('#conversation-title').textContent='A clearer conversation';}
  setScenario(name==='plan'||name.startsWith('conversation-')?'image':name);
  if(name==='live'){state.live=true;state.phase='speaking';state.panel='live';state.messages.push({role:'user',text:'Can you walk me through it?',voice:true},{role:'assistant',text:'Of course. Your conversation stays in the center. The image is part of the exchange, and you can switch between writing and speaking whenever you like.',voice:true});}
  if(name==='screen'&&!restored){state.live=true;state.panel='live';state.sharing='window';state.messages=[{role:'user',text:'Let’s look at my settings together.',voice:true},{role:'assistant',kind:'screen',text:'I can see the RoomKit Settings window.',visual:false}];$('#conversation-title').textContent='Let’s look at it together';}
  if(name==='error'){state.live=true;state.phase='paused';state.error=true;$('#composer-input').value='Keep the image beside our conversation.';state.attachments=[{...sketch}];}
  closeMenus();closeSidebar();render();requestAnimationFrame(()=>$('#conversation').scrollTo({top:name==='live'||restored?$('#conversation').scrollHeight:0,behavior:'instant'}));
}
function userHTML(message,index) {
  const images=(message.images||[]).map((im,i)=>`<button class="sent-image" data-image="${index}:${i}" aria-label="Open ${esc(im.name)}"><img src="${esc(im.src)}" alt="${im.sample?'RoomKit Conversation Settings with Realtime and Voice Channel cards':esc(im.name)}"><span>${icon('image')}${esc(im.name)}</span></button>`).join('');
  return `<article class="message user-message" aria-label="Your message">${images}${message.text?`<div class="user-bubble">${esc(message.text).replace(/\n/g,'<br>')}</div>`:''}<div class="message-meta">You${message.voice?' · Voice transcript':''}</div></article>`;
}
function assistantHTML(message,index) {
  let content;
  if(message.kind==='review')content='<p>One conversation, with more ways to <strong>write, show and talk</strong>.</p><ol><li><strong>One composer.</strong> Text, images and Live, together.</li><li><strong>Images in the flow.</strong> Your reference beside the response.</li><li><strong>A lasting conversation.</strong> End the call, keep the context.</li></ol>';
  else if(message.kind==='screen')content='<p>I can see the <strong>RoomKit Settings</strong> window. The large conversation cards make the two modes easy to compare.</p><p>Let’s use that same hierarchy here: your message first, the image right beside it, and voice controls that stay out of the way until you need them.</p><details class="tool-activity"><summary>'+icon('check')+' Shared view added to this conversation '+icon('chevron')+'</summary><p>RoomKit Settings · one window<br>The shared view stops as soon as you choose Stop sharing.</p></details>';
  else content=`<p>${esc(message.text).replace(/\n/g,'<br>')}</p>`;
  const visual=message.visual?`<button class="result-card" data-action="sketch"><img src="${sketch.src}" alt="Proposed layout with a persistent conversation, inline image and multimodal composer"><span class="result-card-copy"><span class="eyebrow">A DIRECTION TO EXPLORE</span><strong>A calmer starting point</strong><small>Same conversation. More ways to take part.</small><span class="preview-label">Open the layout sketch ↗</span></span></button>`:'';
  return `<article class="message assistant-message" aria-label="RoomKit response"><span class="assistant-symbol" aria-hidden="true">✦</span><div class="assistant-heading">RoomKit</div><div class="copy">${content}</div>${visual}${message.interrupted?'<p class="interrupted-label">Interrupted · you can continue the conversation.</p>':''}<div class="message-actions"><button class="icon-button" data-copy="${index}" aria-label="Copy response" title="Copy response">${icon('copy')}</button><button class="icon-button" data-read="${index}" aria-label="Listen to response" title="Listen to response">${icon('volume')}</button><span>${message.voice?'Voice transcript':'Sample response'}</span></div></article>`;
}
function renderMessages() { $('#welcome').hidden=state.messages.length>0;$('#transcript').innerHTML=(state.messages.length?'<div class="day-label">Today · a conversation in every form</div>':'')+state.messages.map((m,i)=>m.role==='user'?userHTML(m,i):assistantHTML(m,i)).join(''); }
function renderAttachments() { $('#draft-attachments').innerHTML=state.attachments.map((im,i)=>`<div class="draft-attachment"><button type="button" data-draft-image="${i}" aria-label="Preview ${esc(im.name)}"><img src="${esc(im.src)}" alt=""></button><span><strong>${esc(im.name)}</strong><small>Image · ready to send</small></span><button type="button" class="icon-button" data-remove="${i}" aria-label="Remove ${esc(im.name)}">${icon('x')}</button></div>`).join(''); }
function renderComposer() {
  const draft=Boolean($('#composer-input').value.trim()||state.attachments.length);
  $('#send-button').hidden=!draft||state.generating;$('#stop-button').hidden=!state.generating;$('#live-button').hidden=draft||state.generating;$('#live-button').classList.toggle('active',state.live);
  $('#live-button').innerHTML=icon('wave')+`<span>${state.live?'Live is on':'Go Live'}</span>`;
  $('#generation').hidden=!state.generating;$('#live-strip').hidden=!state.live;$('#live-strip-text').textContent=state.error?'Live paused · Connection lost':`Live is on · ${phaseCopy[state.phase][0].replace('…','')}`;
  $('#sharing-strip').hidden=!state.sharing;$('#sharing-strip>span:nth-child(2)').innerHTML=state.sharing==='camera'?'Sharing <b>Built-in camera</b>':'Sharing <b>RoomKit Settings</b>';
  $('#connection-banner').hidden=!state.error;$('#composer-context').textContent=state.provider==='gemini'?'Text, images & voice':'Text & voice';
  $('#provider-name').textContent=state.provider==='gemini'?'Gemini':'Text & voice';
  $$('[data-provider]').forEach(b=>$('.provider-check',b).hidden=b.dataset.provider!==state.provider);
  $('#composer-hint').textContent=state.live?'Type here any time. You’re still in the same conversation.':'Your next thought can take any form.';
}
function renderPanel() {
  const el=$('#context-panel');el.hidden=!state.panel;
  el.classList.toggle('with-sharing',state.panel==='live'&&Boolean(state.sharing));
  if(!state.panel){el.innerHTML='';return;}
  if(state.panel==='live'){
    const [title,desc]=phaseCopy[state.phase];
    el.innerHTML=`<header class="panel-header"><span>Live conversation</span><button class="icon-button" data-action="close-panel" aria-label="Minimize live panel">${icon('x')}</button></header><p class="panel-subtitle">A voice in the same conversation.</p><div class="live-orb ${state.phase==='paused'?'paused':''}" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><p class="live-state" role="status">${title}</p><p class="live-explanation">${desc}</p><div class="live-controls"><button data-action="mute" class="${state.phase==='paused'?'active':''}" aria-label="${state.phase==='paused'?'Unmute microphone':'Mute microphone'}" title="${state.phase==='paused'?'Unmute microphone':'Mute microphone'}">${icon(state.phase==='paused'?'muted':'mic')}</button><button data-action="share" aria-label="Share a window or camera" title="Share a view">${icon('screen')}</button><button data-action="end-live" class="end" aria-label="End live conversation" title="End live">${icon('x')}</button></div>${state.phase==='speaking'?'<button class="interrupt-button" data-action="interrupt">Interrupt response</button>':''}<div class="state-demo" lang="fr"><label for="phase-select">ÉTAT À PRÉVISUALISER</label><select id="phase-select"><option value="listening">Écoute</option><option value="thinking">Réflexion</option><option value="speaking">Réponse vocale</option><option value="paused">Micro coupé</option></select></div>${state.sharing?`<div class="shared-preview"><p>${icon(state.sharing==='camera'?'camera':'screen')} ${state.sharing==='camera'?'Built-in camera':'RoomKit Settings'}</p>${state.sharing==='camera'?'<div class="camera-placeholder">'+icon('camera')+'<small>Camera preview · simulated</small></div>':`<img src="${sample.src}" alt="The RoomKit Settings window being shared in the demo">`}<button data-action="stop-sharing">Stop sharing</button></div>`:''}`;
    $('#phase-select').value=state.phase;
  }else{
    const images=state.messages.flatMap(m=>m.images||[]);
    el.innerHTML=`<header class="panel-header"><span>In this conversation</span><button class="icon-button" data-action="close-panel" aria-label="Close context">${icon('x')}</button></header><div class="context-section"><h3>MODEL</h3><p>${state.provider==='gemini'?'Gemini':'Text & voice setup'}</p><small>${state.provider==='gemini'?'Text, images and voice in one context.':'This example configuration supports text and voice.'}</small></div><div class="context-section"><h3>IMAGES · ${images.length}</h3>${images.length?images.map((im,i)=>`<button data-context-image="${i}" aria-label="Open ${esc(im.name)}"><img class="context-image" src="${esc(im.src)}" alt="${esc(im.name)}"></button>`).join(''):'<small>Add an image from the composer. It will stay attached to its message.</small>'}</div><div class="context-section"><h3>TOOLS & SKILLS</h3><div class="context-chips"><span>Workspace files</span><span>Web search</span><span>Writing</span></div><small>Example configuration. Tool activity appears with the response.</small></div><div class="context-section"><h3>VOICE SESSION</h3><p>${state.live?phaseCopy[state.phase][0]:'Not started'}</p><small>The conversation stays here after Live ends.</small></div>`;
  }
}
function render() {renderMessages();renderAttachments();renderComposer();renderPanel();$$('[data-thread]').forEach(b=>b.classList.toggle('active',b.dataset.thread===state.thread));}
function requireVision() { if(state.provider==='gemini')return true;showToast('This setup has no image support. Choose Gemini to add an image or share a view.');return false; }
function addSample() { if(!requireVision())return;closeMenus();if(!state.attachments.some(im=>im.sample))state.attachments.push({...sample});if(!$('#composer-input').value)$('#composer-input').value='How would you make this experience feel clearer?';renderAttachments();renderComposer();$('#composer-input').focus(); }
function addFiles(files) {
  if(!requireVision())return;
  const valid=[...files].filter(f=>/^image\/(png|jpeg|webp|gif)$/.test(f.type));
  if(!valid.length){showToast('Choose a PNG, JPEG, WebP or GIF image.');return;}
  for(const file of valid){if(state.attachments.length>=4){showToast('Up to four images in this prototype.');break;}if(file.size>10*1024*1024){showToast(`${file.name} is too large for this preview (10 MB maximum).`);continue;}const src=URL.createObjectURL(file);objectURLs.add(src);state.attachments.push({name:file.name,src,detail:'Local image · preview only'});}
  renderAttachments();renderComposer();$('#composer-input').focus();closeMenus();
}
const objectURLs=new Set();
function openImage(im) {$('#image-title').textContent=im.name;$('#full-image').src=im.src;$('#full-image').alt=im.detail||im.name;$('#image-description').textContent=im.detail||'Image attached to this conversation';$('#image-download').href=im.src;$('#image-download').download=im.name;$('#image-dialog').showModal();}
function sendMessage(e) {
  e?.preventDefault();const text=$('#composer-input').value.trim();if(state.generating||(!text&&!state.attachments.length))return;
  if(state.error){showToast('Reconnect to send. Your draft and images are kept.');return;}
  const images=[...state.attachments];state.messages.push({role:'user',text,images});state.attachments=[];$('#composer-input').value='';
  if(!state.thread)createThread(text.slice(0,46)||(images.length?'A conversation in images':'New conversation'));
  state.generating=true;render();scrollBottom();
  state.timer=setTimeout(()=>{
    state.generating=false;
    const usesSample=images.some(i=>i.sample);
    if(usesSample)state.messages.push({role:'assistant',kind:'review',visual:true,text:'Let’s give the conversation more room.'});
    else if(images.length)state.messages.push({role:'assistant',text:'Your image and message are together in the conversation. This is a local preview: in the connected app, the selected model would analyse this image and answer here.'});
    else state.messages.push({role:'assistant',text:'Let’s work through it together. We can start with a written answer, bring in an image for context, and continue the same thought by voice. This response is a scripted example of that flow.'});
    if(state.live)state.phase='speaking';render();scrollBottom();saveThread();
  },1250);
}
function startLive() { if(state.error){showToast('Reconnect to resume Live.');return;}state.live=true;state.phase='listening';state.panel='live';renderComposer();renderPanel(); }
function endLive() { state.live=false;state.sharing=null;state.panel=null;state.phase='listening';renderComposer();renderPanel();showToast('Live ended. Your conversation and draft are still here.'); }
function stopResponse() {cancelPending();state.messages.push({role:'assistant',text:'Response stopped.',interrupted:true});render();scrollBottom();}
function interrupt() {const last=[...state.messages].reverse().find(m=>m.role==='assistant');if(last)last.interrupted=true;state.phase='listening';render();showToast('Response interrupted. The microphone is still on.');}
function shareDialog(kind='window') {if(!requireVision())return;closeMenus();state.shareChoice=kind;renderShareChoice();$('#share-dialog').showModal();}
function renderShareChoice() {$$('[data-share]').forEach(b=>{const selected=b.dataset.share===state.shareChoice;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));$('b',b).hidden=!selected;});$('#confirm-share').textContent=state.shareChoice==='camera'?'Use camera':'Share window';}
function confirmShare() {$('#share-dialog').close();state.sharing=state.shareChoice;state.live=true;state.phase='listening';state.panel='live';renderComposer();renderPanel();showToast('Sharing preview started. No actual screen or camera is accessed.');}
function toggleSidebar() {const open=!$('#sidebar').classList.contains('open');$('#sidebar').classList.toggle('open',open);$('.sidebar-scrim').hidden=!open;$('.menu-button').setAttribute('aria-expanded',String(open));}
function closeSidebar() {$('#sidebar').classList.remove('open');$('.sidebar-scrim').hidden=true;$('.menu-button').setAttribute('aria-expanded','false');}
function toggleTheme() {const light=document.documentElement.dataset.theme!=='light';document.documentElement.dataset.theme=light?'light':'dark';$('#theme-button').innerHTML=icon(light?'moon':'sun');$('#theme-button').setAttribute('aria-label',light?'Passer au thème sombre':'Passer au thème clair');}
document.addEventListener('click',async e=>{
  const b=e.target.closest('button,a');if(!b)return;
  if(b.dataset.scenario){openScenario(b.dataset.scenario);return;}
  if(b.dataset.thread){openScenario(b.dataset.thread,true);return;}
  if(b.dataset.close){$(`#${b.dataset.close}`).close();return;}
  if(b.dataset.provider){if(b.dataset.provider==='text'&&(state.attachments.length||state.messages.some(m=>m.images?.length)||state.sharing)){showToast('This conversation contains images. Keep Gemini, or start a new text-only conversation.');closeMenus();return;}state.provider=b.dataset.provider;closeMenus();renderComposer();renderPanel();return;}
  if(b.dataset.remove!==undefined){state.attachments.splice(Number(b.dataset.remove),1);renderAttachments();renderComposer();return;}
  if(b.dataset.draftImage!==undefined){openImage(state.attachments[Number(b.dataset.draftImage)]);return;}
  if(b.dataset.image){const [i,j]=b.dataset.image.split(':').map(Number);openImage(state.messages[i].images[j]);return;}
  if(b.dataset.contextImage!==undefined){openImage(state.messages.flatMap(m=>m.images||[])[Number(b.dataset.contextImage)]);return;}
  if(b.dataset.copy!==undefined){const text=b.closest('.assistant-message').querySelector('.copy').innerText;try{await navigator.clipboard.writeText(text);showToast('Response copied.');}catch{showToast('Clipboard unavailable here. Select the response text to copy it.');}return;}
  if(b.dataset.read!==undefined){state.live=true;state.phase='speaking';state.panel='live';renderComposer();renderPanel();showToast('Voice playback preview. Audio is simulated.');return;}
  if(b.dataset.share){state.shareChoice=b.dataset.share;renderShareChoice();return;}
  const actions={new:newConversation,sidebar:toggleSidebar,sample:addSample,upload:()=>{if(requireVision())$('#image-input').click();},live:()=>state.live?(state.panel='live',renderPanel()):startLive(),'end-live':endLive,share:()=>shareDialog(),camera:()=>shareDialog('camera'),'stop-sharing':()=>{state.sharing=null;renderComposer();renderPanel();showToast('Sharing stopped. Your voice conversation can continue.');},'close-panel':()=>{state.panel=null;renderPanel();},mute:()=>{state.phase=state.phase==='paused'?'listening':'paused';renderComposer();renderPanel();},interrupt,sketch:()=>openImage(sketch)};
  if(actions[b.dataset.action])actions[b.dataset.action]();
});
$('#brand-home').addEventListener('click',e=>{e.preventDefault();newConversation();});
$('#provider-button').addEventListener('click',()=>toggleMenu('provider'));
$('#attach-button').addEventListener('click',()=>toggleMenu('attach'));
$('#theme-button').addEventListener('click',toggleTheme);
$('#notes-button').addEventListener('click',()=>$('#notes-dialog').showModal());
$('#context-button').addEventListener('click',()=>{state.panel=state.panel==='context'?null:'context';renderPanel();});
$('#live-expand').addEventListener('click',()=>{state.panel='live';renderPanel();});
$('#composer').addEventListener('submit',sendMessage);
$('#composer-input').addEventListener('input',renderComposer);
$('#composer-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendMessage();}});
$('#composer-input').addEventListener('paste',e=>{if(e.clipboardData.files.length){e.preventDefault();addFiles(e.clipboardData.files);}});
$('#image-input').addEventListener('change',e=>{addFiles(e.target.files);e.target.value='';});
$('#composer').addEventListener('dragover',e=>{e.preventDefault();$('#composer').classList.add('dragging');});
$('#composer').addEventListener('dragleave',e=>{if(!$('#composer').contains(e.relatedTarget))$('#composer').classList.remove('dragging');});
$('#composer').addEventListener('drop',e=>{e.preventDefault();$('#composer').classList.remove('dragging');addFiles(e.dataTransfer.files);});
$('#stop-button').addEventListener('click',stopResponse);
$('#confirm-share').addEventListener('click',confirmShare);
$('#context-panel').addEventListener('change',e=>{if(e.target.id==='phase-select'){state.phase=e.target.value;renderComposer();renderPanel();}});
$('#thread-search').addEventListener('input',e=>{const query=e.target.value.toLowerCase();let found=0;$$('[data-thread]').forEach(b=>{b.hidden=!b.textContent.toLowerCase().includes(query);if(!b.hidden)found++;});$('.thread-empty').hidden=found>0;});
$('#retry-button').addEventListener('click',()=>{const btn=$('#retry-button');btn.textContent='Reconnecting…';btn.disabled=true;state.reconnectTimer=setTimeout(()=>{state.error=false;state.phase='listening';btn.textContent='Reconnect';btn.disabled=false;renderComposer();showToast('Reconnected. Your draft and images are ready.');},950);});
$('#dictation-button').addEventListener('click',()=>{if(state.dictationTimer){clearTimeout(state.dictationTimer);state.dictationTimer=null;$('#dictation-button').innerHTML=icon('mic');$('#dictation-button').setAttribute('aria-label','Dictate a message');return;}$('#dictation-button').innerHTML=icon('stop');$('#dictation-button').setAttribute('aria-label','Stop dictation');showToast('Dictation preview: a sample sentence will be added to your draft.');state.dictationTimer=setTimeout(()=>{const input=$('#composer-input');input.value+=(input.value?' ':'')+'Let’s make room for text, images and voice.';state.dictationTimer=null;$('#dictation-button').innerHTML=icon('mic');$('#dictation-button').setAttribute('aria-label','Dictate a message');renderComposer();input.focus();},1100);});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('.provider-anchor,.attach-anchor'))closeMenus();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeMenus();closeSidebar();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='n'){e.preventDefault();newConversation();}});
window.addEventListener('beforeunload',()=>objectURLs.forEach(url=>URL.revokeObjectURL(url)));
hydrate();render();
