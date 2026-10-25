# DeepSeek Harness — Linux 移植产物

由官方 **macOS arm64** 安装包（`DeepSeek Harness 0.2.1-rc.2.dmg`）中的应用载荷重新打包为 Linux 版本。
上游应用：`@deepseek-ai/dsh-desktop 0.2.1-rc.2`。

覆盖 **x86_64** 与 **aarch64** 两种架构，各 **4 种**分发格式，共 **8 个产物**。
全部格式统一使用 **zstd** 压缩。

## 产物清单

### x86_64 (amd64)

| 文件 | 大小 | Electron | 适用发行版 |
|---|---|---|---|
| `DeepSeek-Harness-0.2.1-rc.2-x86_64.AppImage` | 287.5 MB | 内置 44.7.0 | 免安装，通用 |
| `deepseek-harness_0.2.1-rc.2_amd64.bundled.deb` | 258.7 MB | 内置 44.7.0 | Debian 12+ / Ubuntu 21.04+ |
| `deepseek-harness-0.2.1-0.rc2.x86_64.rpm` | 273.7 MB | 内置 44.7.0 | Fedora 31+ / openSUSE Leap 15.3+ |
| `deepseek-harness-desktop-0.2.1_rc.2-1-x86_64.pkg.tar.zst` | 169.6 MB | **依赖系统** | Arch Linux |

### aarch64 (arm64)

| 文件 | 大小 | Electron | 适用发行版 |
|---|---|---|---|
| `DeepSeek-Harness-0.2.1-rc.2-aarch64.AppImage` | 283.6 MB | 内置 44.7.0 | 免安装，通用 |
| `deepseek-harness_0.2.1-rc.2_arm64.bundled.deb` | 253.3 MB | 内置 44.7.0 | Debian 12+ / Ubuntu 21.04+ |
| `deepseek-harness-0.2.1-0.rc2.aarch64.rpm` | 269.8 MB | 内置 44.7.0 | Fedora 31+ / openSUSE Leap 15.3+ |
| `deepseek-harness-desktop-0.2.1_rc.2-1-aarch64.pkg.tar.zst` | 164.8 MB | **依赖系统** | Arch Linux |

> **只提供 `bundled.deb`。** 不再有 `system.deb`：Debian/Ubuntu 官方仓库没有 electron 包，
> 该变体在目标系统上无法直接安装。
>
> `.pkg.tar.zst` 是**唯一依赖系统 Electron** 的格式（Arch 的 `electron` 元包可靠，
> 会连带装 `electron44`）。实测确认：deb 与 rpm 内含
> `usr/lib/deepseek-harness/deepseek-harness` 二进制，`pkg.tar.zst` 不含。

## 系统要求

四种格式**全部使用 zstd** 压缩，因此对解包工具有最低版本要求。

### deb（dpkg）

| 发行版 | dpkg | 支持 |
|---|---|---|
| Ubuntu 21.04 (hirsute) 及更新 | 1.20.9ubuntu1+ | ✅ |
| Ubuntu 22.04 LTS (jammy) | 1.21.1ubuntu2 | ✅ |
| Ubuntu 24.04 LTS (noble) | 1.22.6ubuntu6 | ✅ |
| Debian 12 (bookworm) 及更新 | 1.21.22+ | ✅ |
| **Debian 11 (bullseye) 及更早** | 1.20.13 | ❌ |

> ⚠️ **Ubuntu 与 Debian 的 zstd 支持不同步，不能按上游 dpkg 版本号统一判断。**
> 上游 Debian 在 **1.21.18** 才引入（`libdpkg: Add zstd support for .deb archives.
> Closes: #892664`），而 Ubuntu **21.04 起就有自己的 patch**
> （`dpkg 1.20.9ubuntu1` hirsute：`Add Zstd compression and decompression support
> for binary packages`），并在 `1.21.1ubuntu1` 把默认压缩从 xz 改成 zstd（LP: #1923845）。
> 因此 Ubuntu 22.04 **可以**装，Debian 11 **不行**。

### rpm
`rpm >= 4.14`（Fedora 31+ / openSUSE Leap 15.3+）。更早版本报
`Unsupported payload compressor: zstdio`。

### pkg.tar.zst
pacman 5.x+，当前所有受支持的 Arch 系发行版均满足。

### AppImage
squashfs-tools 4.4+ 或内核支持 zstd squashfs。主流发行版均满足；AppImage 自解压，无需安装。

### 自检

```bash
ar t deepseek-harness_*.deb                 # 应含 data.tar.zst
rpm -qp --qf '%{PAYLOADCOMPRESSOR}\n' *.rpm # 应输出 zstd
bsdtar -tf *.pkg.tar.zst | head -1
./*.AppImage --appimage-offset              # 输出偏移即正常
```

## 压缩设置

| 格式 | 实现 |
|---|---|
| `.deb` | `data.tar.zst` + `control.tar.zst`（`ar` 归档） |
| `.rpm` | `_binary_payload w19.zstdio` |
| `.pkg.tar.zst` | `tar \| zstd -19 -T0 --long=27` |
| `.AppImage` | `mksquashfs -comp zstd -Xcompression-level 19 -Xdict-size 100% -b 1M` |

## 安装

```bash
# AppImage（免安装）
chmod +x DeepSeek-Harness-0.2.1-rc.2-x86_64.AppImage
./DeepSeek-Harness-0.2.1-rc.2-x86_64.AppImage

# Arch Linux（pacman 自动安装 electron 元包 → electron44）
sudo pacman -U deepseek-harness-desktop-0.2.1_rc.2-1-x86_64.pkg.tar.zst

# Debian / Ubuntu
sudo apt install ./deepseek-harness_0.2.1-rc.2_amd64.bundled.deb

# Fedora / openSUSE
sudo dnf install ./deepseek-harness-0.2.1-0.rc2.x86_64.rpm
```

安装后从应用菜单启动「**DeepSeek Harness Desktop**」，或执行 `deepseek-harness`。
AppImage 需要 fuse；无 fuse 时加 `--appimage-extract-and-run`。

也可先校验：

```bash
sha256sum -c SHA256SUMS.txt
```

## 本次移植做了什么

### 1. 修复 Linux 图片附件崩溃（Sharp / libvips 段错误）

`sharp` 依赖的 libvips 在 Linux + Electron 下会触发段错误，而
`@deepseek-ai/dsh-attachment-local` 恰好在 Electron 进程内处理图片附件，导致桌面端整体崩溃。
SIGSEGV 是进程级信号，JS 层无法捕获，因此采用**进程隔离**：

```
resources/
├── app/dsh/node_modules/sharp/      替身包：只转发调用，不含原生库
└── image-worker/
    ├── client.cjs                   Sharp API 兼容层（记录链式调用 → 转发）
    ├── worker.cjs                   在独立 Node 进程中重放并执行 libvips 调用
    └── worker-modules/node_modules/ 私有依赖闭包（约 20 MB / 120 文件）
```

- worker 运行在**载荷自带的 standalone Node** 上，不含 Chromium/GTK 符号空间；
- 使用**独立私有依赖闭包**，与 app 解析路径彻底隔离；
- 子进程环境被清理，仅保留 `PATH`/`HOME`/`LANG`/`TMPDIR`；
- worker 崩溃只影响当次图片操作，客户端自动重启并在连续失败 3 次后熔断。

实测：加载 shim 前后 `/proc/self/maps` 中**始终无 libvips**；
`probeImage` / `detectImage` / `normalizeImage` 三条真实路径，
以及 jpeg / png(alpha) / webp / gif 四种类型全部通过。

### 2. 修复 Linux 托盘

| 问题 | 修复 |
|---|---|
| Electron 44.0.0 的 Linux 托盘回归 | 内置 Electron 升级至 **44.7.0** |
| 托盘仅在 `process.platform === "win32"` 时创建 | 放行 Linux |
| 托盘图标使用 Windows `.ico` | Linux 改用 PNG（`tray.png`，32×32） |
| 无托盘时关窗隐藏窗口 → 应用失联 | 无托盘时关窗直接退出 |

### 3. Linux 原生标题栏 → macOS 风格窗口装饰

官方只为 win32（`titleBarStyle:"hidden"` + `titleBarOverlay`）与 darwin（`hiddenInset` + `vibrancy`）
配置了窗口装饰，**Linux 分支为空**，于是 Linux 下窗口顶上多出一条原生标题栏。

现在 Linux 采用与 macOS 一致的布局：**左上角红黄绿交通灯 + 侧栏半透明毛玻璃**。
实现方式复用应用自带机制，而非自造：

| 复用的东西 | 来源 | 作用 |
|---|---|---|
| `html[data-windows-titlebar]` | 应用自身的「自绘标题栏」模式 | 顶部 48px 预留带、拖拽区、折叠按钮重定位 |
| `color-mix(... var(--dsw-specific-sidebar-fill) 50%, transparent)` + 竖向渐变 | 应用自身的 `[data-platform=darwin]` 侧栏规则 | 侧栏半透明底色 |
| `backdrop-filter: blur(40px) saturate(150%)` | 应用菜单材质同一档位 | 毛玻璃 |
| `trafficLightPosition {x:16, y:18}` | 应用自身的 macOS 常量 | 交通灯坐标 |

**刻意不改 `data-platform`**：该属性也决定快捷键把 `primary` 解析成 Meta(⌘) 还是 Control ——
伪造 `darwin` 会让 Linux 快捷键显示成 ⌘ 且修饰键映射错误。这里只复刻材质数值，
`data-platform` 保持 `linux`。

**模糊为何不放在侧栏元素上**：`backdrop-filter` 会让元素成为 `position:fixed` 后代的包含块、
按自身 `overflow` 裁切、新建 backdrop root，并使整棵子树参与模糊面合成（文字发虚）。
初版加在侧栏上导致「折叠后按钮被裁掉」「侧栏右缘缺口」「文字发灰」三个问题。
现由独立、`pointer-events:none` 的背景层 `#dsh-mac-vibrancy` 承担，插到 `#root` 之前并设
`z-index:-1`；侧栏只保持 `background:0 0`。

**全屏检测为何需要三层**：上游把 Linux 同时排除在主进程事件注册（`darwin || win32`）
和 preload 监听（`syncWindowFullscreen` 早退）之外；而平铺合成器（niri / Hyprland / sway）
不向 Electron 报告全屏（实测铺满屏幕时 `isFullScreen()` 与 `isMaximized()` 均为 false）。
渲染层因此额外做视口自检，与主进程状态取并集。

**KDE 回退**：KDE Plasma 下自动改用不透明侧栏。X11 会话会尝试通过
`_KDE_NET_WM_BLUR_BEHIND_REGION` 请求 KWin 模糊；Wayland 会话或请求失败时回退不透明。

**全屏控件**：全屏时交通灯默认隐藏，鼠标移到顶部 4px 热区时与折叠键/新建键一并淡入，
移开淡出；尊重 `prefers-reduced-motion`。

### 4. 平台与其他适配

- **平台准入**：`["win32","darwin"]` 白名单加入 `"linux"`，否则启动即抛
  `desktop policy: unsupported platform`。
- **平台上报**：`x-client-platform` 对 Linux 上报 `desktop-linux`。
- **原生模块全部替换**为 linux 预编译产物（sharp 0.35.5 / koffi 3.1.1 / sherpa-onnx 1.13.8 /
  ripgrep 1.18.0 / node-addon-require-builtin 0.1.9 / node-addon-system(landlock) 0.1.2 /
  node-pty 1.2.0-beta.15），两架构各一套。
- **Office 引擎**：Linux 无官方原生 LibreOfficeKit 包，改用官方
  `@deepseek-ai/libreoffice-kit-wasm@0.1.5`（应用代码本身对 Linux 就走 WASM 回退路径）。
- **运行时载荷**：Node **24.21.0** + Python **3.12.14**（13 个科学计算包）+ pnpm **11.28.5**；
  `runtime.json` 的 `platform`/`arch` 修正为 `linux` / `x64|arm64`。
- **系统 Electron 兼容**：
  - `DSH_DESKTOP_RESOURCES_DIR` 覆盖 resources 根（原实现依赖 `process.resourcesPath`，
    在系统 Electron 下会指向 `/usr/lib/electron44/resources` 而失效）；
  - `DSH_DESKTOP_FORCE_PACKAGED=1` 让系统 Electron 加载 app 目录时不被误判为开发模式。
- **V8 指纹门禁**：`node-addon-require-builtin` 只接受 Electron 43.0.0 / 44.0.0 / 45.0.0-alpha.6
  三个精确 V8 指纹，系统 Electron 会被拒。已对其匹配函数做二进制放宽，
  **按 ELF 符号定位**（`MatchesERKNS2_19ElectronProfileSpecE`），
  三个 profile 的 ABI 字段是编译期常量、仅版本标签不同，放宽安全 ——
  **不降级 Electron，任意 4x 版本均可运行**。
- **Wayland 应用标识**：`package.json` 的 `desktopName` 设为 `deepseek-harness.desktop`，
  与安装的桌面项一致（否则 Wayland 下任务栏图标/分组异常）。
- **更新器**：官方无 Linux 更新源（`feeds/linux-x64` 返回 404），移除 `app-update.yml`。
- **桌面项**：`Name=DeepSeek Harness Desktop`、`Exec=deepseek-harness`、
  16→512 全套 hicolor 图标、`StartupWMClass`。
- **Arch 包名**为 `deepseek-harness-desktop`（而非 `deepseek-harness`），
  以免顶掉 archlinuxcn 仓库的 npm 版。桌面版仍提供 `/usr/bin/deepseek-harness`。

### 5. 体积裁剪

打包时自动调用 `trim-app-tree.sh`，移除运行时确实不用的载荷：
npm/corepack（应用只用 pnpm）、`node/share`、openssl 的 20 个非本架构头文件变体、
Python 的 `idlelib`/`tkinter`/`ensurepip`/`lib2to3`/`turtledemo`/`pydoc_data`/`pip`、
Windows 专用沙箱包、`LICENSES.chromium.html`。

解包后占用实测减少 **94.9 MB**（1167.1 → 1072.3 MB）。

> ⚠️ **诚实说明**：这些多为文本/头文件，压缩率约 17:1。在成品包中**下载体积仅减少约 0.2 MB**。
> 成品体积主要由 Electron(62MB) / app 依赖(66MB) / python(53MB) / node(28MB) 决定，
> 均为功能必需。该改动的实际价值是**减少安装后磁盘占用**。

## 验证记录

| 项目 | 方式 | 结果 |
|---|---|---|
| 四种格式 zstd | deb `ar t` / rpm `PAYLOADCOMPRESSOR` / pkg `bsdtar` / AppImage squashfs superblock | ✅ 4/4 |
| Sharp 隔离 | `/proc/self/maps` 无 libvips + 三条 attachment 路径 + 四种图片类型 | ✅ |
| 托盘 | 真实 Electron 主进程构造 `Tray` | ✅ |
| ARM64 node | qemu 运行成品包内 node 24.21.0 arm64 | ✅ |
| ARM64 python | numpy 2.3.5 / pandas 3.0.1 / Pillow 12.3.0 + 运算 | ✅ |
| ARM64 sharp | libvips 完整编解码（jpeg/webp/resize） | ✅ |
| 架构审计 | x64 树无 arm64 残留、arm64 树无 x86-64 残留 | ✅ 0 处 |
| 交通灯左置 + 侧栏透明 | 侧栏像素 alpha=0.5；交通灯位于 (16,18)；`data-platform` 保持 linux | ✅ |
| 8 个包 | `sha256sum -c SHA256SUMS.txt` | ✅ 8/8 |

## 已知问题

- **启动需登录**：应用必须登录才能起服务，未登录时会停在
  `connection (required) missing credentials`。这是上游行为，不是移植缺陷。

- **`dsh-connect-workbuddy` 插件图片误拒**（与本次移植无关）：第三方插件
  `dsh-connect-workbuddy@1.4.0` 的 `lib/index.js:81` 读取了错误字段名 ——
  判断 `info.multimodal`，而接口返回的是 `supportsImages`，导致 16 个模型全部被算出
  `inputModalities = ["text"]`，发图时报 `session/agent-busy`（实为 `session/attachment-invalid`）。
  规避：在 WorkBuddy 设置中开启对应模型的图像开关。

## 校验

```bash
sha256sum -c SHA256SUMS.txt
```
