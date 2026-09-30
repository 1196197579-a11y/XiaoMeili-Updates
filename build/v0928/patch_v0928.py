# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0928.py <source_root>")

root=Path(sys.argv[1]).resolve()
main=root/"app/src/main.py"
speech=root/"app/src/speech_input.py"
version_file=root/"app/assets/VERSION.txt"
s=main.read_text(encoding="utf-8")

if 'APP_VERSION = "0.9.2.7"' not in s:
    raise RuntimeError("V0.9.2.8 expected V0.9.2.7 base")
if "import shutil" not in s:
    import_anchor="from pathlib import Path"
    if import_anchor not in s:
        raise RuntimeError("V0.9.2.8 pathlib import anchor missing")
    s=s.replace(import_anchor,"import shutil\n"+import_anchor,1)

s=s.replace('APP_VERSION = "0.9.2.7"','APP_VERSION = "0.9.2.8"',1)
s=s.replace('APP_NAME = "小美丽 V0.9.2.7｜Voice Interaction"','APP_NAME = "小美丽 V0.9.2.8｜Voice Interaction"',1)
s=s.replace("自动存储清理已禁用：V0.9.2.7 不会自动删除任何文件。","自动存储清理已禁用：V0.9.2.8 不会自动删除任何文件。",1)

# ------------------------------------------------------------------
# Stable desktop launcher
#
# The versioned XiaoMeili.exe lives under:
#   %LOCALAPPDATA%\\XiaoMeiliApp\\versions\\v<version>_...\\
# A desktop copy of the tiny, version-independent launcher gives the user one
# permanent entry point.  It reads active.json and always starts the currently
# activated version.  It is CREATED ONLY WHEN MISSING.  Existing desktop files
# are never overwritten, renamed, moved or deleted.
# ------------------------------------------------------------------
main_anchor='''def main():
    set_windows_app_identity()
'''
if main_anchor not in s:
    raise RuntimeError("V0.9.2.8 main startup anchor missing")

helper=r'''def ensure_desktop_launcher():
    """Create a stable desktop XiaoMeili launcher without touching existing files."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        target = desktop_dir() / "小美丽.exe"
        if target.exists():
            return target

        candidates = [
            Path(sys.executable).resolve().parent / "XiaoMeiliLauncher.exe",
        ]
        local = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local:
            candidates.append(Path(local).absolute() / "XiaoMeiliApp" / "XiaoMeiliLauncher.exe")

        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            LOGGER.warning("稳定桌面启动器源文件不存在；跳过桌面入口创建")
            return None

        target.parent.mkdir(parents=True, exist_ok=True)
        # xb = create-new only.  This deliberately cannot overwrite an existing
        # Desktop file, matching XiaoMeili's no-delete/no-replace safety policy.
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        LOGGER.info("已创建稳定桌面启动器：%s -> active.json 当前版本", target)
        return target
    except FileExistsError:
        return desktop_dir() / "小美丽.exe"
    except Exception:
        LOGGER.warning("创建稳定桌面启动器失败（不影响小美丽运行）", exc_info=True)
        return None


'''
s=s.replace(main_anchor,helper+main_anchor,1)

old_main='''def main():
    set_windows_app_identity()
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); app.setApplicationName(APP_NAME); app.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
    cfg=load_config()
'''
new_main='''def main():
    set_windows_app_identity()
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); app.setApplicationName(APP_NAME); app.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
    ensure_desktop_launcher()
    cfg=load_config()
'''
if old_main not in s:
    raise RuntimeError("V0.9.2.8 exact main call anchor missing")
s=s.replace(old_main,new_main,1)

# Safety verification.
checks=[
    'APP_VERSION = "0.9.2.8"',
    'def ensure_desktop_launcher():',
    'target = desktop_dir() / "小美丽.exe"',
    'target.open("xb")',
    'ensure_desktop_launcher()',
    'from native_updater import install_update_package',
    'install_update_package(',
]
for token in checks:
    if token not in s:
        raise RuntimeError("V0.9.2.8 verification missing: "+token)

a=s.find("def ensure_desktop_launcher():")
b=s.find("\ndef main():",a)
if a<0 or b<0:
    raise RuntimeError("V0.9.2.8 desktop launcher helper boundaries missing")
desktop_block=s[a:b]
for forbidden in ("unlink(","rmtree(","os.remove(","replace(","rename(","shutil.move("):
    if forbidden in desktop_block:
        raise RuntimeError("V0.9.2.8 desktop launcher violates no-delete/no-replace policy: "+forbidden)

# Native updater remains the protected version-switch mechanism.
method_start=s.find("    def install_latest_async(self):")
method_end=s.find("\n\ndef _path_size_bytes",method_start)
if method_start<0 or method_end<0:
    raise RuntimeError("V0.9.2.8 updater method missing")
update_method=s[method_start:method_end]
for forbidden in ('powershell.exe','update_helper.ps1','robocopy','/MIR','/PURGE'):
    if forbidden in update_method:
        raise RuntimeError("V0.9.2.8 updater regression: "+forbidden)

main.write_text(s,encoding="utf-8")
py_compile.compile(str(main),doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.7 语音诊断日志","小美丽 V0.9.2.8 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech),doraise=True)

version_file.write_text("0.9.2.8\n",encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.8 stable desktop launcher")
