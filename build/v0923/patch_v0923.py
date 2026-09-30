# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0923.py <source_root>")

root = Path(sys.argv[1]).resolve()
main = root / "app" / "src" / "main.py"
helper = root / "app" / "assets" / "update_helper.ps1"
speech = root / "app" / "src" / "speech_input.py"
version_file = root / "app" / "assets" / "VERSION.txt"

s = main.read_text(encoding="utf-8")
if 'APP_VERSION = "0.9.2.2"' not in s:
    raise RuntimeError("V0.9.2.3 expected V0.9.2.2 base")
s = s.replace('APP_VERSION = "0.9.2.2"', 'APP_VERSION = "0.9.2.3"', 1)
s = s.replace('APP_NAME = "小美丽 V0.9.2.2｜Voice Interaction"', 'APP_NAME = "小美丽 V0.9.2.3｜Voice Interaction"', 1)

# V0.9.2.3 hard safety rule: automatic cleanup is completely disabled.
start = s.find("def cleanup_obsolete_storage():")
end = s.find("\ndef xiaomeili_logical_data_root():", start)
if start < 0 or end < 0:
    raise RuntimeError("cleanup_obsolete_storage boundaries missing")
safe_cleanup = '''def cleanup_obsolete_storage():
    # V0.9.2.3 safety baseline: never delete files automatically.
    LOGGER.info("自动存储清理已禁用：V0.9.2.3 不会自动删除任何文件。")


'''
s = s[:start] + safe_cleanup + s[end+1:]

# Avoid the keyboard package's broken global unhook path seen in V0.9.2.1 logs.
old_hotkeys = '''    def unregister_all(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            LOGGER.warning("清理全局快捷键时 keyboard 库返回异常，已忽略", exc_info=True)
        self.registered = []
'''
new_hotkeys = '''    def unregister_all(self):
        old = list(self.registered)
        self.registered = []
        for combo in old:
            try:
                keyboard.remove_hotkey(combo)
            except Exception:
                LOGGER.info("快捷键解除失败但已忽略: %s", combo)
'''
if old_hotkeys not in s:
    raise RuntimeError("HotkeyManager.unregister_all marker missing")
s = s.replace(old_hotkeys, new_hotkeys, 1)

main.write_text(s, encoding="utf-8")
py_compile.compile(str(main), doraise=True)

hp = helper.read_text(encoding="utf-8-sig")
old_rel = "$relativeExe = [System.IO.Path]::GetRelativePath($actualRoot, $newExe).Replace('\\','/')"
new_rel = "$relativeExe = $newExe.Substring($actualRoot.Length).TrimStart('\\').Replace('\\','/')"
if old_rel not in hp:
    raise RuntimeError("PowerShell 5.1 GetRelativePath compatibility marker missing")
hp = hp.replace(old_rel, new_rel, 1)
if "GetRelativePath" in hp:
    raise RuntimeError("PowerShell 5.1 incompatible GetRelativePath remains")
if "Remove-Item" in hp or "/MIR" in hp or "/PURGE" in hp or "robocopy.exe" in hp:
    raise RuntimeError("V0.9.2.3 update helper contains destructive operation")
helper.write_text(hp, encoding="utf-8")

sp = speech.read_text(encoding="utf-8")
sp = sp.replace("小美丽 V0.9.2.2 语音诊断日志", "小美丽 V0.9.2.3 语音诊断日志")
speech.write_text(sp, encoding="utf-8")
py_compile.compile(str(speech), doraise=True)

version_file.write_text("0.9.2.3\n", encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.3 updater hotfix + no-auto-delete baseline")
