from pathlib import Path
import re, textwrap, shutil, json, os
import sys
if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v0922.py <source_root>')
root=Path(sys.argv[1]).resolve()
main=root/'app/src/main.py'
s=main.read_text(encoding='utf-8')

# Remove actual file deletion from highlight list removal.
old=r'''    def _v0911_remove_highlight_video(self):
        row=self.highlight_video_list.currentRow() if hasattr(self,"highlight_video_list") else -1
        if row<0:return
        item=self.highlight_video_list.takeItem(row)
        path=Path(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        try:
            root=self._v0911_highlight_video_dir().resolve()
            if path.exists() and root in path.resolve().parents:
                path.unlink()
        except Exception:
            LOGGER.warning("删除高光视频失败: %s",path,exc_info=True)
        self._v0911_save_highlight_editor_state()
'''
new=r'''    def _v0911_remove_highlight_video(self):
        row=self.highlight_video_list.currentRow() if hasattr(self,"highlight_video_list") else -1
        if row<0:return
        # V0.9.2.2 safety rule: remove only from the configured pool.  The
        # imported muted file is intentionally retained on disk so this action
        # can never destroy user data or a recoverable asset.
        self.highlight_video_list.takeItem(row)
        self._v0911_save_highlight_editor_state()
'''
if old not in s: raise RuntimeError('remove video function not found')
s=s.replace(old,new,1)

# Insert font helper after preview overlay.
old=r'''    def _v0911_preview_overlay(self):
        if getattr(self,"_v0911_overlay",None) is None:
            self._v0911_overlay=HighlightVideoOverlay(self.pet)
        return self._v0911_overlay

    def _v0911_preview_selected_video(self):
'''
new=r'''    def _v0911_preview_overlay(self):
        if getattr(self,"_v0911_overlay",None) is None:
            self._v0911_overlay=HighlightVideoOverlay(self.pet)
        return self._v0911_overlay

    def _v0922_highlight_font_family(self):
        try:
            self.pet.dialogue_overlay.reload_font()
            return self.pet.dialogue_overlay.font_family
        except Exception:
            return "Microsoft YaHei"

    def _v0911_preview_selected_video(self):
'''
if old not in s: raise RuntimeError('preview overlay block not found')
s=s.replace(old,new,1)

# Update preview selected call.
s=s.replace('''        if not self._v0911_preview_overlay().play(path,phrase,4200,box):''','''        if not self._v0911_preview_overlay().play(path,phrase,4200,box,self._v0922_highlight_font_family()):''',1)

# Replace highlight text editor whole function.
start=s.index('    def _v0911_edit_highlight_text_box(self):')
end=s.index('\n    def _v091_editor_highlight_phrases(self):', start)
new_func=r'''    def _v0911_edit_highlight_text_box(self):
        cfg=self.cfg.setdefault("highlight_cta",{})
        path=self._v0911_selected_highlight_video()
        if not path:
            QMessageBox.information(self,"高光白板视频","请先导入并选中一支高光白板视频，再调整文字限制框。")
            return

        layout=normalized_highlight_text_layout(cfg.get("text_box") or {}, self.cfg.get("whiteboard",{}))
        dlg=QDialog(self)
        dlg.setWindowTitle("高光白板｜文字与限制框")
        dlg.setWindowIcon(QIcon(resource("assets/xiaomeili_icon.png")))
        dlg.resize(980,720); dlg.setMinimumSize(900,650)
        root=QVBoxLayout(dlg)
        title=QLabel("文字与限制框"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("V0.9.2.2 与对白白板使用同一套字体、自动换行和字号适配。绿色虚线框可直接拖动；右下角绿色方块可自由缩放。坐标按视频比例保存，更换 1:1 素材或调整桌宠大小后仍等比例保持。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)

        body=QHBoxLayout(); root.addLayout(body,1)
        preview=WhiteboardLayoutPreview(); preview.set_video_path(path); preview.set_font_family(self._v0922_highlight_font_family())
        sample=(self._v091_editor_highlight_phrases() or ["愣着干嘛，点点关注呀！"])[0]
        preview.set_sample(sample); preview.set_layout(layout); body.addWidget(preview,3)

        controls=QWidget(); form=QFormLayout(controls); body.addWidget(controls,2)
        spins={}; syncing={"on":False}; dirty={"on":False}
        specs=[('x','区域 X (%)',0,95,0.1),('y','区域 Y (%)',0,95,0.1),('w','区域宽度 (%)',5,100,0.1),('h','区域高度 (%)',5,100,0.1),('offset_x','水平偏移 (%)',-30,30,0.1),('offset_y','垂直偏移 (%)',-30,30,0.1)]
        for key,label,lo,hi,step in specs:
            sp=QDoubleSpinBox(); sp.setRange(lo,hi); sp.setSingleStep(step); sp.setDecimals(1); spins[key]=sp; form.addRow(label,sp)
        min_font=QSpinBox(); min_font.setRange(8,48); form.addRow('最小字号 (px)',min_font)
        max_font=QSpinBox(); max_font.setRange(12,88); form.addRow('最大字号 (px)',max_font)
        font_scale=QDoubleSpinBox(); font_scale.setRange(50,180); font_scale.setSuffix('%'); form.addRow('整体字号倍率',font_scale)
        line_spacing=QDoubleSpinBox(); line_spacing.setRange(85,150); line_spacing.setSuffix('%'); form.addRow('行距',line_spacing)
        max_lines=QSpinBox(); max_lines.setRange(1,7); form.addRow('最大行数',max_lines)
        outline=QDoubleSpinBox(); outline.setRange(0,4); outline.setSingleStep(0.5); form.addRow('淡描边 (px)',outline)
        auto_fill=QCheckBox('自动换行 + 自动字号 + 居中（推荐）'); form.addRow(auto_fill)
        sample_box=QGroupBox('台词预览'); sg=QGridLayout(sample_box)
        samples=[x for x in self._v091_editor_highlight_phrases()[:5]] or [sample]
        for i,text_value in enumerate(samples):
            b=QPushButton(f'{i+1}'); b.setToolTip(text_value); b.clicked.connect(lambda checked=False,t=text_value:preview.set_sample(t)); sg.addWidget(b,0,i)
        form.addRow(sample_box)
        full=QPushButton('一键铺满白板区'); form.addRow(full)
        reset=QPushButton('恢复默认模板'); form.addRow(reset)
        help_label=QLabel('绿色虚线框就是文字安全区。字体家族与“对白白板模板”完全一致；保存后，设置页预览与实战高光都使用同一套渲染逻辑。')
        help_label.setWordWrap(True); help_label.setStyleSheet('color:#657185;'); form.addRow(help_label)

        status=QLabel(''); status.setStyleSheet('color:#278a74;')
        bottom=QHBoxLayout(); bottom.addWidget(status); bottom.addStretch(1)
        cancel=QPushButton('取消'); save=QPushButton('保存并应用'); save.setEnabled(False)
        bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom)

        def mark():
            if syncing['on']: return
            dirty['on']=True; save.setEnabled(True); status.setText('未保存')

        def current_from_controls():
            l=dict(layout)
            for key,sp in spins.items(): l[key]=float(sp.value())/100.0
            l['min_font_px']=int(min_font.value()); l['max_font_px']=int(max_font.value())
            l['font_scale']=float(font_scale.value())/100.0; l['line_spacing']=float(line_spacing.value())/100.0
            l['max_lines']=int(max_lines.value()); l['outline_width']=float(outline.value()); l['auto_fill']=bool(auto_fill.isChecked())
            # Always follow the general dialogue-whiteboard typography colors in this mode.
            wb=normalized_whiteboard_layout(self.cfg.get('whiteboard',{}))
            l['text_color']=wb.get('text_color','#08423A'); l['outline_color']=wb.get('outline_color','#F6FFF9')
            return normalized_highlight_text_layout(l,self.cfg.get('whiteboard',{}))

        def sync_controls(l):
            nonlocal layout
            layout=normalized_highlight_text_layout(l,self.cfg.get('whiteboard',{})); syncing['on']=True
            for key,sp in spins.items(): sp.setValue(float(layout[key])*100.0)
            min_font.setValue(int(layout['min_font_px'])); max_font.setValue(int(layout['max_font_px']))
            font_scale.setValue(float(layout['font_scale'])*100.0); line_spacing.setValue(float(layout['line_spacing'])*100.0)
            max_lines.setValue(int(layout['max_lines'])); outline.setValue(float(layout['outline_width'])); auto_fill.setChecked(bool(layout['auto_fill']))
            syncing['on']=False; preview.set_layout(layout)

        def control_changed(*_):
            nonlocal layout
            if syncing['on']: return
            layout=current_from_controls(); preview.set_layout(layout); mark()

        def preview_changed(l):
            sync_controls(l); mark()

        for sp in spins.values(): sp.valueChanged.connect(control_changed)
        for w in (min_font,max_font,font_scale,line_spacing,max_lines,outline): w.valueChanged.connect(control_changed)
        auto_fill.toggled.connect(control_changed)
        preview.layout_changed.connect(preview_changed)

        def do_full():
            l=current_from_controls(); l.update({'x':0.075,'y':0.655,'w':0.850,'h':0.300,'offset_x':0.0,'offset_y':0.0}); sync_controls(l); mark()
        def do_reset():
            wb=normalized_whiteboard_layout(self.cfg.get('whiteboard',{})); l=dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)
            for key in ('min_font_px','max_font_px','font_scale','line_spacing','max_lines','text_color','outline_color','outline_width','auto_fill'):
                l[key]=wb.get(key,l[key])
            sync_controls(l); mark()
        full.clicked.connect(do_full); reset.clicked.connect(do_reset)

        def commit():
            final=normalized_highlight_text_layout(layout,self.cfg.get('whiteboard',{}))
            cfg['text_box']={'schema':2,**final}
            save_config(self.cfg)
            try:self.config_changed.emit()
            except Exception:pass
            status.setText('已应用 ✓'); save.setEnabled(False); dlg.accept()
        save.clicked.connect(commit); cancel.clicked.connect(dlg.reject)
        sync_controls(layout); dirty['on']=False; save.setEnabled(False)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,'_v0775_theme_mode','light')=='dark')
        except Exception:pass
        dlg.exec()
'''
s=s[:start]+new_func+s[end:]

# Update board preview mode play with font family.
s=s.replace('''                    path,board,4200,self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}\n                )''','''                    path,board,4200,self.cfg.setdefault("highlight_cta",{}).get("text_box") or {},\n                    self._v0922_highlight_font_family()\n                )''',1)


main.write_text(s,encoding='utf-8')
print('V0.9.2.2 patch part 2 complete')
