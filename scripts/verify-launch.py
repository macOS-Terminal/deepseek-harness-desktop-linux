#!/usr/bin/env python3
"""逐个解包并实际启动每个安装包，确认应用能起来。

做法：解包 -> 用 xvfb 起进程 -> 从日志里抓 `dsh web: <url>` -> 对 URL 发 HTTP 请求
      -> 检查 lib/main.js 是否含补丁痕迹 -> 关进程。

用法: verify-launch.py <dist 目录>
"""
import glob
import http.cookiejar
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

URL_RE = re.compile(r"dsh web:\s*(https?://\S+)")
MARKERS = ["desktopResourcesRoot", "desktopIsPackaged", "linux-window-control"]
DISPLAY = ":99"
SYS_ELECTRON = "/tmp/sys-electron"


def sh(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def extract_deb(deb, dest):
    os.makedirs(dest, exist_ok=True)
    sh(["ar", "x", os.path.abspath(deb)], cwd=dest)
    data = glob.glob(os.path.join(dest, "data.tar.*"))[0]
    if data.endswith(".zst"):
        # zstd 载荷：显式解压，不依赖 tar 的自动探测
        subprocess.run(f"zstd -dc '{data}' | tar -xf - -C .", shell=True, cwd=dest, check=True)
    else:
        sh(["tar", "-xf", data, "-C", dest])
    os.remove(data)


def extract_rpm(rpm, dest):
    os.makedirs(dest, exist_ok=True)
    subprocess.run(f"rpm2cpio '{os.path.abspath(rpm)}' | cpio -idm --quiet", shell=True, cwd=dest, check=True)


def extract_pkg(pkg, dest):
    os.makedirs(dest, exist_ok=True)
    sh(["bsdtar", "-xf", os.path.abspath(pkg), "-C", dest])


def extract_appimage(appimage, dest):
    os.makedirs(dest, exist_ok=True)
    sh([os.path.abspath(appimage), "--appimage-extract"], cwd=dest)
    # squashfs-root/<app>


def find_bin(root, kind):
    """在解包树里找可执行入口。"""
    if kind == "appimage":
        return os.path.join(root, "squashfs-root", "deepseek-harness")
    if kind == "deb":
        return os.path.join(root, "usr/lib/deepseek-harness/deepseek-harness")
    return os.path.join(root, "usr/lib/deepseek-harness/deepseek-harness")


def launch(binary, home, timeout=120, extra_path=None):
    os.makedirs(os.path.join(home, ".dsh"), exist_ok=True)
    env = dict(os.environ, HOME=home, DSH_HOME=os.path.join(home, ".dsh"),
               DISPLAY=DISPLAY, ELECTRON_DISABLE_SECURITY_WARNINGS="1")
    if extra_path:
        env["PATH"] = extra_path + ":" + env.get("PATH", "")
        env["DSH_DESKTOP_NODE_EXECUTABLE"] = os.path.join(extra_path, "electron")
    p = subprocess.Popen([binary, "--no-sandbox", "--ozone-platform=x11", "--disable-gpu"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=env, start_new_session=True, text=True, errors="replace")
    url, lines, t0 = None, [], time.time()
    while time.time() - t0 < timeout:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            time.sleep(0.05)
            continue
        lines.append(line)
        m = URL_RE.search(line)
        if m:
            url = m.group(1)
            break
    return p, url, "".join(lines)


def http_ok(url):
    """带 token 的 URL 会 303 到 ./ 并下发会话 cookie，必须带 cookie jar 跟随跳转才拿到 200。"""
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        with op.open(url, timeout=20) as r:
            return r.status, len(r.read(8192))
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:80]


def stop(p):
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        p.wait(timeout=10)


def main(dist):
    items = [
        ("AppImage", "appimage", sorted(glob.glob(os.path.join(dist, "*x86_64.AppImage")))),
        ("bundled.deb", "deb", sorted(glob.glob(os.path.join(dist, "*amd64.bundled.deb")))),
        ("rpm", "rpm", sorted(glob.glob(os.path.join(dist, "*x86_64.rpm")))),
        ("pkg.tar.zst", "pkg", sorted(glob.glob(os.path.join(dist, "*x86_64.pkg.tar.zst")))),
    ]
    present = [(n, k, v[0]) for n, k, v in items if v]
    missing = [n for n, k, v in items if not v]
    print(f"发现 {len(present)} 个 x64 产物" + (f"（缺少: {', '.join(missing)}）" if missing else ""))
    results, ok = [], 0
    for name, kind, path in present:
        tmp = tempfile.mkdtemp(prefix="verify-")
        home = os.path.join(tmp, "home")
        try:
            print(f"\n######## {name} ########")
            print(f"  文件: {os.path.basename(path)}  {os.path.getsize(path)/1048576:.1f} MB")
            if kind == "deb":
                members = sh(["ar", "t", path]).stdout.split()
                print(f"  ar t: {', '.join(members)}")
            elif kind == "rpm":
                info = sh(["rpm", "-qip", path], check=False).stdout.splitlines()
                print(f"  rpm -qip: {info[0].strip() if info else '（读取失败）'}")
                listing = subprocess.run(f"rpm2cpio '{path}' | cpio -t 2>/dev/null | head -3",
                                         shell=True, capture_output=True, text=True).stdout.strip()
                print(f"  rpm 内容抽样: {listing.splitlines()[0] if listing else '（空）'}")
            elif kind == "pkg":
                listing = sh(["bsdtar", "-tf", path]).stdout.splitlines()
                print(f"  bsdtar -tf: {len(listing)} 个条目")
            ex = os.path.join(tmp, "x")
            {"appimage": extract_appimage, "deb": extract_deb,
             "rpm": extract_rpm, "pkg": extract_pkg}[kind](path, ex)
            extra_path = None
            if kind == "pkg":
                src = os.path.join(ex, "usr/bin/deepseek-harness")
                appdir = os.path.join(ex, "usr/lib/deepseek-harness/resources")
                body = open(src, encoding="utf8").read().replace(
                    "APP_DIR=/usr/lib/deepseek-harness/resources", f"APP_DIR={appdir}")
                # 沙箱容器内以 root 运行，Chromium 必须显式关闭 setuid 沙箱
                body = body.replace('exec "$ELECTRON_BIN" "$APP_DIR/app"',
                                    'exec "$ELECTRON_BIN" "$APP_DIR/app" --no-sandbox')
                binary = os.path.join(tmp, "launch.sh")
                with open(binary, "w", encoding="utf8") as fh:
                    fh.write(body)
                os.chmod(binary, 0o755)
                extra_path = SYS_ELECTRON
                print(f"  （pkg 依赖系统 Electron，注入 {SYS_ELECTRON}/electron 作为运行时）")
            else:
                binary = find_bin(ex, kind)
            if not os.path.exists(binary):
                print(f"  ✗ 未找到入口: {binary}")
                results.append((name, False, "未找到入口"))
                continue
            os.chmod(binary, 0o755)
            main_js = None
            for cand in glob.glob(os.path.join(ex, "**/app/lib/main.js"), recursive=True):
                main_js = cand
                break
            marks = []
            if main_js:
                body = open(main_js, encoding="utf8", errors="replace").read()
                marks = [m for m in MARKERS if m in body]
            p, url, log = launch(binary, home, extra_path=extra_path)
            if url:
                status, nbytes = http_ok(url)
                print(f"  启动日志: dsh web: {url}")
                print(f"  HTTP 探测: status={status} 首块 {nbytes} 字节")
                good = status == 200
                print(f"  补丁痕迹: {', '.join(marks) if marks else '无'}")
                results.append((name, good, f"HTTP {status}"))
                ok += 1 if good else 0
            else:
                print("  ✗ 未出现 dsh web 行，日志尾部:")
                print("\n".join(log.strip().splitlines()[-8:]))
                results.append((name, False, "无启动日志"))
            stop(p)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        time.sleep(3)
    print("\n===== 汇总 =====")
    for name, good, note in results:
        print(f"  {'✓' if good else '✗'} {name:<14} {note}")
    print(f"  通过 {ok}/{len(results)}")
    return 0 if ok == len(results) and not missing else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist"))
