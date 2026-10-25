# 任务：重新构建 DeepSeek Harness 桌面端 Linux 发行包（x86_64 + aarch64）并验证

你从未接触过这个项目。以下是你需要的全部信息。**先读完再动手。**

---

## 0. 背景

DeepSeek 官方只发布 macOS / Windows 版桌面客户端。本项目把官方 **macOS dmg** 里的
应用载荷重新打包成 Linux 安装包。官方代码里的 Linux 分支基本是空实现，
因此移植 = **用补丁补齐那些空分支** + 替换平台相关的原生模块与运行时。

**上游版本**：`0.2.1-rc.2`（dmg 内目录名 `DeepSeek Harness 0.2.1-rc.2-arm64`）

**你手上已具备**：官方 macOS dmg（已下载好）、可联网的 Linux 环境、本补丁仓库地址。
**你需要做**：拉仓库 → 解包 dmg → 换平台包 → 打补丁 → 构建 → 逐包验证。

---

## 1. 交付物

| # | 交付物 | 验收标准 |
|---|---|---|
| 1 | 拉取仓库 | 本地有 `patches/`、`build-packages.sh`、`trim-app-tree.sh`、`swap-native-linux.sh` |
| 2 | 构建 **x86_64** | AppImage + `.deb`（bundled）+ `.pkg.tar.zst` + `.rpm` |
| 3 | 构建 **aarch64** | 同上 4 种格式 |
| 4 | 验证每个包 | 解包后能实际启动；**且 Agent 预设四个模式均无「加载失败」**（见 5.3） |
| 5 | 校验和 | 生成 `SHA256SUMS.txt`，`sha256sum -c` 全过 |

**只构建 `bundled.deb`**。不要构建 `system.deb`（Debian/Ubuntu 无 electron 包，装不上）。

---

## 2. 仓库

```
https://github.com/macOS-Terminal/deepseek-harness-desktop-linux
```

**务必拉到最新 `main`**（含 `4ad751f` 及其后的提交）。本次重建的核心修复就在那里。

```
patches/                          补丁脚本（核心资产）
  patch-main.py                   平台准入 / 资源根 / 托盘 / 窗口 IPC（14 项）
  patch-titlebar.py               隐藏原生标题栏
  patch-mac-chrome.py             macOS 风格装饰（自动串联下面三个）
  patch-kde-material.py           KDE 不透明回退 + X11 模糊请求
  patch-fullscreen-reveal.py      全屏交通灯与控件
  patch-linux-identity.py         Wayland 应用标识
  patch-fingerprint.py            放宽 V8 指纹门禁（按 ELF 符号定位）
swap-native-linux.sh              平台包替换（x64/arm64）+ 缺失包自动补装
trim-app-tree.sh                  裁剪运行时冗余 + 静态 import 完整性自检
build-packages.sh                 全格式打包入口
install-image-worker.sh           Sharp 进程隔离
verify-launch-x64.sh              逐格式解包并实测启动
image-worker-src/                 Sharp 隔离方案（3 个 .cjs）
icons/                            桌面项 + 全套图标
docs/CHANGELOG.md                 每个修复的根因与实测数据
docs/AGENT_PROMPT.md              上一版提示词（含更多背景）
README.zh.md                      完整中文教程 ← **先读这个**
```

---

## 3. 前置依赖

### 3.1 解包已就位的 dmg
```bash
7z x -oothers/dmg others/dsh-latest-macos-arm64.dmg
```
解出的目录名带版本号，如 `DeepSeek Harness 0.2.1-rc.2-arm64`。
若实际版本不同，**以实际为准**并同步调整下面各处版本号。

### 3.2 Electron **44.7.0**
```
dl/electron-44.7.0-linux-x64.zip
dl/electron-44.7.0-linux-arm64.zip
```
> ⚠️ 必须 ≥ 44.4.5。Electron 44.0.0 有 Linux 托盘回归缺陷。0.2.1-rc.2 内置 44.7.0。

### 3.3 Node 与 Python
```
dl/node-v24.21.0-linux-x64.tar.xz      dl/node-v24.21.0-linux-arm64.tar.xz
dl/python-3.12.14-x64.tar.gz           dl/python-3.12.14-arm64.tar.gz
```
> ⚠️ Python **必须**用 python-build-standalone 的 `install_only_stripped` 变体。
> 普通版再手工 `strip` 会破坏段布局，运行期报 `symbol lookup error`。

### 3.4 Linux 原生模块（两架构各一套，放 `dl/linux-x64` / `dl/linux-arm64`）

版本必须与 0.2.1-rc.2 对齐：

| npm 包 | 版本 |
|---|---|
| `@img/sharp-linux-{x64,arm64}` | 0.35.5 |
| `@img/sharp-libvips-linux-{x64,arm64}` | 1.3.4 |
| `@koromix/koffi-linux-{x64,arm64}` | 3.1.1 |
| `sherpa-onnx-linux-{x64,arm64}` | 1.13.8 |
| `node-addon-require-builtin-linux-{x64,arm64}-gnu` | 0.1.9 |
| `@vscode/ripgrep-linux-{x64,arm64}` | 1.18.0 |
| `@deepseek-ai/node-addon-system-linux-{x64,arm64}` | 0.1.2 |
| `node-pty`（只取 `prebuilds/linux-*`） | 1.2.0-beta.15 |
| `@deepseek-ai/libreoffice-kit-wasm` | 0.1.5（两架构共用，46 MB） |
| `@deepseek-ai/dsh-sandbox-windows-acl` | **跟随 `dsh-sandbox-local` 的版本**（脚本自动补装，见 4.3） |

取包：`npm pack <pkg>@<ver>`，或
`curl -L https://registry.npmjs.org/<pkg>/-/<name>-<ver>.tgz -o x.tgz`。
`swap-native-linux.sh` 期望特定文件名（见脚本内 `install_tgz` 调用处），不符时改名即可。

### 3.5 打包工具
`mksquashfs`（squashfs-tools）、AppImage type2 runtime（`tools/runtime-x86_64`、`tools/runtime-aarch64`）、
`rpmbuild`、`bsdtar`、`fakeroot`、`ar`、**`zstd`**。

---

## 4. 构建流程

### 4.1 铺 Electron 骨架
```bash
cd out-x64
unzip -oq ../dl/electron-44.7.0-linux-x64.zip
mv electron deepseek-harness
rm -f resources/default_app.asar
```

### 4.2 展开 dmg 里的 app.asar 到 `resources/app`
asar 格式：头 16 字节，`[12:16]` 是 JSON 头长度，
`data_start = 8 + uint32([4:8])`，按 `offset`/`size` 切片；
`unpacked: true` 的条目从 `app.asar.unpacked/` 取。

> ⚠️ **必须展开成目录，不要保留 `app.asar`。** Host 进程用 standalone Node 启动，
> **读不了 asar**，会报 `Cannot find module '.../app.asar/dsh/node_modules/...'`。

### 4.3 替换原生模块
```bash
# <app-tree> 指含 dsh/node_modules 的那层：
#   .../Resources/app.asar.unpacked/dsh
./swap-native-linux.sh <app-tree> dl/linux-x64   x64
./swap-native-linux.sh <app-tree> dl/linux-arm64 arm64
```
脚本会：删 darwin 包 → 装 Linux 包 → 清理 `*:com.apple.provenance` →
**自动补装缺失的 `dsh-sandbox-windows-acl`** → 校验 `.node`/`.so` 架构（不符即非零退出）。

> **为什么「Linux 用不上的包」不能删**：
> `@deepseek-ai/dsh-sandbox-windows-acl` 是 Windows 专用的 ACL 沙箱，但
> `dsh-sandbox-local` 在**顶层静态 import** 它。ESM 静态 import 无法按平台条件化，
> Linux 上同样求值 —— 删掉它会让整个 `dsh-sandbox-local` 插件加载失败，
> 导致 `sandbox`/`shell`/`ptcRuntime`/`workflowEngine` 四个服务缺失，
> 表现为 **Agent 预设的标准/PTC/创造三个模式显示「加载失败」**，只有极简模式正常。
> `trim-app-tree.sh` 末尾的**静态 import 完整性自检**会拦截此类误删，
> 出现 `✗ … 静态 import 目标缺失` 时**必须修好再继续**。

其余装配要点：
- `resources/runtime/` 放 `bin/node`、`cli/`、`office-skills/`、`versions.json`
- `resources/runtime/primary-runtime/dependencies/` 放 `node/`、`python/`、`pnpm/`
  > ⚠️ **0.2.1 起 pnpm 在 `dependencies/pnpm/`**（0.2.0 时在 `runtime/pnpm/`）。
  > `patch-main.py` 已同时支持两种布局。
- Python 站点包交叉安装：
  ```bash
  pip install --target <site-packages> \
    --platform manylinux_2_28_x86_64 --platform manylinux_2_27_x86_64 \
    --python-version 3.12 --implementation cp --only-binary=:all: \
    numpy==2.3.5 pandas==3.0.1 Pillow==12.3.0 lxml==6.1.3 \
    python-docx==1.2.0 python-pptx==1.0.2 openpyxl==3.1.5 XlsxWriter==3.2.9 \
    python-dateutil==2.9.0.post0 six==1.17.0 tzdata==2025.2 \
    typing_extensions==4.16.0 et_xmlfile==2.0.0
  ```
  arm64 换 `manylinux_2_28_aarch64` / `manylinux_2_27_aarch64`
- 修正 `runtime/primary-runtime/runtime.json` 的 `platform`/`arch` 为 `linux` / `x64|arm64`

### 4.4 打补丁 —— **顺序不可颠倒**
```bash
python3 patches/patch-main.py       out-x64/resources/app/lib/main.js
python3 patches/patch-titlebar.py   out-x64/resources/app/lib/main.js
python3 patches/patch-mac-chrome.py out-x64/resources/app
python3 patches/patch-fingerprint.py \
  out-x64/resources/app/dsh/node_modules/node-addon-require-builtin-linux-x64-gnu/prebuilt/linux-x64-gnu-napi-v9.node
```
arm64 同理，把 `x64` 换成 `arm64`。

> ③（`patch-mac-chrome.py`）替换的是 ② 产生的 `titleBarOverlay` 分支，顺序不能反。
> 反了会报 `未匹配`（不致命，但窗口装饰不生效）。
>
> ④ 的指纹补丁**按 ELF 符号定位**（`MatchesERKNS2_19ElectronProfileSpecE`）。
> 旧实现用硬编码偏移 + 序言扫描，在新 addon 上命中 233 个无关函数并**打错地址**、
> 静默损坏二进制却报成功。现版本找不到唯一符号就**拒绝打补丁**。不要改回扫描逻辑。

不打补丁的后果：

| 补丁 | 缺失时 |
|---|---|
| `patch-main.py` | 启动即 `desktop policy: unsupported platform` |
| `patch-titlebar.py` | 出现系统原生标题栏 |
| `patch-mac-chrome.py` | 无交通灯、无毛玻璃、全屏布局错乱 |
| `patch-fingerprint.py` | `unsupported Electron runtime fingerprint`，Host 起不来 |

### 4.5 Sharp 进程隔离
```bash
./install-image-worker.sh out-x64 x64
```
> libvips 在 Electron 进程内会 SIGSEGV，JS 层无法捕获，整个桌面端崩溃。
> 方案是转发到独立 Node worker。打包前**务必删除** `node_modules/.sharp-native-backup/`。

### 4.6 打包
```bash
./build-packages.sh x64
./build-packages.sh arm64
```
产物在 `dist/`。脚本会自动调用 `trim-app-tree.sh`（含静态 import 自检）与
`swap-native-linux.sh` 的逻辑。

---

## 5. 验证（必做，不可跳过）

### 5.1 自动验证
```bash
./verify-launch-x64.sh
cd dist && sha256sum -c SHA256SUMS.txt
```

### 5.2 逐包核验

| 检查 | 方法 | 期望 |
|---|---|---|
| 能启动 | 解包后跑，`--ozone-platform=x11 --disable-gpu`（无显示用 `xvfb-run -a`） | 日志出现 `dsh web: http://127.0.0.1:19387/` |
| **静态 import 完整** | 打包时 `trim-app-tree.sh` 的自检输出 | `✓ 107 个静态 import 目标全部可解析` |
| 补丁生效 | 查 `resources/app/lib/main.js` | 含 `desktopResourcesRoot`、`desktopIsPackaged`、`linux-window-control` |
| 指纹已打 | 查 addon 的 `Matches` 处字节 | x64 `b8010000`、arm64 `20008052` |
| Sharp 隔离 | `ELECTRON_RUN_AS_NODE=1 <app> image-worker-src/verify-image-worker.cjs` | `✅ 图片链路与隔离均通过` |
| deb 可解析 | `ar t <deb>` | 含 `data.tar.zst`、`control.tar.zst` |
| rpm 可读 | `rpm -qp --qf '%{PAYLOADCOMPRESSOR}\n' <rpm>` | 输出 `zstd` |
| pkg 可读 | `bsdtar -tf <pkg.tar.zst> \| head` | 无错误 |
| AppImage | `./<AppImage> --appimage-extract` | 能解出 squashfs-root |
| 架构正确 | `file <binary>` | x64 包无 aarch64 残留，反之亦然 |

### 5.3 **Agent 预设必须可用（本次重点回归项）**

这是上一版包的**实际缺陷**：Agent 预设的标准/PTC/创造三个模式显示「加载失败」。
验证方法（在与桌面端相同的 app 目录上跑）：

```bash
cat > /tmp/roster.mjs <<'EOF'
import { createRequire } from 'node:module'
// argv[2] = app 里的 dsh 目录（含 node_modules/@deepseek-ai/dsh）
// argv[3] = profile 目录（如 ~/.dsh/profiles/desktop）
const dshDir = process.argv[2]
const projectDir = process.argv[3]
const require = createRequire(dshDir + '/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js')
const { runProfile } = require('@deepseek-ai/dsh/profile-boot')
const boot = require('@deepseek-ai/dsh-app-boot')
const profile = boot.loadProfileDirectory('dsh', projectDir, dshDir + '/node_modules/@deepseek-ai/dsh/package.json')
const env = boot.loadLayeredEnv('dsh', projectDir)
const application = await runProfile({
  environment: env, profile: 'desktop',
  resolvedProfile: { profile, installAnchor: dshDir + '/node_modules/@deepseek-ai/dsh/package.json' },
  patchFiles: [], args: ['--no-open', '--port', '0'],
})
await new Promise(r => setTimeout(r, 8000))
// 注意：服务在 application.ctx 上，application.get 不存在
const reg = application?.ctx?.get?.('agentPresets')
if (!reg) { console.error('registry 不可用'); process.exit(1) }
for (const p of await reg.list()) console.log(`  ${p.id}: broken=${p.broken ?? '(无)'}`)
process.exit(0)
EOF

# 解包后的包：<deb解包根>/usr/lib/deepseek-harness/resources/app/dsh
node /tmp/roster.mjs \
  <deb解包根>/usr/lib/deepseek-harness/resources/app/dsh \
  ~/.dsh/profiles/desktop
```

> ⚠️ 参数是 **app 里的 `dsh` 目录**（不是 app 目录）。传错会报
> `ENOENT: .../app/node_modules/@deepseek-ai/dsh`。
> profile 目录若不存在，用任意含 `package.json` 的空目录也可以。

期望输出（**四个都必须是 `(无)`**）：
```
  standard: broken=(无)
  ptc: broken=(无)
  minimal: broken=(无)
  cordis: broken=(无)
```

若出现 `broken=… waiting for shell` 之类，说明 `dsh-sandbox-windows-acl` 缺失或版本不匹配：
```bash
ls <app的dsh目录>/node_modules/@deepseek-ai/dsh-sandbox-windows-acl
# 版本应与 dsh-sandbox-local 一致
```
修复：跑一次 `./swap-native-linux.sh <app-tree> dl/linux-x64 x64`（会自动补装正确版本）。

### 5.4 ARM64（本机若为 x86_64）
```bash
qemu-aarch64-static -L <sysroot> <arm64-node> -e "console.log(process.arch)"   # 期望 arm64
```
> sysroot 需 `libc6`、`libstdc++6`、`libgcc-s1`、`zlib1g` 的 arm64 包；
> 注意 `lib/ld-linux-aarch64.so.1` 可能是**断链**，需换成真实文件。

---

## 6. 压缩设置（本次重点）

**四种格式全部使用 zstd**，由 `build-packages.sh` 顶部常量统一控制：

```bash
ZSTD_LEVEL=19                 # 与 xz -9e 体积接近
ZSTD_OPTS="-19 -T0 --long=27" # --long 提升大载荷压缩率
```

| 格式 | 实现 |
|---|---|
| `.deb` | `data.tar.zst` + `control.tar.zst`（ar 归档） |
| `.rpm` | `_binary_payload w19.zstdio` |
| `.pkg.tar.zst` | `tar \| zstd $ZSTD_OPTS` |
| `.AppImage` | `mksquashfs -comp zstd -Xcompression-level 19 -Xdict-size 100% -b 1M` |

### 最低系统要求（已逐条查证）

| 格式 | 要求 | 不支持 |
|---|---|---|
| deb | Ubuntu **21.04+**（dpkg 1.20.9ubuntu1+）<br>Debian **12+**（dpkg 1.21.18+） | Debian 11 及更早、Ubuntu 20.04 及更早 |
| rpm | `rpm >= 4.14`（Fedora 31+ / openSUSE Leap 15.3+） | 更早版本报 `Unsupported payload compressor` |
| pkg.tar.zst | pacman 5.x+ | — |
| AppImage | squashfs-tools 4.4+ / 主流内核 | — |

> ⚠️ **Ubuntu 与 Debian 的 zstd 支持不同步，不能按上游 dpkg 版本号统一判断。**
> 上游 Debian 在 **1.21.18** 才引入（`libdpkg: Add zstd support for .deb archives.
> Closes: #892664`），而 Ubuntu **21.04 起就有自己的 patch**（`dpkg 1.20.9ubuntu1`
> hirsute：`Add Zstd compression and decompression support for binary packages`），
> 并在 `1.21.1ubuntu1` 把默认压缩从 xz 改成 zstd（LP: #1923845）。
> 所以 Ubuntu 22.04（dpkg 1.21.1）**可以**装，Debian 11（1.20.13）**不行**。
> 请在交付说明里写明这一点。

---

## 7. 已知坑

| 现象 | 原因与处理 |
|---|---|
| **Agent 预设三个模式显示「加载失败」** | `dsh-sandbox-windows-acl` 缺失（被静态 import 依赖）。见 5.3 |
| `EADDRINUSE 127.0.0.1:19387` | 已有实例在跑（固定端口），先关掉 |
| 一发图片整个应用崩 | Sharp 替身没装好，检查 `resources/image-worker/` |
| 系统 Electron 下白屏 | 缺 `DSH_DESKTOP_RESOURCES_DIR` / `DSH_DESKTOP_FORCE_PACKAGED` |
| 打包后二进制无执行权限 | 工作区在 NTFS；`normalize_modes` 必须保留 |
| Python `symbol lookup error` | 用了被 strip 的 python-build-standalone，改用 `install_only_stripped` |
| `dpkg -i` 报 control 格式错误 | 可选字段被展开成空行（空行=段落分隔）；已在脚本里修 |
| 全屏时交通灯不隐藏 | 平铺合成器（niri/sway）不向 Electron 报全屏；`syncTilingFullscreen` 必须保留 |
| 折叠后无法展开侧栏 | `backdrop-filter` 不能放在侧栏元素上（会成为 fixed 子元素的包含块），必须用独立层 |
| 误启动真实应用弹错误框 | Electron 优先加载二进制旁的 `resources/app`；测试请用系统 Electron 跑独立小程序 |
| `ar x` 失败 | 工作区在 NTFS 时 ar 行为异常，先 `cp` 到 tmpfs 操作 |
| **`Cannot find module '.../app.asar/...'`** | 包是用 asar 布局打的。Host 用 standalone Node 启动，**读不了 asar**。必须用平铺布局 `resources/app/` |
| `trim-app-tree.sh` 报静态 import 缺失 | 裁掉了被顶层 import 的包。**修好再继续**，不要跳过 |

---

## 8. 硬性约束

1. **不要修改 `patches/` 下的脚本**，除非发现明确 bug —— 它们逐条实测过。
2. **不要构建 `system.deb`**。
3. **不要降级 Electron**。
4. **不要裁剪任何被顶层静态 import 的包**（见 4.3 的说明与自检）。
5. **不要为了让测试通过而放宽断言。** 验证不过就如实报告。
6. 四种格式**必须都用 zstd**（第 6 节）。
7. 磁盘：完整构建约需 15 GB 空闲。
8. 打包前删除 `node_modules/.sharp-native-backup/`，否则白占体积。

---

## 9. 汇报格式

```
## 构建结果
| 架构 | AppImage | bundled.deb | pkg.tar.zst | rpm |
|---|---|---|---|---|
| x86_64 | 大小 | 大小 | 大小 | 大小 |
| aarch64 | 大小 | 大小 | 大小 | 大小 |

## 体积对比
（与上一版 xz/gzip 相比，各格式减少多少）

## 验证证据
（粘贴真实命令输出，不要转述）
- x64 启动实测：<输出>
- **Agent 预设 roster：<四个模式的 broken 状态，必须全是 (无)>**
- 静态 import 自检：<输出>
- sha256sum -c：<通过数/总数>
- Sharp 隔离：<输出>
- deb 结构：ar t 的结果
- rpm 压缩器：rpm -qp 的输出
- 指纹字节：Matches 处 hex

## 兼容性说明
（明确写出 zstd deb 的发行版支持范围：Ubuntu 21.04+ / Debian 12+，
  并说明 Ubuntu 与 Debian 引入版本不同步）

## 未能验证的部分
（如实列出；不要用"应该没问题"代替证据）

## 遇到的问题与处理
```
