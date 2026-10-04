# deepseek-harness-desktop-linux

把 **DeepSeek Harness 桌面端**（官方仅发布 macOS / Windows 包）移植到 Linux 的
**重新打包工具链**：官方 dmg 载荷 + 若干公开下载物 → AppImage / deb / pacman / rpm。

覆盖 **x86_64** 与 **aarch64**，共 10 个发行包。

上游应用版本：`@deepseek-ai/dsh-desktop 0.2.0-rc.2`

> 本仓库只包含**移植补丁与打包脚本**，不含任何官方二进制载荷（体积与授权原因）。
> 详细的中文使用教程见 **[README.zh.md](README.zh.md)**。

---

## 这个移植在解决什么

官方代码里 Linux 分支基本是空实现，因此移植 = **补齐那些空分支**。逐项：

| # | 问题 | 处理 |
|---|---|---|
| 1 | `main.js` 平台白名单只有 `win32` / `darwin`，Linux 启动即 `unsupported platform` | 加入 `linux`，并上报 `x-client-platform: desktop-linux` |
| 2 | 原生模块只带 macOS / Windows 预编译产物 | 换成 `@img/sharp-linux-*`、`@koromix/koffi-linux-*`、`node-pty` prebuilds 等 9 类 |
| 3 | 运行时载荷是 macOS 构建 | 换 Linux 版 Node 24.21.0 + Python 3.12.14（13 个科学计算包）+ pnpm |
| 4 | 原实现依赖 `process.resourcesPath`，系统 Electron 下指错目录 | `DSH_DESKTOP_RESOURCES_DIR` 覆盖 |
| 5 | 系统 Electron 下 `app.isPackaged` 为 false，被误判为开发模式 | `DSH_DESKTOP_FORCE_PACKAGED=1` |
| 6 | 原生插件只认 Electron 43.0.0 / 44.0.0 / 45.0.0-alpha.6 的 V8 指纹 | 二进制放宽匹配（**不降级 Electron**） |
| 7 | **libvips 在 Electron 内段错误，JS 无法捕获，整个应用崩溃** | 进程隔离：Sharp 调用转发到独立 Node worker |
| 8 | Linux 无窗口装饰规则，且托盘代码被 `win32` 门禁挡住 | 复用应用自身的 `data-windows-titlebar` 模式 + 复刻其 darwin 材质配方 |

---

## 目录结构

```
├── patches/
│   ├── patch-main.py            平台准入 / resources 根 / 打包态 / 托盘 / 窗口控制 IPC
│   ├── patch-mac-chrome.py      macOS 风格装饰：左置交通灯 + 侧栏毛玻璃
│   ├── patch-fingerprint.py     放宽 V8 指纹白名单（x64 0x17cdd、arm64 0x1df14）
│   ├── patch-titlebar.py        早期隐藏标题栏方案（已被 patch-mac-chrome 取代）
│   └── upgrade-mac-chrome.py    对已打过旧版 chrome 的树做增量修复（幂等）
├── image-worker-src/
│   ├── client.cjs               Sharp API 兼容层（Electron 内，只记录并转发）
│   ├── worker.cjs               真正执行 libvips 的独立 Node 进程
│   └── verify-image-worker.cjs  隔离效果自检
├── icons/                       桌面项 + 16→512 全套 hicolor 图标
├── auto-build.sh                自动下载、生成应用树并打 AppImage
├── scripts/                     asar 解包、原生依赖替换与分阶段构建模块
├── tests/                       离线构建回归测试
├── build-packages.sh            兼容入口，调用共用打包模块生成全部格式
├── install-image-worker.sh      把 Sharp 替身包装入某棵应用树
├── verify-launch-x64.sh         五种格式逐个解包并实测启动
└── docs/
    ├── ARTIFACTS.md             产物说明：安装方式、依赖策略、验证记录
    ├── CHANGELOG.md             完整变更日志（含每个修复的根因与实测数据）
    └── SHA256SUMS.txt           本次构建 10 个产物的校验和
```

---

## 快速开始

### 自动构建安装包

```bash
./auto-build.sh --dry-run       # 查看计划，不下载、不写入
./auto-build.sh                 # 按本机架构下载、生成应用树并打包
./auto-build.sh --formats all   # 构建全部五种格式
./auto-build.sh --arch all      # 构建 x86_64 与 aarch64
```

需要 Bash、Python 3.12+、7z、curl、tar、xz、unzip 和 coreutils；Python 还需
pip 或 venv 支持。首次安装这些系统工具可能需要管理员权限，构建本身无需 root。
详细选项、版本策略、缓存与验证方法见 [自动构建指南](docs/AUTO_BUILD.md)。
默认保留缓存、解包文件与构建暂存；`--clean` 可在成功后清理中间物。
默认生成 AppImage；`--formats deb,pacman,rpm` 可选择其他格式。对应打包工具需自行安装。

### 手工构建全部格式

```bash
# 1) 按 README.zh.md 准备依赖（官方 dmg、Electron、Node/Python、原生模块、打包工具）
# 2) 生成应用树
python3 patches/patch-main.py        out-x64/resources/app
python3 patches/patch-mac-chrome.py  out-x64/resources/app
python3 patches/patch-fingerprint.py out-x64/resources/app/dsh/node_modules/node-addon-require-builtin-linux-x64-gnu/prebuilt/linux-x64-gnu-napi-v9.node
./install-image-worker.sh out-x64 x64
# 3) 打包
./build-packages.sh x64
./build-packages.sh arm64
# 4) 验证
./verify-launch-x64.sh && (cd dist && sha256sum -c SHA256SUMS.txt)
```

完整的前置依赖清单、交叉打包注意事项与常见坑，见 **[README.zh.md](README.zh.md)**。

---

## 两个值得说明的实现

### Sharp / libvips 进程隔离

SIGSEGV 是进程级信号，JS 层无法捕获，因此**只能真正隔离进程**：

```
resources/
├── app/dsh/node_modules/sharp/     替身包：只转发调用，不含原生库
└── image-worker/
    ├── client.cjs                  记录链式调用 → 转发给 worker
    ├── worker.cjs                  在独立 Node 中重放并执行 libvips
    └── worker-modules/node_modules/ 私有依赖闭包（standalone Node 读不了 asar）
```

worker 崩溃只影响当次图片操作：客户端自动重启，连续 3 次失败后熔断，桌面端不受影响。

### macOS 风格窗口装饰

不自造轮子，而是**复用应用自带机制**：

- 用 `html[data-windows-titlebar]`（原本只在 Windows 启用的自绘标题栏模式）拿到
  48px 顶部预留带、自动拖拽区与页面内边距；
- 交通灯按应用自身常量 `trafficLightPosition {x:16, y:18}` 绘制，点击走新增 IPC；
- 侧栏毛玻璃**逐字复刻**应用 `[data-platform=darwin]` 的配方
  （`color-mix(... 50%, transparent)` + 竖向渐变 + `backdrop-filter: blur(40px) saturate(150%)`）；
- **刻意不改 `data-platform`**：该属性同时决定快捷键把 `primary` 解析成 ⌘ 还是 Ctrl，
  伪造 darwin 会破坏 Linux 快捷键语义。

---

## 已知问题（非本移植引入）

- `dsh-connect-workbuddy@1.4.0` 读 `info.multimodal`，而接口返回 `supportsImages`，
  导致 16/16 模型被算出 `inputModalities=["text"]`，发图报 `session/agent-busy`。
  macOS / Windows 上同样存在。

---

## 许可

应用本体版权归 **DeepSeek**。本仓库只做重新打包的工具链，不修改业务逻辑；
请遵守原应用许可条款，勿将重打包产物用于商业分发。
