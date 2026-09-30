# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import shutil
import sys
from pathlib import Path

SAFE_MANIFEST = "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest_safe.json"

def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")

    if 'APP_VERSION = "0.9.1.1"' not in s:
        raise RuntimeError("V0.9.2 expected APP_VERSION 0.9.1.1 base")
    s = s.replace('APP_VERSION = "0.9.1.1"', 'APP_VERSION = "0.9.2"', 1)

    s = s.replace(
        "https://raw.githubusercontent.com/1196197579-a11y/XiaoMeili-Updates/main/latest.json",
        SAFE_MANIFEST,
    )

    cfg_pos = s.find("old_updates =")
    if cfg_pos < 0:
        raise RuntimeError("V0.9.2 config migration anchor missing")
    ret_pos = s.find("\n    return cfg", cfg_pos)
    if ret_pos < 0:
        raise RuntimeError("V0.9.2 config return anchor missing")
    force_cfg = '\n    cfg.setdefault("updates", {})["manifest_url"] = "' + SAFE_MANIFEST + '"\n'
    s = s[:ret_pos] + force_cfg + s[ret_pos:]

    old_tail = '''                target = Path(sys.executable).parent
                exe_name = Path(sys.executable).name
                updater_log = UPDATE_LOG_DIR / "updater.log"
                runtime_helper = UPDATE_DIR / "update_helper_runtime.ps1"
                shutil.copy2(helper, runtime_helper)
                args = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(runtime_helper),
                    "-Package", str(package),
                    "-Target", str(target),
                    "-ExeName", exe_name,
                    "-ParentPid", str(os.getpid()),
                    "-LogPath", str(updater_log),
                    "-DiagnosticDir", str(UPDATE_DIAGNOSTIC_DIR),
                ]
'''
    new_tail = '''                local_appdata = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
                if not local_appdata:
                    raise RuntimeError("无法读取 LOCALAPPDATA，安全更新已停止。")
                install_root = Path(local_appdata).resolve() / "XiaoMeiliApp"
                marker = install_root / ".xiaomeili-install.json"
                versions_root = install_root / "versions"
                current_exe = Path(sys.executable).resolve()
                if not marker.is_file():
                    raise RuntimeError("当前不是安全安装结构：缺少安装标记。请使用 V0.9.2 安全安装包完成一次迁移。")
                try:
                    current_exe.relative_to(versions_root.resolve())
                except Exception:
                    raise RuntimeError("当前程序不在受保护的版本目录中，自动更新已拒绝执行。请使用 V0.9.2 安全安装包。")

                updater_log = UPDATE_LOG_DIR / "updater_safe.log"
                runtime_helper = UPDATE_DIR / f"safe_update_helper_{version}_{int(time.time()*1000)}.ps1"
                shutil.copy2(helper, runtime_helper)
                args = [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(runtime_helper),
                    "-Package", str(package),
                    "-InstallRoot", str(install_root),
                    "-ExpectedVersion", version,
                    "-ExpectedSha256", expected,
                    "-ParentPid", str(os.getpid()),
                    "-LogPath", str(updater_log),
                    "-DiagnosticDir", str(UPDATE_DIAGNOSTIC_DIR),
                ]
'''
    if old_tail not in s:
        raise RuntimeError("V0.9.2 dangerous updater tail anchor missing")
    s = s.replace(old_tail, new_tail, 1)

    s = s.replace(
        '''                try:
                    part.unlink(missing_ok=True)
                    package.unlink(missing_ok=True)
                except Exception:
                    pass
''',
        '''                # V0.9.2 safety: update staging is append-only; no file deletion.
''',
        1,
    )
    s = s.replace(
        'package = UPDATE_DIR / f"XiaoMeili_{version}_update.zip"\n                part = package.with_suffix(".zip.part")',
        'session_id = f"{version}_{int(time.time()*1000)}"\n                package = UPDATE_DIR / f"XiaoMeili_{session_id}_update.zip"\n                part = UPDATE_DIR / f"XiaoMeili_{session_id}_update.zip.part"',
        1,
    )

    method_start = s.find("    def install_latest_async(self):")
    method_end = s.find("\n\ndef _path_size_bytes", method_start)
    if method_start < 0 or method_end < 0:
        raise RuntimeError("V0.9.2 install_latest_async boundaries missing")
    method = s[method_start:method_end]
    method = method.replace(
        '''                            try:
                                part.unlink(missing_ok=True)
                            except Exception:
                                pass
''',
        '''                            # Keep failed partial download for diagnostics; never delete it.
''',
    )
    method = method.replace(
        '''                        try:
                            part.unlink(missing_ok=True)
                        except Exception:
                            pass
''',
        '''                        # Reuse this private staging file; never delete it automatically.
''',
    )
    s = s[:method_start] + method + s[method_end:]

    s = s.replace("正在安全重启安装…", "已校验完成，正在切换到全新的版本目录…")
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)

def patch_speech(path: Path):
    s = path.read_text(encoding="utf-8")
    s = s.replace("小美丽 V0.9.1.1 语音诊断日志", "小美丽 V0.9.2 语音诊断日志")
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)

def patch(source_root: Path, repo_root: Path):
    root = Path(source_root).resolve()
    repo = Path(repo_root).resolve()
    main = root / "app" / "src" / "main.py"
    speech = root / "app" / "src" / "speech_input.py"
    helper = root / "app" / "assets" / "update_helper.ps1"
    helper_src = repo / "build" / "v092" / "update_helper_safe.ps1"
    for p in (main, speech, helper_src):
        if not p.exists():
            raise FileNotFoundError(p)
    patch_main(main)
    patch_speech(speech)
    shutil.copy2(helper_src, helper)

    m = main.read_text(encoding="utf-8")
    h = helper.read_text(encoding="utf-8-sig")
    checks = [
        'APP_VERSION = "0.9.2"',
        'latest_safe.json',
        'install_root = Path(local_appdata).resolve() / "XiaoMeiliApp"',
        'current_exe.relative_to(versions_root.resolve())',
        '"-InstallRoot", str(install_root)',
    ]
    for token in checks:
        if token not in m:
            raise RuntimeError("V0.9.2 verification failed: " + token)
    for forbidden in ('target = Path(sys.executable).parent', '/MIR', '/PURGE'):
        if forbidden in h:
            raise RuntimeError("V0.9.2 helper still contains forbidden token: " + forbidden)
    if "XIAOMEILI_INSTALL_ROOT_MARKER" not in h or "PROTECTED_USER_PATHS" not in h:
        raise RuntimeError("V0.9.2 helper safety markers missing")
    print("Patched XiaoMeili source to V0.9.2 safe versioned updater")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v092.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]), Path(sys.argv[2]))
