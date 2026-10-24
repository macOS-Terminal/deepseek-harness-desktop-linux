# 任务：为 DeepSeek Harness 桌面端构建 Linux 发行包（x86_64 + aarch64）

你从未接触过这个项目。以下是你需要的全部信息。**先读完再动手。**

---

## 0. 背景

DeepSeek 官方只发布 macOS / Windows 版桌面客户端。本项目的目标是把官方 **macOS dmg**
里的应用载荷重新打包成 **Linux** 安装包。官方代码里的 Linux 分支基本是空实现，
因此移植 = **用补丁补齐那些空分支** + 替换平台相关的原生模块与运行时。

**你手上已具备**：官方 macOS dmg（`0.2.1-rc.2`，已下载好）、可联网的 Linux 环境、
本补丁仓库的地址。
**你需要做**：拉仓库 → 解包 dmg → 换平台包 → 打补丁 → 构建 → 逐包验证。

---

## 1. 交付物

| # | 交付物 | 验收标准 |
|---|---|---|
| 1 | 拉取仓库 | 本地有 `patches/`、`build-packages.sh`、`trim-app-tree.sh`、`swap-native-linux.sh` |
| 2 | 构建 **x86_64** | AppImage + `.deb`（bundled）+ `.pkg.tar.zst` + `.rpm` |
| 3 | 构建 **aarch64** | 同上 4 种格式 |
| 4 | 验证每个包 | 解包后能实际启动，日志出现 `dsh web: http://127.0.0.1:19387/` |
| 5 | 校验和 | 生成 `SHA256SUMS.txt`，`sha256sum -c` 全过 |

**只构建 `bundled.deb`**（内置 Electron），**不要**构建 `system.deb`（脚本已只出 bundled）。

---

## 2. 仓库

```
https://github.com/macOS-Terminal/deepseek-harness-desktop-linux
```

```
patches/                          补丁脚本（核心资产）
  patch-main.py                   平台准入 / 资源根 / 托盘 / 窗口 IPC（14 项）
  patch-titlebar.py               隐藏原生标题栏
  patch-mac-chrome.py             macOS 风格装饰（自动串联下面三个）
  patch-kde-material.py           KDE 不透明回退 + X11 模糊请求
  patch-fullscreen-reveal.py      全屏交通灯与控件
  patch-linux-identity.py         Wayland 应用标识
  patch-fingerprint.py            放宽 V8 指纹门禁（符号定位）
swap-native-linux.sh              平台包替换（x64/arm64）
trim-app-tree.sh                  裁剪运行时冗余
build-packages.sh                 全格式打包入口
install-image-worker.sh           Sharp 进程隔离
verify-launch-x64.sh              逐格式解包并实测启动
image-worker-src/                 Sharp 隔离方案（3 个 .cjs）
icons/                            桌面项 + 全套图标
docs/CHANGELOG.md                 每个修复的根因与实测数据
docs/ARTIFACTS.md                 产物说明 / 安装方式
README.zh.md                      完整中文教程 ← **先读这个**
```

---

## 3. 前置依赖

### 3.1 解包已就位的 dmg
```bash
7z x -oothers/dmg others/dsh-latest-macos-arm64.dmg
```
解出的目录名带版本号，如 `DeepSeek Harness 0.2.1-rc.2-arm64`。
> 若实际版本与文档所写 `0.2.1-rc.2` 不同，以实际为准，并核对下面各处的版本号。

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

> ⚠️ **必须展开成目录，不要保留 `app.asar`**。Host 进程用 standalone Node 启动，
> **读不了 asar**，会报 `Cannot find module '.../app.asar/dsh/node_modules/...'`。

### 4.3 替换原生模块
```bash
# <app-tree> 指含 dsh/node_modules 的那层：
#   .../Resources/app.asar.unpacked/dsh
./swap-native-linux.sh <app-tree> dl/linux-x64   x64
./swap-native-linux.sh <app-tree> dl/linux-arm64 arm64
```
脚本会：删 darwin 包 → 装 Linux 包 → 清理 `*:com.apple.provenance` → 校验 `.node`/`.so` 架构（不符即失败）。

> **必须替换而不是只删**：应用按平台 `require.resolve`，darwin 包永不加载，
> 但**对应 Linux 包必须存在**，否则 require 失败、Host 启动中止。

装配要点：
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

> ③（`patch-mac-chrome.py`）替换的是 ② 产生的 `titleBarOverlay` 分支，所以顺序不能反。
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
产物在 `dist/`。脚本会自动调用 `trim-app-tree.sh` 裁剪冗余（四种格式都生效）。

---

## 5. 压缩设置（本次重点）

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

### ⚠️ 必须向用户声明的兼容性影响

zstd 压缩的 deb 需要 dpkg 支持 `data.tar.zst`。**Ubuntu 与 Debian 的引入版本不同步**：

| 发行版 | dpkg | 能否安装 |
|---|---|---|
| Ubuntu 21.04 (hirsute) 及更新 | 1.20.9ubuntu1+ | ✅ |
| Ubuntu 22.04 LTS (jammy) | 1.21.1ubuntu2 | ✅ |
| Ubuntu 24.04 LTS (noble) | 1.22.6ubuntu6 | ✅ |
| Debian 12 (bookworm) 及更新 | 1.21.22+ | ✅ |
| **Debian 11 (bullseye) 及更早** | 1.20.13 | ❌ |

> ⚠️ **不能按上游 dpkg 版本号统一判断。** 上游 Debian 在 **1.21.18**
> （`libdpkg: Add zstd support for .deb archives. Closes: #892664`）才引入；
> 而 Ubuntu **21.04 起就有自己的 patch**（`dpkg 1.20.9ubuntu1`：
> `Add Zstd compression and decompression support for binary packages`），
> 并在 `1.21.1ubuntu1` 把默认压缩从 xz 改成 zstd（LP: #1923845）。
> 所以 Ubuntu 22.04（dpkg 1.21.1）**可以**装，Debian 11（1.20.13）**不行**。

请在交付说明里明确写出这一点。

---

## 6. 验证（必做，不可跳过）

### 6.1 自动
```bash
./verify-launch-x64.sh
cd dist && sha256sum -c SHA256SUMS.txt
```

### 6.2 逐包核验

| 检查 | 方法 | 期望 |
|---|---|---|
| 能启动 | 解包后跑，`--ozone-platform=x11 --disable-gpu`（无显示用 `xvfb-run -a`） | 日志出现 `dsh web: http://127.0.0.1:19387/` |
| 补丁生效 | 查 `resources/app/lib/main.js` | 含 `desktopResourcesRoot`、`desktopIsPackaged`、`linux-window-control` |
| 指纹已打 | 查 addon 的 `Matches` 处字节 | x64 `b8010000`、arm64 `20008052` |
| Sharp 隔离 | `ELECTRON_RUN_AS_NODE=1 <app> image-worker-src/verify-image-worker.cjs` | `✅ 图片链路与隔离均通过` |
| deb 可解析 | `ar t <deb>` | 含 `data.tar.zst`、`control.tar.zst` |
| deb 可安装 | `dpkg-deb --info <deb>` | 无 parsing warning，单一段落 |
| rpm 可读 | `rpm -qip <rpm>`；`rpm2cpio <rpm> \| cpio -t \| head` | 无错误 |
| pkg 可读 | `bsdtar -tf <pkg.tar.zst> \| head` | 无错误 |
| AppImage | `./<AppImage> --appimage-extract` | 能解出 squashfs-root |
| 架构正确 | `file <binary>` | x64 包无 aarch64 残留，反之亦然 |

> **启动验证会因缺登录凭据停在 `connection (required) missing credentials`**，这是正常的
> （应用必须登录才能真正起服务）。判断标准是：**Host 能启动、不出现 `MODULE_NOT_FOUND`
> / `unsupported platform` / `unsupported fingerprint`**。做对照实验：裁剪前后日志应一致。

### 6.3 ARM64（本机若为 x86_64）
```bash
qemu-aarch64-static -L <sysroot> <arm64-node> -e "console.log(process.arch)"   # 期望 arm64
```
> sysroot 需 `libc6`、`libstdc++6`、`libgcc-s1`、`zlib1g` 的 arm64 包；
> 注意 `lib/ld-linux-aarch64.so.1` 可能是**断链**，需换成真实文件。

---

## 7. 已知坑

| 现象 | 原因与处理 |
|---|---|
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

---

## 8. 硬性约束

1. **不要修改 `patches/` 下的脚本**，除非发现明确 bug —— 它们逐条实测过。
2. **不要构建 `system.deb`**。
3. **不要降级 Electron**。
4. **不要为了让测试通过而放宽断言。** 验证不过就如实报告。
5. 四种格式**必须都用 zstd**（第 5 节）。
6. 磁盘：完整构建约需 15 GB 空闲。
7. 打包前删除 `node_modules/.sharp-native-backup/`，否则白占体积。

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
- sha256sum -c：<通过数/总数>
- Sharp 隔离：<输出>
- deb 结构：ar t 的结果
- 指纹字节：Matches 处 hex

## 兼容性说明
（明确写出 zstd deb 的发行版支持范围：Ubuntu 21.04+ / Debian 12+；并说明 Ubuntu 与 Debian 引入版本不同步）

## 未能验证的部分
（如实列出；不要用"应该没问题"代替证据）

## 遇到的问题与处理
```