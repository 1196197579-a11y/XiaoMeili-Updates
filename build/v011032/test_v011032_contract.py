import hashlib, json, os, sys, tempfile, zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".")
main = (root / "app/src/main.py").read_text(encoding="utf-8")
native = (root / "app/src/native_updater.py").read_text(encoding="utf-8")

required_main = [
    'APP_VERSION = "0.11.0.3.2"',
    'self.brain_download_mode.addItem("小美丽内置下载器（推荐）", "builtin")',
    'self.brain_download_mode.addItem("NDM 加速下载（可选）", "ndm")',
    'uf.addRow("下载方式", update_dl_row)',
    'uf.addRow("NDM 下载目录", update_ndm_dir_row)',
    'allow_external_current=True',
    'IDLE_MAX_ASSETS = 30',
    '桌面 EXE 自动生成已禁用',
    "'exit_chain': '爬出屏幕后接下一支动作'",
]
for token in required_main:
    if token not in main:
        raise SystemExit(f"main contract missing: {token}")
if 'bg.addRow("下载方式", mode_row)' in main:
    raise SystemExit("download selector still lives in Components page")

required_native = [
    'allow_external_current=False',
    'current_is_managed = True',
    'current_was_managed',
]
for token in required_native:
    if token not in native:
        raise SystemExit(f"native contract missing: {token}")

sys.path.insert(0, str(root / "app/src"))
import native_updater as nu

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    os.environ["LOCALAPPDATA"] = str(td / "Local")
    install_root = Path(os.environ["LOCALAPPDATA"]) / "XiaoMeiliApp"
    versions = install_root / "versions"
    versions.mkdir(parents=True)
    (install_root / nu.MARKER_NAME).write_text(json.dumps({
        "product": nu.PRODUCT,
        "schema": 2,
        "install_id": "contract-test",
        "deletion_policy": "NO_AUTOMATIC_FILE_DELETION",
    }), encoding="utf-8")
    launcher = install_root / "XiaoMeiliLauncher.exe"
    launcher.write_bytes(b"launcher")

    desktop_copy = td / "Desktop" / "XiaoMeili.exe"
    desktop_copy.parent.mkdir(parents=True)
    desktop_copy.write_bytes(b"external-copy")
    before = desktop_copy.read_bytes()

    package = td / "update.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("XiaoMeili.exe", b"new-version")
        zf.writestr("_internal/assets/VERSION.txt", "9.9.9")
    h = hashlib.sha256(package.read_bytes()).hexdigest()

    try:
        nu.install_update_package(
            package=package,
            install_root=install_root,
            expected_version="9.9.9",
            expected_sha256=h,
            current_exe=desktop_copy,
        )
        raise SystemExit("strict external-current mode should fail")
    except nu.NativeUpdateError:
        pass

    result = nu.install_update_package(
        package=package,
        install_root=install_root,
        expected_version="9.9.9",
        expected_sha256=h,
        current_exe=desktop_copy,
        allow_external_current=True,
    )
    if result.get("current_was_managed") is not False:
        raise SystemExit("external-current metadata incorrect")
    if desktop_copy.read_bytes() != before:
        raise SystemExit("external desktop copy was modified")
    active = json.loads((install_root / "active.json").read_text(encoding="utf-8"))
    if active.get("version") != "9.9.9":
        raise SystemExit("active version switch failed")
    if not Path(result["version_dir"]).joinpath("XiaoMeili.exe").is_file():
        raise SystemExit("new protected version missing")

print("V011032_CONTRACT_OK")
