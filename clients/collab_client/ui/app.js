'use strict';
const $ = id => document.getElementById(id);
const editor = $('editor');
window.hasUnsavedChanges = () => dirty || !!saving;
let api, current = null, base = '', revision = 0, dirty = false, saving = null;
let timer, polling = false, aiBusy = false, activePanel = '', composition = false, recovering = null;
let selection = [0, 0], polls = 0;
const title = id => id.split(/[-_]/).map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
const node = (tag, cls, text) => { const e = document.createElement(tag); e.className = cls; if (text !== undefined) e.textContent = text; return e; };

async function call(method, ...args) {
  const reply = await api[method](...args);
  if (!reply.ok) {
    if (reply.expired) expire();
    throw new Error(reply.error || 'The request could not be completed.');
  }
  return reply.data;
}
function notice(text = '') { $('message').textContent = text; $('message').classList.toggle('hidden', !text); }
function saveStatus(text, kind = '') { $('save-status').textContent = text; $('save-status').className = `save-status ${kind}`; }
function countWords() { const text = editor.value.trim(); $('word-count').textContent = `${text ? text.split(/\s+/u).length : 0} words`; }
function expire() {
  if (current?.document && dirty) recovering = {username: current.username, id: current.document.id, base, revision, text: editor.value};
  current = null; $('workspace').classList.add('hidden'); $('login').classList.remove('hidden');
  $('login-error').textContent = 'Your session ended. Sign in again to continue.';
  $('password').value = ''; clearTimeout(timer);
}
function renderDocuments() {
  const list = $('document-list'); list.replaceChildren();
  const query = $('search').value.toLowerCase();
  const items = (current?.documents || []).filter(doc => title(doc.id).toLowerCase().includes(query));
  for (const doc of items) {
    const button = node('button', `document-item ${doc.id === current.document?.id ? 'active' : ''}`);
    button.append(node('span', 'document-icon', '▤'), node('span', 'doc-label', title(doc.id)));
    button.title = title(doc.id); button.onclick = () => openDocument(doc.id); list.append(button);
  }
  if (!items.length) list.append(node('p', 'doc-list-empty', query ? 'No matching documents.' : 'Your shared documents will appear here. Create one to begin.'));
}
function applyState(state) {
  current = state;
  $('user-name').textContent = state.username; $('user-avatar').textContent = state.username.slice(0, 1);
  $('server-name').textContent = state.gateway; $('server-name').title = state.gateway;
  const doc = state.document;
  $('empty-state').classList.toggle('hidden', !!doc); $('document-area').classList.toggle('hidden', !doc);
  $('history-button').disabled = !doc; $('assist-button').disabled = !doc;
  if (doc) {
    $('document-title').textContent = title(doc.id); $('breadcrumb-title').textContent = title(doc.id);
    $('revision-label').textContent = `Version ${doc.revision}`;
    if (!dirty && !saving) {
      if (editor.value !== doc.text) {
        const old = editor.value, caret = editor.selectionStart;
        editor.value = doc.text;
        // Preserve the cursor relative to text before it for common remote insertions.
        let prefix = 0;
        while (prefix < old.length && prefix < doc.text.length && old[prefix] === doc.text[prefix]) prefix++;
        const position = caret > prefix ? Math.max(prefix, caret + doc.text.length - old.length) : caret;
        editor.setSelectionRange(Math.min(position, doc.text.length), Math.min(position, doc.text.length));
      }
      base = doc.text; revision = doc.revision;
      saveStatus(doc.connected ? 'All changes saved' : 'Connection interrupted', doc.connected ? '' : 'failed');
    }
    $('participants').replaceChildren();
    const participants = new Map();
    for (const person of doc.participants) participants.set(person.name, person);
    for (const person of participants.values()) {
      const avatar = node('span', 'participant', person.name.slice(0, 1).toUpperCase());
      avatar.style.setProperty('--color', /^#[a-f0-9]{6}$/i.test(person.color) ? person.color : '#67815e');
      avatar.title = `${person.name}${person.name === state.username ? ' (you)' : ''}${person.editing ? ' · editing' : ''}`;
      $('participants').append(avatar);
    }
    const others = [...participants.values()].filter(p => p.name !== state.username);
    $('editing-status').textContent = others.length ? `${others.map(p => title(p.name)).join(', ')} ${others.length === 1 ? 'is' : 'are'} here` : 'Only you are here';
    countWords();
  } else { $('breadcrumb-title').textContent = 'Documents'; $('participants').replaceChildren(); }
  renderDocuments();
}

async function flush() {
  clearTimeout(timer);
  if (saving) { await saving; if (dirty) return flush(); return; }
  if (!dirty || !current?.document || composition) return;
  const docId = current.document.id, sent = editor.value, oldBase = base, oldRevision = revision;
  saveStatus('Saving changes…', 'saving');
  saving = (async () => {
    try {
      const state = await call('save', docId, oldBase, sent, oldRevision);
      const canonical = state.document.text;
      if (editor.value !== sent) {
        // Rebase keystrokes typed during this save over the committed result.
        let draft, merged;
        do {
          draft = editor.value;
          merged = await call('merge', sent, draft, canonical, editor.selectionStart);
        } while (editor.value !== draft);
        editor.value = merged.text; editor.setSelectionRange(merged.caret, merged.caret);
      } else editor.value = canonical;
      base = canonical; revision = state.document.revision; dirty = editor.value !== canonical;
      applyState(state); notice(); saveStatus(dirty ? 'Unsaved changes' : 'All changes saved', dirty ? 'saving' : '');
    } catch (error) {
      dirty = true; saveStatus('Save failed · click to retry', 'failed');
      notice(`${error.message} Your unsaved text is still in the editor. Click the save status to retry.`);
      throw error;
    } finally { saving = null; }
  })();
  await saving;
  if (dirty) return flush();
}
async function openDocument(id) {
  try {
    await flush();
    const state = await call('open', id);
    dirty = false; editor.value = ''; base = ''; revision = 0;
    applyState(state); notice();
    if (activePanel === 'history') await loadHistory();
    if (activePanel === 'assist') resetAI();
    editor.focus();
  } catch (error) { notice(error.message); }
}
function resetAI() { $('ai-result').replaceChildren(node('p', 'subtle', 'Choose a tool to get started.')); }
function panel(which) {
  if (activePanel === which) which = '';
  activePanel = which; $('drawer').classList.toggle('hidden', !which);
  for (const name of ['assist', 'history', 'system']) $(`${name}-panel`).classList.toggle('hidden', name !== which);
  $('drawer-title').textContent = {assist: 'Writing assistant', history: 'Version history', system: 'System status'}[which] || '';
  if (which === 'history') loadHistory();
  if (which === 'assist') call('cluster').then(s => $('assistant-mode').textContent = s.ai_mode).catch(() => {});
  if (which === 'system') loadSystem();
}
async function loadHistory() {
  $('history-list').replaceChildren(node('p', 'subtle', 'Loading history…'));
  try {
    await flush(); const history = await call('history'); $('history-list').replaceChildren();
    for (const edit of history) {
      const item = node('article', 'history-item');
      item.append(node('h3', '', `Version ${edit.revision}`), node('p', '', `Saved by ${title(edit.author || 'a teammate')}`));
      if (!edit.changes.length) item.append(node('p', 'change-text', 'Created document'));
      for (const change of edit.changes) {
        const action = change.start === change.end ? 'Added text' : change.text ? 'Replaced text' : 'Removed text';
        item.append(node('p', '', action));
        if (change.text) item.append(node('p', 'change-text', change.text));
      }
      $('history-list').append(item);
    }
    if (!history.length) $('history-list').append(node('p', 'subtle', 'No saved changes yet.'));
  } catch (error) { $('history-list').replaceChildren(node('p', 'error', error.message)); }
}
async function loadSystem() {
  try {
    const status = await call('cluster'), nodes = status.nodes, live = nodes.filter(n => n.role !== 'unreachable');
    $('assistant-mode').textContent = status.ai_mode;
    $('cluster-summary').replaceChildren(node('p', 'cluster-good', live.length >= 2 ? `${live.length} of 3 replicas reachable from the gateway.` : 'Fewer than two replicas are reachable. Saves may wait for recovery.'));
    $('node-list').replaceChildren();
    nodes.forEach((n, i) => {
      const item = node('article', 'node'), header = node('div', 'node-top');
      header.append(node('h3', '', `Replica ${i + 1}`), node('span', `role ${n.role}`, n.role));
      item.append(header, node('span', 'node-address', n.node));
      if (n.role !== 'unreachable') {
        const dl = node('dl', '');
        for (const [label, value] of [['Election term', n.term], ['Committed entries', n.commit_index], ['Applied entries', n.applied_index], ['Document version', n.revision]]) dl.append(node('dt', '', label), node('dd', '', String(value)));
        item.append(dl);
      }
      $('node-list').append(item);
    });
  } catch (error) { $('cluster-summary').replaceChildren(node('p', 'error', error.message)); }
}
async function assist(task) {
  if (aiBusy) return;
  const range = [...selection];
  try {
    await flush(); aiBusy = true;
    document.querySelectorAll('[data-task], #question-form button').forEach(b => b.disabled = true);
    $('ai-result').replaceChildren(node('p', 'ai-loading', 'Reading your document… The local model may take a moment.'));
    const result = await call('assist', task, range[0], range[1], $('question').value, $('rewrite-mode').value);
    if (result.doc_id !== current?.document?.id) return;
    $('ai-result').replaceChildren();
    if (result.suggestions) {
      if (!result.suggestions.length) $('ai-result').append(node('p', 'subtle', 'No changes suggested for this passage.'));
      for (const s of result.suggestions) {
        const item = node('article', 'suggestion');
        if (s.original) item.append(node('del', '', s.original));
        item.append(node('ins', '', s.replacement), node('small', '', s.reason));
        const apply = node('button', 'quiet-button', 'Apply suggestion');
        apply.onclick = async () => {
          try { await flush(); const state = await call('accept', s.index); dirty = false; applyState(state); resetAI(); notice('Suggestion applied and saved.'); }
          catch (error) { notice(error.message); }
        };
        item.append(apply); $('ai-result').append(item);
      }
    } else {
      $('ai-result').append(node('h3', '', task === 'summary' ? 'Document summary' : 'Answer'), node('p', '', result.text), node('small', 'subtle', `Based on version ${result.revision}`));
    }
  } catch (error) { $('ai-result').replaceChildren(node('p', 'error', error.message)); }
  finally { aiBusy = false; document.querySelectorAll('[data-task], #question-form button').forEach(b => b.disabled = false); }
}

$('login-form').onsubmit = async event => {
  event.preventDefault(); $('signin').disabled = true; $('login-error').textContent = '';
  try {
    await call('configure', $('server').value.trim(), $('tls').checked);
    const state = await call('login', $('username').value, $('password').value);
    $('password').value = ''; dirty = false; saving = null; editor.value = ''; applyState(state);
    $('login').classList.add('hidden'); $('workspace').classList.remove('hidden');
    if (recovering && recovering.username === state.username) {
      const draft = recovering; recovering = null;
      await openDocument(draft.id); base = draft.base; revision = draft.revision; editor.value = draft.text; dirty = true;
      notice('Your unsaved text was kept in this window. It will be merged with the current document.'); await flush();
    }
  } catch (error) { $('login-error').textContent = error.message; }
  finally { $('signin').disabled = false; }
};
$('show-password').onclick = () => { const show = $('password').type === 'password'; $('password').type = show ? 'text' : 'password'; $('show-password').textContent = show ? 'Hide' : 'Show'; };
document.querySelectorAll('[data-demo]').forEach(button => button.onclick = () => { $('username').value = button.dataset.demo; $('password').value = `${button.dataset.demo}123`; });
$('logout').onclick = async () => {
  try { await flush(); await call('logout'); dirty = false; current = null; editor.value = ''; $('workspace').classList.add('hidden'); $('login').classList.remove('hidden'); $('password').value = ''; panel(''); notice(); }
  catch (error) { $('leave-dialog').showModal(); notice(error.message); }
};
$('stay').onclick = () => $('leave-dialog').close();
function newDocument() { $('document-name').value = ''; $('create-error').textContent = ''; $('create-dialog').showModal(); $('document-name').focus(); }
$('new-document').onclick = newDocument; $('empty-create').onclick = newDocument;
$('cancel-create').onclick = () => $('create-dialog').close();
$('create-form').onsubmit = async event => {
  event.preventDefault(); $('create-submit').disabled = true;
  try { await flush(); const state = await call('create', $('document-name').value); dirty = false; editor.value = ''; applyState(state); $('create-dialog').close(); notice(); editor.focus(); }
  catch (error) { $('create-error').textContent = error.message; }
  finally { $('create-submit').disabled = false; }
};
$('refresh-docs').onclick = async () => { try { applyState(await call('documents')); } catch (error) { notice(error.message); } };
$('search').oninput = renderDocuments;
$('assist-button').onclick = () => panel('assist'); $('history-button').onclick = () => panel('history'); $('system-button').onclick = () => panel('system'); $('close-drawer').onclick = () => panel(''); $('refresh-system').onclick = loadSystem;
document.querySelectorAll('[data-task]').forEach(button => button.onclick = () => assist(button.dataset.task));
$('question-form').onsubmit = event => { event.preventDefault(); assist('ask'); };
editor.addEventListener('input', () => { dirty = true; saveStatus('Unsaved changes', 'saving'); countWords(); clearTimeout(timer); timer = setTimeout(() => flush().catch(() => {}), 500); });
editor.addEventListener('compositionstart', () => composition = true);
editor.addEventListener('compositionend', () => { composition = false; flush().catch(() => {}); });
editor.addEventListener('select', () => { selection = [editor.selectionStart, editor.selectionEnd]; });
editor.addEventListener('keyup', () => { selection = [editor.selectionStart, editor.selectionEnd]; });
editor.addEventListener('click', () => { selection = [editor.selectionStart, editor.selectionEnd]; if (current?.document) call('cursor', ...selection).catch(() => {}); });
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); flush().catch(() => {}); } });
$('save-status').onclick = () => flush().catch(() => {});
window.addEventListener('beforeunload', event => { if (dirty || saving) { event.preventDefault(); event.returnValue = ''; } });
async function ready() {
  api = window.pywebview.api;
  const settings = await call('settings'); $('server').value = settings.gateway; $('tls').checked = settings.tls;
  setInterval(async () => {
    if (!current || polling) return;
    polling = true;
    try { applyState(await call('poll')); if (++polls % 15 === 0) applyState(await call('documents')); if (activePanel === 'system' && polls % 4 === 0) await loadSystem(); }
    catch (error) { notice(error.message); }
    finally { polling = false; }
  }, 900);
}
if (window.pywebview?.api) ready(); else window.addEventListener('pywebviewready', ready, {once: true});
