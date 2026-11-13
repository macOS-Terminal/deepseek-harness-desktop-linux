# Chromium netlink 收包失败退避守卫

## 根因

Ubuntu 上曾出现应用整夜运行后 `/var/log/syslog` 增至数百 GB 的报告。重复日志为：

```text
ERROR:net/base/address_tracker_linux.cc Failed to recv from netlink socket: Permission denied (13)
```

该日志来自 Electron 内的 Chromium，而不是 Harness 的业务 JS。Chromium 的
`AddressTrackerLinux::ReadMessages()` 在 `recv()` 遇到 `EACCES` 等错误后记录日志并返回，
但没有撤销 readable-fd watcher，也没有关闭 socket。事件循环随即再次调用同一函数，形成无退避重试。
AppArmor 等安全策略可以触发权限拒绝；同类问题也出现在其他 Electron 应用中。

- [Chromium `address_tracker_linux.cc`](https://raw.githubusercontent.com/chromium/chromium/main/net/base/address_tracker_linux.cc)
- [其他 Electron 应用的同类 syslog 洪泛报告](https://github.com/wimpysworld/sidra/issues/327)

## 本移植的处理

`netlink-guard/netlink_guard.c` 是一个很小的 `LD_PRELOAD` 守卫，只拦截
`socket`、`close`、`recv`、`recvfrom`、`recvmsg`：

- 仅跟踪以 `AF_NETLINK` 创建的 fd，普通 TCP/UDP/Unix socket 不施加延迟；
- 仅对 `EACCES`、`EPERM`、`ENOBUFS` 退避，其他错误与 `EAGAIN` 原样返回；
- 重试间隔按 **1、2、4…60 秒** 指数增长，60 秒封顶；
- 成功收包后重置为 1 秒；关闭 fd 后删除状态，避免 fd 复用继承旧状态；
- 保留原始 `errno`，不会把权限错误伪装成成功，也不关闭其他 Chromium 错误日志。

标准启动入口（AppImage `AppRun`、deb/rpm `/usr/bin/deepseek-harness`、
pkg.tar.zst 的系统 Electron 启动器与 CLI）都会加载该守卫。绕过这些入口、直接执行内部 Electron
二进制不会加载守卫，因此排障时也应使用标准启动命令。
这是一个**移植层的退避修复**，不是对上游 Chromium 源码的修改。永久权限拒绝仍可能按封顶间隔
留下少量日志；应同时检查 AppArmor 的 `recvmsg` / `netlink` 拒绝记录。rsyslog 的大小上限可作为
第二道防线，但不能替代应用侧退避。

## 构建

```bash
# x64（需要本机 cc）
./scripts/install-netlink-guard.sh out-x64 x64

# arm64（x86_64 主机默认需要 aarch64-linux-gnu-gcc，可用 CC_ARM64 覆盖）
./scripts/install-netlink-guard.sh out-arm64 arm64
```

`scripts/assemble-tree.sh` 和 `build-packages.sh` 都会自动执行该步骤；后者每次从当前源码重建，
防止旧 `.so` 残留。产物位于 `resources/netlink-guard/libdsh-netlink-guard.so`。

## 验证

```bash
./tests/test-netlink-guard.sh
```

测试用 seccomp 让 `recvfrom`/`recvmsg` 返回 `EACCES`，不会生成真实日志洪泛。
将上限设为 8ms 后，实测输出：

```text
无守卫：netlink_delays_ms=0,0,0,0,0 ordinary_socket_ms=0
有守卫：netlink_delays_ms=1,2,4,8,8 ordinary_socket_ms=0
禁用后：netlink_delays_ms=0,0,0,0,0 ordinary_socket_ms=0
```

紧急情况下可用 `DSH_NETLINK_GUARD=0 deepseek-harness` 完全绕过守卫；该设置只用于诊断，
会让上游的无退避行为恢复。
