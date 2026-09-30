# -*- coding: utf-8 -*-
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit("usage: test_v0928_contract.py <source_root>")

root=Path(sys.argv[1]).resolve()
main=(root/"app/src/main.py").read_text(encoding="utf-8")

required=[
    'APP_VERSION = "0.9.2.8"',
    'def ensure_desktop_launcher():',
    'target = desktop_dir() / "小美丽.exe"',
    'target.open("xb")',
    'ensure_desktop_launcher()',
    'from native_updater import install_update_package',
]
for token in required:
    if token not in main:
        raise RuntimeError("missing V0.9.2.8 contract token: "+token)

a=main.index("def ensure_desktop_launcher():")
b=main.index("\ndef main():",a)
block=main[a:b]
for forbidden in ("unlink(","rmtree(","os.remove(","replace(","rename(","shutil.move("):
    if forbidden in block:
        raise RuntimeError("desktop launcher mutates/deletes existing file: "+forbidden)

# Must remain a create-new-only entry point, not a versioned desktop app copy.
if 'target.open("wb")' in block or 'shutil.copy2(source, target)' in block:
    raise RuntimeError("desktop launcher can overwrite an existing file")
if 'XiaoMeili_Setup_' in block:
    raise RuntimeError("desktop entry incorrectly points at installer")

print("V0.9.2.8 stable desktop launcher/no-delete contract PASS")
