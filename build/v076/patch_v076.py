# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import shutil
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.6 patch anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    migrate_src = repo_root / "build" / "v076" / "storage_migrate.ps1"
    updater_src = repo_root / "build" / "v076" / "update_helper_v076.ps1"
    migrate_dst = source_root / "app" / "assets" / "storage_migrate.ps1"
    updater_dst = source_root / "app" / "assets" / "update_helper.ps1"

    if not main_path.exists() or not migrate_src.exists() or not updater_src.exists():
        raise FileNotFoundError("v0.7.6 source inputs missing")

    shutil.copy2(migrate_src, migrate_dst)
    shutil.copy2(updater_src, updater_dst)

    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.5"',
        'APP_NAME = "小美丽 V0.7.6｜D Drive Storage Migration"\nAPP_VERSION = "0.7.6"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Storage helpers are intentionally based on the old logical C path. After migration
    # that path becomes a Windows directory junction pointing to D:, which keeps every
    # historical absolute asset/model/config path valid without touching visual behavior.
    settings_anchor = 'class SettingsDialog(QDialog):\n'
    storage_helpers = r'''def xiaomeili_logical_data_root():
    if sys.platform == "win32":
        return Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    return USER


def xiaomeili_physical_data_root():
    root = xiaomeili_logical_data_root()
    try:
        return Path(os.path.realpath(str(root)))
    except Exception:
        return root


def format_storage_size(value):
    try:
        value = int(value or 0)
    except Exception:
        value = 0
    if value >= 1024 ** 3:
        return f"{value / (1024 ** 3):.2f} GB"
    if value >= 1024 ** 2:
        return f"{value / (1024 ** 2):.1f} MB"
    return f"{value / 1024:.1f} KB"


def storage_is_on_d():
    if sys.platform != "win32":
        return False
    try:
        physical = xiaomeili_physical_data_root()
        return str(physical.drive or "").upper() == "D:"
    except Exception:
        return False


'''
    if settings_anchor not in s:
        raise RuntimeError("SettingsDialog anchor missing")
    s = s.replace(settings_anchor, storage_helpers + settings_anchor, 1)

    # New signal used so AppController can shut down voice/brain/vision cleanly before the
    # external migration helper touches the data tree.
    signal_anchor = '''class SettingsDialog(QDialog):
    hotkeys_changed = Signal()
    config_changed = Signal()
'''
    signal_new = '''class SettingsDialog(QDialog):
    hotkeys_changed = Signal()
    config_changed = Signal()
    storage_migration_requested = Signal(str)
'''
    s = replace_once(s, signal_anchor, signal_new, "storage migration signal")

    # Add storage tab after Update, before Vision.
    tab_anchor = '''        self.update_service.progress_changed.connect(self._update_progress_changed)

        # Vision
'''
    tab_new = '''        self.update_service.progress_changed.connect(self._update_progress_changed)

        # Storage V0.7.6
        sp = QWidget(); sv = QVBoxLayout(sp)
        sbox = QGroupBox("小美丽存储位置"); sf = QFormLayout(sbox)
        self.storage_current = QLabel("")
        self.storage_current.setWordWrap(True)
        sf.addRow("当前位置", self.storage_current)

        target_row = QWidget(); target_l = QHBoxLayout(target_row); target_l.setContentsMargins(0,0,0,0)
        self.storage_target = QLineEdit(r"D:\\XiaoMeiliData")
        self.storage_browse = QPushButton("选择目录")
        self.storage_browse.clicked.connect(self._storage_browse)
        target_l.addWidget(self.storage_target, 1); target_l.addWidget(self.storage_browse)
        sf.addRow("迁移目标", target_row)

        self.storage_migrate_btn = QPushButton("一键迁移到 D 盘并自动重启")
        self.storage_migrate_btn.clicked.connect(self._storage_migrate)
        sf.addRow(self.storage_migrate_btn)

        self.storage_refresh_btn = QPushButton("刷新存储状态")
        self.storage_refresh_btn.clicked.connect(self._refresh_storage_status)
        sf.addRow(self.storage_refresh_btn)

        sv.addWidget(sbox)
        snote = QLabel(
            "V0.7.6 会把 XiaoMeiliData 整体搬到 D 盘，包括 Qwen3-8B、llama.cpp、Qwen3-TTS、"
            "语音运行环境、动作素材、养成库、日志、调试文件和更新缓存。\\n"
            "为保证以前所有绝对路径和桌宠效果完全不变，C:\\\\Users\\\\Public\\\\XiaoMeiliData "
            "会变成一个几乎不占空间的 Windows 兼容入口（Junction），实际文件全部在 D 盘。\\n"
            "小美丽程序核心 EXE 仍保留在原安装位置，因为它体积远小于模型，并可避免破坏现有快捷方式与自更新器。"
        )
        snote.setWordWrap(True); sv.addWidget(snote); sv.addStretch(1)
        self.tabs.addTab(sp, "存储")
        self._refresh_storage_status()

        # Vision
'''
    s = replace_once(s, tab_anchor, tab_new, "storage tab")

    # Storage UI methods inside SettingsDialog.
    method_anchor = '    @staticmethod\n    def _semantic_rule_text(rule):\n'
    storage_methods = r'''    def _refresh_storage_status(self):
        if not hasattr(self, "storage_current"):
            return
        logical = xiaomeili_logical_data_root()
        physical = xiaomeili_physical_data_root()
        try:
            size = _path_size_bytes(logical)
        except Exception:
            size = 0
        on_d = storage_is_on_d()
        if on_d:
            text = (
                f"逻辑兼容入口：{logical}\n"
                f"实际数据位置：{physical}\n"
                f"当前数据量：{format_storage_size(size)}\n"
                "状态：✅ 大模型/组件/缓存已经实际存放在 D 盘"
            )
        else:
            text = (
                f"当前数据目录：{logical}\n"
                f"实际数据位置：{physical}\n"
                f"当前数据量：{format_storage_size(size)}\n"
                "状态：⚠️ 目前仍实际占用 C 盘空间"
            )
        self.storage_current.setText(text)
        if hasattr(self, "storage_migrate_btn"):
            self.storage_migrate_btn.setEnabled(sys.platform == "win32" and not on_d)
            self.storage_migrate_btn.setText(
                "已经迁移到 D 盘" if on_d else "一键迁移到 D 盘并自动重启"
            )

    def _storage_browse(self):
        start = self.storage_target.text().strip() or r"D:\\XiaoMeiliData"
        chosen = QFileDialog.getExistingDirectory(self, "选择 D 盘中的小美丽数据目录", start)
        if chosen:
            self.storage_target.setText(chosen)

    def _storage_migrate(self):
        if sys.platform != "win32":
            QMessageBox.warning(self, "存储迁移", "D 盘迁移功能只用于 Windows。")
            return
        if storage_is_on_d():
            QMessageBox.information(self, "存储迁移", "小美丽的数据已经实际存放在 D 盘。")
            self._refresh_storage_status()
            return

        target = self.storage_target.text().strip()
        if not target:
            target = r"D:\\XiaoMeiliData"
        try:
            target_path = Path(target)
        except Exception:
            QMessageBox.warning(self, "存储迁移", "目标路径无效。")
            return
        if str(target_path.drive or "").upper() != "D:":
            QMessageBox.warning(self, "存储迁移", "为了按你的要求释放 C 盘，请选择 D: 盘中的目录。")
            return
        if not Path("D:/").exists():
            QMessageBox.warning(self, "存储迁移", "没有检测到 D: 盘。")
            return

        logical = xiaomeili_logical_data_root()
        size = _path_size_bytes(logical)
        answer = QMessageBox.question(
            self,
            "把小美丽搬到 D 盘",
            "准备迁移以下内容：\n\n"
            f"当前：{logical}\n"
            f"目标：{target_path}\n"
            f"预计数据量：{format_storage_size(size)}\n\n"
            "包含大脑模型、TTS 模型/运行环境、动作素材、养成数据、日志、调试文件和更新缓存。\n"
            "迁移时小美丽会自动退出，完成后自动重新打开。迁移前会先完整复制并逐文件校验，"
            "只有校验通过才删除 C 盘旧副本；失败会自动回滚，不会拿现有效果冒险。\n\n"
            "现在开始吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.storage_migrate_btn.setEnabled(False)
        self.storage_current.setText("迁移助手即将启动，小美丽会安全退出。请不要在迁移过程中关闭迁移窗口或关机。")
        self.storage_migration_requested.emit(str(target_path))

'''
    if method_anchor not in s:
        raise RuntimeError("semantic method anchor missing")
    s = s.replace(method_anchor, storage_methods + method_anchor, 1)

    # Make cleanup reclaim old C-drive update artifacts from pre-v0.7.6 updater runs.
    cleanup_anchor = '''        # Kokoro has been fully retired since V0.6.2. Qwen3-TTS is the only active voice backend.
        legacy_kokoro = USER / "voice" / "kokoro_v1_1_zh"
'''
    cleanup_new = '''        # V0.7.6: clean stale update extraction/backup artifacts left by older updater versions.
        try:
            for p in list(UPDATE_DIR.iterdir()) if UPDATE_DIR.exists() else []:
                if p.is_dir() and (p.name.startswith("update_work_") or p.name.startswith("program_backup_")):
                    reclaimed += _path_size_bytes(p)
                    shutil.rmtree(p, ignore_errors=False)
                    removed.append(str(p))
        except Exception:
            LOGGER.warning("清理新更新器临时目录失败", exc_info=True)

        if getattr(sys, "frozen", False):
            try:
                old_program_backup = Path(str(Path(sys.executable).parent) + ".backup")
                if old_program_backup.exists():
                    reclaimed += _path_size_bytes(old_program_backup)
                    shutil.rmtree(old_program_backup, ignore_errors=False)
                    removed.append(str(old_program_backup))
            except Exception:
                LOGGER.warning("清理旧版 C 盘程序备份失败", exc_info=True)

        try:
            tmp_root = Path(tempfile.gettempdir())
            for p in tmp_root.glob("XiaoMeiliUpdate_*"):
                if p.is_dir():
                    reclaimed += _path_size_bytes(p)
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
        except Exception:
            LOGGER.warning("清理旧版 C 盘更新解压目录失败", exc_info=True)

        # Kokoro has been fully retired since V0.6.2. Qwen3-TTS is the only active voice backend.
        legacy_kokoro = USER / "voice" / "kokoro_v1_1_zh"
'''
    s = replace_once(s, cleanup_anchor, cleanup_new, "old C update cleanup")

    # Connect the settings request to the controller so all child processes are shut down cleanly.
    open_anchor = '''        self.settings.hotkeys_changed.connect(lambda:self.hotkeys.register(self.cfg))
        self.settings.config_changed.connect(self.update_tray_checks)
'''
    open_new = '''        self.settings.hotkeys_changed.connect(lambda:self.hotkeys.register(self.cfg))
        self.settings.config_changed.connect(self.update_tray_checks)
        self.settings.storage_migration_requested.connect(self.start_storage_migration)
'''
    s = replace_once(s, open_anchor, open_new, "controller storage signal")

    quit_anchor = '    def quit(self):\n'
    migration_controller = r'''    def start_storage_migration(self, target):
        try:
            if not getattr(sys, "frozen", False):
                raise RuntimeError("开发模式不执行存储迁移，请在正式 XiaoMeili.exe 中操作。")
            helper = Path(resource("assets/storage_migrate.ps1"))
            if not helper.exists():
                raise FileNotFoundError(f"存储迁移助手缺失：{helper}")
            source = xiaomeili_logical_data_root()
            target = Path(str(target or r"D:\\XiaoMeiliData"))
            desktop_log = desktop_dir() / "小美丽_D盘迁移日志_请上传给ChatGPT.txt"
            args = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(helper),
                "-Source", str(source),
                "-Target", str(target),
                "-ParentPid", str(os.getpid()),
                "-ExePath", str(Path(sys.executable)),
                "-DesktopLog", str(desktop_log),
            ]
            proc = subprocess.Popen(
                args,
                cwd=str(Path(sys.executable).parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            time.sleep(0.7)
            rc = proc.poll()
            if rc is not None:
                raise RuntimeError(f"存储迁移助手启动失败（exit={rc}）。")
            LOGGER.info("D盘迁移助手已启动：%s -> %s", source, target)
            self.quit()
        except Exception as exc:
            LOGGER.exception("启动 D 盘迁移失败")
            QMessageBox.critical(
                None,
                "小美丽存储迁移失败",
                f"没有改动现有数据。错误：{type(exc).__name__}: {exc}\n\n"
                f"错误日志会保存在桌面：小美丽_D盘迁移日志_请上传给ChatGPT.txt",
            )
            if self.settings:
                try:
                    self.settings.storage_migrate_btn.setEnabled(True)
                    self.settings._refresh_storage_status()
                except Exception:
                    pass

'''
    if quit_anchor not in s:
        raise RuntimeError("controller quit anchor missing")
    # Use the last controller quit occurrence, not any unrelated method.
    controller_pos = s.index('class AppController(QObject):')
    quit_pos = s.index(quit_anchor, controller_pos)
    s = s[:quit_pos] + migration_controller + s[quit_pos:]

    # Update explanatory text in the update tab.
    old_update_note = (
        '"更新包会先下载到 XiaoMeiliData/updates，完成 SHA-256 校验后由内部更新助手替换程序文件并自动重启。"\n'
        '            "个人配置、当前语音模型、动作素材和日志都保存在 XiaoMeiliData，不会因程序升级被覆盖。更新成功后会自动清理旧更新包、临时文件和已淘汰的 Kokoro 组件。"'
    )
    new_update_note = (
        '"更新包会先下载到 XiaoMeiliData/updates，完成 SHA-256 校验后由内部更新助手替换程序文件并自动重启。"\n'
        '            "V0.7.6 完成 D 盘迁移后，这个逻辑路径仍保持不变，但更新包、解压临时目录和回滚备份都会实际写入 D 盘。"\n'
        '            "个人配置、语音模型、动作素材和养成数据不会因程序升级被覆盖。"'
    )
    if old_update_note in s:
        s = s.replace(old_update_note, new_update_note, 1)

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    print("Patched XiaoMeili source to V0.7.6 D-drive storage migration")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v076.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
