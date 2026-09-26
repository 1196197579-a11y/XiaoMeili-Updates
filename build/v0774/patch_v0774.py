# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.4 anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Version + widgets needed by the six-section settings shell.
    # ------------------------------------------------------------------
    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.3"',
        'APP_NAME = "小美丽 V0.7.7.4｜Six Section Settings Center"\nAPP_VERSION = "0.7.7.4"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    s = must(
        s,
        "QTableWidgetItem, QKeySequenceEdit, QHeaderView, QSpinBox, QGroupBox, QGridLayout, QLineEdit, QComboBox, QListWidget, QListWidgetItem, QProgressDialog, QDoubleSpinBox, QInputDialog, QProgressBar, QTextEdit\n)",
        "QTableWidgetItem, QKeySequenceEdit, QHeaderView, QSpinBox, QGroupBox, QGridLayout, QLineEdit, QComboBox, QListWidget, QListWidgetItem, QProgressDialog, QDoubleSpinBox, QInputDialog, QProgressBar, QTextEdit, QStackedWidget, QFrame, QScrollArea\n)",
        "Qt widget imports",
    )

    # Drag interaction becomes a real user-facing toggle.
    s, drag_n = re.subn(
        r'if self\.drag_press_global is not None and not self\.drag_visual_active:\n(\s+)threshold = max\(2, min\(6, int\(self\.cfg\.get\("drag_interaction", \{\}\)\.get\("threshold_px", 4\)\)\)\)',
        'if (self.drag_press_global is not None and not self.drag_visual_active\\n'
        '                    and bool(self.cfg.get("drag_interaction", {}).get("enabled", True))):\\n'
        r'\1threshold = max(2, min(6, int(self.cfg.get("drag_interaction", {}).get("threshold_px", 4))))',
        s,
        count=1,
    )
    if drag_n != 1:
        raise RuntimeError("drag enabled guard replacement failed")

    # V2 mouse-follow strength: preserve the validated motion model and only
    # multiply its visible displacement/rotation amplitude.
    old_motion = '''        body_dx = self.body_x * float(micfg.get("body_x_px", 3.2)) * sx
        body_dy = self.body_y * float(micfg.get("body_y_px", 1.7)) * sy
        head_dx = self.head_x * float(micfg.get("head_x_px", 8.5)) * sx
        head_dy = self.head_y * float(micfg.get("head_y_px", 5.0)) * sy
        front_dx = self.front_x * float(micfg.get("front_x_px", 6.4)) * sx
        front_dy = self.front_y * float(micfg.get("front_y_px", 3.6)) * sy
        back_dx = self.back_x * float(micfg.get("back_x_px", 2.4)) * sx
        back_dy = self.back_y * float(micfg.get("back_y_px", 1.8)) * sy

        body_rot = self.body_x * float(micfg.get("body_rot_deg", 1.5))
        head_rot = self.head_x * float(micfg.get("head_rot_deg", 4.2)) + self.head_y * 0.7
        front_rot = self.front_x * float(micfg.get("front_rot_deg", 4.6)) + self.head_vel_x * 14.0
        back_rot = self.back_x * float(micfg.get("back_rot_deg", 1.9)) - self.head_vel_x * 10.0

        pupil_reduce = max(0.35, min(1.0, float(micfg.get("pupil_reduce_when_head_turn", 0.80))))
        pupil_gain = 1.0 - (1.0 - pupil_reduce) * min(1.0, abs(self.head_x))
        eye_dx = self.look_x * float(micfg.get("eye_x_px", 3.2)) * sx * pupil_gain
        eye_dy = self.look_y * float(micfg.get("eye_y_px", 2.0)) * sy * pupil_gain
        ear_dx = (self.ear_x * 2.4 + self.head_vel_x * 9.0) * sx
        ear_dy = (self.ear_y * 1.3 + self.head_vel_y * 4.0) * sy
'''
    new_motion = '''        strength = max(0.55, min(1.55, float(micfg.get("strength", 1.0))))
        body_dx = self.body_x * float(micfg.get("body_x_px", 3.2)) * sx * strength
        body_dy = self.body_y * float(micfg.get("body_y_px", 1.7)) * sy * strength
        head_dx = self.head_x * float(micfg.get("head_x_px", 8.5)) * sx * strength
        head_dy = self.head_y * float(micfg.get("head_y_px", 5.0)) * sy * strength
        front_dx = self.front_x * float(micfg.get("front_x_px", 6.4)) * sx * strength
        front_dy = self.front_y * float(micfg.get("front_y_px", 3.6)) * sy * strength
        back_dx = self.back_x * float(micfg.get("back_x_px", 2.4)) * sx * strength
        back_dy = self.back_y * float(micfg.get("back_y_px", 1.8)) * sy * strength

        body_rot = self.body_x * float(micfg.get("body_rot_deg", 1.5)) * strength
        head_rot = (self.head_x * float(micfg.get("head_rot_deg", 4.2)) + self.head_y * 0.7) * strength
        front_rot = (self.front_x * float(micfg.get("front_rot_deg", 4.6)) + self.head_vel_x * 14.0) * strength
        back_rot = (self.back_x * float(micfg.get("back_rot_deg", 1.9)) - self.head_vel_x * 10.0) * strength

        pupil_reduce = max(0.35, min(1.0, float(micfg.get("pupil_reduce_when_head_turn", 0.80))))
        pupil_gain = 1.0 - (1.0 - pupil_reduce) * min(1.0, abs(self.head_x))
        eye_dx = self.look_x * float(micfg.get("eye_x_px", 3.2)) * sx * pupil_gain * strength
        eye_dy = self.look_y * float(micfg.get("eye_y_px", 2.0)) * sy * pupil_gain * strength
        ear_dx = (self.ear_x * 2.4 + self.head_vel_x * 9.0) * sx * strength
        ear_dy = (self.ear_y * 1.3 + self.head_vel_y * 4.0) * sy * strength
'''
    s = must(s, old_motion, new_motion, "mouse strength")

    # Install the new shell only after the old validated widgets have all been
    # created and signal-wired. Those widgets remain the functional backend.
    s = must(
        s,
        "        self._bind_dirty_tracking()\n",
        "        self._bind_dirty_tracking()\n        self._install_v0774_shell(root)\n",
        "install settings shell",
    )

    # The old Apply implementation remains the canonical persistence path for
    # validated settings. V0.7.7.4 only overrides the fields that are now
    # independently exposed in the new UI.
    apply_start = s.index("    def apply(self):\n", s.index("class SettingsDialog(QDialog):"))
    apply_end = s.index("\n\nclass AppController(QObject):", apply_start)
    apply_block = s[apply_start:apply_end]
    save_anchor = "        save_config(self.cfg)\n"
    if save_anchor not in apply_block:
        raise RuntimeError("apply save anchor missing")
    v774_apply = '''        if hasattr(self, "v774_click_cb"):
            self.cfg["click_through"] = bool(self.v774_click_cb.isChecked())
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
        if hasattr(self, "v774_ai_cb"):
            self.cfg.setdefault("brain", {})["enabled"] = bool(self.v774_ai_cb.isChecked())
        if hasattr(self, "v774_drag_cb"):
            self.cfg.setdefault("drag_interaction", {})["enabled"] = bool(self.v774_drag_cb.isChecked())
        if hasattr(self, "v774_strength_combo"):
            try:
                self.cfg.setdefault("mouse_interaction", {})["strength"] = float(self.v774_strength_combo.currentData() or 1.0)
            except Exception:
                self.cfg.setdefault("mouse_interaction", {})["strength"] = 1.0
        if hasattr(self, "_v774_pet_name"):
            self.cfg["pet_name"] = str(self._v774_pet_name or "小美丽").strip() or "小美丽"
'''
    apply_block = apply_block.replace(save_anchor, v774_apply + save_anchor, 1)
    s = s[:apply_start] + apply_block + s[apply_end:]

    # Brain on/off is a real gate, not a decorative toggle.
    brain_ask_anchor = "    def _brain_ask(self):\n"
    brain_ask_gate = '''    def _brain_ask(self):
        if not bool(self.cfg.get("brain", {}).get("enabled", True)):
            QMessageBox.information(self, "小美丽大脑", "AI 大脑目前已关闭。请先在「大脑」页面重新开启。")
            return
'''
    s = must(s, brain_ask_anchor, brain_ask_gate, "brain enabled gate")

    # The tray's "Check updates" action must navigate to System > Update in the
    # new information architecture.
    tray_start = s.index("    def check_updates_from_tray(self):\n", s.index("class AppController(QObject):"))
    tray_end = s.index("    def update_tray_checks(self):\n", tray_start)
    tray_method = '''    def check_updates_from_tray(self):
        self.open_settings()
        if self.settings:
            try:
                if hasattr(self.settings, "open_system_section"):
                    self.settings.open_system_section("更新")
                else:
                    for i in range(self.settings.tabs.count()):
                        if self.settings.tabs.tabText(i) == "更新":
                            self.settings.tabs.setCurrentIndex(i)
                            break
            except Exception:
                LOGGER.exception("切换到更新页失败")
            self.settings._check_update()

'''
    s = s[:tray_start] + tray_method + s[tray_end:]

    # Add a frozen/offscreen UI smoke test so the release pipeline validates
    # actual SettingsDialog construction, not only Python syntax.
    bottom_anchor = '\n\nif __name__=="__main__":\n'
    if bottom_anchor not in s:
        raise RuntimeError("main entry anchor missing")
    smoke_func = r'''

def settings_ui_self_test():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    cfg = load_config()
    pet = PetWindow(cfg)
    vision = VisionWorker(cfg)
    voice = VoiceService()
    brain = BrainService()
    updater = UpdateService(cfg)
    dialog = SettingsDialog(cfg, pet, vision, voice, brain, updater)
    try:
        expected = ["常规", "大脑", "声音", "互动", "动作", "系统"]
        if list(getattr(dialog, "v774_nav_names", [])) != expected:
            raise RuntimeError(f"V0.7.7.4 nav mismatch: {getattr(dialog, 'v774_nav_names', None)}")
        system_titles = [
            dialog.v774_system_tabs.tabText(i)
            for i in range(dialog.v774_system_tabs.count())
        ]
        for title in ("更新", "存储", "组件与下载", "游戏识别", "日志"):
            if title not in system_titles:
                raise RuntimeError(f"V0.7.7.4 system tab missing: {title}")
        if dialog.windowTitle() != "小美丽 设置":
            raise RuntimeError(f"unexpected settings title: {dialog.windowTitle()}")
        return True
    finally:
        try:
            dialog.close()
        except Exception:
            pass
        try:
            brain.shutdown()
        except Exception:
            pass
        try:
            voice.shutdown()
        except Exception:
            pass
'''
    s = s.replace(bottom_anchor, smoke_func + bottom_anchor, 1)

    entry_anchor = 'if __name__=="__main__":\n    if "--runtime-self-test" in sys.argv:\n'
    if entry_anchor not in s:
        raise RuntimeError("runtime self-test entry anchor missing")
    entry_new = '''if __name__=="__main__":
    if "--settings-ui-self-test" in sys.argv:
        try:
            settings_ui_self_test()
            raise SystemExit(0)
        except Exception:
            LOGGER.exception("V0.7.7.4 设置中心自检失败")
            raise SystemExit(8)
    if "--runtime-self-test" in sys.argv:
'''
    s = s.replace(entry_anchor, entry_new, 1)

    # ------------------------------------------------------------------
    # V0.7.7.4 six-section settings center.
    # ------------------------------------------------------------------
    method_anchor = "    def _toggle_brain_advanced(self, checked):\n"
    if method_anchor not in s:
        raise RuntimeError("v0773 method anchor missing")

    ui_methods = r'''    def _v774_page(self, title, subtitle):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)
        title_label = QLabel(str(title))
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(str(subtitle))
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)
        outer.addWidget(title_label)
        outer.addWidget(subtitle_label)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(12)
        outer.addWidget(body, 1)
        return page, body_layout

    def _v774_card(self, title, value="", description="", button_text="", button_slot=None, control=None):
        card = QFrame()
        card.setObjectName("settingCard")
        card.setMinimumHeight(106)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(18, 14, 16, 14)
        lay.setSpacing(14)
        text_box = QWidget()
        tv = QVBoxLayout(text_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        ttl = QLabel(str(title))
        ttl.setObjectName("cardTitle")
        val = QLabel(str(value))
        val.setObjectName("cardValue")
        val.setWordWrap(True)
        tv.addWidget(ttl)
        tv.addWidget(val)
        if description:
            desc = QLabel(str(description))
            desc.setObjectName("cardDesc")
            desc.setWordWrap(True)
            tv.addWidget(desc)
        lay.addWidget(text_box, 1)
        if control is not None:
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        elif button_text:
            btn = QPushButton(str(button_text))
            btn.setObjectName("cardButton")
            if button_slot is not None:
                btn.clicked.connect(button_slot)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return card, val

    def _v774_scroll_grid(self, cards, columns=2):
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 4, 4)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        for i, card in enumerate(cards):
            grid.addWidget(card, i // columns, i % columns)
        for c in range(columns):
            grid.setColumnStretch(c, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll

    def _v774_legacy_index(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                return i
        return -1

    def _v774_take_legacy_page(self, title):
        idx = self._v774_legacy_index(title)
        if idx < 0:
            return None
        page = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        page.setParent(None)
        return page

    def _v774_open_legacy_dialog(self, title, window_title=None, size=(940, 650)):
        idx = self._v774_legacy_index(title)
        if idx < 0:
            QMessageBox.warning(self, "小美丽", f"没有找到「{title}」设置页。")
            return
        page = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        page.setParent(None)
        dialog = QDialog(self)
        dialog.setWindowTitle(window_title or title)
        dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dialog.resize(int(size[0]), int(size[1]))
        dialog.setMinimumSize(720, 520)
        dv = QVBoxLayout(dialog)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(10)
        dv.addWidget(page, 1)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dv.addLayout(close_row)
        try:
            dialog.exec()
        finally:
            dv.removeWidget(page)
            page.setParent(None)
            self.tabs.addTab(page, title)

    def _v774_hide_form_row(self, widget):
        try:
            parent = widget.parentWidget()
            layout = parent.layout() if parent else None
            if isinstance(layout, QFormLayout):
                label = layout.labelForField(widget)
                if label is not None:
                    label.hide()
            widget.hide()
        except Exception:
            pass

    def _v774_switch_page(self, index):
        index = max(0, min(int(index), self.v774_stack.count() - 1))
        self.v774_stack.setCurrentIndex(index)
        for i, btn in enumerate(self.v774_nav_buttons):
            btn.setChecked(i == index)
        try:
            ui = self.cfg.setdefault("settings_ui", {})
            ui["last_page"] = self.v774_nav_names[index]
            save_config(self.cfg)
        except Exception:
            LOGGER.warning("保存设置页位置失败", exc_info=True)

    def _v774_schedule_apply(self, *args):
        if hasattr(self, "_v774_apply_timer"):
            self._v774_apply_timer.start(180)

    def _v774_apply_now(self):
        try:
            if hasattr(self, "v774_top_cb"):
                self.top_cb.blockSignals(True)
                self.top_cb.setChecked(bool(self.v774_top_cb.isChecked()))
                self.top_cb.blockSignals(False)
            if hasattr(self, "v774_opacity"):
                self.opacity.blockSignals(True)
                self.opacity.setValue(int(self.v774_opacity.value()))
                self.opacity.blockSignals(False)
            if hasattr(self, "v774_size"):
                self.size_spin.blockSignals(True)
                self.size_spin.setValue(int(self.v774_size.value()))
                self.size_spin.blockSignals(False)
            if hasattr(self, "v774_mouse_cb"):
                self.mouse_interaction_cb.blockSignals(True)
                self.mouse_interaction_cb.setChecked(bool(self.v774_mouse_cb.isChecked()))
                self.mouse_interaction_cb.blockSignals(False)
            if hasattr(self, "v774_transition_combo"):
                self.trans_spin.blockSignals(True)
                self.trans_spin.setValue(int(self.v774_transition_combo.currentData() or 200))
                self.trans_spin.blockSignals(False)
            self.apply()
            try:
                self.pet.apply_window_flags()
                self.pet.apply_clickthrough_native()
                self.pet.refresh_mouse_interaction_config()
            except Exception:
                LOGGER.warning("即时应用桌宠设置失败", exc_info=True)
        except Exception as exc:
            LOGGER.exception("V0.7.7.4 即时保存失败")
            QMessageBox.warning(self, "保存设置失败", f"{type(exc).__name__}: {exc}")

    def _v774_autostart_enabled(self):
        if sys.platform != "win32":
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "XiaoMeili")
                return bool(str(value or "").strip())
        except Exception:
            return False

    def _v774_set_autostart(self, checked):
        checked = bool(checked)
        if sys.platform != "win32":
            QMessageBox.information(self, "开机启动", "开机启动只在 Windows 正式版中可用。")
            return
        try:
            import winreg
            if getattr(sys, "frozen", False):
                command = f'"{Path(sys.executable)}"'
            else:
                command = f'"{sys.executable}" "{Path(__file__).resolve()}"'
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if checked:
                    winreg.SetValueEx(key, "XiaoMeili", 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, "XiaoMeili")
                    except FileNotFoundError:
                        pass
            self.cfg["start_with_windows"] = checked
            save_config(self.cfg)
        except Exception as exc:
            LOGGER.exception("修改开机启动失败")
            self.v774_startup_cb.blockSignals(True)
            self.v774_startup_cb.setChecked(not checked)
            self.v774_startup_cb.blockSignals(False)
            QMessageBox.warning(self, "开机启动设置失败", f"{type(exc).__name__}: {exc}")

    def _v774_edit_pet_name(self):
        current = str(getattr(self, "_v774_pet_name", "") or self.cfg.get("pet_name") or "小美丽")
        value, ok = QInputDialog.getText(self, "修改昵称", "你想怎么称呼小美丽？", text=current)
        if not ok:
            return
        value = str(value or "").strip()
        if not value:
            return
        self._v774_pet_name = value[:20]
        self.cfg["pet_name"] = self._v774_pet_name
        save_config(self.cfg)
        self.v774_profile_name.setText(self._v774_pet_name)
        self.v774_name_value.setText(self._v774_pet_name)

    def _v774_open_hotkeys(self):
        self._v774_open_legacy_dialog("快捷键", "快捷键", (860, 620))

    def _v774_open_actions(self):
        self._v774_open_legacy_dialog("动画素材", "动作库与视频素材", (1080, 720))
        self._v774_refresh_action_summary()

    def _v774_open_brain_chat(self):
        self._v774_open_legacy_dialog("大脑", "和小美丽聊两句", (900, 690))
        self._v774_refresh_brain_summary()

    def _v774_open_voice_editor(self):
        if not self.voice_service.ready():
            self.open_system_section("组件与下载")
            QMessageBox.information(self, "小美丽声音", "声音组件还没有准备好，已经带你来到「系统 → 组件与下载」。")
            return
        self._v774_open_legacy_dialog("声音", "小美丽声音", (900, 650))
        self._v774_refresh_voice_summary()

    def _v774_set_ai_enabled(self, checked):
        self.cfg.setdefault("brain", {})["enabled"] = bool(checked)
        save_config(self.cfg)
        self._v774_refresh_brain_summary()

    def _v774_set_expression(self, value):
        try:
            self.brain_temp.setValue(max(0.20, min(1.20, int(value) / 100.0)))
            self._brain_save_settings()
            self.v774_expression_value.setText(f"{int(value)}% · " + ("更稳定" if value < 55 else "自然" if value < 85 else "更自由"))
        except Exception:
            LOGGER.warning("保存表达自由度失败", exc_info=True)

    def _v774_edit_memory(self):
        current = int(self.brain_context.value())
        value, ok = QInputDialog.getInt(
            self,
            "记忆管理",
            "最近对话保留多少轮？\n\n长期记忆目前尚未启用；养成库和语义规则会继续长期保留。",
            current,
            2,
            12,
            1,
        )
        if ok:
            self.brain_context.setValue(int(value))
            self._brain_save_settings()
            self._v774_refresh_brain_summary()

    def _v774_clear_context(self):
        answer = QMessageBox.question(
            self,
            "清空当前对话",
            "只清空最近聊天上下文，不会删除性格卡和养成库。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._brain_clear_history()
            self._v774_refresh_brain_summary()

    def _v774_refresh_brain_summary(self):
        if not hasattr(self, "v774_ai_value"):
            return
        enabled = bool(self.cfg.get("brain", {}).get("enabled", True))
        ready = bool(self.brain_service.ready())
        if not enabled:
            state = "已关闭"
        elif ready:
            state = "已开启 · 大脑就绪"
        else:
            state = "已开启 · 尚未准备"
        self.v774_ai_value.setText(state)
        turns = int(self.brain_context.value()) if hasattr(self, "brain_context") else int(self.cfg.get("brain", {}).get("context_turns", 6))
        count = int(self.brain_service.feedback_count())
        self.v774_memory_value.setText(f"最近 {turns} 轮 · 长期记忆尚未启用")
        self.v774_learning_value.setText(f"已积累 {count} 条养成样本")
        try:
            persona = str(self.brain_persona.toPlainText() or "").strip()
            self.v774_persona_value.setText("已使用自定义性格卡" if persona and persona != str(DEFAULT_PERSONA).strip() else "默认小美丽性格")
        except Exception:
            self.v774_persona_value.setText("小美丽性格")

    def _v774_set_auto_speak(self, checked):
        self.brain_auto_speak.setChecked(bool(checked))
        self._brain_save_settings()

    def _v774_refresh_voice_summary(self):
        if not hasattr(self, "v774_voice_value"):
            return
        voice = self.cfg.get("voice", {}) if isinstance(self.cfg.get("voice"), dict) else {}
        vid = str(voice.get("voice_id") or "").strip()
        if not self.voice_service.ready():
            label = "声音组件尚未准备"
        elif not vid:
            label = "尚未选择固定声音"
        else:
            try:
                label = str(self.voice_service.display_name(vid))
            except Exception:
                label = vid
        self.v774_voice_value.setText(label)
        try:
            self.v774_output_value.setText(str(self.voice_output_combo.currentText() or "系统默认播放设备"))
        except Exception:
            self.v774_output_value.setText("系统默认播放设备")

    def _v774_set_strength_index(self, index):
        self._v774_schedule_apply()

    def _v774_refresh_action_summary(self):
        if not hasattr(self, "v774_action_value"):
            return
        total = 0
        try:
            for key in STATE_NAMES:
                total += len([p for p in _asset_list(self.cfg.get("assets", {}).get(key)) if p])
        except Exception:
            total = 0
        self.v774_action_value.setText(f"{len(STATE_NAMES)} 个状态 · {total} 个素材")
        self.v774_video_value.setText(f"当前共 {total} 个动作素材")

    def _v774_export_diagnostics(self):
        try:
            out = desktop_dir() / f"小美丽诊断包_{time.strftime('%Y%m%d_%H%M%S')}.zip"
            files = []
            if CONFIG_FILE.exists():
                files.append(CONFIG_FILE)
            logs = sorted(
                [p for p in LOG_DIR.glob("*.log") if p.is_file()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:8]
            files.extend(logs)
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "README.txt",
                    f"小美丽诊断包\n版本: V{APP_VERSION}\n生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "请把这个 ZIP 直接上传给 ChatGPT，用于定位小美丽运行问题。\n",
                )
                for p in files:
                    try:
                        zf.write(p, arcname=f"data/{p.name}")
                    except Exception:
                        LOGGER.warning("诊断包跳过文件: %s", p, exc_info=True)
            QMessageBox.information(self, "诊断包已生成", f"已保存到桌面：\n{out}")
            if sys.platform == "win32":
                try:
                    os.startfile(str(out.parent))
                except Exception:
                    pass
        except Exception as exc:
            LOGGER.exception("导出诊断包失败")
            QMessageBox.warning(self, "导出失败", f"{type(exc).__name__}: {exc}")

    def _v774_clean_old_logs(self):
        try:
            removed = 0
            for p in sorted(LOG_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[8:]:
                try:
                    p.unlink()
                    removed += 1
                except Exception:
                    pass
            QMessageBox.information(self, "日志清理", f"已清理 {removed} 个旧日志，最近 8 个日志会保留。")
        except Exception as exc:
            QMessageBox.warning(self, "日志清理失败", str(exc))

    def open_system_section(self, name="更新"):
        try:
            self._v774_switch_page(5)
            idx = self._v774_system_index.get(str(name), 0)
            self.v774_system_tabs.setCurrentIndex(idx)
        except Exception:
            LOGGER.warning("切换系统二级页失败: %s", name, exc_info=True)

    def _v774_first_run_notice(self):
        try:
            ui = self.cfg.setdefault("settings_ui", {})
            if bool(ui.get("v0774_notice_shown", False)):
                return
            QMessageBox.information(
                self,
                "设置中心焕新完成",
                "功能没有减少，只是重新整理到了：\n\n"
                "常规 · 大脑 · 声音 · 互动 · 动作 · 系统\n\n"
                "模型下载、NDM、更新、迁移、游戏识别和日志等技术设置，统一放到了「系统」。",
            )
            ui["v0774_notice_shown"] = True
            save_config(self.cfg)
        except Exception:
            pass

    def _install_v0774_shell(self, root):
        # Native Windows frame is retained for reliable DPI / multi-monitor behavior.
        self.setWindowTitle("小美丽 设置")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1080, 720)
        self.setMinimumSize(920, 620)

        self.setStyleSheet("""
            QDialog { background: #F3F8F6; color: #183A34; }
            QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 13px; }
            QFrame#sidebar { background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 22px; }
            QLabel#avatar {
                background: #3CC9A8; color: white; border-radius: 28px;
                font-size: 25px; font-weight: 800;
            }
            QLabel#profileName { color: #173B34; font-size: 18px; font-weight: 700; }
            QLabel#profileStatus { color: #2DAF8E; font-size: 12px; }
            QPushButton#navButton {
                background: transparent; color: #48635D; border: none; border-radius: 12px;
                text-align: left; padding: 11px 16px; font-size: 14px; font-weight: 600;
            }
            QPushButton#navButton:hover { background: #F1F8F5; color: #1B5B4E; }
            QPushButton#navButton:checked {
                background: #E3F7F0; color: #167B67; border: 1px solid #B9EBDD;
            }
            QLabel#pageTitle { color: #173B34; font-size: 25px; font-weight: 800; }
            QLabel#pageSubtitle { color: #74867F; font-size: 13px; }
            QFrame#settingCard {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 16px;
            }
            QLabel#cardTitle { color: #526B64; font-size: 13px; font-weight: 600; }
            QLabel#cardValue { color: #173B34; font-size: 16px; font-weight: 700; }
            QLabel#cardDesc { color: #85958F; font-size: 11px; }
            QPushButton {
                min-height: 30px; border: 1px solid #D5E5DF; border-radius: 9px;
                padding: 4px 13px; background: #FFFFFF; color: #28584D;
            }
            QPushButton:hover { background: #EFF9F5; border-color: #9EDCCB; }
            QPushButton:pressed { background: #DFF4EC; }
            QPushButton:disabled { background: #F3F6F5; color: #A4B0AC; border-color: #E5EBE9; }
            QPushButton#cardButton {
                min-width: 92px; background: #E4F7F1; border: 1px solid #C7EEE2;
                color: #168069; font-weight: 700;
            }
            QLineEdit, QTextEdit, QListWidget, QComboBox, QSpinBox, QDoubleSpinBox,
            QTableWidget {
                background: #FFFFFF; color: #24473F; border: 1px solid #D8E5E0;
                border-radius: 9px; padding: 5px 7px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox { min-height: 28px; }
            QCheckBox { color: #385A52; spacing: 7px; }
            QSlider::groove:horizontal {
                height: 5px; background: #DFEAE6; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 16px; margin: -6px 0; border-radius: 8px;
                background: #36C4A2; border: 1px solid #29AE8F;
            }
            QSlider::sub-page:horizontal { background: #36C4A2; border-radius: 2px; }
            QProgressBar {
                min-height: 16px; border: 1px solid #D8E5E0; border-radius: 7px;
                text-align: center; background: #EDF3F1; color: #31564D;
            }
            QProgressBar::chunk { background: #36C4A2; border-radius: 6px; }
            QGroupBox {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 13px;
                margin-top: 10px; padding-top: 10px; font-weight: 700; color: #294D44;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QTabWidget::pane {
                background: #FFFFFF; border: 1px solid #DCE9E4; border-radius: 13px;
            }
            QTabBar::tab {
                background: transparent; border: none; padding: 9px 13px;
                color: #647C75; margin: 0 2px;
            }
            QTabBar::tab:selected {
                color: #167B67; font-weight: 700; border-bottom: 2px solid #36C4A2;
            }
            QScrollArea { background: transparent; border: none; }
        """)

        # Old top tabs are now a hidden functional backend and second-level editor pool.
        self.tabs.hide()

        # Hide the old bottom-level Save/Close strip. V0.7.7.4 saves ordinary
        # controls immediately; second-level editors retain explicit save actions where needed.
        try:
            self.save_btn.hide()
            self.apply_status.hide()
            for btn in self.findChildren(QPushButton):
                if btn.text() == "关闭" and btn.window() is self:
                    btn.hide()
        except Exception:
            pass

        # Technical rows must no longer leak into the user-facing Brain/Voice pages.
        try:
            self.brain_advanced_toggle.hide()
            self.brain_advanced_body.hide()
        except Exception:
            pass

        # Build shell.
        shell = QWidget()
        shell_l = QHBoxLayout(shell)
        shell_l.setContentsMargins(12, 12, 12, 12)
        shell_l.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 20, 18, 18)
        side.setSpacing(8)

        profile = QWidget()
        ph = QHBoxLayout(profile)
        ph.setContentsMargins(0, 0, 0, 12)
        ph.setSpacing(12)
        avatar = QLabel("美")
        avatar.setObjectName("avatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(56, 56)
        ph.addWidget(avatar)
        ptext = QVBoxLayout()
        self._v774_pet_name = str(self.cfg.get("pet_name") or "小美丽").strip() or "小美丽"
        self.v774_profile_name = QLabel(self._v774_pet_name)
        self.v774_profile_name.setObjectName("profileName")
        status = QLabel("● 在线")
        status.setObjectName("profileStatus")
        ptext.addStretch(1)
        ptext.addWidget(self.v774_profile_name)
        ptext.addWidget(status)
        ptext.addStretch(1)
        ph.addLayout(ptext, 1)
        side.addWidget(profile)

        nav_caption = QLabel("我的设置")
        nav_caption.setStyleSheet("color:#879690;font-weight:600;padding:8px 4px 4px 4px;")
        side.addWidget(nav_caption)

        self.v774_nav_names = ["常规", "大脑", "声音", "互动", "动作", "系统"]
        self.v774_nav_buttons = []
        for i, name in enumerate(self.v774_nav_names):
            b = QPushButton(name)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, idx=i: self._v774_switch_page(idx))
            side.addWidget(b)
            self.v774_nav_buttons.append(b)

        side.addStretch(1)
        version = QLabel(f"小美丽 V{APP_VERSION}")
        version.setStyleSheet("color:#9AA8A3;font-size:11px;padding:4px;")
        side.addWidget(version)

        self.v774_stack = QStackedWidget()
        shell_l.addWidget(sidebar)
        shell_l.addWidget(self.v774_stack, 1)

        # --------------------------------------------------------------
        # 1. General
        # --------------------------------------------------------------
        general, gv = self._v774_page("常规", "管理小美丽最常用的桌面设置。")
        cards = []

        name_card, self.v774_name_value = self._v774_card(
            "昵称", self._v774_pet_name, "只影响设置中心里的称呼。", "修改", self._v774_edit_pet_name
        )
        cards.append(name_card)

        self.v774_startup_cb = QCheckBox("开机启动")
        self.v774_startup_cb.setChecked(self._v774_autostart_enabled())
        self.v774_startup_cb.toggled.connect(self._v774_set_autostart)
        card, _ = self._v774_card("开机启动", "登录 Windows 后自动启动小美丽", control=self.v774_startup_cb)
        cards.append(card)

        self.v774_top_cb = QCheckBox("开启")
        self.v774_top_cb.setChecked(bool(self.cfg.get("always_on_top", True)))
        self.v774_top_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("始终置顶", "保持在其他窗口上方", control=self.v774_top_cb)
        cards.append(card)

        self.v774_click_cb = QCheckBox("开启")
        self.v774_click_cb.setChecked(bool(self.cfg.get("click_through", False)))
        self.v774_click_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("点击穿透", "鼠标点击会穿过桌宠", control=self.v774_click_cb)
        cards.append(card)

        self.v774_lockpos_cb = QCheckBox("锁定")
        self.v774_lockpos_cb.setChecked(bool(self.cfg.get("lock_position", False)))
        self.v774_lockpos_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("锁定位置", "禁止拖动桌宠位置", control=self.v774_lockpos_cb)
        cards.append(card)

        self.v774_opacity = QSlider(Qt.Orientation.Horizontal)
        self.v774_opacity.setRange(30, 100)
        self.v774_opacity.setFixedWidth(150)
        self.v774_opacity.setValue(int(self.cfg.get("opacity", 100)))
        self.v774_opacity.valueChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("透明度", f"当前 {int(self.cfg.get('opacity',100))}%", "拖动后自动保存", control=self.v774_opacity)
        cards.append(card)

        self.v774_size = QSpinBox()
        self.v774_size.setRange(120, 600)
        self.v774_size.setSuffix(" px")
        self.v774_size.setValue(int(self.cfg.get("pet_width", 280)))
        self.v774_size.valueChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("桌宠大小", "调整小美丽在桌面上的尺寸", control=self.v774_size)
        cards.append(card)

        card, _ = self._v774_card("快捷键", "打开设置、显示隐藏、测试状态等", "全局快捷键可以全部留空", "管理", self._v774_open_hotkeys)
        cards.append(card)

        card, _ = self._v774_card("桌宠位置", "当前位置可随时重置", "", "移到屏幕左上", lambda: self.pet.move(100, 100))
        cards.append(card)

        gv.addWidget(self._v774_scroll_grid(cards, 2), 1)
        self.v774_stack.addWidget(general)

        # --------------------------------------------------------------
        # 2. Brain
        # --------------------------------------------------------------
        brain, bv = self._v774_page("大脑", "决定小美丽怎么思考、怎么记住、怎么和你说话。")
        brain_cards = []

        self.v774_ai_cb = QCheckBox("启用 AI")
        self.v774_ai_cb.setChecked(bool(self.cfg.get("brain", {}).get("enabled", True)))
        self.v774_ai_cb.toggled.connect(self._v774_set_ai_enabled)
        card, self.v774_ai_value = self._v774_card("AI 大脑", "", "模型与组件问题统一到「系统」处理。", control=self.v774_ai_cb)
        brain_cards.append(card)

        card, self.v774_persona_value = self._v774_card(
            "小美丽性格", "", "人设、性格和说话方式。", "编辑性格", self._open_brain_persona_editor
        )
        brain_cards.append(card)

        card, self.v774_memory_value = self._v774_card(
            "记忆", "", "长期记忆尚未启用；当前先管理最近对话。", "管理", self._v774_edit_memory
        )
        brain_cards.append(card)

        card, self.v774_learning_value = self._v774_card(
            "学习与养成", "", "固定台词、语义规则和主人纠正。", "管理养成库", self._open_brain_rules_editor
        )
        brain_cards.append(card)

        expression_host = QWidget()
        eh = QHBoxLayout(expression_host)
        eh.setContentsMargins(0, 0, 0, 0)
        eh.setSpacing(8)
        self.v774_expression_slider = QSlider(Qt.Orientation.Horizontal)
        self.v774_expression_slider.setRange(20, 120)
        self.v774_expression_slider.setValue(int(round(float(self.cfg.get("brain", {}).get("temperature", 0.78)) * 100)))
        self.v774_expression_slider.setFixedWidth(125)
        self.v774_expression_slider.valueChanged.connect(self._v774_set_expression)
        self.v774_expression_value = QLabel("")
        self.v774_expression_value.setStyleSheet("color:#637A73;font-size:11px;")
        eh.addWidget(self.v774_expression_slider)
        eh.addWidget(self.v774_expression_value)
        card, _ = self._v774_card("表达自由度", "控制回答更稳定还是更自由", control=expression_host)
        brain_cards.append(card)

        card, _ = self._v774_card(
            "对话测试", "和小美丽聊两句", "支持 👍 / 👎 纠正与养成。", "打开", self._v774_open_brain_chat
        )
        brain_cards.append(card)

        bv.addWidget(self._v774_scroll_grid(brain_cards, 2), 1)
        self.v774_stack.addWidget(brain)

        # Hide duplicate Brain cards from the old second-level chat page.
        try:
            legacy_brain = self.tabs.widget(self._v774_legacy_index("大脑"))
            for gb in legacy_brain.findChildren(QGroupBox):
                if gb.title() in ("养成库 / 语义规则", "小美丽性格"):
                    gb.hide()
        except Exception:
            pass

        # --------------------------------------------------------------
        # 3. Voice
        # --------------------------------------------------------------
        voice_page, vv = self._v774_page("声音", "管理小美丽怎么听你说话，以及怎么开口。")
        voice_cards = []

        card, _ = self._v774_card("唤醒词", "尚未启用", "「美丽美丽」将在后续语音阶段接入。")
        voice_cards.append(card)
        card, _ = self._v774_card("语音识别", "尚未启用", "麦克风与 ASR 仍未正式接入当前稳定版。")
        voice_cards.append(card)

        card, self.v774_voice_value = self._v774_card(
            "小美丽声音", "", "选择固定中文声线、语速并试听。", "选择与试听", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        self.v774_auto_speak_cb = QCheckBox("开启")
        self.v774_auto_speak_cb.setChecked(bool(self.cfg.get("brain", {}).get("auto_speak", True)))
        self.v774_auto_speak_cb.toggled.connect(self._v774_set_auto_speak)
        card, _ = self._v774_card("回答后自动说出来", "文字回答完成后自动朗读", control=self.v774_auto_speak_cb)
        voice_cards.append(card)

        card, self.v774_output_value = self._v774_card(
            "声音输出", "", "选择 Windows 播放设备。", "设置", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        card, _ = self._v774_card("输入设备", "随语音识别启用", "当前版本尚未接入麦克风输入。")
        voice_cards.append(card)

        vv.addWidget(self._v774_scroll_grid(voice_cards, 2), 1)
        self.v774_stack.addWidget(voice_page)

        # --------------------------------------------------------------
        # 4. Interaction
        # --------------------------------------------------------------
        interact, iv = self._v774_page("互动", "决定小美丽在桌面上怎么回应你。")
        int_cards = []

        self.v774_mouse_cb = QCheckBox("开启")
        self.v774_mouse_cb.setChecked(bool(self.cfg.get("mouse_interaction", {}).get("enabled", True)))
        self.v774_mouse_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("鼠标跟随", "Continuous Puppet V2", "眼睛、头部、身体、头发和耳环连续跟随。", control=self.v774_mouse_cb)
        int_cards.append(card)

        self.v774_strength_combo = QComboBox()
        self.v774_strength_combo.addItem("轻柔", 0.80)
        self.v774_strength_combo.addItem("自然", 1.00)
        self.v774_strength_combo.addItem("明显", 1.25)
        current_strength = float(self.cfg.get("mouse_interaction", {}).get("strength", 1.0) or 1.0)
        best = min(range(self.v774_strength_combo.count()), key=lambda i: abs(float(self.v774_strength_combo.itemData(i)) - current_strength))
        self.v774_strength_combo.setCurrentIndex(best)
        self.v774_strength_combo.currentIndexChanged.connect(self._v774_set_strength_index)
        card, _ = self._v774_card("跟随强度", "调节鼠标互动的可见幅度", control=self.v774_strength_combo)
        int_cards.append(card)

        self.v774_drag_cb = QCheckBox("开启")
        self.v774_drag_cb.setChecked(bool(self.cfg.get("drag_interaction", {}).get("enabled", True)))
        self.v774_drag_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("拖拽互动", "悬挂姿态 + 惯性回弹", "动态眼球、身体、马尾和耳环继续沿用 V0.7.7.2 稳定逻辑。", control=self.v774_drag_cb)
        int_cards.append(card)

        card, _ = self._v774_card("主动互动", "尚未启用", "未来用于游戏事件主动吐槽、闲置主动动作等。")
        int_cards.append(card)

        card, _ = self._v774_card("点击反馈", "由鼠标互动 / 拖拽逻辑接管", "当前没有独立的单击动作触发器。")
        int_cards.append(card)

        self.v774_transition_combo = QComboBox()
        self.v774_transition_combo.addItem("快速", 120)
        self.v774_transition_combo.addItem("自然", 200)
        self.v774_transition_combo.addItem("柔和", 320)
        cur_ms = int(self.cfg.get("transition_ms", 200))
        best = min(range(self.v774_transition_combo.count()), key=lambda i: abs(int(self.v774_transition_combo.itemData(i)) - cur_ms))
        self.v774_transition_combo.setCurrentIndex(best)
        self.v774_transition_combo.currentIndexChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("动画过渡", "动作切换速度", control=self.v774_transition_combo)
        int_cards.append(card)

        iv.addWidget(self._v774_scroll_grid(int_cards, 2), 1)
        self.v774_stack.addWidget(interact)

        # --------------------------------------------------------------
        # 5. Actions
        # --------------------------------------------------------------
        action_page, av = self._v774_page("动作", "管理小美丽的动作、素材和触发方式。")
        action_cards = []
        card, self.v774_action_value = self._v774_card(
            "动作库", "", "待机、低血量、击杀、死亡、胜负和战报素材池。", "打开动作库", self._v774_open_actions
        )
        action_cards.append(card)
        card, _ = self._v774_card(
            "状态动作", f"{len(STATE_NAMES)} 个状态", "每个状态可保存多支素材并随机播放。", "管理", self._v774_open_actions
        )
        action_cards.append(card)
        card, _ = self._v774_card(
            "事件触发", "由 VALORANT 识别自动触发", "识别到低血量、击杀、死亡、胜负等事件后播放对应动作。", "查看识别", lambda: self.open_system_section("游戏识别")
        )
        action_cards.append(card)
        card, self.v774_video_value = self._v774_card(
            "视频素材", "", "批量导入、自动抠绿、白边/柔光、预览和删除。", "管理素材", self._v774_open_actions
        )
        action_cards.append(card)
        av.addWidget(self._v774_scroll_grid(action_cards, 2), 1)
        self.v774_stack.addWidget(action_page)

        # --------------------------------------------------------------
        # 6. System
        # --------------------------------------------------------------
        system_page, syv = self._v774_page("系统", "更新、存储、组件和诊断工具。技术设置统一放在这里。")
        self.v774_system_tabs = QTabWidget()
        self._v774_system_index = {}

        update_page = self._v774_take_legacy_page("更新")
        storage_page = self._v774_take_legacy_page("存储")
        vision_page = self._v774_take_legacy_page("游戏识别")
        log_page = self._v774_take_legacy_page("日志")

        if update_page is not None:
            self._v774_system_index["更新"] = self.v774_system_tabs.addTab(update_page, "更新")
        if storage_page is not None:
            self._v774_system_index["存储"] = self.v774_system_tabs.addTab(storage_page, "存储")

        components = QWidget()
        cv = QVBoxLayout(components)
        cv.setContentsMargins(12, 12, 12, 12)
        cv.setSpacing(12)

        brain_group = QGroupBox("大脑组件")
        bg = QFormLayout(brain_group)
        bg.setContentsMargins(14, 14, 14, 12)
        bg.setSpacing(8)
        bg.addRow("状态", self.brain_status)
        bg.addRow("准备进度", self.brain_progress)
        bg.addRow(self.brain_prepare_btn)
        mode_row = QWidget(); ml = QHBoxLayout(mode_row); ml.setContentsMargins(0,0,0,0); ml.setSpacing(8)
        ml.addWidget(self.brain_download_mode, 1); ml.addWidget(self.brain_ndm_test_btn)
        bg.addRow("下载方式", mode_row)
        dir_row = QWidget(); dl = QHBoxLayout(dir_row); dl.setContentsMargins(0,0,0,0); dl.setSpacing(8)
        dl.addWidget(self.brain_ndm_dir, 1); dl.addWidget(self.brain_ndm_browse_btn)
        bg.addRow("NDM 下载目录", dir_row)
        cv.addWidget(brain_group)

        # Voice technical widgets are removed from the user-facing voice editor
        # and rehomed here.
        self._v774_hide_form_row(self.voice_status)
        self._v774_hide_form_row(self.voice_progress)
        self._v774_hide_form_row(self.voice_prepare_btn)
        self.voice_status.show(); self.voice_progress.show(); self.voice_prepare_btn.show()

        voice_group = QGroupBox("声音组件")
        vg = QFormLayout(voice_group)
        vg.setContentsMargins(14, 14, 14, 12)
        vg.setSpacing(8)
        vg.addRow("状态", self.voice_status)
        vg.addRow("准备进度", self.voice_progress)
        vg.addRow(self.voice_prepare_btn)
        cv.addWidget(voice_group)

        tech_note = QLabel(
            "只有这里显示模型、下载方式、NDM 和组件准备状态。日常使用只需要去「大脑」和「声音」页面。"
        )
        tech_note.setWordWrap(True)
        tech_note.setStyleSheet("color:#73877F;background:#F2F8F5;border:1px solid #DCEAE4;border-radius:9px;padding:8px;")
        cv.addWidget(tech_note)
        cv.addStretch(1)

        self._v774_system_index["组件与下载"] = self.v774_system_tabs.addTab(components, "组件与下载")

        if vision_page is not None:
            self._v774_system_index["游戏识别"] = self.v774_system_tabs.addTab(vision_page, "游戏识别")

        if log_page is not None:
            try:
                log_layout = log_page.layout()
                diag = QGroupBox("诊断工具")
                dg = QVBoxLayout(diag)
                dtext = QLabel("遇到报错时可以一键导出最近日志和配置摘要，再把 ZIP 直接上传给 ChatGPT。")
                dtext.setWordWrap(True)
                dg.addWidget(dtext)
                dr = QHBoxLayout()
                export_btn = QPushButton("导出给 ChatGPT")
                export_btn.clicked.connect(self._v774_export_diagnostics)
                clean_btn = QPushButton("清理旧日志")
                clean_btn.clicked.connect(self._v774_clean_old_logs)
                dr.addWidget(export_btn); dr.addWidget(clean_btn); dr.addStretch(1)
                dg.addLayout(dr)
                log_layout.insertWidget(1, diag)
            except Exception:
                LOGGER.warning("增强日志页失败", exc_info=True)
            self._v774_system_index["日志"] = self.v774_system_tabs.addTab(log_page, "日志")

        syv.addWidget(self.v774_system_tabs, 1)
        self.v774_stack.addWidget(system_page)

        # Put the new shell before the now-hidden legacy tab widget.
        root.insertWidget(0, shell, 1)

        # Automatic saving for controls that used to depend on the global Save button.
        self._v774_apply_timer = QTimer(self)
        self._v774_apply_timer.setSingleShot(True)
        self._v774_apply_timer.timeout.connect(self._v774_apply_now)

        for editor in self.hk_editors.values():
            editor.keySequenceChanged.connect(self._v774_schedule_apply)
        for widget, signal_name in [
            (self.vision_enabled, "toggled"),
            (self.nickname_edit, "textChanged"),
            (self.hp_threshold, "valueChanged"),
            (self.mode_combo, "currentIndexChanged"),
            (self.pause_bg, "toggled"),
            (self.nickname_ocr_cb, "toggled"),
            (self.voice_test_text, "textChanged"),
            (self.voice_speed, "valueChanged"),
            (self.voice_output_combo, "currentIndexChanged"),
        ]:
            try:
                getattr(widget, signal_name).connect(self._v774_schedule_apply)
            except Exception:
                pass

        # Brain download settings are saved immediately even though they live in System.
        try:
            self.brain_download_mode.currentIndexChanged.connect(lambda *a: self._brain_save_settings())
            self.brain_ndm_dir.textChanged.connect(lambda *a: self._brain_save_settings())
        except Exception:
            pass

        # Keep summaries live.
        try:
            self.voice_fix_btn.clicked.connect(lambda *a: QTimer.singleShot(0, self._v774_refresh_voice_summary))
            self.brain_service.setup_finished.connect(lambda *a: self._v774_refresh_brain_summary())
            self.voice_service.download_finished.connect(lambda *a: self._v774_refresh_voice_summary())
        except Exception:
            pass

        # Initial summaries.
        self._v774_refresh_brain_summary()
        self._v774_refresh_voice_summary()
        self._v774_refresh_action_summary()
        self._v774_set_expression(self.v774_expression_slider.value())

        # Restore last top-level page.
        wanted = str(self.cfg.get("settings_ui", {}).get("last_page", "常规") or "常规")
        try:
            initial = self.v774_nav_names.index(wanted)
        except ValueError:
            initial = 0
        self._v774_switch_page(initial)

        QTimer.singleShot(350, self._v774_first_run_notice)

'''
    s = s.replace(method_anchor, ui_methods + method_anchor, 1)

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.4"',
        'self.v774_nav_names = ["常规", "大脑", "声音", "互动", "动作", "系统"]',
        'def open_system_section(self, name="更新"):',
        '小美丽诊断包_',
        '长期记忆尚未启用',
        '语音识别", "尚未启用"',
        'drag_interaction", {}).get("enabled", True)',
        'micfg.get("strength", 1.0)',
        'self.v774_system_tabs.addTab(components, "组件与下载")',
        'self.setWindowTitle("小美丽 设置")',
        'def settings_ui_self_test():',
        '"--settings-ui-self-test" in sys.argv',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.4 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.4 six-section settings center")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0774.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
