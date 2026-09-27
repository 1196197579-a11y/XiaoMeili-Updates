# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import sys
from pathlib import Path


def once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"V0.8.7 expected one {label}, found {n}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    root = Path(source_root).resolve()
    main = root / "app" / "src" / "main.py"
    voice = root / "app" / "src" / "voice_qwen.py"
    if not main.exists() or not voice.exists():
        raise FileNotFoundError("V0.8.7 expected V0.8.6 source")

    m = main.read_text(encoding="utf-8")
    v = voice.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.6"' not in m:
        raise RuntimeError("V0.8.7 expected APP_VERSION 0.8.6 base")

    m = m.replace('APP_VERSION = "0.8.6"', 'APP_VERSION = "0.8.7"', 1)
    m = m.replace("V0.8.6", "V0.8.7")
    v = v.replace("V0.8.6", "V0.8.7")

    # ------------------------------------------------------------------
    # 1) Talking whiteboard: preserve the audience hold, but keep the
    # supplied 15-second talking animation moving the whole time.
    # ------------------------------------------------------------------
    m = once(
        m,
        '''        if hold_ms is None:
            hold_ms = 120
        QTimer.singleShot(max(60, int(hold_ms)), lambda g=generation: self._end_dialogue_board(g))
''',
        '''        if hold_ms is None:
            hold_ms = int(self.cfg.get("whiteboard", {}).get("hold_ms", 3000))
        QTimer.singleShot(max(300, int(hold_ms)), lambda g=generation: self._end_dialogue_board(g))
''',
        "dynamic whiteboard configured hold",
    )

    m = once(
        m,
        '''        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(120)
''',
        '''        if bool(self._speech_cfg().get("whiteboard_enabled",True)):
            self.pet.finish_dialogue_board(int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))
''',
        "live whiteboard configured hold",
    )

    m = m.replace(
        "form.addRow('预览停留',self.hold)",
        "form.addRow('说完后动态停留',self.hold)",
    )
    m = m.replace(
        "文字会跟随 TTS 播报逐步出现；实时语音结束后白板立即收起，不冻结画面。15 秒素材不足时会自动循环。",
        "文字会跟随 TTS 播报逐步出现；说完后白板继续保持动态并停留设定时间，默认 3 秒。15 秒素材不足时会自动循环，整个过程不冻结画面。",
    )

    # ------------------------------------------------------------------
    # 2) Phrase voice override editor.
    # V0.8.6 already adds the generic data path. V0.8.7 makes it usable
    # from the normal Voice settings page and adds one-click preview.
    # ------------------------------------------------------------------
    summary_anchor = '''        if hasattr(self, "v080_wake_value"):
            replies=self.cfg.get("speech",{}).get("wake_replies",[]) if isinstance(self.cfg.get("speech"),dict) else []
            self.v080_wake_value.setText(f"{len(replies)} 条 · 随机不连续重复")
'''
    summary_new = summary_anchor + '''        if hasattr(self, "v087_phrase_value"):
            rules=self.cfg.get("speech",{}).get("phrase_voice_overrides",{}) if isinstance(self.cfg.get("speech"),dict) else {}
            count=len(rules) if isinstance(rules,dict) else 0
            self.v087_phrase_value.setText(f"{count} 条 · 完全匹配台词")
'''
    m = once(m, summary_anchor, summary_new, "phrase override summary")

    wake_method_end = '''        save.clicked.connect(commit); dlg.exec()

    def _v080_open_whiteboard_template(self):
'''
    phrase_editor = '''        save.clicked.connect(commit); dlg.exec()

    def _v087_open_phrase_voice_overrides(self):
        dlg=QDialog(self); dlg.setWindowTitle("小美丽｜单句语气微调"); dlg.setWindowIcon(QIcon(resource('assets/xiaomeili_icon.png'))); dlg.resize(860,560)
        root=QVBoxLayout(dlg)
        title=QLabel("单句语气微调"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("只对完全匹配的台词追加一条声音要求。匹配时会忽略空格和常见标点，不会改变小美丽的全局固定声线。适合修正“干嘛”这类特别短、偶尔年龄感漂移的句子。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)

        table=QTableWidget(0,2); table.setHorizontalHeaderLabels(["台词","附加声音要求"])
        table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False); table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(table,1)

        rules=self.cfg.get('speech',{}).get('phrase_voice_overrides',{})
        if not isinstance(rules,dict): rules={}
        def add_row(phrase="", instruct=""):
            row=table.rowCount(); table.insertRow(row)
            table.setItem(row,0,QTableWidgetItem(str(phrase or "")))
            table.setItem(row,1,QTableWidgetItem(str(instruct or "")))
            table.setRowHeight(row,54)
        for phrase,instruct in rules.items():
            add_row(phrase,instruct)

        buttons=QHBoxLayout()
        add=QPushButton("添加台词"); delete=QPushButton("删除选中"); preview=QPushButton("试听选中")
        buttons.addWidget(add); buttons.addWidget(delete); buttons.addWidget(preview); buttons.addStretch(1); root.addLayout(buttons)
        def add_one():
            add_row("","")
            table.setCurrentCell(table.rowCount()-1,0); table.editItem(table.item(table.rowCount()-1,0))
        def del_one():
            rows=sorted({idx.row() for idx in table.selectionModel().selectedRows()},reverse=True)
            for row in rows: table.removeRow(row)
        def preview_one():
            row=table.currentRow()
            if row<0: return
            p=table.item(row,0).text().strip() if table.item(row,0) else ""
            ins=table.item(row,1).text().strip() if table.item(row,1) else ""
            if not p:
                QMessageBox.information(dlg,"单句语气微调","请先填写要试听的台词。"); return
            voice=self.cfg.get('voice',{}) if isinstance(self.cfg.get('voice'),dict) else {}
            vid=str(voice.get('voice_id') or "")
            if not vid or not self.voice_service.ready():
                QMessageBox.information(dlg,"单句语气微调","请先在“小美丽声音”中固定一个可用声线。"); return
            self.voice_service.preview(
                p, vid, float(voice.get('speed',1.0) or 1.0),
                str(voice.get('output_device','default') or 'default'),
                extra_instruct=ins,
            )
        add.clicked.connect(add_one); delete.clicked.connect(del_one); preview.clicked.connect(preview_one)

        bottom=QHBoxLayout(); bottom.addStretch(1)
        cancel=QPushButton("取消"); save=QPushButton("保存并应用")
        bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom); cancel.clicked.connect(dlg.reject)
        def commit():
            out={}
            for row in range(table.rowCount()):
                phrase=table.item(row,0).text().strip() if table.item(row,0) else ""
                instruct=table.item(row,1).text().strip() if table.item(row,1) else ""
                if not phrase and not instruct: continue
                if not phrase or not instruct:
                    QMessageBox.warning(dlg,"无法保存",f"第 {row+1} 行需要同时填写台词和声音要求。"); return
                out[phrase[:40]]=instruct[:400]
                if len(out)>=20: break
            self.cfg.setdefault('speech',{})['phrase_voice_overrides']=out
            save_config(self.cfg); self.config_changed.emit(); self._v080_refresh_speech_summary()
            dlg.accept()
        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()

    def _v080_open_whiteboard_template(self):
'''
    m = once(m, wake_method_end, phrase_editor, "phrase override editor")

    voice_card_anchor = '''        card, self.v774_voice_value = self._v774_card(
            "小美丽声音", "", "选择固定中文声线、语速并试听。", "选择与试听", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        self.v774_auto_speak_cb = QCheckBox("开启")
'''
    voice_card_new = '''        card, self.v774_voice_value = self._v774_card(
            "小美丽声音", "", "选择固定中文声线、语速并试听。", "选择与试听", self._v774_open_voice_editor
        )
        voice_cards.append(card)

        card, self.v087_phrase_value = self._v774_card(
            "单句语气微调", "", "只修正指定台词的年龄感、语气或说话方式，不改变全局声线。", "管理", self._v087_open_phrase_voice_overrides
        )
        voice_cards.append(card)

        self.v774_auto_speak_cb = QCheckBox("开启")
'''
    m = once(m, voice_card_anchor, voice_card_new, "phrase override voice card")

    # ------------------------------------------------------------------
    # 3) VoiceService correctness + preview support.
    # V0.8.6 introduced optional extra_instruct, but its nested speak()
    # worker accidentally shadowed the closure variable. Fix that before
    # publishing the feature.
    # ------------------------------------------------------------------
    speak_head_old = '''    def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue", extra_instruct=""):
        text = str(text or "").strip()
        voice_id = str(voice_id or "").strip()
        tag = str(tag or "dialogue")
        if not text:
'''
    speak_head_new = '''    def speak(self, text, voice_id, speed=1.0, output_device="default", tag="dialogue", extra_instruct=""):
        text = str(text or "").strip()
        voice_id = str(voice_id or "").strip()
        tag = str(tag or "dialogue")
        phrase_instruct = str(extra_instruct or "").strip()
        if not text:
'''
    v = once(v, speak_head_old, speak_head_new, "speak closure normalization")

    v = once(
        v,
        '''                extra_instruct = str(extra_instruct or "").strip()
                out = self._speech_cache_path(text, voice_id, speed, extra_instruct)
                if not out.exists() or out.stat().st_size < 256:
                    self._synthesize_to(text, voice_id, speed, out, extra_instruct)
''',
        '''                out = self._speech_cache_path(text, voice_id, speed, phrase_instruct)
                if not out.exists() or out.stat().st_size < 256:
                    self._synthesize_to(text, voice_id, speed, out, phrase_instruct)
''',
        "speak closure use",
    )

    preview_sig_old = '''    def preview(self, text, voice_id, speed=1.0, output_device="default"):
'''
    preview_sig_new = '''    def preview(self, text, voice_id, speed=1.0, output_device="default", extra_instruct=""):
'''
    v = once(v, preview_sig_old, preview_sig_new, "preview extra instruction signature")

    preview_req_old = '''                    "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed),
                    "output": str(out),
'''
    preview_req_new = '''                    "instruct": str(preset.get("instruct") or "") + self._speed_instruction(speed) + (" " + str(extra_instruct).strip() if str(extra_instruct or "").strip() else ""),
                    "output": str(out),
'''
    # One occurrence remains in preview because _synthesize_to was already
    # changed by V0.8.6.
    v = once(v, preview_req_old, preview_req_new, "preview extra instruction request")

    main.write_text(m, encoding="utf-8")
    voice.write_text(v, encoding="utf-8")
    py_compile.compile(str(main), doraise=True)
    py_compile.compile(str(voice), doraise=True)

    mm = main.read_text(encoding="utf-8")
    vv = voice.read_text(encoding="utf-8")
    for token in (
        'APP_VERSION = "0.8.7"',
        'def _arm_speech_followup(self):',
        'self.pet.finish_dialogue_board(int(self.cfg.get("whiteboard",{}).get("hold_ms",3000)))',
        'def _v087_open_phrase_voice_overrides(self):',
        '"单句语气微调"',
        'self.voice_service.preview(',
    ):
        if token not in mm:
            raise RuntimeError("V0.8.7 main check failed: " + token)
    for token in (
        'phrase_instruct = str(extra_instruct or "").strip()',
        'def preview(self, text, voice_id, speed=1.0, output_device="default", extra_instruct=""):',
        'out = self._speech_cache_path(text, voice_id, speed, phrase_instruct)',
    ):
        if token not in vv:
            raise RuntimeError("V0.8.7 voice check failed: " + token)

    board_block = mm[mm.find("def finish_dialogue_board"):mm.find("def _end_dialogue_board")]
    if "setPaused(True)" in board_block:
        raise RuntimeError("V0.8.7 dialogue board still freezes")
    if "hold_ms = 120" in board_block:
        raise RuntimeError("V0.8.7 dialogue board still uses 120 ms hold")
    if "extra_instruct = str(extra_instruct or \"\").strip()" in vv[vv.find("def speak("):vv.find("def preview(")]:
        raise RuntimeError("V0.8.7 speak closure shadow bug still present")

    print("Patched XiaoMeili source to V0.8.7 dynamic hold + continuous dialogue + phrase voice editor")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v087.py <source_root>")
    patch(Path(sys.argv[1]))
