#!/bin/bash
# Build in a throwaway directory and verify netlink-only exponential backoff.
set -euo pipefail
B="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d /tmp/dsh-netlink-guard-test-XXXXXX)"
trap 'rm -rf "$T"' EXIT
python3 "$B/tests/test-netlink-launchers.py"
mkdir -p "$T/tree/resources"
"$B/scripts/install-netlink-guard.sh" "$T/tree" x64
cc -std=c11 -O2 -Wall -Wextra -Werror \
  "$B/tests/netlink-guard-test.c" -o "$T/netlink-guard-test"

echo '== 无守卫基线（seccomp 立即返回 EACCES）=='
DSH_NETLINK_GUARD_MAX_MS=8 "$T/netlink-guard-test"

echo '== 启用守卫：期望 1 / 2 / 4 / 8 / 8 ms 退避（封顶）=='
DSH_NETLINK_GUARD_MAX_MS=8 EXPECT_BACKOFF=1 \
  LD_PRELOAD="$T/tree/resources/netlink-guard/libdsh-netlink-guard.so" \
  "$T/netlink-guard-test"

echo '== DSH_NETLINK_GUARD=0：透传，不施加退避 =='
DSH_NETLINK_GUARD=0 DSH_NETLINK_GUARD_MAX_MS=8 \
  LD_PRELOAD="$T/tree/resources/netlink-guard/libdsh-netlink-guard.so" \
  "$T/netlink-guard-test"

echo '  ✓ netlink 退避、普通 socket 透传、禁用开关均通过'
