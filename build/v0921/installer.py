# -*- coding: utf-8 -*-
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

PRODUCT = "XiaoMeili"
VERSION = "0.9.2.1"
ROOT_NAME = "XiaoMeiliApp"

def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload" / name

def message(text, title="小美丽安全安装"):
    ctypes.windll.user32.MessageBoxW(0, str(text), title, 0x40)

def fail(text):
    ctypes.windll.user32.MessageBoxW(0, str(text), "小美丽安装失败", 0x10)
    raise SystemExit(1)

def install_root():
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise RuntimeError("LOCALAPPDATA 不可用")
    return (Path(local) / ROOT_NAME).resolve()

def protected_paths():
    vals = []
    home = Path.home().resolve()
    vals.extend([home, home / "Desktop", home / "Documents", home / "Downloads"])
    for key in ("OneDrive", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        raw = os.environ.get(key, "").strip()
        if raw:
            try:
                vals.append(Path(raw).resolve())
            except Exception:
                pass
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        p = Path(letter + ":\\")
        if p.exists():
            try:
                vals.append(p.resolve())
            except Exception:
                pass
    return {str(x).lower().rstrip("\\/") for x in vals}

def safe_extract(zip_path, destination):
    base = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("安装包损坏：" + bad)
        for info in archive.infolist():
            target = (base / info.filename).resolve()
            try:
                target.relative_to(base)
            except Exception:
                raise RuntimeError("安装包路径越界：" + info.filename)
        archive.extractall(base)

def create_shortcut(target, workdir):
    desktop = Path.home() / "Desktop"
    link = desktop / "小美丽（安全版）.lnk"
    link_s = str(link).replace("'", "''")
    target_s = str(target).replace("'", "''")
    work_s = str(workdir).replace("'", "''")
    ps = (
        "$ws=New-Object -ComObject WScript.Shell;"
        "$s=$ws.CreateShortcut('" + link_s + "');"
        "$s.TargetPath='" + target_s + "';"
        "$s.WorkingDirectory='" + work_s + "';"
        "$s.IconLocation='" + target_s + ",0';"
        "$s.Save();"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
    )

def migrate_existing_startup(launcher):
    launcher_s = str(launcher).replace("'", "''")
    ps = (
        "$k='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';"
        "if(Test-Path $k){"
        "$p=Get-ItemProperty $k;"
        "$p.PSObject.Properties|ForEach-Object{"
        "if($_.Name -notmatch '^PS' -and ([string]$_.Value) -match 'XiaoMeili\\.exe'){"
        "Set-ItemProperty -Path $k -Name $_.Name -Value '\"" + launcher_s + "\"' -Force"
        "}}}"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=False,
        )
    except Exception:
        pass

def self_test():
    update_zip = resource("XiaoMeili_0.9.2.1_update.zip")
    launcher = resource("XiaoMeiliLauncher.exe")
    if not update_zip.is_file() or not launcher.is_file():
        return 2
    with zipfile.ZipFile(update_zip, "r") as archive:
        names = {Path(x).name.lower() for x in archive.namelist()}
        if "xiaomeili.exe" not in names:
            return 3
    return 0

def main():
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())

    root = install_root()
    expected = (Path(os.environ["LOCALAPPDATA"]) / ROOT_NAME).resolve()
    if root != expected:
        raise RuntimeError("安装目录校验失败")
    if str(root).lower().rstrip("\\/") in protected_paths():
        raise RuntimeError("安装目录命中受保护路径，已拒绝安装")

    root.mkdir(parents=True, exist_ok=True)
    versions = root / "versions"
    versions.mkdir(parents=True, exist_ok=True)

    marker_path = root / ".xiaomeili-install.json"
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
        if marker.get("product") != PRODUCT or int(marker.get("schema", 0)) < 2:
            raise RuntimeError("现有安装标记不是小美丽安全安装结构")
        install_id = str(marker.get("install_id", "")).strip()
        if not install_id:
            raise RuntimeError("现有安装标记缺少 install_id")
    else:
        install_id = str(uuid.uuid4())
        marker = {
            "schema": 2,
            "product": PRODUCT,
            "install_id": install_id,
            "root_policy": "LOCALAPPDATA_XiaoMeiliApp_ONLY",
            "deletion_policy": "NO_AUTOMATIC_FILE_DELETION",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        marker_path.write_text(
            json.dumps(marker, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    version_dir = versions / (
        "v" + VERSION + "_" + stamp + "_" + uuid.uuid4().hex[:8]
    )
    version_dir.mkdir(parents=False, exist_ok=False)

    safe_extract(resource("XiaoMeili_0.9.2.1_update.zip"), version_dir)

    exe = version_dir / "XiaoMeili.exe"
    if not exe.is_file():
        raise RuntimeError("安装后缺少 XiaoMeili.exe")

    version_file = None
    for candidate in (
        version_dir / "_internal" / "assets" / "VERSION.txt",
        version_dir / "assets" / "VERSION.txt",
    ):
        if candidate.is_file():
            version_file = candidate
            break
    if not version_file:
        raise RuntimeError("安装后缺少 VERSION.txt")
    if version_file.read_text(encoding="utf-8-sig").strip() != VERSION:
        raise RuntimeError("版本校验失败")

    launcher_src = resource("XiaoMeiliLauncher.exe")
    launcher_dst = root / "XiaoMeiliLauncher.exe"
    if not launcher_dst.exists():
        launcher_dst.write_bytes(launcher_src.read_bytes())

    relative_exe = exe.resolve().relative_to(root).as_posix()
    active = {
        "schema": 1,
        "product": PRODUCT,
        "version": VERSION,
        "relative_exe": relative_exe,
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (root / "active.json").write_text(
        json.dumps(active, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    create_shortcut(launcher_dst, root)
    migrate_existing_startup(launcher_dst)
    subprocess.Popen([str(launcher_dst)], cwd=str(root), close_fds=True)

    message(
        "小美丽 V0.9.2.1 安全基线已安装完成。\\n\\n"
        "以后请从桌面的“小美丽（安全版）”启动。\\n"
        "后续更新将在小美丽内部完成，并采用全新版本目录切换；"
        "不会镜像同步，也不会自动删除旧版本或用户文件。"
    )

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        fail(str(exc))
