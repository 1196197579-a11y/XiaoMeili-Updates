# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import shutil
import sys
from pathlib import Path

def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.1 anchor: {label}")
    return text.replace(old, new, 1)


def install_eye_assets(source_root: Path, repo_root: Path):
    src = repo_root / "build" / "v0771" / "assets"
    out = source_root / "app" / "assets" / "drag_interaction"
    out.mkdir(parents=True, exist_ok=True)
    expected = (
        "eye_white_left.webp",
        "eye_white_right.webp",
        "pupil_left.webp",
        "pupil_right.webp",
    )
    for name in expected:
        p = src / name
        if not p.exists():
            raise FileNotFoundError(f"missing V0.7.7.1 eye asset: {p}")
        data = p.read_bytes()
        if len(data) < 500 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise RuntimeError(f"invalid V0.7.7.1 eye asset: {name}")
        shutil.copy2(p, out / name)
    print(f"Installed {len(expected)} V0.7.7.1 drag eye assets")


def patch(source_root: Path, repo_root: Path):
    install_eye_assets(source_root, repo_root)
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

    # Crops are stored tightly to keep the update lightweight. Coordinates are from
    # the user's original 1254x1254 drag PSD/PNG canvas.
    EYE_CROPS = {
        "eye_white_left": (246, 710, 378, 828),
        "eye_white_right": (422, 742, 614, 848),
        "pupil_left": (295, 741, 354, 798),
        "pupil_right": (455, 765, 532, 827),
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
        self.target_x *= 0.87
        self.target_y *= 0.87
        self.gaze_target_x *= 0.88
        self.gaze_target_y *= 0.88
        self.motion_energy *= 0.91

        self.body_x = self._follow(self.body_x, self.target_x * 0.58, 0.15)
        self.body_y = self._follow(self.body_y, self.target_y * 0.42, 0.14)

        self.head_x = self._follow(self.head_x, self.target_x * 0.64, 0.20)
        self.head_y = self._follow(self.head_y, self.target_y * 0.50, 0.19)

        self.front2_x = self._follow(self.front2_x, self.target_x * 0.72, 0.16)
        self.front2_y = self._follow(self.front2_y, self.target_y * 0.56, 0.15)
        self.front_x = self._follow(self.front_x, self.target_x * 0.92, 0.14)
        self.front_y = self._follow(self.front_y, self.target_y * 0.70, 0.13)

        self.back_x = self._follow(self.back_x, self.target_x * 1.48, 0.085)
        self.back_y = self._follow(self.back_y, self.target_y * 0.98, 0.09)
        self.ear_x = self._follow(self.ear_x, self.target_x * 1.55, 0.095)
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

    def _draw_crop(self, painter, key, base_x, base_y, side, nx=0.0, ny=0.0,
                   rot=0.0, pivot=(0.46, 0.42), extra_px_x=0.0, extra_px_y=0.0):
        pm = self.pix.get(key)
        bbox = self.EYE_CROPS.get(key)
        if pm is None or pm.isNull() or not bbox:
            return
        sx = side / 1254.0
        left, top, right, bottom = bbox
        rx = base_x + float(left) * sx
        ry = base_y + float(top) * sx
        rw = float(right - left) * sx
        rh = float(bottom - top) * sx

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
            QRectF(rx, ry, rw, rh),
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
        self._draw_crop(cp, "eye_white_left", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42))
        self._draw_crop(cp, "eye_white_right", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42))

        eye_dx = max(-3.4, min(3.4, self.gaze_x * 3.4))
        eye_dy = max(-2.2, min(2.2, self.gaze_y * 2.2))
        self._draw_crop(cp, "pupil_left", x0, y0, side, self.head_x, self.head_y,
                        rot=head_rot, pivot=(0.46, 0.42), extra_px_x=eye_dx, extra_px_y=eye_dy)
        self._draw_crop(cp, "pupil_right", x0, y0, side, self.head_x, self.head_y,
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
        'EYE_CROPS = {',
        'self._draw_crop(cp, "pupil_left"',
    ]
    for token in required:
        if token not in final:
            raise RuntimeError(f"v0.7.7.1 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.1 drag interaction hotfix")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v0771.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
