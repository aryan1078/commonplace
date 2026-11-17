// Offline regression checks against the actual UI controller. No browser/CDN,
// framework, installed Node packages or fake Raft implementation is involved.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.value = ''; this.textContent = ''; this.children = []; this.events = {};
    this.style = {setProperty() {}}; this.selectionStart = this.selectionEnd = 0;
    const classes = new Set();
    this.classList = {
      add: name => classes.add(name), remove: name => classes.delete(name),
      contains: name => classes.has(name),
      toggle(name, force) {
        const enabled = force === undefined ? !classes.has(name) : force;
        enabled ? classes.add(name) : classes.delete(name); return enabled;
      }
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute() {}
  focus() {}
  showModal() {}
  close() {}
}

const ok = data => ({ok:true, data});
const deferred = () => {
  let resolve;
  const promise = new Promise(done => resolve = done);
  return {promise, resolve};
};
const state = (id, revision, text, username = 'alice') => ({username, gateway:'demo',
  documents: id ? [{id, revision}] : [],
  document: id ? {id, revision, text, connected:true, participants:[]} : null});

async function fixture(overrides = {}) {
  const elements = new Map(); let poll;
  const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const api = {settings: async () => ok({gateway:'demo', tls:false}),
    configure: async () => ok({}), logout: async () => ok({}), ...overrides};
  const context = vm.createContext({
    document: {getElementById:element, createElement:() => new Element(),
      querySelectorAll:() => [], addEventListener() {}},
    window: {pywebview:{api}, addEventListener() {}},
    setInterval: callback => { poll = callback; }, setTimeout:() => 1, clearTimeout() {},
    console, input:null
  });
  const source = fs.readFileSync(path.join(__dirname, '../clients/collab_client/ui/app.js'), 'utf8');
  vm.runInContext(source, context);
  await vm.runInContext('ready()', context);
  return {context, element, poll:() => poll(), run:code => vm.runInContext(code, context),
    apply(value) { context.input = value; return vm.runInContext('applyState(input)', context); }};
}

async function run() {
  {
    const ui = await fixture();
    ui.apply(state('one', 5, 'latest committed text'));
    assert.equal(ui.apply(state('one', 4, 'delayed stale text')), false);
    assert.equal(ui.element('editor').value, 'latest committed text');
    assert.equal(ui.element('revision-label').textContent, 'Version 5');
  }
  {
    const pending = deferred();
    const ui = await fixture({poll:() => pending.promise, open:async () => ok(state('two', 1, 'document two'))});
    ui.apply(state('one', 4, 'document one'));
    const poll = ui.poll();
    const opening = ui.run("openDocument('two')");
    assert.equal(ui.element('editor').readOnly, true);
    await opening;
    pending.resolve(ok(state('one', 4, 'delayed document one'))); await poll;
    assert.equal(ui.run('current.document.id'), 'two');
    assert.equal(ui.element('editor').value, 'document two');
    assert.equal(ui.element('editor').readOnly, false);
  }
  {
    const pending = deferred();
    const ui = await fixture({poll:() => pending.promise,
      login:async () => ok(state(null, 0, '', 'bob'))});
    ui.apply(state('one', 1, 'alice document'));
    const poll = ui.poll();
    await ui.element('logout').onclick();
    ui.element('username').value = 'bob'; ui.element('password').value = 'demo';
    await ui.element('login-form').onsubmit({preventDefault() {}});
    pending.resolve({ok:false, expired:true, error:'old Alice session ended'}); await poll;
    assert.equal(ui.run('current.username'), 'bob');
    assert.equal(ui.element('workspace').classList.contains('hidden'), false);
  }
  {
    const pending = deferred();
    const ui = await fixture({save:() => pending.promise});
    ui.apply(state('one', 3, 'before'));
    ui.element('editor').value = 'our edit'; ui.element('editor').events.input();
    const save = ui.run('flush()');
    ui.apply(state('one', 5, 'our edit and a newer remote edit'));
    pending.resolve(ok(state('one', 4, 'our edit'))); await save;
    assert.equal(ui.element('editor').value, 'our edit and a newer remote edit');
    assert.equal(ui.run('revision'), 5);
    assert.equal(ui.run('base'), 'our edit and a newer remote edit');
  }
  {
    const pending = deferred();
    const ui = await fixture({assist:async () => ok({doc_id:'one', suggestions:[
      {index:0, original:'We has', replacement:'We have', reason:'Agreement'}]}), accept:() => pending.promise});
    ui.apply(state('one', 1, 'We has notes'));
    await ui.run("assist('grammar')");
    const applying = ui.element('ai-result').children[0].children.at(-1).onclick();
    assert.equal(ui.element('editor').readOnly, true);
    pending.resolve(ok(state('one', 2, 'We have notes'))); await applying;
    assert.equal(ui.element('editor').value, 'We have notes');
    assert.equal(ui.element('editor').readOnly, false);
  }
  console.log('5 editor response-ordering regressions passed.');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
