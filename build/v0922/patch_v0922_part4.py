from pathlib import Path
import re, textwrap, shutil, json, os
import sys
if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v0922.py <source_root>')
root=Path(sys.argv[1]).resolve()
main=root/'app/src/main.py'
s=main.read_text(encoding='utf-8')

# Harden D-drive migration: preserve the original C: copy and use unique
# handshake/log names so normal migration does not proactively delete files.
old_migration_tmp = r'''            desktop_log = STORAGE_DIAGNOSTIC_DIR / f"migration_{time.strftime('%Y%m%d_%H%M%S')}.log"
            ready_file = Path(tempfile.gettempdir()) / f"XiaoMeili_storage_ready_{os.getpid()}.txt"
            try:
                ready_file.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                desktop_log.unlink(missing_ok=True)
            except Exception:
                pass
'''
new_migration_tmp = r'''            migration_token = uuid.uuid4().hex[:10]
            desktop_log = STORAGE_DIAGNOSTIC_DIR / f"migration_{time.strftime('%Y%m%d_%H%M%S')}_{migration_token}.log"
            ready_file = Path(tempfile.gettempdir()) / f"XiaoMeili_storage_ready_{os.getpid()}_{migration_token}.txt"
'''
if old_migration_tmp not in s:
    raise RuntimeError('V0.9.2.2 storage migration temp marker missing')
s=s.replace(old_migration_tmp,new_migration_tmp,1)

main.write_text(s,encoding='utf-8')

storage=root/'app/assets/storage_migrate.ps1'
ms=storage.read_text(encoding='utf-8-sig')
ms=ms.replace("    try { Remove-Item -LiteralPath $DesktopLog -Force -ErrorAction SilentlyContinue } catch {}\n    try { Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue } catch {}\n\n", "", 1)
old_backup='''        Log "Junction verification passed. Removing the old C: copy to reclaim space."
        Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
        Log "Old C: copy removed successfully."'''
new_backup='''        Log "Junction verification passed. Keeping the original C: copy as a safety backup."
        Log ("Safety backup retained at: " + $backup)'''
if old_backup not in ms:
    raise RuntimeError('V0.9.2.2 storage backup-retention marker missing')
ms=ms.replace(old_backup,new_backup,1)
storage.write_text(ms,encoding='utf-8')

# Speech and VERSION bump
speech=root/'app/src/speech_input.py'
sp=speech.read_text(encoding='utf-8').replace('小美丽 V0.9.2.1 语音诊断日志','小美丽 V0.9.2.2 语音诊断日志')
speech.write_text(sp,encoding='utf-8')
(root/'app/assets/VERSION.txt').write_text('0.9.2.2\n',encoding='ascii')
print('Patched XiaoMeili source to V0.9.2.2')
