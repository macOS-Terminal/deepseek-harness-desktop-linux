#!/usr/bin/env python3
"""Validate every generated launcher and its netlink-guard path (no packaging)."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "build-packages.sh").read_text(encoding="utf8")

TEMPLATES = {
    "system": 'cat > "$META/launcher" <<\'LAUNCH\'\n',
    "bundled": 'cat > "$META/bundled-launcher" <<\'LAUNCH\'\n',
    "cli": "cat > \"$CLI\" <<'CLIEOF'\n",
    "appimage": "cat > \"$A/AppRun\" <<'APPRUN'\n",
}
EXPECTED = {
    "system": 'GUARD="$APP_DIR/netlink-guard/libdsh-netlink-guard.so"',
    "bundled": 'GUARD="$APP_HOME/resources/netlink-guard/libdsh-netlink-guard.so"',
    "cli": 'GUARD="$runtime/../netlink-guard/libdsh-netlink-guard.so"',
    "appimage": 'GUARD="$HERE/resources/netlink-guard/libdsh-netlink-guard.so"',
}
END = {"system": "LAUNCH", "bundled": "LAUNCH", "cli": "CLIEOF", "appimage": "APPRUN"}

with tempfile.TemporaryDirectory(prefix="dsh-launcher-syntax-") as tmp:
    for name, start_marker in TEMPLATES.items():
        start = SOURCE.index(start_marker) + len(start_marker)
        end_marker = "\n" + END[name] + "\n"
        body = SOURCE[start:SOURCE.index(end_marker, start) + 1]
        assert EXPECTED[name] in body, f"{name}: wrong or missing guard path"
        assert 'LD_PRELOAD="$GUARD${LD_PRELOAD:+:$LD_PRELOAD}"' in body, name
        assert 'export LD_PRELOAD' in body, name
        path = Path(tmp) / (name + ".sh")
        path.write_text(body, encoding="utf8")
        subprocess.run(["bash", "-n", str(path)], check=True)
        print(f"  ✓ {name}: guard path + shell syntax")

assert '"$B/scripts/install-netlink-guard.sh" "$SRC" "$ARCH"' in SOURCE
assert 'cp "$META/bundled-launcher" "$D/usr/bin/deepseek-harness"' in SOURCE
assert 'cp %{_sourcedir}/deepseek-harness-launcher %{buildroot}/usr/bin/deepseek-harness' in SOURCE
print("  ✓ deb / rpm / pkg.tar.zst / AppImage 均接入构建链")
