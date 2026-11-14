# DeepSeek Harness 0.2.2-rc.3 · Linux 版

由上游 macOS 安装包移植重建。内置 Electron 44.7.0 / Node 24.21.0 / Python 3.12.14 / pnpm 11.28.5。

## 选哪个包

| 你的系统 | 用这个 |
|---|---|
| 任意发行版，免安装 | `DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage` |
| Debian 12+ / Ubuntu 21.04+ | `deepseek-harness_0.2.2-rc.3_amd64.bundled.deb` |
| Fedora 31+ / openSUSE Leap 15.3+ | `deepseek-harness-0.2.2-0.rc3.x86_64.rpm` |
| Arch / Manjaro | `deepseek-harness-desktop-0.2.2_rc.3-1-x86_64.pkg.tar.zst` |

ARM64 机器选文件名带 `aarch64` / `arm64` 的对应版本。

体积：

| 格式 | x86_64 | aarch64 |
|---|---|---|
| AppImage | 296.0 MB | 290.6 MB |
| bundled.deb | 265.6 MB | 259.9 MB |
| rpm | 280.6 MB | 275.1 MB |
| pkg.tar.zst | 177.5 MB | 171.2 MB |

## 安装

```bash
# AppImage
chmod +x DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage
./DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage

# Debian / Ubuntu
sudo apt install ./deepseek-harness_0.2.2-rc.3_amd64.bundled.deb

# Fedora / openSUSE
sudo dnf install ./deepseek-harness-0.2.2-0.rc3.x86_64.rpm

# Arch / Manjaro（先装随包提供的运行时，再装应用）
sudo pacman -U electron45-45.2.3-1-x86_64.pkg.tar.zst
sudo pacman -U deepseek-harness-desktop-0.2.2_rc.3-1-x86_64.pkg.tar.zst
```

装好后从应用菜单启动「DeepSeek Harness Desktop」，或在终端执行 `deepseek-harness`。

AppImage 需要 FUSE。若提示无法挂载，改用：

```bash
./DeepSeek-Harness-0.2.2-rc.3-x86_64.AppImage --appimage-extract-and-run
```

## 校验

```bash
sha256sum -c SHA256SUMS.txt
```

## 卸载

```bash
# Deb / Ubuntu
sudo apt remove deepseek-harness

# Fedora / openSUSE
sudo dnf remove deepseek-harness

# Arch
sudo pacman -R deepseek-harness-desktop
```

AppImage 直接删除文件即可。

## 注意事项

- **Debian 11 及更早无法安装 deb**（dpkg 不支持 zstd），请用 AppImage 或 rpm。
- Arch 的 `pkg.tar.zst` 不内置 Electron，需已安装 `electron39`–`electron45` 之一；
  随包提供的 `electron45` 包是推荐选择。
- 启动器会自动设置所需环境变量并加载 netlink 退避守卫，
  请通过菜单或 `/usr/bin/deepseek-harness` 启动，不要直接运行内部二进制。
- 官方没有 Linux 更新源，需要更新时下载新版本重新安装。
