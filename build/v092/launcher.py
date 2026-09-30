# -*- coding: utf-8 -*-
import ctypes
import json
import os
import subprocess
from pathlib import Path

PRODUCT = "XiaoMeili"
ROOT_NAME = "XiaoMeiliApp"

def install_root():
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise RuntimeError("LOCALAPPDATA 不可用")
    return (Path(local) / ROOT_NAME).resolve()

def fail(message):
    try:
        ctypes.windll.user32.MessageBoxW(0, str(message), "小美丽启动失败", 0x10)
    finally:
        raise SystemExit(1)

def main():
    root = install_root()
    marker_path = root / ".xiaomeili-install.json"
    active_path = root / "active.json"
    if not marker_path.is_file() or not active_path.is_file():
        fail("安全安装信息缺失，请重新运行小美丽安全安装包。")

    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
        active = json.loads(active_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        fail(f"安装信息损坏：{exc}")

    if marker.get("product") != PRODUCT or int(marker.get("schema", 0)) < 2:
        fail("安装标记无效。")

    rel = str(active.get("relative_exe", "")).replace("/", os.sep)
    exe = (root / rel).resolve()
    versions_root = (root / "versions").resolve()
    try:
        exe.relative_to(versions_root)
    except Exception:
        fail("启动路径越界，已拒绝运行。")

    if exe.name.lower() != "xiaomeili.exe" or not exe.is_file():
        fail("当前激活版本不存在。")

    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)

if __name__ == "__main__":
    main()
