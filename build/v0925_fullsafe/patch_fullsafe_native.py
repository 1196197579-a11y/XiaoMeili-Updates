# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_fullsafe_native.py <source_root> <repo_root>")

root = Path(sys.argv[1]).resolve()
repo = Path(sys.argv[2]).resolve()
main = root / "app" / "src" / "main.py"
native_dst = root / "app" / "src" / "native_updater.py"
native_src = repo / "build" / "v0925_fullsafe" / "native_updater.py"

s = main.read_text(encoding="utf-8")
if 'APP_VERSION = "0.9.2.5"' not in s:
    raise RuntimeError("FullSafe patch requires V0.9.2.5 source")

anchor = "from speech_input import SpeechInputService\n"
if anchor not in s:
    raise RuntimeError("speech import anchor missing")
if "from native_updater import install_update_package" not in s:
    s = s.replace(anchor, anchor + "from native_updater import install_update_package\n", 1)

a = s.find("    def install_latest_async(self):\n")
b = s.find("\n\ndef _path_size_bytes", a)
if a < 0 or b < 0:
    raise RuntimeError("install_latest_async boundaries missing")
method = s[a:b]

x = method.find('                helper = Path(resource("assets/update_helper.ps1"))\n')
last = '                self.restart_requested.emit()\n'
y = method.find(last, x)
if x < 0 or y < 0:
    raise RuntimeError("legacy updater tail not found")
y += len(last)

replacement = r'''                if not getattr(sys, "frozen", False):
                    raise RuntimeError("开发模式不执行正式更新，请在打包后的 XiaoMeili.exe 中测试。")

                local_appdata = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
                if not local_appdata:
                    raise RuntimeError("无法读取 LOCALAPPDATA，安全更新已停止。")
                install_root = Path(local_appdata).absolute() / "XiaoMeiliApp"
                current_exe = Path(sys.executable).resolve()
                native_log = UPDATE_LOG_DIR / "native_updater.log"

                self.progress_changed.emit(96, "校验完成，正在创建全新的版本目录…")
                result = install_update_package(
                    package=package,
                    install_root=install_root,
                    expected_version=version,
                    expected_sha256=expected,
                    current_exe=current_exe,
                    log_path=native_log,
                )
                launcher = Path(result["launcher"])
                self.progress_changed.emit(
                    100,
                    f"{source_name}下载并校验完成，V{version} 已安全安装到独立版本目录，正在重启…",
                )
                subprocess.Popen(
                    [str(launcher)],
                    cwd=str(install_root),
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                time.sleep(0.35)
                self.restart_requested.emit()
'''
method = method[:x] + replacement + method[y:]
if "install_update_package(" not in method:
    raise RuntimeError("native updater call missing")
s = s[:a] + method + s[b:]

main.write_text(s, encoding="utf-8")
shutil.copy2(native_src, native_dst)
py_compile.compile(str(main), doraise=True)
py_compile.compile(str(native_dst), doraise=True)
print("Patched V0.9.2.5 with native updater")
