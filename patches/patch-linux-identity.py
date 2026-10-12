#!/usr/bin/env python3
"""Match Electron's Linux desktop identity to the installed desktop entry."""
import json
import sys
from pathlib import Path

DESKTOP_NAME = 'deepseek-harness.desktop'

def main(app_dir):
    path = Path(app_dir) / 'package.json'
    package = json.loads(path.read_text())
    if package.get('desktopName') != DESKTOP_NAME:
        package['desktopName'] = DESKTOP_NAME
        path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
