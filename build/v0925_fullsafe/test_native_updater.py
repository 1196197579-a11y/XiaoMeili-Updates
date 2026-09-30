# -*- coding: utf-8 -*-
from pathlib import Path
import hashlib
import json
import os
import sys
import uuid
import zipfile

if len(sys.argv) != 2:
    raise SystemExit("usage: test_native_updater.py <source_root>")

source_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source_root / "app" / "src"))
from native_updater import install_update_package, NativeUpdateError


def digest(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


base = Path(os.environ.get("RUNNER_TEMP", ".")) / ("xm-native-test-" + uuid.uuid4().hex)
local = base / "LocalAppData"
os.environ["LOCALAPPDATA"] = str(local)
root = local / "XiaoMeiliApp"
versions = root / "versions"
old = versions / "v0.9.2.5_existing"
old.mkdir(parents=True)
(root / ".xiaomeili-install.json").write_text(
    json.dumps(
        {
            "schema": 2,
            "product": "XiaoMeili",
            "install_id": "ci-native-updater",
            "root_policy": "LOCALAPPDATA_XiaoMeiliApp_ONLY",
            "deletion_policy": "NO_AUTOMATIC_FILE_DELETION",
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
(root / "XiaoMeiliLauncher.exe").write_bytes(b"launcher-sentinel")
(root / "active.json").write_text(
    json.dumps(
        {
            "schema": 1,
            "product": "XiaoMeili",
            "version": "0.9.2.5",
            "relative_exe": "versions/v0.9.2.5_existing/XiaoMeili.exe",
        }
    ),
    encoding="utf-8",
)
(old / "XiaoMeili.exe").write_bytes(b"old-exe")
(old / "DO_NOT_TOUCH.txt").write_text("old-version-sentinel", encoding="utf-8")

outside = base / "OUTSIDE_DO_NOT_TOUCH.txt"
outside.write_text("outside-sentinel", encoding="utf-8")
marker = root / ".xiaomeili-install.json"
launcher = root / "XiaoMeiliLauncher.exe"
before = {
    str(old / "XiaoMeili.exe"): digest(old / "XiaoMeili.exe"),
    str(old / "DO_NOT_TOUCH.txt"): digest(old / "DO_NOT_TOUCH.txt"),
    str(outside): digest(outside),
    str(marker): digest(marker),
    str(launcher): digest(launcher),
}

payload = base / "payload"
(payload / "_internal" / "assets").mkdir(parents=True)
(payload / "XiaoMeili.exe").write_bytes(b"new-exe")
(payload / "_internal" / "assets" / "VERSION.txt").write_text("9.9.9\n", encoding="ascii")
package = base / "update.zip"
with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_STORED) as z:
    z.write(payload / "XiaoMeili.exe", "XiaoMeili.exe")
    z.write(payload / "_internal" / "assets" / "VERSION.txt", "_internal/assets/VERSION.txt")
sha = hashlib.sha256(package.read_bytes()).hexdigest()

result = install_update_package(
    package=package,
    install_root=root,
    expected_version="9.9.9",
    expected_sha256=sha,
    current_exe=old / "XiaoMeili.exe",
    log_path=base / "native.log",
)

active = json.loads((root / "active.json").read_text(encoding="utf-8-sig"))
if active.get("version") != "9.9.9":
    raise RuntimeError("native updater did not activate target version")
new_dir = Path(result["version_dir"])
if not (new_dir / "XiaoMeili.exe").is_file():
    raise RuntimeError("new version executable missing")
if not (new_dir / "_internal" / "assets" / "VERSION.txt").is_file():
    raise RuntimeError("new version VERSION.txt missing")

for p, old_hash in before.items():
    pp = Path(p)
    if not pp.is_file():
        raise RuntimeError("pre-existing sentinel disappeared: " + p)
    if digest(pp) != old_hash:
        raise RuntimeError("pre-existing sentinel changed: " + p)

if not list((root / "active_history").glob("active_*.json")):
    raise RuntimeError("active.json history backup missing")

bad = base / "bad.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("../ESCAPE.txt", "blocked")
bad_sha = hashlib.sha256(bad.read_bytes()).hexdigest()
try:
    install_update_package(
        package=bad,
        install_root=root,
        expected_version="9.9.10",
        expected_sha256=bad_sha,
        current_exe=old / "XiaoMeili.exe",
        log_path=base / "native.log",
    )
    raise RuntimeError("path traversal package was accepted")
except NativeUpdateError:
    pass

if (base / "ESCAPE.txt").exists() or (root.parent / "ESCAPE.txt").exists():
    raise RuntimeError("path traversal escaped the version directory")

print("NATIVE_UPDATER_TEST_PASS")
print("existing files unchanged:", len(before))
print("new version:", new_dir)
