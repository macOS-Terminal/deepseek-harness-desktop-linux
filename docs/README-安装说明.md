# DeepSeek Harness 0.2.1-rc.5 · Linux 版

由上游 macOS 安装包（`dsh-latest-macos-arm64.dmg`，版本 `0.2.1-rc.5`）移植重建。
内置 Electron 44.7.0 / Node 24.21.0 / Python 3.12.14 / pnpm 11.28.5。

## 选哪个包

| 你的系统 | 用这个 |
|---|---|
| 任意发行版，免安装 | `DeepSeek-Harness-0.2.1-rc.5-x86_64.AppImage` |
| Debian 12+ / Ubuntu 21.04+ | `deepseek-harness_0.2.1-rc.5_amd64.bundled.deb` |
| Fedora 31+ / openSUSE Leap 15.3+ | `deepseek-harness-0.2.1-0.rc5.x86_64.rpm` |
| Arch / Manjaro | `deepseek-harness-desktop-0.2.1_rc.5-1-x86_64.pkg.tar.zst` |

ARM64 机器（如树莓派 4/5、ARM 服务器、Asahi Linux）选对应 `aarch64` / `arm64` 的文件。

体积：

| 格式 | x86_64 | aarch64 |
|---|---|---|
| AppImage | 287.5 MB | 282.0 MB |
| bundled.deb | 258.8 MB | 252.1 MB |
| rpm | 273.8 MB | 268.4 MB |
| pkg.tar.zst | 169.6 MB | 163.4 MB |

## 安装

```bash
# AppImage
chmod +x DeepSeek-Harness-0.2.1-rc.5-x86_64.AppImage
./DeepSeek-Harness-0.2.1-rc.5-x86_64.AppImage

# Debian / Ubuntu
sudo apt install ./deepseek-harness_0.2.1-rc.5_amd64.bundled.deb

# Fedora / openSUSE
sudo dnf install ./deepseek-harness-0.2.1-0.rc5.x86_64.rpm

# Arch
sudo pacman -U deepseek-harness-desktop-0.2.1_rc.5-1-x86_64.pkg.tar.zst
```

AppImage 若报 FUSE 相关错误，加 `--appimage-extract-and-run` 运行。

## 校验

```bash
sha256sum -c SHA256SUMS.txt
```

## 兼容性

- **deb 为 zstd 载荷**：Debian 需 ≥ 12，Ubuntu 需 ≥ 21.04（Ubuntu 22.04 已实测可装）。
  更老的系统（Debian 11）请改用 AppImage。
- **rpm 为 zstd 载荷**：需 rpm ≥ 4.14。
- 需要 glibc 2.28+（Electron 44 的下限）。

## 说明

- `pkg.tar.zst` 按设计依赖系统 `electron`，需先安装 `electron` 包。
- AppImage / deb / rpm 三种均为自带 Electron 的完整包，互不依赖。
- 数据目录：`~/.dsh`（可用 `DSH_HOME` 覆盖）。
- 托盘图标需要系统托盘支持（GNOME 需装 AppIndicator 扩展）。
