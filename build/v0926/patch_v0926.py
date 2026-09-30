# -*- coding: utf-8 -*-
from pathlib import Path
import py_compile
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v0926.py <source_root>")

root=Path(sys.argv[1]).resolve()
main=root/"app/src/main.py"
speech=root/"app/src/speech_input.py"
version_file=root/"app/assets/VERSION.txt"
s=main.read_text(encoding="utf-8")

if 'APP_VERSION = "0.9.2.5"' not in s:
    raise RuntimeError("V0.9.2.6 expected V0.9.2.5 FullSafe base")
s=s.replace('APP_VERSION = "0.9.2.5"','APP_VERSION = "0.9.2.6"',1)
s=s.replace('APP_NAME = "小美丽 V0.9.2.5｜Voice Interaction"','APP_NAME = "小美丽 V0.9.2.6｜Voice Interaction"',1)
s=s.replace("自动存储清理已禁用：V0.9.2.5 不会自动删除任何文件。","自动存储清理已禁用：V0.9.2.6 不会自动删除任何文件。",1)

# ------------------------------------------------------------------
# 1) Asset manager: remove the unused help badge shown beside "当前 x/20 支".
#    This removes only the UI badge. It does not alter assets or config.
# ------------------------------------------------------------------
old_manage_help='''        top.addWidget(info); top.addWidget(HelpBadge("每条素材显示首帧缩略图，方便删除时确认。随机播放采用有放回抽取，允许连续重复同一支。")); top.addStretch(1); lay.addLayout(top)
'''
new_manage_help='''        top.addWidget(info); top.addStretch(1); lay.addLayout(top)
'''
if old_manage_help not in s:
    raise RuntimeError("V0.9.2.6 asset-manager help badge anchor missing")
s=s.replace(old_manage_help,new_manage_help,1)

# ------------------------------------------------------------------
# 2) Action-library Test button: choose the exact clip before playback.
#    We temporarily narrow the in-memory pool to one item, trigger the existing
#    playback path, then restore the original pool immediately. No config save,
#    move, rename, overwrite or file deletion occurs.
# ------------------------------------------------------------------
old_report_test='''                test=QPushButton("测试")
                test.clicked.connect(self.test_report_preview)
                grid.addWidget(test,row,5)
'''
new_report_test='''                test=QPushButton("测试")
                test.clicked.connect(lambda checked=False,s=key:self._v0926_choose_and_test_asset(s))
                grid.addWidget(test,row,5)
'''
if old_report_test not in s:
    raise RuntimeError("V0.9.2.6 report test button anchor missing")
s=s.replace(old_report_test,new_report_test,1)

old_state_test='''                test=QPushButton("测试")
                test.clicked.connect(lambda checked=False,s=key:self.pet.play_state(s, force_new_clip=True))
                grid.addWidget(test,row,5)
'''
new_state_test='''                test=QPushButton("测试")
                test.clicked.connect(lambda checked=False,s=key:self._v0926_choose_and_test_asset(s))
                grid.addWidget(test,row,5)
'''
if old_state_test not in s:
    raise RuntimeError("V0.9.2.6 state test button anchor missing")
s=s.replace(old_state_test,new_state_test,1)

manage_anchor='''    def manage_assets(self,state):
'''
if manage_anchor not in s:
    raise RuntimeError("V0.9.2.6 manage_assets anchor missing")
choose_method=r'''    def _v0926_choose_and_test_asset(self,state):
        pool=[
            str(p) for p in _asset_list(self.cfg.get("assets",{}).get(state))
            if str(p or "").strip() and Path(str(p)).exists()
        ]
        if not pool:
            QMessageBox.information(self,"测试素材",f"「{STATE_NAMES.get(state,state)}」当前没有可播放素材。")
            return

        dlg=QDialog(self)
        dlg.setWindowTitle(f"选择要测试的「{STATE_NAMES.get(state,state)}」素材")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(720,560)
        lay=QVBoxLayout(dlg)
        hint=QLabel("选中一支素材后播放。这里仅做预览，不会修改、移动或删除素材文件。")
        hint.setWordWrap(True)
        hint.setObjectName("pageSubtitle")
        lay.addWidget(hint)

        lst=QListWidget()
        lst.setIconSize(QSize(96,96))
        lst.setSpacing(6)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for pth in pool:
            thumb=asset_thumbnail(pth,96)
            item=QListWidgetItem(QIcon(thumb) if thumb else QIcon(),Path(pth).name)
            item.setData(Qt.ItemDataRole.UserRole,pth)
            item.setToolTip(pth)
            item.setSizeHint(QSize(0,104))
            lst.addItem(item)
        if lst.count():
            lst.setCurrentRow(0)
        lay.addWidget(lst,1)

        row=QHBoxLayout()
        row.addStretch(1)
        cancel=QPushButton("取消")
        play=QPushButton("播放选中")
        row.addWidget(cancel)
        row.addWidget(play)
        lay.addLayout(row)

        def do_play():
            item=lst.currentItem()
            if item is None:
                QMessageBox.information(dlg,"请选择素材","请先选中一支素材。")
                return
            selected=str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not selected or not Path(selected).exists():
                QMessageBox.warning(dlg,"素材不可用","选中的素材文件当前不可用。")
                return

            assets=self.cfg.setdefault("assets",{})
            had_key=state in assets
            original=assets.get(state)
            assets[state]=[selected]
            try:
                if state=="report":
                    self.test_report_preview()
                else:
                    self.pet.play_state(state,force_new_clip=True)
            finally:
                if had_key:
                    assets[state]=original
                else:
                    assets.pop(state,None)
            dlg.accept()

        play.clicked.connect(do_play)
        cancel.clicked.connect(dlg.reject)
        lst.itemDoubleClicked.connect(lambda *_:do_play())
        try:
            self._v0775_apply_native_titlebar(dlg,getattr(self,"_v0775_theme_mode","light")=="dark")
        except Exception:
            pass
        dlg.exec()

'''
s=s.replace(manage_anchor,choose_method+manage_anchor,1)

# ------------------------------------------------------------------
# 3) True, consistent '?' help affordances in Settings.
#    V0.7.7.5 intentionally converted '?' to 'i'; that glyph renders as the
#    exclamation-like mark seen by the user. Keep actual '?' and style it.
# ------------------------------------------------------------------
old_help='''                setter("i")
                if isinstance(widget, QLabel):
                    widget.setObjectName("helpLabel")
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    widget.setObjectName("helpButton")
                widget.setFixedSize(21, 21)
'''
new_help='''                setter("?")
                if isinstance(widget, QLabel):
                    widget.setObjectName("helpLabel")
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                else:
                    widget.setObjectName("helpButton")
                widget.setFixedSize(20, 20)
                widget.setStyleSheet("font-family:Arial;font-size:13px;font-weight:700;")
'''
if old_help not in s:
    raise RuntimeError("V0.9.2.6 help-widget marker anchor missing")
s=s.replace(old_help,new_help,1)

# ------------------------------------------------------------------
# 4) Per-video highlight whiteboard text boxes.
#    The video's generated filename is the stable key, so a D-drive migration
#    or root-path change does not lose the preset.
# ------------------------------------------------------------------
font_helper='''    def _v0922_highlight_font_family(self):
        try:
            self.pet.dialogue_overlay.reload_font()
            return self.pet.dialogue_overlay.font_family
        except Exception:
            return "Microsoft YaHei"

'''
if font_helper not in s:
    raise RuntimeError("V0.9.2.6 highlight font helper anchor missing")
settings_helpers=font_helper+r'''    def _v0926_highlight_video_key(self,path):
        return Path(str(path or "")).name

    def _v0926_highlight_text_box_for(self,path):
        cfg=self.cfg.setdefault("highlight_cta",{})
        boxes=cfg.get("video_text_boxes") if isinstance(cfg.get("video_text_boxes"),dict) else {}
        key=self._v0926_highlight_video_key(path)
        raw=boxes.get(key) if key else None
        if not isinstance(raw,dict):
            raw=cfg.get("text_box") or {}
        return normalized_highlight_text_layout(raw,self.cfg.get("whiteboard",{}))

'''
s=s.replace(font_helper,settings_helpers,1)

# Mark videos with individual presets unobtrusively in the list.
old_list_item='''                _item=QListWidgetItem(Path(str(_p)).name)
                _item.setData(Qt.ItemDataRole.UserRole,str(_p))
'''
new_list_item='''                _boxes=hcfg.get("video_text_boxes") if isinstance(hcfg.get("video_text_boxes"),dict) else {}
                _name=Path(str(_p)).name
                _item=QListWidgetItem(("✓ " if _name in _boxes else "")+_name)
                _item.setData(Qt.ItemDataRole.UserRole,str(_p))
'''
if old_list_item not in s:
    raise RuntimeError("V0.9.2.6 highlight list item anchor missing")
s=s.replace(old_list_item,new_list_item,1)

# Editor loads/saves the selected video's own preset, while old global text_box
# remains untouched as a backwards-compatible fallback.
old_editor_load='''        layout=normalized_highlight_text_layout(cfg.get("text_box") or {}, self.cfg.get("whiteboard",{}))
        dlg=QDialog(self)
'''
new_editor_load='''        video_key=self._v0926_highlight_video_key(path)
        layout=self._v0926_highlight_text_box_for(path)
        dlg=QDialog(self)
'''
if old_editor_load not in s:
    raise RuntimeError("V0.9.2.6 highlight editor load anchor missing")
s=s.replace(old_editor_load,new_editor_load,1)

old_editor_title='''        title=QLabel("文字与限制框"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("V0.9.2.2 与对白白板使用同一套字体、自动换行和字号适配。绿色虚线框可直接拖动；右下角绿色方块可自由缩放。坐标按视频比例保存，更换 1:1 素材或调整桌宠大小后仍等比例保持。")
'''
new_editor_title='''        title=QLabel(f"文字与限制框 · {Path(path).name}"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("当前设置只属于这支白板视频。绿色虚线框可直接拖动，右下角绿色方块可缩放；实战和“预览”随机抽到这支视频时，会自动使用它自己的文字区域。")
'''
if old_editor_title not in s:
    raise RuntimeError("V0.9.2.6 highlight editor title anchor missing")
s=s.replace(old_editor_title,new_editor_title,1)

old_editor_commit='''            cfg['text_box']={'schema':2,**final}
            save_config(self.cfg)
'''
new_editor_commit='''            boxes=cfg.setdefault('video_text_boxes',{})
            boxes[video_key]={'schema':3,**final}
            if hasattr(self,"highlight_video_list"):
                item=self.highlight_video_list.currentItem()
                if item is not None:
                    item.setText("✓ "+Path(str(item.data(Qt.ItemDataRole.UserRole) or "")).name)
            save_config(self.cfg)
'''
if old_editor_commit not in s:
    raise RuntimeError("V0.9.2.6 highlight editor commit anchor missing")
s=s.replace(old_editor_commit,new_editor_commit,1)

# Settings preview uses the selected random video's own text layout.
old_preview_box='''        box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}
'''
if s.count(old_preview_box)<1:
    raise RuntimeError("V0.9.2.6 preview text-box anchor missing")
# The first occurrence after _v0925_highlight_preview_started is the synchronized preview.
idx=s.find('    def _v0925_highlight_preview_started(self, text, duration_ms, tag):')
p=s.find(old_preview_box,idx)
if p<0:
    raise RuntimeError("V0.9.2.6 synchronized preview box not found")
s=s[:p]+'        box=self._v0926_highlight_text_box_for(path)\n'+s[p+len(old_preview_box):]

# Visual-only preview fallback has its own global-box lookup.
idx=s.find('    def _v0924_preview_highlight(self):')
end=s.find('\n    def _v0911_style_report_snapshot_bar',idx)
if idx<0 or end<0:
    raise RuntimeError("V0.9.2.6 preview method boundaries missing")
block=s[idx:end]
block=block.replace(
    'box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}',
    'box=self._v0926_highlight_text_box_for(path)'
)
s=s[:idx]+block+s[end:]

# AppController live high-glow playback also selects the box by video filename.
pick_anchor='''    def _pick_highlight_video(self):
'''
if pick_anchor not in s:
    raise RuntimeError("V0.9.2.6 controller video picker anchor missing")
controller_helper=r'''    def _highlight_text_box_for_video(self,video):
        cfg=self._highlight_cfg()
        boxes=cfg.get("video_text_boxes") if isinstance(cfg.get("video_text_boxes"),dict) else {}
        key=Path(str(video or "")).name
        raw=boxes.get(key) if key else None
        if not isinstance(raw,dict):
            raw=cfg.get("text_box") or {}
        return raw

'''
s=s.replace(pick_anchor,controller_helper+pick_anchor,1)

old_live_box='self._highlight_cfg().get("text_box") or {}'
live_count=s.count(old_live_box)
if live_count<1:
    raise RuntimeError("V0.9.2.6 live highlight text-box lookup missing")
s=s.replace(old_live_box,'self._highlight_text_box_for_video(video)')

# Update the compact helper copy without adding more controls.
s=s.replace(
    '支持多支 1:1 绿幕 MP4；实战与“预览”都会轮换台词和视频。语音开始时文字同步出现，播报结束后动画继续循环 3 秒再回到待机。',
    '每支白板都可保存自己的文字限制框；先选中视频，再点“文字与限制框”。实战与“预览”会分别随机抽取视频和台词并合并播放，语音结束后动画继续循环 3 秒。',
    1,
)

# ------------------------------------------------------------------
# Safety assertions. V0.9.2.6 must inherit the native no-delete updater.
# ------------------------------------------------------------------
checks=[
    'APP_VERSION = "0.9.2.6"',
    'from native_updater import install_update_package',
    'install_update_package(',
    'def _v0926_choose_and_test_asset',
    'def _v0926_highlight_text_box_for',
    'def _highlight_text_box_for_video',
    'video_text_boxes',
    'setter("?")',
]
for token in checks:
    if token not in s:
        raise RuntimeError("V0.9.2.6 verification missing: "+token)

# Confirm manage-assets no longer has its help badge and test buttons no longer
# directly random-play a state.
if 'top.addWidget(info); top.addWidget(HelpBadge("每条素材显示首帧缩略图' in s:
    raise RuntimeError("V0.9.2.6 asset-manager help badge still present")
if 'test.clicked.connect(lambda checked=False,s=key:self.pet.play_state(s, force_new_clip=True))' in s:
    raise RuntimeError("V0.9.2.6 random Test button path still present")

# No runtime updater regression to the old PowerShell handoff.
method_start=s.find("    def install_latest_async(self):")
method_end=s.find("\n\ndef _path_size_bytes",method_start)
if method_start<0 or method_end<0:
    raise RuntimeError("V0.9.2.6 updater method missing")
update_method=s[method_start:method_end]
for forbidden in ('powershell.exe','update_helper.ps1','robocopy','/MIR','/PURGE'):
    if forbidden in update_method:
        raise RuntimeError("V0.9.2.6 updater regression: "+forbidden)

main.write_text(s,encoding="utf-8")
py_compile.compile(str(main),doraise=True)

sp=speech.read_text(encoding="utf-8")
sp=sp.replace("小美丽 V0.9.2.5 语音诊断日志","小美丽 V0.9.2.6 语音诊断日志")
speech.write_text(sp,encoding="utf-8")
py_compile.compile(str(speech),doraise=True)
version_file.write_text("0.9.2.6\n",encoding="ascii")
print("Patched XiaoMeili source to V0.9.2.6")
