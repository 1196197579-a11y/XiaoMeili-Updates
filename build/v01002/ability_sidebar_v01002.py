# -*- coding: utf-8 -*-
"""XiaoMeili V0.10.0.2 Beauty Ability sidebar.

The sidebar is drawn as true translucent/vector UI. It does not use a baked
screenshot as the panel background. The only continuous animation is the two
cyan sweep lights around the outer rounded border, and that timer runs only
while the sidebar is visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt, Signal, QRect, QRectF, QPointF, QVariantAnimation,
    QEasingCurve, QPropertyAnimation, QTimer,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPainterPath, QLinearGradient,
    QFont, QFontDatabase,
)
from PySide6.QtWidgets import QWidget, QAbstractButton, QApplication


FEATURES = (
    ("beauty_lock", "01", "美丽锁定"),
    ("beauty_insight", "02", "美丽洞察"),
    ("power_20", "03", "二成功力"),
    ("power_50", "04", "五成功力"),
    ("beauty_god", "05", "美丽之神"),
)


def _asset(name: str) -> str:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parent.parent
    return str(root / "assets" / name)


_FONT_FAMILY = None


def _ability_font_family() -> str:
    """Use the private Maoken font when bundled; never install system-wide."""
    global _FONT_FAMILY
    if _FONT_FAMILY:
        return _FONT_FAMILY
    font_path = Path(_asset("MaokenAssortedSans-Lite.otf"))
    if font_path.exists():
        try:
            fid = QFontDatabase.addApplicationFont(str(font_path))
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                _FONT_FAMILY = str(fams[0])
                return _FONT_FAMILY
        except Exception:
            pass
    _FONT_FAMILY = "Microsoft YaHei UI"
    return _FONT_FAMILY


class AnimatedToggle(QAbstractButton):
    """Reference-style toggle: 170 ms slide, glow only when ON."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(56, 30)
        self._progress = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate_to_state)

    def _on_anim(self, value):
        try:
            self._progress = float(value)
        except Exception:
            self._progress = 1.0 if self.isChecked() else 0.0
        self.update()
        parent = self.parentWidget()
        if parent is not None:
            parent.update()

    def _animate_to_state(self, checked):
        self._anim.stop()
        self._anim.setStartValue(float(self._progress))
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked):  # noqa: N802
        super().setChecked(bool(checked))
        if self._anim.state() != QVariantAnimation.State.Running:
            self._progress = 1.0 if checked else 0.0
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = max(0.0, min(1.0, float(self._progress)))
        rect = QRectF(2.5, 2.5, self.width() - 5.0, self.height() - 5.0)

        if t > 0.01:
            for width, alpha in ((9, int(24 * t)), (6, int(42 * t)), (3, int(86 * t))):
                p.setPen(QPen(QColor(34, 247, 249, alpha), width))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect, 14, 14)

        off = QColor(21, 53, 70, 236)
        on = QColor(11, 181, 187, 245)
        track = QColor(
            int(off.red() * (1.0 - t) + on.red() * t),
            int(off.green() * (1.0 - t) + on.green() * t),
            int(off.blue() * (1.0 - t) + on.blue() * t),
            245,
        )
        p.setPen(QPen(QColor(200, 248, 255, int(120 + 100 * t)), 1.2))
        p.setBrush(track)
        p.drawRoundedRect(rect, 14, 14)

        x0 = 5.0
        x1 = float(self.width() - 26)
        x = x0 + (x1 - x0) * t
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 255))
        p.drawEllipse(QRectF(x, 5.0, 20.0, 20.0))
        p.setBrush(QColor(220, 228, 232, 135))
        p.drawEllipse(QRectF(x + 2.0, 7.0, 16.0, 16.0))
        p.end()


class AbilityNode(QWidget):
    """Small cyan node beside XiaoMeili; no background rectangle."""

    clicked = Signal()
    hover_entered = Signal()
    hover_left = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(47, 246, 248, 24)); p.drawEllipse(c, 15.0, 15.0)
        p.setBrush(QColor(47, 246, 248, 54)); p.drawEllipse(c, 11.0, 11.0)
        p.setBrush(QColor(238, 255, 255, 250)); p.drawEllipse(c, 6.1, 6.1)
        p.setBrush(QColor(43, 225, 229, 255)); p.drawEllipse(c, 4.0, 4.0)
        p.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(); event.accept(); return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.hover_entered.emit(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit(); super().leaveEvent(event)


class AbilitySidebar(QWidget):
    """True-vector glass sidebar matching the approved reference composition."""

    state_changed = Signal(str, bool)
    visibility_changed = Signal(bool)
    hover_entered = Signal()
    hover_left = Signal()

    ability_lock_on = Signal(); ability_lock_off = Signal()
    ability_insight_on = Signal(); ability_insight_off = Signal()
    ability_power2_on = Signal(); ability_power2_off = Signal()
    ability_power5_on = Signal(); ability_power5_off = Signal()
    ability_god_on = Signal(); ability_god_off = Signal()

    PANEL_W = 230
    PANEL_H = 320
    PAD = 12
    LINK_W = 62
    TOTAL_W = PANEL_W + LINK_W + PAD * 2
    TOTAL_H = PANEL_H + PAD * 2
    PET_OVERLAP = 10

    ROW_TOP = 36
    ROW_STEP = 55
    ROW_H = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setFixedSize(self.TOTAL_W, self.TOTAL_H)
        self.setWindowOpacity(0.0)

        self._states = {key: False for key, _, _ in FEATURES}
        self._buttons = {}
        self._button_guard = False
        self._anchor_rect = QRect()
        self._open = False
        self._closing = False
        self._side = "left"
        self._sweep_phase = 0.0

        self._slide = QPropertyAnimation(self, b"geometry", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.finished.connect(self._slide_finished)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

        # V0.10.0.2: active only while visible. No sidebar polling while closed.
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(33)
        self._sweep_timer.timeout.connect(self._advance_sweep)

        for idx, (key, _num, _name) in enumerate(FEATURES):
            sw = AnimatedToggle(self)
            sw.toggled.connect(lambda checked, fid=key: self._on_toggled(fid, checked))
            self._buttons[key] = sw
        self._layout_children()
        self.hide()

    def _panel_rect(self) -> QRectF:
        px = self.PAD if self._side == "left" else self.PAD + self.LINK_W
        return QRectF(float(px), float(self.PAD), float(self.PANEL_W), float(self.PANEL_H))

    def _layout_children(self):
        panel = self._panel_rect()
        for idx, (key, _num, _name) in enumerate(FEATURES):
            self._buttons[key].move(
                int(panel.x() + 163),
                int(panel.y() + self.ROW_TOP + idx * self.ROW_STEP + 8),
            )

    def _screen_area(self, anchor: QRect):
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    def side_for_anchor(self, anchor: QRect) -> str:
        area = self._screen_area(anchor)
        left_space = anchor.left() - area.left()
        right_space = area.right() - anchor.right()
        need = self.TOTAL_W - self.PET_OVERLAP + 8
        if left_space >= need:
            return "left"
        if right_space >= need:
            return "right"
        return "left" if left_space >= right_space else "right"

    def _target_geometry(self, anchor: QRect):
        area = self._screen_area(anchor)
        side = self.side_for_anchor(anchor)
        if side != self._side:
            self._side = side
            self._layout_children()
        if self._side == "left":
            x = anchor.left() - self.TOTAL_W + self.PET_OVERLAP
        else:
            x = anchor.right() - self.PET_OVERLAP
        y = anchor.top() + int((anchor.height() - self.TOTAL_H) * 0.36)
        x = max(area.left() + 2, min(x, area.right() - self.TOTAL_W - 2))
        y = max(area.top() + 2, min(y, area.bottom() - self.TOTAL_H - 2))
        return QRect(int(x), int(y), self.TOTAL_W, self.TOTAL_H)

    def sync_to_anchor(self, anchor: QRect, force=False):
        if not isinstance(anchor, QRect):
            return
        self._anchor_rect = QRect(anchor)
        if not self.isVisible():
            return
        target = self._target_geometry(anchor)
        if force or self._slide.state() != QPropertyAnimation.State.Running:
            self.setGeometry(target); self.update()

    def show_animated(self, anchor: QRect):
        self._anchor_rect = QRect(anchor)
        target = self._target_geometry(self._anchor_rect)
        if self._open and self.isVisible() and not self._closing:
            self.setGeometry(target)
            if not self._sweep_timer.isActive(): self._sweep_timer.start()
            return
        self._open = True; self._closing = False
        self._slide.stop(); self._fade.stop()
        shift = self.PANEL_W - 26
        start = target.translated(shift if self._side == "left" else -shift, 0)
        self.setGeometry(start); self.setWindowOpacity(0.0)
        self.show(); self.raise_()
        self._sweep_phase = 0.0
        self._sweep_timer.start()
        self._slide.setDuration(260); self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.setDuration(220)
        self._slide.setStartValue(start); self._slide.setEndValue(target)
        self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        self._slide.start(); self._fade.start()
        self.visibility_changed.emit(True)

    def hide_animated(self):
        if not self.isVisible() or self._closing:
            self._open = False
            self._sweep_timer.stop()
            return
        self._closing = True
        self._slide.stop(); self._fade.stop()
        start = self.geometry(); shift = self.PANEL_W - 26
        end = start.translated(shift if self._side == "left" else -shift, 0)
        self._slide.setDuration(210); self._slide.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide.setStartValue(start); self._slide.setEndValue(end)
        self._fade.setDuration(180)
        self._fade.setStartValue(self.windowOpacity()); self._fade.setEndValue(0.0)
        self._slide.start(); self._fade.start()

    def hideEvent(self, event):
        self._sweep_timer.stop()
        super().hideEvent(event)

    def _slide_finished(self):
        if self._closing:
            self._closing = False; self._open = False
            self._sweep_timer.stop(); self.hide()
            self.visibility_changed.emit(False)

    def is_open(self):
        return bool(self._open and self.isVisible() and not self._closing)

    def enterEvent(self, event):
        self.hover_entered.emit(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit(); super().leaveEvent(event)

    def _advance_sweep(self):
        # One lap in about 4.0 seconds at 30 fps.
        self._sweep_phase = (self._sweep_phase + 0.00825) % 1.0
        self.update()

    def set_states(self, states):
        data = states if isinstance(states, dict) else {}
        self._button_guard = True
        try:
            for key, _, _ in FEATURES:
                value = bool(data.get(key, False))
                self._states[key] = value
                self._buttons[key].setChecked(value)
        finally:
            self._button_guard = False
        self.update()

    def states(self):
        return dict(self._states)

    def _emit_feature_event(self, feature_id, checked):
        signals = {
            ("beauty_lock", True): self.ability_lock_on,
            ("beauty_lock", False): self.ability_lock_off,
            ("beauty_insight", True): self.ability_insight_on,
            ("beauty_insight", False): self.ability_insight_off,
            ("power_20", True): self.ability_power2_on,
            ("power_20", False): self.ability_power2_off,
            ("power_50", True): self.ability_power5_on,
            ("power_50", False): self.ability_power5_off,
            ("beauty_god", True): self.ability_god_on,
            ("beauty_god", False): self.ability_god_off,
        }
        sig = signals.get((feature_id, bool(checked)))
        if sig is not None:
            sig.emit()

    def _on_toggled(self, feature_id, checked):
        if self._button_guard:
            return
        self._states[str(feature_id)] = bool(checked)
        self.state_changed.emit(str(feature_id), bool(checked))
        self._emit_feature_event(str(feature_id), bool(checked))
        self.update()

    @staticmethod
    def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _paint_sweep_dot(self, p: QPainter, border_path: QPainterPath, phase: float):
        # Two compact comet-like points; their tails are dots, not a flowing line.
        for i in range(7, -1, -1):
            t = (phase - i * 0.0055) % 1.0
            pt = border_path.pointAtPercent(t)
            alpha = int(22 + (7 - i) * 22)
            radius = 2.2 + (7 - i) * 0.24
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(97, 255, 255, min(210, alpha)))
            p.drawEllipse(pt, radius, radius)
        pt = border_path.pointAtPercent(phase % 1.0)
        for radius, alpha in ((9.5, 24), (6.0, 60), (3.2, 255)):
            p.setBrush(QColor(188, 255, 255, alpha) if radius <= 3.3 else QColor(47, 248, 250, alpha))
            p.drawEllipse(pt, radius, radius)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        panel = self._panel_rect()
        radius = 24.0
        panel_path = self._rounded_path(panel, radius)

        # Outer cyan glow. The rounded glowing outline itself is the visual boundary.
        for width, alpha in ((16, 20), (11, 30), (7, 46), (4, 82)):
            p.setPen(QPen(QColor(58, 247, 249, alpha), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(panel_path)

        # True translucent glass, no screenshot/background rectangle.
        grad = QLinearGradient(panel.topLeft(), panel.bottomRight())
        grad.setColorAt(0.0, QColor(47, 166, 211, 150))
        grad.setColorAt(0.42, QColor(19, 113, 158, 136))
        grad.setColorAt(1.0, QColor(10, 73, 111, 150))
        p.setPen(QPen(QColor(216, 255, 255, 245), 2.0))
        p.setBrush(QBrush(grad))
        p.drawPath(panel_path)

        # Subtle inner edge and glass sheen.
        inner = panel.adjusted(5.0, 5.0, -5.0, -5.0)
        p.setPen(QPen(QColor(152, 244, 255, 90), 1.0)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(inner, radius - 4, radius - 4)
        sheen = QLinearGradient(panel.left(), panel.top(), panel.left(), panel.top() + 78)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 45)); sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(sheen))
        p.drawRoundedRect(QRectF(panel.left() + 7, panel.top() + 7, panel.width() - 14, 68), 17, 17)

        # Three tiny decorative dots, as in the approved reference.
        for i in range(3):
            p.setBrush(QColor(230, 255, 255, 230 - i * 25)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(panel.left() + 19 + i * 10, panel.top() + 17), 2.5, 2.5)

        family = _ability_font_family()
        num_font = QFont(family, 16, QFont.Weight.DemiBold)
        name_font = QFont(family, 15, QFont.Weight.DemiBold)

        for idx, (key, num, name) in enumerate(FEATURES):
            top = panel.top() + self.ROW_TOP + idx * self.ROW_STEP
            row = QRectF(panel.left() + 14, top, panel.width() - 28, self.ROW_H)
            on = bool(self._states.get(key, False))
            if on:
                p.setPen(QPen(QColor(49, 248, 250, 74), 7)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(row.adjusted(2, 2, -2, -2), 14, 14)
            p.setPen(QPen(QColor(191, 249, 255, 235 if on else 190), 1.25))
            p.setBrush(QColor(12, 80, 113, 68 if on else 108))
            p.drawRoundedRect(row, 14, 14)

            p.setPen(QColor(224, 252, 255, 244))
            p.setFont(num_font)
            p.drawText(QRectF(row.left() + 13, row.top(), 40, row.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, num)
            p.setFont(name_font)
            p.drawText(QRectF(row.left() + 56, row.top(), 100, row.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)

        # Correct connector: one ring straddles the glowing outer border, then one curved line.
        node_y = panel.top() + 128.0
        if self._side == "left":
            node_x = panel.right()
            end_x = self.width() - self.PAD - 1.0
            line_start = QPointF(node_x + 8.0, node_y)
            line_end = QPointF(end_x, node_y + 34.0)
            c1 = QPointF(node_x + 21.0, node_y + 1.0)
            c2 = QPointF(end_x - 21.0, node_y + 31.0)
        else:
            node_x = panel.left()
            end_x = self.PAD + 1.0
            line_start = QPointF(node_x - 8.0, node_y)
            line_end = QPointF(end_x, node_y + 34.0)
            c1 = QPointF(node_x - 21.0, node_y + 1.0)
            c2 = QPointF(end_x + 21.0, node_y + 31.0)
        link = QPainterPath(line_start); link.cubicTo(c1, c2, line_end)
        for width, alpha in ((8, 22), (4, 52), (1.6, 235)):
            pen = QPen(QColor(73, 249, 250, alpha), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(link)

        for radius_node, alpha in ((13.0, 22), (10.0, 50)):
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(54, 247, 249, alpha)); p.drawEllipse(QPointF(node_x, node_y), radius_node, radius_node)
        p.setBrush(QColor(24, 118, 157, 132)); p.setPen(QPen(QColor(228, 255, 255, 245), 1.6)); p.drawEllipse(QPointF(node_x, node_y), 8.0, 8.0)
        p.setBrush(QColor(171, 255, 255, 90)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(node_x, node_y), 4.4, 4.4)

        # Two identical cyan sweep lights, exactly half a lap apart.
        self._paint_sweep_dot(p, panel_path, self._sweep_phase)
        self._paint_sweep_dot(p, panel_path, (self._sweep_phase + 0.5) % 1.0)

        if self._states.get("beauty_god", False):
            p.setPen(QPen(QColor(51, 249, 249, 110), 3.0)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(panel_path)
        p.end()
