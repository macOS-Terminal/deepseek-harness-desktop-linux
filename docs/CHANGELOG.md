# Changelog

本项目是 **DeepSeek Harness 桌面端（Electron）的 Linux 移植/重打包**。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [Unreleased]

### 新增

- 对应用树全部活动 ELF 载荷检查目标架构，拒绝混入 x64 / ARM64 原生模块。
- 指纹补丁按 ELF 机器类型和唯一函数符号定位，未知布局中止，支持重复运行。
- 验证 ARM64 AppImage、deb、pacman 与 RPM 打包；区分静态检查与目标机运行验证。

- 一键入口支持 `--formats appimage,deb,pacman,rpm` 与 `all`，按所选格式预检查工具。
- 两个入口共用发行包构建模块，版本来自应用树，各格式提供 SHA256 文件并保留暂存。

- 一键 AppImage 构建入口 `auto-build.sh`，支持本机架构与 x64/arm64 双架构。
- 按 prepare/tree/package 拆分的构建模块、asar 解包与同版本原生依赖替换工具。
- 本地或 URL dmg、独立缓存目录、镜像回退、Electron/Node 校验和验证、Sharp 自检。
- 默认保留所有缓存、解包物和构建暂存，`--clean` 在成功后显式清理中间物。
- 自动构建指南与离线回归测试。窗口装饰沿用现有补丁。

## [2.0.0] — 2026-10-01 — 适配 `0.2.0-rc.2`

上游从 `0.1.7-rc.1` 升级到 **0.2.0-rc.2**。本次以官方 **macOS arm64** dmg 为唯一载荷来源
（用户已删除先前的 Windows 安装包），重新完成整套 Linux 移植，产出 x86_64 与 aarch64
各 5 种格式，共 10 个产物。

> 上一版（1.0.0，基于 0.1.7-rc.1）的构建产物与下载缓存已被用户全部删除，
> 本次为完整重建：Electron、Node、Python、全部原生模块、打包工具，以及此前的
> 补丁与 image-worker 方案，均按新版本重新实现并重新验证。

### 新增

- **产物 10 个**（体积为 MiB，1 MiB = 1048576 B）：

  | 格式 | x86_64 | aarch64 |
  |---|---|---|
  | AppImage | 291 | 282 |
  | `bundled.deb` | 255 | 238 |
  | `system.deb` | **167** | **157** |
  | `pkg.tar.zst` / `.gz` | **181** | **172** |
  | `.rpm` | 255 | 239 |

- **支持 0.2.0 新增的 `runtime/cli`**（官方新增的 CLI 安装功能）：
  其 macOS 启动器引用了 `../MacOS/DeepSeek Harness` 与 `resources/app.asar/...`，
  已改写为 Linux 版本，可自动定位发行版 electron 或内置二进制，
  再以 `ELECTRON_RUN_AS_NODE` 运行 `dsh-desktop-host/lib/cli.js`。


### 修复 — Linux 图片附件崩溃（Sharp / libvips 段错误）

与 0.1.7 同源问题，方案不变（进程隔离），按新版重新实现：

```
resources/
├── app/dsh/node_modules/sharp/     替身包：只转发调用，不含原生库
└── image-worker/
    ├── client.cjs                  Sharp API 兼容层（记录链式调用 → 转发）
    ├── worker.cjs                  在独立 Node 进程中重放并执行 libvips 调用
    └── worker-modules/node_modules/ 私有依赖闭包（约 20 MB / 120 文件）
```

- worker 跑在载荷自带的 standalone Node 上，不含 Chromium/GTK 符号空间；
- 私有依赖闭包置于 asar 之外（standalone Node 无 asar 支持）；
- 子进程环境清理为 `PATH`/`HOME`/`LANG`/`TMPDIR`；
- worker 崩溃只影响当次操作，客户端自动重启，连续 3 次失败后熔断。

实测：`/proc/self/maps` 全程无 libvips；三条 attachment 路径与 jpeg / png(alpha) /
webp / gif 四种类型全部通过；坏数据抛错而非崩溃。

### 修复 — Linux 托盘

四个独立问题（与上一版同类，按新版重新定位）：

| 问题 | 修复 |
|---|---|
| Electron 44.0.0 的 Linux 托盘回归 | 内置 Electron 升级至 44.4.5 |
| 托盘仅 win32 时创建 | 放行 Linux |
| 图标为 Windows `.ico` | 改用 PNG `tray.png`（32×32） |
| 无托盘时关窗隐藏 → 失联 | 无托盘时直接退出 |

实测：真实 Electron 主进程构造 `Tray` 成功。

### 修复 — Linux 原生标题栏

上游仅给 win32（`titleBarStyle:"hidden"` + `titleBarOverlay`）与 darwin（`hiddenInset`）
配置了自绘标题栏，Linux 分支为空，导致原生标题栏与应用头双层叠加。
因渲染层无拖拽区、preload 无窗口控制 API，裸 `hidden` 会得到无法拖动/关闭的窗口，
故同样走 `titleBarOverlay`（GTK 绘制系统按钮、标题区可拖动），主窗口 40px、欢迎窗口 42px。

### 新增 — macOS 风格窗口装饰（左置交通灯 + 侧栏毛玻璃）

上游只为 win32 与 darwin 配置窗口装饰，Linux 分支为空；本次让 Linux 与 macOS 视觉对齐：

- **三大金刚键强制左置**：改用应用自身的「自绘标题栏」模式
  （`html[data-windows-titlebar]`，原本仅 Windows 启用）获得 48px 顶部预留带、
  自动拖拽区与页面内边距，再按 macOS 常量 `trafficLightPosition {x:16, y:18}`
  在左上角绘制红黄绿交通灯；点击经新增 IPC（`dsh-desktop:linux-window-control`）
  执行最小化 / 最大化切换 / 关闭。移除上一版把按钮放到右上角的 `titleBarOverlay`。
- **侧栏毛玻璃**：复刻应用自身 `[data-platform=darwin]` 的材质配方 ——
  `color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent)` 叠竖向渐变，
  再补 `backdrop-filter: blur(40px) saturate(150%)`；同时清掉 `body` 与侧栏内层
  `._3WPZCG_root` 的不透明底（后者正是先前"看不到透明"的原因）。
- **不改 `data-platform`**：该属性同时决定快捷键 `primary` → Meta(⌘) 还是 Control，
  伪造 darwin 会破坏 Linux 快捷键语义，故只复刻材质数值。
- **窗口层**：主窗口与欢迎窗改为 `titleBarStyle:"hidden"` + `transparent:true`
  （欢迎窗额外 `frame:false`），使半透明真正透出桌面。
- **Wayland 兜底**：niri 等合成器不实现 `isMaximized()`，最大化切换改为
  「已铺满工作区即视为最大化」，避免点了没反应。

验证：侧栏像素实测 `srgba(28,28,28,0.5)`（真 50% 透明）、内容区 `alpha=1`；
拖拽带 48px 且 `app-region:drag`；交通灯 (16,18) 三色正确。

### 修复 — deb 的 control 文件存在空行，导致 dpkg/apt 拒绝安装

**（社区反馈：[issue #1](https://github.com/macOS-Terminal/deepseek-harness-desktop-linux/issues/1)）**

现象：`dpkg -i` / `apt install ./*.deb` 报控制文件格式错误，无法安装。

根因在 `build-packages.sh` 生成 `DEBIAN/control` 的那段 heredoc：

```sh
Depends: $deps
${rec:+Recommends: $rec}      # ← bundled 变体下 rec 为空，这一行展开成空行
Homepage: https://harness.deepseek.com
```

`${rec:+...}` 在 `rec` 未设置时展开为**空字符串**，但模板里该行本身还在，
于是输出一个真正的空行。而 Debian 控制文件的语法中，**空行是段落分隔符** ——
dpkg 会把后面的 `Homepage:` / `Description:` 当成「第二个包」的起始，
而该段缺少必需的 `Package:` / `Version:`，解析随即失败。

这一点已用严格的分段解析器复现并验证：

| 版本 | 解析出的段落数 | 结果 |
|---|---|---|
| 修复前 | **2**（Homepage 起被当作新包） | ✗ 非法 |
| 修复后 · bundled | 1 | ✓ 合法 |
| 修复后 · system | 1 | ✓ 合法 |

修复：把可选字段先拼成变量，为空时**整行不输出**（而不是留空行），
同时保留 `Recommends` 行尾换行，避免与下一字段粘连：

```sh
local recommends_line=""
if [ -n "$rec" ]; then
  recommends_line="Recommends: $rec
"
fi
...
${recommends_line}Homepage: https://harness.deepseek.com
```

> 注意：`system` 变体因为有 `Recommends` 字段，原本不会触发该问题；
> 只有 **`bundled` 变体**（`rec` 为空）会产生空行 —— 这也解释了为何只有部分用户遇到。

### 修复 — 折叠侧栏时新建按钮与交通灯重叠（用户实测反馈）

折叠侧栏后，应用的导轨按钮位置是**写死**的：

```css
[data-windows-titlebar] ._3WPZCG_collapsed ._3WPZCG_newSession {
  position: fixed; left: 48px;
}
```

这是为 Windows 设计的 —— Windows 的窗口按钮在**右侧**，左侧 12px 起是空的，
所以从 48px 开始排「新建」「展开」两个圆钮正合适。
但本移植把交通灯放在左侧 16–68px，于是折叠态的新建按钮（48px）正好压在灯上；
全屏时灯会隐藏，所以那个状态下看不出问题 —— 这正是「窗口模式重叠、全屏正常」的原因。

修复：**仅在窗口模式**把折叠态两个导轨按钮右移（新建 `88px`、展开 `128px`），
避开 16–68px 的灯区；**全屏时交通灯已隐藏，不需要让位**，因此保留应用原本的
leading-edge 位置（新建 `48px`、展开 `12px`），维持原生观感。
展开态的侧栏 toggle 同样只在窗口模式贴右缘（`--dsh-linux-toggle-left`），全屏回 `12px`。

实测（真实矩形相交判定）：

| 状态 | 交通灯 | 新建按钮 | 展开按钮 | 矩形相交 |
|---|---|---|---|---|
| 展开·窗口 | 16–68 | 12,102（整行） | 240 | 否 |
| 折叠·窗口 | 16–68 | **88** | **128** | **否** |
| 折叠·全屏 | 隐藏 | **48** | **12** | 否 |
| 展开·全屏 | 隐藏 | 整行 | **12** | 否 |

同时把失焦态的交通灯从「变灰」改为「降饱和 + 压暗」（`saturate(.55) brightness(.72)`），
与 macOS 行为一致 —— 后者窗口失焦时灯仍保留色相，只是变暗。

### 修复 — 真全屏不生效 / 侧栏底部暗条 / 登录页无文字（用户实测反馈）

**1. 真全屏时交通灯不隐藏、按钮重叠**

两层原因，缺一不可：

- 主进程把 Linux 排除在全屏事件之外：`if (process.platform === "darwin" || process.platform === "win32")`
  → 从未注册 `enter-full-screen` / `maximize` 监听，`data-fullscreen` 永不置位；
- preload 的监听同样早退：`syncWindowFullscreen()` 里的
  `if (process.platform !== "darwin" && process.platform !== "win32") return;`
  → 即使主进程发了事件，渲染层也收不到。

此外，**平铺合成器（niri / Hyprland / sway）根本不向 Electron 报告全屏**：
实测窗口铺满 2560×1440 时 `isFullScreen()` 与 `isMaximized()` 均为 false。
因此在渲染层补了一个视口自检：视口覆盖屏幕可用区域即视为全屏，并与主进程状态取并集，
`resize` 时重新计算。

实测：窗口态 `data-fullscreen=false`、交通灯显示、折叠键 240px；
铺满屏幕后 `true`、交通灯 `display:none`、折叠键 12px；还原后全部复原，全程无重叠。

**2. 侧栏底部出现不透明暗条**

应用自身有一个列表滚动淡出层：

```css
._7514NG_fade { background: linear-gradient(to bottom, transparent, var(--dsw-specific-sidebar-fill)); }
```

它渐变到 `--dsw-specific-sidebar-fill`（不透明的 `rgb(27,27,28)`）。侧栏改为半透明后，
这个终点色不再匹配，于是底部露出一条实心暗带。修法不是在 fade 上打补丁，
而是让 `--dsh-linux-sidebar-tint` 承载半透明值并让 fade 使用它，
这样任何引用该变量的组件都会自动跟随。

**3. 登录页文字全部消失**

`preload-welcome.cjs` 中 `const VIBRANCY_ID` 被重复声明（`SyntaxError`），
导致 preload 加载失败、页面拿不到 locale 数据，界面只剩空壳。
已在两个 preload、两棵架构树中各去掉重复声明。

### 修复 — 全屏与清晰度（用户实测反馈）

三个问题，均已修复：

**1. 侧栏文字/图标发灰、清晰度不足**

初版把 `backdrop-filter` 加在侧栏元素上，使整棵侧栏子树参与模糊面合成，
文字被混合到模糊层里，边缘发虚、对比度下降。

修复：模糊层独立为 `#dsh-mac-vibrancy` 后，进一步把它移到 `#root` **之前**并设
`z-index:-1`，让它真正位于整个 UI 之下；侧栏自身 `background:0 0` 且不再带
`backdrop-filter`，文字重新落在独立合成层上。

**2. 内容区左上角圆角造成空白缺口**

应用为 Windows 无边框窗口加了 `[data-windows-titlebar] ._centerCol{border-radius:16px 0 0 0}`。
我们复用该模式后，窗口铺满屏幕时这个圆角的外侧就是露出的空白（KDE Plasma 同样可见）。

修复：`html[data-dsh-mac-chrome] [class*="_centerCol"]{border-radius:0}` —— 该圆角在
无窗口装饰、铺满屏幕的场景下没有意义。

**3. 全屏布局未对齐 macOS**

应用自身已有 macOS 全屏规则（`[data-platform=darwin][data-fullscreen]`），
但我们的 `data-windows-titlebar` 模式没有对应处理。

修复：按 macOS 行为补两条 —— 全屏时**隐藏红黄绿交通灯**，折叠键回到左侧
（`left:12px`），与应用的 darwin 全屏规则一致；退出全屏自动恢复。

实测：`vibZ=-1` 且位于 `#root` 之前；`_centerCol` 圆角 `0px`；
模拟全屏后交通灯 `display:none`、折叠键 `left=12`，退出后恢复 `flex` / `240`。

### 修复 — 毛玻璃引入的两个回归（用户实测发现）

初版把 `backdrop-filter` 直接加在侧栏元素上，触发了 `backdrop-filter` 的两个规范行为，
造成两个可复现的故障，均已修复：

| 现象 | 根因 | 修复 |
|---|---|---|
| 侧栏右缘出现一条缺口（截图里"中间缺一块"） | `backdrop-filter` 使其元素成为新的 backdrop root，配合 `_frame` 的 `overflow:hidden` 导致该区域合成被裁切 | 模糊不再放在侧栏上 |
| **侧栏折叠后无法再展开**（按钮消失） | `backdrop-filter` 会让元素成为 `position:fixed` 后代的**包含块**并按自身 `overflow` 裁切。应用的折叠按钮本是 `position:fixed`，被改为相对侧栏定位；侧栏宽度收到 0 时按钮一起被裁掉 | 见下 |

修复方式：把 `backdrop-filter`（连同半透明配色）**移到一个独立的背景层**
`#dsh-mac-vibrancy`（`position:fixed; inset:0 auto 0 0; width:var(--dsh-linux-sidebar-width);
pointer-events:none`），侧栏本身只保留 `background:0 0`。这样：

- 模糊与色调的视觉效果保持不变（仍是应用自身的 darwin 配方）；
- 不再有元素因 `backdrop-filter` 成为包含块，折叠按钮恢复视口级 fixed 定位；
- 背景层 `pointer-events:none`，不拦截任何点击。

同时让折叠态按钮停在 `left:88px`（避让左上交通灯；应用原本在 Windows 上给它的是
`left:12px`，那会与交通灯重叠），展开态仍贴侧栏右缘。

实测（CDP 逐点命中 + 尺寸断言）：

| 状态 | 侧栏宽 | 折叠按钮 | 可点击（命中测试） | 模糊层 |
|---|---|---|---|---|
| 展开 | 280px | (240, 10) | ✓ | 280px / `blur(40px) saturate(1.5)` |
| 折叠 | 0 | **(88, 10) 可见** | ✓ | 保持 |
| 再次展开 | **280px** | (240, 10) | ✓ | 保持 |

按钮的视口 y 坐标由 58 恢复为 10，证明包含块效应已消除；侧栏右缘逐点命中连续，缺口消失。

### 修复 — 平台与系统 Electron 兼容

- 平台白名单加入 `linux`；`x-client-platform` 上报 `desktop-linux`。
- 原生模块全部替换为 linux 预编译产物（sharp / koffi / sherpa-onnx / ripgrep /
  node-addon-require-builtin / node-addon-system(landlock) / node-pty / reflink），两架构各一套。
- Office 引擎改用 `@deepseek-ai/libreoffice-kit-wasm@0.1.0`（Linux 走 WASM 回退）。
- `runtime.json` 的 `platform`/`arch` 修正为 `linux` / `x64|arm64`。
- `DSH_DESKTOP_RESOURCES_DIR` 覆盖 resources 根；`DSH_DESKTOP_FORCE_PACKAGED=1`
  修正系统 Electron 下 `app.isPackaged` 为 false 的误判（共 12 处判定改用 helper）。
- **V8 指纹门禁**：`node-addon-require-builtin` 只接受 Electron 43.0.0 / 44.0.0 /
  45.0.0-alpha.6 的精确 V8 指纹，44.4.5 会被拒并导致 Host 启动失败
  （`unsupported Electron runtime fingerprint`）。已对其匹配函数做二进制放宽：
  x64 `0x17cdd`（`mov eax,1; ret`）、arm64 `0x1df14`（`mov w0,#1; ret`）。
  三个 profile 的 ABI 字段为编译期常量、仅版本标签不同，放宽安全，无需降级 Electron。

### 打包与元数据

- 桌面项 `Name=DeepSeek Harness Desktop`（含中文名）、`Exec=deepseek-harness`、
  16→512 hicolor 图标、`StartupWMClass`。
- Arch 包名 `deepseek-harness-desktop`（避免顶掉 archlinuxcn 的 npm 版
  `deepseek-harness`；两者零路径冲突，可共存）。
- 移除 `app-update.yml`（官方无 Linux 更新源）。
- `chrome-sandbox` setuid 由 deb `postinst` / rpm `%attr(4755)` / pacman `.INSTALL` 设置；
  rpm 用 `%defattr(-,root,root,-)` 保留归一化权限；归档属主统一 `root:root`；
  禁止 rpmbuild strip 厂商预编译二进制。
- **本次主机环境为 NTFS（fuseblk），chmod 无效且一切文件显示为 0777**，
  因此改为在 tmpfs 上暂存并按文件内容（ELF / `#!` / `.so` / `.node`）恢复权限后再打包。

### 验证

| 项目 | 结果 |
|---|---|
| x64 五种格式解包实测启动 | ✅ 5/5 |
| Sharp 隔离（maps 无 libvips + 路径与类型覆盖） | ✅ |
| 托盘（真实 Electron 主进程） | ✅ |
| ARM64 node / python / sharp（qemu，取自成品 deb） | ✅ |
| 架构审计（两树互无错位残留） | ✅ 0 处 |
| 交通灯左置 + 侧栏透明（像素级验证 alpha=0.5） | ✅ |
| 折叠按钮可见可点、折叠后可再次展开侧栏 | ✅ |
| 侧栏右缘无缺口（逐点命中连续） | ✅ |
| 文字清晰度（模糊层移到 #root 之前，侧栏不再带 filter） | ✅ |
| 内容区圆角归零、全屏隐藏交通灯 + 折叠键靠左 | ✅ |
| 真全屏（平铺合成器）检测：铺满屏幕即隐藏交通灯 | ✅ |
| 侧栏底部淡出条跟随半透明底色、无实心暗带 | ✅ |
| 折叠态导轨按钮避开交通灯（新建 88px / 展开 128px） | ✅ |
| deb control 文件无空行（分段解析段落数=1） | ✅ |
| 标题栏补丁存在于两架构包内 | ✅ 10/10 |
| ARM64 node / python / sharp（qemu，取自成品 deb） | ✅ |
| `sha256sum -c`（10 个包） | ✅ 10/10 |

### 已知问题（非移植引入）

- `dsh-connect-workbuddy@1.4.0` 字段名不匹配（读 `info.multimodal`，
  而接口返回 `supportsImages`），导致 16/16 模型被算出 `inputModalities=["text"]`，
  发图报 `session/agent-busy`（真因被包装）。macOS/Windows 同理。
  规避：在设置中开启模型的图像开关。

---

## [1.0.0] — 2026-09-26 — 适配 `0.1.7-rc.1`

首个完整 Linux 移植版本（基于 Windows x64 安装包载荷），
覆盖 x86_64 与 aarch64 各 5 种格式，并首次实现：

- Sharp/libvips **进程隔离**方案（方案 A），解决 Linux 图片附件段错误；
- Linux 托盘修复（Electron 44.0.0 → 44.4.5、win32 门禁放行、PNG 图标、无托盘退出兜底）；
- 系统 Electron 兼容（`DSH_DESKTOP_RESOURCES_DIR`、`DSH_DESKTOP_FORCE_PACKAGED`、
  V8 指纹放宽）；
- 体积优化：Python 载荷 421 → 231 MB、Node 载荷 204 → 104 MB，压缩改用 xz / zstd。

> 该版产物与缓存后续被用户删除，其补丁与方案已在 2.0.0 中按新版重新实现。
