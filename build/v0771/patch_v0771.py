# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import py_compile
import re
import sys
from pathlib import Path


EYE_ASSETS_B64 = {
    "eye_white_left.webp": """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""",
    "eye_white_right.webp": """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""",
    "pupil_left.webp": """UklGRiQFAABXRUJQVlA4WAoAAAAQAAAA/wEA/wEAQUxQSN0BAAABkHJrmyI5b9UXZmaS7KOZmRkdM1nmxOesjWX8CzmxzKBYLVR3Vc+32K2/0BsREwD6n/6n/+l/+p/+p//pf/qf/qf/6X/6n/6n/+l/+p/+p//pf/qf/qf/6X/6n/6n/+l/+p/+p//pf/qf/qf/6X/6/z8nfedO7YqzurJenMF5TDm078CB/Qd2zhgMQJy5CW5ohz/ubR0AiLE59HgVG0NoagpRVT8f6wWxNY/xsUjtxyxTfTYb3lmaYJ7mHaSUYpPWTsA7Q+uEHZoXRUcphVyvQExtT5uiRIqZnoNY2s52SqYUg66DmJlgjcZyRVHk6fto5+1sqqZKKWgdxMocBn7VVCnFMAneyOBxr5ZXKVLQaxArE6zVakXUT73hjMy57s9qeaWU60yIkUGwWLNKRdCTdgbBdQ2VMn0Ib2bOd3usoUquz7vBWRk8et3TGMtF/TUC3szg4S+q5rFEirX6cZYG5zDzqWrMYmo/10/94QwNTtB58xNVzUMWY0pNtZvwsHUBML3ug6pqkWeqsyDGBicA+k07+fBLpvpuLxzs3YkAQO/Jy5cNgNU76eTQ1ltdW+c7iQP9T//T//Q//U//0//0P/1P/9P/9D/9T//T//Q//U//0//0P/1P/9P/dggAVlA4ICADAAAQPwCdASoAAgACPj0ejkWiIaEQHAQAIAPEtLdwu7CO8vI1EiI/F2AGe5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPYhJXcvpdrxcnIe+2TkPfbHAcRfK8QlyxRsDOuzWX/YFC5fzych77ZOQ99snIe9IwbvOW3RI9BfSDX0ga0v09snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych77ZOQ99snIe+2TkPfbJyHvtk5D32ych6wAA/v/2GQAAAAAAAAAAAAAAAAAAA0fwJVsH84Wjrugeb55CFP4uiqSaEUdTzYg7iDkyrlaymEIxe3u+/5tp/5cb/3iO/kt//z2HeTXoP/9x4EWnEYzAVIi1rms5Zd+P3etkUxQn6oCr0TFf72O66td9uokavoDDNv79PVBNVGN9YfzK8/bfTkFspcs4wxoVJS/QymGpIVcjnlOSKcTN68AhGd0TU01sDuWdniU3xrOH7z5BXCkyofBaNrMOZr2yVkWj4XMEg81AevJ60L8YNPt19oB3Bf3rNnhSi2EGvjjkLQ5yORDTBnylB2ptCNoOvHZkd+RL8grH2ecMaPxA2KKnv77m/0PeCe6dF4FTMVyyRGU9rgAAAAAAAAAAAAAAAA==""",
    "pupil_right.webp": """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"""
}


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.1 anchor: {label}")
    return text.replace(old, new, 1)


def install_eye_assets(source_root: Path):
    out = source_root / "app" / "assets" / "drag_interaction"
    out.mkdir(parents=True, exist_ok=True)
    for name, encoded in EYE_ASSETS_B64.items():
        data = base64.b64decode(encoded)
        if len(data) < 500 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise RuntimeError(f"invalid embedded eye asset: {name}")
        (out / name).write_bytes(data)


def patch(source_root: Path):
    install_eye_assets(source_root)
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7"',
        'APP_NAME = "小美丽 V0.7.7.1｜Drag Interaction Hotfix"\nAPP_VERSION = "0.7.7.1"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    start = s.index("class DragInteractionLayer(QWidget):\n")
    end = s.index("\n\nclass PetWindow(QWidget):\n", start)

    drag_class = r'''class DragInteractionLayer(QWidget):
    """V0.7.7.1 layered drag pose.

    Fixes:
    * hair_front2 is rendered UNDER the face, matching the supplied layer relationship;
    * the eye whites are restored over the baked head-group pupils, then two pupil layers
      move independently so the dragged pose has live gaze;
    * body/head/front hair/ponytail/earrings use stronger but still subtle inertia.
    """
    settled = Signal()

    ASSET_FILES = {
        "back": "hair_back.webp",
        "body": "body.webp",
        "head": "head_group.webp",
        "earrings": "earrings.webp",
        "front2": "hair_front2.webp",
        "front": "hair_front.webp",
        "eye_white_left": "eye_white_left.webp",
        "eye_white_right": "eye_white_right.webp",
        "pupil_left": "pupil_left.webp",
        "pupil_right": "pupil_right.webp",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.pix = {}
        for key, filename in self.ASSET_FILES.items():
            p = resource(f"assets/drag_interaction/{filename}")
            pm = QPixmap(p)
            if pm.isNull():
                LOGGER.error("拖拽互动图层加载失败: %s", p)
            self.pix[key] = pm

        self.active = False
        self.recovering = False
        self.recover_started = 0.0

        self.target_x = self.target_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.front2_x = self.front2_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.swing_x = 0.0

        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.hide()

    @staticmethod
    def _follow(current, target, smooth):
        return current + (target - current) * smooth

    def reset_pose(self):
        self.target_x = self.target_y = 0.0
        self.body_x = self.body_y = 0.0
        self.head_x = self.head_y = 0.0
        self.front_x = self.front_y = 0.0
        self.front2_x = self.front2_y = 0.0
        self.back_x = self.back_y = 0.0
        self.ear_x = self.ear_y = 0.0
        self.swing_x = 0.0
        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.recovering = False
        self.recover_started = 0.0
        self.update()

    def start_drag(self):
        self.reset_pose()
        self.active = True
        self.recovering = False
        self.show()
        self.raise_()
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def feed_motion(self, dx, dy):
        if not self.active:
            return
        nx = max(-1.0, min(1.0, float(dx) / 16.0))
        ny = max(-1.0, min(1.0, float(dy) / 16.0))

        # The pet follows the pointer instantly as a window, while the drawn parts lag behind.
        self.target_x = -nx
        self.target_y = -ny
        self.swing_x = self._follow(self.swing_x, -nx, 0.64)

        # During a physical drag the pointer is attached to the pet, so use drag direction as
        # the live gaze target. This produces the same "eyes are paying attention" feeling as V2.
        self.gaze_target_x = nx
        self.gaze_target_y = ny
        self.motion_energy = min(1.0, self.motion_energy + (abs(nx) + abs(ny)) * 0.28)

    def begin_recover(self):
        if not self.active:
            return
        self.recovering = True
        self.recover_started = time.monotonic()
        self.target_x = self.target_y = 0.0
        self.gaze_target_x = self.gaze_target_y = 0.0
        if not self.timer.isActive():
            self.timer.start()

    def cancel(self):
        self.active = False
        self.recovering = False
        self.timer.stop()
        self.reset_pose()
        self.hide()

    def _tick(self):
        if not self.active:
            self.timer.stop()
            return

        # Preserve an impulse long enough to be visible instead of snapping back within 1-2 frames.
        self.target_x *= 0.82
        self.target_y *= 0.82
        self.gaze_target_x *= 0.88
        self.gaze_target_y *= 0.88
        self.motion_energy *= 0.91

        self.body_x = self._follow(self.body_x, self.target_x * 0.46, 0.16)
        self.body_y = self._follow(self.body_y, self.target_y * 0.34, 0.15)

        self.head_x = self._follow(self.head_x, self.target_x * 0.64, 0.20)
        self.head_y = self._follow(self.head_y, self.target_y * 0.50, 0.19)

        self.front2_x = self._follow(self.front2_x, self.target_x * 0.72, 0.16)
        self.front2_y = self._follow(self.front2_y, self.target_y * 0.56, 0.15)
        self.front_x = self._follow(self.front_x, self.target_x * 0.92, 0.14)
        self.front_y = self._follow(self.front_y, self.target_y * 0.70, 0.13)

        self.back_x = self._follow(self.back_x, self.target_x * 1.28, 0.095)
        self.back_y = self._follow(self.back_y, self.target_y * 0.98, 0.09)
        self.ear_x = self._follow(self.ear_x, self.target_x * 1.36, 0.105)
        self.ear_y = self._follow(self.ear_y, self.target_y * 1.02, 0.10)
        self.swing_x *= 0.86

        self.gaze_x = self._follow(self.gaze_x, self.gaze_target_x, 0.30)
        self.gaze_y = self._follow(self.gaze_y, self.gaze_target_y, 0.28)

        self.update()

        if self.recovering:
            values = (
                self.body_x, self.body_y, self.head_x, self.head_y,
                self.front_x, self.front_y, self.front2_x, self.front2_y,
                self.back_x, self.back_y, self.ear_x, self.ear_y,
                self.swing_x, self.gaze_x, self.gaze_y,
            )
            elapsed = time.monotonic() - self.recover_started
            if elapsed >= 0.32 or max(abs(v) for v in values) < 0.010:
                self.active = False
                self.recovering = False
                self.timer.stop()
                self.reset_pose()
                self.hide()
                self.settled.emit()

    def _draw(self, painter, key, base_x, base_y, side, nx=0.0, ny=0.0,
              rot=0.0, pivot=(0.5, 0.5), extra_px_x=0.0, extra_px_y=0.0):
        pm = self.pix.get(key)
        if pm is None or pm.isNull():
            return
        dx = float(nx) * side * 0.040 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.030 + float(extra_px_y) * (side / 512.0)
        px = base_x + side * float(pivot[0])
        py = base_y + side * float(pivot[1])
        painter.save()
        painter.translate(px + dx, py + dy)
        if rot:
            painter.rotate(float(rot))
        painter.translate(-px, -py)
        painter.drawPixmap(
            QRectF(base_x, base_y, side, side),
            pm,
            QRectF(0.0, 0.0, float(pm.width()), float(pm.height())),
        )
        painter.restore()

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return

        canvas = QImage(self.width(), self.height(), QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)
        cp = QPainter(canvas)
        cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        side = float(min(self.width(), self.height()))
        x0 = (float(self.width()) - side) * 0.5
        y0 = (float(self.height()) - side) * 0.5

        # Correct PSD-style z order:
        # back hair -> body -> tiny front2 lock BEHIND face -> head/eyes -> earrings -> main front hair.
        self._draw(cp, "back", x0, y0, side, self.back_x, self.back_y,
                   rot=self.back_x * 5.2 + self.swing_x * 2.6, pivot=(0.62, 0.28))
        self._draw(cp, "body", x0, y0, side, self.body_x, self.body_y,
                   rot=self.body_x * 2.0, pivot=(0.52, 0.48))
        self._draw(cp, "front2", x0, y0, side, self.front2_x, self.front2_y,
                   rot=self.front2_x * 2.5 + self.swing_x * 0.9, pivot=(0.30, 0.70))

        head_rot = self.head_x * 2.8
        self._draw(cp, "head", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))

        # Eye whites cover the pupils baked into the old head_group, then live pupils are redrawn.
        self._draw(cp, "eye_white_left", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))
        self._draw(cp, "eye_white_right", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))

        eye_dx = max(-3.4, min(3.4, self.gaze_x * 3.4))
        eye_dy = max(-2.2, min(2.2, self.gaze_y * 2.2))
        self._draw(cp, "pupil_left", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42), extra_px_x=eye_dx, extra_px_y=eye_dy)
        self._draw(cp, "pupil_right", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42), extra_px_x=eye_dx, extra_px_y=eye_dy)

        self._draw(cp, "earrings", x0, y0, side, self.ear_x, self.ear_y,
                   rot=self.ear_x * 6.0 + self.swing_x * 2.0, pivot=(0.50, 0.48))
        self._draw(cp, "front", x0, y0, side, self.front_x, self.front_y,
                   rot=self.front_x * 4.4 + self.swing_x * 1.8, pivot=(0.45, 0.36))
        cp.end()

        rgba = MouseInteractionLayer._qimage_rgba_array(canvas)
        rgba = _add_soft_white_glow(
            rgba, outline_px=1, glow_px=4,
            outline_strength=0.42, glow_strength=0.24,
        )
        rgba = np.ascontiguousarray(rgba)
        final_img = QImage(
            rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
            QImage.Format.Format_RGBA8888,
        ).copy()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(0, 0, final_img)
        p.end()
'''

    s = s[:start] + drag_class + s[end:]

    # Remove the mouse-interaction fade race while a press/drag is in progress.
    s = must(
        s,
        '''            if self.drag_offset is not None:
                if self.mouse_interaction_active: self._exit_mouse_interaction(resume_idle=True)
                return
''',
        '''            if self.drag_offset is not None or self.drag_visual_active:
                if self.mouse_interaction_active:
                    self._exit_mouse_interaction(resume_idle=False)
                return
''',
        "poll drag race",
    )

    # Replace the V0.7.7 mouse event block. Explicit mouse grab guarantees the first press-drag
    # keeps receiving move/release events even while layers are hidden/swapped under the cursor.
    mstart = s.index("    def mousePressEvent(self, event):\n", s.index("class PetWindow(QWidget):"))
    mend = s.index("    def contextMenuEvent(self, event):\n", mstart)
    mouse_block = r'''    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.cfg.get("lock_position", False) and not self.cfg.get("click_through", False):
            gp = event.globalPosition().toPoint()
            self.drag_offset = gp - self.frameGeometry().topLeft()
            self.drag_press_global = gp
            self.drag_last_global = gp

            # Kill the normal V2 cross-fade immediately. In V0.7.7 that timer could race the
            # first drag and make the first press feel "dead".
            if self.mouse_interaction_active:
                self._exit_mouse_interaction(resume_idle=False)
            try:
                self.grabMouse()
            except Exception:
                pass
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            gp = event.globalPosition().toPoint()

            # Always move on the FIRST physical drag. Visual switching no longer gates movement.
            self.move(gp - self.drag_offset)

            delta = gp - self.drag_last_global if self.drag_last_global is not None else QPoint(0, 0)
            if not self.drag_visual_active and self.drag_press_global is not None:
                threshold = max(2, min(6, int(self.cfg.get("drag_interaction", {}).get("threshold_px", 4))))
                if (gp - self.drag_press_global).manhattanLength() >= threshold:
                    self._begin_drag_interaction()

            if self.drag_visual_active:
                self._feed_drag_interaction(delta.x(), delta.y())

            self.drag_last_global = gp
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            was_dragging = self.drag_visual_active
            self.drag_offset = None
            self.drag_press_global = None
            self.drag_last_global = None
            try:
                self.releaseMouse()
            except Exception:
                pass

            self.cfg["x"], self.cfg["y"] = self.x(), self.y()
            save_config(self.cfg)

            if was_dragging:
                self._end_drag_interaction()
            elif not self.report_active and self.current_state == "idle":
                # A click without enough movement must not leave V2 hidden.
                for lab in self.labels:
                    lab.show()
            event.accept()
            return
        super().mouseReleaseEvent(event)

'''
    s = s[:mstart] + mouse_block + s[mend:]

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    required = [
        'APP_VERSION = "0.7.7.1"',
        '"eye_white_left": "eye_white_left.webp"',
        '"pupil_right": "pupil_right.webp"',
        'self.grabMouse()',
        'self.move(gp - self.drag_offset)',
        '# Correct PSD-style z order:',
        'eye_dx = max(-3.4',
    ]
    for token in required:
        if token not in final:
            raise RuntimeError(f"v0.7.7.1 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.1 drag interaction hotfix")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0771.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
