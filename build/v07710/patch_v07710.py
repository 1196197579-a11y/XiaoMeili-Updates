# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.10 anchor: {label}")
    return text.replace(old, new, 1)


def patch_voice(voice_path: Path):
    v = voice_path.read_text(encoding="utf-8")

    if "import re\n" not in v:
        v = must(v, "import os\n", "import os\nimport re\n", "voice re import")

    # New recommended XiaoMeili voice. Keep every previous preset available so
    # the user can A/B them instead of losing an old voice after an update.
    anchor = '''    # Optional VoiceDesign presets. These are genuinely generated from different
    # voice descriptions, rather than being style labels on Vivian/Serena.
'''
    preset = '''    "design_xiaomeili_cool": {
        "name": "小美丽｜高冷酷拽（推荐）",
        "kind": "design",
        "seed": 61723,
        "human_pause": True,
        "recommended_speed": 0.95,
        "instruct": (
            "中国普通话年轻女孩声线，年龄感偏小但不是幼童。声音清澈、偏冷，音高自然略高，"
            "但绝对不要甜、不要奶、不要撒娇。说话高冷、酷、拽、自信，带一点漫不经心和轻微嫌弃感，"
            "像一个聪明、有主见、不太愿意多解释的女孩。语速自然略慢，情绪起伏克制，短语之间有很轻的"
            "真人式停顿，转折或思考处允许短暂停一下，句尾干净利落、略微下压。不要软萌，不要夹子音，"
            "不要成熟御姐感，不要播音腔，不要明显气声，不要外国口音，也不要故意拖长尾音。"
        ),
    },
'''
    v = must(v, anchor, anchor + preset, "cool voice preset")

    # Human-like pauses are deliberately light. We do not insert filler words
    # or ellipses everywhere. We only give natural clause boundaries to text
    # that would otherwise be read as one perfectly even machine sentence.
    speed_anchor = '''    @staticmethod
    def _speed_instruction(speed):
'''
    helper = r'''    @staticmethod
    def _humanize_spoken_text(text):
        text = re.sub(r"\s+", " ", str(text or "").strip())
        if not text:
            return text

        # Normalize ASCII punctuation first.
        text = text.replace("...", "……")
        text = re.sub(r",\s*", "，", text)
        text = re.sub(r";\s*", "；", text)

        # Add a soft clause boundary before common Chinese turns only when
        # there is not already punctuation. This usually yields a subtle
        # ~phrase-level pause from Qwen3-TTS without sounding theatrical.
        connectors = (
            "不过", "但是", "可是", "所以", "然后", "其实",
            "而且", "结果", "要不", "不然", "反正",
        )
        for word in connectors:
            text = re.sub(
                rf"(?<=[\u4e00-\u9fffA-Za-z0-9])({re.escape(word)})(?=[\u4e00-\u9fffA-Za-z0-9])",
                rf"，\1",
                text,
            )

        # Avoid over-punctuation from repeated transformations.
        text = re.sub(r"，{2,}", "，", text)
        text = re.sub(r"([。！？；，])\s+", r"\1", text)
        return text

'''
    v = must(v, speed_anchor, helper + speed_anchor, "human pause helper")

    old_req = '''                req = {
                    "cmd": "synthesize",
                    "kind": preset.get("kind", "custom"),
                    "text": text,
                    "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed),
                    "output": str(out),
                }
'''
    new_req = '''                spoken_text = (
                    self._humanize_spoken_text(text)
                    if bool(preset.get("human_pause", False))
                    else text
                )
                req = {
                    "cmd": "synthesize",
                    "kind": preset.get("kind", "custom"),
                    "text": spoken_text,
                    "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed),
                    "output": str(out),
                }
'''
    v = must(v, old_req, new_req, "preview humanized text")

    voice_path.write_text(v, encoding="utf-8")
    py_compile.compile(str(voice_path), doraise=True)

    final = voice_path.read_text(encoding="utf-8")
    checks = [
        '"design_xiaomeili_cool"',
        '"小美丽｜高冷酷拽（推荐）"',
        '"human_pause": True',
        '"recommended_speed": 0.95',
        "def _humanize_spoken_text(text):",
        'spoken_text = (',
        'if bool(preset.get("human_pause", False))',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"V0.7.7.10 voice verification failed: {token}")


def patch_main(main_path: Path):
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.9"',
        'APP_NAME = "小美丽 V0.7.7.10｜Cool Voice + Voice Picker Fix + Lock Menu"\nAPP_VERSION = "0.7.7.10"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ------------------------------------------------------------------
    # Voice picker bug:
    # load_voices_async() emits synchronously while SettingsDialog is still
    # hidden. The old handler discarded that event if !isVisible(), leaving
    # the combo permanently disabled. Never gate model-state sync on visibility.
    # ------------------------------------------------------------------
    old_ready = '''    def _voice_list_ready(self, voices):
        if not self.isVisible():
            return
        voices = [str(v) for v in (voices or [])]
'''
    new_ready = '''    def _voice_list_ready(self, voices):
        voices = [str(v) for v in (voices or [])]
'''
    s = must(s, old_ready, new_ready, "voice list visibility bug")

    # Friendly installed-state button instead of a grey button that still says
    # "install". This also makes it obvious the VoiceDesign model already exists.
    old_design = '''        self.voice_design_btn = QPushButton("安装小女孩声线扩展（可选，约 4.5 GB）")
        self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
'''
    new_design = '''        self.voice_design_btn = QPushButton(
            "✓ 小女孩声线扩展已安装"
            if self.voice_service.design_ready()
            else "安装小女孩声线扩展（可选，约 4.5 GB）"
        )
        self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
'''
    s = must(s, old_design, new_design, "design button installed state")

    old_download = '''        if hasattr(self, "voice_design_btn"):
            self.voice_design_btn.setEnabled(self.voice_service.ready() and not self.voice_service.design_ready())
'''
    new_download = '''        if hasattr(self, "voice_design_btn"):
            design_ready = self.voice_service.design_ready()
            self.voice_design_btn.setText(
                "✓ 小女孩声线扩展已安装"
                if design_ready
                else "安装小女孩声线扩展（可选，约 4.5 GB）"
            )
            self.voice_design_btn.setEnabled(self.voice_service.ready() and not design_ready)
'''
    s = must(s, old_download, new_download, "design button refresh")

    # Show a friendly fixed voice name at window construction instead of
    # exposing an internal ID such as design_bean.
    old_fixed = '''        self.voice_fixed_label = QLabel("当前固定：" + (str(cfg.get("voice",{}).get("voice_id")) or "尚未选择"))
'''
    new_fixed = '''        _fixed_vid = str(cfg.get("voice",{}).get("voice_id") or "")
        _fixed_name = self.voice_service.display_name(_fixed_vid) if _fixed_vid else "尚未选择"
        self.voice_fixed_label = QLabel("当前固定：" + _fixed_name)
'''
    s = must(s, old_fixed, new_fixed, "friendly fixed voice label")

    # Make the recommended line easy to discover after the selector is fixed.
    old_status = '''        if ready:
            self.voice_status.setText(f"Qwen3-TTS 已就绪：{self.voice_combo.count()} 个小美丽候选声线可试听。")
'''
    new_status = '''        if ready:
            recommended = self.voice_combo.findData("design_xiaomeili_cool")
            suffix = " 推荐先试听「小美丽｜高冷酷拽」。" if recommended >= 0 else ""
            self.voice_status.setText(
                f"Qwen3-TTS 已就绪：{self.voice_combo.count()} 个候选声线可试听。" + suffix
            )
'''
    s = must(s, old_status, new_status, "recommended voice status")

    # New installs get a test phrase that exposes the cold/draggy delivery and
    # the light pause behavior. Existing custom test text is preserved.
    old_test = '''        self.voice_test_text = QLineEdit(str(cfg.get("voice",{}).get("test_text") or "美丽美丽，我在呢。今天又想让我陪你干嘛？"))
'''
    new_test = '''        self.voice_test_text = QLineEdit(str(
            cfg.get("voice",{}).get("test_text")
            or "你又要保枪？不过……随你。别说是我教的。"
        ))
'''
    s = must(s, old_test, new_test, "cool voice default test phrase")

    # ------------------------------------------------------------------
    # Right-click lock/unlock:
    # V0.7.7.8 still unlocked automatically on button release. Windows can post
    # WM_CONTEXTMENU after that release, so the newly-unlocked pet then shows
    # "锁定小美丽" again. While locked, keep the pet transparent and use the
    # global right-button detector only to open a separate unlock menu.
    # ------------------------------------------------------------------
    old_poll = r'''        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            self._v0778_unlock_pending = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down

            if down and not was_down:
                pos = QCursor.pos()
                self._v0778_unlock_pending = bool(self._cursor_hits_pet_shape(pos))
                if self._v0778_unlock_pending:
                    LOGGER.info("锁定状态检测到小美丽区域右键：等待释放后解锁")

            if (not down) and was_down and bool(getattr(self, "_v0778_unlock_pending", False)):
                self._v0778_unlock_pending = False
                LOGGER.info("锁定状态右键已释放：解除游戏防误触锁定")
                self.set_interaction_lock(False)
        except Exception:
            self._v0778_unlock_pending = False
            LOGGER.warning("锁定状态右键解锁检测失败", exc_info=True)
'''
    new_poll = r'''        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            self._v0778_unlock_pending = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down

            if down and not was_down:
                pos = QCursor.pos()
                self._v0778_unlock_pending = bool(self._cursor_hits_pet_shape(pos))
                if self._v0778_unlock_pending:
                    LOGGER.info("锁定状态检测到小美丽区域右键：等待释放后显示解锁菜单")

            if (not down) and was_down and bool(getattr(self, "_v0778_unlock_pending", False)):
                self._v0778_unlock_pending = False
                menu_pos = QCursor.pos()
                LOGGER.info("锁定状态右键已释放：显示解锁菜单")
                QTimer.singleShot(0, lambda p=menu_pos: self._show_locked_context_menu(p))
        except Exception:
            self._v0778_unlock_pending = False
            LOGGER.warning("锁定状态右键菜单检测失败", exc_info=True)
'''
    s = must(s, old_poll, new_poll, "locked right-click menu trigger")

    menu_anchor = '''    def set_interaction_lock(self, locked):
'''
    locked_menu = r'''    def _show_locked_context_menu(self, global_pos=None):
        if not bool(self.cfg.get("lock_position", False)):
            return
        pos = global_pos if global_pos is not None else QCursor.pos()
        menu = QMenu()
        unlock_action = menu.addAction("解锁小美丽（游戏防误触）")
        chosen = menu.exec(pos)
        if chosen == unlock_action:
            self.set_interaction_lock(False)

'''
    s = must(s, menu_anchor, locked_menu + menu_anchor, "locked unlock menu method")

    old_context = r'''    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        menu = QMenu(self)
        lock_action = menu.addAction(
            "解锁小美丽（游戏防误触）" if locked else "锁定小美丽（游戏防误触）"
        )
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
    new_context = r'''    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        if locked:
            # Normally unreachable because the pet itself is transparent.
            # Keep this fallback state-correct if Windows delivers it anyway.
            self._show_locked_context_menu(event.globalPos())
            event.accept()
            return

        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

'''
    s = must(s, old_context, new_context, "right-click state-correct menu")

    # ------------------------------------------------------------------
    # Frozen self-test additions. They require no voice model downloads.
    # ------------------------------------------------------------------
    smoke_anchor = '''        if brain.get_rule(probe_id) is not None:
            raise RuntimeError("v0779 deleted rule is still addressable")

        return True
'''
    smoke_new = '''        if brain.get_rule(probe_id) is not None:
            raise RuntimeError("v0779 deleted rule is still addressable")

        # Voice list sync must work while the settings dialog is not visible,
        # which is the exact regression that left the user's selector greyed out.
        dialog.hide()
        dialog._voice_list_ready(["design_xiaomeili_cool"])
        app.processEvents()
        if dialog.voice_combo.count() != 1:
            raise RuntimeError("voice selector ignored hidden-dialog voice list")
        if str(dialog.voice_combo.currentData() or "") != "design_xiaomeili_cool":
            raise RuntimeError("recommended cool voice did not populate selector")
        if not dialog.voice_combo.isEnabled():
            raise RuntimeError("voice selector remained disabled after voice list sync")

        if voice.display_name("design_xiaomeili_cool") != "小美丽｜高冷酷拽（推荐）":
            raise RuntimeError("cool XiaoMeili voice preset missing")
        humanized = voice._humanize_spoken_text("你今天还行但是别得意")
        if "，但是" not in humanized:
            raise RuntimeError(f"human pause text transform failed: {humanized}")

        return True
'''
    s = must(s, smoke_anchor, smoke_new, "v07710 voice smoke tests")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.10"',
        'def _voice_list_ready(self, voices):\\n        voices = [str(v)',
        '✓ 小女孩声线扩展已安装',
        'design_xiaomeili_cool',
        'def _show_locked_context_menu(self, global_pos=None):',
        '等待释放后显示解锁菜单',
        'unlock_action = menu.addAction("解锁小美丽（游戏防误触）")',
        'dialog._voice_list_ready(["design_xiaomeili_cool"])',
    ]
    for token in checks:
        if token.replace("\\n", "\n") not in final:
            raise RuntimeError(f"V0.7.7.10 main verification failed: {token}")


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    voice_path = source_root / "app" / "src" / "voice_qwen.py"
    if not main_path.exists() or not voice_path.exists():
        raise FileNotFoundError("V0.7.7.10 source inputs missing")

    patch_voice(voice_path)
    patch_main(main_path)
    print("Patched XiaoMeili source to V0.7.7.10 cool voice + selector + lock menu")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v07710.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
