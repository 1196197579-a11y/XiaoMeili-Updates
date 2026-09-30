# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0925.py <source_root>")

root = Path(sys.argv[1]).resolve()
main = root / "app" / "src" / "main.py"
speech = root / "app" / "src" / "speech_input.py"
version_file = root / "app" / "assets" / "VERSION.txt"

s = main.read_text(encoding="utf-8")
if 'APP_VERSION = "0.9.2.4"' not in s:
    raise RuntimeError("V0.9.2.5 expected V0.9.2.4 base")
s = s.replace('APP_VERSION = "0.9.2.4"', 'APP_VERSION = "0.9.2.5"', 1)
s = s.replace('APP_NAME = "小美丽 V0.9.2.4｜Voice Interaction"', 'APP_NAME = "小美丽 V0.9.2.5｜Voice Interaction"', 1)
s = s.replace("自动存储清理已禁用：V0.9.2.4 不会自动删除任何文件。", "自动存储清理已禁用：V0.9.2.5 不会自动删除任何文件。", 1)

# ------------------------------------------------------------------
# 1) Highlight settings cleanup: remove the visible trigger-condition row.
#    Runtime eligibility logic is intentionally untouched.
# ------------------------------------------------------------------
trigger_row = '''        conditions=QLabel("✓ 本回合本人击杀达到阈值   ✓ 本人完成敌方最后一杀   ✓ 本人存活   ✓ 本回合获胜")
        conditions.setWordWrap(True)
        hf.addRow("触发条件",conditions)

'''
if trigger_row not in s:
    raise RuntimeError("V0.9.2.5 trigger-condition UI row anchor missing")
s = s.replace(trigger_row, "", 1)

# ------------------------------------------------------------------
# 2) All Settings QCheckBox controls use one green Windows-style switch.
#    This is a pure visual theme change; control semantics are unchanged.
# ------------------------------------------------------------------
asset_dir = root / "app" / "assets" / "v0925"
asset_dir.mkdir(parents=True, exist_ok=True)

toggle_on = """<svg xmlns="http://www.w3.org/2000/svg" width="38" height="22" viewBox="0 0 38 22">
  <rect x="0.75" y="0.75" width="36.5" height="20.5" rx="10.25" fill="#36C4A2" stroke="#2DAF8E" stroke-width="1.5"/>
  <circle cx="27" cy="11" r="8" fill="#FFFFFF"/>
</svg>
"""
toggle_off_light = """<svg xmlns="http://www.w3.org/2000/svg" width="38" height="22" viewBox="0 0 38 22">
  <rect x="0.75" y="0.75" width="36.5" height="20.5" rx="10.25" fill="#DCE6E2" stroke="#C7D5D0" stroke-width="1.5"/>
  <circle cx="11" cy="11" r="8" fill="#FFFFFF" stroke="#D1DBD7" stroke-width="0.8"/>
</svg>
"""
toggle_off_dark = """<svg xmlns="http://www.w3.org/2000/svg" width="38" height="22" viewBox="0 0 38 22">
  <rect x="0.75" y="0.75" width="36.5" height="20.5" rx="10.25" fill="#455A52" stroke="#526A61" stroke-width="1.5"/>
  <circle cx="11" cy="11" r="8" fill="#FFFFFF"/>
</svg>
"""
(asset_dir / "toggle_on.svg").write_text(toggle_on, encoding="utf-8")
(asset_dir / "toggle_off_light.svg").write_text(toggle_off_light, encoding="utf-8")
(asset_dir / "toggle_off_dark.svg").write_text(toggle_off_dark, encoding="utf-8")

theme_head = '''    def _v0775_stylesheet(self, dark):
        up, down = self._v0775_theme_urls(dark)
'''
theme_head_new = '''    def _v0775_stylesheet(self, dark):
        up, down = self._v0775_theme_urls(dark)
        toggle_on = str(Path(resource("assets/v0925/toggle_on.svg"))).replace("\\", "/")
        toggle_off = str(Path(resource(f"assets/v0925/toggle_off_{'dark' if dark else 'light'}.svg"))).replace("\\", "/")
'''
if theme_head not in s:
    raise RuntimeError("V0.9.2.5 settings theme header anchor missing")
s = s.replace(theme_head, theme_head_new, 1)

old_checkbox_qss = '''            QCheckBox {{ color: {text2}; spacing: 7px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 5px;
                border: 1px solid {border_soft}; background: {input_bg};
            }}
            QCheckBox::indicator:hover {{ border-color: {accent}; }}
            QCheckBox::indicator:checked {{
                background: {accent}; border: 1px solid {accent};
            }}
'''
new_checkbox_qss = '''            QCheckBox {{ color: {text2}; spacing: 8px; }}
            QCheckBox::indicator {{
                width: 38px; height: 22px;
                border: none; background: transparent;
            }}
            QCheckBox::indicator:unchecked {{ image: url("{toggle_off}"); }}
            QCheckBox::indicator:checked {{ image: url("{toggle_on}"); }}
'''
if old_checkbox_qss not in s:
    raise RuntimeError("V0.9.2.5 global checkbox style anchor missing")
s = s.replace(old_checkbox_qss, new_checkbox_qss, 1)

# ------------------------------------------------------------------
# 3) High-glow preview timing.
#    V0.9.2.4 started the overlay before TTS synthesis/playback, which made
#    typewriter text visibly lead the audio. V0.9.2.5 starts visual playback
#    only from VoiceService.playback_started, i.e. at the same moment audio
#    playback begins. Both preview and live high-glow then keep the talking
#    video looping for 3 seconds after speech ends. No freeze-frame.
# ------------------------------------------------------------------
bind_anchor = '''        self.highlight_preview_btn.clicked.connect(self._v0924_preview_highlight)
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_text_box_btn,self.highlight_preview_btn):
'''
bind_new = '''        self.highlight_preview_btn.clicked.connect(self._v0924_preview_highlight)
        if not getattr(self,"_v0925_preview_signals_bound",False):
            self.voice_service.playback_started.connect(self._v0925_highlight_preview_started)
            self.voice_service.playback_finished.connect(self._v0925_highlight_preview_finished)
            self._v0925_preview_signals_bound=True
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_text_box_btn,self.highlight_preview_btn):
'''
if bind_anchor not in s:
    raise RuntimeError("V0.9.2.5 preview signal-binding anchor missing")
s = s.replace(bind_anchor, bind_new, 1)

# Update the high-glow helper copy.
s = s.replace(
    '支持多支 1:1 绿幕 MP4；导入时自动生成无音轨副本。实战与“预览”都会轮换台词和视频。',
    '支持多支 1:1 绿幕 MP4；实战与“预览”都会轮换台词和视频。语音开始时文字同步出现，播报结束后动画继续循环 3 秒再回到待机。',
    1,
)

start = s.find('    def _v0924_preview_highlight(self):\n')
end = s.find('    def _v0911_style_report_snapshot_bar(self):\n', start)
if start < 0 or end < 0:
    raise RuntimeError("V0.9.2.5 preview method boundaries missing")

preview_block = r'''    def _v0925_highlight_phrase_instruct(self, text):
        rules=(self.cfg.get("speech",{}) or {}).get("phrase_voice_overrides") or {}
        if not isinstance(rules,dict):
            return ""
        normalized=re.sub(r"[\s，,。.!！？?、:：]+","",str(text or "").strip())
        for key,value in rules.items():
            k=re.sub(r"[\s，,。.!！？?、:：]+","",str(key or "").strip())
            if k and k==normalized:
                return str(value or "").strip()
        return ""

    def _v0925_finish_preview_visual(self, hold_ms=3000):
        try:
            overlay=self._v0911_preview_overlay()
            if overlay.isVisible():
                overlay.finish(int(hold_ms))
            elif getattr(self.pet,"dialogue_board_active",False):
                self.pet.finish_dialogue_board(int(hold_ms))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] preview visual finish failed")

    def _v0925_reset_preview_button(self):
        try:
            if hasattr(self,"highlight_preview_btn"):
                self.highlight_preview_btn.setText("预览")
                self.highlight_preview_btn.setEnabled(True)
        except Exception:
            pass
        self._v0925_preview_pending_video=""

    def _v0925_highlight_preview_started(self, text, duration_ms, tag):
        if str(tag or "")!="highlight_preview":
            return
        phrase=str(text or "").strip()
        path=str(getattr(self,"_v0925_preview_pending_video","") or "")
        box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}
        try:
            if path and self._v0911_preview_overlay().play(
                path,phrase,int(duration_ms),box,self._v0922_highlight_font_family()
            ):
                return
            # Graceful fallback when no dedicated high-glow video exists.
            self.pet.start_dialogue_board(phrase,int(duration_ms))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] synced preview start failed")

    def _v0925_highlight_preview_finished(self, ok, message, tag):
        if str(tag or "")!="highlight_preview":
            return
        # The user's high-glow clip contains a continuously talking mouth.
        # Keep the VIDEO LOOPING during the 3-second reading tail; never freeze.
        hold_ms=3000 if bool(ok) else 400
        self._v0925_finish_preview_visual(hold_ms)
        QTimer.singleShot(hold_ms+80,self._v0925_reset_preview_button)
        if not ok:
            LOGGER.warning("[HIGHLIGHT] preview voice failed: %s",message)

    def _v0924_preview_highlight(self):
        phrase=self._v0924_preview_pick_phrase()
        path=self._v0924_preview_pick_video()

        # Stop any prior visual preview without deleting or modifying media.
        try:
            self._v0911_preview_overlay().stop()
        except Exception:
            pass
        try:
            if getattr(self.pet,"dialogue_board_active",False):
                self.pet._end_dialogue_board()
        except Exception:
            pass

        voice=self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
        vid=str(voice.get("voice_id") or "").strip()
        self._v0925_preview_pending_video=path
        if hasattr(self,"highlight_preview_btn"):
            self.highlight_preview_btn.setEnabled(False)
            self.highlight_preview_btn.setText("准备预览…")

        if not vid or not self.voice_service.ready():
            # Visual-only fallback. There is no audio to synchronize with.
            box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}
            if path:
                if self._v0911_preview_overlay().play(
                    path,phrase,4200,box,self._v0922_highlight_font_family()
                ):
                    QTimer.singleShot(4200,lambda:self._v0925_finish_preview_visual(3000))
                    QTimer.singleShot(7280,self._v0925_reset_preview_button)
                    return
            try:
                self.pet.start_dialogue_board(phrase,4200)
                QTimer.singleShot(4200,lambda:self._v0925_finish_preview_visual(3000))
                QTimer.singleShot(7280,self._v0925_reset_preview_button)
            except Exception:
                LOGGER.exception("[HIGHLIGHT] visual-only preview failed")
                self._v0925_reset_preview_button()
            return

        # Use the normal speak path, not VoiceService.preview. speak() emits
        # playback_started with the real WAV duration immediately before audio
        # starts, giving the board/video a single timing origin.
        self.voice_service.speak(
            phrase,
            vid,
            float(voice.get("speed",1.0) or 1.0),
            str(voice.get("output_device","default") or "default"),
            tag="highlight_preview",
            extra_instruct=self._v0925_highlight_phrase_instruct(phrase),
        )

'''
s = s[:start] + preview_block + s[end:]

# Controller must explicitly ignore the Settings-only preview tag so an active
# speech session can never accidentally create a second board layer.
start = s.find('    def _on_voice_playback_started(self, text, duration_ms, tag):\n')
end = s.find('    def _on_voice_playback_finished(self, ok, message, tag):\n', start)
if start < 0 or end < 0:
    raise RuntimeError("V0.9.2.5 controller playback-start boundaries missing")
block=s[start:end]
needle='''        tag=str(tag or "")
        if tag=="highlight_cta":
'''
repl='''        tag=str(tag or "")
        if tag=="highlight_preview":
            return
        if tag=="highlight_cta":
'''
if needle not in block:
    raise RuntimeError("V0.9.2.5 controller preview-ignore start marker missing")
block=block.replace(needle,repl,1)
s=s[:start]+block+s[end:]

start = s.find('    def _on_voice_playback_finished(self, ok, message, tag):\n')
end = s.find('    def _arm_speech_followup(self):\n', start)
if start < 0 or end < 0:
    raise RuntimeError("V0.9.2.5 controller playback-finish boundaries missing")
block=s[start:end]
needle='''        tag=str(tag or "")
        if tag=="highlight_cta":
'''
repl='''        tag=str(tag or "")
        if tag=="highlight_preview":
            return
        if tag=="highlight_cta":
'''
if needle not in block:
    raise RuntimeError("V0.9.2.5 controller preview-ignore finish marker missing")
block=block.replace(needle,repl,1)

old_live = '''        if tag=="highlight_cta":
            try:
                if getattr(self,"_highlight_overlay",None) and self._highlight_overlay.isVisible():
                    self._highlight_overlay.finish(900)
                else:
                    self.pet.finish_dialogue_board(900)
            except Exception:
                pass
            self._highlight_pending_video=""
            self._highlight_active=False
            if bool(self._speech_cfg().get("enabled",True)) and self.speech_service.ready():
                QTimer.singleShot(1100,self.refresh_speech_interaction)
            return
'''
new_live = '''        if tag=="highlight_cta":
            # Keep the talking whiteboard clip moving for a full 3-second tail.
            # HighlightVideoOverlay.finish() only schedules stop; the frame
            # timer continues looping, so there is no frozen talking pose.
            hold_ms=3000
            try:
                if getattr(self,"_highlight_overlay",None) and self._highlight_overlay.isVisible():
                    self._highlight_overlay.finish(hold_ms)
                else:
                    self.pet.finish_dialogue_board(hold_ms)
            except Exception:
                pass
            self._highlight_pending_video=""
            QTimer.singleShot(hold_ms,lambda:setattr(self,"_highlight_active",False))
            if bool(self._speech_cfg().get("enabled",True)) and self.speech_service.ready():
                QTimer.singleShot(hold_ms+120,self.refresh_speech_interaction)
            return
'''
if old_live not in block:
    raise RuntimeError("V0.9.2.5 live highlight hold marker missing")
block=block.replace(old_live,new_live,1)
s=s[:start]+block+s[end:]

# Safety invariants: no automatic cleanup and no high-glow media deletion.
cleanup_start=s.find("def cleanup_obsolete_storage():")
cleanup_end=s.find("\ndef xiaomeili_logical_data_root():", cleanup_start)
if cleanup_start < 0 or cleanup_end < 0:
    raise RuntimeError("V0.9.2.5 cleanup safety block missing")
cleanup=s[cleanup_start:cleanup_end]
if "unlink(" in cleanup or "rmtree(" in cleanup or "Remove-Item" in cleanup:
    raise RuntimeError("V0.9.2.5 automatic cleanup contains deletion operation")
remove_start=s.find("    def _v0911_remove_highlight_video(self):")
remove_end=s.find("\n    def _v0911_save_highlight_editor_state", remove_start)
if remove_start < 0 or remove_end < 0:
    raise RuntimeError("V0.9.2.5 high-glow removal method missing")
remove_block=s[remove_start:remove_end]
if "unlink(" in remove_block or "remove(" in remove_block or "rmtree(" in remove_block:
    raise RuntimeError("V0.9.2.5 high-glow list removal would delete a file")

# Static V0.9.2.5 assertions.
checks = [
    'APP_VERSION = "0.9.2.5"',
    'self.highlight_preview_btn=QPushButton("预览")',
    'tag="highlight_preview"',
    'def _v0925_highlight_preview_started',
    'def _v0925_highlight_preview_finished',
    'hold_ms=3000',
    'toggle_on.svg',
    'toggle_off_',
    'QCheckBox::indicator:checked {{',
]
for token in checks:
    if token not in s:
        raise RuntimeError("V0.9.2.5 verification failed: "+token)
if 'hf.addRow("触发条件",conditions)' in s:
    raise RuntimeError("V0.9.2.5 trigger-condition row still visible")

main.write_text(s, encoding="utf-8")
py_compile.compile(str(main), doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.4 语音诊断日志","小美丽 V0.9.2.5 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech), doraise=True)

version_file.write_text("0.9.2.5\n", encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.5 toggle UI + synchronized high-glow timing")
