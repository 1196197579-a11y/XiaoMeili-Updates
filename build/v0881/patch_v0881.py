# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import re
import sys
from pathlib import Path

def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    if not main.exists():
        raise FileNotFoundError(main)
    s = main.read_text(encoding="utf-8")
    s, n = re.subn(
        r'APP_VERSION\s*=\s*"0\.8\.8"',
        'APP_VERSION = "0.8.8.1"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("V0.8.8.1 expected APP_VERSION 0.8.8 after v088 patch")
    s = s.replace("V0.8.8｜", "V0.8.8.1｜", 1)
    main.write_text(s, encoding="utf-8")
    py_compile.compile(str(main), doraise=True)
    final = main.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.8.1"' not in final:
        raise RuntimeError("V0.8.8.1 version verification failed")
    if 'def _v088_selected_exchange(self):' not in final:
        raise RuntimeError("V0.8.8.1 missing real V0.8.8 correction feature")
    print("Patched XiaoMeili source to V0.8.8.1 packaging hotfix")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0881.py <source_root>")
    patch(Path(sys.argv[1]))
