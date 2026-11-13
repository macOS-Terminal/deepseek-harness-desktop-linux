# DeepSeek Harness — Linux 移植源码包

把官方 **macOS arm64** 安装包（`DeepSeek Harness 0.2.2-rc.1.dmg`）里的应用载荷，
重新打包成 Linux 桌面发行包（AppImage / deb / pacman / rpm，x86_64 + aarch64），
全部格式统一使用 **zstd** 压缩。

本目录是**可复现的移植工具链**：官方 dmg + 若干公开下载物 → 8 个 Linux 安装包（AppImage / bundled.deb / pkg.tar.zst / rpm × 两架构）。

---

## 目录结构

```
dsh-desktop-linux-source/
├── patches/                     逆向/适配补丁（按顺序执行）
│   ├── patch-main.py            平台准入、resources 根、打包态判定、托盘、窗口控制 IPC
│   ├── patch-titlebar.py        隐藏原生标题栏（历史版本，被 patch-mac-chrome 取代）
│   ├── patch-fingerprint.py     放宽 node-addon-require-builtin 的 V8 指纹白名单
│   ├── patch-mac-chrome.py      macOS 风格窗口装饰（左置交通灯 + 侧栏毛玻璃）
│   └── upgrade-mac-chrome.py    对已打过旧版 chrome 的树做增量升级（幂等补充）
├── image-worker-src/            Sharp/libvips 进程隔离方案
│   ├── client.cjs               Sharp API 兼容层（跑在 Electron 内，只转发）
│   ├── worker.cjs               真正执行 libvips 的独立 Node 进程
│   └── verify-image-worker.cjs  隔离效果自检脚本
├── netlink-guard/               Chromium netlink 收包失败退避守卫
├── icons/                       桌面项与 16→512 全套 hicolor 图标
├── build-packages.sh            打全部格式（deb×2 / pkg / rpm / AppImage）
├── install-image-worker.sh      把 Sharp 替身包装入某个应用树
├── verify-launch-x64.sh         五种格式逐个解包并实测启动
├── docs/
│   ├── ARTIFACTS.md             产物说明：安装方式、依赖策略、验证记录
│   ├── CHANGELOG.md             完整变更日志（含各修复的根因）
│   └── SHA256SUMS.txt           本次构建 10 个产物的校验和
└── README.md                    本文件
```

---

## 一、准备：需要自行获取的东西

源码包**不含**任何二进制载荷（体积与授权原因），需按下表准备。

### 1. 官方安装包

从 DeepSeek 官方下载 macOS 版 dmg，放到 `others/`：

```
dsh-desktop-linux/
└── others/
    └── dsh-latest-macos-arm64.dmg
```

> 只提供 macOS 包也能做出 Linux 版：应用层 JS 与架构无关，
> 平台相关的只是原生模块（脚本会替换）。

### 2. Electron 运行时（内置版用）

到 npmmirror 或 GitHub Releases 取 **Electron 44.7.0**（与上游 0.2.2-rc.1 内置版本一致）：

```
dl/electron-44.7.0-linux-x64.zip
dl/electron-44.7.0-linux-arm64.zip
```

> 必须 ≥ 44.4.5：Electron 44.0.0 有 Linux 托盘回归缺陷。
> 若用发行版自带的 Electron，则只需系统已安装（见下文「system 变体」）。

### 3. Node 与 Python 运行时载荷

```
dl/node-v24.21.0-linux-x64.tar.xz      dl/node-v24.21.0-linux-arm64.tar.xz
dl/python-3.12.14-x64.tar.gz           dl/python-3.12.14-arm64.tar.gz
```

> 上游 0.2.2-rc.1 仍内置 Node 24.21.0（自带 npm 11.19.0，裁剪时移除，仅保留上游自带的 pnpm 11.28.5）与 Python 3.12.14。

Python 必须是 **python-build-standalone 的 `install_only_stripped`** 变体。
⚠️ 不要用普通版再手工 `strip`：其段布局非标准，`strip`/`objcopy` 会破坏版本符号，
导致运行期 `symbol lookup error`。

### 4. Linux 原生模块（各架构一套）

从 npm registry 取对应平台的 tgz：

| 包 | 用途 |
|---|---|
| `@img/sharp-linux-{x64,arm64}@0.35.5` + `@img/sharp-libvips-linux-*@1.3.4` | 图片处理 |
| `@koromix/koffi-linux-*@3.1.1` | FFI |
| `sherpa-onnx-linux-*@1.13.8` | 语音识别 |
| `node-addon-require-builtin-linux-*-gnu@0.1.9` | 内建模块桥接 |
| `@vscode/ripgrep-linux-*@1.18.0` | 搜索 |
| `@deepseek-ai/node-addon-system-linux-*@0.1.2` | landlock 沙箱 |
| `node-pty@1.2.0-beta.15`（取其中 `prebuilds/linux-*`） | 终端 |
| `@deepseek-ai/libreoffice-kit-wasm@0.1.5` | Office 引擎（Linux 走 WASM 回退） |
| `@deepseek-ai/dsh-sandbox-windows-acl@0.2.2-rc.1` | 跟随 `dsh-sandbox-local` 版本（顶层静态 import，不可裁剪） |

### 5. 打包工具

- `mksquashfs`（squashfs-tools，AppImage 用）
- AppImage type2 runtime：`runtime-x86_64`、`runtime-aarch64`
- `rpmbuild`、`bsdtar`、`fakeroot`、`ar`、`zstd`、`xz`
- C 编译器：x64 用 `cc`；x86_64 主机交叉构建 arm64 用 `aarch64-linux-gnu-gcc`
  （也可用 `CC_X64` / `CC_ARM64` 指定）

放到 `tools/`：

```
tools/usr/bin/mksquashfs
tools/runtime-x86_64
tools/runtime-aarch64
```

---

## 二、生成应用树

以下命令都在项目根目录（含 `dl/`、`others/`、`tools/` 的那一层）执行。

### 1. 解出 dmg 里的应用载荷

```bash
mkdir -p app-new
7z x -oothers/dmg others/dsh-latest-macos-arm64.dmg
# 用随包提供的 asar 提取逻辑展开 app.asar（见下方说明）
```

`app.asar` 是 Electron 归档：文件头 16 字节中，`[12:16]` 是 JSON 头长度，
`data_start = 8 + uint32([4:8])`，各文件按 `offset/size` 切片；
`unpacked: true` 的条目要从 `app.asar.unpacked/` 取。

### 2. 铺 Electron 骨架（每架构一次）

```bash
cd out-x64
unzip -oq ../dl/electron-44.7.0-linux-x64.zip
mv electron deepseek-harness
rm -f resources/default_app.asar
```

### 3. 替换原生模块 + 装配运行时载荷

把 `app-new` 复制到 `resources/app`，然后：

- 删除所有 `*-darwin-*` / `*-win32-*` 原生包，换成对应的 `*-linux-*`；
- `resources/runtime/` 下放置 `bin/node`、`pnpm/`、`cli/`、`office-skills/`；
- `resources/runtime/primary-runtime/dependencies/{node,python}` 放入运行时载荷；
- Python 站点包用交叉安装：

```bash
pip install --target <site-packages> \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_27_x86_64 \
  --python-version 3.12 --implementation cp --only-binary=:all: \
  numpy==2.3.5 pandas==3.0.1 Pillow==12.3.0 lxml==6.1.3 \
  python-docx==1.2.0 python-pptx==1.0.2 openpyxl==3.1.5 XlsxWriter==3.2.9 \
  python-dateutil==2.9.0.post0 six==1.17.0 tzdata==2025.2 \
  typing_extensions==4.16.0 et_xmlfile==2.0.0
```

- 修正 `runtime/primary-runtime/runtime.json` 里的 `platform`/`arch`。

### 4. 打补丁

```bash
python3 patches/patch-main.py       out-x64/resources/app/lib/main.js
python3 patches/patch-titlebar.py   out-x64/resources/app/lib/main.js
python3 patches/patch-mac-chrome.py out-x64/resources/app
python3 patches/patch-fingerprint.py \
  out-x64/resources/app/dsh/node_modules/node-addon-require-builtin-linux-x64-gnu/prebuilt/linux-x64-gnu-napi-v9.node
```

逐项说明：

| 补丁 | 作用 | 不改会怎样 |
|---|---|---|
| `patch-main.py` | 平台准入放行 linux；`DSH_DESKTOP_RESOURCES_DIR` / `DSH_DESKTOP_FORCE_PACKAGED`；托盘放行并改用 PNG；无托盘时关窗退出 | 启动即抛 `unsupported platform` |
| `patch-titlebar.py` | 隐藏系统原生标题栏（为 `patch-mac-chrome.py` 提供锚点） | 顶部出现系统原生标题栏 |
| `patch-mac-chrome.py` | 复用应用自带的 `data-windows-titlebar` 模式获得顶部预留带与拖拽区，绘制左上交通灯，侧栏毛玻璃（串联 KDE/全屏/Wayland 标识补丁） | 顶部有原生标题栏、按钮在右侧 |
| `patch-fingerprint.py` | 按 ELF 符号定位 `Matches` 函数并放宽 V8 指纹匹配（x64 `0x1808f`、arm64 `0x1e1e4`） | 非白名单指纹的 Electron 启动失败 |
| `upgrade-mac-chrome.py` | 旧版 chrome 的增量修复 | 仅在树已打过旧版 chrome 时需要 |

### 5. 装 Sharp 进程隔离

```bash
./install-image-worker.sh out-x64 x64
```

这一步会：

- 把真正的 `sharp` 移入 `node_modules/.sharp-native-backup/`；
- 在 `resources/image-worker/` 下建立私有依赖闭包（standalone Node 读不了 asar）；
- 安装替身包，使 `require("sharp")` 走到 out-of-process worker。

⚠️ 打包前**务必删除** `node_modules/.sharp-native-backup/`，否则会白占体积。
`build-packages.sh` 会强制重复执行该安装并删除备份；`tests/test-image-worker.sh`
会连续安装两轮，验证 facade、worker 载荷、大图、动画、并发和异常图片。

### 6. 安装 netlink 收包失败退避守卫

```bash
./scripts/install-netlink-guard.sh out-x64 x64
# arm64 交叉构建默认使用 aarch64-linux-gnu-gcc
./scripts/install-netlink-guard.sh out-arm64 arm64
```

Chromium 在 netlink `recv()` 权限失败后保留 watcher，会无退避重试并刷爆 syslog。
守卫仅对 `AF_NETLINK` 的 `EACCES` / `EPERM` / `ENOBUFS` 施加 1–60 秒指数退避，
不影响普通 socket，也不屏蔽其他错误日志。详见 `docs/NETLINK-GUARD.md`。
`assemble-tree.sh` 与 `build-packages.sh` 会自动执行本步骤。

### 7. 自检

```bash
# 图片链路与隔离（需图形环境或 xvfb）
DSH_DESKTOP_RESOURCES_DIR=$PWD/out-x64/resources \
  ELECTRON_RUN_AS_NODE=1 ./out-x64/deepseek-harness image-worker-src/verify-image-worker.cjs

# 启动冒烟
HOME=/tmp/t DSH_HOME=/tmp/t/.dsh xvfb-run -a ./out-x64/deepseek-harness --ozone-platform=x11 --disable-gpu
# 看到 "dsh web: http://127.0.0.1:19387/" 即成功
```

### 8. arm64 同理

把上面的 `x64` 换成 `arm64`（原生模块、Electron、Node、Python 载荷都要换对应架构）。

---

## 三、打包

```bash
./build-packages.sh x64
./build-packages.sh arm64
```

产物落在 `dist/`：

| 文件 | 说明 |
|---|---|
| `DeepSeek-Harness-0.2.2-rc.1-{x86_64,aarch64}.AppImage` | 内置 Electron，免安装 |
| `deepseek-harness_0.2.2-rc.1_{amd64,arm64}.bundled.deb` | 内置 Electron |
| `deepseek-harness-desktop-0.2.2_rc.1-1-{x86_64,aarch64}.pkg.tar.zst` | Arch，**依赖系统 `electron`**（不内置） |
| `deepseek-harness-0.2.2-0.rc1.{x86_64,aarch64}.rpm` | Fedora/openSUSE，内置 Electron |

> 只发布 `bundled.deb`。不再提供 `system.deb`：Debian/Ubuntu 没有官方 electron 包，
> 该变体在目标系统上无法直接安装。
>
> `.pkg.tar.zst` 是**唯一依赖系统 Electron** 的格式（Arch 的 `electron` 元包可靠），
> 其余三种（AppImage / deb / rpm）都内置 Electron。实测确认：deb 与 rpm 内含
> `usr/lib/deepseek-harness/deepseek-harness` 二进制，pkg.tar.zst 不含。

### 压缩设置

四种格式**全部使用 zstd**，由 `build-packages.sh` 顶部常量统一控制：

```bash
ZSTD_LEVEL=19                  # 与 xz -9e 体积接近，解压快 3-5 倍
ZSTD_OPTS="-19 -T0 --long=27"  # --long 提升大载荷压缩率
```

| 格式 | 实现 |
|---|---|
| `.deb` | `data.tar.zst` + `control.tar.zst`（`ar` 归档） |
| `.rpm` | `_binary_payload w19.zstdio` |
| `.pkg.tar.zst` | `tar \| zstd $ZSTD_OPTS` |
| `.AppImage` | `mksquashfs -comp zstd -Xcompression-level 19 -Xdict-size 100% -b 1M` |

**最低系统要求**（详见 `docs/ARTIFACTS.md` 的「系统要求」）：

| 格式 | 要求 |
|---|---|
| deb | Ubuntu **21.04+**（dpkg 1.20.9ubuntu1+，Ubuntu 自带 backport）；Debian **12+**（dpkg 1.21.18+）。**Debian 11 及更早不支持** |
| rpm | `rpm >= 4.14`（Fedora 31+ / openSUSE Leap 15.3+） |
| pkg.tar.zst | pacman 5.x+（当前所有 Arch 系均满足） |
| AppImage | squashfs-tools 4.4+ / 主流内核 |

> ⚠️ Ubuntu 与 Debian 的 zstd 支持**不同步**：上游 Debian 在 dpkg 1.21.18 才加入，
> 而 Ubuntu 从 21.04 起就有自己的 patch（`1.20.9ubuntu1`），并在 `1.21.1ubuntu1`
> 把默认压缩改成 zstd。所以判断能否安装要看**发行版**，不能只看 dpkg 版本号。

脚本要点：

- **在 tmpfs 上暂存**并按文件内容（ELF / `#!` / `.so` / `.node`）恢复可执行位
  —— 若工作区在 NTFS/exFAT 上，`chmod` 无效且一切显示 0777；
- 归档属主统一 `root:root`；rpm 用 `%defattr(-,root,root,-)` 保留归一化权限；
- 禁止 rpmbuild strip 厂商预编译二进制；
- `chrome-sandbox` 的 setuid 由各包脚本设置（deb `postinst` / rpm `%attr(4755)` / pacman `.INSTALL`）。

### aarch64 交叉打包注意

- 用 `--platform manylinux_2_28_aarch64` 安装 Python 包（`manylinux2014` 标签已过时）；
- x86_64 主机上 rpmbuild 默认拒绝 aarch64 目标，需补 `buildarch_compat`：
  ```
  buildarch_compat: x86_64: aarch64 noarch
  arch_compat: x86_64: aarch64
  ```

---

## 四、验证

```bash
./tests/test-image-worker.sh  # Sharp 隔离幂等安装与完整图片回归
./tests/test-netlink-guard.sh  # seccomp 模拟 EACCES，验证 1/2/4/8/8ms 退避
./verify-launch-x64.sh          # 四种格式逐个解包并实际启动
cd dist && sha256sum -c SHA256SUMS.txt
```

arm64 可用 qemu 验证载荷：

```bash
qemu-aarch64-static -L <sysroot> out-arm64/resources/runtime/.../node -e "console.log(process.arch)"
```

---

## 五、这套移植在改什么（原理速览）

官方只发布 macOS/Windows 包，Linux 分支在代码里是空实现。移植 = **补上那些空分支**：

1. **平台准入**：`main.js` 的白名单只有 `win32`/`darwin` → 加入 `linux`。
2. **原生模块**：把 darwin/win32 预编译产物换成 linux 产物（应用层 JS 通用）。
3. **运行时**：Node/Python 换成 Linux 构建，`runtime.json` 平台字段改掉。
4. **resources 根**：原实现依赖 `process.resourcesPath`，系统 Electron 下会指错 →
   增加 `DSH_DESKTOP_RESOURCES_DIR`。
5. **打包态**：系统 Electron 加载 app 目录时 `app.isPackaged` 为 false →
   增加 `DSH_DESKTOP_FORCE_PACKAGED=1`。
6. **V8 指纹**：原生插件只认 43.0.0/44.0.0/45.0.0-alpha.6 →
   放宽匹配函数（不降级 Electron）。
7. **Sharp 崩溃**：libvips 在 Electron 内段错误且 JS 无法捕获 →
   改成独立 Node 进程隔离。
8. **窗口装饰**：复用应用自身的 `data-windows-titlebar` 模式 +
   复刻它自己的 darwin 材质配方，得到左置交通灯与侧栏毛玻璃。

详细根因与验证记录见 `docs/CHANGELOG.md`。

---

## 六、常见坑

| 现象 | 原因与处理 |
|---|---|
| `desktop policy: unsupported platform` | `patch-main.py` 没打 |
| `unsupported Electron runtime fingerprint` | `patch-fingerprint.py` 没打 |
| 启动即 `EADDRINUSE 127.0.0.1:19387` | 已有一个实例在跑（应用固定用这个端口），先关掉 |
| 图片一发就整个应用崩 | 检查 sharp 是否有 `Out-of-process Sharp facade` 标记、`resources/image-worker/` 是否完整；原生包与 facade 的入口路径相同，不能只看路径 |
| syslog 反复出现 `Failed to recv from netlink socket` | Chromium 收包失败后无退避重试；确认 `resources/netlink-guard/` 存在并从标准启动器启动。紧急诊断可用 `DSH_NETLINK_GUARD=0`，日常不要关闭 |
| 侧栏折叠后无法展开 / 侧栏右缘缺口 / 文字发灰 | 均因 `backdrop-filter` 放在侧栏元素上（旧版缺陷）。现由独立层 `#dsh-mac-vibrancy` 承担模糊，且插在 `#root` 之前 + `z-index:-1` |
| 内容区左上角露白、全屏布局不对 | 应用给 `_centerCol` 的 16px 圆角 + 缺全屏规则；已置零圆角并对齐 macOS 全屏（隐藏交通灯、折叠键靠左） |
| 真全屏（niri 等平铺合成器）不隐藏交通灯 | 上游把 Linux 排除在事件注册与 preload 监听之外，且平铺合成器不报告全屏；已补视口自检 |
| 侧栏底部有实心暗条 | 应用的列表淡出层渐变到不透明的 `--dsw-specific-sidebar-fill`；已改用半透明 tint 变量 |
| 登录页文字全消失 | `preload-welcome.cjs` 重复声明 `VIBRANCY_ID` 导致 preload 语法错误 |
| 系统 Electron 下白屏 | 缺 `DSH_DESKTOP_RESOURCES_DIR` / `DSH_DESKTOP_FORCE_PACKAGED` |
| 打包后二进制没有执行权限 | 工作区在 NTFS；`build-packages.sh` 的 `normalize_modes` 必须保留 |
| Python 报 `symbol lookup error` | 用了被 `strip` 过的 python-build-standalone，改用 `install_only_stripped` |
| `dpkg -i` 报 control 文件格式错误 | 生成 control 时可选字段展开成了空行（空行=段落分隔符）；已改为整行省略。见 CHANGELOG 的 issue #1 条目 |

---

## 七、许可与声明

- 应用本体版权归 **DeepSeek**，本工具链只做重新打包，不修改业务逻辑；
- 请遵守原应用的许可条款，勿将重打包产物用于商业分发；
- 官方无 Linux 更新源，产物已移除 `app-update.yml`，升级需重新打包。
