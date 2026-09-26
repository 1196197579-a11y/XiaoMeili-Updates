# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.6 anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"

    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.5"',
        'APP_NAME = "小美丽 V0.7.7.6｜Lean General + Editable Profile"\nAPP_VERSION = "0.7.7.6"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    s = must(
        s,
        "from PIL import Image\n",
        "from PIL import Image, ImageOps, ImageDraw\n",
        "Pillow imports",
    )

    # ------------------------------------------------------------------
    # 1) Remove low-value General cards.
    # Click-through is retired as a user-facing state, because a click-through
    # pet cannot receive the right-click that is now required to unlock it.
    # ------------------------------------------------------------------
    click_card = '''        self.v774_click_cb = QCheckBox("开启")
        self.v774_click_cb.setChecked(bool(self.cfg.get("click_through", False)))
        self.v774_click_cb.toggled.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("点击穿透", "鼠标点击会穿过桌宠", control=self.v774_click_cb)
        cards.append(card)

'''
    s = must(s, click_card, "", "remove click-through card")

    opacity_card = '''        self.v774_opacity = QSlider(Qt.Orientation.Horizontal)
        self.v774_opacity.setRange(30, 100)
        self.v774_opacity.setFixedWidth(150)
        self.v774_opacity.setValue(int(self.cfg.get("opacity", 100)))
        self.v774_opacity.valueChanged.connect(self._v774_schedule_apply)
        card, _ = self._v774_card("透明度", f"当前 {int(self.cfg.get('opacity',100))}%", "拖动后自动保存", control=self.v774_opacity)
        cards.append(card)

'''
    s = must(s, opacity_card, "", "remove opacity card")

    position_card = '''        card, _ = self._v774_card("桌宠位置", "当前位置可随时重置", "", "移到屏幕左上", lambda: self.pet.move(100, 100))
        cards.append(card)

'''
    s = must(s, position_card, "", "remove reset-position card")

    # Old hidden settings must never resurrect click-through when another setting
    # is auto-saved. Opacity is normalized to 100% because its UI is retired.
    old_apply = '''        if hasattr(self, "v774_click_cb"):
            self.cfg["click_through"] = bool(self.v774_click_cb.isChecked())
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
'''
    new_apply = '''        # V0.7.7.6: click-through UI is retired. Keep the pet right-clickable.
        self.cfg["click_through"] = False
        self.cfg["opacity"] = 100
        if hasattr(self, "v774_lockpos_cb"):
            self.cfg["lock_position"] = bool(self.v774_lockpos_cb.isChecked())
'''
    s = must(s, old_apply, new_apply, "retire click-through persistence")

    # ------------------------------------------------------------------
    # 2) Remove hover lock bubble and move lock/unlock into the pet context menu.
    # Lock now means "lock position", not click-through, otherwise the user
    # would be unable to right-click the pet again to unlock it.
    # ------------------------------------------------------------------
    old_lock_init = '''        self.lock_bubble = LockBubble()
        self.lock_bubble.clicked.connect(self.toggle_interaction_lock)
        self.lock_bubble.set_locked(bool(self.cfg.get("click_through", False)))
        self._hover_last_seen = 0.0
'''
    new_lock_init = '''        # V0.7.7.6 migration: retire click-through + hover lock bubble.
        # Keep a hidden LockBubble object only for old shutdown code compatibility.
        if bool(self.cfg.get("click_through", False)) or int(self.cfg.get("opacity", 100)) != 100:
            self.cfg["click_through"] = False
            self.cfg["opacity"] = 100
            save_config(self.cfg)
        else:
            self.cfg["click_through"] = False
            self.cfg["opacity"] = 100
        self.lock_bubble = LockBubble()
        self.lock_bubble.hide()
        self._hover_last_seen = 0.0
'''
    s = must(s, old_lock_init, new_lock_init, "remove hover lock init")

    hover_start = s.index("    def _position_lock_bubble(self):\n", s.index("class PetWindow(QWidget):"))
    hover_end = s.index("    def toggle_show_hide(self):\n", hover_start)
    new_lock_methods = r'''    def _position_lock_bubble(self):
        # Retained only for backward compatibility. The bubble is no longer shown.
        try:
            self.lock_bubble.hide()
        except Exception:
            pass

    def poll_hover_lock_button(self):
        # V0.7.7.6: the floating lock icon has been removed.
        try:
            if self.lock_bubble.isVisible():
                self.lock_bubble.hide()
        except Exception:
            pass

    def set_interaction_lock(self, locked):
        # "Lock" now means position lock only. Click-through would make the new
        # right-click unlock action unreachable, so it is intentionally disabled.
        locked = bool(locked)
        self.cfg["click_through"] = False
        self.cfg["lock_position"] = locked
        save_config(self.cfg)
        self.apply_clickthrough_native()
        try:
            self.lock_bubble.hide()
        except Exception:
            pass
        self.config_changed.emit()

    def toggle_interaction_lock(self):
        self.set_interaction_lock(not bool(self.cfg.get("lock_position", False)))

'''
    s = s[:hover_start] + new_lock_methods + s[hover_end:]

    menu_start = s.index("    def contextMenuEvent(self, event):\n", s.index("class PetWindow(QWidget):"))
    menu_end = s.index("    def mouseDoubleClickEvent(self, event):\n", menu_start)
    new_menu = r'''    def contextMenuEvent(self, event):
        menu = QMenu(self)
        locked = bool(self.cfg.get("lock_position", False))
        lock_action = menu.addAction("解除锁定" if locked else "锁定位置")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(not locked)
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

'''
    s = s[:menu_start] + new_menu + s[menu_end:]

    # ------------------------------------------------------------------
    # 3) Double-click learning rules + restore mode choice after editing.
    # The old editor only updated the existing mode, which is why the
    # "learn this meaning / fixed sentence" choice disappeared.
    # ------------------------------------------------------------------
    rule_list_anchor = '''        self.brain_rules_list = QListWidget(); self.brain_rules_list.setMinimumHeight(330)
        rules_dv.addWidget(self.brain_rules_list, 1)
'''
    rule_list_new = '''        self.brain_rules_list = QListWidget(); self.brain_rules_list.setMinimumHeight(330)
        self.brain_rules_list.setToolTip("双击任意规则即可编辑")
        self.brain_rules_list.itemDoubleClicked.connect(lambda item: self._brain_edit_rule())
        rules_dv.addWidget(self.brain_rules_list, 1)
'''
    s = must(s, rule_list_anchor, rule_list_new, "rule double-click")

    edit_start = s.index("    def _brain_edit_rule(self):\n")
    edit_end = s.index("    def _brain_toggle_rule(self):\n", edit_start)
    new_edit = r'''    def _v0776_choose_rule_mode(self, current_mode="fixed"):
        box = QMessageBox(self)
        box.setWindowTitle("选择养成方式")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("这条修改后的规则，想让小美丽怎么记住？")
        box.setInformativeText(
            "学这个意思（推荐）：允许自然换句式，但核心意思不能偏离。\n"
            "固定这句话：同样的问题逐字回答你写的内容。"
        )
        semantic_btn = box.addButton("学这个意思（推荐）", QMessageBox.ButtonRole.AcceptRole)
        fixed_btn = box.addButton("固定这句话", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        if str(current_mode) == "semantic":
            box.setDefaultButton(semantic_btn)
        else:
            box.setDefaultButton(fixed_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is semantic_btn:
            return "semantic"
        if clicked is fixed_btn:
            return "fixed"
        return None

    def _brain_edit_rule(self):
        rule_id = self._selected_brain_rule_id()
        if not rule_id:
            QMessageBox.information(self, "养成库", "请先选中一条规则。")
            return
        rule = self.brain_service.get_rule(rule_id)
        if not rule:
            self._refresh_brain_rules()
            return

        current_mode = str(rule.get("mode") or "fixed")
        if current_mode == "semantic":
            initial_answer = str(rule.get("reference_answer") or rule.get("intent") or "").strip()
            prompt = "修改这条规则想表达的答案 / 核心意思：\n\n点击确定后，可以重新选择「学这个意思」或「固定这句话」。"
        else:
            initial_answer = str(rule.get("reference_answer") or "").strip()
            prompt = "修改同样问题命中时的回答：\n\n点击确定后，可以重新选择「学这个意思」或「固定这句话」。"

        desired, ok = QInputDialog.getMultiLineText(
            self,
            "编辑养成规则",
            prompt,
            initial_answer,
        )
        if not ok:
            return
        desired = str(desired or "").strip()
        if not desired:
            QMessageBox.information(self, "养成库", "规则内容不能为空。")
            return

        mode = self._v0776_choose_rule_mode(current_mode)
        if not mode:
            return

        if mode == "fixed":
            self.brain_service.update_rule(
                rule_id,
                {
                    "mode": "fixed",
                    "reference_answer": desired,
                    "intent": "",
                    "must": "",
                    "forbid": "",
                    "tone": "",
                },
            )
            self.brain_status.setText(f"规则 #{rule_id} 已保存为固定台词")
        else:
            base = dict(rule)
            base["scene"] = str(base.get("scene") or base.get("user_text") or "").strip()
            base["intent"] = desired
            base["must"] = desired
            base["reference_answer"] = desired
            if not str(base.get("tone") or "").strip():
                base["tone"] = "保持主人纠正时的口吻"

            semantic_text, accepted = QInputDialog.getMultiLineText(
                self,
                "确认语义规则",
                "可以继续调整场景、核心意思、必须体现、禁止偏离和语气：",
                self._semantic_rule_text(base),
            )
            if not accepted:
                return
            changes = self._parse_semantic_rule_text(semantic_text, base)
            changes["mode"] = "semantic"
            changes["reference_answer"] = desired
            self.brain_service.update_rule(rule_id, changes)
            self.brain_status.setText(f"规则 #{rule_id} 已保存为语义规则")

        self._refresh_brain_rules()

'''
    s = s[:edit_start] + new_edit + s[edit_end:]

    # ------------------------------------------------------------------
    # 4) Editable sidebar avatar.
    # It is copied into XiaoMeiliData so updates and D-drive migration keep it.
    # Hover shows a lightweight "更换" overlay; click opens an image picker.
    # ------------------------------------------------------------------
    settings_anchor = "class SettingsDialog(QDialog):\n"
    avatar_class = r'''class EditableAvatar(QLabel):
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._editable_hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("点击更换头像")

    def enterEvent(self, event):
        self._editable_hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._editable_hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._editable_hover:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(9, 49, 40, 145))
        p.drawEllipse(rect)
        p.setPen(QColor("#FFFFFF"))
        font = p.font()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "更换")
        p.end()


'''
    s = must(s, settings_anchor, avatar_class + settings_anchor, "editable avatar class")

    # Avatar methods inside SettingsDialog.
    avatar_method_anchor = "    def _v774_edit_pet_name(self):\n"
    avatar_methods = r'''    def _v0776_avatar_file(self):
        raw = str(self.cfg.get("settings_ui", {}).get("profile_avatar") or "").strip()
        p = Path(raw) if raw else (USER / "profile" / "avatar.png")
        return p

    def _v0776_refresh_avatar(self):
        label = getattr(self, "v0776_avatar", None)
        if label is None:
            return
        p = self._v0776_avatar_file()
        if p.exists() and p.is_file():
            pix = QPixmap(str(p))
            if not pix.isNull():
                label.setText("")
                label.setPixmap(
                    pix.scaled(
                        56, 56,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        label.setPixmap(QPixmap())
        label.setText("美")

    def _v0776_choose_avatar(self):
        start = str(Path.home() / "Pictures")
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择小美丽头像",
            start,
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not chosen:
            return
        try:
            target = USER / "profile" / "avatar.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(chosen) as src:
                img = ImageOps.exif_transpose(src).convert("RGBA")
                side = max(1, min(img.width, img.height))
                left = max(0, (img.width - side) // 2)
                top = max(0, (img.height - side) // 2)
                img = img.crop((left, top, left + side, top + side))
                resampling = getattr(Image, "Resampling", Image)
                img = img.resize((256, 256), resampling.LANCZOS)
                mask = Image.new("L", (256, 256), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((2, 2, 253, 253), fill=255)
                out = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                out.paste(img, (0, 0), mask)
                out.save(target, format="PNG", optimize=True)

            self.cfg.setdefault("settings_ui", {})["profile_avatar"] = str(target)
            save_config(self.cfg)
            self._v0776_refresh_avatar()
        except Exception as exc:
            LOGGER.exception("保存自定义头像失败")
            QMessageBox.warning(self, "头像设置失败", f"{type(exc).__name__}: {exc}")

'''
    s = must(s, avatar_method_anchor, avatar_methods + avatar_method_anchor, "avatar methods")

    old_avatar_block = '''        avatar = QLabel("美")
        avatar.setObjectName("avatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(56, 56)
        ph.addWidget(avatar)
'''
    new_avatar_block = '''        self.v0776_avatar = EditableAvatar("美")
        self.v0776_avatar.setObjectName("avatar")
        self.v0776_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.v0776_avatar.setFixedSize(56, 56)
        self.v0776_avatar.clicked.connect(self._v0776_choose_avatar)
        self._v0776_refresh_avatar()
        ph.addWidget(self.v0776_avatar)
'''
    s = must(s, old_avatar_block, new_avatar_block, "sidebar avatar")

    # The retired controls must not be touched by the immediate-save bridge.
    old_sync = '''            if hasattr(self, "v774_opacity"):
                self.opacity.blockSignals(True)
                self.opacity.setValue(int(self.v774_opacity.value()))
                self.opacity.blockSignals(False)
'''
    s = must(s, old_sync, "", "remove opacity sync")

    # Strengthen runtime UI smoke checks for the V0.7.7.6 contract.
    smoke_anchor = '''        dialog._v0775_apply_theme("light", False)
        app.processEvents()
        return True
'''
    smoke_new = '''        dialog._v0775_apply_theme("light", False)
        app.processEvents()

        # General page no longer exposes the retired controls.
        general = dialog.v774_stack.widget(0)
        texts = []
        for w in general.findChildren((QLabel, QCheckBox, QPushButton)):
            try:
                texts.append(str(w.text() or ""))
            except Exception:
                pass
        joined = "\\n".join(texts)
        for retired in ("点击穿透", "透明度", "桌宠位置"):
            if retired in joined:
                raise RuntimeError(f"retired General control is still visible: {retired}")

        if not isinstance(getattr(dialog, "v0776_avatar", None), EditableAvatar):
            raise RuntimeError("editable avatar widget missing")

        return True
'''
    s = must(s, smoke_anchor, smoke_new, "v0776 UI smoke checks")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    # Brain service: allow an existing rule to change between fixed/semantic modes.
    b = brain_path.read_text(encoding="utf-8")
    old_keys = '''            for key in ("scene", "intent", "must", "forbid", "tone", "reference_answer", "enabled"):
                if key in changes:
                    rule[key] = changes[key]
'''
    new_keys = '''            for key in ("mode", "user_text", "scene", "intent", "must", "forbid", "tone", "reference_answer", "enabled"):
                if key in changes:
                    rule[key] = changes[key]
'''
    b = must(b, old_keys, new_keys, "rule mode updates")
    brain_path.write_text(b, encoding="utf-8")
    py_compile.compile(str(brain_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.6"',
        'menu.addAction("解除锁定" if locked else "锁定位置")',
        'self.cfg["click_through"] = False',
        'def poll_hover_lock_button(self):',
        'self.brain_rules_list.itemDoubleClicked.connect',
        'def _v0776_choose_rule_mode',
        '点击确定后，可以重新选择',
        'class EditableAvatar(QLabel):',
        'self.v0776_avatar.clicked.connect(self._v0776_choose_avatar)',
        'USER / "profile" / "avatar.png"',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.6 static verification failed: {token}")

    for retired_block in (
        'self._v774_card("点击穿透"',
        'self._v774_card("透明度"',
        'self._v774_card("桌宠位置"',
    ):
        if retired_block in final:
            raise RuntimeError(f"retired UI still present: {retired_block}")

    print("Patched XiaoMeili source to V0.7.7.6 lean General + rule editing + editable avatar")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0776.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
