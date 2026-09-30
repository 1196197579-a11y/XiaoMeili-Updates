from pathlib import Path
import re, textwrap, shutil, json, os
import sys
if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v0922.py <source_root>')
root=Path(sys.argv[1]).resolve()
main=root/'app/src/main.py'
s=main.read_text(encoding='utf-8')

# Version bump
s=s.replace('APP_NAME = "小美丽 V0.9.1｜Voice Interaction"', 'APP_NAME = "小美丽 V0.9.2.2｜Voice Interaction"', 1)
s=s.replace('APP_VERSION = "0.9.2.1"', 'APP_VERSION = "0.9.2.2"', 1)

# Insert highlight normalization helper after normalized_whiteboard_layout.
marker='''    out["outline_color"] = str(out.get("outline_color") or "#F6FFF9")\n    return out\n\n\ndef _dialogue_wrap_lines'''
insert='''    out["outline_color"] = str(out.get("outline_color") or "#F6FFF9")\n    return out\n\n\nDEFAULT_HIGHLIGHT_TEXT_LAYOUT = {\n    "x": 0.10, "y": 0.57, "w": 0.80, "h": 0.30,\n    "offset_x": 0.0, "offset_y": 0.0,\n    "min_font_px": 13, "max_font_px": 42, "font_scale": 1.0,\n    "line_spacing": 1.02, "max_lines": 4,\n    "text_color": "#08423A", "outline_color": "#F6FFF9", "outline_width": 0.0,\n    "auto_fill": True, "hold_ms": 3000,\n}\n\n\ndef normalized_highlight_text_layout(value, whiteboard_style=None):\n    """Normalize V0.9.2.2 highlight text boxes to the same layout engine as dialogue whiteboards.\n\n    V0.9.1.1/V0.9.2.1 stored x/y/w/h and font_pct as percentages.  Keep those\n    positions when migrating, but intentionally adopt the dialogue-board font\n    family/fitting rules requested for V0.9.2.2.\n    """\n    raw = dict(value) if isinstance(value, dict) else {}\n    base = dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)\n    wb = normalized_whiteboard_layout(whiteboard_style or {})\n    for key in ("min_font_px", "max_font_px", "font_scale", "line_spacing", "max_lines",\n                "text_color", "outline_color", "outline_width", "auto_fill"):\n        base[key] = wb.get(key, base[key])\n\n    legacy_percent = False\n    for key in ("x", "y", "w", "h"):\n        try:\n            if float(raw.get(key, 0.0)) > 1.0:\n                legacy_percent = True\n                break\n        except Exception:\n            pass\n    if legacy_percent:\n        for key in ("x", "y", "w", "h"):\n            if key in raw:\n                try: base[key] = float(raw[key]) / 100.0\n                except Exception: pass\n        # Legacy color was independent of the dialogue template.  V0.9.2.2\n        # intentionally follows the dialogue-board typography by default.\n    else:\n        for key in base:\n            if key in raw:\n                base[key] = raw[key]\n    return normalized_whiteboard_layout(base)\n\n\ndef _dialogue_wrap_lines'''
if marker not in s:
    raise RuntimeError('normalization insert marker missing')
s=s.replace(marker,insert,1)

# Replace HighlightVideoOverlay class.
start=s.index('class HighlightVideoOverlay(QWidget):')
end=s.index('\n\nclass SettingsDialog(QDialog):', start)
new_class=r'''class HighlightVideoOverlay(QWidget):
    """Dedicated high-glow whiteboard player with isolated base-pet rendering.

    V0.9.2.2 uses exactly the same typography/layout engine as the dialogue
    whiteboard.  While this overlay is visible the normal pet window is hidden,
    so the idle animation can never ghost through the green-screen background.
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
        self.layout_cfg = dict(DEFAULT_HIGHLIGHT_TEXT_LAYOUT)
        self.font_family = "Microsoft YaHei"
        self._generation = 0
        self._pet_was_visible = False
        self._pet_hidden_by_overlay = False
        self._cached_geometry = QRect()

    def _sync_geometry(self):
        try:
            if self.pet.isVisible() or self._cached_geometry.isNull():
                self._cached_geometry = QRect(self.pet.frameGeometry())
            g = self._cached_geometry
            if g.isNull():
                g = self.pet.frameGeometry()
            self.setGeometry(g)
            self.view.setGeometry(0,0,max(1,g.width()),max(1,g.height()))
        except Exception:
            pass

    def _hide_base_pet(self):
        try:
            self._pet_was_visible = bool(self.pet.isVisible())
            self._sync_geometry()
            if self._pet_was_visible:
                self.pet.hide()
                self._pet_hidden_by_overlay = True
        except Exception:
            LOGGER.warning("[HIGHLIGHT] hide base pet failed", exc_info=True)

    def _restore_base_pet(self):
        if not self._pet_hidden_by_overlay:
            return
        self._pet_hidden_by_overlay = False
        try:
            if self._pet_was_visible:
                self.pet.show()
                self.pet.raise_()
                QTimer.singleShot(30, self.pet.apply_clickthrough_native)
        except Exception:
            LOGGER.warning("[HIGHLIGHT] restore base pet failed", exc_info=True)

    @staticmethod
    def _green_alpha(frame):
        b,g,r = cv2.split(frame)
        mx = np.maximum(r,b).astype(np.int16)
        gi = g.astype(np.int16)
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
            reveal = max(1,int(round(len(self.text)*ratio))) if self.text else 0
            if reveal <= 0:
                return image
            pm = render_dialogue_text_pixmap(
                image.width(), image.height(), self.layout_cfg,
                self.text, self.font_family, reveal,
            )
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
            painter.drawPixmap(0,0,pm)
            painter.end()
        except Exception:
            LOGGER.exception("[HIGHLIGHT] draw text failed")
        return image

    def play(self, path, text, duration_ms, box=None, font_family=None):
        self.stop()
        self._generation += 1
        self.path = str(path or "")
        self.text = str(text or "")
        self.duration_ms = max(300,int(duration_ms or 3000))
        self.started_at = time.monotonic()
        self.layout_cfg = normalized_highlight_text_layout(
            box if isinstance(box,dict) else {},
            self.pet.cfg.get("whiteboard",{}) if isinstance(getattr(self.pet,"cfg",None),dict) else {},
        )
        self.font_family = str(font_family or getattr(getattr(self.pet,"dialogue_overlay",None),"font_family","") or "Microsoft YaHei")

        try:
            self.cap = cv2.VideoCapture(self.path)
            if not self.cap or not self.cap.isOpened():
                raise RuntimeError("无法打开高光白板视频")
            fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 30.0)
            interval = int(max(20,min(66,1000.0/max(12.0,min(50.0,fps)))))
            self._hide_base_pet()
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
        self._restore_base_pet()

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
s=s[:start]+new_class+s[end:]


main.write_text(s,encoding='utf-8')
print('V0.9.2.2 patch part 1 complete')
