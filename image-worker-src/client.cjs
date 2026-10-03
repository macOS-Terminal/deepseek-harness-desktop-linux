'use strict';
/**
 * Client half of the out-of-process raster pipeline.
 *
 * Presents the Sharp API surface that `@deepseek-ai/dsh-attachment-local` uses, while
 * every libvips call happens in a standalone-Node worker. `require('sharp')` therefore
 * never loads libvips inside Electron, which is what keeps the pre-existing Linux
 * libvips fault from taking the desktop shell down.
 *
 * The chain is recorded as a list of `{ name, args }` steps and replayed in the worker,
 * so chainable Sharp methods keep working without enumerating them here.
 */
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { existsSync } = require('node:fs');
const { dirname, join } = require('node:path');

const REQUEST_TIMEOUT_MS = Number(process.env.DSH_IMAGE_WORKER_TIMEOUT_MS ?? 120000);
/** Give up after this many consecutive worker deaths; image work then fails fast. */
const MAX_CONSECUTIVE_FAILURES = Number(process.env.DSH_IMAGE_WORKER_MAX_FAILURES ?? 3);
const HANDLE_LIMIT = 8;
const DEBUG = process.env.DSH_IMAGE_WORKER_DEBUG === '1';

/** Methods that finish the chain instead of returning a new pipeline. */
const TERMINALS = new Set(['toBuffer', 'toFile', 'metadata', 'stats']);
/** Methods that select an output codec; they finish through toBuffer. */
const OUTPUT_FORMATS = new Set(['jpeg', 'jpg', 'png', 'webp', 'avif', 'tiff', 'gif', 'heif', 'jxl']);

const state = {
  child: null,
  nextId: 1,
  pending: new Map(),
  inbound: Buffer.alloc(0),
  handles: new Map(),
  failures: 0,
  tail: [],
};

function note(entry) {
  state.tail.push(entry);
  while (state.tail.length > 20) state.tail.shift();
}

/**
 * Locate the resources root.
 *
 * The worker, the bundled Node, and the Python payload all live directly under
 * `<resources>/`, and this client always sits at `<resources>/image-worker/`. Deriving
 * the root from `__dirname` therefore works for every packaging layout — flat app
 * directory, `app.asar`, bundled Electron, or system Electron — without relying on
 * `process.resourcesPath`, which points at the distribution's Electron under a
 * system-wide runtime.
 */
function resourcesRoot() {
  const configured = process.env.DSH_DESKTOP_RESOURCES_DIR;
  if (configured !== undefined && configured !== '') return configured;
  const derived = dirname(__dirname);
  if (existsSync(join(derived, 'runtime')) || existsSync(join(derived, 'app'))) return derived;
  if (existsSync(join(derived, 'app.asar'))) return derived;
  return process.resourcesPath ?? derived;
}

function resolveNodeBinary() {
  const explicit = process.env.DSH_IMAGE_WORKER_NODE ?? process.env.DSH_DESKTOP_NODE_BINARY;
  if (explicit !== undefined && explicit !== '' && existsSync(explicit)) return explicit;
  const resources = resourcesRoot();
  for (const candidate of [
    join(resources, 'runtime', 'primary-runtime', 'dependencies', 'node', 'bin', 'node'),
    join(resources, 'runtime', 'bin', 'node'),
  ]) {
    if (existsSync(candidate)) return candidate;
  }
  // Last resort: the Electron binary in Node mode still behaves as a standalone Node.
  return process.execPath;
}

function resolveWorkerScript() {
  for (const candidate of [join(__dirname, 'worker.cjs'), process.env.DSH_IMAGE_WORKER_SCRIPT]) {
    if (candidate !== undefined && candidate !== '' && existsSync(candidate)) return candidate;
  }
  throw new Error('image worker: worker.cjs is missing beside the client');
}

/**
 * Spawn the worker with a minimal environment.
 *
 * Electron exports library and asar variables into children; a clean environment keeps
 * the worker's dynamic linker away from Chromium's libraries, which is the point.
 */
function spawnWorker() {
  const node = resolveNodeBinary();
  const script = resolveWorkerScript();
  const environment = {
    PATH: process.env.PATH ?? '/usr/bin:/bin',
    HOME: process.env.HOME ?? '',
    LANG: process.env.LANG ?? 'C',
    TMPDIR: process.env.TMPDIR ?? '/tmp',
  };
  if (DEBUG) environment.DSH_IMAGE_WORKER_DEBUG = '1';
  const child = spawn(node, [script], {
    cwd: dirname(script),
    env: environment,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });
  child.stdout.on('data', (chunk) => {
    state.inbound = state.inbound.length === 0 ? chunk : Buffer.concat([state.inbound, chunk]);
    drain();
  });
  child.stderr.on('data', (chunk) => {
    for (const line of String(chunk).split('\n')) {
      if (line.trim() !== '') note(line.trim());
    }
  });
  child.on('error', (error) => {
    failAll(new Error(`image worker failed to start: ${error.message}`));
  });
  child.on('exit', (code, signal) => {
    state.child = null;
    state.failures += 1;
    const detail = state.tail.slice(-3).join(' | ');
    const how = signal !== null && signal !== undefined ? `signal ${signal}` : `exit code ${String(code)}`;
    failAll(new Error(`image worker stopped unexpectedly (${how})${detail === '' ? '' : `: ${detail}`}`));
  });
  state.child = child;
  return child;
}

function ensureChild() {
  if (state.failures >= MAX_CONSECUTIVE_FAILURES) {
    throw new Error(`image worker unavailable after ${String(state.failures)} consecutive failures`);
  }
  if (state.child === null) spawnWorker();
  return state.child;
}

function failAll(error) {
  for (const entry of state.pending.values()) {
    clearTimeout(entry.timer);
    entry.reject(error);
  }
  state.pending.clear();
  state.handles.clear();
}

function drain() {
  for (;;) {
    if (state.inbound.length < 4) return;
    const headerLength = state.inbound.readUInt32LE(0);
    if (headerLength === 0 || headerLength > 8 * 1024 * 1024) {
      note('protocol: malformed response header; restarting worker');
      state.child?.kill('SIGKILL');
      return;
    }
    if (state.inbound.length < 4 + headerLength) return;
    let header;
    try {
      header = JSON.parse(state.inbound.toString('utf8', 4, 4 + headerLength));
    } catch {
      note('protocol: response header is not JSON; restarting worker');
      state.child?.kill('SIGKILL');
      return;
    }
    const payloadLength = Number.isInteger(header.payloadLength) ? header.payloadLength : 0;
    if (state.inbound.length < 4 + headerLength + payloadLength) return;
    const payload = payloadLength === 0
      ? Buffer.alloc(0)
      : Buffer.from(state.inbound.subarray(4 + headerLength, 4 + headerLength + payloadLength));
    state.inbound = state.inbound.subarray(4 + headerLength + payloadLength);
    deliver(header, payload);
  }
}

/** Revive Buffers that crossed the wire as tagged base64. */
function decodeValue(value) {
  if (value === null || typeof value !== 'object') return value;
  if (typeof value.__dshBuffer === 'string') return Buffer.from(value.__dshBuffer, 'base64');
  if (Array.isArray(value)) return value.map(decodeValue);
  const out = {};
  for (const key of Object.keys(value)) out[key] = decodeValue(value[key]);
  return out;
}

function deliver(header, payload) {
  const entry = state.pending.get(header.id);
  if (entry === undefined) return;
  state.pending.delete(header.id);
  clearTimeout(entry.timer);
  if (header.ok === true) {
    entry.resolve({ json: decodeValue(header.json ?? null), payload });
    return;
  }
  const detail = header.error ?? {};
  const error = new Error(detail.message ?? 'image worker request failed');
  if (detail.name !== undefined) error.name = detail.name;
  if (detail.code !== undefined) error.code = detail.code;
  error.fromImageWorker = true;
  entry.reject(error);
}

function request(kind, body, payload) {
  const child = ensureChild();
  const id = state.nextId++;
  // payloadLength must travel inside the header: the worker sizes its read from it.
  const header = { id, kind, ...body, payloadLength: payload ? payload.length : 0 };
  const headerBytes = Buffer.from(JSON.stringify(header), 'utf8');
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32LE(headerBytes.length, 0);
  const frame = payload && payload.length
    ? Buffer.concat([prefix, headerBytes, payload])
    : Buffer.concat([prefix, headerBytes]);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      state.pending.delete(id);
      note(`timeout: ${kind} exceeded ${String(REQUEST_TIMEOUT_MS)}ms; restarting worker`);
      child.kill('SIGKILL');
      reject(new Error(`image worker timed out after ${String(REQUEST_TIMEOUT_MS)}ms`));
    }, REQUEST_TIMEOUT_MS);
    if (typeof timer.unref === 'function') timer.unref();
    state.pending.set(id, { resolve, reject, timer });
    child.stdin.write(frame, (error) => {
      if (error === undefined || error === null) return;
      state.pending.delete(id);
      clearTimeout(timer);
      reject(error);
    });
  });
}

/** Upload source bytes once, then address them by handle while a ladder runs. */
async function upload(buffer) {
  const key = createHash('sha256').update(buffer).digest('hex');
  const cached = state.handles.get(key);
  if (cached !== undefined) return cached;
  const { json } = await request('upload', {}, buffer);
  const handle = json?.handle;
  if (!Number.isInteger(handle)) throw new Error('image worker did not return a source handle');
  if (state.handles.size >= HANDLE_LIMIT) {
    const oldest = state.handles.keys().next();
    if (!oldest.done) state.handles.delete(oldest.value);
  }
  state.handles.set(key, handle);
  return handle;
}

/** Options must survive JSON; reject anything that cannot cross the wire. */
function sanitize(args) {
  return args.map((arg) => {
    if (arg === undefined) return null;
    return JSON.parse(JSON.stringify(arg));
  });
}

/** Translate positional client arguments into the worker's terminal descriptor. */
function terminalArgs(name, args) {
  if (name === 'toBuffer') {
    const options = args[0];
    const raw = options !== undefined && options !== null && options.raw === true;
    const resolveWithObject = options === undefined || options === null
      ? false
      : options.resolveWithObject === true;
    return { raw, resolveWithObject };
  }
  if (name === 'toFile') return { path: args[0] };
  return {};
}

/**
 * Build one immutable chain node.
 *
 * @param source - source bytes, retained for every derivative of this chain.
 * @param inputOptions - options handed to Sharp on construction.
 * @param ops - recorded pipeline steps.
 * @param format - selected output codec, or null for the default encoder.
 */
function createPipeline(source, inputOptions, ops, format) {
  const finish = async (terminal, args) => {
    if (state.failures >= MAX_CONSECUTIVE_FAILURES) throw new Error('image worker unavailable');
    const handle = await upload(source);
    const descriptor = { name: terminal, ...terminalArgs(terminal, args) };
    if (format !== null) {
      descriptor.format = format.name;
      descriptor.formatOptions = format.options ?? {};
    }
    const started = Date.now();
    const { json, payload } = await request('run', {
      uploaded: true,
      handle,
      ops,
      terminal: descriptor,
      inputOptions,
    });
    if (DEBUG) note(`timing: ${terminal} ${String(Date.now() - started)}ms`);
    if (terminal === 'metadata' || terminal === 'stats' || terminal === 'toFile') return json;
    if (terminal === 'toBuffer') {
      const options = args[0];
      const wantsObject = options !== undefined && options !== null && options.resolveWithObject === true;
      return wantsObject ? { data: payload, info: json?.info ?? {} } : payload;
    }
    return json;
  };

  const pipeline = {
    clone: () => createPipeline(source, inputOptions, [...ops], format),
    toBuffer: (...args) => finish('toBuffer', args),
    toFile: (...args) => finish('toFile', args),
    metadata: (...args) => finish('metadata', args),
    stats: (...args) => finish('stats', args),
    __dshImageWorkerOps: () => [...ops],
  };

  for (const formatName of OUTPUT_FORMATS) {
    pipeline[formatName] = (options) => createPipeline(source, inputOptions, ops, {
      name: formatName === 'jpg' ? 'jpeg' : formatName,
      options: options ?? {},
    });
  }

  // Any other property is a recorded pipeline step, so unfamiliar Sharp methods still work.
  return new Proxy(pipeline, {
    get(target, property, receiver) {
      if (typeof property !== 'string' || property in target) {
        return Reflect.get(target, property, receiver);
      }
      if (property === 'then' || property === 'constructor') return undefined;
      if (TERMINALS.has(property)) {
        return (...args) => finish(property, args);
      }
      if (OUTPUT_FORMATS.has(property)) {
        return (options) => createPipeline(source, inputOptions, ops, { name: property, options: options ?? {} });
      }
      return (...args) => createPipeline(source, inputOptions, [...ops, { name: property, args: sanitize(args) }], format);
    },
  });
}

/**
 * Sharp-compatible entry point.
 *
 * @param input - source bytes (Buffer or Uint8Array).
 * @param options - Sharp constructor options, forwarded to the worker.
 * @returns a chainable pipeline whose work happens out of process.
 */
function sharp(input, options) {
  let buffer;
  if (Buffer.isBuffer(input)) buffer = input;
  else if (input instanceof Uint8Array) buffer = Buffer.from(input);
  else throw new TypeError('sharp: source must be a Buffer or Uint8Array');
  return createPipeline(buffer, options ?? {}, [], null);
}

sharp.cache = () => undefined;
sharp.concurrency = () => 1;
sharp.simd = () => false;
sharp.versions = { sharp: '0.35.4+dsh-worker', vips: 'isolated' };
sharp.format = {};
sharp.queue = { on: () => undefined };
/** Terminate the worker; used on shutdown so no orphan process outlives the shell. */
sharp.destroy = () => {
  const child = state.child;
  state.child = null;
  if (child !== null) {
    try {
      child.stdin.end();
    } catch {
      /* the pipe may already be gone */
    }
  }
};
/** Diagnostics for support bundles: worker pid, in-flight requests, recent stderr. */
sharp.__dshWorkerStatus = () => ({
  pid: state.child === null ? null : state.child.pid,
  pending: state.pending.size,
  failures: state.failures,
  tail: [...state.tail],
});

module.exports = sharp;
module.exports.default = sharp;
