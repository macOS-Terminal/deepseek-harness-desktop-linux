# 工具链升级与兼容性测试（2026-11-07）

本轮把移植链上所有"可升级"的组件都试到当前最新稳定版，逐项做真实构建/启动验证，
记录哪些能用、哪些有坑。**所有结论都来自本机实测**，不是推断。

测试基线：上游 `0.2.2-rc.1`（dmg `dsh-latest-macos-arm64.dmg`，268,886,612 字节）。

## 结论速览

| 组件 | 基线版本 | 最新稳定版 | 实测结论 | 本轮处置 |
|---|---|---|---|---|
| Electron | 44.7.0 | **45.2.3** | ✅ 可用 | 已出 `electron45` 包，DSH 的 `pkg.tar.zst` 已放行 |
| Node.js | 24.21.0 | **26.13.0**（LTS "Krypton" 之后一条线） | ✅ 可用 | 仅测试，产物仍用 24.21.0 |
| pnpm | 11.28.5 | **12.18.0** | ⚠️ 需改载荷结构，否则普通用户直接失败 | 给出方案，产物仍用 11.28.5 |
| npm | 11.9.0 | **12.2.2** | ❌ 本项目不可用（`workspace:` 协议） | 不升级 |
| Python | 3.12.14 | **3.15.2**（3.16.0 只有 a1） | ❌ 受阻（wheel + 构建来源） | 不升级 |

> 版本口径：`electron@latest` = 45.2.3、`pnpm@latest` = 12.18.0、`npm@latest` = 12.2.2、
> `node` 最新 LTS = 26.13.0、Python 最新正式版 = 3.15.2（`3.16.0` 目录下只有 `3.16.0a1`）。

## 1. Electron 45.2.3 —— 可用，但要重新确认三件事

实测运行时信息（`ELECTRON_RUN_AS_NODE` 下读 `process.versions`）：

```
node 24.22.2   modules(ABI) 150   v8 15.6.75.27-electron.0
```

- **指纹门禁**：`node-addon-require-builtin` 只接受 `43.0.0 / 44.0.0 / 45.0.0-alpha.6`
  三套指纹，45.2.3 会落在门外。`patches/patch-fingerprint.py` 走 ELF 符号表定位
  `Matches(...)`，与 Electron 版本无关，45 下仍然命中同一地址
  （x64 `@0x1808f`，patch 后 `b8 01 00 00 00 c3`），**无需改补丁**。
- **原生模块 ABI**：9 个平台包全部加载成功，没有 `NODE_MODULE_VERSION` 冲突：

  | 模块 | 结果 |
  |---|---|
  | sharp / sharp-libvips | ✅ |
  | koffi | ✅ |
  | node-pty | ✅（`spawn|fork` 可用） |
  | sherpa-onnx-node | ✅ |
  | @vscode/ripgrep | ✅ |
  | node-addon-require-builtin | ✅ |
  | @deepseek-ai/libreoffice-kit | ✅ |

  只有一条上游警告（44 时代就存在，不是 45 引入的）：

  ```
  [SharpElectronLinux] Warning: Binaries provided by Electron for use on Linux
  may be incompatible with sharp — https://sharp.pixelplumbing.com/install#electron-and-linux
  ```
  sharp 在 Electron 下走自带 libvips，实测图片编解码正常，可忽略。
- **行为回归**：GUI 启动出 `dsh web`、Agent 预设四模式
  （standard / ptc / minimal / cordis）`broken=(无)`、托盘 `nativeImage` 非空
  32×32 —— 与 44.7.0 基线一致。

`electron45` 包安装布局（`scripts/build-electron-pkg.sh`）：

```
/usr/lib/electron45/{electron,*.pak,*.so,icudtl.dat,locales/,resources/}
/usr/bin/electron45 -> /usr/lib/electron45/electron
chrome-sandbox 权限 4755（tar 里就是 rwsr-xr-x，pacman 直接生效）
provides = electron45, electron
```

> 踩坑：最初打包时按"精简"思路删了 `resources/default_app.asar`，结果
> `electron45 /path/to/app` 这种跑别人应用的用法静默失效（进程起来但没有窗口、
> 也没有任何报错）。Arch 官方 electron 包是保留它的，本包已保留并在脚本里加了断言。

## 2. Node.js 26.13.0 —— 可用

- dmg 载荷里是 24.21.0。把 `runtime/primary-runtime/dependencies/node` 换成 26.13.0 后：
  - GUI 启动正常；
  - `dsh-desktop-host/lib/cli.js --version` → `0.2.2-rc.1`；
  - 直接用它跑 profile 引导（不经 Electron），四预设依旧 `broken=(无)`。
- 注意：**node 26.13.0 自带的是 npm 11.20.0**，不是 npm 12；想要 npm 12 得单独装。
- 本轮产物仍用 24.21.0：Electron 45 内嵌的是 Node 24.22.2，载荷跟着它走可以少一套
  运行时语义，没必要为了"版本新"而分叉。

## 3. pnpm 12.18.0 —— ⚠️ 载荷模型变了，直接替换会坏

pnpm 12 不再是纯 JS 包：

- `bin/` 只剩 `pnpm.mjs` / `pnpx.mjs` 两个入口，`pnpm.cjs` 没了；
- 真正的实现是**平台原生二进制**（`@pnpm/exe.linux-x64` 等，解压 60.9 MB）；
- 包装器在**首次运行时**下载它并写进**包目录**：

  ```
  $ node bin/pnpm.mjs --version
  Downloading the pnpm 12.18.0 binary for linux-x64...
  12.18.0
  $ ls
  pnpm-native        # 60 MB，落在包装器旁边
  ```

**实测故障**（模拟系统安装：目录 root 所有、普通用户调用）：

```
$ su nobody -c 'node bin/pnpm.mjs --version'      # 目录只读
Downloading the pnpm 12.18.0 binary for linux-x64...
Could not download the pnpm 12.18.0 binary: EACCES: permission denied,
  open '/usr/lib/deepseek-harness/.../pnpm/pnpm-native.<hash>.tgz'
```

也就是说：**装到 `/usr/lib` 之后，任何非 root 用户第一次用 pnpm 都会失败**；
即使有写权限，也要联网从 registry 拉 60 MB（离线环境直接废）。

可行方案（已验证）：把平台包预置进包装器自己的 `node_modules`，包装器会优先用它，
不再下载：

```
dependencies/pnpm/node_modules/@pnpm/exe.linux-x64/{pnpm,package.json}   # 60.9 MB
```

实测 `pnpm install` 正常（`+ semver 7.8.5, Done in 2.7s using pnpm v12.18.0`），
桌面端 profile 引导 + 四预设也全部通过。

两个附带的坑：

1. `@pnpm/exe.linux-x64` 的 `dist-tags.latest` 仍是 **12.0.0**，必须显式写 `12.18.0`，
   否则包装器与自身版本错配。
2. store 目录版本号变成 `~/.pnpm/store/v11`，与 pnpm 11 的 store 不通用，
   老用户升级后第一次装包会全部重新下载。

因此本轮**不把 pnpm 12 塞进产物**：要多带 60 MB/架构的原生二进制，收益不足以抵消
风险。方案记在这里，等上游自己升到 pnpm 12 时照此预置即可。

## 4. npm 12.2.2 —— 本项目用不了

`app-new/package.json` 里是 pnpm workspace 协议：

```
$ npm install --dry-run
npm error code EUNSUPPORTEDPROTOCOL
npm error Unsupported URL Type "workspace:": workspace:*
```

npm 全系（含 12.2.2）都不支持 `workspace:*`，构建/装配链只能走 pnpm。
这不是 npm 12 的问题，但意味着"把 pnpm 换成 npm"不可行，别被"统一工具链"的思路带偏。

## 5. Python 3.15.2 —— 受阻，两个独立原因

### 原因一：wheel 没有 cp315 版本（`pip download --only-binary=:all: --python-version 3.15`）

| 包 | 载荷锁定版本 | cp312 | cp315 | 建议 |
|---|---|---|---|---|
| numpy | 2.3.5 | ✅ | ❌ 无该版本 | 需升到 **2.5.4** |
| pandas | 3.0.1 | ✅ | ❌ 无该版本 | 需升到 **3.1.1** |
| Pillow | 12.3.0 | ✅ | ✅ | 可用（最新 13.0.0） |
| lxml | 6.1.3 | ✅ | ✅ | 可用 |

`runtime.json` 里的 `pythonPackages` 是**硬编码版本**，升 Python 必须同步升
numpy/pandas，否则启动即 `ImportError`（site-packages 里是 `.so`，ABI 不跨版本）。

### 原因二：拿不到可用的 Python 3.15 构建

`python-build-standalone` 最新 release（`20261026`）的 `install_only_stripped`
只到 `3.13.18`，没有 3.14/3.15/3.16 产物；python.org 侧 `3.16.0` 只有 `3.16.0a1`。
要上 3.15 就得自己从源码编译，并重做整套交叉 pip 安装 —— 这不是"顺手升级"的量级。

结论：**Python 保持 3.12.14**。真要升，按 3.13 → 3.15 分两步走，每一步都要
重建 `pythonPackages` 版本矩阵。

## 6. 顺手修掉的构建脚本 bug

| 问题 | 症状 | 修法 |
|---|---|---|
| `ZSTD_OPTS` / `ZSTD_LEVEL` 从未定义 | 单独运行 `build-packages.sh` 在 `set -u` 下直接 `unbound variable`，deb 与 pkg.tar.zst 两处都炸（历史构建是靠外部环境变量掩盖的） | 脚本内给默认值 `-19 -T0 --long=27` / `19` |
| `pkg.tar.zst` 不认 electron45 | `depend = electron` + 启动器只搜到 `electron44`，装了 electron45 也用不上 | `depend = electron45`，启动器搜索链把 `electron45` 提到最前，`optdepend` 保留发行版 electron/nodejs-electron 作为替代 |
| CLI 入口是 macOS 专用路径 | `runtime/cli/bin/dsh` 里写死 `$resources/../MacOS/DeepSeek Harness` 与 `app.asar/dsh/...`，Linux 下必然 `not found` | `pkg.tar.zst` 打包时重写该脚本：按 `electron45 → electron → nodejs-electron` 找运行时，`app/dsh/...` 直连（实测 `dsh --version` → `0.2.2-rc.1`） |
| 只能整包构建 | 验证单个格式要重跑 1.3 GB 的 AppImage | 新增 `FORMATS=deb,pkgtar,rpm,appimage` 与 `DSH_OUT=<目录>` |

## 7. 未做与风险

- **arm64 只做了装配 + 架构核验 + 打包**，没有真机/模拟器启动测试（本机是无
  binfmt 的 x86_64）。x64 侧所有结论都经过实际启动，arm64 仅验证二进制架构一致、
  包结构与元数据正确。
- pnpm 12 / Node 26 / Python 3.15 的结论来自单机单次测量，没有做长跑稳定性测试。
- `electron45` 包只提供运行时，不含 `electron` 的 `/usr/bin/electron` 入口
  （避免与发行版 electron 抢占同名文件）；如果别的包硬依赖 `electron` 可执行文件，
  需要装发行版 electron，两者可以共存（路径不重叠）。
