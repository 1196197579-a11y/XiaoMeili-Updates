# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def patch(root: Path, repo_root: Path):
    main = root / "app" / "src" / "main.py"
    speech = root / "app" / "src" / "speech_input.py"
    helper = root / "app" / "assets" / "update_helper.ps1"
    helper_src = repo_root / "build" / "v0921" / "update_helper_safe_v0921.ps1"
    for p in (main, speech, helper_src):
        if not p.exists():
            raise FileNotFoundError(p)

    s = main.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.9.2"' not in s:
        raise RuntimeError("V0.9.2.1 expected V0.9.2 base")
    s = s.replace('APP_VERSION = "0.9.2"', 'APP_VERSION = "0.9.2.1"', 1)
    main.write_text(s, encoding="utf-8")
    py_compile.compile(str(main), doraise=True)

    sp = speech.read_text(encoding="utf-8")
    sp = sp.replace("小美丽 V0.9.2 语音诊断日志", "小美丽 V0.9.2.1 语音诊断日志")
    speech.write_text(sp, encoding="utf-8")
    py_compile.compile(str(speech), doraise=True)

    shutil.copy2(helper_src, helper)
    hp = helper.read_text(encoding="utf-8-sig")
    for forbidden in ("/MIR", "/PURGE", "robocopy.exe", "Remove-Item", "Stop-Process"):
        if forbidden.lower() in hp.lower():
            raise RuntimeError("V0.9.2.1 helper contains forbidden operation: " + forbidden)
    for required in ("XIAOMEILI_INSTALL_ROOT_MARKER", "PROTECTED_USER_PATHS", "LOCALAPPDATA", "XiaoMeiliApp", "Expand-Archive"):
        if required not in hp:
            raise RuntimeError("V0.9.2.1 helper missing safety token: " + required)

    print("Patched XiaoMeili source to V0.9.2.1 final safe baseline")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0921.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
