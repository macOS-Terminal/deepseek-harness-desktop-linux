# 任务：为 DeepSeek Harness 桌面端构建 Linux 发行包并验证可用性

你从未接触过这个项目。以下是你需要的全部信息。**先读完再动手。**

**你手上已具备**：官方 macOS dmg（`0.2.1-rc.2`，已下载好）、可联网的 Linux 环境、
本补丁仓库的地址。**你需要做**：拉仓库 → 解包 dmg → 换平台包 → 打补丁 → 构建 →
逐包验证。

---

## 0. 背景（一句话）

DeepSeek 官方只发布 macOS / Windows 版桌面客户端。本项目的目标是把官方 **macOS dmg**
里的应用载荷重新打包成 **Linux** 安装包。官方代码里的 Linux 分支基本是空实现，
因此移植 = **用补丁补齐那些空分支** + 替换平台相关的原生模块与运行时。

**上游版本：`0.2.1-rc.2`**（dmg 内目录名 `DeepSeek Harness 0.2.1-rc.2-arm64`）

---

## 1. 你的交付物

| # | 交付物 | 验收标准 |
|---|---|---|
| 1 | 拉取补丁仓库 | 本地存在 `patches/`、`build-packages.sh`、`image-worker-src/`、`icons/` |
| 2 | 构建 **x86_64** 产物 | 生成 AppImage + `.deb`（bundled）+ `.pkg.tar.zst` + `.rpm` |
| 3 | 构建 **aarch64** 产物 | 同上 4 种格式 |
| 4 | 验证每个包 | 每个包解包后能实际启动，看到 `dsh web: http://127.0.0.1:19387/` |
| 5 | 校验和 | 生成 `SHA256SUMS.txt` 并 `sha256sum -c` 全部通过 |

**官方 macOS dmg 已为你准备好**（上游版本 `0.2.1-rc.2`），无需下载。
你只需把它解包，然后按第 4 节流程构建。

**注意**：只需构建 `bundled.deb`（内置 Electron）。**不要**构建 `system.deb`——
构建脚本已改为只出 bundled 变体，请勿改回去。

---

## 2. 仓库

```
https://github.com/macOS-Terminal/deepseek-harness-desktop-linux
```

克隆后你会看到：

```
patches/                          补丁脚本（核心资产）
image-worker-src/                 Sharp 进程隔离方案（3 个 .cjs）
icons/                            桌面项 + 全套图标
build-packages.sh                 全格式打包入口
install-image-worker.sh           把 Sharp 替身包装入应用树
verify-launch-x64.sh              五种格式逐个解包并实测启动
swap-native-linux.sh              把 darwin 原生包替换为 Linux 版（x64/arm64 双架构）
build-linux-ready-archive.sh      生成 Linux-ready 裁剪分发包（x64/arm64）
docs/ARTIFACTS.md                 产物说明 / 安装方式 / 依赖策略
docs/CHANGELOG.md                 完整变更日志（含每个修复的根因与实测数据）
docs/AGENT_PROMPT.md              本文件
README.zh.md                      完整中文教程 ← **先读这个**
README.md                         英文概览
```

**先读 `README.zh.md`**，它包含完整的前置依赖清单与常见坑。

---

## 3. 前置依赖（需你自行获取）

仓库**不含**任何官方二进制载荷（体积与授权原因）。需要准备：

### 3.1 解包已就位的官方 dmg
dmg 已放在 `others/`（文件名形如 `dsh-latest-macos-arm64.dmg`）。解包：
```bash
7z x -oothers/dmg others/dsh-latest-macos-arm64.dmg
```
解出的目录名会带版本号，例如 `DeepSeek Harness 0.2.1-rc.2-arm64`。
> 若解出的版本与本文档写的 `0.2.1-rc.2` 不同，请以实际为准，
> 并核对第 3.2/3.4 节的 Electron 与 npm 包版本号是否需同步调整。

### 3.2 Electron **44.7.0**
```
dl/electron-44.7.0-linux-x64.zip
dl/electron-44.7.0-linux-arm64.zip
```
> ⚠️ 必须 ≥ 44.4.5：Electron 44.0.0 有 Linux 托盘回归缺陷。
> 0.2.1-rc.2 官方 dmg 内置的是 44.7.0。

### 3.3 Node 与 Python 运行时
```
dl/node-v24.21.0-linux-x64.tar.xz      dl/node-v24.21.0-linux-arm64.tar.xz
dl/python-3.12.14-x64.tar.gz           dl/python-3.12.14-arm64.tar.gz
```
> ⚠️ Python **必须**用 python-build-standalone 的 `install_only_stripped` 变体。
> 不要用普通版再手工 `strip` —— 其段布局非标准，`strip`/`objcopy` 会破坏版本符号，
> 运行期报 `symbol lookup error`。

### 3.4 Linux 原生模块（两架构各一套）

| npm 包 | 用途 |
|---|---|
| `@img/sharp-linux-{x64,arm64}` + `@img/sharp-libvips-linux-*` | 图片处理（**sharp 0.35.5**） |
| `@koromix/koffi-linux-*` | FFI |
| `sherpa-onnx-linux-*` | 语音识别 |
| `node-addon-require-builtin-linux-*-gnu` | 内建模块桥接（**需打指纹补丁**） |
| `@vscode/ripgrep-linux-*` | 搜索 |
| `@deepseek-ai/node-addon-system-linux-*` | landlock 沙箱 |
| `node-pty`（取 `prebuilds/linux-*`） | 终端 |
| `@deepseek-ai/libreoffice-kit-wasm@0.1.5` | Office 引擎（Linux 走 WASM 回退） |

> 说明：`@deepseek-ai/libreoffice-kit` 的 `platformTarget()` 在 Linux 上只解析
> `linux-{arch}-glibc` 或 wasm，**darwin 包在 Linux 上永不加载**，无需携带。

### 3.5 打包工具
`mksquashfs`（squashfs-tools）、AppImage type2 runtime（`runtime-x86_64`、`runtime-aarch64`）、
`rpmbuild`、`bsdtar`、`fakeroot`、`ar`、`zstd`、`xz`。

放置：`tools/usr/bin/mksquashfs`、`tools/runtime-x86_64`、`tools/runtime-aarch64`

---

## 4. 构建流程

### 4.1 铺 Electron 骨架（每架构一次）
```bash
cd out-x64
unzip -oq ../dl/electron-44.7.0-linux-x64.zip
mv electron deepseek-harness
rm -f resources/default_app.asar
```

### 4.2 展开 dmg 里的 app.asar 到 `resources/app`
asar 格式：文件头 16 字节，`[12:16]` 是 JSON 头长度，
`data_start = 8 + uint32([4:8])`，各文件按 `offset`/`size` 切片；
`unpacked: true` 的条目从 `app.asar.unpacked/` 取。
（仓库的 `README.zh.md` 有说明；也可参考 `scripts/extract-asar.py` 的思路。）

### 4.3 替换原生模块 + 装配运行时

**平台替换用仓库里的脚本**（已实测两架构）：
```bash
# 从 npm 取好对应架构的 Linux 包放进 dl/linux-x64 或 dl/linux-arm64（见 3.4 节），然后：
./swap-native-linux.sh <app-tree> dl/linux-x64  x64
./swap-native-linux.sh <app-tree> dl/linux-arm64 arm64
```
`<app-tree>` 指含 `dsh/node_modules` 的那一层（即 `.../Resources/app.asar.unpacked/dsh`）。
脚本会：删 darwin 包 → 装 Linux 包 → 清理 `*:com.apple.provenance` →
对全部 `.node`/`.so` 做架构核验（不符即非零退出）。

> **为什么必须替换而不是只删**：应用按平台 `require.resolve` 解析原生模块。
> darwin 包在 Linux 上永不加载，但**对应的 Linux 包必须存在**，否则 require 失败、
> Host 启动中止。只删不装会得到一个能解包但跑不起来的树。

其余装配要点：
- `resources/runtime/` 放 `bin/node`、`cli/`、`office-skills/`、`versions.json`
- `resources/runtime/primary-runtime/dependencies/` 放 `node/`、`python/`、`pnpm/`
  > ⚠️ **0.2.1 起 pnpm 位于 `dependencies/pnpm/`**（0.2.0 时在 `runtime/pnpm/`）。
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
  （arm64 换 `--platform manylinux_2_28_aarch64 --platform manylinux_2_27_aarch64`）
- 修正 `runtime/primary-runtime/runtime.json` 的 `platform`/`arch` 为 `linux` / `x64|arm64`

### 4.4 打补丁 —— **必须按此顺序**
```bash
cd <项目根>

# ① 平台准入 / 资源根 / 托盘 / 窗口控制 IPC（14 项）
python3 patches/patch-main.py        out-x64/resources/app/lib/main.js

# ② 隐藏原生标题栏（为 ③ 铺垫：先建立 linux 窗口分支）
python3 patches/patch-titlebar.py    out-x64/resources/app/lib/main.js

# ③ macOS 风格装饰（交通灯 + 毛玻璃 + 全屏）
#    会依次自动调用 patch-kde-material.py / patch-fullscreen-reveal.py / patch-linux-identity.py
python3 patches/patch-mac-chrome.py  out-x64/resources/app

# ④ 放宽 V8 指纹门禁（对 .node 二进制打补丁）
python3 patches/patch-fingerprint.py \
  out-x64/resources/app/dsh/node_modules/node-addon-require-builtin-linux-x64-gnu/prebuilt/linux-x64-gnu-napi-v9.node
```

> **顺序不可颠倒**：③ 的两步替换的是 ② 产生的 `titleBarOverlay` 分支。
> 若先跑 ③ 会报 `未匹配`（不致命，但窗口装饰不会生效）。
>
> **指纹补丁已改为按 ELF 符号定位**（`MatchesERKNS2_19ElectronProfileSpecE`）。
> 旧实现用硬编码偏移 + 序言扫描兜底，在新版 addon 上扫描命中 233 个无关函数并
> **打错了地址**（把 `0x1e174` 当成 `0x1e1e4`），静默损坏二进制却报成功。
> 现版本找不到唯一符号就**拒绝打补丁**。请勿改回扫描逻辑。
>
> **arm64 同理**，把 `x64` 换成 `arm64`，指纹补丁目标换成
> `.../node-addon-require-builtin-linux-arm64-gnu/prebuilt/linux-arm64-gnu-napi-v9.node`。

补丁作用与「不打会怎样」：

| 补丁 | 不打会怎样 |
|---|---|
| `patch-main.py` | 启动即抛 `desktop policy: unsupported platform` |
| `patch-titlebar.py` | 出现系统原生标题栏 |
| `patch-mac-chrome.py` | 无交通灯、无毛玻璃、全屏布局不对 |
| `patch-fingerprint.py` | `unsupported Electron runtime fingerprint`，Host 启动失败 |

### 4.5 装 Sharp 进程隔离
```bash
./install-image-worker.sh out-x64 x64
```
> **为什么必须做**：libvips 在 Electron 进程内会段错误（SIGSEGV），JS 层无法捕获，
> 整个桌面端会崩溃。方案是进程隔离：Sharp 调用转发到独立 Node worker。
>
> ⚠️ 打包前**务必删除** `node_modules/.sharp-native-backup/`，否则白占体积。

### 4.6 打包
```bash
./build-packages.sh x64
./build-packages.sh arm64
```
产物落在 `dist/`。

> 脚本要点：在 tmpfs 暂存并按文件内容恢复可执行位（NTFS/exFAT 上 `chmod` 无效）；
> 归档属主统一 `root:root`；rpm 用 `%defattr(-,root,root,-)` 且禁用 strip。
> aarch64 交叉打包需给 rpmbuild 补 `buildarch_compat: x86_64: aarch64 noarch`。

---

## 5. 验证（必做，不可跳过）

### 5.1 自动验证
```bash
./verify-launch-x64.sh                 # 五种格式逐个解包并实际启动
cd dist && sha256sum -c SHA256SUMS.txt
```

### 5.2 逐包人工核验要点

| 检查 | 方法 | 期望 |
|---|---|---|
| 能启动 | 解包后跑二进制，`--ozone-platform=x11 --disable-gpu` | 日志出现 `dsh web: http://127.0.0.1:19387/` |
| 补丁生效 | 解包后 grep `lib/main.js` | 含 `desktopResourcesRoot`、`desktopIsPackaged`、`linux-window-control` |
| Sharp 隔离 | `ELECTRON_RUN_AS_NODE=1 <app> image-worker-src/verify-image-worker.cjs` | 输出 `✅ 图片链路与隔离均通过` |
| deb 可安装 | `dpkg-deb --info <deb>` | 无 parsing warning，单一段落 |
| 架构正确 | `file <binary>` | x64 包无 aarch64 残留，反之亦然 |

### 5.3 ARM64 验证（若本机是 x86_64）
用 qemu-user-static：
```bash
qemu-aarch64-static -L <sysroot> <arm64-node> -e "console.log(process.arch)"   # 期望 arm64
```
> sysroot 需要 `libc6`、`libstdc++6`、`libgcc-s1`、`zlib1g` 的 arm64 包；
> 注意 `lib/ld-linux-aarch64.so.1` 可能是**断链**，需换成真实文件。

---

## 6. 已知坑（都踩过，直接照做）

| 现象 | 原因与处理 |
|---|---|
| 启动即 `EADDRINUSE 127.0.0.1:19387` | 已有实例在跑（应用固定用此端口），先关掉 |
| 一发图片整个应用崩 | Sharp 替身包没装好，检查 `resources/image-worker/` |
| 系统 Electron 下白屏 | 缺 `DSH_DESKTOP_RESOURCES_DIR` / `DSH_DESKTOP_FORCE_PACKAGED` |
| 打包后二进制无执行权限 | 工作区在 NTFS；`build-packages.sh` 的 `normalize_modes` 必须保留 |
| Python 报 `symbol lookup error` | 用了被 strip 过的 python-build-standalone，改用 `install_only_stripped` |
| `dpkg -i` 报 control 格式错误 | 可选字段被展开成空行（空行=段落分隔符）；已在脚本里修，勿回退 |
| 全屏时交通灯不隐藏 | 平铺合成器（niri/sway）不向 Electron 报告全屏；`syncTilingFullscreen` 必须保留 |
| 折叠后无法展开侧栏 | `backdrop-filter` 不能放在侧栏元素上（会成为 fixed 子元素的包含块）；必须用独立层 |
| 误启动真实应用弹错误框 | Electron 优先加载二进制旁的 `resources/app`；测试请用系统 Electron 跑独立小程序 |

---

## 7. 硬性约束

1. **不要修改 `patches/` 下的脚本**，除非发现明确 bug —— 它们是逐条实测过的。
2. **不要构建 `system.deb`**。
3. **不要降级 Electron**（指纹补丁已放宽，任意 4x 可用）。
4. 验证不通过就不要声称完成。**不要为了让测试通过而放宽断言**。
5. 磁盘：完整构建约需 15GB 空闲（两架构产物 + 暂存）。

---

## 8. 汇报格式

```
## 构建结果
| 架构 | AppImage | bundled.deb | pkg.tar.zst | rpm |
|---|---|---|---|---|
| x86_64 | 大小 | 大小 | 大小 | 大小 |
| aarch64 | 大小 | 大小 | 大小 | 大小 |

## 验证证据
（粘贴真实命令输出，不要转述）
- x64 启动实测：<verify-launch-x64.sh 的输出>
- sha256sum -c：<通过数量/总数>
- Sharp 隔离：<verify-image-worker.cjs 的输出>

## 未能验证的部分
（如实列出；不要用"应该没问题"代替证据）

## 遇到的问题与处理
```