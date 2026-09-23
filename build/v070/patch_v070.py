# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7 patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_src = repo_root / "build" / "v070" / "brain_qwen.py"
    brain_dst = source_root / "app" / "src" / "brain_qwen.py"
    if not main_path.exists() or not brain_src.exists():
        raise FileNotFoundError("v0.7 source inputs missing")
    shutil.copy2(brain_src, brain_dst)

    s = main_path.read_text(encoding="utf-8")
    s = must(
        s,
        'APP_NAME = "小美丽 V0.6.2.2｜Qwen3-TTS Voice Mouth + Output Routing"\nAPP_VERSION = "0.6.2.2"',
        'APP_NAME = "小美丽 V0.7｜Local Brain + Qwen3-TTS + Continuous Puppet V2"\nAPP_VERSION = "0.7.0"',
        "version",
    )

    # QTextEdit is used by the persona editor.
    s = must(
        s,
        'QProgressDialog, QDoubleSpinBox, QInputDialog, QProgressBar\n)',
        'QProgressDialog, QDoubleSpinBox, QInputDialog, QProgressBar, QTextEdit\n)',
        "QTextEdit import",
    )

    # Brain backend is a lightweight bridge; llama.cpp/model are downloaded at first use.
    s = must(
        s,
        'from voice_qwen import VoiceService\n',
        'from voice_qwen import VoiceService\nfrom brain_qwen import BrainService, DEFAULT_PERSONA\n',
        "BrainService import",
    )

    # Config schema.
    s = must(s, '"config_version": 18,', '"config_version": 19,', "config version")
    voice_block = '''        "voice": {
            "enabled": True,
            "voice_id": "",
            "speed": 1.0,
            "test_text": "美丽美丽，我在呢。今天又想让我陪你干嘛？",
            "output_device": "default",
        },
'''
    brain_block = voice_block + '''        "brain": {
            "enabled": True,
            "auto_speak": True,
            "temperature": 0.78,
            "max_tokens": 220,
            "context_turns": 6,
            "persona": DEFAULT_PERSONA,
        },
'''
    s = must(s, voice_block, brain_block, "brain config block")

    s = must(
        s,
        'if k in ("hotkeys", "assets", "vision", "mouse_interaction", "voice", "updates"):',
        'if k in ("hotkeys", "assets", "vision", "mouse_interaction", "voice", "brain", "updates"):',
        "brain config skip",
    )
    s = must(
        s,
        '    old_updates = old_data.get("updates", {}) if isinstance(old_data.get("updates"), dict) else {}\n',
        '    old_brain = old_data.get("brain", {}) if isinstance(old_data.get("brain"), dict) else {}\n'
        '    cfg["brain"].update({k: v for k, v in old_brain.items() if k in cfg["brain"]})\n\n'
        '    old_updates = old_data.get("updates", {}) if isinstance(old_data.get("updates"), dict) else {}\n',
        "brain config migration",
    )

    # Frozen self-test now verifies both external-service bridges.
    s = must(
        s,
        '    from voice_qwen import VoiceService\n    _ = VoiceService\n    return True',
        '    from voice_qwen import VoiceService\n    from brain_qwen import BrainService\n    _ = VoiceService\n    _ = BrainService\n    return True',
        "runtime brain self test",
    )

    # Settings dialog receives the long-lived BrainService.
    s = must(
        s,
        'def __init__(self, cfg, pet: PetWindow, vision: VisionWorker, voice_service, update_service, parent=None):',
        'def __init__(self, cfg, pet: PetWindow, vision: VisionWorker, voice_service, brain_service, update_service, parent=None):',
        "settings signature",
    )
    s = must(
        s,
        '        self.voice_service = voice_service\n        self.update_service = update_service',
        '        self.voice_service = voice_service\n        self.brain_service = brain_service\n        self.update_service = update_service',
        "settings brain assignment",
    )

    # Insert V0.7 Brain tab directly after voice setup and before Updates.
    anchor = '        # Updates V0.6.1\n'
    brain_ui = '''        # Brain V0.7: local text conversation + persona + feedback learning.
        bp = QWidget(); bv = QVBoxLayout(bp)
        bintro = QLabel(
            "V0.7 给小美丽装上“脑子”：文字输入 → 本地 Qwen3-8B → 小美丽人格 → 固定 Qwen3-TTS 声音。"
            "\n这一版先把思考和人格调稳，麦克风、唤醒词和白板联动放到后续版本。"
        )
        bintro.setWordWrap(True); bv.addWidget(bintro)

        bbox = QGroupBox("小美丽本地大脑"); bf = QFormLayout(bbox)
        self.brain_status = QLabel(self.brain_service.component_status()); self.brain_status.setWordWrap(True)
        bf.addRow("组件状态", self.brain_status)
        self.brain_progress = QProgressBar(); self.brain_progress.setRange(0,100); self.brain_progress.setValue(100 if self.brain_service.ready() else 0)
        bf.addRow("首次准备", self.brain_progress)
        self.brain_prepare_btn = QPushButton("准备小美丽大脑（Qwen3-8B Q4_K_M，模型约 5.03 GB）")
        self.brain_prepare_btn.setEnabled(not self.brain_service.ready())
        self.brain_prepare_btn.clicked.connect(self._prepare_brain)
        bf.addRow(self.brain_prepare_btn)

        self.brain_chat = QListWidget(); self.brain_chat.setWordWrap(True); self.brain_chat.setMinimumHeight(170)
        bf.addRow("对话", self.brain_chat)

        ask_row = QWidget(); ask_l = QHBoxLayout(ask_row); ask_l.setContentsMargins(0,0,0,0)
        self.brain_input = QLineEdit(); self.brain_input.setPlaceholderText("例如：美丽，你觉得我今天枪法怎么样？")
        self.brain_input.returnPressed.connect(self._brain_ask)
        self.brain_send_btn = QPushButton("发送")
        self.brain_send_btn.clicked.connect(self._brain_ask)
        ask_l.addWidget(self.brain_input,1); ask_l.addWidget(self.brain_send_btn)
        bf.addRow("和美丽说话", ask_row)

        controls = QWidget(); controls_l = QHBoxLayout(controls); controls_l.setContentsMargins(0,0,0,0)
        self.brain_auto_speak = QCheckBox("回答后自动说出来")
        self.brain_auto_speak.setChecked(bool(cfg.get("brain",{}).get("auto_speak", True)))
        clear_chat = QPushButton("清空上下文"); clear_chat.clicked.connect(self._brain_clear_history)
        controls_l.addWidget(self.brain_auto_speak); controls_l.addStretch(1); controls_l.addWidget(clear_chat)
        bf.addRow(controls)

        tune = QWidget(); tune_l = QHBoxLayout(tune); tune_l.setContentsMargins(0,0,0,0)
        self.brain_temp = QDoubleSpinBox(); self.brain_temp.setRange(0.20,1.20); self.brain_temp.setSingleStep(0.05); self.brain_temp.setDecimals(2)
        self.brain_temp.setValue(float(cfg.get("brain",{}).get("temperature",0.78)))
        self.brain_context = QSpinBox(); self.brain_context.setRange(2,12); self.brain_context.setValue(int(cfg.get("brain",{}).get("context_turns",6)))
        tune_l.addWidget(QLabel("随机度")); tune_l.addWidget(self.brain_temp); tune_l.addSpacing(12)
        tune_l.addWidget(QLabel("记住最近")); tune_l.addWidget(self.brain_context); tune_l.addWidget(QLabel("轮"))
        tune_l.addStretch(1)
        bf.addRow("聊天参数", tune)

        feedback_row = QWidget(); feedback_l = QHBoxLayout(feedback_row); feedback_l.setContentsMargins(0,0,0,0)
        self.brain_like_btn = QPushButton("👍 这句像小美丽"); self.brain_dislike_btn = QPushButton("👎 我来纠正")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_like_btn.clicked.connect(self._brain_like); self.brain_dislike_btn.clicked.connect(self._brain_dislike)
        self.brain_feedback_label = QLabel(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        feedback_l.addWidget(self.brain_like_btn); feedback_l.addWidget(self.brain_dislike_btn)
        feedback_l.addStretch(1); feedback_l.addWidget(self.brain_feedback_label)
        bf.addRow("养成", feedback_row)
        bv.addWidget(bbox)

        pbox = QGroupBox("小美丽人格卡"); pv = QVBoxLayout(pbox)
        self.brain_persona = QTextEdit(); self.brain_persona.setMaximumHeight(135)
        self.brain_persona.setPlainText(str(cfg.get("brain",{}).get("persona") or DEFAULT_PERSONA))
        pv.addWidget(self.brain_persona)
        persona_buttons = QHBoxLayout()
        save_persona = QPushButton("保存人格卡"); save_persona.clicked.connect(self._brain_save_persona)
        reset_persona = QPushButton("恢复默认人格"); reset_persona.clicked.connect(self._brain_reset_persona)
        persona_buttons.addWidget(save_persona); persona_buttons.addWidget(reset_persona); persona_buttons.addStretch(1)
        pv.addLayout(persona_buttons); bv.addWidget(pbox)

        bnote = QLabel(
            "现在的👍/👎不是重新训练模型，而是在本地记录“主人喜欢/纠正的答案”，之后相似问题会作为示例喂给小美丽。"
            "等积累到足够多的高质量样本后，再考虑 LoRA 微调。所有聊天样本都只保存在本机 XiaoMeiliData/brain。"
        )
        bnote.setWordWrap(True); bv.addWidget(bnote); bv.addStretch(1)
        self.tabs.addTab(bp, f"大脑 V{APP_VERSION}")

        self.brain_service.setup_progress.connect(self._brain_setup_progress)
        self.brain_service.setup_finished.connect(self._brain_setup_finished)
        self.brain_service.status_changed.connect(self.brain_status.setText)
        self.brain_service.generation_started.connect(self._brain_generation_started)
        self.brain_service.generation_finished.connect(self._brain_generation_finished)

'''
    if anchor not in s:
        raise RuntimeError("updates anchor not found")
    s = s.replace(anchor, brain_ui + anchor, 1)

    # Brain methods are inserted before voice handlers.
    method_anchor = '    def _prepare_voice_components(self):\n'
    methods = '''    def _prepare_brain(self):
        self.brain_prepare_btn.setEnabled(False)
        self.brain_status.setText("正在准备本地大脑…")
        self.brain_service.start_setup()

    def _brain_setup_progress(self, value, text):
        self.brain_progress.setValue(max(0,min(100,int(value))))
        self.brain_status.setText(str(text))

    def _brain_setup_finished(self, ok, message):
        self.brain_status.setText(str(message))
        self.brain_prepare_btn.setEnabled(not ok)
        if ok:
            self.brain_progress.setValue(100)
            self.brain_send_btn.setEnabled(True)

    def _brain_save_settings(self):
        if not isinstance(self.cfg.get("brain"), dict):
            self.cfg["brain"] = {}
        self.cfg["brain"]["auto_speak"] = bool(self.brain_auto_speak.isChecked())
        self.cfg["brain"]["temperature"] = float(self.brain_temp.value())
        self.cfg["brain"]["context_turns"] = int(self.brain_context.value())
        self.cfg["brain"]["persona"] = self.brain_persona.toPlainText().strip() or DEFAULT_PERSONA
        save_config(self.cfg)

    def _brain_save_persona(self):
        self._brain_save_settings()
        self.brain_status.setText("人格卡已保存。下一次回答立即生效。")

    def _brain_reset_persona(self):
        self.brain_persona.setPlainText(DEFAULT_PERSONA)
        self._brain_save_settings()
        self.brain_status.setText("已恢复默认小美丽人格。")

    def _brain_ask(self):
        text = self.brain_input.text().strip()
        if not text:
            return
        self._brain_save_settings()
        self.brain_chat.addItem(f"你：{text}")
        self.brain_chat.scrollToBottom()
        self.brain_input.clear()
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)
        self.brain_service.ask(
            text,
            self.cfg["brain"].get("persona") or DEFAULT_PERSONA,
            self.cfg["brain"].get("temperature",0.78),
            self.cfg["brain"].get("max_tokens",220),
            self.cfg["brain"].get("context_turns",6),
        )

    def _brain_generation_started(self):
        self.brain_send_btn.setEnabled(False)
        self.brain_status.setText("小美丽正在想…")

    def _brain_generation_finished(self, ok, answer, message):
        self.brain_send_btn.setEnabled(True)
        self.brain_status.setText(str(message))
        if not ok:
            self.brain_chat.addItem(f"系统：{message}")
            self.brain_chat.scrollToBottom()
            return
        spoken = str(answer.get("spoken_text") or "").strip()
        board = str(answer.get("board_text") or "").strip()
        emotion = str(answer.get("emotion") or "neutral")
        self.brain_chat.addItem(f"小美丽：{spoken}")
        self.brain_chat.addItem(f"〔白板草稿｜{emotion}〕{board.replace(chr(10),' / ')}")
        self.brain_chat.scrollToBottom()
        self.brain_like_btn.setEnabled(True); self.brain_dislike_btn.setEnabled(True)
        if self.brain_auto_speak.isChecked():
            voice = self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
            vid = str(voice.get("voice_id") or "")
            if vid:
                try:
                    self.voice_service.preview(
                        spoken, vid, float(voice.get("speed",1.0) or 1.0),
                        str(voice.get("output_device","default") or "default")
                    )
                except Exception:
                    LOGGER.exception("大脑回答自动朗读失败")

    def _brain_like(self):
        ex = self.brain_service.last_exchange()
        if not ex:
            return
        self.brain_service.save_feedback("up", ex.get("user_text",""), ex.get("assistant_text",""))
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        self.brain_status.setText("记住了：这句像小美丽。")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)

    def _brain_dislike(self):
        ex = self.brain_service.last_exchange()
        if not ex:
            return
        desired, ok = QInputDialog.getMultiLineText(
            self,
            "纠正小美丽",
            "这句话你希望小美丽怎么回答？\n我会把它保存成养成样本，后面相似问题会优先模仿：",
            str(ex.get("assistant_text") or ""),
        )
        if not ok:
            return
        desired = str(desired or "").strip()
        if not desired:
            return
        self.brain_service.save_feedback("down", ex.get("user_text",""), ex.get("assistant_text",""), desired)
        self.brain_feedback_label.setText(f"已积累 {self.brain_service.feedback_count()} 条养成样本")
        self.brain_chat.addItem(f"你教她：{desired}")
        self.brain_chat.scrollToBottom()
        self.brain_status.setText("纠正已记住。下次相似语境会优先参考。")
        self.brain_like_btn.setEnabled(False); self.brain_dislike_btn.setEnabled(False)

    def _brain_clear_history(self):
        self.brain_service.clear_history()
        self.brain_chat.clear()
        self.brain_status.setText("当前聊天上下文已清空；人格卡和养成样本仍然保留。")

'''
    if method_anchor not in s:
        raise RuntimeError("voice method anchor not found")
    s = s.replace(method_anchor, methods + method_anchor, 1)

    # App controller owns one persistent brain process.
    s = must(
        s,
        '        self.voice_service=VoiceService()\n        self.update_service=UpdateService(cfg)',
        '        self.voice_service=VoiceService()\n        self.brain_service=BrainService()\n        self.update_service=UpdateService(cfg)',
        "brain service controller",
    )
    s = must(
        s,
        'self.settings=SettingsDialog(self.cfg,self.pet,self.vision,self.voice_service,self.update_service)',
        'self.settings=SettingsDialog(self.cfg,self.pet,self.vision,self.voice_service,self.brain_service,self.update_service)',
        "settings pass brain",
    )

    # Shutdown both local AI workers on exit. Match the post-v0.6.2.1 shutdown sequence.
    voice_shutdown = '''            try: self.voice_service.shutdown()
            except Exception: pass
            LOGGER.info("正常退出")'''
    voice_and_brain = '''            try: self.voice_service.shutdown()
            except Exception: pass
            try: self.brain_service.shutdown()
            except Exception: pass
            LOGGER.info("正常退出")'''
    if voice_shutdown in s:
        s = s.replace(voice_shutdown, voice_and_brain, 1)
    else:
        # Defensive fallback for builds where voice shutdown is formatted on one line.
        s = must(
            s,
            '            LOGGER.info("正常退出")',
            '            try: self.brain_service.shutdown()\n            except Exception: pass\n            LOGGER.info("正常退出")',
            "brain shutdown",
        )

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_dst), doraise=True)
    print("Patched XiaoMeili source to V0.7.0")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v070.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
