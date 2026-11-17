/* Binary gRPC-Web + the three string fields in browser.proto. No CDN required. */
(() => {
  if (document.documentElement.dataset.client !== 'browser') return;
  document.documentElement.classList.add('browser-client');
  const encoder = new TextEncoder(), decoder = new TextDecoder();
  let key = '', initializing = null, discovering = null, discovered = false;
  let pendingSave = null, username = '';
  let root = (window.COMMONPLACE_API || '').replace(/\/$/, '');
  const discovery = window.COMMONPLACE_DISCOVERY || '';
  const requestId = () => [...crypto.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
  async function discover() {
    if (!discovery) return;
    discovering ||= (async () => {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(`${discovery}&_=${Date.now()}`, {cache:'no-store', credentials:'omit', signal:controller.signal});
        if (!response.ok) return;
        const file = await response.json();
        const endpoint = JSON.parse(atob(file.content.replace(/\s/g, ''))).url;
        if (/^https:\/\/[a-z0-9-]+(?:\.app)?\.lhr\.(?:life|rocks)$/.test(endpoint)) root = endpoint;
      } catch (_) { /* The configured endpoint remains a usable fallback. */ }
      finally { clearTimeout(timer); }
    })().finally(() => discovering = null);
    await discovering;
  }
  async function request(body, signal) {
    for (let attempt = 0; ; attempt++) {
      try {
        const response = await fetch(`${root}/collab.v1.BrowserService/Call`, {
          method:'POST', headers:{'Content-Type':'application/grpc-web+proto','X-Grpc-Web':'1'},
          body, signal, credentials:'omit', cache:'no-store', referrerPolicy:'no-referrer'
        });
        if (response.ok || ![502,503,504].includes(response.status) || !discovery || attempt >= 2) return response;
      } catch (error) { if (!discovery || attempt >= 2 || signal.aborted) throw error; }
      await discover();
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  function varint(value) {
    const bytes = [];
    do { const b = value & 127; value = Math.floor(value / 128); bytes.push(b | (value ? 128 : 0)); } while (value);
    return bytes;
  }
  function encode(fields) {
    const parts = fields.map((value, index) => {
      const data = encoder.encode(value);
      return [new Uint8Array([((index + 1) << 3) | 2, ...varint(data.length)]), data];
    }).flat();
    const data = new Uint8Array(parts.reduce((sum, p) => sum + p.length, 0));
    let offset = 0; for (const p of parts) { data.set(p, offset); offset += p.length; }
    const framed = new Uint8Array(data.length + 5);
    new DataView(framed.buffer).setUint32(1, data.length);
    framed.set(data, 5); return framed;
  }
  function decode(data) {
    const fields = {}; let offset = 0;
    function readVarint() {
      let value = 0, shift = 0, b;
      do {
        if (offset >= data.length || shift > 28) throw Error('Invalid server response.');
        b = data[offset++]; value += (b & 127) * 2 ** shift; shift += 7;
      } while (b & 128);
      return value;
    }
    while (offset < data.length) {
      const tag = readVarint(), length = readVarint();
      if ((tag & 7) !== 2 || offset + length > data.length) throw Error('Invalid server response.');
      fields[tag >> 3] = decoder.decode(data.subarray(offset, offset + length)); offset += length;
    }
    return fields;
  }
  async function rpc(action, args, id = requestId()) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), action === 'assist' ? 210000 : 65000);
    try {
      const response = await request(encode([key, action, JSON.stringify(args), id]), controller.signal);
      if (!response.ok) throw Error(`The demo server returned ${response.status}. Try again shortly.`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      let offset = 0, message, status = response.headers.get('grpc-status');
      while (offset + 5 <= bytes.length) {
        const flag = bytes[offset], size = new DataView(bytes.buffer, bytes.byteOffset + offset + 1, 4).getUint32(0);
        offset += 5;
        if (offset + size > bytes.length) throw Error('Incomplete server response.');
        const frame = bytes.subarray(offset, offset + size);
        if (flag === 0) message = decode(frame);
        else if (flag === 128) status = /grpc-status:\s*(\d+)/i.exec(decoder.decode(frame))?.[1];
        else throw Error('Unsupported server response.');
        offset += size;
      }
      if (offset !== bytes.length || status !== '0' || !message) throw Error('The demo server could not complete this request.');
      key = message[1] || '';
      return JSON.parse(message[2]);
    } catch (error) {
      if (error instanceof TypeError || error.name === 'AbortError')
        throw Error('The demo server is offline or taking too long. Keep this tab open to preserve unsaved text, and try again when the host is online.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function invoke(action, ...args) {
    try {
      if (!discovered) { discovered = true; await discover(); }
      if (!key) {
        initializing ||= rpc('settings', []).finally(() => initializing = null);
        const settings = await initializing;
        if (!settings.ok || action === 'settings') return settings;
      }
      if (action === 'save' && pendingSave) {
        const previous = pendingSave;
        const acknowledged = await rpc('save', previous.args, previous.id);
        if (!acknowledged.ok) return acknowledged;
        pendingSave = null;
        if (JSON.stringify(args) === JSON.stringify(previous.args)) return acknowledged;
        if (args[0] !== previous.args[0]) throw Error('Retry the pending save before changing documents.');
        const canonical = acknowledged.data.document;
        const merged = await rpc('merge', [previous.args[2], args[2], canonical.text, args[2].length]);
        if (!merged.ok) return merged;
        args = [args[0], canonical.text, merged.data.text, canonical.revision];
      }
      const id = requestId();
      if (action === 'save') pendingSave = {args, id, username};
      const result = await rpc(action, args, id);
      if (action === 'save' && result.ok) pendingSave = null;
      if (action === 'login' && result.ok) {
        username = result.data.username;
        if (pendingSave && pendingSave.username !== username) pendingSave = null;
      }
      return result;
    } catch (error) { return {ok: false, error: error.message}; }
  }
  const methods = ['settings', 'configure', 'login', 'logout', 'poll', 'documents', 'open',
    'create', 'save', 'cursor', 'history', 'cluster', 'assist', 'accept', 'merge'];
  window.commonplaceBrowser = {api: Object.fromEntries(methods.map(name => [name, (...args) => invoke(name, ...args)]))};
  addEventListener('beforeunload', event => {
    if (window.hasUnsavedChanges?.()) { event.preventDefault(); event.returnValue = ''; }
  });
})();
