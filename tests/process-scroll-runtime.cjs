// Exercise the upstream process-body ResizeObserver / edge-class feedback in
// Chromium, rather than just asserting that a selector contains certain text.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const css = fs.readFileSync(0, 'utf8');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-process-scroll-'));
const browser = spawn(process.argv[2], [
  '--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
let sequence = 0;
const pending = new Map();
const timeout = setTimeout(() => { browser.kill(); process.exitCode = 1; }, 20000);
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function run(rule, expanded = false) {
  const result = await command('Runtime.evaluate', {
    awaitPromise: true, returnByValue: true,
    expression: `(${async function (rule, expanded) {
      document.documentElement.dataset.dshMacChrome = '';
      document.head.innerHTML = '<style>' + rule + `
        .process_body{max-height:200px;overflow-y:auto;scrollbar-gutter:stable}
        .process_content{display:flex;flex-direction:column}
        .process_content>*{flex-shrink:0}
        .process_fadeTop{mask-image:linear-gradient(#0000,#000 24px)}
        .process_fadeBottom{mask-image:linear-gradient(#000 0 calc(100% - 24px),#0000)}
      ` + '</style>';
      document.body.innerHTML = `
        <aside class="layout_sidebarCol"><div class="sessions_fade">fade</div></aside>
        <section data-step-process>
          <button aria-expanded="true">tools</button>
          <div class="process_body" data-step-process-body>
            <div class="process_content"><div style="height:100px">row</div>
              <div id="reasoning" style="height:24px">reasoning</div>
            </div>
          </div>
        </section>`;
      const body = document.querySelector('[data-step-process-body]');
      if (expanded) body.style.maxHeight = 'none';
      let changes = 0;
      let edges = '';
      // Equivalent to useProcessScroll's measurement and React class update.
      const observer = new ResizeObserver(() => {
        const floor = Math.max(0, body.scrollHeight - body.clientHeight);
        const next = expanded ? '' : [
          body.scrollTop > 1 ? 'process_fadeTop' : '',
          body.scrollTop < floor - 1 ? 'process_fadeBottom' : '',
        ].filter(Boolean).join(' ');
        if (next !== edges) { changes++; edges = next; body.className = 'process_body ' + next; }
      });
      observer.observe(body);
      observer.observe(body.firstElementChild);
      // Opening a long reasoning disclosure within the already-open group.
      document.querySelector('#reasoning').style.height = '1600px';
      const samples = [];
      for (let frame = 0; frame < 40; frame++) {
        await new Promise(requestAnimationFrame);
        samples.push(body.clientHeight);
      }
      const sidebarHidden = getComputedStyle(document.querySelector('.sessions_fade')).display === 'none';
      const report = { changes, samples, sidebarHidden };
      observer.disconnect();
      return report;
    }})(${JSON.stringify(rule)}, ${expanded})`,
  });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
(async () => {
  try {
    const endpoint = await new Promise((resolve, reject) => {
      let output = '';
      browser.stderr.on('data', chunk => {
        output += chunk;
        const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (match) resolve(match[1]);
      });
      browser.once('error', reject);
      browser.once('exit', code => reject(new Error(`Chromium exited: ${code}`)));
    });
    const tabs = await (await fetch(new URL('/json/list', endpoint.replace('ws:', 'http:')))).json();
    socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      const item = pending.get(data.id);
      if (!item) return;
      pending.delete(data.id);
      if (data.error) item.reject(new Error(data.error.message)); else item.resolve(data.result);
    };
    const broken = await run('html[data-dsh-mac-chrome] [class*="_fade"]{display:none!important}');
    assert(broken.changes > 5, 'control must reproduce the resize feedback loop');
    assert(broken.samples.includes(0), 'control must lose the process body');
    const fixed = await run(css);
    assert(fixed.changes <= 2, JSON.stringify(fixed));
    assert(fixed.samples.every(height => height === 200), JSON.stringify(fixed));
    assert(fixed.sidebarHidden, 'sidebar fade should remain hidden');
    const expanded = await run(css, true);
    assert(expanded.samples.every(height => height === 1700), JSON.stringify(expanded));
    console.log(JSON.stringify({ brokenChanges: broken.changes, fixedChanges: fixed.changes, expandedHeight: expanded.samples.at(-1) }));
  } finally {
    clearTimeout(timeout);
    socket?.close();
    browser.kill();
    await new Promise(resolve => browser.exitCode !== null ? resolve() : browser.once('exit', resolve));
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
