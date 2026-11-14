# Changelog

DeepSeek Harness 桌面端（Electron）的 Linux 移植/重打包记录。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [3.7.1] — 2026-11-14 — 跟进上游 `0.2.2-rc.3`

上游桌面端升级到 `0.2.2-rc.3`，本版重跑整条构建链并对齐 `main` 基线。

### 修复

- `scripts/assemble-tree.sh`：自动探测 `others/dmg` 下最新的上游目录，不再写死版本号；
  上游已移除 `runtime/office-skills`，改为存在才复制；装配时补 `resources/tray.png`。
- `patches/patch-titlebar.py`：rc.3 把窗口选项移入 `createWindow()` 并在 win32 分支新增字段，
  改用整块匹配再追加 Linux 分支，不再依赖块内字段顺序。
- `patches/patch-mac-chrome.py`：按 rc.3 的 `import` 列表动态插入 `screen`，并保留语句分号。
- `swap-native-linux.sh`：`file | grep` 无匹配时不再因 `pipefail` 静默中止；
  清理上游自带的 win32/darwin prebuilds。
- 恢复 `scripts/` 下 5 个脚本的可执行位，避免 `Permission denied`。

### 产物

x86_64 与 aarch64 各 4 种格式，共 8 个应用包，另附 2 个 `electron45` 运行时包。
详见 `docs/ARTIFACTS.md`。

---

## [3.6.0] — 2026-11-13 — 修复 Sharp 隔离未进入安装包

### 修复

- 成品包中 `resources/image-worker/` 缺失、`sharp` 仍是原生包，图片处理失去进程隔离保护。
- `build-packages.sh` 现在每次打包都强制安装 Sharp 隔离并清理原生备份。
- `install-image-worker.sh` 改为幂等，可从备份或 worker 私有闭包恢复原生 sharp。
- 验证脚本改为检查 facade 标记，不再因原生包与 facade 入口路径相同而误判通过。
- 新增 `tests/test-image-worker.sh`，覆盖大图、动画 GIF、并发与异常图片。

### 验证

JPEG / PNG / WebP / GIF、6000×4000 大图、两帧 GIF、4 路并发、坏数据与截断 JPEG 全部通过，
Electron 主进程始终未加载 libvips。

---

## [3.5.0] — 2026-11-13 — 修复 netlink 失败重试刷爆 syslog

### 修复

- Chromium 的 netlink 收包失败后无退避重试，导致日志风暴。
- 新增 `netlink-guard/netlink_guard.c`：仅对 `AF_NETLINK` 的 `EACCES`/`EPERM`/`ENOBUFS`
  施加 1/2/4…60 秒指数退避，保留原错误，普通 socket 不受影响。
- 四种格式的启动器统一注入该守卫；可用 `DSH_NETLINK_GUARD=0` 临时关闭。
- 详见 `docs/NETLINK-GUARD.md`。

---

## [3.4.0] — 2026-11-07 — Arch 安装失败修复

### 修复

- `libuuid` 不是 Arch 包名，改由 `util-linux` 提供；移除 `.PKGINFO` 中的注释行。
- 删除错误的 `conflicts` 键，并放开 Electron 39–45 任意版本。
- 启动器按版本从高到低探测，支持 `DSH_ELECTRON_BIN` 指定。
- 新增 `electron45` 运行时包。

---

## [3.3.0] — 2026-11-07 — 工具链升级与 Electron 45 支持

### 新增

- `scripts/build-electron-pkg.sh`：把官方 Electron 打包成 Arch 运行时包。
- `scripts/swap-electron.sh`：只替换 Electron 骨架，保留应用与运行时。
- `docs/COMPAT-TOOLCHAIN.md`：Electron、Node、pnpm、Python 的升级实测记录。

### 修复

- `.pkg.tar.zst` 依赖 `electron` 改为可用的版本探测链。
- 修正 Linux 下失效的 CLI 入口。
- 补上 `ZSTD_OPTS` / `ZSTD_LEVEL` 默认值，并支持 `FORMATS` / `DSH_OUT` 局部构建。

---

## [3.2.0] — 2026-10-31 — 跟进上游 `0.2.1-rc.5`

- 应用载荷升级到 `0.2.1-rc.5`，重建双架构 8 个产物。
- 构建脚本改为从 `runtime.json` 自动读取版本号。
- 四格式统一使用 zstd 压缩。

---

## [3.1.0] — 2026-10-25 — 修复 Agent 预设与托盘图标

### 修复

- 裁剪脚本误删 `dsh-sandbox-windows-acl`，导致标准/PTC/创造预设「加载失败」。
  该包是静态 import 依赖，现已保留并加自检。
- 托盘图标不显示：补 `resources/tray.png`，并在缺失时回退。

---

## [2.0.0] — 2026-10-01 — 适配上游 `0.2.0-rc.2`

- 完成 Linux 平台移植：平台准入、原生模块替换、运行时装配。
- 修复 Sharp/libvips 在 Electron 内的段错误，改为独立进程处理图片。
- 实现 macOS 风格窗口装饰（左置交通灯、侧栏毛玻璃）。
- 首次产出双架构、多格式安装包。

---

## [1.0.0] — 2026-09-26 — 首个可用版本

- 从官方 macOS 包提取载荷，完成 Linux 打包流程验证。
