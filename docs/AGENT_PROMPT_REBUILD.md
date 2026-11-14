# 任务：重建 DeepSeek Harness Linux 发行包（x86_64 + aarch64）并验证

你从未接触过这个项目。以下命令以**当前仓库脚本**为准。**先读完再动手，不要凭旧笔记改写脚本。**

---

## 0. 当前基线

DeepSeek 官方只发布 macOS / Windows 桌面端。本项目把 macOS dmg 中的应用载荷重打包为
Linux 安装包：补齐 Linux 分支、替换原生模块与运行时，再逐一验证。

| 项目 | 本次基线 |
|---|---|
| 上游应用 | `0.2.2-rc.3`（dmg 目录 `DeepSeek Harness 0.2.2-rc.3-arm64`） |
| 内置 Electron（AppImage/deb/rpm） | **44.7.0**（取自 dmg，与上游一致） |
| pkg.tar.zst 的 Electron | 系统提供，启动器支持 **39–45**，优先最高版本 |
| Node / Python / pnpm | **24.21.0 / 3.12.14 / 11.28.5** |
| 移植修复级别 | **3.7.1**：netlink 退避 + Sharp 强制隔离 + rc.3 适配 |
| 最低仓库提交 | 必须包含 3.7.1；实际构建拉取当时最新 `main` 并核对 `git log` |

> 不要擅自升级 Node、pnpm、Python。`docs/COMPAT-TOOLCHAIN.md` 记录了升级实测及受阻原因。
> 应用包内置 Electron 44.7.0；45.2.3 仅用于 Arch 的 `electron45` 运行时包，二者不要混用。

---

## 1. 交付物

| # | 交付物 | 验收标准 |
|---|---|---|
| 1 | x86_64 应用包 | AppImage + bundled.deb + pkg.tar.zst + rpm |
| 2 | aarch64 应用包 | 同上 4 种格式 |
| 3 | 启动验证 | x64 四格式实际启动，日志均出现 `dsh web:`；Agent 四预设全部 `broken=(无)` |
| 4 | 图片回归 | Sharp 隔离重复安装两轮通过；大图/动画/并发/坏图均不使主进程崩溃 |
| 5 | netlink 回归 | 退避实测 `1,2,4,8,8 ms`；普通 socket 不延迟；包内守卫与启动入口齐全 |
| 6 | 结构与架构 | 四格式均为 zstd；x64 无 arm64 残留，反之亦然 |
| 7 | 校验和 | 生成 `SHA256SUMS.txt`，`sha256sum -c` 全过 |

**只构建 bundled.deb，不构建 system.deb。**

Arch 用户若需要系统运行时，可同时提供已有的 `electron45-45.2.3-1-{x86_64,aarch64}.pkg.tar.zst`。
该运行时包与本轮应用修复无关时可复用，不必每次重复构建。

---

## 2. 拉取仓库与核对文件

```bash
git clone https://github.com/macOS-Terminal/deepseek-harness-desktop-linux.git
cd deepseek-harness-desktop-linux
git checkout main
git pull --ff-only origin main
git log -1 --oneline
```

必须看到以下路径；缺失说明仓库或工作区不对：

```text
patches/                       Linux JS 与指纹补丁
scripts/assemble-tree.sh       装配应用树
scripts/apply-patches.sh       按固定顺序应用补丁
scripts/swap-electron.sh       保留 app/runtime，只换 Electron 骨架
scripts/install-netlink-guard.sh
netlink-guard/netlink_guard.c
build-packages.sh              四格式打包
trim-app-tree.sh               裁剪与静态 import 自检
install-image-worker.sh        Sharp 进程隔离
verify-launch-x64.sh           四格式实际启动（经包内启动器）
tests/test-netlink-guard.sh    netlink 退避与入口测试
tests/test-image-worker.sh     Sharp 幂等安装与图片全链路测试
docs/NETLINK-GUARD.md          netlink 根因与验证说明
docs/CHANGELOG.md              历史修复记录
```

---

## 3. 准备输入与构建依赖

### 3.1 官方 dmg

```bash
mkdir -p others
# 将上游 dmg 放为 others/dsh-latest-macos-arm64.dmg
7z x -oothers/dmg others/dsh-latest-macos-arm64.dmg
```

若 7z 因 Apple LZFSE 块失败，使用 `scripts/dmg-extract.py`（需要 `/usr/lib/liblzfse.so`）
先转成裸 HFS+ 镜像，再用 7z 解包。不要用不完整的解包结果继续。

### 3.2 Electron

应用包使用 dmg 内置的 **44.7.0**，由 `assemble-tree.sh` 自动铺好，无需额外下载。

只有构建 Arch 的 `electron45` 运行时包时才需要官方 zip：

```text
dl45/electron-v45.2.3-linux-x64.zip
dl45/electron-v45.2.3-linux-arm64.zip
```

### 3.3 Node、Python 与原生模块

```text
dl/node-v24.21.0-linux-x64.tar.xz
dl/node-v24.21.0-linux-arm64.tar.xz
dl/python-3.12.14-x64.tar.gz
dl/python-3.12.14-arm64.tar.gz
```

Python 必须用 python-build-standalone 的 **`install_only_stripped`** 变体。
普通版再手工 `strip` 会破坏段布局，运行期报 `symbol lookup error`。

两架构原生模块分别放 `dl/linux-x64/`、`dl/linux-arm64/`：

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
| `@deepseek-ai/libreoffice-kit-wasm` | 0.1.5（两架构共用） |
| `@deepseek-ai/dsh-sandbox-windows-acl` | 跟随 `dsh-sandbox-local`，本版为 0.2.2-rc.3 |

取包用 `npm pack <pkg>@<ver>` 或 registry tgz。文件名以 `swap-native-linux.sh`
里的 `install_tgz` 调用为准。

### 3.4 构建工具

- `7z`、`unzip`、`python3`、`pip`
- `mksquashfs`、AppImage type2 runtime（`tools/runtime-x86_64`、`tools/runtime-aarch64`）
- `rpmbuild`、`bsdtar`、`fakeroot`、`ar`、`zstd`
- `xvfb-run`（无显示环境启动验证）
- **C 编译器**：x64 用 `cc`；x86_64 主机交叉 arm64 默认用
  `aarch64-linux-gnu-gcc`，也可用 `CC_X64` / `CC_ARM64` 指定

预留至少 **15 GB** 临时空间；tmpfs 构建还需注意 RAM 上限。

---

## 4. 构建流程

### 4.1 展开 app.asar 为平铺目录

```bash
# 目录名带版本号，按实际解出的名字填；也可交给 assemble-tree.sh 自动探测
RES="others/dmg/DeepSeek Harness 0.2.2-rc.3-arm64/DeepSeek Harness.app/Contents/Resources"
rm -rf app-new
python3 scripts/extract-asar.py "$RES/app.asar" app-new
```

`unpacked: true` 的文件会由脚本从 `app.asar.unpacked/` 取。

> **不要保留 app.asar 布局。** Host 用 standalone Node 启动，读不了 asar；
> 必须是 `resources/app/` 平铺目录，否则出现 `Cannot find module .../app.asar/...`。

### 4.2 装配双架构应用树

```bash
scripts/assemble-tree.sh x64
scripts/assemble-tree.sh arm64
```

脚本会铺骨架、复制 app、装配 Node/Python/pnpm、交叉安装 Python 站点包、
替换原生模块、修正 `runtime.json` 平台字段，并安装 netlink 守卫。

rc.3 相关注意：

- 上游目录名随版本变化，脚本会自动取 `others/dmg` 下最新的一个；
  需要指定时用 `DSH_APP=<.../Contents/Resources>` 覆盖。
- `runtime/office-skills` 自 rc.2 起被上游移除，脚本已改为存在才复制。
- 托盘图标 `resources/tray.png` 由脚本从 `icons/32x32/` 补齐并断言非空。

Python 站点包使用 manylinux 交叉安装；arm64 使用
`manylinux_2_28_aarch64` / `manylinux_2_27_aarch64`，不要用已经过时的 `manylinux2014` 标签。

### 4.3 Electron 版本

`assemble-tree.sh` 使用 dmg 内置的 **44.7.0** 铺骨架，产物即用该版本，**不要替换**。

`electron45-45.2.3` 是给 `pkg.tar.zst`（系统 Electron 变体）用的独立运行时包，用
`scripts/build-electron-pkg.sh` 生成，与本轮应用包无关；两者不要混用。

如需单独验证其他 Electron 版本能否启动，可用 `scripts/swap-electron.sh`
在**临时副本**上替换骨架，验证后丢弃，不要用于出包：

```bash
cp -al out-x64 /tmp/tree-ver
scripts/swap-electron.sh /tmp/tree-ver dl45/electron-v45.2.3-linux-x64.zip x64
```

该脚本保留 `resources/app`、`resources/runtime` 和托盘图标，只替换 Electron 骨架。

### 4.4 应用补丁——顺序不可颠倒

```bash
scripts/apply-patches.sh out-x64 x64
scripts/apply-patches.sh out-arm64 arm64
```

固定顺序：

1. `patch-main.py`：平台准入、资源根、打包态、托盘、关窗等；
2. `patch-titlebar.py`：生成后续装饰补丁需要的分支；
3. `patch-mac-chrome.py`：窗口装饰，并串联 KDE、全屏、Wayland 标识补丁；
4. `patch-fingerprint.py`：按 ELF 符号定位 `MatchesERKNS2_19ElectronProfileSpecE`。

③ 替换的是 ② 产生的 `titleBarOverlay` 分支，不能交换。
④ 找不到唯一符号必须拒绝继续，**不要恢复旧的硬编码偏移或序言扫描**。

`swap-native-linux.sh` 会自动补装/纠正 `dsh-sandbox-windows-acl`。
它虽为 Windows ACL 包，却被 `dsh-sandbox-local` 顶层静态 import；删掉会导致
sandbox/shell/ptcRuntime/workflowEngine 服务缺失，标准/PTC/创造预设显示「加载失败」。

### 4.5 Sharp 进程隔离

```bash
./install-image-worker.sh out-x64 x64
./install-image-worker.sh out-arm64 arm64
rm -rf out-x64/resources/app/dsh/node_modules/.sharp-native-backup
rm -rf out-arm64/resources/app/dsh/node_modules/.sharp-native-backup
```

libvips 在 Electron 进程内会 SIGSEGV，JS 无法捕获，因此必须转发到独立 Node worker。
打包前必须删除备份目录，避免白占体积。

`build-packages.sh` 现在会**强制重新安装** Sharp 隔离并删除备份，漏掉上述手工命令也不能继续出包。
安装脚本可重复执行：第二轮会从备份或 worker 的私有原生闭包恢复，不会把 facade 错当成原生 sharp。
完整回归：

```bash
./tests/test-image-worker.sh out-x64 x64
```

该测试连续安装两次，再检查 facade 标记、worker 载荷、JPEG/PNG/WebP/GIF、6000×4000 大图、
动画 GIF、并发请求、坏数据与截断 JPEG；主进程必须始终无 libvips。

### 4.6 netlink 收包失败退避守卫

装配脚本已经安装一次；需要显式复核或重建时执行：

```bash
scripts/install-netlink-guard.sh out-x64 x64
scripts/install-netlink-guard.sh out-arm64 arm64
file out-x64/resources/netlink-guard/libdsh-netlink-guard.so
file out-arm64/resources/netlink-guard/libdsh-netlink-guard.so
```

期望分别为 `x86-64` 与 `ARM aarch64`。

Chromium 在 netlink `recv()` 遇到 `EACCES` 后保留 watcher，会无退避重试并刷爆 syslog。
守卫只对 `AF_NETLINK` 的 `EACCES`/`EPERM`/`ENOBUFS` 施加 1、2、4…60 秒退避，
不屏蔽其他错误日志，不影响普通 socket。详见 `docs/NETLINK-GUARD.md`。

`build-packages.sh` 还会从当前源码再构建一次，防止旧 `.so` 残留。

### 4.7 打包

```bash
./build-packages.sh x64
./build-packages.sh arm64
```

产物在 `dist/`。可用 `FORMATS` 与 `DSH_OUT` 做局部验证，例如：

```bash
FORMATS=deb DSH_OUT="$PWD/dist-check" ./build-packages.sh x64
```

但最终交付必须重新确认 `dist/` 中双架构 8 个应用包齐全。
版本号自动读 `resources/runtime/primary-runtime/runtime.json` 的 `desktopVersion`，
可用 `DSH_VER` 显式覆盖，不要在脚本里写死版本。

---

## 5. 验证（全部必做）

### 5.1 自动测试与四格式启动

```bash
./tests/test-image-worker.sh out-x64 x64
./tests/test-netlink-guard.sh
./verify-launch-x64.sh "$PWD/dist"
```

netlink 测试用 seccomp 模拟 `EACCES`，不会写真实 syslog。必须看到：

```text
无守卫：netlink_delays_ms=0,0,0,0,0 ordinary_socket_ms=0
有守卫：netlink_delays_ms=1,2,4,8,8 ordinary_socket_ms=0
禁用后：netlink_delays_ms=0,0,0,0,0 ordinary_socket_ms=0
```

`verify-launch-x64.sh` 对 deb/rpm/pkg 使用**包内启动器**，AppImage 无 FUSE 时解包后运行 `AppRun`，
因此也覆盖守卫的 `LD_PRELOAD`。四格式必须全部出现 `dsh web:`。
端口可能是 19387，也可能是动态端口，不要写死匹配完整 URL。

### 5.2 逐包检查

| 检查 | 方法 | 期望 |
|---|---|---|
| 启动 | 上述 `verify-launch-x64.sh` | `4/4 通过` |
| 补丁痕迹 | 查 `resources/app/lib/main.js` | 含 `desktopResourcesRoot`、`desktopIsPackaged`、`linux-window-control` |
| 静态 import | 在构建树上运行 `bash trim-app-tree.sh out-x64` | 全部可解析；数量随上游变化，以自检输出为准 |
| 托盘 | 查 `resources/tray.png` 并用 `nativeImage` 读取 | 文件存在、非空、32×32 |
| 指纹 | 查 addon `Matches` 处字节 | x64 `b8010000`；arm64 `20008052` |
| Sharp | `./tests/test-image-worker.sh out-x64 x64` | 两轮幂等安装均通过；大图/动画/并发/坏图通过；主进程无 libvips |
| netlink 退避 | `tests/test-netlink-guard.sh` | `1,2,4,8,8 ms`；普通 socket 0ms |
| 守卫文件 | 解包查 `resources/netlink-guard/libdsh-netlink-guard.so` | 存在且架构正确 |
| 守卫入口 | 查 AppRun 与 `/usr/bin/deepseek-harness` | 含正确 `LD_PRELOAD`；不得绕过启动器验证 |
| deb | `ar t <deb>` | `data.tar.zst`、`control.tar.zst` |
| rpm | `rpm -qp --qf '%{PAYLOADCOMPRESSOR}\n' <rpm>` | `zstd` |
| pkg | `bsdtar -tf <pkg.tar.zst>` | 正常读取；`.PKGINFO` 无 `libuuid` / `conflicts` 错误键 |
| AppImage | `./<AppImage> --appimage-extract` | 能解出 squashfs-root |
| 架构 | `file` 检查 ELF | x64 包无 aarch64 残留，反之亦然 |

Arch pkg 还需在真实安装布局验证：

```bash
dsh --version
# 期望 0.2.2-rc.3
```

### 5.3 Agent 预设 roster——使用隔离 profile

不要用测试过程写入真实 `~/.dsh/profiles/`。先创建脚本：

```bash
cat > /tmp/roster.mjs <<'EOF'
import { createRequire } from 'node:module'
const dshDir = process.argv[2]       // app 内的 dsh 目录，不是 app 目录
const projectDir = process.argv[3]   // 隔离的临时 profile 目录
const require = createRequire(dshDir + '/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js')
const { runProfile } = require('@deepseek-ai/dsh/profile-boot')
const boot = require('@deepseek-ai/dsh-app-boot')
const installAnchor = dshDir + '/node_modules/@deepseek-ai/dsh/package.json'
const profile = boot.loadProfileDirectory('dsh', projectDir, installAnchor)
const env = boot.loadLayeredEnv('dsh', projectDir)
const application = await runProfile({
  environment: env,
  profile: 'desktop',
  resolvedProfile: { profile, installAnchor },
  patchFiles: [],
  args: ['--no-open', '--port', '0'],
})
await new Promise(resolve => setTimeout(resolve, 8000))
const registry = application?.ctx?.get?.('agentPresets')
if (!registry) { console.error('agentPresets registry 不可用'); process.exit(1) }
for (const preset of await registry.list()) {
  console.log(`  ${preset.id}: broken=${preset.broken ?? '(无)'}`)
}
process.exit(0)
EOF
```

在解包后的 x64 应用树上运行（`ROOT` 换成实际解包根）：

```bash
ROOT=/path/to/unpacked-x64
APP="$ROOT/usr/lib/deepseek-harness/resources/app"
NODE="$ROOT/usr/lib/deepseek-harness/resources/runtime/primary-runtime/dependencies/node/bin/node"
rm -rf /tmp/dsh-roster
mkdir -p /tmp/dsh-roster/profile
cat > /tmp/dsh-roster/profile/package.json <<'JSON'
{"name":"dsh-roster","private":true,"dsh":{"profile":{"bundles":["@deepseek-ai/dsh-base","@deepseek-ai/dsh-web-app"]}}}
JSON
HOME=/tmp/dsh-roster DSH_HOME=/tmp/dsh-roster/.dsh \
  "$NODE" /tmp/roster.mjs "$APP/dsh" /tmp/dsh-roster/profile
```

`@deepseek-ai/dsh-base` 与 `@deepseek-ai/dsh-web-app` 两个内置 bundle 不能省略；
只写空的 `package.json` 会导致 `agentPresets registry 不可用`。

必须得到：

```text
  standard: broken=(无)
  ptc: broken=(无)
  minimal: broken=(无)
  cordis: broken=(无)
```

telemetry 的 ValidationError 若不影响上述四项，作为已知噪声单独记录，不要掩盖真实服务缺失。
若出现 `waiting for shell` 等，检查 `dsh-sandbox-windows-acl` 是否存在、版本是否等于
`dsh-sandbox-local`。修复后重跑，不得放宽断言。

完成后清理：

```bash
rm -rf /tmp/roster.mjs /tmp/dsh-roster
```

### 5.4 ARM64

x86_64 主机至少做交叉架构核验；有 qemu/sysroot 或 arm64 真机时再补启动：

```bash
qemu-aarch64-static -L <sysroot> <arm64-node> -e "console.log(process.arch)"
# 期望 arm64
```

sysroot 需要 arm64 的 `libc6`、`libstdc++6`、`libgcc-s1`、`zlib1g`。
注意 `lib/ld-linux-aarch64.so.1` 可能是断链，需要换成真实文件。
**未实际启动 arm64 就必须在报告里明确写“未验证”，不能用架构检查冒充启动通过。**

### 5.5 校验和

```bash
cd dist
sha256sum *.AppImage *.deb *.rpm *.pkg.tar.zst > SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt
```

---

## 6. 压缩与兼容要求

四种格式全部使用 zstd，由 `build-packages.sh` 顶部常量控制：

```bash
ZSTD_LEVEL=19
ZSTD_OPTS="-19 -T0 --long=27"
```

| 格式 | 当前实现 |
|---|---|
| deb | `data.tar.zst` + `control.tar.zst` |
| rpm | `_binary_payload w19.zstdio` |
| pkg.tar.zst | `tar | zstd $ZSTD_OPTS` |
| AppImage | `mksquashfs -comp zstd -Xcompression-level 19 -b 1M -processors "$(nproc)"` |

> **不要加回 `-Xdict-size`**：当前 squashfs 的 zstd 压缩器不支持它。
> `-processors` 也不能传 0。构建日志必须落盘并检查，不能丢进 `/dev/null`。

| 格式 | 最低要求 |
|---|---|
| deb | Ubuntu **21.04+**；Debian **12+** |
| rpm | rpm >= 4.14（Fedora 31+ / openSUSE Leap 15.3+） |
| pkg.tar.zst | pacman 5.x+ |
| AppImage | 支持 zstd squashfs 的主流内核 |

Ubuntu 21.04 自带 zstd backport；上游 Debian 到 dpkg 1.21.18 才加入。
因此 Ubuntu 22.04 可以安装，Debian 11 不行，不能只看 dpkg 版本号笼统判断。

---

## 7. 已知坑

| 现象 | 处理 |
|---|---|
| Agent 标准/PTC/创造预设「加载失败」 | 检查 `dsh-sandbox-windows-acl`；它是静态依赖，不能裁剪 |
| `Cannot find module .../app.asar/...` | 布局错误，必须展开为 `resources/app/` |
| 托盘存在但图标空白 | `resources/tray.png` 缺失；`nativeImage.createFromPath()` 对缺失文件返回空图而不抛错 |
| 图片一发就崩 | 检查顶层 sharp 是否带 `Out-of-process Sharp facade` 标记、`resources/image-worker/` 是否完整；路径相同不等于 facade |
| `unsupported Electron runtime fingerprint` | 指纹补丁未打或定位失败；不要改回硬编码偏移 |
| 系统 Electron 白屏 | 检查 `DSH_DESKTOP_RESOURCES_DIR` 与 `DSH_DESKTOP_FORCE_PACKAGED` |
| `EADDRINUSE` | 按实际日志端口停掉旧实例；不要假设所有版本都固定 19387 |
| syslog 反复 `Failed to recv from netlink socket` | 确认守卫文件存在并从标准启动器启动；最终验证不得设 `DSH_NETLINK_GUARD=0` |
| AppArmor 拒绝 `recvmsg`/`netlink` | 守卫负责退避，不负责放权；另查内核 audit 记录 |
| `pacman` 报未知 `conflicts` 或无法解决 `libuuid` | 使用当前打包脚本；`conflicts` 是错误键，`libuuid` 应由 `util-linux` 提供 |
| `mksquashfs` 不识别 `-Xdict-size` | 删除该参数；zstd 不需要它 |
| Python `symbol lookup error` | 改用 `install_only_stripped`，不要手工 strip |
| 打包后无执行权限 | 保留 `normalize_modes`；NTFS 上不能依赖 chmod |
| `ar x` 在 NTFS 异常 | 复制到 tmpfs 后操作 |

---

## 8. 硬性约束

1. 不要构建 `system.deb`，不要降级 Electron。
2. 不要擅自修改已实测补丁；发现明确 bug 时必须附根因和回归测试。
3. 不要删除 `dsh-sandbox-windows-acl`、`resources/tray.png` 或任何被静态 import 的包。
4. 不要删除 netlink 守卫或绕过启动器做最终验证；`DSH_NETLINK_GUARD=0` 仅用于诊断。
5. 不要为了让测试通过而放宽断言，不要把超时/工具失败写成“验证通过”。
6. 四种格式必须都用 zstd，不要恢复旧 AppImage 压缩参数。
7. 打包前删除 `.sharp-native-backup/`；不得跳过 Sharp 隔离安装与图片全链路验证。
8. 测试 profile 必须放 `/tmp` 等隔离位置并清理，不要污染真实 `~/.dsh/profiles/`。

---

## 9. 汇报格式

```text
## 构建结果
| 架构 | AppImage | bundled.deb | pkg.tar.zst | rpm |
| x86_64 | 大小 | 大小 | 大小 | 大小 |
| aarch64 | 大小 | 大小 | 大小 | 大小 |

## 基线
- 上游应用版本 / 仓库 commit
- 内置 Electron 版本
- Node / Python / pnpm 版本

## 验证证据（粘贴真实输出，不要转述）
- x64 四格式启动结果
- Agent 四预设 broken 状态
- 静态 import 自检
- netlink 退避原始输出与普通 socket 对照
- 包内 guard 文件与启动器 LD_PRELOAD 检查
- Sharp 隔离
- deb/rpm/pkg/AppImage 结构
- 指纹字节
- sha256sum -c 通过数/总数

## 兼容性说明
- zstd deb 支持范围
- pkg.tar.zst 使用系统 Electron 39–45，其余格式内置 44.7.0

## 未能验证
- 明确列出 arm64 启动、真机桌面环境等未覆盖项

## 遇到的问题与处理
- 根因、改动、验证；不要只写“已修复”
```
