const app = document.querySelector('#app');
const KEY = 'paprika-voice-continuity-v1';
let data, state, context, active = null, epoch = 0;
const buffers = new Map();
const element = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const persist = () => localStorage.setItem(KEY, JSON.stringify(state));
function button(text, handler, cls = '') {
  const node = element('button', text, cls); node.onclick = handler; return node;
}
function showError(text) {
  let node = document.querySelector('#error');
  if (!node) { node = element('p', '', 'error'); node.id = 'error'; app.append(node); }
  node.textContent = text;
}
function stop(message = 'Stopped. Choose A or B to listen again.') {
  epoch++;
  const old = active; active = null;
  if (old) { old.source.onended = null; try { old.source.stop(); } catch {} }
  const status = document.querySelector('#status');
  if (status) { status.textContent = message; status.className = 'status'; }
}
async function prepare() {
  context ??= new AudioContext(); await context.resume();
  for (const example of data.examples) for (const variant of example.variants) {
    const key = example.id + ':' + variant.id;
    if (buffers.has(key)) continue;
    const response = await fetch(`/audio/${example.id}-${variant.id}.wav`);
    if (!response.ok) throw Error('Audio could not load. Check the external drive is connected.');
    buffers.set(key, await context.decodeAudioData(await response.arrayBuffer()));
  }
}
function nextAction() {
  for (const example of data.examples) {
    for (const variant of example.variants) {
      if (!state.completed.includes(example.id + ':' + variant.id)) return `Next: listen to ${variant.id.toUpperCase()} for “${example.title}”.`;
    }
    const review = state.reviews[example.id];
    if (!review.rating && !review.notes.trim()) return `Next: choose a response or write a note for “${example.title}”.`;
  }
  return 'Your review is complete. Save your feedback below to finish.';
}
function canSave() {
  return data.examples.every(e => e.variants.every(v => state.completed.includes(e.id + ':' + v.id))
    && (state.reviews[e.id].rating || state.reviews[e.id].notes.trim()));
}
function refreshGuidance() {
  document.querySelector('#save').disabled = !canSave();
  if (!active) document.querySelector('#status').textContent = nextAction();
}
async function play(example, variant) {
  stop(); const ticket = epoch;
  try {
    document.querySelector('#status').textContent = 'Getting the audio ready…';
    await prepare(); if (ticket !== epoch) return;
    const key = example.id + ':' + variant.id;
    const source = context.createBufferSource(), gain = context.createGain();
    source.buffer = buffers.get(key); gain.gain.value = state.volume / 100;
    source.connect(gain).connect(context.destination); active = { source, gain };
    const status = document.querySelector('#status'); status.className = 'status speaking';
    status.textContent = `Playing ${variant.id.toUpperCase()} · ${example.title}. Listen for pauses, clipped words or changes in volume.`;
    source.onended = () => {
      if (active?.source !== source) return;
      active = null; state.completed = [...new Set([...state.completed, key])]; persist(); comparison();
    };
    source.start();
  } catch (error) {
    if (ticket !== epoch) return;
    stop('Playback did not start.'); showError(error.message + ' Press A or B to try again.');
  }
}
function intro() {
  app.replaceChildren(element('p', 'Paprika · a short listening check', 'muted'),
    element('h1', 'Does K still sound smooth?'),
    element('p', data.focus || 'We are trying a way to start replies sooner while keeping K. Hear two versions of the same words and listen for awkward pauses, clipped words or jumps in volume.', 'muted'),
    element('div', `This is not a voice-choice or transcription test. A and B both use K. ${data.examples.length === 1 ? 'There is one reply' : `There are ${data.examples.length} replies`}, and you can switch back and forth as often as you like.`, 'card'),
    element('p', 'Turn your sound on at a comfortable level. These are local, pre-recorded examples—not a live speed test. No microphone, recording, cloud request or extra spending.', 'muted'),
    button('Start listening check', async () => {
      try { await prepare(); state.started = true; persist(); comparison(); }
      catch (error) { showError(error.message + ' Press Start to retry.'); }
    }));
}
function comparison() {
  app.replaceChildren(element('h1', 'Same voice. Same words.'),
    element('p', 'Listen to A and B for each reply. Judge how smoothly the speech flows; you can also write anything you notice.', 'muted'));
  const status = element('div', nextAction(), 'status'); status.id = 'status'; status.setAttribute('aria-live', 'polite'); app.append(status);
  const row = element('div', undefined, 'row'), volume = element('input'), out = element('output', state.volume + '%');
  volume.type = 'range'; volume.min = 0; volume.max = 100; volume.value = state.volume; volume.setAttribute('aria-label', 'Playback volume');
  volume.oninput = () => { state.volume = +volume.value; out.textContent = state.volume + '%'; if (active) active.gain.gain.value = state.volume / 100; persist(); };
  row.append(element('span', 'Playback volume'), volume, out, button('Stop playback', () => stop(), 'secondary')); app.append(row);
  for (const example of data.examples) {
    const card = element('section', undefined, 'card'); card.setAttribute('aria-label', example.title);
    card.append(element('h2', example.title), element('p', example.question, 'question'));
    for (const variant of example.variants) {
      const done = state.completed.includes(example.id + ':' + variant.id);
      card.append(button(`${done ? '✓ ' : ''}Play ${variant.id.toUpperCase()}`, () => play(example, variant), variant.id === 'b' ? 'secondary' : ''));
    }
    const details = element('details'); details.append(element('summary', 'Read the reply'), element('p', example.text)); card.append(details);
    const group = element('fieldset'); group.append(element('legend', 'How did these sound?'));
    const enabled = example.variants.every(v => state.completed.includes(example.id + ':' + v.id));
    for (const [value, title] of [['both_good', 'Both sound smooth enough'], ['a_smoother', 'A sounds smoother'], ['b_smoother', 'B sounds smoother'], ['neither', 'Both need work']]) {
      const label = element('label'), input = element('input'); input.type = 'radio'; input.name = example.id; input.value = value;
      input.checked = state.reviews[example.id].rating === value; input.disabled = !enabled;
      input.onchange = () => { state.reviews[example.id].rating = value; state.saved = false; persist(); refreshGuidance(); };
      label.append(input, document.createTextNode(title)); group.append(label);
    }
    card.append(group);
    if (!enabled) card.append(element('p', 'Listen to both versions to unlock the choices.', 'muted'));
    const label = element('label', 'Your own words (instead of, or alongside, a choice)'), notes = element('textarea');
    notes.id = example.id + '-notes'; label.htmlFor = notes.id; notes.value = state.reviews[example.id].notes; notes.maxLength = 4000;
    notes.oninput = () => { state.reviews[example.id].notes = notes.value; state.saved = false; persist(); refreshGuidance(); };
    card.append(label, notes); app.append(card);
  }
  const saveButton = button('Save feedback + finish', save); saveButton.id = 'save'; saveButton.disabled = !canSave();
  app.append(saveButton, element('p', 'Feedback saves directly on this Mac’s external drive. No download or extra step.', 'muted'));
}
async function save() {
  stop();
  try {
    const response = await fetch('/save', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Review-Token': data.token },
      body: JSON.stringify({ id: state.id, manifest_sha256: data.manifest_sha256, completed: state.completed, reviews: state.reviews }) });
    const value = await response.json(); if (!response.ok) throw Error(value.error || 'Saving did not work.');
    state.saved = true; persist(); done();
  } catch (error) { showError(error.message + ' Your answers are still here. Press Save again.'); }
}
function done() {
  app.replaceChildren(element('h1', 'Your feedback is saved.'), element('p', 'You can close this page. There is no download or extra save step.', 'muted'),
    element('p', 'This checks how K’s speech flows. It does not change the robot’s voice or approve the complete conversation system.', 'muted'),
    button('Listen again or change my feedback', () => { state.saved = false; persist(); comparison(); }, 'secondary'));
}
document.addEventListener('visibilitychange', () => { if (document.hidden && active) stop('Playback stopped when you left the page. Replay A or B when you are ready.'); });
try {
  const response = await fetch('/api/examples'); if (!response.ok) throw Error('The listening page is unavailable.'); data = await response.json();
  let previous; try { previous = JSON.parse(localStorage.getItem(KEY)); } catch {}
  state = previous?.manifest_sha256 === data.manifest_sha256 ? previous : {
    id: crypto.randomUUID(), manifest_sha256: data.manifest_sha256, volume: 50, completed: [],
    reviews: Object.fromEntries(data.examples.map(e => [e.id, { rating: null, notes: '' }])), started: false, saved: false };
  if (data.qa) document.title = 'QA · K continuity';
  if (state.saved) done(); else if (state.started) comparison(); else intro();
} catch (error) {
  app.replaceChildren(element('h1', 'The listening check could not load.')); showError(error.message);
  app.append(button('Reload listening check', () => location.reload()));
}
