const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const app = process.argv[2];
const solid = process.argv[3] === 'solid';
const atom = '_KDE_NET_WM_BLUR_BEHIND_REGION';
const main = fs.readFileSync(path.join(app, 'lib/main.js'), 'utf8');
const helper = main.split('/* dsh-linux-blur:begin v1 */')[1].split('/* dsh-linux-blur:end */')[0];

async function probe(options = {}) {
  const calls = [], backgrounds = [];
  let destroyed = options.destroyed || false;
  const window = {
    isDestroyed: () => destroyed,
    setBackgroundColor: color => backgrounds.push(color),
    getNativeWindowHandle: () => options.handle || Buffer.from([42, 0, 0, 0, 0, 0, 0, 0]),
  };
  const execFile = (file, args, config, callback) => {
    calls.push(Array.from(args));
    assert.equal(file, 'xprop');
    assert.equal(config.timeout, 800);
    assert.equal(config.env.LC_ALL, 'C');
    if (options.error) return callback(new Error(options.error));
    if (args[0] === '-root') return callback(null,
      options.unsupported ? `${atom}: no such atom on any window.` : `${atom}(ATOM) = 0`);
    if (args.includes('_NET_WM_PID')) return callback(null,
      `_NET_WM_PID(CARDINAL) = ${options.foreign ? 99 : 1234}`);
    if (args.includes('-set')) return callback(null, '');
    if (options.destroyDuringRead) destroyed = true;
    callback(null, options.refused ? `${atom}: not found.` : `${atom}(CARDINAL) = 0`);
  };
  const context = vm.createContext({
    Buffer, fakeExecFile: execFile,
    process: { platform: 'linux', pid: 1234, env: options.noDisplay ? {} : { DISPLAY: ':1', WAYLAND_DISPLAY: 'wayland-1' } },
    nativeTheme: { shouldUseDarkColors: Boolean(options.dark) },
  });
  // Replace only module loading so the generated helper runs with a fake
  // child process; all capability checks, args and state transitions are real.
  vm.runInContext(helper.replace('await import("node:child_process")', '({ execFile: fakeExecFile })'), context);
  const mode = await context.requestLinuxBlur(window);
  return { mode, calls, backgrounds };
}

function renderer(preload, reply, failStyleOnce = false) {
  let response = reply;
  let maximized = false;
  const source = fs.readFileSync(path.join(app, 'lib', preload), 'utf8')
    .split('/* dsh-linux-chrome:begin v3 */')[1].split('/* dsh-linux-chrome:end */')[0];
  const elements = new Map(), intervals = [], handlers = {}, calls = [];
  const makeElement = () => ({
    dataset: {}, style: { setProperty() {}, getPropertyValue() { return ''; } },
    setAttribute() {}, removeAttribute() {}, addEventListener() {}, appendChild() {},
  });
  const root = makeElement();
  const sidebar = { getBoundingClientRect: () => ({ width: 280 }) };
  const appendChild = node => elements.set(node.id, node);
  const document = {
    documentElement: root, readyState: 'complete',
    body: { appendChild }, head: { appendChild },
    getElementById: id => elements.get(id) || null,
    querySelector: () => preload === 'preload-app.cjs' ? sidebar : null, createElement: makeElement,
  };
  const context = vm.createContext({
    document, process: { platform: 'linux' },
    electron: { ipcRenderer: { invoke: async (channel, action, css) => {
      calls.push([channel, action, css]);
      if (action === "chrome-style") {
        if (failStyleOnce) { failStyleOnce = false; throw new Error('IPC not ready'); }
        return true;
      }
      if (action === "state") return { maximized };
      if (response instanceof Error) throw response;
      return response;
    } } },
    window: { innerWidth: 800, innerHeight: 600, screen: { availWidth: 1920, availHeight: 1080 },
      addEventListener: (event, callback) => {
        const previous = handlers[event];
        handlers[event] = () => { previous?.(); callback(); };
      } },
    MutationObserver: class { observe() {} },
    ResizeObserver: class { observe() {} unobserve() {} },
    setInterval: (callback, delay) => { intervals.push({ callback, delay }); return 1; },
    setTimeout() {}, clearInterval() {}, requestAnimationFrame: callback => callback(),
  });
  vm.runInContext(source, context);
  assert.equal(root.dataset.dshLinuxBlur, solid ? 'solid' : 'css', 'Opaque surface must exist before native reply');
  assert.equal(elements.has('dsh-mac-vibrancy'), !solid);
  return { root, elements, intervals, handlers, calls, setReply: value => { response = value; }, setMaximized: value => { maximized = value; } };
}

(async () => {
  // The renderer only styles its own window, including CSP-protected welcome.
  const control = main.match(/ipcMain.handle\("dsh-desktop:linux-window-control", async \(event, action, css\) => \{[\s\S]*?\n\t\}\);/)[0];
  let ownedWindow = null, handler;
  const inserted = [];
  vm.runInNewContext(control, {
    ipcMain: { handle: (_, callback) => { handler = callback; } },
    BrowserWindow: { fromWebContents: () => ownedWindow },
  });
  assert.equal(await handler({ sender: {} }, 'chrome-style', 'body {}'), false);
  ownedWindow = { isDestroyed: () => false, webContents: { insertCSS: async css => inserted.push(css) } };
  assert.equal(await handler({ sender: {} }, 'chrome-style', null), false);
  assert.equal(await handler({ sender: {} }, 'chrome-style', 'x'.repeat(65537)), false);
  assert.equal(await handler({ sender: {} }, 'chrome-style', 'body { background: #fff }'), true);
  assert.deepEqual(inserted, ['body { background: #fff }']);

  // A maximized KWin window must keep its controls; real fullscreen hides them.
  const body = main.match(/const sendFullscreen = \(\) => \{([\s\S]*?)\n\t\t\};/)[1];
  for (const fullscreen of [false, true]) {
    const sent = [];
    const context = vm.createContext({
      window: { isDestroyed: () => false, isFullScreen: () => fullscreen,
        isMaximized: () => true, webContents: { send: (_, state) => sent.push(state) } },
      DESKTOP_IPC: { windowFullscreen: 'fullscreen' }, process: { platform: 'linux' },
    });
    vm.runInContext('(()=>{' + body + '})()', context);
    assert.deepEqual(sent, [fullscreen]);
  }
  // A Wayland session with a validated XWayland window must still succeed.
  let result = await probe();
  assert.equal(result.mode, 'system');
  assert.deepEqual(result.backgrounds, ['#00000000']);
  assert.deepEqual(result.calls[2], ['-id', '0x2a', '-f', atom, '32c', '-set', atom, '0']);
  for (const options of [{ unsupported: true }, { foreign: true }, { noDisplay: true },
    { error: 'ENOENT' }, { error: 'timeout' }, { refused: true }, { handle: Buffer.alloc(1) },
    { handle: Buffer.alloc(8) }, { handle: Buffer.from([42, 0, 0, 0, 1, 0, 0, 0]) }]) {
    result = await probe(options);
    assert.equal(result.mode, 'css', JSON.stringify(options));
    assert.deepEqual(result.backgrounds, ['#00000000']);
    if (options.foreign || options.unsupported) assert.ok(!result.calls.some(args => args.includes('-set')));
  }
  assert.deepEqual((await probe({ unsupported: true, dark: true })).backgrounds, ['#00000000']);
  assert.deepEqual((await probe({ destroyDuringRead: true })).backgrounds, []);
  for (const preload of ['preload-app.cjs', 'preload-welcome.cjs']) {
    for (const reply of ['system', 'css', new Error('IPC failed')]) {
      const state = renderer(preload, reply);
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(state.root.dataset.dshLinuxBlur, solid ? 'solid' : reply === 'system' ? 'system' : 'css');
      assert.equal(state.calls.filter(call => call[1] !== 'chrome-style')[0][1], solid ? 'state' : 'blur');
      const styles = state.calls.filter(call => call[1] === 'chrome-style');
      assert.equal(styles.length, 1);
      assert.ok(styles[0][2].includes('clip-path: inset(0 round 12px)'));
      assert.ok(!state.elements.has('dsh-mac-chrome-style'), 'CSP-blocked inline styles must not be used');
      state.intervals.find(timer => timer.delay === 500).callback();
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(state.calls.filter(call => call[1] === 'chrome-style').length, 1);
      assert.equal(state.root.dataset.dshWindowMaximized, 'false');
      state.setMaximized(true);
      state.handlers.resize();
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(state.root.dataset.dshWindowMaximized, 'true');
      state.setMaximized(false);
      state.handlers.resize();
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(state.root.dataset.dshWindowMaximized, 'false');
      assert.equal(state.intervals.some(timer => timer.delay === 10000), !solid);
      if (!solid && reply === 'system') {
        // Simulate a failed recheck after a successful first request.
        state.setReply('css');
        state.handlers.focus();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(state.calls.filter(call => call[1] === "blur").length, 2);
        assert.equal(state.root.dataset.dshLinuxBlur, 'css');
      }
    }
  }
  const retry = renderer('preload-welcome.cjs', 'css', true);
  await new Promise(resolve => setImmediate(resolve));
  const poll = retry.intervals.find(timer => timer.delay === 500);
  poll.callback();
  await new Promise(resolve => setImmediate(resolve));
  poll.callback();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(retry.calls.filter(call => call[1] === 'chrome-style').length, 2, 'Retry failed CSS once; keep successful insertion');
  console.log('Linux blur + preload runtime checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
