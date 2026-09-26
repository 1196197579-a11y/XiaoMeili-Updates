# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.5 anchor: {label}")
    return text.replace(old, new, 1)


def write_theme_assets(source_root: Path):
    out = source_root / "app" / "assets" / "v0775"
    out.mkdir(parents=True, exist_ok=True)

    def svg(path_d: str, stroke: str):
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">
  <path d="{path_d}" fill="none" stroke="{stroke}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''

    assets = {
        "chevron_down_light.svg": svg("M3.5 5.2 L7 8.7 L10.5 5.2", "#51756B"),
        "chevron_up_light.svg": svg("M3.5 8.8 L7 5.3 L10.5 8.8", "#51756B"),
        "chevron_down_dark.svg": svg("M3.5 5.2 L7 8.7 L10.5 5.2", "#B7D4CB"),
        "chevron_up_dark.svg": svg("M3.5 8.8 L7 5.3 L10.5 8.8", "#B7D4CB"),
    }
    for name, data in assets.items():
        (out / name).write_text(data, encoding="utf-8")


def patch(source_root: Path):
    write_theme_assets(source_root)
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.4"',
        'APP_NAME = "小美丽 V0.7.7.5｜UI Polish + Night Mode"\nAPP_VERSION = "0.7.7.5"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ------------------------------------------------------------------
    # Fix the blank second-level windows.
    # Root cause: the legacy page was removed from a hidden QTabWidget while it
    # still carried a hidden state. Reparenting alone does not guarantee that
    # Qt makes that page visible again. Explicitly activate, reparent and show
    # it, then restore it to the same hidden backend tab index on close.
    # ------------------------------------------------------------------
    start = s.index("    def _v774_open_legacy_dialog(self, title, window_title=None, size=(940, 650)):\n")
    end = s.index("    def _v774_hide_form_row(self, widget):\n", start)

    dialog_methods = r'''    def _v0775_build_legacy_dialog(self, title, window_title=None, size=(940, 650)):
        idx = self._v774_legacy_index(title)
        if idx < 0:
            return None, None, -1

        self.tabs.setCurrentIndex(idx)
        page = self.tabs.widget(idx)
        if page is None:
            return None, None, -1

        # Removing a page from a hidden QTabWidget can leave WA_WState_Hidden
        # set. Clear that state explicitly after the new parent is assigned.
        self.tabs.removeTab(idx)

        dialog = QDialog(self)
        dialog.setWindowTitle(window_title or title)
        dialog.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dialog.resize(int(size[0]), int(size[1]))
        dialog.setMinimumSize(720, 520)

        dv = QVBoxLayout(dialog)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(10)

        page.setParent(dialog)
        dv.addWidget(page, 1)
        page.setVisible(True)
        page.show()
        page.raise_()

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryCloseButton")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dv.addLayout(close_row)

        try:
            self._v0775_apply_native_titlebar(dialog, self._v0775_theme_mode == "dark")
        except Exception:
            pass

        dialog._v0775_page = page
        dialog._v0775_tab_title = str(title)
        dialog._v0775_original_index = int(idx)
        return dialog, page, idx

    def _v0775_restore_legacy_dialog(self, dialog, page, idx, title):
        if page is None:
            return
        try:
            page.hide()
            layout = dialog.layout() if dialog is not None else None
            if layout is not None:
                layout.removeWidget(page)
            page.setParent(None)
            insert_at = max(0, min(int(idx), self.tabs.count()))
            self.tabs.insertTab(insert_at, page, str(title))
        except Exception:
            LOGGER.exception("恢复二级设置页失败: %s", title)

    def _v774_open_legacy_dialog(self, title, window_title=None, size=(940, 650)):
        dialog, page, idx = self._v0775_build_legacy_dialog(title, window_title, size)
        if dialog is None or page is None:
            QMessageBox.warning(self, "小美丽", f"没有找到「{title}」设置页。")
            return
        try:
            # A queued show is important on Windows after a widget has just left
            # a hidden QTabWidget.
            QTimer.singleShot(0, page.show)
            dialog.exec()
        finally:
            self._v0775_restore_legacy_dialog(dialog, page, idx, title)

'''
    s = s[:start] + dialog_methods + s[end:]

    # Install the V0.7.7.5 theme layer after the six-section shell exists.
    s = must(
        s,
        "        QTimer.singleShot(350, self._v774_first_run_notice)\n",
        "        self._install_v0775_theme_layer()\n"
        "        QTimer.singleShot(350, self._v774_first_run_notice)\n",
        "theme layer install",
    )

    # ------------------------------------------------------------------
    # Theme + polished native controls.
    # ------------------------------------------------------------------
    anchor = "    def _toggle_brain_advanced(self, checked):\n"
    if anchor not in s:
        raise RuntimeError("settings method insertion anchor missing")

    theme_methods = r'''    def _v0775_apply_native_titlebar(self, window, dark):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            value = ctypes.c_int(1 if dark else 0)
            hwnd = int(window.winId())
            # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on modern Windows; 19 on older builds.
            for attr in (20, 19):
                try:
                    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                    )
                    if int(result) == 0:
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def _v0775_theme_urls(self, dark):
        suffix = "dark" if dark else "light"
        up = str(Path(resource(f"assets/v0775/chevron_up_{suffix}.svg"))).replace("\\", "/")
        down = str(Path(resource(f"assets/v0775/chevron_down_{suffix}.svg"))).replace("\\", "/")
        return up, down

    def _v0775_stylesheet(self, dark):
        up, down = self._v0775_theme_urls(dark)
        if dark:
            bg = "#101815"
            sidebar = "#15211D"
            card = "#182620"
            card_hover = "#1D3028"
            border = "#2A4038"
            border_soft = "#253A33"
            text = "#EAF4F0"
            text2 = "#B3C5BF"
            muted = "#80948D"
            accent = "#53D7B5"
            accent_text = "#8BEACF"
            accent_bg = "#173C32"
            accent_border = "#286858"
            input_bg = "#111C18"
            input_hover = "#172722"
            button_bg = "#17231F"
            button_hover = "#20342D"
            disabled_bg = "#18201E"
            disabled_text = "#63726D"
            progress_bg = "#1A2924"
            title_sub = "#94A7A0"
        else:
            bg = "#F3F8F6"
            sidebar = "#FFFFFF"
            card = "#FFFFFF"
            card_hover = "#F9FCFB"
            border = "#DCE9E4"
            border_soft = "#D6E4DF"
            text = "#173B34"
            text2 = "#526B64"
            muted = "#85958F"
            accent = "#36C4A2"
            accent_text = "#167B67"
            accent_bg = "#E3F7F0"
            accent_border = "#B9EBDD"
            input_bg = "#FFFFFF"
            input_hover = "#F7FBF9"
            button_bg = "#FFFFFF"
            button_hover = "#EFF9F5"
            disabled_bg = "#F3F6F5"
            disabled_text = "#A4B0AC"
            progress_bg = "#EDF3F1"
            title_sub = "#74867F"

        return f"""
            QDialog {{ background: {bg}; color: {text}; }}
            QWidget {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 13px; color: {text}; }}

            QFrame#sidebar {{
                background: {sidebar}; border: 1px solid {border}; border-radius: 22px;
            }}
            QLabel#avatar {{
                background: {accent}; color: #FFFFFF; border-radius: 28px;
                font-size: 25px; font-weight: 800;
            }}
            QLabel#profileName {{ color: {text}; font-size: 18px; font-weight: 700; }}
            QLabel#profileStatus {{ color: {accent}; font-size: 12px; }}

            QPushButton#navButton {{
                background: transparent; color: {text2}; border: none; border-radius: 12px;
                text-align: left; padding: 11px 16px; font-size: 14px; font-weight: 600;
            }}
            QPushButton#navButton:hover {{ background: {card_hover}; color: {accent_text}; }}
            QPushButton#navButton:checked {{
                background: {accent_bg}; color: {accent_text};
                border: 1px solid {accent_border};
            }}

            QLabel#pageTitle {{ color: {text}; font-size: 25px; font-weight: 800; }}
            QLabel#pageSubtitle {{ color: {title_sub}; font-size: 13px; }}
            QFrame#settingCard {{
                background: {card}; border: 1px solid {border}; border-radius: 16px;
            }}
            QFrame#settingCard:hover {{ background: {card_hover}; }}
            QLabel#cardTitle {{ color: {text2}; font-size: 13px; font-weight: 600; }}
            QLabel#cardValue {{ color: {text}; font-size: 16px; font-weight: 700; }}
            QLabel#cardDesc {{ color: {muted}; font-size: 11px; }}

            QPushButton {{
                min-height: 30px; border: 1px solid {border_soft}; border-radius: 9px;
                padding: 4px 13px; background: {button_bg}; color: {text2};
            }}
            QPushButton:hover {{ background: {button_hover}; border-color: {accent_border}; color: {accent_text}; }}
            QPushButton:pressed {{ background: {accent_bg}; }}
            QPushButton:disabled {{
                background: {disabled_bg}; color: {disabled_text}; border-color: {border_soft};
            }}
            QPushButton#cardButton {{
                min-width: 92px; background: {accent_bg}; border: 1px solid {accent_border};
                color: {accent_text}; font-weight: 700;
            }}
            QPushButton#secondaryCloseButton {{
                min-width: 74px; background: {accent_bg}; border: 1px solid {accent_border};
                color: {accent_text}; font-weight: 700;
            }}
            QPushButton#themeButton {{
                min-width: 0px; min-height: 0px; padding: 0px;
                background: {card}; border: 1px solid {border}; border-radius: 17px;
                color: {accent_text}; font-size: 17px; font-weight: 700;
            }}
            QPushButton#themeButton:hover {{
                background: {accent_bg}; border-color: {accent_border};
            }}
            QPushButton#helpButton {{
                min-width: 0px; min-height: 0px; padding: 0px;
                background: {accent_bg}; border: 1px solid {accent_border};
                border-radius: 10px; color: {accent_text};
                font-size: 12px; font-weight: 800;
            }}
            QLabel#helpLabel {{
                background: {accent_bg}; border: 1px solid {accent_border};
                border-radius: 10px; color: {accent_text};
                font-size: 12px; font-weight: 800;
            }}

            QLineEdit, QTextEdit, QListWidget, QTableWidget {{
                background: {input_bg}; color: {text}; border: 1px solid {border_soft};
                border-radius: 9px; padding: 5px 7px; selection-background-color: {accent_bg};
                selection-color: {text};
            }}
            QLineEdit:focus, QTextEdit:focus, QListWidget:focus, QTableWidget:focus {{
                border: 1px solid {accent_border};
            }}

            QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {input_bg}; color: {text}; border: 1px solid {border_soft};
                border-radius: 9px; min-height: 30px; padding: 2px 36px 2px 9px;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                background: {input_hover}; border-color: {accent_border};
            }}

            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 30px; border: none; border-left: 1px solid {border_soft};
                border-top-right-radius: 8px; border-bottom-right-radius: 8px;
                background: transparent;
            }}
            QComboBox::drop-down:hover {{ background: {accent_bg}; }}
            QComboBox::down-arrow {{
                image: url("{down}"); width: 14px; height: 14px;
            }}

            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border; subcontrol-position: top right;
                width: 28px; height: 15px; border: none; border-left: 1px solid {border_soft};
                border-top-right-radius: 8px; background: transparent;
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border; subcontrol-position: bottom right;
                width: 28px; height: 15px; border: none; border-left: 1px solid {border_soft};
                border-bottom-right-radius: 8px; background: transparent;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: {accent_bg};
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: url("{up}"); width: 12px; height: 12px;
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: url("{down}"); width: 12px; height: 12px;
            }}

            QCheckBox {{ color: {text2}; spacing: 7px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 5px;
                border: 1px solid {border_soft}; background: {input_bg};
            }}
            QCheckBox::indicator:hover {{ border-color: {accent}; }}
            QCheckBox::indicator:checked {{
                background: {accent}; border: 1px solid {accent};
            }}

            QSlider::groove:horizontal {{
                height: 5px; background: {border}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 16px; margin: -6px 0; border-radius: 8px;
                background: {accent}; border: 1px solid {accent};
            }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}

            QProgressBar {{
                min-height: 16px; border: 1px solid {border_soft}; border-radius: 7px;
                text-align: center; background: {progress_bg}; color: {text2};
            }}
            QProgressBar::chunk {{ background: {accent}; border-radius: 6px; }}

            QGroupBox {{
                background: {card}; border: 1px solid {border}; border-radius: 13px;
                margin-top: 10px; padding-top: 10px; font-weight: 700; color: {text2};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}

            QTabWidget::pane {{
                background: {card}; border: 1px solid {border}; border-radius: 13px;
            }}
            QTabBar::tab {{
                background: transparent; border: none; padding: 9px 13px;
                color: {muted}; margin: 0 2px;
            }}
            QTabBar::tab:hover {{ color: {accent_text}; }}
            QTabBar::tab:selected {{
                color: {accent_text}; font-weight: 700; border-bottom: 2px solid {accent};
            }}

            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                width: 9px; background: transparent; margin: 3px 1px 3px 1px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_soft}; min-height: 28px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {accent_border}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    def _v0775_mark_help_widgets(self):
        # Replace legacy '?' affordances with a small, consistent information pill.
        for widget in self.findChildren(QWidget):
            try:
                getter = getattr(widget, "text", None)
                setter = getattr(widget, "setText", None)
                if not callable(getter) or not callable(setter):
                    continue
                raw = str(getter() or "").strip()
                if raw not in {"?", "？"}:
                    continue
                setter("i")
                if isinstance(widget, QLabel):
                    widget.setObjectName("helpLabel")
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    widget.setObjectName("helpButton")
                widget.setFixedSize(21, 21)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            except Exception:
                continue

    def _v0775_place_theme_button(self):
        if not hasattr(self, "v0775_theme_btn"):
            return
        margin = 18
        x = max(0, self.width() - self.v0775_theme_btn.width() - margin)
        y = 16
        self.v0775_theme_btn.move(x, y)
        self.v0775_theme_btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._v0775_place_theme_button()
        except Exception:
            pass

    def _v0775_apply_theme(self, mode, persist=True):
        mode = "dark" if str(mode).lower() == "dark" else "light"
        self._v0775_theme_mode = mode
        dark = mode == "dark"
        self.setStyleSheet(self._v0775_stylesheet(dark))

        if hasattr(self, "v0775_theme_btn"):
            self.v0775_theme_btn.setText("☀" if dark else "☾")
            self.v0775_theme_btn.setToolTip("切换到白天模式" if dark else "切换到夜间模式")

        self._v0775_mark_help_widgets()
        self._v0775_apply_native_titlebar(self, dark)
        for dlg_name in ("brain_persona_dialog", "brain_rules_dialog"):
            dlg = getattr(self, dlg_name, None)
            if dlg is not None:
                try:
                    self._v0775_apply_native_titlebar(dlg, dark)
                except Exception:
                    pass

        if persist:
            ui = self.cfg.setdefault("settings_ui", {})
            ui["theme"] = mode
            save_config(self.cfg)

    def _v0775_toggle_theme(self):
        self._v0775_apply_theme("light" if self._v0775_theme_mode == "dark" else "dark", True)

    def _install_v0775_theme_layer(self):
        ui = self.cfg.setdefault("settings_ui", {})
        self._v0775_theme_mode = "dark" if str(ui.get("theme", "light")).lower() == "dark" else "light"

        self.v0775_theme_btn = QPushButton(self)
        self.v0775_theme_btn.setObjectName("themeButton")
        self.v0775_theme_btn.setFixedSize(34, 34)
        self.v0775_theme_btn.clicked.connect(self._v0775_toggle_theme)
        self.v0775_theme_btn.show()
        self._v0775_apply_theme(self._v0775_theme_mode, False)
        self._v0775_place_theme_button()

'''
    s = s.replace(anchor, theme_methods + anchor, 1)

    # ------------------------------------------------------------------
    # Strengthen the frozen UI self-test: verify that the previously blank
    # second-level pages can actually be mounted into a visible QDialog.
    # ------------------------------------------------------------------
    smoke_anchor = '''        if dialog.windowTitle() != "小美丽 设置":
            raise RuntimeError(f"unexpected settings title: {dialog.windowTitle()}")
        return True
'''
    smoke_new = '''        if dialog.windowTitle() != "小美丽 设置":
            raise RuntimeError(f"unexpected settings title: {dialog.windowTitle()}")

        for legacy_title in ("快捷键", "大脑", "动画素材"):
            child, page, original_idx = dialog._v0775_build_legacy_dialog(
                legacy_title, f"UI smoke: {legacy_title}", (820, 580)
            )
            if child is None or page is None:
                raise RuntimeError(f"legacy page missing: {legacy_title}")
            try:
                child.show()
                page.show()
                app.processEvents()
                if not page.isVisible():
                    raise RuntimeError(f"legacy page stayed hidden after reparent: {legacy_title}")
                visible_controls = [
                    w for w in page.findChildren(QWidget)
                    if w.isVisible() and not isinstance(w, QLabel)
                ]
                if len(visible_controls) < 1:
                    raise RuntimeError(f"legacy page has no visible controls: {legacy_title}")
            finally:
                child.hide()
                dialog._v0775_restore_legacy_dialog(child, page, original_idx, legacy_title)

        dialog._v0775_apply_theme("dark", False)
        app.processEvents()
        if dialog._v0775_theme_mode != "dark":
            raise RuntimeError("dark theme did not apply")
        dialog._v0775_apply_theme("light", False)
        app.processEvents()
        return True
'''
    s = must(s, smoke_anchor, smoke_new, "settings UI smoke extensions")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.5"',
        'def _v0775_build_legacy_dialog',
        'page.setVisible(True)',
        'QTimer.singleShot(0, page.show)',
        'def _v0775_stylesheet',
        'QComboBox::down-arrow',
        'QSpinBox::up-arrow',
        'def _v0775_toggle_theme',
        'ui["theme"] = mode',
        'self.v0775_theme_btn.setFixedSize(34, 34)',
        'legacy_title in ("快捷键", "大脑", "动画素材")',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.5 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.5 UI polish + night mode")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0775.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
