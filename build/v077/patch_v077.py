# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import io
import py_compile
import re
import sys
import zipfile
from pathlib import Path


def must_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7 anchor: {label}")
    return text.replace(old, new, 1)


def install_drag_assets(source_root: Path, repo_root: Path):
    chunk_dir = repo_root / "build" / "v077" / "assets_b64"
    chunks = sorted(chunk_dir.glob("part_*.txt"))
    if len(chunks) != 8:
        raise RuntimeError(f"expected 8 drag asset chunks, got {len(chunks)}")
    encoded = "".join(p.read_text(encoding="utf-8").strip() for p in chunks)
    raw = base64.b64decode(encoded, validate=True)
    out_dir = source_root / "app" / "assets" / "drag_interaction"
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = {
        "hair_back.webp",
        "body.webp",
        "head_group.webp",
        "earrings.webp",
        "hair_front2.webp",
        "hair_front.webp",
    }
    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        names = set(zf.namelist())
        if names != expected:
            raise RuntimeError(f"unexpected drag asset bundle: {sorted(names)}")
        for name in sorted(expected):
            data = zf.read(name)
            if len(data) < 100 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
                raise RuntimeError(f"invalid WebP drag asset: {name}")
            (out_dir / name).write_bytes(data)
    print(f"Installed {len(expected)} V0.7.7 drag assets ({len(raw)} bytes bundle)")


def patch(source_root: Path, repo_root: Path):
    install_drag_assets(source_root, repo_root)
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.6\.2"',
        'APP_NAME = "小美丽 V0.7.7｜Drag Interaction"\nAPP_VERSION = "0.7.7"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    drag_class = r'''
class DragInteractionLayer(QWidget):
    """Layered dangling pose used only while the user physically drags XiaoMeili.

    It deliberately does not replace Continuous Puppet V2.  The normal mouse-follow
    layer remains untouched; this layer is mounted only after a real drag threshold
    is crossed, then settles for a short spring-back after release.
    """
    settled = Signal()

    ASSET_FILES = {
        "back": "hair_back.webp",
        "body": "body.webp",
        "head": "head_group.webp",
        "earrings": "earrings.webp",
        "front2": "hair_front2.webp",
        "front": "hair_front.webp",
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
        # Mouse/window travel is instant; body pieces lag in the opposite direction.
        nx = max(-1.0, min(1.0, float(dx) / 22.0))
        ny = max(-1.0, min(1.0, float(dy) / 22.0))
        self.target_x = -nx
        self.target_y = -ny
        self.swing_x = self._follow(self.swing_x, -nx, 0.55)

    def begin_recover(self):
        if not self.active:
            return
        self.recovering = True
        self.recover_started = time.monotonic()
        self.target_x = self.target_y = 0.0
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

        # Movement impulse fades even while the pointer pauses, giving a soft pendulum stop.
        self.target_x *= 0.70
        self.target_y *= 0.70

        # Body follows least. Hair and earrings trail more strongly and more slowly.
        self.body_x = self._follow(self.body_x, self.target_x * 0.34, 0.19)
        self.body_y = self._follow(self.body_y, self.target_y * 0.24, 0.18)

        self.head_x = self._follow(self.head_x, self.target_x * 0.55, 0.23)
        self.head_y = self._follow(self.head_y, self.target_y * 0.42, 0.21)

        self.front2_x = self._follow(self.front2_x, self.target_x * 0.70, 0.17)
        self.front2_y = self._follow(self.front2_y, self.target_y * 0.54, 0.16)
        self.front_x = self._follow(self.front_x, self.target_x * 0.82, 0.15)
        self.front_y = self._follow(self.front_y, self.target_y * 0.62, 0.14)

        self.back_x = self._follow(self.back_x, self.target_x * 1.08, 0.105)
        self.back_y = self._follow(self.back_y, self.target_y * 0.82, 0.10)
        self.ear_x = self._follow(self.ear_x, self.target_x * 1.20, 0.12)
        self.ear_y = self._follow(self.ear_y, self.target_y * 0.92, 0.11)
        self.swing_x *= 0.78

        self.update()

        if self.recovering:
            values = (
                self.body_x, self.body_y, self.head_x, self.head_y,
                self.front_x, self.front_y, self.front2_x, self.front2_y,
                self.back_x, self.back_y, self.ear_x, self.ear_y, self.swing_x,
            )
            elapsed = time.monotonic() - self.recover_started
            if elapsed >= 0.28 or max(abs(v) for v in values) < 0.012:
                self.active = False
                self.recovering = False
                self.timer.stop()
                self.reset_pose()
                self.hide()
                self.settled.emit()

    def _draw(self, painter, key, base_x, base_y, side, nx=0.0, ny=0.0,
              rot=0.0, pivot=(0.5, 0.5)):
        pm = self.pix.get(key)
        if pm is None or pm.isNull():
            return
        # Values are normalized spring displacement. Keep the motion subtle at desktop-pet scale.
        dx = float(nx) * side * 0.030
        dy = float(ny) * side * 0.022
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

        # Rotation is tied to the horizontal spring/inertia, not to pointer position itself.
        self._draw(cp, "back", x0, y0, side, self.back_x, self.back_y,
                   rot=self.back_x * 4.2 + self.swing_x * 2.0, pivot=(0.62, 0.28))
        self._draw(cp, "body", x0, y0, side, self.body_x, self.body_y,
                   rot=self.body_x * 1.35, pivot=(0.52, 0.48))
        self._draw(cp, "head", x0, y0, side, self.head_x, self.head_y,
                   rot=self.head_x * 2.15, pivot=(0.46, 0.42))
        self._draw(cp, "earrings", x0, y0, side, self.ear_x, self.ear_y,
                   rot=self.ear_x * 5.0 + self.swing_x * 1.6, pivot=(0.50, 0.48))
        self._draw(cp, "front2", x0, y0, side, self.front2_x, self.front2_y,
                   rot=self.front2_x * 2.8 + self.swing_x * 1.3, pivot=(0.48, 0.36))
        self._draw(cp, "front", x0, y0, side, self.front_x, self.front_y,
                   rot=self.front_x * 3.6 + self.swing_x * 1.6, pivot=(0.45, 0.36))
        cp.end()

        # Exactly the same soft white edge/glow treatment used by Continuous Puppet V2.
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
    pet_anchor = "class PetWindow(QWidget):\n"
    if pet_anchor not in s:
        raise RuntimeError("PetWindow anchor missing")
    s = s.replace(pet_anchor, drag_class + pet_anchor, 1)

    s = must_replace(
        s,
        "        self.drag_offset = None\n",
        "        self.drag_offset = None\n"
        "        self.drag_press_global = None\n"
        "        self.drag_last_global = None\n"
        "        self.drag_visual_active = False\n",
        "drag state init",
    )

    mouse_layer_anchor = '''        self.mouse_layer.setGraphicsEffect(self.mouse_effect)
        self.mouse_layer.hide()

        self.report_overlay = ReportTextOverlay(self.cfg, self)
'''
    mouse_layer_new = '''        self.mouse_layer.setGraphicsEffect(self.mouse_effect)
        self.mouse_layer.hide()

        self.drag_layer = DragInteractionLayer(self)
        self.drag_layer.setGeometry(0, 0, self.width(), self.height())
        self.drag_layer.settled.connect(self._finish_drag_interaction)
        self.drag_layer.hide()

        self.report_overlay = ReportTextOverlay(self.cfg, self)
'''
    s = must_replace(s, mouse_layer_anchor, mouse_layer_new, "drag layer init")

    resize_anchor = '''        if hasattr(self, "mouse_layer"):
            self.mouse_layer.setGeometry(0, 0, w, h)
        if hasattr(self, "report_overlay"):
'''
    resize_new = '''        if hasattr(self, "mouse_layer"):
            self.mouse_layer.setGeometry(0, 0, w, h)
        if hasattr(self, "drag_layer"):
            self.drag_layer.setGeometry(0, 0, w, h)
        if hasattr(self, "report_overlay"):
'''
    s = must_replace(s, resize_anchor, resize_new, "drag resize")

    # Insert helper methods before the existing mouse press handler.
    press_pos = s.index("    def mousePressEvent(self, event):\n", s.index("class PetWindow(QWidget):"))
    helpers = r'''    def _begin_drag_interaction(self):
        if self.drag_visual_active:
            self.drag_layer.start_drag()
            return
        if self.report_active or self.current_state != "idle":
            return
        if self.mouse_interaction_active:
            self._exit_mouse_interaction(resume_idle=False)
        self.drag_visual_active = True
        for lab in self.labels:
            lab.hide()
        self.mouse_layer.hide()
        self.drag_layer.setGeometry(0, 0, self.width(), self.height())
        self.drag_layer.start_drag()
        self.drag_layer.raise_()
        self.report_overlay.raise_()
        LOGGER.info("拖拽互动进入：分层悬挂姿态")

    def _feed_drag_interaction(self, dx, dy):
        if self.drag_visual_active:
            self.drag_layer.feed_motion(dx, dy)

    def _end_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_layer.begin_recover()
        LOGGER.info("拖拽互动松手：开始回弹")

    def _finish_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_visual_active = False
        self.drag_layer.hide()
        if not self.report_active and self.current_state == "idle":
            for lab in self.labels:
                lab.show()
            self.play_state("idle", force_new_clip=True, immediate=True)
        LOGGER.info("拖拽互动结束：恢复待机")

    def _cancel_drag_interaction(self):
        if not self.drag_visual_active:
            return
        self.drag_visual_active = False
        self.drag_layer.cancel()
        for lab in self.labels:
            lab.show()
        LOGGER.info("拖拽互动被更高优先级状态打断")

'''
    s = s[:press_pos] + helpers + s[press_pos:]

    old_mouse_block_start = s.index("    def mousePressEvent(self, event):\n", press_pos + len(helpers))
    old_mouse_block_end = s.index("    def contextMenuEvent(self, event):\n", old_mouse_block_start)
    new_mouse_block = r'''    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.cfg.get("lock_position", False) and not self.cfg.get("click_through", False):
            gp = event.globalPosition().toPoint()
            self.drag_offset = gp - self.frameGeometry().topLeft()
            self.drag_press_global = gp
            self.drag_last_global = gp
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            gp = event.globalPosition().toPoint()
            if self.drag_press_global is not None and not self.drag_visual_active:
                threshold = max(4, int(self.cfg.get("drag_interaction", {}).get("threshold_px", 6)))
                if (gp - self.drag_press_global).manhattanLength() >= threshold:
                    self._begin_drag_interaction()

            if self.drag_last_global is not None and self.drag_visual_active:
                delta = gp - self.drag_last_global
                self._feed_drag_interaction(delta.x(), delta.y())

            self.move(gp - self.drag_offset)
            self.drag_last_global = gp
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag_offset is not None:
            was_dragging = self.drag_visual_active
            self.drag_offset = None
            self.drag_press_global = None
            self.drag_last_global = None
            self.cfg["x"], self.cfg["y"] = self.x(), self.y()
            save_config(self.cfg)
            if was_dragging:
                self._end_drag_interaction()
            event.accept()

'''
    s = s[:old_mouse_block_start] + new_mouse_block + s[old_mouse_block_end:]

    # Gameplay/report reactions retain priority over drag interaction.
    play_anchor = '''    def play_state(self, state, immediate=False, force_new_clip=False, asset_override=None):
        if state not in STATE_NAMES:
'''
    play_new = '''    def play_state(self, state, immediate=False, force_new_clip=False, asset_override=None):
        if self.drag_visual_active:
            if state != "idle":
                self._cancel_drag_interaction()
                immediate = True
            elif not force_new_clip and not immediate:
                return
        if state not in STATE_NAMES:
'''
    s = must_replace(s, play_anchor, play_new, "drag priority in play_state")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    # Static release gate: if any of these disappear, do not package the build.
    final = main_path.read_text(encoding="utf-8")
    required = [
        'APP_VERSION = "0.7.7"',
        "class DragInteractionLayer(QWidget):",
        "def _begin_drag_interaction(self):",
        "def _end_drag_interaction(self):",
        "_add_soft_white_glow(",
        'resource(f"assets/drag_interaction/{filename}")',
    ]
    for token in required:
        if token not in final:
            raise RuntimeError(f"v0.7.7 static verification failed: {token}")
    print("Patched XiaoMeili source to V0.7.7 drag interaction")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v077.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
