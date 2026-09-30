# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0924.py <source_root>")

root = Path(sys.argv[1]).resolve()
main = root / "app" / "src" / "main.py"
speech = root / "app" / "src" / "speech_input.py"
version_file = root / "app" / "assets" / "VERSION.txt"

s = main.read_text(encoding="utf-8")
if 'APP_VERSION = "0.9.2.3"' not in s:
    raise RuntimeError("V0.9.2.4 expected V0.9.2.3 base")
s = s.replace('APP_VERSION = "0.9.2.3"', 'APP_VERSION = "0.9.2.4"', 1)
s = s.replace('APP_NAME = "小美丽 V0.9.2.3｜Voice Interaction"', 'APP_NAME = "小美丽 V0.9.2.4｜Voice Interaction"', 1)

# ------------------------------------------------------------------
# Highlight UI: one preview button only.
# ------------------------------------------------------------------
# Remove the obsolete standalone "board text for preview" field. Its old
# config value is deliberately left untouched for backwards compatibility;
# V0.9.2.4 never deletes or rewrites user data just to clean a legacy key.
old_board = '''        self.highlight_board_text=QLineEdit(str(hcfg.get("board_text") or "愣着干嘛，点点关注呀！"))
        hf.addRow("仅预览白板文字",self.highlight_board_text)

'''
if old_board not in s:
    raise RuntimeError("V0.9.2.4 obsolete preview-board field anchor missing")
s = s.replace(old_board, "", 1)

# Stop persisting the now-hidden legacy field.
old_save = '''        hcfg["board_text"]=self.highlight_board_text.text().strip() if hasattr(self,"highlight_board_text") else "愣着干嘛，点点关注呀！"
'''
if old_save not in s:
    raise RuntimeError("V0.9.2.4 legacy board_text save anchor missing")
s = s.replace(old_save, "", 1)

# Collapse the video-toolbar preview to a single global Preview button.
old_toolbar = '''        self.highlight_import_video_btn=QPushButton("导入白板视频")
        self.highlight_remove_video_btn=QPushButton("移出列表")
        self.highlight_remove_video_btn.setToolTip("只从高光素材池移除，不删除磁盘上的视频文件。")
        self.highlight_preview_video_btn=QPushButton("预览选中")
        self.highlight_text_box_btn=QPushButton("文字与限制框")
        self.highlight_import_video_btn.clicked.connect(self._v0911_import_highlight_videos)
        self.highlight_remove_video_btn.clicked.connect(self._v0911_remove_highlight_video)
        self.highlight_preview_video_btn.clicked.connect(self._v0911_preview_selected_video)
        self.highlight_text_box_btn.clicked.connect(self._v0911_edit_highlight_text_box)
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_preview_video_btn,self.highlight_text_box_btn):
            _vr.addWidget(_b)
'''
new_toolbar = '''        self.highlight_import_video_btn=QPushButton("导入白板视频")
        self.highlight_remove_video_btn=QPushButton("移出列表")
        self.highlight_remove_video_btn.setToolTip("只从高光素材池移除，不删除磁盘上的视频文件。")
        self.highlight_text_box_btn=QPushButton("文字与限制框")
        self.highlight_preview_btn=QPushButton("预览")
        self.highlight_preview_btn.setToolTip("随机抽取一条播报台词，并按实战逻辑轮换高光白板视频。")
        self.highlight_import_video_btn.clicked.connect(self._v0911_import_highlight_videos)
        self.highlight_remove_video_btn.clicked.connect(self._v0911_remove_highlight_video)
        self.highlight_text_box_btn.clicked.connect(self._v0911_edit_highlight_text_box)
        self.highlight_preview_btn.clicked.connect(self._v0924_preview_highlight)
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_text_box_btn,self.highlight_preview_btn):
            _vr.addWidget(_b)
'''
if old_toolbar not in s:
    raise RuntimeError("V0.9.2.4 highlight video toolbar anchor missing")
s = s.replace(old_toolbar, new_toolbar, 1)

s = s.replace(
    '支持多支 1:1 绿幕 MP4；导入时自动生成无音轨副本。实战和随机预览会轮换视频。',
    '支持多支 1:1 绿幕 MP4；导入时自动生成无音轨副本。实战与“预览”都会轮换台词和视频。',
    1,
)

# Remove the second/legacy three-button preview row entirely.
old_preview_row = '''        preview_row=QWidget()
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

'''
if old_preview_row not in s:
    raise RuntimeError("V0.9.2.4 legacy three-button preview row anchor missing")
s = s.replace(old_preview_row, "", 1)

# Remove the old selected-video-only preview method.
start = s.find('    def _v0911_preview_selected_video(self):\n')
end = s.find('    def _v0911_edit_highlight_text_box(self):\n', start)
if start < 0 or end < 0:
    raise RuntimeError("V0.9.2.4 selected-video preview method boundaries missing")
s = s[:start] + s[end:]

# Replace the old random/next/board preview subsystem with one real-world
# preview path. Phrase and video both use shuffle bags: randomized order,
# every item once per cycle, and no immediate repeat at the cycle boundary.
start = s.find('    def _v091_preview_pick(self, mode):\n')
end = s.find('    def _v091_scale_css(self, css, scale):\n', start)
if start < 0 or end < 0:
    raise RuntimeError("V0.9.2.4 legacy preview subsystem boundaries missing")

preview_methods = r'''    def _v0924_preview_pick_phrase(self):
        values=self._v091_editor_highlight_phrases()
        key=tuple(values)
        if getattr(self,"_v0924_preview_phrase_key",None)!=key:
            self._v0924_preview_phrase_key=key
            self._v0924_preview_phrase_bag=[]
        bag=list(getattr(self,"_v0924_preview_phrase_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_v0924_preview_phrase_last","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        phrase=bag.pop(0)
        self._v0924_preview_phrase_bag=bag
        self._v0924_preview_phrase_last=phrase
        return phrase

    def _v0924_preview_pick_video(self):
        values=[]
        if hasattr(self,"highlight_video_list"):
            for i in range(self.highlight_video_list.count()):
                p=str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
                if p and Path(p).exists() and p not in values:
                    values.append(p)
        if not values:
            return ""
        key=tuple(values)
        if getattr(self,"_v0924_preview_video_key",None)!=key:
            self._v0924_preview_video_key=key
            self._v0924_preview_video_bag=[]
        bag=list(getattr(self,"_v0924_preview_video_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_v0924_preview_video_last","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        path=bag.pop(0)
        self._v0924_preview_video_bag=bag
        self._v0924_preview_video_last=path
        return path

    def _v0924_preview_highlight(self):
        phrase=self._v0924_preview_pick_phrase()
        path=self._v0924_preview_pick_video()
        box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}

        # Stop a previous preview cleanly. This only stops playback; it never
        # removes, overwrites or deletes any user file.
        try:
            self._v0911_preview_overlay().stop()
        except Exception:
            pass
        for method_name in ("stop_playback","stop_audio","cancel_playback"):
            try:
                method=getattr(self.voice_service,method_name,None)
                if callable(method):
                    method()
                    break
            except Exception:
                pass

        # Visual preview is the same dedicated high-glow renderer used by the
        # live feature. If no dedicated video is configured, gracefully fall
        # back to the universal dialogue board rather than failing.
        if path:
            ok=self._v0911_preview_overlay().play(
                path,phrase,4200,box,self._v0922_highlight_font_family()
            )
            if ok:
                QTimer.singleShot(4200,lambda:self._v0911_preview_overlay().finish(500))
            else:
                QMessageBox.warning(self,"高光预览","高光白板视频无法播放，请检查素材编码。")
                return
        else:
            try:
                self.pet.preview_dialogue(phrase,4200)
            except Exception as exc:
                QMessageBox.warning(self,"高光预览",f"白板预览失败：{type(exc).__name__}: {exc}")
                return

        # Audio preview deliberately uses VoiceService.preview rather than the
        # live highlight tag, preventing a second dialogue-board layer from
        # being created behind the dedicated high-glow overlay.
        voice=self.cfg.get("voice",{}) if isinstance(self.cfg.get("voice"),dict) else {}
        vid=str(voice.get("voice_id") or "").strip()
        if vid and self.voice_service.ready():
            try:
                self.voice_service.preview(
                    phrase,
                    vid,
                    float(voice.get("speed",1.0) or 1.0),
                    str(voice.get("output_device","default") or "default"),
                    extra_instruct="",
                )
            except Exception:
                LOGGER.exception("[HIGHLIGHT] V0.9.2.4 audio preview failed")
        else:
            LOGGER.info("[HIGHLIGHT] V0.9.2.4 preview is visual-only: voice not ready")

'''
s = s[:start] + preview_methods + s[end:]

# Explicitly verify the obsolete labels/handlers are gone from runtime source.
for obsolete in (
    'QPushButton("预览选中")',
    'QPushButton("▶ 随机预览高光")',
    'QPushButton("逐句试听下一句")',
    'QPushButton("仅预览白板")',
    'hf.addRow("仅预览白板文字"',
    'def _v0911_preview_selected_video',
    'def _v091_preview_highlight',
):
    if obsolete in s:
        raise RuntimeError("V0.9.2.4 obsolete preview path remains: " + obsolete)

# Hard safety invariant inherited from V0.9.2.3: no automatic file cleanup.
cleanup_start=s.find("def cleanup_obsolete_storage():")
cleanup_end=s.find("\ndef xiaomeili_logical_data_root():", cleanup_start)
if cleanup_start < 0 or cleanup_end < 0:
    raise RuntimeError("V0.9.2.4 cleanup safety block missing")
cleanup=s[cleanup_start:cleanup_end]
if "unlink(" in cleanup or "rmtree(" in cleanup or "Remove-Item" in cleanup:
    raise RuntimeError("V0.9.2.4 cleanup safety block contains deletion operation")

main.write_text(s, encoding="utf-8")
py_compile.compile(str(main), doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.3 语音诊断日志","小美丽 V0.9.2.4 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech), doraise=True)

version_file.write_text("0.9.2.4\n", encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.4 single highlight preview")
