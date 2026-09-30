from pathlib import Path
import re, textwrap, shutil, json, os
import sys
if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v0922.py <source_root>')
root=Path(sys.argv[1]).resolve()
main=root/'app/src/main.py'
s=main.read_text(encoding='utf-8')

# Replace report snapshot styling helper for red/amber/green card parity.
start=s.index('    def _v0911_style_report_snapshot_bar(self):')
end=s.index('\n    def _v091_scale_css', start)
new_style=r'''    def _v0911_style_report_snapshot_bar(self):
        """Keep report-snapshot state visually identical to the highlight qualification card."""
        try:
            label=getattr(self,"report_snapshot_status",None)
            if label is None:
                return
            raw=str(label.text() or "").strip()
            if "已锁定" in raw and "未锁定" not in raw:
                palette="background:#E1F7EA;color:#147A45;border:1px solid #8AD5AA;"
            elif "候选" in raw or "缓存" in raw or "等待" in raw:
                palette="background:#FFF4D6;color:#9A6700;border:1px solid #E6C66A;"
            else:
                palette="background:#FDE8E8;color:#B42318;border:1px solid #F4B4B4;"
            label.setObjectName("reportSnapshotBar")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(54)
            label.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            label.setStyleSheet(
                "QLabel#reportSnapshotBar{"+palette+
                "border-radius:10px;padding:10px 14px;font-size:20px;font-weight:900;}"
            )
        except Exception:
            LOGGER.warning("战报快照状态条样式更新失败",exc_info=True)
'''
s=s[:start]+new_style+s[end:]

# Ensure snapshot card is styled before any early return in update_vision_snapshot.
needle='''        self.report_parse_label.setText(f"战报解析：{parse_status}{result}")\n\n        mode_name="极低功耗"'''
repl='''        self.report_parse_label.setText(f"战报解析：{parse_status}{result}")\n        # V0.9.2.2: style immediately so disabled/background/non-game early\n        # returns cannot leave the snapshot line in the old plain-text style.\n        self._v0911_style_report_snapshot_bar()\n\n        mode_name="极低功耗"'''
if needle not in s: raise RuntimeError('snapshot early style marker missing')
s=s.replace(needle,repl,1)

# Initial style after creating report snapshot group.
needle='''        lv.addWidget(self.report_snapshot_status)\n        lv.addWidget(self.report_parse_label)'''
repl='''        lv.addWidget(self.report_snapshot_status)\n        lv.addWidget(self.report_parse_label)\n        QTimer.singleShot(0,self._v0911_style_report_snapshot_bar)'''
if needle not in s: raise RuntimeError('snapshot construction marker missing')
s=s.replace(needle,repl,1)

# Add source export group under components before tech note.
needle='''        cv.addWidget(speech_group)\n\n        tech_note = QLabel('''
insert='''        cv.addWidget(speech_group)\n\n        source_group = QGroupBox("源码工程")\n        source_form = QFormLayout(source_group)\n        source_form.setContentsMargins(14,14,14,12); source_form.setSpacing(8)\n        self.v0922_source_status = QLabel(f"当前 V{APP_VERSION} 完整可编辑源码快照已随程序提供")\n        self.v0922_source_status.setWordWrap(True)\n        source_form.addRow("状态", self.v0922_source_status)\n        self.v0922_export_source_btn = QPushButton("打包完整原始源码工程")\n        self.v0922_export_source_btn.setToolTip("只导出当前版本随包携带的只读源码 ZIP；不会读取、移动、覆盖或删除你的个人文件。")\n        self.v0922_export_source_btn.clicked.connect(self._v0922_export_source_project)\n        source_form.addRow(self.v0922_export_source_btn)\n        source_hint = QLabel("用于新建 ChatGPT 对话时直接上传继续开发。源码包不包含模型权重、个人配置、聊天记忆、日志或你后来导入的素材。")\n        source_hint.setWordWrap(True); source_hint.setObjectName("cardDesc"); source_form.addRow(source_hint)\n        cv.addWidget(source_group)\n\n        tech_note = QLabel('''
if needle not in s: raise RuntimeError('components insert marker missing')
s=s.replace(needle,insert,1)

# Add source export method after open_system_section.
needle='''    def _v774_first_run_notice(self):\n        # V0.7.7.11: onboarding notice retired permanently.\n        return\n'''
insert=r'''    def _v0922_export_source_project(self):
        """Export the exact release source snapshot without deleting or overwriting anything."""
        try:
            bundle=Path(resource(f"assets/XiaoMeili_V{APP_VERSION}_SourceProject.zip"))
            if not bundle.is_file():
                raise FileNotFoundError(f"源码快照缺失：{bundle.name}")
            folder=QFileDialog.getExistingDirectory(self,"选择源码工程保存位置",str(desktop_dir()))
            if not folder:
                return
            folder=Path(folder)
            base=folder/f"XiaoMeili_V{APP_VERSION}_完整原始源码工程.zip"
            target=base
            index=1
            # Never overwrite an existing user file.  Generate a unique name instead.
            while target.exists():
                target=folder/f"XiaoMeili_V{APP_VERSION}_完整原始源码工程 ({index}).zip"
                index+=1
            shutil.copyfile(bundle,target)
            src_hash=hashlib.sha256(bundle.read_bytes()).hexdigest()
            dst_hash=hashlib.sha256(target.read_bytes()).hexdigest()
            if src_hash != dst_hash:
                raise RuntimeError("导出后 SHA-256 校验失败")
            if hasattr(self,"v0922_source_status"):
                self.v0922_source_status.setText(f"已导出：{target.name}  |  SHA-256 校验通过")
            QMessageBox.information(self,"源码工程已导出",f"完整原始源码工程已保存：\n{target}\n\n没有覆盖或删除任何现有文件。")
        except Exception as exc:
            LOGGER.exception("导出完整原始源码工程失败")
            QMessageBox.warning(self,"源码工程导出失败",f"{type(exc).__name__}: {exc}")

    def _v774_first_run_notice(self):
        # V0.7.7.11: onboarding notice retired permanently.
        return
'''
if needle not in s: raise RuntimeError('source export method marker missing')
s=s.replace(needle,insert,1)

# AppController helper for font family after ensure overlay.
needle='''    def _ensure_highlight_overlay(self):\n        if getattr(self,"_highlight_overlay",None) is None:\n            self._highlight_overlay=HighlightVideoOverlay(self.pet)\n        return self._highlight_overlay\n\n    def _warm_highlight_cta_cache(self):'''
repl='''    def _ensure_highlight_overlay(self):\n        if getattr(self,"_highlight_overlay",None) is None:\n            self._highlight_overlay=HighlightVideoOverlay(self.pet)\n        return self._highlight_overlay\n\n    def _highlight_font_family(self):\n        try:\n            self.pet.dialogue_overlay.reload_font()\n            return self.pet.dialogue_overlay.font_family\n        except Exception:\n            return "Microsoft YaHei"\n\n    def _warm_highlight_cta_cache(self):'''
if needle not in s: raise RuntimeError('app controller font helper marker missing')
s=s.replace(needle,repl,1)

# AppController overlay.play calls (2 specific places)
s=s.replace('''                video,phrase,4200,self._highlight_cfg().get("text_box") or {}\n            )''','''                video,phrase,4200,self._highlight_cfg().get("text_box") or {},self._highlight_font_family()\n            )''',1)
s=s.replace('''                if overlay.play(video,board,int(duration_ms),box):''','''                if overlay.play(video,board,int(duration_ms),box,self._highlight_font_family()):''',1)

# Update hint for remove button safety.
s=s.replace('''        self.highlight_remove_video_btn=QPushButton("删除选中")''','''        self.highlight_remove_video_btn=QPushButton("移出列表")\n        self.highlight_remove_video_btn.setToolTip("只从高光素材池移除，不删除磁盘上的视频文件。")''',1)


main.write_text(s,encoding='utf-8')
print('V0.9.2.2 patch part 3 complete')
