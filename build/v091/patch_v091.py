# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.9.1 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.9.1 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


def patch_main(path: Path):
    s = path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.9.0"' not in s:
        raise RuntimeError("V0.9.1 expected APP_VERSION 0.9.0 base")
    s = s.replace('APP_VERSION = "0.9.0"', 'APP_VERSION = "0.9.1"', 1)
    s = s.replace("V0.9.0｜", "V0.9.1｜", 1)

    # ------------------------------------------------------------------
    # 1) Settings UI proportional scaling + scroll safety.
    #    Theme CSS is scaled instead of the pet/global QApplication, so only
    #    the Settings center changes size.
    # ------------------------------------------------------------------
    theme_old = '        self.setStyleSheet(self._v0775_stylesheet(dark))\n'
    theme_new = '''        _css=self._v0775_stylesheet(dark)
        self.setStyleSheet(self._v091_scale_css(_css, float(getattr(self,"_v091_ui_scale",1.0) or 1.0)))
'''
    if theme_old not in s:
        raise RuntimeError("V0.9.1 theme stylesheet anchor missing")
    s = s.replace(theme_old, theme_new, 1)

    # Wrap the top-level page stack so an unusually tall System page can never
    # force the whole native window past the Windows work area.
    stack_old = '''        self.v774_stack = QStackedWidget()
        shell_l.addWidget(sidebar)
        shell_l.addWidget(self.v774_stack, 1)
'''
    stack_new = '''        self.v774_stack = QStackedWidget()
        self.v091_stack_scroll = QScrollArea()
        self.v091_stack_scroll.setObjectName("settingsMainScroll")
        self.v091_stack_scroll.setWidgetResizable(True)
        self.v091_stack_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.v091_stack_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.v091_stack_scroll.setStyleSheet("QScrollArea#settingsMainScroll{background:transparent;border:none;} QScrollArea#settingsMainScroll>QWidget>QWidget{background:transparent;}")
        self.v091_stack_scroll.setWidget(self.v774_stack)
        shell_l.addWidget(sidebar)
        shell_l.addWidget(self.v091_stack_scroll, 1)
'''
    if stack_old not in s:
        raise RuntimeError("V0.9.1 settings stack anchor missing")
    s = s.replace(stack_old, stack_new, 1)

    # Add the user-facing scale selector immediately after Nickname.
    general_anchor = '''        cards.append(name_card)

        self.v774_startup_cb = QCheckBox("开机启动")
'''
    general_new = '''        cards.append(name_card)

        self.v091_scale_combo = QComboBox()
        self.v091_scale_combo.addItem("自动（推荐）", "auto")
        self.v091_scale_combo.addItem("80%", "0.80")
        self.v091_scale_combo.addItem("90%", "0.90")
        self.v091_scale_combo.addItem("100%", "1.00")
        self.v091_scale_combo.addItem("110%", "1.10")
        _scale_mode=str(self.cfg.get("settings_ui",{}).get("ui_scale_mode","auto") or "auto")
        _scale_idx=self.v091_scale_combo.findData(_scale_mode)
        self.v091_scale_combo.setCurrentIndex(_scale_idx if _scale_idx>=0 else 0)
        self.v091_scale_combo.currentIndexChanged.connect(self._v091_scale_changed)
        card, _ = self._v774_card(
            "界面缩放",
            "只缩放设置中心，不影响桌面上的小美丽",
            "自动模式会根据当前显示器可用工作区等比例缩放；空间不足时仍可滚动。",
            control=self.v091_scale_combo,
        )
        cards.append(card)

        self.v774_startup_cb = QCheckBox("开机启动")
'''
    if general_anchor not in s:
        raise RuntimeError("V0.9.1 General scale card anchor missing")
    s = s.replace(general_anchor, general_new, 1)

    # Install scale methods before the old shell installer.
    install_anchor = "    def _install_v0774_shell(self, root):\n"
    if install_anchor not in s:
        raise RuntimeError("V0.9.1 shell installer anchor missing")
    scale_methods = r'''    def _v091_scale_css(self, css, scale):
        scale=max(0.72,min(1.15,float(scale or 1.0)))
        def repl(match):
            value=float(match.group(1))
            scaled=max(1.0,value*scale)
            if abs(scaled-round(scaled))<0.05:
                return f"{int(round(scaled))}px"
            return f"{scaled:.1f}px"
        return re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)px\b", repl, str(css or ""))

    def _v091_auto_scale(self):
        try:
            screen=self.screen() or QApplication.primaryScreen()
            if screen is None:
                return 1.0
            area=screen.availableGeometry()
            # Leave breathing room for the title bar, taskbar and window shadow.
            sx=max(0.1,(float(area.width())-36.0)/1080.0)
            sy=max(0.1,(float(area.height())-36.0)/720.0)
            return max(0.75,min(1.0,sx,sy))
        except Exception:
            return 0.90

    def _v091_capture_fixed_baselines(self):
        if getattr(self,"_v091_baselines_captured",False):
            return
        self._v091_baselines_captured=True
        for widget in self.findChildren(QWidget):
            try:
                widget.setProperty("_v091_min_w",int(widget.minimumWidth()))
                widget.setProperty("_v091_min_h",int(widget.minimumHeight()))
                widget.setProperty("_v091_max_w",int(widget.maximumWidth()))
                widget.setProperty("_v091_max_h",int(widget.maximumHeight()))
            except Exception:
                pass

    def _v091_apply_widget_scale(self, scale):
        self._v091_capture_fixed_baselines()
        huge=1000000
        for widget in self.findChildren(QWidget):
            try:
                min_w=int(widget.property("_v091_min_w") or 0)
                min_h=int(widget.property("_v091_min_h") or 0)
                max_w=int(widget.property("_v091_max_w") or 16777215)
                max_h=int(widget.property("_v091_max_h") or 16777215)
                widget.setMinimumWidth(max(0,int(round(min_w*scale))) if min_w>0 else 0)
                widget.setMinimumHeight(max(0,int(round(min_h*scale))) if min_h>0 else 0)
                if 0<max_w<huge:
                    widget.setMaximumWidth(max(1,int(round(max_w*scale))))
                if 0<max_h<huge:
                    widget.setMaximumHeight(max(1,int(round(max_h*scale))))
            except Exception:
                pass

    def _v091_resolve_scale(self):
        mode="auto"
        if hasattr(self,"v091_scale_combo"):
            mode=str(self.v091_scale_combo.currentData() or "auto")
        else:
            mode=str(self.cfg.get("settings_ui",{}).get("ui_scale_mode","auto") or "auto")
        if mode=="auto":
            return self._v091_auto_scale()
        try:
            return max(0.72,min(1.15,float(mode)))
        except Exception:
            return self._v091_auto_scale()

    def _v091_apply_settings_scale(self, persist=False):
        scale=self._v091_resolve_scale()
        self._v091_ui_scale=float(scale)
        self._v091_apply_widget_scale(scale)

        # Rebuild the current theme through the scale-aware stylesheet hook.
        try:
            self._v0775_apply_theme(getattr(self,"_v0775_theme_mode","light"),False)
        except Exception:
            pass

        try:
            screen=self.screen() or QApplication.primaryScreen()
            area=screen.availableGeometry() if screen is not None else None
            target_w=max(760,int(round(1080*scale)))
            target_h=max(520,int(round(720*scale)))
            if area is not None:
                target_w=min(target_w,max(680,int(area.width())-20))
                target_h=min(target_h,max(480,int(area.height())-20))
            self.setMinimumSize(min(760,target_w),min(500,target_h))
            self.resize(target_w,target_h)
        except Exception:
            pass

        try:
            self._v0775_place_theme_button()
        except Exception:
            pass

        if persist:
            ui=self.cfg.setdefault("settings_ui",{})
            ui["ui_scale_mode"]=str(self.v091_scale_combo.currentData() or "auto")
            save_config(self.cfg)

    def _v091_scale_changed(self, *args):
        self._v091_apply_settings_scale(True)

'''
    s = s.replace(install_anchor, scale_methods + install_anchor, 1)

    # Apply after the shell/theme layers have been built. Later UI patches may
    # insert lines between theme installation and the first-run notice, so use
    # the stable notice call as the anchor instead of requiring adjacency.
    scale_notice = '        QTimer.singleShot(350, self._v774_first_run_notice)\n'
    if scale_notice not in s:
        raise RuntimeError("V0.9.1 first-run notice anchor missing")
    s = s.replace(
        scale_notice,
        '        QTimer.singleShot(0, lambda: self._v091_apply_settings_scale(False))\n' + scale_notice,
        1,
    )

    # ------------------------------------------------------------------
    # 2) Highlight UI: preview controls + clearer state presentation.
    # ------------------------------------------------------------------
    phrase_anchor = '''        self.highlight_phrases.setPlainText("\\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        self.highlight_status=QLabel("当前回合：等待识别")
        self.highlight_status.setWordWrap(True)
        hf.addRow("实时状态",self.highlight_status)
'''
    phrase_new = '''        self.highlight_phrases.setPlainText("\\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        preview_row=QWidget()
        preview_l=QHBoxLayout(preview_row)
        preview_l.setContentsMargins(0,0,0,0)
        preview_l.setSpacing(8)
        self.highlight_preview_random_btn=QPushButton("▶ 随机预览高光")
        self.highlight_preview_next_btn=QPushButton("逐句试听下一句")
        self.highlight_preview_board_btn=QPushButton("仅预览白板")
        self.highlight_preview_random_btn.clicked.connect(lambda: self._v091_preview_highlight("random"))
        self.highlight_preview_next_btn.clicked.connect(lambda: self._v091_preview_highlight("next"))
        self.highlight_preview_board_btn.clicked.connect(lambda: self._v091_preview_highlight("board"))
        preview_l.addWidget(self.highlight_preview_random_btn)
        preview_l.addWidget(self.highlight_preview_next_btn)
        preview_l.addWidget(self.highlight_preview_board_btn)
        preview_l.addStretch(1)
        hf.addRow("预览",preview_row)

        self.highlight_status=QLabel(
            "本人击杀：0  |  敌方存活：?/5  |  存活：未确认\\n"
            "最后一杀：非本人\\n最近判定：等待"
        )
        self.highlight_status.setWordWrap(True)
        hf.addRow("实时状态",self.highlight_status)

        self.highlight_qualification=QLabel("高光资格：未满足")
        self.highlight_qualification.setObjectName("highlightQualification")
        self.highlight_qualification.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.highlight_qualification.setMinimumHeight(54)
        self.highlight_qualification.setStyleSheet(
            "QLabel#highlightQualification{background:#FDE8E8;color:#B42318;"
            "border:1px solid #F4B4B4;border-radius:10px;padding:10px 14px;"
            "font-size:20px;font-weight:900;}"
        )
        hf.addRow(self.highlight_qualification)
'''
    if phrase_anchor not in s:
        raise RuntimeError("V0.9.1 highlight phrase/status UI anchor missing")
    s = s.replace(phrase_anchor, phrase_new, 1)

    # Preview methods live in SettingsDialog near the shell methods.
    preview_anchor = "    def _v091_scale_css(self, css, scale):\n"
    preview_methods = r'''    def _v091_editor_highlight_phrases(self):
        if hasattr(self,"highlight_phrases"):
            values=[x.strip() for x in self.highlight_phrases.toPlainText().splitlines() if x.strip()]
        else:
            values=[]
        return values or ["愣着干嘛，点点关注呀！"]

    def _v091_preview_pick(self, mode):
        values=self._v091_editor_highlight_phrases()
        key=tuple(values)
        if getattr(self,"_v091_preview_key",None)!=key:
            self._v091_preview_key=key
            self._v091_preview_bag=[]
            self._v091_preview_index=0

        if mode=="next":
            idx=int(getattr(self,"_v091_preview_index",0)) % len(values)
            self._v091_preview_index=idx+1
            return values[idx]

        bag=list(getattr(self,"_v091_preview_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_v091_preview_last","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        phrase=bag.pop(0)
        self._v091_preview_bag=bag
        self._v091_preview_last=phrase
        return phrase

    def _v091_preview_highlight(self, mode="random"):
        board=(
            self.highlight_board_text.text().strip()
            if hasattr(self,"highlight_board_text") else ""
        ) or "愣着干嘛，点点关注呀！"

        if mode=="board":
            try:
                self.pet.preview_dialogue(board,4200)
            except Exception as exc:
                QMessageBox.warning(self,"高光预览",f"白板预览失败：{type(exc).__name__}: {exc}")
            return

        phrase=self._v091_preview_pick("next" if mode=="next" else "random")
        voice=self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
        vid=str(voice.get("voice_id") or "").strip()
        if not vid or not self.voice_service.ready():
            try:
                self.pet.preview_dialogue(board,4200)
            except Exception:
                pass
            QMessageBox.information(self,"高光预览","声音组件或固定声线尚未就绪，本次只预览白板。")
            return

        # Preview uses the same highlight tag, so AppController drives the real
        # whiteboard/TTS path instead of a fake settings-only animation.
        for method_name in ("stop_playback","stop_audio","cancel_playback"):
            try:
                method=getattr(self.voice_service,method_name,None)
                if callable(method):
                    method()
                    break
            except Exception:
                pass
        try:
            self.voice_service.speak(
                phrase,
                vid,
                float(voice.get("speed",1.0) or 1.0),
                str(voice.get("output_device","default") or "default"),
                tag="highlight_cta",
                extra_instruct="",
            )
        except Exception as exc:
            LOGGER.exception("[HIGHLIGHT] preview failed")
            QMessageBox.warning(self,"高光预览",f"播放失败：{type(exc).__name__}: {exc}")

'''
    if preview_anchor not in s:
        raise RuntimeError("V0.9.1 preview insertion anchor missing")
    s = s.replace(preview_anchor, preview_methods + preview_anchor, 1)

    # Clear, user-requested state labels and a large red/green qualification bar.
    status_old = '''        if hasattr(self,"highlight_status"):
            self.highlight_status.setText(
                f"本人击杀：{data.get('round_self_kills',0)}  |  敌方存活：{data.get('enemy_alive','?')}/5  |  "
                f"主人：{'已死亡' if data.get('death_latched') else '存活/未确认'}\\n"
                f"最后一杀：{'✓ 本人' if data.get('self_final_kill_confirmed') else '等待/非本人'}  |  "
                f"高光资格：{'已满足击杀' if data.get('highlight_candidate') else '未满足'}\\n"
                f"最近判定：{data.get('highlight_reason','等待')}"
            )
'''
    status_new = '''        if hasattr(self,"highlight_status"):
            _dead=bool(data.get("death_latched"))
            _alive_state=data.get("alive_state")
            _alive_text="已死亡" if _dead else ("已确认" if _alive_state is True else "未确认")
            _final_text="是本人" if bool(data.get("self_final_kill_confirmed")) else "非本人"
            self.highlight_status.setText(
                f"本人击杀：{data.get('round_self_kills',0)}  |  敌方存活：{data.get('enemy_alive','?')}/5  |  "
                f"存活：{_alive_text}\\n"
                f"最后一杀：{_final_text}\\n"
                f"最近判定：{data.get('highlight_reason','等待')}"
            )
        if hasattr(self,"highlight_qualification"):
            _triggered=bool(data.get("highlight_triggered"))
            self.highlight_qualification.setText(
                "高光资格：已触发" if _triggered else "高光资格：未满足"
            )
            self.highlight_qualification.setStyleSheet(
                "QLabel#highlightQualification{"
                + (
                    "background:#E1F7EA;color:#147A45;border:1px solid #8AD5AA;"
                    if _triggered else
                    "background:#FDE8E8;color:#B42318;border:1px solid #F4B4B4;"
                )
                + "border-radius:10px;padding:10px 14px;font-size:20px;font-weight:900;}"
            )
'''
    if status_old not in s:
        raise RuntimeError("V0.9.1 highlight status update anchor missing")
    s = s.replace(status_old, status_new, 1)

    # ------------------------------------------------------------------
    # 3) Real shuffle-bag phrase selection for live triggers.
    #    Every phrase is used once per cycle before the bag is reshuffled.
    # ------------------------------------------------------------------
    pick_new = r'''    def _pick_highlight_phrase(self):
        values=self._highlight_phrases_list()
        key=tuple(values)
        if getattr(self,"_highlight_phrase_key",None)!=key:
            self._highlight_phrase_key=key
            self._highlight_phrase_bag=[]

        bag=list(getattr(self,"_highlight_phrase_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            if len(bag)>1 and bag[0]==self._highlight_last_phrase:
                bag[0],bag[1]=bag[1],bag[0]

        choice=bag.pop(0)
        self._highlight_phrase_bag=bag
        self._highlight_last_phrase=choice
        LOGGER.info(
            "[HIGHLIGHT] shuffle-bag pick | phrase=%s remaining=%s total=%s",
            choice,len(bag),len(values),
        )
        return choice

'''
    s = replace_method(s, "_pick_highlight_phrase", "_trigger_highlight_cta", pick_new, "highlight shuffle bag")

    # Existing controller state needs the bag attributes.
    ctrl_init_anchor = '''        self._highlight_seen_event_id=0
        self._highlight_active=False
        self._highlight_last_phrase=""
'''
    ctrl_init_new = '''        self._highlight_seen_event_id=0
        self._highlight_active=False
        self._highlight_last_phrase=""
        self._highlight_phrase_key=None
        self._highlight_phrase_bag=[]
'''
    if ctrl_init_anchor not in s:
        raise RuntimeError("V0.9.1 controller highlight init anchor missing")
    s = s.replace(ctrl_init_anchor, ctrl_init_new, 1)

    # Speech diagnostic version label.
    path.write_text(s, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def patch_speech(path: Path):
    s=path.read_text(encoding="utf-8")
    s=s.replace("小美丽 V0.9.0 语音诊断日志","小美丽 V0.9.1 语音诊断日志")
    path.write_text(s,encoding="utf-8")
    py_compile.compile(str(path),doraise=True)


def patch(source_root: Path):
    root=Path(source_root).resolve()
    main=root/"app"/"src"/"main.py"
    speech=root/"app"/"src"/"speech_input.py"
    if not main.exists(): raise FileNotFoundError(main)
    if not speech.exists(): raise FileNotFoundError(speech)

    patch_main(main)
    patch_speech(speech)

    m=main.read_text(encoding="utf-8")
    sp=speech.read_text(encoding="utf-8")
    checks=[
        'APP_VERSION = "0.9.1"',
        'def _v091_scale_css',
        'def _v091_apply_settings_scale',
        '自动（推荐）',
        'settingsMainScroll',
        '▶ 随机预览高光',
        '逐句试听下一句',
        '仅预览白板',
        '高光资格：未满足',
        '高光资格：已触发',
        '存活：{_alive_text}',
        '最后一杀：{_final_text}',
        'shuffle-bag pick',
        'self._highlight_phrase_bag',
    ]
    for token in checks:
        if token not in m:
            raise RuntimeError("V0.9.1 verification failed: "+token)
    if "小美丽 V0.9.1 语音诊断日志" not in sp:
        raise RuntimeError("V0.9.1 speech diagnostic version label missing")

    print("Patched XiaoMeili source to V0.9.1 settings-scale + highlight preview/status/shuffle-bag")


if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("usage: patch_v091.py <source_root>")
    patch(Path(sys.argv[1]))
