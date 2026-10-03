'use strict';
/**
 * Out-of-process raster worker for the DeepSeek Harness desktop shell.
 *
 * Runs on the bundled standalone Node runtime — never on Electron — so libvips is
 * loaded in a process that shares no symbol space with Chromium, GTK, or Electron's
 * Node environment. A libvips fault therefore kills only this worker; the client
 * notices the exit and restarts it on the next request, so image handling degrades to
 * a failed operation instead of taking the desktop shell down.
 *
 * Wire format over stdio, both directions:
 *   [4-byte LE uint32 header length][header JSON (utf8)][optional payload bytes]
 */
const { createRequire } = require('node:module');
const { existsSync } = require('node:fs');
const { join } = require('node:path');

/**
 * Resolve Sharp from this worker's private closure.
 *
 * The closure sits beside the worker (`worker-modules/`) so libvips loads from paths
 * physically outside `app.asar` (standalone Node has no asar support), and so the
 * Electron process tree never resolves this copy.
 */
function resolveSharp() {
  const vendored = join(__dirname, 'worker-modules', 'node_modules', 'sharp', 'package.json');
  if (existsSync(vendored)) return createRequire(vendored)('sharp');
  const hint = process.env.DSH_IMAGE_SHARP_ROOT;
  if (hint !== undefined && hint !== '') return createRequire(join(hint, 'package.json'))('sharp');
  return require('sharp');
}

const sharp = resolveSharp();

/** Bounded cache of uploaded sources, addressed by handle; the client reuses them. */
const HANDLES = new Map();
const MAX_HANDLES = 8;
let nextHandle = 1;

/** Buffers travel as tagged base64 inside JSON so the client can revive them. */
function encodeValue(value) {
  if (Buffer.isBuffer(value)) return { __dshBuffer: value.toString('base64') };
  if (value instanceof Uint8Array) return { __dshBuffer: Buffer.from(value).toString('base64') };
  if (Array.isArray(value)) return value.map(encodeValue);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value)) {
      const inner = value[key];
      if (inner === undefined) continue;
      out[key] = encodeValue(inner);
    }
    return out;
  }
  return value;
}

function serializeError(error) {
  return {
    name: error && error.name ? String(error.name) : 'Error',
    message: error && error.message ? String(error.message) : String(error),
    code: error && error.code !== undefined ? String(error.code) : undefined,
  };
}

function rememberHandle(buffer) {
  const handle = nextHandle++;
  HANDLES.set(handle, buffer);
  while (HANDLES.size > MAX_HANDLES) {
    const oldest = HANDLES.keys().next();
    if (oldest.done) break;
    HANDLES.delete(oldest.value);
  }
  return handle;
}

/**
 * Replay the recorded lazy pipeline against real libvips.
 *
 * Operations are replayed generically, so any chainable Sharp method the Host uses in
 * future keeps working without touching this worker.
 */
function buildPipeline(request, buffer) {
  let image = sharp(buffer, request.inputOptions ?? {});
  for (const op of request.ops ?? []) {
    const method = image[op.name];
    if (typeof method !== 'function') {
      throw new Error(`image worker: unknown pipeline operation ${String(op.name)}`);
    }
    const result = method.apply(image, op.args ?? []);
    if (result !== undefined) image = result;
  }
  return image;
}

/** Apply the explicit output format when the client recorded one. */
function applyFormat(pipeline, terminal, options) {
  const encoder = pipeline[terminal.format];
  if (typeof encoder !== 'function') {
    throw new Error(`image worker: unknown output format ${String(terminal.format)}`);
  }
  const result = encoder.call(pipeline, options);
  return result === undefined ? pipeline : result;
}

async function runTerminal(request, buffer) {
  const terminal = request.terminal ?? {};
  const formatOptions = terminal.formatOptions ?? null;
  const pipeline = formatOptions === null
    ? buildPipeline(request, buffer)
    : applyFormat(buildPipeline(request, buffer), terminal, formatOptions);

  if (terminal.name === 'metadata') {
    return { json: encodeValue(await sharp(buffer, request.inputOptions ?? {}).metadata()) };
  }
  if (terminal.name === 'stats') {
    return { json: encodeValue(await pipeline.stats()) };
  }
  if (terminal.name === 'toFile') {
    return { json: encodeValue(await pipeline.toFile(terminal.path)) };
  }
  if (terminal.name === 'toBuffer') {
    if (terminal.raw === true) {
      return { json: null, payload: await pipeline.raw().toBuffer() };
    }
    if (terminal.resolveWithObject === true) {
      const result = await pipeline.toBuffer({ resolveWithObject: true });
      return { json: encodeValue({ info: result.info }), payload: result.data };
    }
    return { json: null, payload: await pipeline.toBuffer() };
  }
  throw new Error(`image worker: unsupported terminal operation ${String(terminal.name)}`);
}

async function handleFrame(header, payload) {
  if (header.kind === 'upload') {
    return { header: { id: header.id, ok: true, json: { handle: rememberHandle(payload) } } };
  }
  if (header.kind === 'release') {
    HANDLES.delete(header.handle);
    return { header: { id: header.id, ok: true, json: null } };
  }
  if (header.kind === 'ping') {
    return { header: { id: header.id, ok: true, json: { pid: process.pid, versions: process.versions } } };
  }
  if (header.kind !== 'run') throw new Error(`image worker: unsupported request kind ${String(header.kind)}`);
  const buffer = header.uploaded === true ? HANDLES.get(header.handle) : payload;
  if (!Buffer.isBuffer(buffer)) throw new Error('image worker: source bytes are no longer available');
  const result = await runTerminal(header, buffer);
  return {
    header: {
      id: header.id,
      ok: true,
      json: result.json ?? null,
      payloadLength: result.payload ? result.payload.length : 0,
    },
    payload: result.payload,
  };
}

/* ---------------------------------------------------------------- framing -- */
let inbound = Buffer.alloc(0);
let writing = Promise.resolve();

function frame(header, payload) {
  const headerBytes = Buffer.from(JSON.stringify(header), 'utf8');
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32LE(headerBytes.length, 0);
  return payload && payload.length
    ? Buffer.concat([prefix, headerBytes, payload])
    : Buffer.concat([prefix, headerBytes]);
}

function send(header, payload) {
  const bytes = frame(header, payload);
  writing = writing.then(() => new Promise((resolve) => {
    if (process.stdout.write(bytes)) resolve();
    else process.stdout.once('drain', resolve);
  }));
  return writing;
}

function drainInbound() {
  for (;;) {
    if (inbound.length < 4) return;
    const headerLength = inbound.readUInt32LE(0);
    if (headerLength === 0 || headerLength > 8 * 1024 * 1024) {
      process.stderr.write('image worker: malformed frame header\n');
      process.exit(2);
    }
    if (inbound.length < 4 + headerLength) return;
    let header;
    try {
      header = JSON.parse(inbound.toString('utf8', 4, 4 + headerLength));
    } catch {
      process.stderr.write('image worker: request header is not valid JSON\n');
      process.exit(2);
      return;
    }
    const payloadLength = Number.isInteger(header.payloadLength) ? header.payloadLength : 0;
    if (inbound.length < 4 + headerLength + payloadLength) return;
    const payload = payloadLength === 0
      ? Buffer.alloc(0)
      : Buffer.from(inbound.subarray(4 + headerLength, 4 + headerLength + payloadLength));
    inbound = inbound.subarray(4 + headerLength + payloadLength);
    void dispatch(header, payload);
  }
}

async function dispatch(header, payload) {
  try {
    const result = await handleFrame(header, payload);
    await send(result.header, result.payload);
  } catch (error) {
    await send({ id: header.id, ok: false, error: serializeError(error) });
  }
}

process.stdin.on('data', (chunk) => {
  inbound = inbound.length === 0 ? chunk : Buffer.concat([inbound, chunk]);
  drainInbound();
});
/* The client owns this process: a closed request pipe ends the worker. */
process.stdin.on('end', () => process.exit(0));
process.stdin.on('close', () => process.exit(0));
process.stdout.on('error', () => process.exit(0));
