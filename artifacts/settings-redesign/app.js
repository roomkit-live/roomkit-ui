/* An isolated interaction model. Nothing reads or writes RoomKit settings. */
const icons = {
  general: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  conversation: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H5l-3 2V11.5A8.5 8.5 0 0 1 10.5 3h2a8.5 8.5 0 0 1 8.5 8.5Z"/><path d="M7 10h9M7 14h6"/>',
  audio: '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
  mic: '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
  speaker: '<path d="m11 4-6 5H2v6h3l6 5V4ZM15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/>',
  keys: '<circle cx="8" cy="8" r="5"/><path d="m12 12 9 9M17 17l3-3M14 14l3-3"/>',
  models: '<path d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>',
  integrations: '<path d="M8 3v5M16 3v5M5 8h14v3a7 7 0 0 1-14 0V8ZM12 18v4"/>',
  privacy: '<path d="m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5l8-3Z"/><path d="m8 11 3 3 5-5"/>',
  diagnostics: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.1"/>',
  keyboard: '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M6 9h.1M10 9h.1M14 9h.1M18 9h.1M6 13h.1M10 13h.1M14 13h.1M18 13h.1M7 16h10"/>',
  spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  cloud: '<path d="M6 18a4 4 0 0 1-1-7.9A7 7 0 0 1 18.5 8 5 5 0 0 1 18 18H6Z"/>',
  local: '<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M8 21h8M12 16v5"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  play: '<path d="m8 4 12 8-12 8V4Z"/>',
  users: '<circle cx="9" cy="7" r="4"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 7M20 21v-3a7 7 0 0 0-3-5"/>',
  terminal: '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m6 9 3 3-3 3M12 15h5"/>',
  moon: '<path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
};
const icon = (name) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.general}</svg>`;
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sections = [
  { group: 'WORKSPACE', id: 'general', label: 'General', icon: 'general', description: 'Appearance, shortcuts, and everyday preferences.' },
  { group: 'WORKSPACE', id: 'conversation', label: 'Conversation', icon: 'conversation', description: 'Choose how your assistant listens, thinks, and speaks.' },
  { group: 'WORKSPACE', id: 'audio', label: 'Audio & voice', icon: 'audio', description: 'Sound clear. Hear clearly. Make room for your voice.' },
  { group: 'WORKSPACE', id: 'dictation', label: 'Dictation & wake word', icon: 'mic', description: 'Bring your assistant into the way you work.' },
  { group: 'CAPABILITIES', id: 'providers', label: 'Providers & keys', icon: 'keys', description: 'One connection for every place you use a provider.' },
  { group: 'CAPABILITIES', id: 'models', label: 'Models & components', icon: 'models', description: 'Everything your local setup needs, in one place.' },
  { group: 'CAPABILITIES', id: 'integrations', label: 'Integrations', icon: 'integrations', description: 'Give your assistant the tools and skills it needs.' },
  { group: 'SYSTEM', id: 'privacy', label: 'Privacy & memory', icon: 'privacy', description: 'Understand what is remembered, recorded, and shared.' },
  { group: 'SYSTEM', id: 'diagnostics', label: 'Diagnostics', icon: 'diagnostics', description: 'Inspect audio and traces when you need a closer look.' },
  { group: 'SYSTEM', id: 'about', label: 'About RoomKit', icon: 'info', description: 'A voice assistant that works your way.' },
];
const state = {
  theme: 'light', mode: 'realtime', realtimeProvider: 'gemini', geminiVoice: 'Aoede', openaiVoice: 'alloy',
  assistantHotkey: true, assistantKeys: ['⌃', '⇧', 'A'], dictationKeys: ['Right ⌘'],
  memory: true, dictation: true, wakeword: false, wakewordEnrolled: false, hangup: false, hangupSeconds: '15',
  inputDevice: 'System default', outputDevice: 'System default', aec: 'WebRTC', denoise: 'None', inference: 'CPU',
  vad: 'Silero VAD', vadThreshold: '0.35', silenceMs: '500', turnDetector: 'None',
  dictationProvider: 'Local', dictationLanguage: 'Auto-detect', translate: false,
  personality: 'Concise', prompt: 'You are a friendly voice assistant. Be concise and helpful.',
  recording: false, debugTaps: false, telemetry: 'Disabled', endpoint: '',
  geminiKey: true, openaiKey: false, anthropicKey: true, deepgramKey: false,
  geminiInstalled: true, openaiInstalled: true, anthropicInstalled: true, deepgramInstalled: false,
  localInstalled: true, pocketInstalled: false,
  vcSTT: 'Local', vcLLM: 'Anthropic', vcTTS: 'Piper', interruption: 'Any speech',
  speaking: 'Always respond', thinker: false, background: false,
  downloaded: ['whisper-small', 'silero', 'piper'], downloading: {},
  integrationTab: 'mcp', conversationTab: 'setup', audioTab: 'devices', modelsTab: 'models', dictationTab: 'dictation',
  integrations: [], speakerNames: [], userName: '', speakerGate: false,
};
let currentPage = 'general';
let saveTimer, toastTimer, searchIndex = 0;
const providers = {
  gemini: { name: 'Google Gemini', symbol: '✦', style: 'gemini', uses: 'Realtime conversations · Voice Channel', model: 'Gemini native audio', key: 'geminiKey', installed: 'geminiInstalled' },
  openai: { name: 'OpenAI', symbol: '◎', style: '', uses: 'Realtime · Voice Channel · Dictation', model: 'GPT Realtime', key: 'openaiKey', installed: 'openaiInstalled' },
  anthropic: { name: 'Anthropic', symbol: 'A', style: 'anthropic', uses: 'Voice Channel reasoning', model: 'Claude Sonnet', key: 'anthropicKey', installed: 'anthropicInstalled' },
  deepgram: { name: 'Deepgram', symbol: 'D', style: '', uses: 'Voice Agent · Transcription · Dictation', model: 'Nova', key: 'deepgramKey', installed: 'deepgramInstalled' },
};
const badge = (text, tone = '') => `<span class="badge ${tone}">${text}</span>`;
const button = (text, action, attrs = '', primary = false) => `<button class="button${primary ? ' primary' : ''}" data-action="${action}" ${attrs}>${text}</button>`;
const link = (text, page, target = '') => `<button class="subtle-link" data-page="${page}"${target ? ` data-target="${target}"` : ''}>${text}${icon('arrow')}</button>`;
const toggle = (key, label, disabled = false) => `<button class="switch" role="switch" aria-checked="${state[key]}" aria-label="${escapeHTML(label)}" data-toggle="${key}"${disabled ? ' disabled' : ''}></button>`;
const options = (values, value) => values.map(v => `<option${v === value ? ' selected' : ''}>${escapeHTML(v)}</option>`).join('');
const select = (key, label, values) => `<select data-setting="${key}" aria-label="${escapeHTML(label)}">${options(values, state[key])}</select>`;
const row = (label, description, control, id = '') => `<div class="row"${id ? ` id="${id}"` : ''}><div class="row-copy"><span class="row-label">${label}</span>${description ? `<span class="row-description">${description}</span>` : ''}</div><div class="row-control">${control}</div></div>`;
const section = (title, description, body, id = '', trailing = '') => `<section class="section"${id ? ` id="${id}"` : ''}><div class="section-heading"><div><h2>${title}</h2>${description ? `<p>${description}</p>` : ''}</div>${trailing}</div>${body}</section>`;
const field = (label, key, values) => `<div class="field"><label for="field-${key}">${label}</label><select id="field-${key}" data-setting="${key}">${options(values, state[key])}</select></div>`;
const textField = (label, key, type = 'text', extra = '') => `<div class="field"><label for="field-${key}">${label}</label><input class="input" id="field-${key}" type="${type}" data-setting="${key}" value="${escapeHTML(state[key])}" ${extra}></div>`;
const notice = (text, tone = '') => `<div class="notice ${tone}">${icon('info')}<span>${text}</span></div>`;
const tabs = (key, entries) => `<div class="tabs" aria-label="Page sections">${entries.map(([id, title]) => `<button data-tab="${key}" data-value="${id}" aria-pressed="${state[key] === id}">${title}</button>`).join('')}</div>`;
const keycaps = (keys) => `<span class="key-combo">${keys.map(k => `<kbd>${escapeHTML(k)}</kbd>`).join('')}</span>`;
const advanced = (title, content) => `<details class="advanced"><summary>${title}</summary><div class="advanced-content">${content}</div></details>`;
function setupRail() {
  const provider = state.mode === 'realtime' ? providers[state.realtimeProvider].name : state.vcLLM;
  return `<aside class="context-rail" aria-label="Preview configuration"><p class="eyebrow">YOUR SETUP AT A GLANCE</p>
    <div class="setup-item"><span class="setup-label">Conversation</span><span class="setup-value">${icon('conversation')}${state.mode === 'realtime' ? 'Realtime' : 'Voice Channel'}</span></div>
    <div class="setup-item"><span class="setup-label">AI provider</span><span class="setup-value">${icon('spark')}${provider}</span></div>
    <div class="setup-item"><span class="setup-label">Microphone</span><span class="setup-value">${icon('mic')}${escapeHTML(state.inputDevice)}</span></div>
    <div class="setup-item"><span class="setup-label">Conversation memory</span><span class="setup-value">${icon('local')}${state.memory ? 'On · stored locally' : 'Off'}</span></div>
    <div class="rail-divider"></div><p class="rail-help">Sample configuration.<br>Changes here only affect this preview.</p>${link('Review conversation', 'conversation')}
  </aside>`;
}
function themePreview(theme, label) {
  return `<button class="theme-choice" data-theme-choice="${theme}" aria-pressed="${state.theme === theme}" aria-label="${label} appearance">
    <span class="theme-preview ${theme === 'dark' ? 'dark-preview' : ''}" aria-hidden="true"><span class="mini-window"><span class="mini-side"><span class="mini-dots"><i></i><i></i><i></i></span><span class="mini-line active" style="display:block"></span><span class="mini-line" style="display:block"></span><span class="mini-line" style="display:block"></span></span><span class="mini-main"><span class="mini-line" style="display:block"></span><span class="mini-block" style="display:block"></span><span class="mini-block" style="display:block"></span></span></span></span>
    <span class="theme-label">${label}<span class="choice-check">✓</span></span></button>`;
}
function generalPage() {
  return section('Appearance', 'A comfortable space, day or night.', `<div class="theme-options">${themePreview('light', 'Light')}${themePreview('dark', 'Dark')}</div><p class="section-note">${icon('info')}Your choice is previewed immediately.</p>`, 'appearance') +
    section('Keyboard shortcuts', 'One gesture to start a conversation.', `<div class="card">${row('Talk to your assistant', 'Start or end a voice session from any app.', toggle('assistantHotkey', 'Enable assistant shortcut'), 'assistant-shortcut')}${row('Assistant shortcut', 'Click the keys to record a new shortcut.', `<button class="shortcut-button" data-action="shortcut" data-key="assistantKeys" aria-label="Change assistant shortcut"${state.assistantHotkey ? '' : ' disabled'}>${keycaps(state.assistantKeys)}</button>`)}${row('Dictation shortcut', 'Speak directly into the app you are using.', `<button class="shortcut-button" data-action="shortcut" data-key="dictationKeys" aria-label="Change dictation shortcut">${keycaps(state.dictationKeys)}</button>`)}</div>`, 'shortcuts') +
    section('Make it yours', '', `<div class="card">${row('Your assistant’s personality', 'Adjust its tone and the way it responds.', link(state.personality, 'conversation', 'personality'))}${row('Conversation memory', 'Choose what carries over between sessions.', link(state.memory ? 'On · manage' : 'Off · manage', 'privacy', 'memory'))}</div>`) +
    `<div class="guide-card">${icon('audio')}<div><strong>Start with a sound check</strong><p>Choose your microphone and speaker before your next conversation.</p></div>${link('Audio settings', 'audio')}</div>`;
}
function providerSetup() {
  const p = providers[state.realtimeProvider];
  const hasKey = state[p.key];
  const keyStatus = hasKey ? badge('Key added · not tested', 'green') : badge('API key needed', 'amber');
  return `<div class="card"><div class="provider-row"><div class="provider-symbol ${p.style}">${p.symbol}</div><div class="provider-copy"><strong>${p.name}</strong><small>Native voice conversation</small></div>${keyStatus}</div><div class="padded-card"><div class="field-grid"><div class="field"><label for="field-realtimeProvider">Provider</label><select id="field-realtimeProvider" data-setting="realtimeProvider"><option value="gemini"${state.realtimeProvider === 'gemini' ? ' selected' : ''}>Google Gemini</option><option value="openai"${state.realtimeProvider === 'openai' ? ' selected' : ''}>OpenAI</option></select></div><div class="field"><label for="realtime-model">Model</label><select id="realtime-model" data-notify="Model selected for this preview"><option>${p.model}</option></select></div></div></div>${row('Assistant voice', 'The voice you hear during a conversation.', state.realtimeProvider === 'gemini' ? select('geminiVoice', 'Assistant voice', ['Aoede', 'Puck', 'Charon', 'Kore', 'Fenrir']) : select('openaiVoice', 'Assistant voice', ['alloy', 'ash', 'coral', 'sage', 'verse']))}${row('Provider connection', 'Shared across conversations and dictation.', link(hasKey ? 'Manage key' : 'Add a key', 'providers'))}</div>
    ${!hasKey ? notice('Add an API key in Providers & keys before starting a real conversation.', 'amber') : ''}
    ${advanced('Advanced realtime settings', '<p class="rail-help">Only settings supported by the selected provider should appear here. The full provider-specific catalog remains available in the native app.</p>' + row('Interruption', 'Choose whether your speech can interrupt the assistant.', select('interruption', 'Interruption', ['Any speech', 'Off'])) + textField('Silence before replying (ms)', 'silenceMs', 'number', 'min="100" max="5000" step="100"'))}`;
}
function pipelineSetup() {
  return `<div class="pipeline" aria-label="Voice Channel processing order"><div class="pipeline-step"><small>01 · TRANSCRIBE</small><strong>${state.vcSTT}</strong></div><span aria-hidden="true">→</span><div class="pipeline-step"><small>02 · REASON</small><strong>${state.vcLLM}</strong></div><span aria-hidden="true">→</span><div class="pipeline-step"><small>03 · SPEAK</small><strong>${state.vcTTS}</strong></div></div>
  <div class="card">${row('Transcription', 'Turn your speech into text.', select('vcSTT', 'Transcription provider', ['Local', 'Deepgram', 'Gradium', 'Meta Muse']))}${row('Intelligence', 'Generate the assistant’s response.', select('vcLLM', 'AI provider', ['Anthropic', 'OpenAI', 'Google Gemini', 'Ollama', 'llama.cpp']))}${row('Speech', 'Read the response in the voice you choose.', select('vcTTS', 'Speech provider', ['Piper', 'ElevenLabs', 'Pocket TTS']))}</div>
  ${notice('Each step can run locally or use a cloud provider. Connections are managed in Providers & keys.')}
  ${advanced('Turn-taking & agent behavior', row('Interrupt the assistant', 'With an offline model, words arrive after you stop speaking.', select('interruption', 'Interruption', ['Any speech', 'Words only', 'Off'])) + row('When to respond', 'A classifier can decide whether a reply is needed.', select('speaking', 'Speaking policy', ['Always respond', 'When addressed'])) + row('Think while listening', state.speaking === 'Always respond' ? 'Choose “When addressed” to enable a classifier first.' : 'Prepare a response before your turn is over.', toggle('thinker', 'Think while listening', state.speaking === 'Always respond')) + row('Work in the background', 'Let the agent complete tasks between turns.', toggle('background', 'Work in the background')))}`;
}
function personalityPage() {
  const examples = { Concise: '“Your next meeting is at 2 pm. You have 20 minutes to prepare.”', Professional: '“Your next meeting begins at 2 pm. Would you like a summary of the agenda?”', Friendly: '“You’ve got a meeting at 2! Want to go over the agenda together?”' };
  return section('Personality', 'Set the default tone for your conversations.', `<div class="card padded-card"><div class="chip-options">${Object.keys(examples).map(name => `<button class="chip" data-personality="${name}" aria-pressed="${state.personality === name}">${name}</button>`).join('')}</div><blockquote class="persona-example">${examples[state.personality]}</blockquote><p class="section-note">Illustrative response · no AI request is made.</p></div>`, 'personality') +
    section('Instructions', 'Give your assistant a role and a few clear guidelines.', `<div class="card padded-card"><label class="sr-only" for="system-prompt">System instructions</label><textarea id="system-prompt" class="input" data-setting="prompt">${escapeHTML(state.prompt)}</textarea><p class="section-note">Applies to both conversation modes on the next session.</p></div>`, 'instructions');
}
function conversationPage() {
  return tabs('conversationTab', [['setup', 'Voice setup'], ['personality', 'Personality & instructions']]) +
    (state.conversationTab === 'personality' ? personalityPage() :
    section('Conversation mode', 'Choose the experience. Fine-tune the details below.', `<div class="mode-options"><button class="mode-option" data-mode="realtime" aria-pressed="${state.mode === 'realtime'}"><span class="mode-top">${icon('audio')}<span class="choice-check">✓</span></span><strong>Realtime</strong><p>A single provider handles a fluid, live voice conversation.</p></button><button class="mode-option" data-mode="voice_channel" aria-pressed="${state.mode === 'voice_channel'}"><span class="mode-top">${icon('models')}<span class="choice-check">✓</span></span><strong>Voice Channel</strong><p>Choose separate models for transcription, reasoning, and speech.</p></button></div>`, 'conversation-mode') +
    section(state.mode === 'realtime' ? 'Your voice assistant' : 'Build your voice pipeline', '', state.mode === 'realtime' ? providerSetup() : pipelineSetup(), 'voice-setup') +
    `<p class="section-note">${icon('clock')}Conversation changes take effect on the next session.</p>`);
}
function audioPage() {
  const device = (kind, key, title, choices) => `<div class="audio-device" id="${kind}"><div class="audio-device-heading">${icon(kind)}${title}</div><div class="device-controls">${select(key, title, choices)}${button(icon('play') + 'Test', 'audio-test', `data-kind="${kind}"`)}</div><div class="meter-row"><div class="meter" id="meter-${kind}" aria-hidden="true">${'<i></i>'.repeat(24)}</div><span class="meter-label" id="meter-label-${kind}">Click to simulate</span></div></div>`;
  return tabs('audioTab', [['devices', 'Devices & processing'], ['speakers', 'Speaker recognition']]) +
    (state.audioTab === 'speakers' ? speakersPage() :
    section('Audio devices', 'Choose where sound comes in and goes out.', `<div class="card">${device('mic', 'inputDevice', 'Microphone', ['System default', 'MacBook microphone', 'USB microphone'])}${device('speaker', 'outputDevice', 'Speaker', ['System default', 'MacBook speakers', 'Headphones'])}</div><p class="section-note">${icon('info')}Sample devices. Tests animate the preview without using your microphone.</p>`, 'audio-devices') +
    section('Sound quality', 'Keep the conversation focused on your voice.', `<div class="card">${row('Echo cancellation', 'Prevent your speaker audio from being picked up again.', select('aec', 'Echo cancellation', ['WebRTC', 'Speex', 'None']))}${row('Noise reduction', 'Available in Voice Channel mode. Realtime uses its own audio path.', state.mode === 'voice_channel' ? select('denoise', 'Noise reduction', ['None', 'RNNoise', 'GTCRN']) : badge('Voice Channel only', 'outline'))}</div>`, 'sound-quality') +
    advanced('Advanced audio · detection & performance', `<div class="field-grid">${field('Voice activity detection (VAD)', 'vad', ['Silero VAD', 'None'])}${field('Inference device', 'inference', ['CPU', 'CoreML'])}${textField('Speech threshold', 'vadThreshold', 'number', 'min="0" max="1" step="0.05"')}${textField('Silence duration (ms)', 'silenceMs', 'number', 'min="100" max="5000" step="100"')}</div>${notice('Models and components must be available before using a detector. Only Voice Channel uses noise reduction; VAD also supports local speaker recognition.')}${link('Manage audio models', 'models')}`));
}
function speakersPage() {
  return section('Recognize who is speaking', 'Name voices and choose whose speech the assistant follows.', `<div class="card">${state.speakerNames.length ? state.speakerNames.map(n => `<div class="item-row">${icon('users')}<div class="item-info"><strong>${escapeHTML(n)}</strong><small>Sample voice profile · no audio recorded</small></div>${badge('Demo profile', 'purple')}</div>`).join('') : `<div class="empty-state">${icon('users')}<h3>No voice profiles yet</h3><p>Local recognition needs an enrolled voice. Meta Muse can distinguish speakers live without enrollment.</p>${button('Preview voice enrollment', 'enroll-speaker')}</div>`}</div>`, 'speaker-profiles') +
    `<div class="card">${row('Listen only to the primary speaker', 'Requires speaker recognition and a named primary speaker.', toggle('speakerGate', 'Listen only to primary speaker', !state.speakerNames.length))}</div>${notice('Voice recognition depends on the selected transcription provider. This preview illustrates enrollment and the empty state.')}`;
}
function dictationPage() {
  return tabs('dictationTab', [['dictation', 'Dictation'], ['wakeword', 'Wake word & sessions']]) + (state.dictationTab === 'wakeword' ? wakewordPage() :
    section('Type with your voice', 'Speak, then paste the transcription into the focused app.', `<div class="card">${row('Enable dictation', 'Use a global shortcut to start and stop recording.', toggle('dictation', 'Enable dictation'))}${row('Shortcut', 'Available from any application.', `<button class="shortcut-button" data-action="shortcut" data-key="dictationKeys" aria-label="Change dictation shortcut">${keycaps(state.dictationKeys)}</button>`)}</div>`, 'dictation-shortcut') +
    section('Transcription', 'Choose where your speech is processed.', `<div class="card">${row('Provider', state.dictationProvider === 'Local' ? 'Speech is transcribed on this device.' : 'Speech is sent to the selected cloud provider.', select('dictationProvider', 'Dictation provider', ['Local', 'OpenAI', 'Deepgram']))}${state.dictationProvider === 'Local' ? row('Local model', 'Whisper Small · downloaded in this sample setup.', badge('Whisper Small', 'outline')) : row('API connection', 'Uses the shared key from Providers & keys.', link('Manage connection', 'providers'))}${row('Language', 'Use automatic detection or choose your language.', select('dictationLanguage', 'Dictation language', ['Auto-detect', 'English', 'French', 'Spanish', 'German']))}${state.dictationProvider === 'Local' ? row('Translate to English', 'Supported by Whisper models.', toggle('translate', 'Translate dictation to English')) : ''}</div>`, 'transcription') +
    `<div class="guide-card">${icon(state.dictationProvider === 'Local' ? 'local' : 'cloud')}<div><strong>${state.dictationProvider === 'Local' ? 'This transcription stays on your device' : 'This transcription uses a cloud service'}</strong><p>${state.dictationProvider === 'Local' ? 'The local model can work without an internet connection.' : 'Your selected provider receives the audio needed to transcribe it.'}</p></div></div>`);
}
function wakewordPage() {
  return section('Start with your voice', 'An enrolled phrase can open a new conversation.', `<div class="card">${row('Listen for a wake word', state.wakewordEnrolled ? 'Your sample phrase is ready.' : 'Set up a phrase before enabling detection.', toggle('wakeword', 'Listen for a wake word', !state.wakewordEnrolled))}<div class="padded-card">${state.wakewordEnrolled ? badge('“Hey RoomKit” · demo phrase', 'purple') : '<p class="rail-help">No phrase enrolled. In the app, a short guided recording teaches RoomKit your wake phrase.</p>'}${button(state.wakewordEnrolled ? 'Review demo phrase' : 'Preview setup', 'wakeword-setup')}</div></div>${notice('Wake-word detection runs locally. After it triggers, a conversation uses the provider configured in Conversation.')}`, 'wakeword') +
    section('End a quiet session', 'Avoid leaving a conversation open when you step away.', `<div class="card">${row('End after inactivity', 'Applies to all sessions, including manually started ones.', toggle('hangup', 'End after inactivity'))}${state.hangup ? row('Wait before ending', 'Measured after the conversation goes quiet.', select('hangupSeconds', 'Inactivity delay in seconds', ['15', '30', '60', '120'])) : ''}</div>`, 'session-timeout');
}
function providersPage() {
  return section('Cloud providers', 'Keys are shared by every feature that uses the same provider.', `<div class="card">${Object.entries(providers).map(([id, p]) => `<div class="item-row"><div class="provider-symbol ${p.style}">${p.symbol}</div><div class="item-info"><strong>${p.name}</strong><small>${p.uses}</small></div><div class="item-actions">${badge(!state[p.installed] ? 'Component needed' : state[p.key] ? 'Key added' : 'No key', !state[p.installed] || !state[p.key] ? 'amber' : 'green')}${button('Manage', 'manage-provider', `data-provider="${id}"`)}</div></div>`).join('')}</div><p class="section-note">${icon('info')}“Key added” means a value is present. It does not mean a connection has been verified.</p>`, 'provider-keys') +
    section('Local providers', 'Run models on your own machine.', `<div class="card">${row('Ollama / vLLM', 'Connect to a running local server.', button('Configure', 'local-provider'))}${row('llama.cpp', 'Run a GGUF model through RoomKit’s managed server.', link('Models & components', 'models'))}</div>`) +
    notice('This is a representative provider list. The native redesign should retain every supported provider, including Azure, Gradium, Meta, ElevenLabs, xAI, and TypeSafe.');
}
const models = [
  { id: 'whisper-small', name: 'Whisper Small', detail: 'Transcription · offline · ~357 MB', kind: 'mic' },
  { id: 'parakeet-offline', name: 'Parakeet', detail: 'Transcription · offline · ~640 MB', kind: 'mic' },
  { id: 'kroko-streaming-fr', name: 'Kroko Streaming (FR)', detail: 'Transcription · streaming · ~147 MB', kind: 'mic' },
  { id: 'silero', name: 'Silero VAD', detail: 'Voice activity detection', kind: 'audio' },
  { id: 'piper', name: 'Piper voice', detail: 'Speech synthesis · local voice', kind: 'speaker' },
];
function modelsPage() {
  return tabs('modelsTab', [['models', 'Local models'], ['components', 'Components']]) + (state.modelsTab === 'components' ? componentsPage() :
    section('Local model library', 'Download once. Use across conversations and dictation.', `<div class="card">${models.map(m => `<div class="item-row"><div class="provider-symbol">${icon(m.kind)}</div><div class="item-info"><strong>${m.name}</strong><small>${m.detail}</small></div><div class="item-actions" id="model-action-${m.id}">${modelAction(m.id)}</div></div>`).join('')}</div>`, 'model-library', badge(`${state.downloaded.length} downloaded`, 'outline')) +
    `<div class="guide-card">${icon('models')}<div><strong>A model and a component do different jobs</strong><p>Models are data. Components add the software needed to run them.</p></div><button class="subtle-link" data-tab="modelsTab" data-value="components">View components ${icon('arrow')}</button></div>`);
}
function modelAction(id) {
  return state.downloaded.includes(id) ? badge('Downloaded', 'green') : state.downloading[id] !== undefined ? `<div class="download-progress" role="progressbar" aria-label="Simulated download" aria-valuenow="${state.downloading[id]}" aria-valuemin="0" aria-valuemax="100"><i style="width:${state.downloading[id]}%"></i></div>${button('Cancel', 'cancel-download', `data-model="${id}"`)}` : button(icon('download') + 'Download', 'download-model', `data-model="${id}"`);
}
function componentsPage() {
  return section('Installed capabilities', 'Software packages that power RoomKit’s features.', `<div class="card">${row('Local voice', 'Offline transcription, Piper TTS, and speaker recognition.', badge('Installed', 'green'))}${row('Google Gemini', 'Realtime conversations and text generation.', badge('Installed', 'green'))}${row('Deepgram', 'Cloud transcription and Voice Agent.', state.deepgramInstalled ? badge('Installed in preview', 'green') : button('Preview install', 'install-component', 'data-component="deepgramInstalled"'))}${row('Pocket TTS', 'Local speech synthesis and voice cloning.', state.pocketInstalled ? badge('Installed in preview', 'green') : button('Preview install', 'install-component', 'data-component="pocketInstalled"'))}</div>${notice('The native app must adapt this action to its installation: install for supported pip/uv environments, copy a command for source checkouts, or explain bundled-app limitations. The preview only simulates completion.')}`, 'components');
}
function integrationsPage() {
  const tab = state.integrationTab;
  const descriptions = { mcp: ['Connected tools', 'MCP servers expose tools your assistant can use.', 'integrations', 'No MCP servers yet', 'Connect a server to bring external tools into your conversations.', 'Add server'], cli: ['Command-line tools', 'Make selected local commands available to your assistant.', 'terminal', 'No CLI tools yet', 'Declare a command and describe when the assistant should use it.', 'Add CLI tool'], skills: ['Agent skills', 'Reusable instructions for tasks your assistant performs.', 'spark', 'No skills enabled', 'Add a local source or a Git repository to discover skills.', 'Add skill source'] };
  const [title, description, glyph, emptyTitle, emptyDescription, action] = descriptions[tab];
  const items = state.integrations.filter(i => i.type === tab);
  return tabs('integrationTab', [['mcp', 'MCP servers'], ['cli', 'CLI tools'], ['skills', 'Skills']]) +
    section(title, description, `<div class="card">${items.length ? items.map(i => `<div class="item-row">${icon(glyph)}<div class="item-info"><strong>${escapeHTML(i.name)}</strong><small>${escapeHTML(i.endpoint)} · preview only</small></div>${badge('Not connected', 'outline')}<button class="icon-button" aria-label="Remove ${escapeHTML(i.name)}" data-action="remove-integration" data-id="${i.id}">×</button></div>`).join('') : `<div class="empty-state">${icon(glyph)}<h3>${emptyTitle}</h3><p>${emptyDescription}</p>${button('+ ' + action, 'add-integration', '', true)}</div>`}</div>`, 'integrations-list', items.length ? button('+ ' + action, 'add-integration') : '') +
    notice(tab === 'mcp' ? 'Keep connection, authorization, and enabled state distinct. A configured server is not necessarily connected.' : tab === 'cli' ? 'In the app, enabled commands can run with your user permissions. This prototype only creates a sample entry.' : 'Skills supply instructions; enabling a skill does not grant a new connection or install a model.');
}
function privacyPage() {
  return `<div class="privacy-visual">${icon('privacy')}<div><strong>Local memory. Clear boundaries.</strong><p>Conversation history is stored locally. Your selected cloud provider still receives the content needed for your conversation.</p></div></div>` +
    section('Conversation memory', 'Choose whether past sessions inform future conversations.', `<div class="card">${row('Remember conversations', 'Save local history so your assistant can recall previous sessions.', toggle('memory', 'Remember conversations'), 'memory')}${row('Where memory lives', 'Stored in RoomKit’s local application data directory.', badge('On this device', 'outline'))}</div>`) +
    section('Audio recording', 'Keep a recording only when you choose to.', `<div class="card">${row('Record sessions', 'Save session audio locally. Separate from text history.', toggle('recording', 'Record sessions'), 'recording')}${state.recording ? row('Recording mode', 'Both your voice and the assistant’s audio.', badge('Both · stereo', 'outline')) : ''}</div>`) +
    section('Connections & observability', '', `<div class="card">${row('Provider credentials', 'Review the services your assistant uses.', link('Manage keys', 'providers'))}${row('Telemetry', state.telemetry === 'Disabled' ? 'Trace export is currently off in this preview.' : `Trace destination: ${state.telemetry}.`, link('Review diagnostics', 'diagnostics'))}</div>`) +
    `<p class="section-note">${icon('info')}Turning off memory stops future persistence; it does not erase existing history.</p>`;
}
function diagnosticsPage() {
  return section('Audio inspection', 'Capture pipeline stages to troubleshoot sound problems.', `<div class="card">${row('Audio debug captures', 'Store diagnostic audio locally while a session runs.', toggle('debugTaps', 'Enable audio debug captures'))}${row('Session recordings', 'Recording is controlled separately in Privacy & memory.', link(state.recording ? 'On · manage' : 'Off · manage', 'privacy', 'recording'))}</div>`, 'audio-debug') +
    section('Telemetry', 'Collect timing and usage traces for your pipeline.', `<div class="card">${row('Trace destination', 'Off by default. Choose a destination when debugging.', select('telemetry', 'Telemetry destination', ['Disabled', 'Console', 'OTLP endpoint']))}${state.telemetry === 'OTLP endpoint' ? `<div class="padded-card">${textField('OTLP endpoint', 'endpoint', 'url', 'placeholder="http://localhost:4317"')}<p class="rail-help">Trace data is sent to this endpoint. Configuration is not validated by this preview.</p></div>` : ''}</div>`, 'telemetry') +
    section('Recent captures', '', `<div class="card"><div class="empty-state">${icon('diagnostics')}<h3>No diagnostic captures</h3><p>In the app, captured files appear here with their duration, size, playback, and deletion controls.</p></div></div>`) +
    `<p class="section-note">${icon('info')}There is no active RoomKit session behind this prototype.</p>`;
}
function aboutPage() {
  return `<div class="card padded-card"><div class="privacy-visual">${icon('audio')}<div><strong>RoomKit UI · 0.2.1</strong><p>A desktop voice assistant built with PySide6 and RoomKit.</p></div></div><p class="row-description">This design study reorganizes existing settings around everyday tasks. It is an HTML prototype intended to guide a native Qt implementation.</p><div class="dialog-actions"><a class="button" href="audit.html">Read the UX audit ↗</a></div></div>`;
}
const renderers = { general: generalPage, conversation: conversationPage, audio: audioPage, dictation: dictationPage, providers: providersPage, models: modelsPage, integrations: integrationsPage, privacy: privacyPage, diagnostics: diagnosticsPage, about: aboutPage };
function render() {
  const page = sections.find(s => s.id === currentPage);
  const main = document.querySelector('#main');
  const scroll = main.scrollTop;
  document.querySelector('#breadcrumb-current').textContent = page.label;
  document.querySelectorAll('[data-page]').forEach(b => {
    if (b.classList.contains('nav-item')) b.setAttribute('aria-current', b.dataset.page === currentPage ? 'page' : 'false');
  });
  main.innerHTML = `<div class="page"><div class="page-heading"><div><h1 id="page-title" tabindex="-1">${page.label}</h1><p>${page.description}</p></div><span class="icon-tile">${icon(page.icon)}</span></div><div class="content-grid"><div class="content-main">${renderers[currentPage]()}</div>${setupRail()}</div></div>`;
  main.scrollTop = scroll;
  document.body.dataset.theme = state.theme;
}
function navigate(page, target = '', focus = true) {
  if (!renderers[page]) return;
  if (page === 'conversation' && target) state.conversationTab = ['personality', 'instructions'].includes(target) ? 'personality' : 'setup';
  if (page === 'audio' && target) state.audioTab = target === 'speaker-profiles' ? 'speakers' : 'devices';
  if (page === 'dictation' && target) state.dictationTab = ['wakeword', 'session-timeout'].includes(target) ? 'wakeword' : 'dictation';
  if (page === 'models' && target) state.modelsTab = target === 'components' ? 'components' : 'models';
  currentPage = page;
  history.replaceState(null, '', `#${page}`);
  document.body.classList.remove('menu-open');
  document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false');
  render();
  document.querySelector('#main').scrollTop = 0;
  if (target) {
    const element = document.getElementById(target);
    if (element) { element.scrollIntoView({ block: 'center' }); element.classList.add('highlight-target'); }
  }
  if (focus) document.querySelector('#page-title').focus({ preventScroll: true });
}
function changed(message = 'Saved for this preview') {
  clearTimeout(saveTimer);
  const status = document.querySelector('#save-status');
  status.textContent = 'Saving preview…';
  saveTimer = setTimeout(() => { status.innerHTML = `<span class="saved-check">✓</span> ${escapeHTML(message)}`; }, 350);
}
function toast(message) {
  clearTimeout(toastTimer);
  const element = document.querySelector('#toast');
  element.textContent = message;
  element.classList.add('visible');
  toastTimer = setTimeout(() => element.classList.remove('visible'), 3500);
}
function detail(title, description, body, actionLabel = '', onSubmit = null) {
  const dialog = document.querySelector('#detail-dialog');
  document.querySelector('#detail-content').innerHTML = `<form id="detail-form"><div class="dialog-heading"><div><h2 id="detail-title">${title}</h2><p>${description}</p></div><button type="button" class="icon-button" data-close-dialog="detail-dialog" aria-label="Close dialog">×</button></div>${body}<div class="dialog-actions"><button type="button" class="button" data-close-dialog="detail-dialog">${actionLabel ? 'Cancel' : 'Done'}</button>${actionLabel ? `<button type="submit" class="button primary">${actionLabel}</button>` : ''}</div></form>`;
  document.querySelector('#detail-form').addEventListener('submit', event => { event.preventDefault(); if (onSubmit) onSubmit(new FormData(event.target), dialog); });
  dialog.showModal();
}
function manageProvider(id) {
  const p = providers[id];
  detail(p.name, 'Shared across every feature using this provider.', `<div class="card">${row('Component', 'The software needed to use this provider.', badge(state[p.installed] ? 'Installed' : 'Not installed', state[p.installed] ? 'green' : 'amber'))}${row('API key', 'A stored key has not necessarily been tested.', badge(state[p.key] ? 'Added · not tested' : 'Not added', state[p.key] ? 'green' : 'amber'))}</div><div class="field" style="margin-top:20px"><label for="demo-key">Sample key value</label><input class="input" id="demo-key" name="key" type="password" placeholder="Enter sample text" autocomplete="off" required><small>Use sample text only. This preview holds no real credentials.</small></div>${!state[p.installed] ? notice('The provider also needs its component. Find it in Models & components.', 'amber') : ''}`, 'Save demo key', (_data, dialog) => {
    state[p.key] = true;
    dialog.close();
    document.querySelector('#detail-content').replaceChildren();
    render(); changed(); toast(`${p.name}: demo key added, connection not tested.`);
  });
}
function recordShortcut(key) {
  let pending = null;
  detail('Record a shortcut', 'Press a modifier and a key. Escape cancels.', `<div class="card padded-card" style="text-align:center" id="shortcut-capture"><p class="rail-help">Waiting for a key combination…</p>${keycaps(state[key])}</div><p class="section-note">This preview does not register a system-wide shortcut.</p>`, 'Use shortcut', (_data, dialog) => {
    if (!pending) { document.querySelector('#shortcut-capture').innerHTML = '<p class="rail-help">Press a combination such as Control + Shift + A first.</p>'; return; }
    state[key] = pending; dialog.close(); render(); changed();
  });
  const handler = event => {
    if (event.key === 'Escape' || event.key === 'Tab') return;
    if (!event.ctrlKey && !event.metaKey && !event.altKey) return;
    if (['Control', 'Meta', 'Shift', 'Alt'].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    pending = [...(event.ctrlKey ? ['⌃'] : []), ...(event.altKey ? ['⌥'] : []), ...(event.shiftKey ? ['⇧'] : []), ...(event.metaKey ? ['⌘'] : []), event.key.toUpperCase()];
    document.querySelector('#shortcut-capture').innerHTML = keycaps(pending);
  };
  const dialog = document.querySelector('#detail-dialog');
  dialog.addEventListener('keydown', handler);
  dialog.addEventListener('close', () => dialog.removeEventListener('keydown', handler), { once: true });
}
function audioTest(kind) {
  const meter = document.getElementById(`meter-${kind}`);
  const label = document.getElementById(`meter-label-${kind}`);
  if (meter.classList.contains('testing')) return;
  meter.classList.add('testing'); label.textContent = 'Simulated signal';
  toast('Simulated sound check · no audio is captured or played.');
  setTimeout(() => { if (meter.isConnected) { meter.classList.remove('testing'); label.textContent = 'Preview complete'; } }, 2800);
}
const downloadTimers = new Map();
function downloadModel(id) {
  if (state.downloading[id] !== undefined) return;
  state.downloading[id] = 0;
  render();
  const timer = setInterval(() => {
    state.downloading[id] += 10;
    if (state.downloading[id] >= 100) {
      clearInterval(timer); downloadTimers.delete(id); delete state.downloading[id]; state.downloaded.push(id);
      if (currentPage === 'models') render();
      changed(); toast('Simulated download complete. No files were downloaded.');
    } else {
      const control = document.getElementById(`model-action-${id}`);
      if (control) control.innerHTML = modelAction(id);
    }
  }, 250);
  downloadTimers.set(id, timer);
}
function addIntegration() {
  const type = state.integrationTab;
  const titles = { mcp: ['Add an MCP server', 'Server URL', 'https://example.com/mcp'], cli: ['Add a CLI tool', 'Command', 'gh'], skills: ['Add a skill source', 'Repository URL or local path', '/path/to/skills'] };
  const [title, endpointLabel, placeholder] = titles[type];
  detail(title, 'Create a sample configuration. Nothing connects or executes.', `<div class="field"><label for="integration-name">Name</label><input class="input" id="integration-name" name="name" placeholder="A recognizable name" maxlength="60" required></div><div class="field"><label for="integration-endpoint">${endpointLabel}</label><input class="input" id="integration-endpoint" name="endpoint" placeholder="${placeholder}" maxlength="200" required></div>`, 'Add to preview', (data, dialog) => {
    const name = data.get('name').trim(), endpoint = data.get('endpoint').trim();
    if (!name || !endpoint) return;
    state.integrations.push({ id: Date.now(), type, name, endpoint });
    dialog.close(); render(); changed();
  });
}
const actions = {
  'shortcut': el => recordShortcut(el.dataset.key),
  'audio-test': el => audioTest(el.dataset.kind),
  'manage-provider': el => manageProvider(el.dataset.provider),
  'download-model': el => downloadModel(el.dataset.model),
  'cancel-download': el => { const id = el.dataset.model; clearInterval(downloadTimers.get(id)); downloadTimers.delete(id); delete state.downloading[id]; render(); toast('Simulated download canceled.'); },
  'add-integration': addIntegration,
  'remove-integration': el => { state.integrations = state.integrations.filter(i => String(i.id) !== el.dataset.id); render(); changed(); },
  'install-component': el => {
    const key = el.dataset.component;
    detail('Preview component installation', 'In the native app, this flow depends on how RoomKit was installed.', notice('This action only marks the sample component as installed. No package manager runs and no files change.'), 'Simulate completion', (_data, dialog) => { state[key] = true; dialog.close(); render(); changed(); toast('Component installed in the preview only.'); });
  },
  'wakeword-setup': () => detail('Set up a wake phrase', 'The native flow records a few examples of your voice.', `<div class="card padded-card"><p class="eyebrow">EXAMPLE PHRASE</p><p style="font-size:24px;margin:0">“Hey RoomKit”</p><p class="row-description">No microphone is used here. Continue to preview an enrolled phrase.</p></div>`, 'Use demo phrase', (_data, dialog) => { state.wakewordEnrolled = true; dialog.close(); render(); changed(); }),
  'enroll-speaker': () => detail('Name a voice', 'A real enrollment would capture several spoken examples.', '<div class="field"><label for="speaker-name">Name</label><input class="input" id="speaker-name" name="name" placeholder="Your name" maxlength="50" required></div>', 'Create demo profile', (data, dialog) => { const name = data.get('name').trim(); if (!name) return; state.speakerNames.push(name); dialog.close(); render(); changed(); }),
  'local-provider': () => detail('Local server', 'Connect RoomKit to an OpenAI-compatible endpoint.', `<div class="field"><label for="local-url">Base URL</label><input class="input" id="local-url" name="url" type="url" value="${escapeHTML(state.localURL || 'http://localhost:11434/v1')}" required></div><p class="rail-help">This preview saves the example address in memory. It does not contact the server.</p>`, 'Save in preview', (data, dialog) => { state.localURL = data.get('url'); dialog.close(); changed(); toast('Example address saved. No connection was attempted.'); }),
};
document.addEventListener('click', event => {
  const el = event.target.closest('button, a');
  if (!el) return;
  if (el.dataset.closeDialog) { document.getElementById(el.dataset.closeDialog).close(); return; }
  if (el.dataset.page) { navigate(el.dataset.page, el.dataset.target); return; }
  if (el.dataset.themeChoice) {
    state.theme = el.dataset.themeChoice; render(); changed('Appearance updated in preview');
    document.querySelector(`[data-theme-choice="${state.theme}"]`).focus({ preventScroll: true }); return;
  }
  if (el.dataset.toggle) {
    const key = el.dataset.toggle; state[key] = !state[key]; render(); changed();
    document.querySelector(`[data-toggle="${key}"]`)?.focus({ preventScroll: true }); return;
  }
  if (el.dataset.tab) {
    const { tab, value } = el.dataset; state[tab] = value; render();
    document.querySelector(`[data-tab="${tab}"][data-value="${value}"]`)?.focus({ preventScroll: true }); return;
  }
  if (el.dataset.mode) { state.mode = el.dataset.mode; render(); changed('Saved · next session in app'); document.querySelector(`[data-mode="${state.mode}"]`).focus({ preventScroll: true }); return; }
  if (el.dataset.personality) { state.personality = el.dataset.personality; render(); changed(); document.querySelector(`[data-personality="${state.personality}"]`).focus({ preventScroll: true }); return; }
  if (el.dataset.action && actions[el.dataset.action]) actions[el.dataset.action](el);
});
const rerenderSettings = new Set(['realtimeProvider', 'dictationProvider', 'vcSTT', 'vcLLM', 'vcTTS', 'telemetry', 'speaking', 'inputDevice']);
document.addEventListener('change', event => {
  const el = event.target;
  if (el.dataset.setting) {
    if (!el.checkValidity()) { el.reportValidity(); return; }
    state[el.dataset.setting] = el.value;
    if (el.dataset.setting === 'speaking' && el.value === 'Always respond') state.thinker = false;
    changed();
    if (rerenderSettings.has(el.dataset.setting)) { const key = el.dataset.setting; render(); document.querySelector(`[data-setting="${key}"]`)?.focus({ preventScroll: true }); }
  }
  if (el.dataset.notify) changed(el.dataset.notify);
});
// Commit editable text to the in-memory model while typing, including before navigation.
document.addEventListener('input', event => {
  const el = event.target;
  if (el.dataset.setting && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') && el.checkValidity()) { state[el.dataset.setting] = el.value; changed(); }
});
const searchEntries = [
  ['Appearance', 'general', 'appearance', 'theme light dark display thème apparence'],
  ['Assistant keyboard shortcut', 'general', 'shortcuts', 'hotkey keys raccourci clavier'],
  ['Conversation mode', 'conversation', 'conversation-mode', 'realtime speech voice channel STT LLM TTS'],
  ['Personality & instructions', 'conversation', 'personality', 'attitudes system prompt tone personnalité'],
  ['Microphone & speakers', 'audio', 'audio-devices', 'input output sound périphérique micro casque'],
  ['Echo cancellation & noise reduction', 'audio', 'sound-quality', 'AEC WebRTC Speex denoise RNNoise GTCRN bruit écho'],
  ['Speaker recognition', 'audio', 'speaker-profiles', 'diarization enrollment voice profiles locuteur'],
  ['Dictation shortcut', 'dictation', 'dictation-shortcut', 'hotkey speech paste dictée'],
  ['Transcription language', 'dictation', 'transcription', 'STT Whisper translate français langue'],
  ['Wake word', 'dictation', 'wakeword', 'phrase trigger activation mot réveil'],
  ['Automatic session end', 'dictation', 'session-timeout', 'idle hangup silence délai'],
  ['Provider API keys', 'providers', 'provider-keys', 'Gemini OpenAI Anthropic Deepgram credentials clé connexion'],
  ['Download local models', 'models', 'model-library', 'Whisper Parakeet Piper VAD modèle télécharger'],
  ['Install components', 'models', 'components', 'packages dependencies backend installation composant'],
  ['Tools & skills', 'integrations', 'integrations-list', 'MCP CLI servers integrations serveurs outils compétences'],
  ['Conversation memory', 'privacy', 'memory', 'history local SQLite souvenir mémoire confidentialité'],
  ['Session recording', 'privacy', 'recording', 'audio files enregistrer enregistrement'],
  ['Audio debug captures', 'diagnostics', 'audio-debug', 'pipeline logs troubleshooting diagnostic'],
  ['Telemetry & traces', 'diagnostics', 'telemetry', 'OTLP OpenTelemetry endpoint traces télémétrie'],
];
let filteredEntries = [];
function normalized(text) { return text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
function search(query = '') {
  filteredEntries = searchEntries.filter(entry => normalized(entry.join(' ')).includes(normalized(query.trim())));
  searchIndex = 0;
  document.querySelector('#search-results').innerHTML = filteredEntries.length ? filteredEntries.map(([title, page, target], i) => `<button class="search-result${i === 0 ? ' active' : ''}" data-search-result="${i}">${icon(sections.find(s => s.id === page).icon)}<span><strong>${title}</strong><small>${sections.find(s => s.id === page).label}</small></span><span aria-hidden="true">↵</span></button>`).join('') : '<div class="empty-state"><h3>No settings found</h3><p>Try “audio”, “keys”, “memory”, or “shortcut”.</p></div>';
}
function openSearch() {
  const dialog = document.querySelector('#search-dialog');
  if (document.querySelector('#detail-dialog').open || dialog.open) return;
  document.querySelector('#setting-search').value = ''; search(); dialog.showModal(); document.querySelector('#setting-search').focus();
}
function selectSearchResult(index) {
  const entry = filteredEntries[index];
  if (entry) { document.querySelector('#search-dialog').close(); navigate(entry[1], entry[2]); }
}
document.querySelector('#search-trigger').addEventListener('click', openSearch);
document.querySelector('#setting-search').addEventListener('input', event => search(event.target.value));
document.querySelector('#search-results').addEventListener('click', event => { const result = event.target.closest('[data-search-result]'); if (result) selectSearchResult(Number(result.dataset.searchResult)); });
document.querySelector('#search-dialog').addEventListener('keydown', event => {
  if (event.key === 'Enter' && event.target.id === 'setting-search') { event.preventDefault(); selectSearchResult(searchIndex); }
  if (['ArrowDown', 'ArrowUp'].includes(event.key) && filteredEntries.length) {
    event.preventDefault();
    searchIndex = (searchIndex + (event.key === 'ArrowDown' ? 1 : -1) + filteredEntries.length) % filteredEntries.length;
    document.querySelectorAll('.search-result').forEach((el, i) => el.classList.toggle('active', i === searchIndex));
    document.querySelectorAll('.search-result')[searchIndex].scrollIntoView({ block: 'nearest' });
    document.querySelector('#setting-search').focus();
  }
});
document.addEventListener('keydown', event => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !document.querySelector('#detail-dialog').open) { event.preventDefault(); openSearch(); } });
document.querySelector('#menu-toggle').addEventListener('click', event => { const open = document.body.classList.toggle('menu-open'); event.currentTarget.setAttribute('aria-expanded', open); });
window.addEventListener('hashchange', () => navigate(location.hash.slice(1) || 'general'));
let previousGroup = '';
document.querySelector('#navigation').innerHTML = sections.filter(s => s.id !== 'about').map(s => {
  let heading = '';
  if (s.group !== previousGroup) { heading = `${previousGroup ? '</div>' : ''}<div class="nav-group"><p class="nav-group-label">${s.group}</p>`; previousGroup = s.group; }
  return `${heading}<button class="nav-item" data-page="${s.id}">${icon(s.icon)}${s.label}</button>`;
}).join('') + '</div>';
document.querySelector('#search-trigger kbd').textContent = /Mac/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';
navigate(renderers[location.hash.slice(1)] ? location.hash.slice(1) : 'general', '', false);
