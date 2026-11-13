'use strict';
/**
 * Integration check for the out-of-process Sharp facade, run *inside Electron*
 * (same execution mode as the desktop Host).
 *
 * Verifies:
 *   1. resolving `sharp` the way @deepseek-ai/dsh-attachment-local does reaches the facade
 *   2. libvips never appears in this process's memory map
 *   3. every API call the attachment pipeline makes actually works
 *   4. malformed input raises an error instead of crashing the process
 */
const { existsSync, readFileSync } = require('node:fs');
const { spawnSync } = require('node:child_process');
const { createRequire } = require('node:module');

const RES = process.env.DSH_DESKTOP_RESOURCES_DIR || '/usr/lib/deepseek-harness/resources';
const APP = `${RES}/app`;
const NODE = `${RES}/runtime/primary-runtime/dependencies/node/bin/node`;
const VENDORED = `${RES}/image-worker/worker-modules/node_modules/sharp`;

process.env.DSH_DESKTOP_RESOURCES_DIR = RES;

const mapsHasVips = () => {
  try {
    return /libvips/i.test(readFileSync(`/proc/${process.pid}/maps`, 'utf8'));
  } catch {
    return null;
  }
};

/** Generate a source image with the vendored (out-of-process) sharp. */
function sourceImage(script) {
  const r = spawnSync(NODE, ['-e', `const s = require(${JSON.stringify(VENDORED)}); ${script}`], {
    maxBuffer: 1 << 28,
  });
  if (r.status !== 0) throw new Error(`source generation failed: ${r.stderr?.toString().slice(0, 300)}`);
  return new Uint8Array(r.stdout);
}

(async () => {
  let failures = 0;
  const check = (label, ok, detail = '') => {
    console.log(`  ${ok ? '✓' : '✗'} ${label}${detail ? ` (${detail})` : ''}`);
    if (!ok) failures++;
  };

  console.log(`Electron ${process.versions.electron} / Node ${process.versions.node}`);
  check('加载 shim 前本进程无 libvips', mapsHasVips() === false);

  // Reject the native package before requiring it: its entry is also
  // node_modules/sharp/dist/index.cjs, so a path-only check is a false pass.
  const facadePackage = JSON.parse(readFileSync(`${APP}/dsh/node_modules/sharp/package.json`, 'utf8'));
  const isFacade = typeof facadePackage.description === 'string'
    && facadePackage.description.includes('Out-of-process Sharp facade');
  const workerReady = [
    `${RES}/image-worker/client.cjs`,
    `${RES}/image-worker/worker.cjs`,
    `${RES}/image-worker/worker-modules/node_modules/sharp/package.json`,
  ].every(existsSync);
  check('sharp 包确为隔离 facade', isFacade, facadePackage.description ?? '(无 description)');
  check('image-worker 载荷完整', workerReady, RES.replace(/^.+?(?=\/resources)/, '…'));
  if (!isFacade || !workerReady) {
    console.error('\n❌ 原生 sharp 或缺失的 worker 不能进入图片测试；请先修复打包');
    process.exit(1);
  }

  // Resolve exactly like the attachment package does.
  const req = createRequire(`${APP}/dsh/node_modules/@deepseek-ai/dsh-attachment-local/lib/index.js`);
  const resolved = req.resolve('sharp');
  const sharp = req('sharp');
  check('sharp 解析到 facade', resolved.includes('node_modules/sharp/dist/index.cjs'), resolved.replace(RES, '…'));

  // Build the images the pipeline actually handles.
  const jpeg = sourceImage(`s({create:{width:800,height:600,channels:3,background:{r:90,g:140,b:220}}}).jpeg({quality:88}).toBuffer().then(b=>process.stdout.write(b))`);
  const pngAlpha = sourceImage(`s({create:{width:400,height:300,channels:4,background:{r:10,g:200,b:80,alpha:0.5}}}).png().toBuffer().then(b=>process.stdout.write(b))`);
  const webp = sourceImage(`s({create:{width:300,height:200,channels:3,background:{r:200,g:30,b:30}}}).webp({quality:80}).toBuffer().then(b=>process.stdout.write(b))`);
  const gif = sourceImage(`s({create:{width:120,height:120,channels:3,background:{r:0,g:0,b:255}}}).gif().toBuffer().then(b=>process.stdout.write(b))`);
  const large = sourceImage(`s({create:{width:6000,height:4000,channels:3,background:{r:32,g:96,b:160}}}).jpeg({quality:85}).toBuffer().then(b=>process.stdout.write(b))`);
  const animatedGif = Buffer.from('R0lGODlhBAAEAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACAAAACwAAAAABAAEAAAICQABCBxIsCCAgAAh+QQBCAABACwAAAAABAAEAIEAAP8AAAAAAAAAAAAICQABCBxIsCCAgAA7', 'base64');

  // 1) probeImage path: metadata only
  const md = await sharp(jpeg, { failOn: 'error', limitInputPixels: false }).metadata();
  check('probeImage 路径 metadata', md.format === 'jpeg' && md.width === 800, `${md.format} ${md.width}x${md.height}`);

  // 2) detectImage path: full decode
  const raw = await sharp(jpeg, { failOn: 'error', limitInputPixels: false }).raw().toBuffer();
  check('detectImage 路径全量解码', raw.length === 800 * 600 * 3, `${raw.length} bytes`);

  // 3) normalizeImage path: rotate → toColourspace → resize → ladder with clone
  const prepared = sharp(jpeg, { failOn: 'error', limitInputPixels: false })
    .rotate()
    .toColourspace('srgb')
    .resize({ width: 512, height: 512, fit: 'inside', withoutEnlargement: true });
  let smallest = null;
  for (const quality of [85, 75, 60]) {
    const out = await prepared.clone().jpeg({ quality }).toBuffer({ resolveWithObject: true });
    if (smallest === null || out.data.byteLength < smallest) smallest = out.data.byteLength;
  }
  check('normalizeImage 质量阶梯 + clone', smallest !== null && smallest > 0, `最小 ${smallest} bytes`);

  const asWebp = await prepared.clone().webp({ quality: 80, effort: 0 }).toBuffer({ resolveWithObject: true });
  check('alpha 源走 webp 编码', asWebp.info.format === 'webp', `${asWebp.data.byteLength} bytes`);

  // 4) the other admitted types
  for (const [label, bytes] of [['png(alpha)', pngAlpha], ['webp', webp], ['gif', gif]]) {
    const meta = await sharp(bytes).metadata();
    check(`${label} 可解码`, typeof meta.width === 'number' && meta.width > 0, `${meta.format} ${meta.width}x${meta.height}`);
  }

  // 5) large input, animation, concurrent requests, and malformed data.
  const largeOut = await sharp(large, { failOn: 'error', limitInputPixels: false })
    .resize({ width: 512, height: 512, fit: 'inside', withoutEnlargement: true })
    .jpeg({ quality: 80 }).toBuffer({ resolveWithObject: true });
  check('6000x4000 大图归一化', largeOut.info.width === 512 && largeOut.info.height <= 512,
    `${largeOut.info.width}x${largeOut.info.height}, ${largeOut.data.byteLength} bytes`);

  const animatedMeta = await sharp(animatedGif).metadata();
  check('动画 GIF 可读取', animatedMeta.format === 'gif' && animatedMeta.pages === 2,
    `${animatedMeta.width}x${animatedMeta.height}, pages=${animatedMeta.pages}`);

  const concurrent = await Promise.all([jpeg, pngAlpha, webp, gif].map((bytes) => sharp(bytes).metadata()));
  check('并发 metadata 请求', concurrent.every((meta) => typeof meta.width === 'number' && meta.width > 0),
    `${concurrent.length} 个请求`);

  for (const [label, bytes] of [['坏数据', Buffer.from('not an image at all')], ['截断 JPEG', jpeg.subarray(0, 100)]]) {
    let threw = false;
    try {
      await sharp(bytes).metadata();
    } catch {
      threw = true;
    }
    check(`${label}抛错而非崩溃`, threw);
  }

  // 6) the isolation invariant that matters
  check('全程本进程始终无 libvips', mapsHasVips() === false);

  const status = typeof sharp.__dshWorkerStatus === 'function' ? sharp.__dshWorkerStatus() : null;
  if (status) console.log(`  worker pid=${status.pid} pending=${status.pending} failures=${status.failures}`);
  if (typeof sharp.destroy === 'function') sharp.destroy();

  console.log(failures === 0 ? '\n✅ 图片链路与隔离均通过' : `\n❌ ${failures} 项失败`);
  process.exit(failures === 0 ? 0 : 1);
})().catch((error) => {
  console.error('❌ 运行失败:', error && error.stack ? error.stack.split('\n').slice(0, 8).join('\n') : error);
  process.exit(1);
});
