# DeepSeek Harness — Linux 移植产物

由官方 **macOS arm64** 安装包（`DeepSeek Harness 0.2.0-rc.2.dmg`）中的应用载荷重新打包为 Linux 版本。
上游应用：`@deepseek-ai/dsh-desktop 0.2.0-rc.2`。

覆盖 **x86_64** 与 **aarch64** 两种架构，各 5 种分发格式，共 **10 个产物**。

## 产物清单

### x86_64 (amd64)

| 文件 | 大小 | Electron | 适用发行版 |
|---|---|---|---|
| `DeepSeek-Harness-0.2.0-rc.2-x86_64.AppImage` | 291 MB | 内置 44.4.5 | 免安装，通用 |
| `deepseek-harness_0.2.0-rc.2_amd64.bundled.deb` | 255 MB | 内置 44.4.5 | Debian / Ubuntu |
| `deepseek-harness_0.2.0-rc.2_amd64.system.deb` | **167 MB** | 依赖系统 | Debian / Ubuntu |
| `deepseek-harness-desktop-0.2.0_rc.2-1-x86_64.pkg.tar.zst` | **181 MB** | 依赖系统 | Arch Linux |
| `deepseek-harness-0.2.0-0.rc2.x86_64.rpm` | 255 MB | 内置 44.4.5 | Fedora / openSUSE |

### aarch64 (arm64)

| 文件 | 大小 |
|---|---|
| `DeepSeek-Harness-0.2.0-rc.2-aarch64.AppImage` | 282 MB |
| `deepseek-harness_0.2.0-rc.2_arm64.bundled.deb` | 238 MB |
| `deepseek-harness_0.2.0-rc.2_arm64.system.deb` | **157 MB** |
| `deepseek-harness-desktop-0.2.0_rc.2-1-aarch64.pkg.tar.zst` | **172 MB** |
| `deepseek-harness-0.2.0-0.rc2.aarch64.rpm` | 239 MB |

> Arch 包只提供 `.pkg.tar.zst`（zstd 压缩，pacman 直接可用）。

## 安装

```bash
# AppImage（免安装）
chmod +x DeepSeek-Harness-0.2.0-rc.2-x86_64.AppImage
./DeepSeek-Harness-0.2.0-rc.2-x86_64.AppImage

# Arch Linux（pacman 自动安装 electron 元包 → electron44）
sudo pacman -U deepseek-harness-desktop-0.2.0_rc.2-1-x86_64.pkg.tar.zst

# Debian / Ubuntu
sudo apt install ./deepseek-harness_0.2.0-rc.2_amd64.bundled.deb

# Fedora / openSUSE
sudo dnf install ./deepseek-harness-0.2.0-0.rc2.x86_64.rpm
```

安装后从应用菜单启动「**DeepSeek Harness Desktop**」，或执行 `deepseek-harness`。
AppImage 需要 fuse；无 fuse 时加 `--appimage-extract-and-run`。

## 本次移植做了什么

### 1. 修复 Linux 图片附件崩溃（Sharp / libvips 段错误）

`sharp` 依赖的 libvips 在 Linux + Electron 下会触发段错误，而
`@deepseek-ai/dsh-attachment-local` 恰好在 Electron 进程内处理图片附件，导致桌面端整体崩溃。
SIGSEGV 是进程级信号，JS 层无法捕获，因此采用**进程隔离**：

```
resources/
├── app/dsh/node_modules/sharp/     替身包：只转发调用，不含原生库
└── image-worker/
    ├── client.cjs                  Sharp API 兼容层（记录链式调用 → 转发）
    ├── worker.cjs                  在独立 Node 进程中重放并执行 libvips 调用
    └── worker-modules/node_modules/ 私有依赖闭包（约 20 MB / 120 文件）
```

- worker 运行在**载荷自带的 standalone Node** 上，不含 Chromium/GTK 符号空间；
- 使用**独立私有依赖闭包**，与 `app.asar` 及 Electron 解析路径彻底隔离
  （standalone Node 无 asar 支持，这也是闭包必须置于 asar 之外的原因）；
- 子进程环境被清理，仅保留 `PATH`/`HOME`/`LANG`/`TMPDIR`，避免 Electron 库路径泄漏；
- worker 崩溃只影响当次图片操作，客户端自动重启并在连续失败 3 次后熔断，**不会拖垮桌面端**。

实测：加载 shim 前后 `/proc/self/maps` 中**始终无 libvips**；
`probeImage` / `detectImage` / `normalizeImage`（含质量阶梯、`clone` 复用、元数据复检）三条真实路径，
以及 jpeg / png(alpha) / webp / gif 四种类型全部通过；坏数据抛错而非崩溃。

### 2. 修复 Linux 托盘

| 问题 | 修复 |
|---|---|
| Electron 44.0.0 的 Linux 托盘回归 | 内置 Electron 升级至 **44.4.5** |
| 托盘仅在 `process.platform === "win32"` 时创建 | 放行 Linux |
| 托盘图标使用 Windows `.ico` | Linux 改用 PNG（`tray.png`，32×32） |
| 无托盘时关窗隐藏窗口 → 应用失联 | 无托盘时关窗直接退出 |

实测：真实 Electron 主进程构造 `Tray`，44.4.5 返回成功。运行时依赖系统的
`libappindicator3` / `libayatana-appindicator`（主流桌面环境默认自带）。

### 修复 — Linux 原生标题栏

官方在 win32 用 `titleBarStyle:"hidden" + titleBarOverlay`、在 darwin 用 `hiddenInset`，
**唯独 Linux 分支什么都没给**，于是 Linux 下窗口顶上多出一条原生标题栏（截图里的“应用 Edit”），
与界面自带的应用头叠成两层。

Linux 渲染层没有 `-webkit-app-region` 拖拽区、preload 也没有暴露窗口控制 API，
直接 `titleBarStyle:"hidden"` 会得到一个**既不能拖动也不能关闭**的窗口。
因此修复采用与 Windows 相同的 `titleBarOverlay`：GTK 负责绘制最小化/最大化/关闭按钮，
标题区保持可拖动，主窗口（40px）与欢迎窗口（42px）都已适配。

实测：补丁后应用正常启动（web-ready），此前全部修复不受影响。

### 新增 — macOS 风格窗口装饰（左置交通灯 + 侧栏毛玻璃）

官方只为 win32（`titleBarStyle:"hidden"` + `titleBarOverlay`）与 darwin（`hiddenInset` + `vibrancy`）
配置了窗口装饰，Linux 分支为空，因此先前版本会看到系统原生标题栏（或右侧的系统按钮）。

现在 Linux 采用与 macOS 一致的布局：**左上角红黄绿交通灯 + 侧栏半透明毛玻璃**。

实现方式不是自造一套，而是**复用应用自带的机制**：

| 复用的东西 | 来源 | 作用 |
|---|---|---|
| `html[data-windows-titlebar]` | 应用自身的「自绘标题栏」模式（原本只在 Windows 启用） | 顶部 48px 预留带、自动拖拽区（`-webkit-app-region:drag`）、页面标题内边距、折叠按钮重定位 |
| `color-mix(in srgb, var(--dsw-specific-sidebar-fill) 50%, transparent)` + 竖向渐变 | 应用自身的 `[data-platform=darwin]` 侧栏规则 | 侧栏半透明底色 |
| `backdrop-filter: blur(40px) saturate(150%)` | 应用菜单材质用的同一档位 | 毛玻璃 |
| `trafficLightPosition {x:16, y:18}` | 应用自身的 macOS 常量 | 交通灯坐标 |

同时**刻意不改 `data-platform`**：该属性不只切材质，也决定快捷键把 `primary` 解析成
Meta(⌘) 还是 Control —— 伪造 `darwin` 会让 Linux 上的快捷键显示成 ⌘ 且修饰键映射错误，
因此这里只复刻材质数值，`data-platform` 保持 `linux`。

配套的窗口层改动：Linux 主窗口与欢迎窗均改为 `titleBarStyle:"hidden"` + `transparent:true`
（欢迎窗额外 `frame:false`），移除上一版的 `titleBarOverlay`；交通灯点击经
`dsh-desktop:linux-window-control` IPC 走最小化 / 最大化切换 / 关闭。
最大化切换对 Wayland 合成器（如 niri 不实现 `isMaximized()`）做了兜底：按窗口是否已铺满工作区判断。

验证：侧栏像素实测为 `srgba(28,28,28,0.5)`（真 50% 透明），内容区保持 `alpha=1` 以保证可读性；
顶部拖拽带 48px 且 `app-region:drag`；交通灯位于 (16,18)。

**模糊为何不放在侧栏元素上**：`backdrop-filter` 有三个副作用 —— 它会让元素成为
`position:fixed` 后代的包含块并按自身 `overflow` 裁切、新建 backdrop root、
并使整棵子树参与模糊面合成（文字因此发虚）。初版把它直接加在侧栏上，
导致「折叠后按钮被裁掉、无法再次展开」「侧栏右缘缺口」「文字发灰」三个问题。

现由独立、`pointer-events:none` 的背景层 `#dsh-mac-vibrancy` 承担模糊与色调，
且该层被插到 `#root` **之前**并设 `z-index:-1`，真正位于整个 UI 之下；
侧栏只保持 `background:0 0`。视觉效果不变，但不再影响布局、命中测试与文字清晰度。

**全屏与圆角**：应用为 Windows 无边框窗口给内容区加了 `border-radius:16px 0 0 0`，
铺满屏幕时该圆角外侧会露出空白（KDE Plasma 上同样可见），已置零。
全屏行为对齐应用的 macOS 规则：隐藏红黄绿交通灯、折叠键回到左侧 `left:12px`。

**全屏检测为何需要三层**：上游把 Linux 同时排除在主进程事件注册（`darwin || win32`）
和 preload 监听（`syncWindowFullscreen` 早退）之外；而平铺合成器（niri / Hyprland / sway）
又不会向 Electron 报告全屏（实测铺满屏幕时 `isFullScreen()` 与 `isMaximized()` 均为 false）。
因此渲染层额外做视口自检：视口覆盖屏幕可用区域即视为全屏，与主进程状态取并集。

**侧栏底部暗条**：应用自身的列表滚动淡出层渐变到 `--dsw-specific-sidebar-fill`，
该变量是不透明的 `rgb(27,27,28)`，侧栏透明后终点色不再匹配。改由
`--dsh-linux-sidebar-tint` 承载半透明值，任何引用它的组件自动跟随。

**折叠态按钮位置**：应用把折叠后的导轨按钮写死在 `left:48px` / `88px`（Windows 的窗口
按钮在右侧，左侧是空的）。本移植在左侧放交通灯（16–68px），因此在**窗口模式**下把
这两个按钮右移到 88px / 128px；**全屏时交通灯隐藏，不需要让位**，保留应用原本的
48px / 12px。展开态的侧栏 toggle 同理只在窗口模式贴右缘。

> 说明：真正的「桌面模糊」由合成器决定 —— `backdrop-filter` 只能模糊页面内内容，
> 桌面背景的模糊需要 KWin / Hyprland 等支持窗口模糊的合成器；niri 等无模糊的合成器
> 上表现为「半透明但桌面清晰」，透明度本身在所有合成器上都生效。

### 3. 平台与其他适配

- **平台准入**：`["win32","darwin"]` 白名单加入 `"linux"`，否则启动即抛
  `desktop policy: unsupported platform`。
- **平台上报**：`x-client-platform` 对 Linux 上报 `desktop-linux`。
- **原生模块全部替换**为 linux 预编译产物（sharp / koffi / sherpa-onnx / ripgrep /
  node-addon-require-builtin / node-addon-system(landlock) / node-pty / reflink），
  两架构各一套。
- **Office 引擎**：Linux 无官方原生 LibreOfficeKit 包，改用官方
  `@deepseek-ai/libreoffice-kit-wasm@0.1.0`（应用代码本身对 Linux 就走 WASM 回退路径）。
- **运行时载荷**：Linux 版 Node 24.21.0 + Python 3.12.14（13 个科学计算包）+ pnpm 11.7.0；
  `runtime.json` 的 `platform`/`arch` 修正为 `linux` / `x64|arm64`。
- **系统 Electron 兼容**：
  - `DSH_DESKTOP_RESOURCES_DIR` 覆盖 resources 根（原实现依赖 `process.resourcesPath`，
    在系统 Electron 下会指向 `/usr/lib/electron44/resources` 而失效）；
  - `DSH_DESKTOP_FORCE_PACKAGED=1` 让系统 Electron 加载 app 目录时不被误判为开发模式。
- **V8 指纹门禁**：`node-addon-require-builtin` 原生插件只接受 Electron
  43.0.0 / 44.0.0 / 45.0.0-alpha.6 三个精确 V8 指纹，系统 Electron（44.4.5）会被拒。
  已对其匹配函数做二进制放宽（x64 `0x17cdd`、arm64 `0x1df14`），
  三个 profile 的 ABI 字段是编译期常量、仅版本标签不同，放宽安全——
  **不降级 Electron，任意 4x 版本均可运行**。
- **新增 `runtime/cli`**：0.2.0 起官方新增了 CLI 安装功能，其 macOS 启动器
  （引用 `../MacOS/DeepSeek Harness` 与 `resources/app.asar/...`）已改写为 Linux 版本，
  能自动定位 electron 或内置二进制来运行 `dsh-desktop-host/lib/cli.js`。
- **更新器**：官方无 Linux 更新源（`feeds/linux-x64` 返回 404），移除 `app-update.yml`。
- **桌面项**：`Name=DeepSeek Harness Desktop`（含中文名）、`Exec=deepseek-harness`、
  16→512 全套 hicolor 图标、`StartupWMClass`。
- **Arch 包名**为 `deepseek-harness-desktop`（而非 `deepseek-harness`），
  以免顶掉 archlinuxcn 仓库的 npm 版 `deepseek-harness`（该包提供 `/usr/bin/dsh`，
  与本桌面版零路径冲突，可共存）。桌面版仍提供 `/usr/bin/deepseek-harness`。

## 依赖策略（system-wide Electron 变体）

| 发行版 | 包名 | 官方仓库 | 本包声明 |
|---|---|---|---|
| Arch Linux | `electron`（元包 → `electron44`） | 有 | `depend = electron`（pacman 自动连带安装） |
| openSUSE Tumbleweed | `nodejs-electron`（`Provides: electron`） | 有 | 启动器运行时探测 |
| Fedora Rawhide | `nodejs-electron`（`Provides: electron`） | 有 | 启动器运行时探测 |
| Fedora 稳定版 / EPEL | — | 无 | 建议用 bundled / rpm 内置版 |
| Debian / Ubuntu | — | **无** | electron 置于 **`Recommends`** |

> Debian/Ubuntu 官方仓库不存在 electron 包，硬依赖会导致 `apt install` 直接失败
> （`electron : Depends: electron but it is not installable`），故改用 `Recommends`：
> 有则自动安装，无则照常安装并由启动器给出明确提示。
> Debian/Ubuntu 用户建议直接用 `*.bundled.deb`。

启动时依次探测 `electron` / `electron44` … / `nodejs-electron`，
以及 `/usr/lib/electron44/electron`、`/usr/lib/electron/electron`、
`/usr/lib64/electron/electron`、`/usr/lib/nodejs-electron/electron`、`/opt/electron/electron`。

## 验证记录

| 项目 | 方式 | 结果 |
|---|---|---|
| x64 五种格式 | 解包后实际启动，`dsh web: http://127.0.0.1:19387/` 正常监听 | ✅ 5/5 |
| Sharp 隔离 | `/proc/self/maps` 无 libvips + 三条 attachment 路径 + 四种图片类型 | ✅ |
| 托盘 | 真实 Electron 主进程构造 `Tray` | ✅ |
| ARM64 node | qemu 运行成品 deb 内 node 24.21.0 arm64 | ✅ |
| ARM64 python | numpy 2.3.5 / pandas 3.0.1 / Pillow 12.3.0 + 运算 | ✅ |
| ARM64 sharp | libvips 8.18.6 完整编解码（jpeg/webp/resize） | ✅ |
| 架构审计 | x64 树无 arm64 残留、arm64 树无 x86-64 残留 | ✅ 0 处 |
| 交通灯左置 + 侧栏透明 | 侧栏像素实测 alpha=0.5；交通灯位于 (16,18)；`data-platform` 保持 linux | ✅ |
| 10 个包 | `sha256sum -c SHA256SUMS.txt` | ✅ 10/10 |

## 已知问题

- **`dsh-connect-workbuddy` 插件图片误拒**（与本次移植无关）：第三方插件
  `dsh-connect-workbuddy@1.4.0` 的 `lib/index.js:81` 读取了错误字段名 ——
  判断 `info.multimodal`，而 WorkBuddy 接口返回的字段是 `supportsImages`，
  导致全部 16 个模型被算出 `inputModalities = ["text"]`，
  发送图片时报 `session/agent-busy`（真实原因被包装在 `reason` 字段，
  实为 `session/attachment-invalid`），文字消息不受影响。
  规避：在 WorkBuddy 设置中开启对应模型的图像开关（插件的 `imageModelIds`
  会注入 `multimodal: true`）。

## 校验

```bash
sha256sum -c SHA256SUMS.txt
```
