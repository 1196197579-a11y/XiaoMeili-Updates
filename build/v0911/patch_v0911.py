# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import sys
from pathlib import Path


def replace_method(text: str, name: str, next_name: str, new_method: str, label: str) -> str:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise RuntimeError(f"V0.9.1.1 missing method start: {label} / {name}")
    end = text.find(f"    def {next_name}(", start + 1)
    if end < 0:
        raise RuntimeError(f"V0.9.1.1 missing method end: {label} / {next_name}")
    return text[:start] + new_method + text[end:]


HIGHLIGHT_OVERLAY = r'''
class HighlightVideoOverlay(QWidget):
    """Lightweight occasional-use high-glow whiteboard player.

    Dedicated high-glow clips are stored muted. Frames are decoded only while a
    P100 highlight is visible, resized to the pet geometry first, then chroma
    keyed. Text is painted inside a normalized editable restriction box.
    """

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.view = QLabel(self)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setStyleSheet("background:transparent;")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.cap = None
        self.path = ""
        self.text = ""
        self.duration_ms = 1
        self.started_at = 0.0
        self.box = {"x":10.0,"y":57.0,"w":80.0,"h":30.0,"font_pct":5.8,"color":"black"}
        self._generation = 0

    def _sync_geometry(self):
        try:
            g = self.pet.frameGeometry()
            self.setGeometry(g)
            self.view.setGeometry(0,0,max(1,g.width()),max(1,g.height()))
        except Exception:
            pass

    @staticmethod
    def _green_alpha(frame):
        b,g,r = cv2.split(frame)
        mx = np.maximum(r,b).astype(np.int16)
        gi = g.astype(np.int16)
        # Pure/near-pure green background becomes transparent. A 28px feather
        # band keeps hair/outline edges from looking cut out.
        excess = gi - mx
        greenish = (g >= 80) & (excess >= 18)
        alpha = np.full(g.shape,255,dtype=np.uint8)
        feather = np.clip((36 - excess) * (255.0/18.0),0,255).astype(np.uint8)
        alpha[greenish] = feather[greenish]
        alpha[(g >= 110) & (excess >= 42)] = 0
        rgba = cv2.cvtColor(frame,cv2.COLOR_BGR2RGBA)
        rgba[:,:,3] = alpha
        return rgba

    def _paint_text(self, image):
        try:
            elapsed = max(0.0,(time.monotonic()-self.started_at)*1000.0)
            ratio = min(1.0, elapsed / max(250.0,float(self.duration_ms)))
            visible = self.text[:max(1,int(round(len(self.text)*ratio)))] if self.text else ""
            if not visible:
                return image

            h,w = image.height(), image.width()
            cfg = self.box if isinstance(self.box,dict) else {}
            x = int(w*float(cfg.get("x",10.0))/100.0)
            y = int(h*float(cfg.get("y",57.0))/100.0)
            rw = int(w*float(cfg.get("w",80.0))/100.0)
            rh = int(h*float(cfg.get("h",30.0))/100.0)
            rect = QRect(max(0,x),max(0,y),max(1,rw),max(1,rh))

            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
            color = str(cfg.get("color","black")).lower()
            painter.setPen(QColor("#FFFFFF" if color=="white" else "#111111"))
            px = max(10,int(round(w*float(cfg.get("font_pct",5.8))/100.0)))
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(px)
            font.setBold(True)
            painter.setFont(font)

            flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)
            painter.drawText(rect,flags,visible)
            painter.end()
        except Exception:
            LOGGER.exception("[HIGHLIGHT] draw text failed")
        return image

    def play(self, path, text, duration_ms, box=None):
        self.stop()
        self._generation += 1
        self.path = str(path or "")
        self.text = str(text or "")
        self.duration_ms = max(300,int(duration_ms or 3000))
        self.started_at = time.monotonic()
        if isinstance(box,dict):
            self.box = dict(box)

        try:
            self.cap = cv2.VideoCapture(self.path)
            if not self.cap or not self.cap.isOpened():
                raise RuntimeError("无法打开高光白板视频")
            fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 30.0)
            interval = int(max(20,min(66,1000.0/max(12.0,min(50.0,fps)))))
            self._sync_geometry()
            self.show()
            self.raise_()
            self.timer.start(interval)
            self._tick()
            return True
        except Exception:
            LOGGER.exception("[HIGHLIGHT] dedicated video play failed: %s",self.path)
            self.stop()
            return False

    def finish(self, hold_ms=800):
        generation = self._generation
        QTimer.singleShot(
            max(0,int(hold_ms)),
            lambda g=generation: self.stop() if g==self._generation else None,
        )

    def stop(self):
        try:self.timer.stop()
        except Exception:pass
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:pass
        self.cap = None
        try:self.hide()
        except Exception:pass

    def _tick(self):
        if self.cap is None:
            return
        try:
            ok,frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES,0)
                ok,frame = self.cap.read()
            if not ok:
                return
            self._sync_geometry()
            tw=max(2,self.width()); th=max(2,self.height())
            frame=cv2.resize(frame,(tw,th),interpolation=cv2.INTER_AREA)
            rgba=self._green_alpha(frame)
            q=QImage(rgba.data,tw,th,rgba.strides[0],QImage.Format.Format_RGBA8888).copy()
            q=self._paint_text(q)
            self.view.setPixmap(QPixmap.fromImage(q))
        except Exception:
            LOGGER.exception("[HIGHLIGHT] frame render failed")
'''


def patch_main(path: Path):
    s=path.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.9.1"' not in s:
        raise RuntimeError("V0.9.1.1 expected APP_VERSION 0.9.1 base")
    s=s.replace('APP_VERSION = "0.9.1"','APP_VERSION = "0.9.1.1"',1)

    # Imports used by the dedicated video/text overlay.
    import_anchor='from pathlib import Path\n'
    if import_anchor not in s:
        raise RuntimeError("V0.9.1.1 pathlib import anchor missing")
    s=s.replace(
        import_anchor,
        import_anchor+
        'from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont\n'
        'from PySide6.QtCore import QRect\n',
        1,
    )

    # Insert high-glow renderer before SettingsDialog so both Settings preview
    # and AppController can instantiate it.
    class_anchor='class SettingsDialog(QDialog):\n'
    if class_anchor not in s:
        raise RuntimeError("V0.9.1.1 SettingsDialog anchor missing")
    s=s.replace(class_anchor,HIGHLIGHT_OVERLAY+'\n\n'+class_anchor,1)

    # --------------------------------------------------------------
    # 1) Random/highlight text must be the SAME phrase on voice + board.
    # --------------------------------------------------------------
    old_started='''        if tag=="highlight_cta":
            self._highlight_active=True
            board=str(self._highlight_cfg().get("board_text") or "愣着干嘛，点点关注呀！")
            try:
                if getattr(self.pet,"dialogue_board_active",False):
                    self.pet._end_dialogue_board()
            except Exception:
                pass
            self.pet.start_dialogue_board(board,int(duration_ms))
            return
'''
    new_started='''        if tag=="highlight_cta":
            self._highlight_active=True
            # V0.9.1.1: the whiteboard always follows the actual selected
            # random phrase. Voice and board can no longer drift apart.
            board=str(text or "").strip() or "愣着干嘛，点点关注呀！"
            try:
                if getattr(self.pet,"dialogue_board_active",False):
                    self.pet._end_dialogue_board()
            except Exception:
                pass

            video=str(getattr(self,"_highlight_pending_video","") or "")
            box=self._highlight_cfg().get("text_box") or {}
            if video:
                overlay=self._ensure_highlight_overlay()
                if overlay.play(video,board,int(duration_ms),box):
                    return
            self.pet.start_dialogue_board(board,int(duration_ms))
            return
'''
    if old_started not in s:
        raise RuntimeError("V0.9.1.1 highlight playback-start anchor missing")
    s=s.replace(old_started,new_started,1)

    old_fallback='''        phrase=self._pick_highlight_phrase()
        voice=self._speech_voice_cfg()
        vid=str(voice.get("voice_id") or "")
        if not vid or not self.voice_service.ready():
            LOGGER.warning("[HIGHLIGHT] voice unavailable, showing board only")
            text=str(self._highlight_cfg().get("board_text") or "愣着干嘛，点点关注呀！")
            self.pet.preview_dialogue(text,4200)
            QTimer.singleShot(4400,lambda:setattr(self,"_highlight_active",False))
            return
'''
    new_fallback='''        phrase=self._pick_highlight_phrase()
        self._highlight_pending_video=self._pick_highlight_video()
        voice=self._speech_voice_cfg()
        vid=str(voice.get("voice_id") or "")
        if not vid or not self.voice_service.ready():
            LOGGER.warning("[HIGHLIGHT] voice unavailable, showing board only")
            video=str(self._highlight_pending_video or "")
            if video and self._ensure_highlight_overlay().play(
                video,phrase,4200,self._highlight_cfg().get("text_box") or {}
            ):
                QTimer.singleShot(4200,lambda:self._highlight_overlay.finish(700))
            else:
                self.pet.preview_dialogue(phrase,4200)
            QTimer.singleShot(5000,lambda:setattr(self,"_highlight_active",False))
            return
'''
    if old_fallback not in s:
        raise RuntimeError("V0.9.1.1 highlight fallback anchor missing")
    s=s.replace(old_fallback,new_fallback,1)

    old_finished='''        if tag=="highlight_cta":
            try:
                self.pet.finish_dialogue_board(900)
            except Exception:
                pass
            self._highlight_active=False
'''
    new_finished='''        if tag=="highlight_cta":
            try:
                if getattr(self,"_highlight_overlay",None) and self._highlight_overlay.isVisible():
                    self._highlight_overlay.finish(900)
                else:
                    self.pet.finish_dialogue_board(900)
            except Exception:
                pass
            self._highlight_pending_video=""
            self._highlight_active=False
'''
    if old_finished not in s:
        raise RuntimeError("V0.9.1.1 highlight finish anchor missing")
    s=s.replace(old_finished,new_finished,1)

    # Controller video shuffle bag + renderer helpers.
    helper_anchor='''    def _highlight_phrases_list(self):
        values=self._highlight_cfg().get("phrases") or ["愣着干嘛，点点关注呀！"]
        values=[str(x or "").strip() for x in values if str(x or "").strip()]
        return values or ["愣着干嘛，点点关注呀！"]

'''
    if helper_anchor not in s:
        raise RuntimeError("V0.9.1.1 highlight helper anchor missing")
    helper_extra=helper_anchor+r'''    def _highlight_videos_list(self):
        values=self._highlight_cfg().get("videos") or []
        out=[]
        for value in values if isinstance(values,list) else []:
            p=str(value or "").strip()
            if p and Path(p).exists() and p not in out:
                out.append(p)
        return out

    def _pick_highlight_video(self):
        values=self._highlight_videos_list()
        if not values:
            return ""
        key=tuple(values)
        if getattr(self,"_highlight_video_key",None)!=key:
            self._highlight_video_key=key
            self._highlight_video_bag=[]
        bag=list(getattr(self,"_highlight_video_bag",[]) or [])
        if not bag:
            bag=list(values)
            ASSET_RNG.shuffle(bag)
            last=str(getattr(self,"_highlight_last_video","") or "")
            if len(bag)>1 and bag[0]==last:
                bag[0],bag[1]=bag[1],bag[0]
        chosen=bag.pop(0)
        self._highlight_video_bag=bag
        self._highlight_last_video=chosen
        return chosen

    def _ensure_highlight_overlay(self):
        if getattr(self,"_highlight_overlay",None) is None:
            self._highlight_overlay=HighlightVideoOverlay(self.pet)
        return self._highlight_overlay

'''
    s=s.replace(helper_anchor,helper_extra,1)

    ctrl_anchor='''        self._highlight_phrase_key=None
        self._highlight_phrase_bag=[]
'''
    ctrl_new='''        self._highlight_phrase_key=None
        self._highlight_phrase_bag=[]
        self._highlight_pending_video=""
        self._highlight_overlay=None
        self._highlight_video_key=None
        self._highlight_video_bag=[]
        self._highlight_last_video=""
'''
    if ctrl_anchor not in s:
        raise RuntimeError("V0.9.1.1 controller bag init anchor missing")
    s=s.replace(ctrl_anchor,ctrl_new,1)

    # --------------------------------------------------------------
    # 2) Highlight video manager UI.
    # --------------------------------------------------------------
    ui_anchor='''        self.highlight_phrases.setPlainText("\\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        preview_row=QWidget()
'''
    if ui_anchor not in s:
        raise RuntimeError("V0.9.1.1 highlight manager UI anchor missing")
    ui_new='''        self.highlight_phrases.setPlainText("\\n".join(str(x) for x in _phrases if str(x).strip()))
        hf.addRow("随机播报池（每行一句）",self.highlight_phrases)

        # Dedicated high-glow video pool. Imported MP4s are re-encoded without
        # audio into XiaoMeiliData so source-track audio can never leak into TTS.
        video_panel=QWidget()
        video_l=QVBoxLayout(video_panel); video_l.setContentsMargins(0,0,0,0); video_l.setSpacing(6)
        self.highlight_video_list=QListWidget()
        self.highlight_video_list.setMinimumHeight(82)
        for _p in hcfg.get("videos",[]) if isinstance(hcfg.get("videos"),list) else []:
            if str(_p or "").strip():
                _item=QListWidgetItem(Path(str(_p)).name)
                _item.setData(Qt.ItemDataRole.UserRole,str(_p))
                self.highlight_video_list.addItem(_item)
        video_l.addWidget(self.highlight_video_list)
        _vr=QHBoxLayout()
        self.highlight_import_video_btn=QPushButton("导入白板视频")
        self.highlight_remove_video_btn=QPushButton("删除选中")
        self.highlight_preview_video_btn=QPushButton("预览选中")
        self.highlight_text_box_btn=QPushButton("文字与限制框")
        self.highlight_import_video_btn.clicked.connect(self._v0911_import_highlight_videos)
        self.highlight_remove_video_btn.clicked.connect(self._v0911_remove_highlight_video)
        self.highlight_preview_video_btn.clicked.connect(self._v0911_preview_selected_video)
        self.highlight_text_box_btn.clicked.connect(self._v0911_edit_highlight_text_box)
        for _b in (self.highlight_import_video_btn,self.highlight_remove_video_btn,self.highlight_preview_video_btn,self.highlight_text_box_btn):
            _vr.addWidget(_b)
        _vr.addStretch(1)
        video_l.addLayout(_vr)
        _vh=QLabel("支持多支 1:1 绿幕 MP4；导入时自动生成无音轨副本。实战和随机预览会轮换视频。")
        _vh.setWordWrap(True); _vh.setObjectName("pageSubtitle"); video_l.addWidget(_vh)
        hf.addRow("高光白板视频",video_panel)

        preview_row=QWidget()
'''
    s=s.replace(ui_anchor,ui_new,1)

    # Rename the fixed board field so its limited role is clear.
    s=s.replace('hf.addRow("白板文字",self.highlight_board_text)',
                'hf.addRow("仅预览白板文字",self.highlight_board_text)',1)

    # Persist imported video paths and text box settings through normal apply.
    save_anchor='''        if hasattr(self,"highlight_phrases"):
            hcfg["phrases"]=[x.strip() for x in self.highlight_phrases.toPlainText().splitlines() if x.strip()]
'''
    save_new=save_anchor+'''        if hasattr(self,"highlight_video_list"):
            hcfg["videos"]=[
                str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
                for i in range(self.highlight_video_list.count())
                if str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
            ]
'''
    if save_anchor not in s:
        raise RuntimeError("V0.9.1.1 highlight save anchor missing")
    s=s.replace(save_anchor,save_new,1)

    # Settings methods: import muted video, selected preview, text-box editor.
    method_anchor='''    def _v091_editor_highlight_phrases(self):
'''
    if method_anchor not in s:
        raise RuntimeError("V0.9.1.1 settings method anchor missing")
    methods=r'''    def _v0911_highlight_video_dir(self):
        p=Path(xiaomeili_logical_data_root())/"highlight_cta"/"videos"
        p.mkdir(parents=True,exist_ok=True)
        return p

    def _v0911_mute_copy_video(self, source, target):
        cap=cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise RuntimeError("无法读取视频")
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if w<=0 or h<=0:
            cap.release(); raise RuntimeError("无法读取视频尺寸")
        writer=cv2.VideoWriter(
            str(target),cv2.VideoWriter_fourcc(*"mp4v"),
            max(1.0,fps),(w,h)
        )
        if not writer.isOpened():
            cap.release(); raise RuntimeError("无法创建无音轨视频")
        written=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok: break
                writer.write(frame); written+=1
        finally:
            cap.release(); writer.release()
        if written<2 or not Path(target).exists() or Path(target).stat().st_size<4096:
            raise RuntimeError("视频转码失败")
        return written,fps

    def _v0911_import_highlight_videos(self):
        paths,_=QFileDialog.getOpenFileNames(
            self,"导入高光白板视频","",
            "视频文件 (*.mp4 *.mov *.avi *.mkv);;所有文件 (*.*)"
        )
        if not paths:return
        outdir=self._v0911_highlight_video_dir()
        ok_count=0; errors=[]
        for source in paths[:20]:
            try:
                src=Path(source)
                stamp=time.strftime("%Y%m%d_%H%M%S")
                target=outdir/f"{src.stem}_{stamp}_{ok_count+1}_muted.mp4"
                self._v0911_mute_copy_video(src,target)
                item=QListWidgetItem(target.name)
                item.setData(Qt.ItemDataRole.UserRole,str(target))
                self.highlight_video_list.addItem(item)
                ok_count+=1
            except Exception as exc:
                errors.append(f"{Path(source).name}: {exc}")
        self._v0911_save_highlight_editor_state()
        msg=f"成功导入 {ok_count} 支高光白板视频。导入副本不包含原生音轨。"
        if errors: msg+="\\n\\n失败：\\n"+"\\n".join(errors[:6])
        QMessageBox.information(self,"高光白板视频",msg)

    def _v0911_remove_highlight_video(self):
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

    def _v0911_save_highlight_editor_state(self):
        hcfg=self.cfg.setdefault("highlight_cta",{})
        if hasattr(self,"highlight_video_list"):
            hcfg["videos"]=[
                str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "")
                for i in range(self.highlight_video_list.count())
                if str(self.highlight_video_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
            ]
        save_config(self.cfg)
        try:self.config_changed.emit()
        except Exception:pass

    def _v0911_selected_highlight_video(self):
        if not hasattr(self,"highlight_video_list") or self.highlight_video_list.count()<=0:
            return ""
        item=self.highlight_video_list.currentItem() or self.highlight_video_list.item(0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _v0911_preview_overlay(self):
        if getattr(self,"_v0911_overlay",None) is None:
            self._v0911_overlay=HighlightVideoOverlay(self.pet)
        return self._v0911_overlay

    def _v0911_preview_selected_video(self):
        path=self._v0911_selected_highlight_video()
        if not path:
            QMessageBox.information(self,"高光白板视频","请先导入并选中一支视频。"); return
        phrase=self._v091_editor_highlight_phrases()[0]
        box=self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}
        if not self._v0911_preview_overlay().play(path,phrase,4200,box):
            QMessageBox.warning(self,"高光白板视频","视频预览失败，请检查素材编码。")
            return
        QTimer.singleShot(4200,lambda:self._v0911_preview_overlay().finish(500))

    def _v0911_edit_highlight_text_box(self):
        cfg=self.cfg.setdefault("highlight_cta",{})
        box=dict(cfg.get("text_box") or {})
        defaults={"x":10.0,"y":57.0,"w":80.0,"h":30.0,"font_pct":5.8,"color":"black"}
        for k,v in defaults.items(): box.setdefault(k,v)

        dlg=QDialog(self); dlg.setWindowTitle("高光白板｜文字与限制框"); dlg.resize(760,620)
        root=QVBoxLayout(dlg)
        title=QLabel("文字与限制框"); title.setObjectName("pageTitle"); root.addWidget(title)
        hint=QLabel("限制框使用视频百分比坐标，因此更换 1:1 素材或调整桌宠大小后仍会等比例保持。随机高光时，白板文字会与本次实际播报台词完全一致。")
        hint.setWordWrap(True); hint.setObjectName("pageSubtitle"); root.addWidget(hint)

        preview=QLabel(); preview.setMinimumSize(440,360); preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet("background:#18211f;border:1px solid #45605a;border-radius:10px;")
        root.addWidget(preview,1)

        form=QGridLayout()
        controls={}
        specs=[
            ("x","左边距 %",0.0,95.0,1.0),
            ("y","上边距 %",0.0,95.0,1.0),
            ("w","宽度 %",5.0,100.0,1.0),
            ("h","高度 %",5.0,100.0,1.0),
            ("font_pct","字号 %",1.5,14.0,0.2),
        ]
        for row,(key,label,lo,hi,step) in enumerate(specs):
            sp=QDoubleSpinBox(); sp.setRange(lo,hi); sp.setSingleStep(step); sp.setDecimals(1); sp.setValue(float(box.get(key,defaults[key])))
            controls[key]=sp; form.addWidget(QLabel(label),row*2//4,(row*2)%4); form.addWidget(sp,row*2//4,(row*2)%4+1)
        color=QComboBox(); color.addItem("黑色","black"); color.addItem("白色","white")
        idx=color.findData(str(box.get("color","black"))); color.setCurrentIndex(max(0,idx))
        form.addWidget(QLabel("文字颜色"),3,0); form.addWidget(color,3,1)
        root.addLayout(form)

        def current_box():
            return {k:float(w.value()) for k,w in controls.items()} | {"color":str(color.currentData() or "black")}

        def render_preview():
            path=self._v0911_selected_highlight_video()
            canvas=np.zeros((420,420,3),dtype=np.uint8); canvas[:]=(30,38,36)
            if path:
                cap=cv2.VideoCapture(path); ok,frame=cap.read(); cap.release()
                if ok: canvas=cv2.resize(frame,(420,420),interpolation=cv2.INTER_AREA)
            q=QImage(cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB).data,420,420,420*3,QImage.Format.Format_RGB888).copy()
            painter=QPainter(q); painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
            b=current_box()
            x=int(420*b["x"]/100); y=int(420*b["y"]/100); rw=int(420*b["w"]/100); rh=int(420*b["h"]/100)
            rect=QRect(x,y,max(1,rw),max(1,rh))
            painter.setPen(QColor("#35D5B0")); painter.drawRect(rect)
            painter.fillRect(rect,QColor(53,213,176,30))
            painter.setPen(QColor("#FFFFFF" if b["color"]=="white" else "#111111"))
            f=QFont("Microsoft YaHei UI"); f.setPixelSize(max(10,int(420*b["font_pct"]/100))); f.setBold(True); painter.setFont(f)
            painter.drawText(rect,int(Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap),"愣着干嘛，点点关注呀！")
            painter.end()
            preview.setPixmap(QPixmap.fromImage(q).scaled(preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        for w in controls.values(): w.valueChanged.connect(lambda *_:render_preview())
        color.currentIndexChanged.connect(lambda *_:render_preview())

        tools=QHBoxLayout()
        full=QPushButton("一键铺满")
        default=QPushButton("恢复默认")
        tools.addWidget(full); tools.addWidget(default); tools.addStretch(1); root.addLayout(tools)
        def do_full():
            vals={"x":5.0,"y":5.0,"w":90.0,"h":90.0}
            for k,v in vals.items(): controls[k].setValue(v)
        def do_default():
            for k,v in defaults.items():
                if k in controls: controls[k].setValue(float(v))
            color.setCurrentIndex(max(0,color.findData("black")))
        full.clicked.connect(do_full); default.clicked.connect(do_default)

        bottom=QHBoxLayout(); bottom.addStretch(1)
        cancel=QPushButton("取消"); save=QPushButton("保存并应用")
        bottom.addWidget(cancel); bottom.addWidget(save); root.addLayout(bottom)
        cancel.clicked.connect(dlg.reject)
        def commit():
            cfg["text_box"]=current_box()
            save_config(self.cfg)
            try:self.config_changed.emit()
            except Exception:pass
            dlg.accept()
        save.clicked.connect(commit)
        try:self._v0775_apply_native_titlebar(dlg,getattr(self,"_v0775_theme_mode","light")=="dark")
        except Exception:pass
        QTimer.singleShot(50,render_preview)
        dlg.exec()

'''
    s=s.replace(method_anchor,methods+method_anchor,1)

    # "仅预览白板" now previews the selected dedicated video when available.
    old_board_preview='''        if mode=="board":
            try:
                self.pet.preview_dialogue(board,4200)
            except Exception as exc:
                QMessageBox.warning(self,"高光预览",f"白板预览失败：{type(exc).__name__}: {exc}")
            return
'''
    new_board_preview='''        if mode=="board":
            path=self._v0911_selected_highlight_video()
            if path:
                if not self._v0911_preview_overlay().play(
                    path,board,4200,self.cfg.setdefault("highlight_cta",{}).get("text_box") or {}
                ):
                    QMessageBox.warning(self,"高光预览","专属白板视频预览失败。")
                else:
                    QTimer.singleShot(4200,lambda:self._v0911_preview_overlay().finish(500))
            else:
                try:self.pet.preview_dialogue(board,4200)
                except Exception as exc: QMessageBox.warning(self,"高光预览",f"白板预览失败：{type(exc).__name__}: {exc}")
            return
'''
    if old_board_preview not in s:
        raise RuntimeError("V0.9.1.1 board-only preview anchor missing")
    s=s.replace(old_board_preview,new_board_preview,1)

    # --------------------------------------------------------------
    # 3) Report snapshot gets the same large red/green status bar treatment.
    # --------------------------------------------------------------
    vision_anchor='''        self.vision_status.setText(text)
'''
    if vision_anchor not in s:
        raise RuntimeError("V0.9.1.1 vision status anchor missing")
    report_style='''        self.vision_status.setText(text)
        self._v0911_style_report_snapshot_bar()
'''
    s=s.replace(vision_anchor,report_style,1)

    report_helper_anchor='''    def _v091_scale_css(self, css, scale):
'''
    report_helper=r'''    def _v0911_style_report_snapshot_bar(self):
        try:
            for label in self.findChildren(QLabel):
                raw=str(label.text() or "").strip()
                if not raw.startswith("战报快照"):
                    continue
                locked=("已锁定" in raw) and ("未锁定" not in raw)
                label.setObjectName("reportSnapshotBar")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label.setMinimumHeight(54)
                label.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
                label.setStyleSheet(
                    "QLabel#reportSnapshotBar{"
                    + (
                        "background:#E1F7EA;color:#147A45;border:1px solid #8AD5AA;"
                        if locked else
                        "background:#FDE8E8;color:#B42318;border:1px solid #F4B4B4;"
                    )
                    + "border-radius:10px;padding:10px 14px;font-size:20px;font-weight:900;}"
                )
        except Exception:
            LOGGER.warning("战报快照状态条样式更新失败",exc_info=True)

'''
    if report_helper_anchor not in s:
        raise RuntimeError("V0.9.1.1 report helper insertion anchor missing")
    s=s.replace(report_helper_anchor,report_helper+report_helper_anchor,1)

    # Update note in high-glow panel.
    s=s.replace(
        "V0.9.0 测试版暂时复用当前通用白板动画。高光触发会抢占普通TTS/普通白板；播报使用小美丽当前固定声音。",
        "已支持导入专属高光白板视频；导入时自动去除原生音轨。随机台词会同时用于白板文字和小美丽TTS，并使用文字限制框排版。",
        1,
    )

    path.write_text(s,encoding="utf-8")
    py_compile.compile(str(path),doraise=True)


def patch_speech(path: Path):
    s=path.read_text(encoding="utf-8")
    s=s.replace("小美丽 V0.9.1 语音诊断日志","小美丽 V0.9.1.1 语音诊断日志")
    path.write_text(s,encoding="utf-8")
    py_compile.compile(str(path),doraise=True)


def patch_helper(path: Path):
    # Future updates must clear any process still executing modules from the
    # install directory before robocopy. This does not repair the currently
    # installed 0.9.1 helper, but V0.9.1.1 and later inherit the fix.
    helper=r'''param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][Alias('Pid')][int]$ParentPid,
    [Parameter(Mandatory=$true)][Alias('DesktopLog')][string]$LogPath,
    [Parameter(Mandatory=$true)][string]$DiagnosticDir
)
$ErrorActionPreference='Stop'
function Log([string]$s){
    $p=Split-Path -Parent $LogPath
    if($p){New-Item -ItemType Directory -Force -Path $p|Out-Null}
    Add-Content -LiteralPath $LogPath -Value ("[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $s") -Encoding UTF8
}
function Stop-Residual {
    try{
        $tl=$Target.ToLowerInvariant()
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
            $exe=[string]$_.ExecutablePath; $cmd=[string]$_.CommandLine; $name=[string]$_.Name
            $hit=($name -ieq $ExeName) -or ($exe -and $exe.ToLowerInvariant().StartsWith($tl)) -or ($cmd -and $cmd.ToLowerInvariant().Contains($tl))
            if($hit -and [int]$_.ProcessId -ne $PID){
                try{Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue; Log "Stopped residual PID=$($_.ProcessId) $name"}catch{}
            }
        }
    }catch{Log "Residual scan warning: $($_.Exception.Message)"}
    Start-Sleep -Seconds 2
}
function Robo([string]$src,[string]$dst,[string]$label){
    $detail=Join-Path (Split-Path -Parent $LogPath) ("robocopy_"+(Get-Date -Format 'yyyyMMdd_HHmmss')+".log")
    & robocopy.exe $src $dst /MIR /COPY:DAT /DCOPY:DAT /R:6 /W:1 /XJ /NP /TEE /LOG:$detail
    $rc=$LASTEXITCODE; Log "$label exit=$rc detail=$detail"
    if($rc -ge 8){Stop-Residual; & robocopy.exe $src $dst /MIR /COPY:DAT /DCOPY:DAT /R:10 /W:1 /XJ /NP /TEE /LOG+:$detail; $rc=$LASTEXITCODE; Log "$label retry exit=$rc"}
    if($rc -ge 8){throw "$label failed, robocopy exit=$rc, detail=$detail"}
}
try{
    Log "Updater start package=$Package target=$Target parent=$ParentPid"
    for($i=0;$i -lt 40;$i++){if(-not(Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)){break};Start-Sleep -Milliseconds 250}
    if(Get-Process -Id $ParentPid -ErrorAction SilentlyContinue){Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue}
    Stop-Residual
    if(-not(Test-Path -LiteralPath $Package)){throw "Package missing: $Package"}
    $root=Split-Path -Parent $Package; $work=Join-Path $root ("work_"+[Guid]::NewGuid()); $backup=Join-Path $root ("backup_"+[Guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $work,$backup|Out-Null
    Expand-Archive -LiteralPath $Package -DestinationPath $work -Force
    $payload=$work
    if(-not(Test-Path (Join-Path $payload $ExeName))){
        $nested=Get-ChildItem $work -Directory|Where-Object{Test-Path (Join-Path $_.FullName $ExeName)}|Select-Object -First 1
        if(-not $nested){throw "Package missing $ExeName"};$payload=$nested.FullName
    }
    Robo $Target $backup "backup"
    Stop-Residual
    Robo $payload $Target "update"
    $exe=Join-Path $Target $ExeName
    Start-Process -FilePath $exe -WorkingDirectory $Target
    Log "Updater finished successfully"
}catch{
    try{Log ("ERROR: "+$_.Exception.Message);Log ($_|Out-String)}catch{}
    exit 1
}
exit 0
'''
    path.write_text(helper,encoding="utf-8")


def patch(source_root: Path):
    root=Path(source_root).resolve()
    main=root/"app"/"src"/"main.py"
    speech=root/"app"/"src"/"speech_input.py"
    helper=root/"app"/"assets"/"update_helper.ps1"
    for p in (main,speech,helper):
        if not p.exists(): raise FileNotFoundError(p)
    patch_main(main)
    patch_speech(speech)
    patch_helper(helper)

    m=main.read_text(encoding="utf-8")
    sp=speech.read_text(encoding="utf-8")
    checks=[
        'APP_VERSION = "0.9.1.1"',
        'class HighlightVideoOverlay(QWidget):',
        '高光白板视频',
        '导入白板视频',
        '文字与限制框',
        'def _v0911_mute_copy_video',
        'def _pick_highlight_video',
        'board=str(text or "").strip()',
        'def _v0911_style_report_snapshot_bar',
        'reportSnapshotBar',
    ]
    for token in checks:
        if token not in m: raise RuntimeError("V0.9.1.1 verification failed: "+token)
    if "小美丽 V0.9.1.1 语音诊断日志" not in sp:
        raise RuntimeError("V0.9.1.1 speech label missing")
    print("Patched XiaoMeili source to V0.9.1.1 highlight video/template hotfix")


if __name__=="__main__":
    if len(sys.argv)!=2: raise SystemExit("usage: patch_v0911.py <source_root>")
    patch(Path(sys.argv[1]))
