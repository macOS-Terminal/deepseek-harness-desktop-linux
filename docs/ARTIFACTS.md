# DeepSeek Harness — Linux 移植产物

上游应用：`@deepseek-ai/dsh-desktop 0.2.2-rc.3`（取自官方 macOS arm64 dmg）。
本批为 **3.7.1**：跟进 rc.3 并重跑整条构建链。

覆盖 **x86_64** 与 **aarch64**，各 4 种格式，共 **8 个应用包**；另附 2 个 `electron45` 运行时包。
全部格式使用 **zstd** 压缩。

## 产物清单

### x86_64 (amd64)

| 文件 | 大小 | Electron |
|---|---|---|
| `DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage` | 296.0 MB | 内置 44.7.0 |
| `deepseek-harness_0.2.2-rc.3_amd64.bundled.deb` | 265.6 MB | 内置 44.7.0 |
| `deepseek-harness-0.2.2-0.rc3.x86_64.rpm` | 280.6 MB | 内置 44.7.0 |
| `deepseek-harness-desktop-0.2.2_rc.3-1-x86_64.pkg.tar.zst` | 177.5 MB | 依赖系统 |

### aarch64 (arm64)

| 文件 | 大小 | Electron |
|---|---|---|
| `DeepSeek-Harness-0.2.2-rc.3-aarch64.AppImage` | 290.6 MB | 内置 44.7.0 |
| `deepseek-harness_0.2.2-rc.3_arm64.bundled.deb` | 259.9 MB | 内置 44.7.0 |
| `deepseek-harness-0.2.2-0.rc3.aarch64.rpm` | 275.1 MB | 内置 44.7.0 |
| `deepseek-harness-desktop-0.2.2_rc.3-1-aarch64.pkg.tar.zst` | 171.2 MB | 依赖系统 |

### 附带的运行时包

| 文件 | 大小 | 说明 |
|---|---|---|
| `electron45-45.2.3-1-x86_64.pkg.tar.zst` | 92.1 MB | Arch 用；`provides electron45, electron` |
| `electron45-45.2.3-1-aarch64.pkg.tar.zst` | 91.8 MB | 同上 |

> `pkg.tar.zst` 是唯一**不内置 Electron** 的格式。启动器按
> `electron45 → electron44 … electron39 → electron → nodejs-electron` 顺序查找，
> 任意 39–45 版本均可启动；推荐安装上表中的 `electron45`。

## 系统要求

| 格式 | 要求 |
|---|---|
| deb | Ubuntu 21.04+ / Debian 12+ |
| rpm | rpm >= 4.14（Fedora 31+ / openSUSE Leap 15.3+） |
| pkg.tar.zst | pacman 5.x+ |
| AppImage | squashfs-tools 4.4+ 或内核支持 zstd squashfs |

deb 使用 zstd，Ubuntu 与 Debian 的引入版本不同步：Ubuntu 21.04 起支持，
Debian 需 12+。**Debian 11 及更早无法安装。**

自检：

```bash
ar t deepseek-harness_*.deb                  # 应含 data.tar.zst
rpm -qp --qf '%{PAYLOADCOMPRESSOR}\n' *.rpm  # 应输出 zstd
bsdtar -tf *.pkg.tar.zst | head -1
./*.AppImage --appimage-offset               # 输出偏移即正常
sha256sum -c SHA256SUMS.txt
```

## 安装

```bash
# AppImage（免安装）
chmod +x DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage
./DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage

# Debian / Ubuntu
sudo apt install ./deepseek-harness_0.2.2-rc.3_amd64.bundled.deb

# Fedora / openSUSE
sudo dnf install ./deepseek-harness-0.2.2-0.rc3.x86_64.rpm

# Arch / Manjaro
sudo pacman -U electron45-45.2.3-1-x86_64.pkg.tar.zst
sudo pacman -U deepseek-harness-desktop-0.2.2_rc.3-1-x86_64.pkg.tar.zst
```

安装后从应用菜单启动「DeepSeek Harness Desktop」，或执行 `deepseek-harness`。
AppImage 需要 FUSE；无 FUSE 时加 `--appimage-extract-and-run`。

## 与上游 macOS 包的差异

- **原生模块换平台**：darwin 包替换为对应 Linux 包，并清理 win32/darwin prebuilds。
- **运行时换平台**：Node 24.21.0 / Python 3.12.14 / pnpm 11.28.5，均换成 Linux 构建。
- **平台准入补丁**：放行 `linux`，包括 `dshMandatoryUpdatePolicy` 的平台校验。
- **窗口装饰**：复用应用自带的 `data-windows-titlebar` 模式，实现左置交通灯与侧栏毛玻璃。
- **托盘**：补 `resources/tray.png`，否则托盘会创建成功但图标为空。
- **Sharp 进程隔离**：libvips 移到独立 Node 进程，避免 Electron 内段错误。
- **netlink 退避守卫**：Chromium netlink 收包失败时按 1/2/4…60 秒退避，避免刷爆 syslog。

细节见 `docs/CHANGELOG.md`。

## 已知限制

- 应用使用 Electron 44.7.0；`electron45` 包是给 Arch 的系统 Electron 变体用的。
- 官方无 Linux 更新源，产物已移除 `app-update.yml`，升级需重新安装新版本。
