# 自动构建 AppImage

`auto-build.sh` 将官方 macOS arm64 dmg 载荷转换为 Linux AppImage，支持
x86_64（`x64`）与 aarch64（`arm64`）。它自动准备依赖、生成应用树并打包；
不改变现有窗口补丁。deb、pacman、rpm 仍由 `build-packages.sh` 生成。

## 依赖与首次运行

需要 Bash、Python **3.12 或更新版本**、7z（或 7za）、curl、tar、xz、unzip、
sha256sum、realpath 和其他 coreutils 命令。Python 需要 pip，或能够通过 venv 创建
带 pip 的环境。Python 辅助脚本仅使用标准库。

Debian/Ubuntu 可安装这些系统工具（需要管理员权限）：

```bash
sudo apt install bash python3 python3-pip python3-venv p7zip-full curl tar xz-utils unzip coreutils
```

若发行版的 Python 低于 3.12，请使用已有的 Python 3.12+ 环境，将其 `python3`
放在 PATH 前面。构建本身无需 sudo。可选安装 `squashfs-tools` 以复用系统
`mksquashfs`；否则从本机架构的 appimagetool 提取并检查其能否运行。
`xvfb-run` 可用于本机架构的启动冒烟测试，托盘图片转换可选用 ffmpeg。

在仓库目录运行：

```bash
./auto-build.sh --dry-run
./auto-build.sh
./auto-build.sh --arch all
```

默认按本机架构构建。跨架构生成应用树与打包不需运行目标二进制，但目标架构的
Sharp/启动测试会跳过；应在目标机器上另行验证。首次运行需下载较大的 dmg、
Electron 与运行时归档，并预留数 GB 的解包、应用树和打包空间。

## 分阶段构建

| 阶段 | 内容 |
|---|---|
| `prepare` | 获取 dmg，读取运行时版本，下载 Electron/Node/Python 与 AppImage 工具并校验 |
| `tree` | 展开 asar，替换 Linux 运行时与原生包，运行现有补丁，安装 Sharp worker 和 Linux CLI 启动器 |
| `package` | 生成 AppDir，用 mksquashfs 和 type2 runtime 组装 AppImage，写出校验和 |

```bash
./auto-build.sh --only prepare
./auto-build.sh --only tree
./auto-build.sh --only package
```

`--only` 可以组合阶段，例如 `--only tree,package`。无论参数中的顺序如何，
均按 prepare → tree → package 执行。后两个阶段需要前一阶段的缓存或应用树。
完整流程中的 `tree` 阶段每次从 dmg 生成新树，避免重复应用非幂等补丁。

需要其他格式时保留应用树，再运行原有脚本：

```bash
./auto-build.sh
./build-packages.sh x64
```

注意：原有 `build-packages.sh` 的版本元数据是固定的；使用其他 dmg 版本前应先核对
该脚本。自动 AppImage 名称从 dmg 的 runtime.json 读取应用版本。

## 输入与缓存

```bash
./auto-build.sh --dmg /absolute/path/to/app.dmg
./auto-build.sh --dmg https://example.com/app.dmg
./auto-build.sh --store /tmp/dsh-store
./auto-build.sh --work /tmp/dsh-package
```

本地 dmg 不会被下载或覆盖。URL dmg 下载到 `<store>/others/`，失败即停止。
默认 dmg 地址失败时才尝试配置的镜像。相对本地 dmg 路径以仓库根为基准。
解包缓存记录 dmg 的 SHA256；更换 dmg 会重新解包。

默认下载存放于 `dl/`，dmg 存放于 `others/`，打包工具存放于 `tools/`，
暂存目录是 `/tmp/dsh-appimage/<arch>`。`--store` 改变前三个位置并把默认暂存目录
改为 `<store>/work/<arch>`；`--work` 单独覆盖暂存位置。
**应用树 `out-<arch>/` 和产物 `dist/` 始终位于仓库根。**
目录参数必须是绝对路径并通过规范化检查，不能指向系统目录。
使用专门的构建目录。默认保留所有下载缓存、dmg 解包物、pip wheel 缓存、
应用树、AppDir、`app.squashfs`、运行时解包暂存和冒烟测试日志，便于检查与重复构建。
原生 Sharp 备份保留在应用树中供诊断，打包时排除，避免增加成品体积。
重新执行某个构建阶段仍会替换该阶段同名的旧输出；保留策略不为每次运行另建历史副本。

需要释放中间文件占用的空间时，显式加 `--clean`：

```bash
./auto-build.sh --clean
./auto-build.sh --only package --clean
./auto-build.sh --dry-run --clean   # 查看清理计划，不写入、不删除
```

`--clean` 仅在所有选定阶段成功后执行，清理 dmg 解包目录、默认 pip 缓存、
本次架构的打包暂存（包括 AppDir、squashfs 和日志）、node-pty 解包暂存、
appimagetool 解包暂存，以及本次已打包架构的应用树。
仅运行 `--only tree` 时保留作为该阶段输出的应用树，只清除其原生 Sharp 诊断备份。
失败时保留现场；下载的 dmg、运行时归档、npm 包、工具、pip venv 与 `dist/` 成品始终保留。
外部自定义 `PIP_CACHE_DIR` 不在清理范围内。

`--force` 重新下载依赖并重新解包；本地 `--dmg` 输入仍保留。默认无需任何保留开关。

默认 dmg 是滚动的 latest。已有下载会复用；脚本通过 HEAD 元数据提示上游是否变更，
不会自动替换本地载荷。HEAD 是更新提示，不是完整性验证。

## 版本与验证

Node、Python 与 Python 包版本来自 dmg 的 `runtime.json`。`--dry-run` 使用占位版本
展示计划，不承诺这些版本对应当前 latest。Electron 默认 44.4.5，可配置；现有二进制
指纹补丁与应用布局针对已支持的载荷，其他版本仍需验证。

原生平台包默认要求同版本的 Linux 包；LibreOffice 使用应用指定版本的 WASM 回退，
node-pty 补充同版本的 Linux prebuild。没有对应版本时停止，`--allow-drift`
才允许平台包选择替代版本。npm 归档按 registry 提供的 integrity 验证（若提供）。
Electron 与 Node 必须通过官方 SHA256SUMS 比对；`--no-sha256` 可显式跳过。
Python 和 AppImage 工具目前不比对发布方摘要；默认 dmg 也没有配置发布方摘要。

本机架构应用树运行 Sharp worker 自检，失败时中止；`--no-verify` 可显式跳过。
有 xvfb-run 时另做启动冒烟；未看到 web-ready 日志会警告并保留日志，不当作 Sharp
自检成功的依据。自动构建不验证 KDE 标题栏与桌面毛玻璃的视觉效果。

```bash
chmod +x dist/DeepSeek-Harness-*.AppImage
./dist/DeepSeek-Harness-*.AppImage
# 没有 FUSE 时可尝试 --appimage-extract-and-run
(cd dist && sha256sum -c *.sha256)
```

校验和文件使用相对文件名，移动产物和对应 `.sha256` 后仍可校验。

## 网络配置

默认 GitHub 资源经 gh-proxy.org，Node/npm 使用 npmmirror，pip 使用 TUNA。
可用 `--no-proxy` 直连 GitHub，或 `--proxy URL` 指定 GitHub 代理前缀。
`--jobs N` 控制并行下载数，必须为正整数。不同候选 URL 使用不同断点文件。

| 环境变量 | 用途 |
|---|---|
| `DSH_GH_PROXY` | GitHub 代理前缀，空值表示直连 |
| `DSH_NPM_REGISTRY` / `DSH_NPM_FALLBACK` | npm 主源 / 备源 |
| `DSH_NODE_MIRROR` / `DSH_ELECTRON_MIRROR` | Node / Electron 镜像根 |
| `DSH_PYPI_MIRROR` | pip 主源，失败后尝试阿里云与官方 PyPI |
| `DSH_ELECTRON_VERSION` | Electron 版本 |
| `DSH_DMG_URL` | 默认 dmg 地址 |
| `DSH_DMG_MIRROR` / `DSH_DMG_MIRROR_TAG` | dmg 备源与标签 |
| `DSH_PBS_TAGS` | Python standalone 候选标签，空格分隔；之后尝试 GitHub API |
| `DSH_RUNTIME_REPO` / `DSH_APPIMAGETOOL_BASE` | AppImage 工具下载根 |
| `DSH_STORE` | 与 `--store` 对应 |
| `DSH_NODE_VERSION` / `DSH_PY_VERSION` | 仅用于 dry-run 占位 |

## 维护与离线测试

入口 `auto-build.sh` 负责参数和流程；`scripts/build/` 按职责分为
common、download、prepare、tree、package 模块。`scripts/extract-asar.py` 展开
asar 与 unpacked 载荷；`scripts/npm-linux-swap.py` 转换平台包并检查遗留原生包。

```bash
bash -n auto-build.sh
for script in scripts/build/*.sh; do bash -n "$script"; done
python3 -m unittest discover -s tests -v
```

离线测试覆盖参数错误、dry-run 无写入/无网络、双架构去重、本地 dmg、asar 载荷与
异常输入、npm 版本/摘要/归档。完整构建及目标机器运行检查另行执行。
