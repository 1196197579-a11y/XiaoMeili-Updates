from pathlib import Path
import hashlib, re, sys

MAIN_IN = "51a21fc5cd045e05b78f86ae544f3dc6f5a19c5aa89d9c91cf800de07c86d087"
MAIN_OUT = "695d13ed44e44e684dac6a2cafabb8a9869c15900a48d9152c057f4aa53e1838"
NATIVE_IN = "2cfc48fdbc1cef2f89368469afebf264ea1f493f49a4069c4e8e924364b0129c"
NATIVE_OUT = "d5c678f2a12208c6602c5d9de4b1ec6d6d2796e8a0e4196e1a9ea04001549b93"

if len(sys.argv) != 3:
    raise SystemExit("usage: apply_v011032_delta.py MAIN_PY NATIVE_UPDATER_PY")

main_path = Path(sys.argv[1]).resolve()
native_path = Path(sys.argv[2]).resolve()
main_raw = main_path.read_bytes()
native_raw = native_path.read_bytes()
main = main_raw.decode("utf-8").replace("\r\n", "\n")
native = native_raw.decode("utf-8").replace("\r\n", "\n")
print("V011032_BASELINE", hashlib.sha256(main.encode("utf-8")).hexdigest(), hashlib.sha256(native.encode("utf-8")).hexdigest())

def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)

main = once(main,
    'APP_NAME = "小美丽 V0.11.0.3.1｜桌面动作模板热修复"',
    'APP_NAME = "小美丽 V0.11.0.3.2｜更新链路与下载方式修复"',
    "app name")
main = once(main, 'APP_VERSION = "0.11.0.3.1"', 'APP_VERSION = "0.11.0.3.2"', "app version")
main = once(main, 'APP_UPDATE_VERSION = "0.11.0.3.1"', 'APP_UPDATE_VERSION = "0.11.0.3.2"', "update version")
main = once(main, '"download_mode": "ndm",', '"download_mode": "builtin",', "new config default")

main = once(main,
'''        self.brain_download_mode.addItem("NDM 加速下载（推荐）", "ndm")
        self.brain_download_mode.addItem("小美丽内置下载器", "builtin")
        wanted_mode = str(cfg.get("brain",{}).get("download_mode","ndm") or "ndm")''',
'''        self.brain_download_mode.addItem("小美丽内置下载器（推荐）", "builtin")
        self.brain_download_mode.addItem("NDM 加速下载（可选）", "ndm")
        wanted_mode = str(cfg.get("brain",{}).get("download_mode","builtin") or "builtin")''',
"download choices")

main = main.replace('str(self.brain_download_mode.currentData() or "ndm")',
                    'str(self.brain_download_mode.currentData() or "builtin")')

main = once(main,
'''        dl_l.addWidget(self.brain_download_mode, 1); dl_l.addWidget(self.brain_ndm_test_btn)
        adv.addRow("下载方式", dl_row)

        dir_row = QWidget(); dir_l = QHBoxLayout(dir_row); dir_l.setContentsMargins(0,0,0,0); dir_l.setSpacing(7)
        self.brain_ndm_dir = QLineEdit(str(cfg.get("brain",{}).get("ndm_download_dir") or (Path.home() / "Downloads")))
        self.brain_ndm_dir.setPlaceholderText("请选择 NDM 的 Download Directory")
        self.brain_ndm_browse_btn = QPushButton("选择目录")
        self.brain_ndm_browse_btn.clicked.connect(self._brain_choose_ndm_dir)
        dir_l.addWidget(self.brain_ndm_dir, 1); dir_l.addWidget(self.brain_ndm_browse_btn)
        adv.addRow("NDM 下载目录", dir_row)
        ndm_note = QLabel(
            "NDM 模式会把小美丽需要的组件直接发送给本机 Neat Download Manager。"
            "下载完成后会自动监控目录并导入 XiaoMeiliData；若 NDM 没有开启或连接失败，可切换到内置下载器。"
        )
        ndm_note.setWordWrap(True); ndm_note.setStyleSheet("color:#657185;")
        adv.addRow(ndm_note)
''',
'''        dl_l.addWidget(self.brain_download_mode, 1); dl_l.addWidget(self.brain_ndm_test_btn)

        dir_row = QWidget(); dir_l = QHBoxLayout(dir_row); dir_l.setContentsMargins(0,0,0,0); dir_l.setSpacing(7)
        self.brain_ndm_dir = QLineEdit(str(cfg.get("brain",{}).get("ndm_download_dir") or (Path.home() / "Downloads")))
        self.brain_ndm_dir.setPlaceholderText("请选择 NDM 的 Download Directory")
        self.brain_ndm_browse_btn = QPushButton("选择目录")
        self.brain_ndm_browse_btn.clicked.connect(self._brain_choose_ndm_dir)
        dir_l.addWidget(self.brain_ndm_dir, 1); dir_l.addWidget(self.brain_ndm_browse_btn)
''',
"remove brain-page download rows")

main = once(main,
'''        source_l.addWidget(self.update_url, 1); source_l.addWidget(save_source)
        uf.addRow("更新源", source_row)

        self.update_status = QLabel("尚未检查更新")
''',
'''        source_l.addWidget(self.update_url, 1); source_l.addWidget(save_source)
        uf.addRow("更新源", source_row)

        update_dl_row = QWidget(); update_dl_l = QHBoxLayout(update_dl_row); update_dl_l.setContentsMargins(0,0,0,0); update_dl_l.setSpacing(8)
        update_dl_l.addWidget(self.brain_download_mode, 1); update_dl_l.addWidget(self.brain_ndm_test_btn)
        uf.addRow("下载方式", update_dl_row)
        update_ndm_dir_row = QWidget(); update_ndm_dir_l = QHBoxLayout(update_ndm_dir_row); update_ndm_dir_l.setContentsMargins(0,0,0,0); update_ndm_dir_l.setSpacing(8)
        update_ndm_dir_l.addWidget(self.brain_ndm_dir, 1); update_ndm_dir_l.addWidget(self.brain_ndm_browse_btn)
        uf.addRow("NDM 下载目录", update_ndm_dir_row)
        update_dl_note = QLabel("内置下载器可直接用于更新；选择 NDM 时会先检测本机 NDM，连接失败则本次自动回退内置下载器。")
        update_dl_note.setWordWrap(True); update_dl_note.setStyleSheet("color:#657185;")
        uf.addRow(update_dl_note)

        self.update_status = QLabel("尚未检查更新")
''',
"update page download controls")

main = once(main,
'''        mode_row = QWidget(); ml = QHBoxLayout(mode_row); ml.setContentsMargins(0,0,0,0); ml.setSpacing(8)
        ml.addWidget(self.brain_download_mode, 1); ml.addWidget(self.brain_ndm_test_btn)
        bg.addRow("下载方式", mode_row)
        dir_row = QWidget(); dl = QHBoxLayout(dir_row); dl.setContentsMargins(0,0,0,0); dl.setSpacing(8)
        dl.addWidget(self.brain_ndm_dir, 1); dl.addWidget(self.brain_ndm_browse_btn)
        bg.addRow("NDM 下载目录", dir_row)
''',
'',
"remove component-page download rows")

main = once(main,
'''    def _brain_test_ndm(self):
        ok, msg = self.brain_service.test_ndm()
        self.brain_status.setText(msg)
        if not ok:
            QMessageBox.warning(self, "NDM 未连接", "没有连接到 Neat Download Manager。\\n\\n请先打开 NDM，再点击“测试 NDM”。")
''',
'''    def _brain_test_ndm(self):
        ok, msg = self.brain_service.test_ndm()
        self.brain_status.setText(msg)
        if hasattr(self, "update_status"):
            self.update_status.setText(msg if ok else "NDM 当前不可用；可直接选择“小美丽内置下载器（推荐）”。")
        if not ok:
            QMessageBox.warning(self, "NDM 未连接", "没有连接到 Neat Download Manager。\\n\\n可以直接在「系统 → 更新」把下载方式切换为“小美丽内置下载器（推荐）”，不影响正常更新。")
''',
"NDM test feedback")

main = once(main,
    'mode = str(brain_cfg.get("download_mode", "ndm") or "ndm").strip().lower()',
    'mode = str(brain_cfg.get("download_mode", "builtin") or "builtin").strip().lower()',
    "update mode default")

main = once(main,
'''                if not download_ok:
                    for attempt in range(1, 4):
''',
'''                if not download_ok:
                    if mode == "builtin":
                        self.progress_changed.emit(0, "已选择小美丽内置下载器，正在开始下载…")
                    for attempt in range(1, 4):
''',
"built-in progress")

main = once(main,
'''                    current_exe=current_exe,
                    log_path=native_log,
                )''',
'''                    current_exe=current_exe,
                    log_path=native_log,
                    allow_external_current=True,
                )''',
"external current updater call")

main = once(main,
'更新包会先下载到 XiaoMeiliData/updates，完成完整性与 SHA-256 校验后再替换程序。个人配置、模型、动作素材和养成数据不会被覆盖。',
'更新包会先进入 XiaoMeiliData/updates，完成 ZIP 与 SHA-256 校验后安装到全新的受保护版本目录。即使当前从桌面测试副本启动，也不会修改该副本；个人配置、模型、动作素材和养成数据不会被覆盖。',
"update safety note")

main = once(main, 'self.brain_advanced_toggle = QPushButton("模型与下载配置  ▸")',
                 'self.brain_advanced_toggle = QPushButton("模型配置  ▸")', "brain toggle")
main = once(main,
'只有这里显示模型、下载方式、NDM 和组件准备状态。日常使用只需要去「大脑」和「声音」页面。',
'这里显示本地模型与组件准备状态；更新包下载方式与 NDM 设置已迁移到「更新」页。日常使用只需要去「大脑」和「声音」页面。',
"component hint")

native = once(native,
'def _validate_root(install_root, current_exe=None):',
'def _validate_root(install_root, current_exe=None, allow_external_current=False):',
"validate signature")

native = once(native,
'''    if current_exe:
        cur = Path(current_exe).resolve()
        try:
            cur.relative_to(versions.resolve())
        except Exception as exc:
            raise NativeUpdateError("当前程序不在受保护的 versions 目录中。") from exc

    return actual_resolved, versions, launcher
''',
'''    current_is_managed = True
    if current_exe:
        cur = Path(current_exe).resolve()
        try:
            cur.relative_to(versions.resolve())
        except Exception as exc:
            current_is_managed = False
            if not allow_external_current:
                raise NativeUpdateError("当前程序不在受保护的 versions 目录中。") from exc

    return actual_resolved, versions, launcher, current_is_managed
''',
"external-current validation")

native = once(native,
'''    current_exe=None,
    log_path=None,
):''',
'''    current_exe=None,
    log_path=None,
    allow_external_current=False,
):''',
"install signature")

native = once(native,
'''    root, versions, launcher = _validate_root(install_root, current_exe=current_exe)
    _log(log_path, f"NATIVE updater start package={package} root={root} version={expected_version}")
''',
'''    root, versions, launcher, current_is_managed = _validate_root(
        install_root,
        current_exe=current_exe,
        allow_external_current=bool(allow_external_current),
    )
    _log(log_path, f"NATIVE updater start package={package} root={root} version={expected_version} current_managed={current_is_managed}")
    if not current_is_managed:
        _log(log_path, "External current EXE accepted after protected install-root validation; only a fresh version directory and active.json will be written.")
''',
"install validation call")

native = once(native,
'''        "sha256": actual_sha,
    }
''',
'''        "sha256": actual_sha,
        "current_was_managed": bool(current_is_managed),
    }
''',
"result metadata")

main_out = main.encode("utf-8")
native_out = native.encode("utf-8")
print("V011032_OUTPUT", hashlib.sha256(main_out).hexdigest(), hashlib.sha256(native_out).hexdigest())
main_path.write_bytes(main_out)
native_path.write_bytes(native_out)
print("V011032_DELTA_OK")
