# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.2"',
        'APP_NAME = "小美丽 V0.7.7.3｜Settings UI Refresh"\nAPP_VERSION = "0.7.7.3"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # Voice and Brain tab names should remain stable across later version bumps.
    s, voice_n = re.subn(
        r'self\.tabs\.addTab\(sp,\s*(?:f)?"声音(?:\s+V[^"]*)?"\)',
        'self.tabs.addTab(sp, "声音")',
        s,
        count=1,
    )
    if voice_n != 1:
        raise RuntimeError("voice tab label replacement failed")

    resize_match = re.search(r'        self\.resize\(\d+,\s*\d+\)\n        root = QVBoxLayout\(self\)\n', s)
    if not resize_match:
        raise RuntimeError("settings resize anchor missing")
    shell = '''        self.resize(780, 720)
        self.setMinimumSize(720, 620)
        self.setStyleSheet("""
            QDialog { background: #F7F9FC; }
            QTabWidget::pane { border: 1px solid #DDE3EC; border-radius: 8px; background: #FFFFFF; }
            QTabBar::tab { background: transparent; border: none; padding: 8px 12px; margin: 0 1px; color: #3C4657; }
            QTabBar::tab:selected { color: #1769E0; border-bottom: 2px solid #2D7CF6; font-weight: 600; }
            QGroupBox { border: 1px solid #DDE3EC; border-radius: 9px; margin-top: 9px; padding-top: 9px; background: #FFFFFF; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { min-height: 28px; border: 1px solid #D4DAE4; border-radius: 7px; padding: 3px 12px; background: #FFFFFF; color: #283243; }
            QPushButton:hover { border-color: #8FB8F7; background: #F3F8FF; }
            QPushButton:pressed { background: #E8F1FF; }
            QPushButton:disabled { color: #9AA4B2; background: #F3F5F8; }
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox { border: 1px solid #D8DEE8; border-radius: 7px; background: #FFFFFF; padding: 4px 7px; }
            QProgressBar { border: 1px solid #D8DEE8; border-radius: 6px; text-align: center; background: #F1F4F8; min-height: 14px; }
            QProgressBar::chunk { border-radius: 5px; background: #2E7AF0; }
            QCheckBox { spacing: 7px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
'''
    s = s[:resize_match.start()] + shell + s[resize_match.end():]

    brain_start = s.find('        # Brain V0.7:')
    if brain_start < 0:
        brain_start = s.find('        # Brain V0.7')
    brain_end = s.find('        # Updates V0.6.1', brain_start)
    if brain_start < 0 or brain_end < 0:
        raise RuntimeError("brain page boundaries not found")

    brain_ui = r'''        # Brain V0.7.7.3: compact main page + second-level editors.
        bp = QWidget(); bv = QVBoxLayout(bp)
        bv.setContentsMargins(10, 10, 10, 10); bv.setSpacing(9)

        self.brain_advanced_toggle = QPushButton("模型与下载配置  ▸")
        self.brain_advanced_toggle.setCheckable(True)
        self.brain_advanced_toggle.setChecked(False)
        self.brain_advanced_toggle.setStyleSheet("text-align:left; font-weight:600; padding-left:12px;")
        self.brain_advanced_toggle.toggled.connect(self._toggle_brain_advanced)
        bv.addWidget(self.brain_advanced_toggle)

        self.brain_advanced_body = QGroupBox("")
        adv = QFormLayout(self.brain_advanced_body)
        adv.setContentsMargins(12, 8, 12, 10); adv.setSpacing(7)
        self.brain_status = QLabel(self.brain_service.component_status())
        self.brain_status.setWordWrap(True)
        adv.addRow("组件状态", self.brain_status)
        self.brain_progress = QProgressBar(); self.brain_progress.setRange(0,100)
        self.brain_progress.setValue(100 if self.brain_service.ready() else 0)
        adv.addRow("首次准备", self.brain_progress)
        self.brain_prepare_btn = QPushButton("准备小美丽大脑（Qwen3-8B Q4_K_M，模型约 5.03 GB）")
        self.brain_prepare_btn.setEnabled(not self.brain_service.ready())
        self.brain_prepare_btn.clicked.connect(self._prepare_brain)
        adv.addRow(self.brain_prepare_btn)

        dl_row = QWidget(); dl_l = QHBoxLayout(dl_row); dl_l.setContentsMargins(0,0,0,0); dl_l.setSpacing(7)
        self.brain_download_mode = QComboBox()
        self.brain_download_mode.addItem("NDM 加速下载（推荐）", "ndm")
        self.brain_download_mode.addItem("小美丽内置下载器", "builtin")
        wanted_mode = str(cfg.get("brain",{}).get("download_mode","ndm") or "ndm")
        idx = self.brain_download_mode.findData(wanted_mode)
        if idx >= 0: self.brain_download_mode.setCurrentIndex(idx)
        self.brain_ndm_test_btn = QPushButton("测试 NDM")
        self.brain_ndm_test_btn.clicked.connect(self._brain_test_ndm)
        dl_l.addWidget(self.brain_download_mode, 1); dl_l.addWidget(self.brain_ndm_test_btn)
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
        self.brain_advanced_body.setVisible(False)
        bv.addWidget(self.brain_advanced_body)

        chat_box = QGroupBox("对话")
        chat_v = QVBoxLayout(chat_box); chat_v.setContentsMargins(10, 12, 10, 10); chat_v.setSpacing(8)
        self.brain_chat = QListWidget(); self.brain_chat.setWordWrap(True); self.brain_chat.setMinimumHeight(235)
        chat_v.addWidget(self.brain_chat, 1)

        ask_row = QWidget(); ask_l = QHBoxLayout(ask_row); ask_l.setContentsMargins(0,0,0,0); ask_l.setSpacing(8)
        ask_l.addWidget(QLabel("和美丽说话"))
        self.brain_input = QLineEdit(); self.brain_input.setPlaceholderText("例如：美丽，你觉得我今天枪法怎么样？")
        self.brain_input.returnPressed.connect(self._brain_ask)
        self.brain_send_btn = QPushButton("发送")
        self.brain_send_btn.setEnabled(self.brain_service.ready())
        self.brain_send_btn.clicked.connect(self._brain_ask)
        ask_l.addWidget(self.brain_input, 1); ask_l.addWidget(self.brain_send_btn)
        chat_v.addWidget(ask_row)

        chat_controls = QHBoxLayout()
        self.brain_auto_speak = QCheckBox("回答后自动说出来")
        self.brain_auto_speak.setChecked(bool(cfg.get("brain",{}).get("auto_speak", True)))
        clear_chat = QPushButton("清空上下文"); clear_chat.clicked.connect(self._brain_clear_history)
        chat_controls.addWidget(self.brain_auto_speak); chat_controls.addStretch(1); chat_controls.addWidget(clear_chat)
        chat_v.addLayout(chat_controls)
        bv.addWidget(chat_box, 1)

        train_box = QGroupBox("养成工具")
        train_l = QHBoxLayout(train_box); train_l.setContentsMargins(10, 12, 10, 10); train_l.setSpacing(8)
        train_l.addWidget(QLabel("随机度"))
        self.brain_temp = QDoubleSpinBox(); self.brain_temp.setRange(0.20,1.20); self.brain_temp.setSingleStep(0.05); self.brain_temp.setDecimals(2)
        self.brain_temp.setValue(float(cfg.get("brain",{}).get("temperature",0.78)))
        train_l.addWidget(self.brain_temp)
        train_l.addSpacing(6); train_l.addWidget(QLabel("记住最近"))
        self.brain_context = QSpinBox(); self.brain_context.setRange(2,12); self.brain_context.setValue(int(cfg.get("brain",{}).get("context_turns",6)))
        train_l.addWidget(self.brain_context); train_l.addWidget(QLabel("轮"))
        train_l.addStretch(1)
        self.brain_feedback_label = QLabel(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        train_l.addWidget(self.brain_feedback_label)
        self.brain_like_btn = QPushButton("👍 这句像小美丽")
        self.brain_dislike_btn = QPushButton("👎 纠正 / 养成")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_like_btn.clicked.connect(self._brain_like); self.brain_dislike_btn.clicked.connect(self._brain_dislike)
        train_l.addWidget(self.brain_like_btn); train_l.addWidget(self.brain_dislike_btn)
        bv.addWidget(train_box)

        self.brain_rules_dialog = QDialog(self)
        self.brain_rules_dialog.setWindowTitle("养成库 / 语义规则编辑")
        self.brain_rules_dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        rules_dv = QVBoxLayout(self.brain_rules_dialog); rules_dv.setContentsMargins(12,12,12,12); rules_dv.setSpacing(8)
        rules_hint = QLabel("管理固定台词、语义规则和启用状态。这里的修改会直接作用于小美丽后续回答。")
        rules_hint.setWordWrap(True); rules_hint.setStyleSheet("color:#657185;")
        rules_dv.addWidget(rules_hint)
        self.brain_rules_list = QListWidget(); self.brain_rules_list.setMinimumHeight(330)
        rules_dv.addWidget(self.brain_rules_list, 1)
        rules_btns = QHBoxLayout()
        self.brain_rules_refresh_btn = QPushButton("刷新")
        self.brain_rules_edit_btn = QPushButton("编辑")
        self.brain_rules_toggle_btn = QPushButton("启用 / 暂停")
        self.brain_rules_delete_btn = QPushButton("删除")
        self.brain_rules_refresh_btn.clicked.connect(self._refresh_brain_rules)
        self.brain_rules_edit_btn.clicked.connect(self._brain_edit_rule)
        self.brain_rules_toggle_btn.clicked.connect(self._brain_toggle_rule)
        self.brain_rules_delete_btn.clicked.connect(self._brain_delete_rule)
        rules_btns.addWidget(self.brain_rules_refresh_btn); rules_btns.addWidget(self.brain_rules_edit_btn)
        rules_btns.addWidget(self.brain_rules_toggle_btn); rules_btns.addWidget(self.brain_rules_delete_btn)
        rules_btns.addStretch(1)
        rules_close = QPushButton("关闭"); rules_close.clicked.connect(self.brain_rules_dialog.accept)
        rules_btns.addWidget(rules_close); rules_dv.addLayout(rules_btns)

        self.brain_persona_dialog = QDialog(self)
        self.brain_persona_dialog.setWindowTitle("小美丽性格编辑")
        self.brain_persona_dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        persona_v = QVBoxLayout(self.brain_persona_dialog); persona_v.setContentsMargins(12,12,12,12); persona_v.setSpacing(8)
        persona_hint = QLabel("这里决定小美丽的人设、性格和说话方式。JSON 输出协议由程序内部锁定，不需要写进性格卡。")
        persona_hint.setWordWrap(True); persona_hint.setStyleSheet("color:#657185;")
        persona_v.addWidget(persona_hint)
        self.brain_persona = QTextEdit(); self.brain_persona.setMinimumHeight(300)
        self.brain_persona.setPlainText(str(cfg.get("brain",{}).get("persona") or DEFAULT_PERSONA))
        persona_v.addWidget(self.brain_persona, 1)
        persona_btns = QHBoxLayout()
        reset_persona = QPushButton("恢复默认人格"); reset_persona.clicked.connect(self._brain_reset_persona)
        persona_btns.addWidget(reset_persona); persona_btns.addStretch(1)
        persona_cancel = QPushButton("取消"); persona_cancel.clicked.connect(self.brain_persona_dialog.reject)
        persona_save = QPushButton("保存并应用"); persona_save.clicked.connect(self._save_persona_dialog)
        persona_btns.addWidget(persona_cancel); persona_btns.addWidget(persona_save); persona_v.addLayout(persona_btns)

        cards = QHBoxLayout(); cards.setSpacing(9)
        rules_card = QGroupBox("养成库 / 语义规则")
        rcv = QVBoxLayout(rules_card); rcv.setContentsMargins(10,12,10,10)
        rdesc = QLabel("管理固定台词、语义规则、触发逻辑与启用状态")
        rdesc.setWordWrap(True); rdesc.setStyleSheet("color:#657185;")
        open_rules = QPushButton("打开编辑"); open_rules.clicked.connect(self._open_brain_rules_editor)
        rcv.addWidget(rdesc); rcv.addWidget(open_rules)
        persona_card = QGroupBox("小美丽性格")
        pcv = QVBoxLayout(persona_card); pcv.setContentsMargins(10,12,10,10)
        pdesc = QLabel("编辑小美丽的人设、性格和说话风格")
        pdesc.setWordWrap(True); pdesc.setStyleSheet("color:#657185;")
        open_persona = QPushButton("打开性格编辑"); open_persona.clicked.connect(self._open_brain_persona_editor)
        pcv.addWidget(pdesc); pcv.addWidget(open_persona)
        cards.addWidget(rules_card, 1); cards.addWidget(persona_card, 1)
        bv.addLayout(cards)

        bnote = QLabel("提示：日常聊天只需要停留在这一页；模型下载、NDM 等低频设置已经收进上方的「模型与下载配置」。")
        bnote.setWordWrap(True); bnote.setStyleSheet("color:#55749E; background:#EEF6FF; border:1px solid #D5E8FF; border-radius:7px; padding:6px 8px;")
        bv.addWidget(bnote)
        self.tabs.addTab(bp, "大脑")

        self.brain_service.setup_progress.connect(self._brain_setup_progress)
        self.brain_service.setup_finished.connect(self._brain_setup_finished)
        self.brain_service.status_changed.connect(self.brain_status.setText)
        self.brain_service.generation_started.connect(self._brain_generation_started)
        self.brain_service.generation_finished.connect(self._brain_generation_finished)
        self.brain_service.rule_proposed.connect(self._brain_rule_proposed)
        self._pending_semantic_lesson = None
        self._refresh_brain_rules()

'''
    s = s[:brain_start] + brain_ui + s[brain_end:]

    update_start = s.find('        # Updates V0.6.1')
    storage_marker = s.find('        # Storage V0.7.6', update_start)
    if storage_marker < 0:
        storage_marker = s.find('        # Vision', update_start)
    if update_start < 0 or storage_marker < 0:
        raise RuntimeError("update page boundaries not found")

    update_ui = r'''        # Updates V0.7.7.3: fixed-height release notes prevent window overflow.
        up = QWidget(); uv = QVBoxLayout(up)
        uv.setContentsMargins(10, 10, 10, 10); uv.setSpacing(9)

        ubox = QGroupBox("检查更新"); uf = QFormLayout(ubox)
        uf.setContentsMargins(12, 12, 12, 10); uf.setSpacing(7)
        self.update_version_label = QLabel(f"V{APP_VERSION}")
        uf.addRow("当前版本", self.update_version_label)

        source_row = QWidget(); source_l = QHBoxLayout(source_row); source_l.setContentsMargins(0,0,0,0); source_l.setSpacing(7)
        self.update_url = QLineEdit(self.update_service.manifest_url())
        self.update_url.setPlaceholderText("永久更新清单地址（latest.json）")
        save_source = QPushButton("保存更新源"); save_source.clicked.connect(self._save_update_source)
        source_l.addWidget(self.update_url, 1); source_l.addWidget(save_source)
        uf.addRow("更新源", source_row)

        self.update_status = QLabel("尚未检查更新")
        self.update_status.setWordWrap(True)
        self.update_status.setMaximumHeight(48)
        uf.addRow("状态", self.update_status)
        self.update_progress = QProgressBar(); self.update_progress.setRange(0,100); self.update_progress.setValue(0)
        uf.addRow("更新进度", self.update_progress)

        update_buttons = QWidget(); update_l = QHBoxLayout(update_buttons); update_l.setContentsMargins(0,0,0,0); update_l.setSpacing(8)
        self.update_check_btn = QPushButton("检查更新")
        self.update_install_btn = QPushButton("立即更新"); self.update_install_btn.setEnabled(False)
        self.update_check_btn.clicked.connect(self._check_update); self.update_install_btn.clicked.connect(self._install_update)
        update_l.addWidget(self.update_check_btn); update_l.addWidget(self.update_install_btn)
        uf.addRow(update_buttons)
        uv.addWidget(ubox)

        notes_box = QGroupBox("更新内容")
        notes_v = QVBoxLayout(notes_box); notes_v.setContentsMargins(10,12,10,10)
        self.update_notes = QTextEdit(); self.update_notes.setReadOnly(True)
        self.update_notes.setMinimumHeight(205); self.update_notes.setMaximumHeight(270)
        self.update_notes.setPlainText("点击「检查更新」后，本次版本说明会显示在这里。\n内容再多也只在这个区域内滚动，不会把设置窗口撑出屏幕。")
        notes_v.addWidget(self.update_notes)
        uv.addWidget(notes_box, 1)

        unote = QLabel("更新包会先下载到 XiaoMeiliData/updates，完成完整性与 SHA-256 校验后再替换程序。个人配置、模型、动作素材和养成数据不会被覆盖。")
        unote.setWordWrap(True); unote.setStyleSheet("color:#657185;")
        uv.addWidget(unote)
        self.tabs.addTab(up, "更新")
        self.update_service.status_changed.connect(self.update_status.setText)
        self.update_service.check_finished.connect(self._update_check_finished)
        self.update_service.progress_changed.connect(self._update_progress_changed)

'''
    s = s[:update_start] + update_ui + s[storage_marker:]

    method_anchor = '    def _prepare_brain(self):\n'
    if method_anchor not in s:
        raise RuntimeError("brain method anchor missing")
    ui_methods = r'''    def _toggle_brain_advanced(self, checked):
        checked = bool(checked)
        if hasattr(self, "brain_advanced_body"):
            self.brain_advanced_body.setVisible(checked)
        if hasattr(self, "brain_advanced_toggle"):
            self.brain_advanced_toggle.setText("模型与下载配置  ▾" if checked else "模型与下载配置  ▸")

    def _open_brain_persona_editor(self):
        self.brain_persona_dialog.resize(680, 470)
        self.brain_persona_dialog.exec()

    def _save_persona_dialog(self):
        self._brain_save_persona()
        self.brain_persona_dialog.accept()

    def _open_brain_rules_editor(self):
        self._refresh_brain_rules()
        self.brain_rules_dialog.resize(760, 520)
        self.brain_rules_dialog.exec()

'''
    s = s.replace(method_anchor, ui_methods + method_anchor, 1)

    check_start = s.find('    def _update_check_finished(self, has_update, manifest, message):\n')
    check_end = s.find('    def _update_progress_changed(self, value, message):\n', check_start)
    if check_start < 0 or check_end < 0:
        raise RuntimeError("update completion method boundaries not found")
    new_check = r'''    def _update_check_finished(self, has_update, manifest, message):
        self.update_check_btn.setEnabled(True)
        self.update_install_btn.setEnabled(bool(has_update and manifest))

        if isinstance(manifest, dict):
            version = str(manifest.get("version") or "").strip()
            notes = manifest.get("notes", "")
            if isinstance(notes, list):
                body = "\n".join("• " + str(x) for x in notes)
            else:
                body = str(notes or "").strip()
            if has_update:
                self.update_status.setText(f"发现新版本 V{version}，可以立即更新。")
                title = f"V{version} 更新说明"
            else:
                self.update_status.setText(f"当前已是最新版本 V{APP_VERSION}。")
                title = f"V{version or APP_VERSION}（当前版本）"
            self.update_notes.setPlainText(title + ("\n\n" + body if body else "\n\n暂无额外版本说明。"))
        else:
            msg = str(message or "检查更新失败")
            self.update_status.setText(msg.splitlines()[0][:160])
            self.update_notes.setPlainText(msg)

        if not has_update:
            self.update_progress.setValue(0)

'''
    s = s[:check_start] + new_check + s[check_end:]

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.3"',
        'self.tabs.addTab(sp, "声音")',
        'self.tabs.addTab(bp, "大脑")',
        '模型与下载配置  ▸',
        '养成库 / 语义规则编辑',
        '小美丽性格编辑',
        'self.update_notes = QTextEdit()',
        '发现新版本 V{version}，可以立即更新。',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.3 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.3 compact settings UI")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0773.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
