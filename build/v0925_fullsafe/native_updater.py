# -*- coding: utf-8 -*-
"""XiaoMeili native versioned updater.

Safety contract:
- only installs under %LOCALAPPDATA%\\XiaoMeiliApp
- only creates a fresh versions/v<version>_* directory
- never mirrors, purges, removes, unlinks, or recursively deletes files
- never touches Desktop/Documents/Downloads/XiaoMeiliData
- switches versions only after full ZIP/hash/version verification
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import time
import uuid
import zipfile

PRODUCT = "XiaoMeili"
ROOT_NAME = "XiaoMeiliApp"
MARKER_NAME = ".xiaomeili-install.json"


class NativeUpdateError(RuntimeError):
    pass


def _log(path, text):
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except Exception:
        pass


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _expected_root():
    local = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if not local:
        raise NativeUpdateError("LOCALAPPDATA 不可用，安全更新已停止。")
    lexical = Path(local).absolute() / ROOT_NAME
    resolved_parent = Path(local).resolve()
    resolved = lexical.resolve()
    if resolved.parent != resolved_parent:
        raise NativeUpdateError("安装根目录存在重定向/联接，安全更新已停止。")
    return lexical, resolved


def _validate_root(install_root, current_exe=None):
    expected_lexical, expected_resolved = _expected_root()
    actual_lexical = Path(install_root).absolute()
    actual_resolved = actual_lexical.resolve()
    if os.path.normcase(str(actual_lexical)) != os.path.normcase(str(expected_lexical)):
        raise NativeUpdateError(
            f"安装根目录不安全：expected={expected_lexical} actual={actual_lexical}"
        )
    if os.path.normcase(str(actual_resolved)) != os.path.normcase(str(expected_resolved)):
        raise NativeUpdateError("安装根目录解析结果异常，安全更新已停止。")

    marker_path = actual_resolved / MARKER_NAME
    if not marker_path.is_file():
        raise NativeUpdateError("安全安装标记缺失。")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise NativeUpdateError(f"安全安装标记无法读取：{exc}") from exc
    if (
        marker.get("product") != PRODUCT
        or int(marker.get("schema", 0) or 0) < 2
        or not str(marker.get("install_id", "") or "").strip()
    ):
        raise NativeUpdateError("安全安装标记无效。")
    if str(marker.get("deletion_policy", "") or "") != "NO_AUTOMATIC_FILE_DELETION":
        raise NativeUpdateError("安装标记缺少 NO_AUTOMATIC_FILE_DELETION 策略。")

    versions = actual_resolved / "versions"
    if not versions.is_dir():
        raise NativeUpdateError("安全版本目录缺失。")

    launcher = actual_resolved / "XiaoMeiliLauncher.exe"
    if not launcher.is_file():
        raise NativeUpdateError("稳定启动器缺失。")

    if current_exe:
        cur = Path(current_exe).resolve()
        try:
            cur.relative_to(versions.resolve())
        except Exception as exc:
            raise NativeUpdateError("当前程序不在受保护的 versions 目录中。") from exc

    return actual_resolved, versions, launcher


def _safe_parts(name):
    clean = str(name or "").replace("\\", "/")
    if not clean or clean.startswith("/") or "\x00" in clean:
        raise NativeUpdateError(f"ZIP 路径非法：{name}")
    p = PurePosixPath(clean)
    parts = [x for x in p.parts if x not in ("", ".")]
    if not parts or ".." in parts:
        raise NativeUpdateError(f"ZIP 路径越界：{name}")
    for part in parts:
        if ":" in part:
            raise NativeUpdateError(f"ZIP 路径包含非法冒号：{name}")
    return parts


def _is_zip_symlink(info):
    mode = (int(info.external_attr) >> 16) & 0o170000
    return mode == 0o120000


def _extract_new_only(package, destination):
    base = Path(destination).resolve()
    with zipfile.ZipFile(package, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise NativeUpdateError(f"ZIP 内部文件损坏：{bad}")
        infos = zf.infolist()
        for info in infos:
            if _is_zip_symlink(info):
                raise NativeUpdateError(f"ZIP 符号链接已拒绝：{info.filename}")
            parts = _safe_parts(info.filename)
            target = (base.joinpath(*parts)).resolve()
            try:
                target.relative_to(base)
            except Exception as exc:
                raise NativeUpdateError(f"ZIP 路径越界：{info.filename}") from exc

        for info in infos:
            parts = _safe_parts(info.filename)
            target = base.joinpath(*parts)
            is_dir = info.is_dir() or str(info.filename).replace("\\", "/").endswith("/")
            if is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise NativeUpdateError(f"新版本目录中意外存在同名文件：{target}")
            with zf.open(info, "r") as src, target.open("xb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())


def install_update_package(
    package,
    install_root,
    expected_version,
    expected_sha256,
    current_exe=None,
    log_path=None,
):
    package = Path(package)
    expected_version = str(expected_version or "").strip()
    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if not expected_version:
        raise NativeUpdateError("目标版本为空。")

    root, versions, launcher = _validate_root(install_root, current_exe=current_exe)
    _log(log_path, f"NATIVE updater start package={package} root={root} version={expected_version}")

    if not package.is_file():
        raise NativeUpdateError(f"更新包不存在：{package}")
    actual_sha = _sha256(package)
    if expected_sha256 and actual_sha != expected_sha256:
        raise NativeUpdateError(
            f"SHA-256 不一致：expected={expected_sha256} actual={actual_sha}"
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    version_dir = versions / (
        f"v{expected_version}_{stamp}_{uuid.uuid4().hex[:8]}"
    )
    if version_dir.exists():
        raise NativeUpdateError("新版本目录意外已存在。")
    version_dir.mkdir(parents=False, exist_ok=False)

    _extract_new_only(package, version_dir)

    exe = version_dir / "XiaoMeili.exe"
    if not exe.is_file():
        raise NativeUpdateError("新版本缺少 XiaoMeili.exe。")

    version_file = None
    for candidate in (
        version_dir / "_internal" / "assets" / "VERSION.txt",
        version_dir / "assets" / "VERSION.txt",
    ):
        if candidate.is_file():
            version_file = candidate
            break
    if version_file is None:
        raise NativeUpdateError("新版本缺少 VERSION.txt。")
    actual_version = version_file.read_text(encoding="utf-8-sig").strip()
    if actual_version != expected_version:
        raise NativeUpdateError(
            f"版本校验失败：expected={expected_version} actual={actual_version}"
        )

    active_path = root / "active.json"
    history = root / "active_history"
    history.mkdir(parents=True, exist_ok=True)
    if active_path.is_file():
        old_text = active_path.read_text(encoding="utf-8-sig")
        backup = history / (
            "active_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".json"
        )
        backup.write_text(old_text, encoding="utf-8")

    active = {
        "schema": 1,
        "product": PRODUCT,
        "version": expected_version,
        "relative_exe": exe.resolve().relative_to(root).as_posix(),
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updater": "native-no-delete-v1",
    }
    with active_path.open("w", encoding="utf-8") as f:
        json.dump(active, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

    _log(
        log_path,
        f"Activated V{expected_version} at {version_dir}. "
        "No existing version or user file was deleted.",
    )
    return {
        "version_dir": str(version_dir),
        "launcher": str(launcher),
        "active_json": str(active_path),
        "sha256": actual_sha,
    }
