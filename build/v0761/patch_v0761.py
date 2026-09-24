# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import shutil
import sys
from pathlib import Path


def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    helper_src = repo_root / "build" / "v0761" / "storage_migrate_v0761.ps1"
    helper_dst = source_root / "app" / "assets" / "storage_migrate.ps1"

    if not main_path.exists() or not helper_src.exists():
        raise FileNotFoundError("v0.7.6.1 source inputs missing")
    shutil.copy2(helper_src, helper_dst)

    s = main_path.read_text(encoding="utf-8")
    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.6"',
        'APP_NAME = "小美丽 V0.7.6.1｜D Drive Migration Hotfix"\nAPP_VERSION = "0.7.6.1"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("v0.7.6.1 version replacement failed")

    start = s.index("    def start_storage_migration(self, target):", s.index("class AppController(QObject):"))
    end = s.index("    def quit(self):", start)
    new_method = r'''    def start_storage_migration(self, target):
        try:
            if not getattr(sys, "frozen", False):
                raise RuntimeError("开发模式不执行存储迁移，请在正式 XiaoMeili.exe 中操作。")
            helper = Path(resource("assets/storage_migrate.ps1"))
            if not helper.exists():
                raise FileNotFoundError(f"存储迁移助手缺失：{helper}")

            source = xiaomeili_logical_data_root()
            target = Path(str(target or r"D:\XiaoMeiliData"))
            desktop_log = desktop_dir() / "小美丽_D盘迁移日志_请上传给ChatGPT.txt"
            ready_file = Path(tempfile.gettempdir()) / f"XiaoMeili_storage_ready_{os.getpid()}.txt"
            try:
                ready_file.unlink(missing_ok=True)
            except Exception:
                pass

            args = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(helper),
                "-Source", str(source),
                "-Target", str(target),
                "-ParentPid", str(os.getpid()),
                "-ExePath", str(Path(sys.executable)),
                "-DesktopLog", str(desktop_log),
                "-ReadyFile", str(ready_file),
            ]
            proc = subprocess.Popen(
                args,
                cwd=str(Path(sys.executable).parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )

            # V0.7.6.1 handshake: NEVER close XiaoMeili merely because PowerShell is alive.
            # Wait until the helper proves that it parsed correctly and completed basic preflight.
            ready = False
            for _ in range(50):
                if ready_file.exists():
                    ready = True
                    break
                rc = proc.poll()
                if rc is not None:
                    detail = ""
                    try:
                        if desktop_log.exists():
                            detail = desktop_log.read_text(encoding="utf-8-sig", errors="replace")[-2400:]
                    except Exception:
                        pass
                    raise RuntimeError(f"存储迁移助手启动失败（exit={rc}）。{detail}")
                time.sleep(0.08)

            if not ready:
                try:
                    proc.terminate()
                except Exception:
                    pass
                raise RuntimeError("存储迁移助手 4 秒内没有完成启动握手。为保护现有数据，小美丽保持运行且没有开始迁移。")

            LOGGER.info("D盘迁移助手握手成功：%s -> %s", source, target)
            self.quit()
        except Exception as exc:
            LOGGER.exception("启动 D 盘迁移失败")
            QMessageBox.critical(
                None,
                "小美丽存储迁移失败",
                f"没有改动现有数据。错误：{type(exc).__name__}: {exc}\n\n"
                "如果桌面生成了「小美丽_D盘迁移日志_请上传给ChatGPT.txt」，请直接上传给我。",
            )
            if self.settings:
                try:
                    self.settings.storage_migrate_btn.setEnabled(True)
                    self.settings._refresh_storage_status()
                except Exception:
                    pass

'''
    s = s[:start] + new_method + s[end:]

    # Make the storage note explicitly identify the hotfix behavior.
    old = "迁移时小美丽会自动退出，完成后自动重新打开。迁移前会先完整复制并逐文件校验，"
    new = "V0.7.6.1 会先等待迁移助手启动握手成功，只有确认 PowerShell 已正常解析后小美丽才会退出。迁移前会先完整复制并逐文件校验，"
    if old in s:
        s = s.replace(old, new, 1)

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.6.1 migration hotfix")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0761.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
