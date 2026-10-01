# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import py_compile
import zlib
import sys
from pathlib import Path


def must(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f"V0.10.0 anchor missing: {label}")
    return s.replace(old, new, 1)


def patch(source_root: Path, repo_root: Path):
    source_root = source_root.resolve()
    repo_root = repo_root.resolve()
    main = source_root / "app" / "src" / "main.py"
    speech = source_root / "app" / "src" / "speech_input.py"
    version_file = source_root / "app" / "assets" / "VERSION.txt"
    asset_blob = repo_root / "build" / "v0100" / "payloads.json"

    if not main.exists() or not asset_blob.exists():
        raise RuntimeError("V0.10.0 source/asset inputs missing")

    payload = json.loads(asset_blob.read_text(encoding="utf-8"))
    module_data = base64.b64decode(payload.pop("__ability_sidebar_py_zlib__").encode("ascii"))
    (source_root / "app" / "src" / "ability_sidebar.py").write_bytes(zlib.decompress(module_data))
    for name, encoded in payload.items():
        target = source_root / "app" / "assets" / str(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(encoded.encode("ascii")))

    s = main.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.9.2.8"' not in s:
        raise RuntimeError("V0.10.0 expected V0.9.2.8 base")

    s = s.replace('APP_VERSION = "0.9.2.8"', 'APP_VERSION = "0.10.0"', 1)
    s = s.replace(
        'APP_NAME = "小美丽 V0.9.2.8｜Voice Interaction"',
        'APP_NAME = "小美丽 V0.10.0｜美丽能力侧栏"',
        1,
    )
    s = s.replace(
        "自动存储清理已禁用：V0.9.2.8 不会自动删除任何文件。",
        "自动存储清理已禁用：V0.10.0 不会自动删除任何文件。",
        1,
    )
    s = s.replace('"config_version": 23', '"config_version": 24', 1)

    app_anchor = 'APP_NAME = "小美丽 V0.10.0｜美丽能力侧栏"\n'
    s = must(
        s,
        app_anchor,
        'from ability_sidebar import AbilitySidebarManager\n\n' + app_anchor,
        "ability sidebar import",
    )

    s = must(
        s,
        '''class PetWindow(QWidget):\n    request_settings = Signal()\n    config_changed = Signal()\n''',
        '''class PetWindow(QWidget):\n    request_settings = Signal()\n    request_ability = Signal()\n    config_changed = Signal()\n''',
        "PetWindow ability signal",
    )

    old_menu = '''        menu = QMenu(self)\n        lock_action = menu.addAction("锁定小美丽（游戏防误触）")\n        menu.addSeparator()\n        showhide = menu.addAction("显示/隐藏")\n        settings = menu.addAction("设置")\n        chosen = menu.exec(event.globalPos())\n        if chosen == lock_action:\n            self.set_interaction_lock(True)\n        elif chosen == showhide:\n            self.toggle_show_hide()\n        elif chosen == settings:\n            self.request_settings.emit()\n'''
    new_menu = '''        menu = QMenu(self)\n        ability_action = menu.addAction("美丽能力侧栏")\n        lock_action = menu.addAction("锁定小美丽（游戏防误触）")\n        menu.addSeparator()\n        showhide = menu.addAction("显示/隐藏")\n        settings = menu.addAction("设置")\n        chosen = menu.exec(event.globalPos())\n        if chosen == ability_action:\n            self.request_ability.emit()\n        elif chosen == lock_action:\n            self.set_interaction_lock(True)\n        elif chosen == showhide:\n            self.toggle_show_hide()\n        elif chosen == settings:\n            self.request_settings.emit()\n'''
    s = must(s, old_menu, new_menu, "pet context ability action")

    settings_method_anchor = '''    def _v774_schedule_apply(self, *args):\n'''
    ability_settings_methods = '''    def _v0100_set_ability_option(self, key, value):\n        try:\n            cfg = self.cfg.setdefault("ability_sidebar", {})\n            cfg[str(key)] = bool(value)\n            save_config(self.cfg)\n            self.config_changed.emit()\n        except Exception:\n            LOGGER.exception("保存美丽能力侧栏设置失败: %s", key)\n\n'''
    s = must(
        s,
        settings_method_anchor,
        ability_settings_methods + settings_method_anchor,
        "ability settings save helper",
    )

    interaction_anchor = '''        card, _ = self._v774_card("动画过渡", "动作切换速度", control=self.v774_transition_combo)\n        int_cards.append(card)\n\n        iv.addWidget(self._v774_scroll_grid(int_cards, 2), 1)\n'''
    interaction_new = '''        card, _ = self._v774_card("动画过渡", "动作切换速度", control=self.v774_transition_combo)\n        int_cards.append(card)\n\n        ability_cfg = self.cfg.setdefault("ability_sidebar", {})\n        self.v0100_ability_cb = QCheckBox("开启")\n        self.v0100_ability_cb.setChecked(bool(ability_cfg.get("enabled", True)))\n        self.v0100_ability_cb.toggled.connect(lambda v: self._v0100_set_ability_option("enabled", v))\n        card, _ = self._v774_card("美丽能力侧栏", "贴身能力节点 + 顺滑展开", "鼠标靠近小美丽后出现入口；锁定状态自动隐藏。", control=self.v0100_ability_cb)\n        int_cards.append(card)\n\n        self.v0100_ability_voice_cb = QCheckBox("开启")\n        self.v0100_ability_voice_cb.setChecked(bool(ability_cfg.get("voice_feedback_enabled", True)))\n        self.v0100_ability_voice_cb.toggled.connect(lambda v: self._v0100_set_ability_option("voice_feedback_enabled", v))\n        card, _ = self._v774_card("能力语音反馈", "已预留五项独立事件接口", "本版先完成视觉与事件接口，后续可为每个开关绑定专属语音。", control=self.v0100_ability_voice_cb)\n        int_cards.append(card)\n\n        self.v0100_ability_command_cb = QCheckBox("开启")\n        self.v0100_ability_command_cb.setChecked(bool(ability_cfg.get("voice_command_enabled", True)))\n        self.v0100_ability_command_cb.toggled.connect(lambda v: self._v0100_set_ability_option("voice_command_enabled", v))\n        card, _ = self._v774_card("语音打开侧栏", "支持「美丽美丽，打开能力侧栏」", "也支持「收起能力侧栏」；彩蛋口令「开挂」只负责打开娱乐侧栏。", control=self.v0100_ability_command_cb)\n        int_cards.append(card)\n\n        iv.addWidget(self._v774_scroll_grid(int_cards, 2), 1)\n'''
    s = must(s, interaction_anchor, interaction_new, "interaction ability cards")

    controller_line = '        self.app=app; self.cfg=cfg; self.bridge=Bridge(); self.pet=PetWindow(cfg); self.settings=None\n'
    controller_new = controller_line + '''        self.ability_sidebar=AbilitySidebarManager(\n            self.pet, self.cfg,\n            resource("assets/ability_xiaomeili.png"),\n            [resource(f"assets/ability_label_{i}.png") for i in range(1,6)],\n            save_callback=save_config, open_settings_callback=self.open_settings,\n        )\n'''
    s = must(s, controller_line, controller_new, "AppController ability manager")

    signal_anchor = '        self.pet.request_settings.connect(self.open_settings)\n'
    signal_new = signal_anchor + '''        self.pet.request_ability.connect(self.ability_sidebar.toggle)\n        self.ability_sidebar.ability_event.connect(self._on_ability_event)\n'''
    s = must(s, signal_anchor, signal_new, "ability signals")

    tray_anchor = '''        menu.addSeparator()\n        self.lock_act=QAction("锁定（位置 + 点击穿透）",menu); self.lock_act.setCheckable(True); self.lock_act.setChecked(self.cfg.get("click_through",False)); self.lock_act.triggered.connect(self.pet.set_interaction_lock); menu.addAction(self.lock_act)\n'''
    tray_new = '''        menu.addSeparator()\n        ability=QAction("美丽能力侧栏",menu); ability.triggered.connect(self.ability_sidebar.toggle); menu.addAction(ability)\n        self.lock_act=QAction("锁定（位置 + 点击穿透）",menu); self.lock_act.setCheckable(True); self.lock_act.setChecked(self.cfg.get("click_through",False)); self.lock_act.triggered.connect(self.pet.set_interaction_lock); menu.addAction(self.lock_act)\n'''
    s = must(s, tray_anchor, tray_new, "tray ability action")

    settings_changed = '''    def _on_settings_changed(self):\n        self.update_tray_checks()\n        self.refresh_speech_interaction()\n'''
    settings_changed_new = '''    def _on_settings_changed(self):\n        self.update_tray_checks()\n        self.refresh_speech_interaction()\n        self.ability_sidebar.refresh_config()\n'''
    s = must(s, settings_changed, settings_changed_new, "settings ability refresh")

    speech_cfg_anchor = '''    def _speech_cfg(self):\n'''
    ability_controller_methods = r'''    def _on_ability_event(self, key, enabled):
        LOGGER.info("[ABILITY] %s -> %s", str(key), "ON" if enabled else "OFF")

    def _handle_ability_voice_command(self, text):
        if not bool(self.cfg.setdefault("ability_sidebar", {}).get("voice_command_enabled", True)):
            return False
        raw = re.sub(r"[\s，,。.!！？?、:：]+", "", str(text or "").strip())
        if not raw:
            return False
        open_cmds = {"打开能力侧栏", "开启能力侧栏", "打开美丽能力", "打开美丽能力侧栏", "开挂"}
        close_cmds = {"收起能力侧栏", "关闭能力侧栏", "收起美丽能力", "关闭美丽能力"}
        if raw in open_cmds:
            self.ability_sidebar.open()
            LOGGER.info("[ABILITY] voice command open: %s", text)
            return True
        if raw in close_cmds:
            self.ability_sidebar.close()
            LOGGER.info("[ABILITY] voice command close: %s", text)
            return True
        return False

'''
    s = must(s, speech_cfg_anchor, ability_controller_methods + speech_cfg_anchor, "ability controller methods")

    utterance_old = '''        if not self._speech_session_active:\n            woke,rest=self._split_wake_phrase(text)\n            if not woke:return\n            self._begin_speech_session(rest)\n'''
    utterance_new = '''        if not self._speech_session_active:\n            woke,rest=self._split_wake_phrase(text)\n            if not woke:return\n            if self._handle_ability_voice_command(rest):\n                return\n            self._begin_speech_session(rest)\n'''
    s = must(s, utterance_old, utterance_new, "ability voice interception")

    quit_anchor = '''    def quit(self):\n        try:\n            self.cfg["x"],self.cfg["y"]=self.pet.x(),self.pet.y(); save_config(self.cfg)\n'''
    quit_new = '''    def quit(self):\n        try:\n            try: self.ability_sidebar.shutdown()\n            except Exception: pass\n            self.cfg["x"],self.cfg["y"]=self.pet.x(),self.pet.y(); save_config(self.cfg)\n'''
    s = must(s, quit_anchor, quit_new, "ability shutdown")

    test_anchor = '''    updater = UpdateService(cfg)\n    dialog = SettingsDialog(cfg, pet, vision, voice, brain, updater, speech)\n    try:\n'''
    test_new = '''    updater = UpdateService(cfg)\n    ability = AbilitySidebarManager(\n        pet, cfg, resource("assets/ability_xiaomeili.png"),\n        [resource(f"assets/ability_label_{i}.png") for i in range(1,6)],\n        save_callback=save_config,\n    )\n    dialog = SettingsDialog(cfg, pet, vision, voice, brain, updater, speech)\n    try:\n        if ability.overlay.character.isNull() or any(pm.isNull() for pm in ability.overlay.panel.labels):\n            raise RuntimeError("V0.10.0 ability sidebar visual asset missing")\n        ability.overlay.panel.set_checked(1, True, animated=False, emit=False)\n        if not ability.overlay.panel.states[1] or ability.overlay.panel.values[1] < 0.99:\n            raise RuntimeError("V0.10.0 ability switch state model failed")\n'''
    s = must(s, test_anchor, test_new, "ability frozen self-test setup")

    finally_anchor = '''    finally:\n        try:\n            dialog.close()\n'''
    finally_new = '''    finally:\n        try:\n            ability.shutdown()\n        except Exception:\n            pass\n        try:\n            dialog.close()\n'''
    s = must(s, finally_anchor, finally_new, "ability frozen self-test cleanup")

    checks = [
        'APP_VERSION = "0.10.0"',
        'from ability_sidebar import AbilitySidebarManager',
        'request_ability = Signal()',
        'menu.addAction("美丽能力侧栏")',
        'def _v0100_set_ability_option(self, key, value):',
        'self.v0100_ability_cb = QCheckBox("开启")',
        'self.ability_sidebar=AbilitySidebarManager(',
        'self.pet.request_ability.connect(self.ability_sidebar.toggle)',
        'def _handle_ability_voice_command(self, text):',
        'if self._handle_ability_voice_command(rest):',
        'ability.overlay.panel.set_checked(1, True, animated=False, emit=False)',
        'from native_updater import install_update_package',
    ]
    for token in checks:
        if token not in s:
            raise RuntimeError("V0.10.0 verification missing: " + token)

    main.write_text(s, encoding="utf-8")
    py_compile.compile(str(main), doraise=True)
    py_compile.compile(str(source_root / "app" / "src" / "ability_sidebar.py"), doraise=True)

    sp = speech.read_text(encoding="utf-8")
    sp = sp.replace("小美丽 V0.9.2.8 语音诊断日志", "小美丽 V0.10.0 语音诊断日志")
    speech.write_text(sp, encoding="utf-8")
    py_compile.compile(str(speech), doraise=True)

    version_file.write_text("0.10.0\n", encoding="ascii")

    ability_text = (source_root / "app" / "src" / "ability_sidebar.py").read_text(encoding="utf-8")
    for forbidden in ("unlink(", "rmtree(", "os.remove(", "shutil.move(", "replace(", "rename("):
        if forbidden in ability_text:
            raise RuntimeError("V0.10.0 ability module violates no-delete policy: " + forbidden)

    print("Patched XiaoMeili source to V0.10.0 ability sidebar")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0100.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]), Path(sys.argv[2]))
