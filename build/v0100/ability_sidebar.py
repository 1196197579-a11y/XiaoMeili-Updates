# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import (
    Qt, QObject, Signal, Property, QTimer, QPropertyAnimation,
    QEasingCurve, QVariantAnimation, QPoint, QRectF,
)
from PySide6.QtGui import (
    QPainter, QColor, QPixmap, QPainterPath, QPen, QCursor,
)
from PySide6.QtWidgets import QApplication, QWidget, QMenu

ABILITY_KEYS = (
    "beauty_lock",
    "beauty_insight",
    "power_2",
    "power_5",
    "beauty_god",
)


class AbilityNode(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = self.rect().center()
        for radius, alpha in ((15, 22), (12, 42), (9, 75)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(53, 249, 235, alpha))
            p.drawEllipse(c, radius, radius)
        p.setPen(QPen(QColor(194, 255, 251, 240), 2.0))
        p.setBrush(QColor(17, 92, 98, 220))
        p.drawEllipse(c, 7, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(232, 255, 254, 255))
        p.drawEllipse(c, 2, 2)
        p.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AbilityPanel(QWidget):
    ability_toggled = Signal(str, bool)

    def __init__(self, label_paths):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(388, 464)
        self._progress = 0.0
        self.reveal_from = "right"
        self.states = [False] * 5
        self.values = [0.0] * 5
        self._switch_anims = [None] * 5
        self.labels = [QPixmap(str(p)) for p in label_paths]
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def get_progress(self):
        return float(self._progress)

    def set_progress(self, value):
        self._progress = max(0.0, min(1.0, float(value)))
        self.setEnabled(self._progress >= 0.985)
        self.update()

    progress = Property(float, get_progress, set_progress)

    def set_reveal_from(self, side):
        self.reveal_from = "right" if str(side) == "right" else "left"
        self.update()

    def reset_switches(self):
        for i in range(5):
            self.states[i] = False
            self.values[i] = 0.0
            anim = self._switch_anims[i]
            if anim is not None:
                try:
                    anim.stop()
                except Exception:
                    pass
            self._switch_anims[i] = None
        self.update()

    def set_checked(self, index, checked, animated=True, emit=True):
        index = int(index)
        if index < 0 or index >= 5:
            return
        checked = bool(checked)
        self.states[index] = checked
        target = 1.0 if checked else 0.0
        old = float(self.values[index])
        if not animated:
            self.values[index] = target
            self.update()
        else:
            anim = QVariantAnimation(self)
            anim.setDuration(165)
            anim.setStartValue(old)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            def on_value(v, i=index):
                self.values[i] = float(v)
                self.update()
            anim.valueChanged.connect(on_value)
            anim.finished.connect(lambda i=index: self._switch_finished(i))
            self._switch_anims[index] = anim
            anim.start()
        if emit:
            self.ability_toggled.emit(ABILITY_KEYS[index], checked)

    def _switch_finished(self, index):
        self.values[index] = 1.0 if self.states[index] else 0.0
        self._switch_anims[index] = None
        self.update()

    def _outer_rect(self):
        return QRectF(12.0, 12.0, self.width() - 24.0, self.height() - 24.0)

    def _row_rect(self, index):
        top = 31.0 + index * 82.0
        return QRectF(28.0, top, self.width() - 56.0, 68.0)

    def _switch_rect(self, index):
        r = self._row_rect(index)
        return QRectF(r.right() - 88.0, r.top() + 15.0, 72.0, 38.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        visible_w = self.width() * self._progress
        if self.reveal_from == "right":
            clip = QRectF(self.width() - visible_w, 0.0, visible_w, self.height())
        else:
            clip = QRectF(0.0, 0.0, visible_w, self.height())
        p.setClipRect(clip)

        outer = self._outer_rect()
        god_boost = 1.0 if self.states[4] else 0.0
        for extra, alpha in ((9.0, 18), (6.0, 28), (3.0, 50)):
            glow = outer.adjusted(-extra, -extra, extra, extra)
            p.setPen(QPen(QColor(61, 247, 235, int(alpha + 22 * god_boost)), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(glow, 29.0 + extra, 29.0 + extra)

        p.setPen(QPen(QColor(178, 255, 251, 215), 2.1))
        p.setBrush(QColor(7, 52, 66, 188))
        p.drawRoundedRect(outer, 28.0, 28.0)

        sheen = QRectF(outer.left() + 4.0, outer.top() + 4.0, outer.width() - 8.0, outer.height() * 0.30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(180, 244, 255, 14))
        p.drawRoundedRect(sheen, 24.0, 24.0)

        for i in range(5):
            row = self._row_rect(i)
            value = float(self.values[i])
            if value > 0.001:
                for extra, alpha in ((5.0, int(18 * value)), (2.5, int(34 * value))):
                    rr = row.adjusted(-extra, -extra, extra, extra)
                    p.setPen(QPen(QColor(40, 248, 232, alpha), 1.4))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(rr, 22.0, 22.0)
            p.setPen(QPen(QColor(170, 239, 241, int(118 + 70 * value)), 1.35))
            p.setBrush(QColor(10, 55, 68, int(150 + 28 * value)))
            p.drawRoundedRect(row, 20.0, 20.0)

            if i < len(self.labels) and not self.labels[i].isNull():
                label = self.labels[i]
                target_h = 48.0
                scale = min(1.0, target_h / max(1, label.height()))
                target_w = min(235.0, label.width() * scale)
                target_h2 = label.height() * (target_w / max(1.0, label.width()))
                target = QRectF(row.left() + 18.0, row.center().y() - target_h2 / 2.0, target_w, target_h2)
                p.drawPixmap(target, label, QRectF(label.rect()))

            sr = self._switch_rect(i)
            if value > 0.001:
                for extra, alpha in ((8.0, int(24 * value)), (5.0, int(38 * value)), (2.0, int(62 * value))):
                    gr = sr.adjusted(-extra, -extra, extra, extra)
                    p.setPen(QPen(QColor(30, 255, 235, alpha), 1.5))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(gr, gr.height() / 2.0, gr.height() / 2.0)

            off = QColor(17, 43, 51, 235)
            on = QColor(8, 194, 181, 220)
            mix = QColor(
                int(off.red() + (on.red() - off.red()) * value),
                int(off.green() + (on.green() - off.green()) * value),
                int(off.blue() + (on.blue() - off.blue()) * value),
                int(off.alpha() + (on.alpha() - off.alpha()) * value),
            )
            p.setPen(QPen(QColor(190, 232, 235, int(112 + 95 * value)), 1.4))
            p.setBrush(mix)
            p.drawRoundedRect(sr, sr.height() / 2.0, sr.height() / 2.0)

            knob_r = 14.0
            left_x = sr.left() + 19.0
            right_x = sr.right() - 19.0
            cx = left_x + (right_x - left_x) * value
            cy = sr.center().y()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 52))
            p.drawEllipse(QPoint(int(cx + 1.5), int(cy + 2.0)), int(knob_r + 3.0), int(knob_r + 3.0))
            p.setBrush(QColor(241, 251, 252, 255))
            p.drawEllipse(QPoint(int(cx), int(cy)), int(knob_r), int(knob_r))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._progress >= 0.985:
            pos = event.position()
            for i in range(5):
                if self._row_rect(i).contains(pos):
                    self.set_checked(i, not self.states[i], animated=True, emit=True)
                    event.accept()
                    return
        super().mousePressEvent(event)


class AbilityOverlay(QWidget):
    request_close = Signal()
    request_settings = Signal()
    drag_moved = Signal(QPoint)
    drag_finished = Signal(QPoint)

    PANEL_W = 388
    PANEL_H = 464
    CHAR_W = 330
    CHAR_H = 438
    GAP = 36
    MARGIN = 16

    def __init__(self, character_path, label_paths):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(self.PANEL_W + self.GAP + self.CHAR_W + self.MARGIN * 2, max(self.PANEL_H, self.CHAR_H) + self.MARGIN * 2)
        self.character = QPixmap(str(character_path))
        self.panel = AbilityPanel(label_paths)
        self.panel.setParent(self)
        self.side = "left"
        self._open_anim = None
        self._opacity_anim = None
        self._drag_offset = None
        self.dragging = False
        self._update_layout()
        self.hide()

    def set_side(self, side):
        self.side = "right" if str(side) == "right" else "left"
        self._update_layout()
        self.update()

    def _char_rect(self):
        y = (self.height() - self.CHAR_H) // 2
        if self.side == "left":
            x = self.MARGIN + self.PANEL_W + self.GAP
        else:
            x = self.MARGIN
        return QRectF(float(x), float(y), float(self.CHAR_W), float(self.CHAR_H))

    def _panel_rect(self):
        y = (self.height() - self.PANEL_H) // 2
        if self.side == "left":
            x = self.MARGIN
        else:
            x = self.MARGIN + self.CHAR_W + self.GAP
        return QRectF(float(x), float(y), float(self.PANEL_W), float(self.PANEL_H))

    def _update_layout(self):
        pr = self._panel_rect()
        self.panel.setGeometry(int(pr.x()), int(pr.y()), int(pr.width()), int(pr.height()))
        self.panel.set_reveal_from("right" if self.side == "left" else "left")

    def character_center_global(self):
        cr = self._char_rect()
        local = QPoint(int(cr.center().x()), int(cr.center().y()))
        return self.mapToGlobal(local)

    def place_for_pet(self, pet_rect, screen_rect=None):
        cr = self._char_rect()
        center = pet_rect.center()
        x = int(center.x() - cr.center().x())
        y = int(center.y() - cr.center().y())
        if screen_rect is not None:
            x = max(int(screen_rect.left() - 4), min(x, int(screen_rect.right() - self.width() + 4)))
            y = max(int(screen_rect.top() - 4), min(y, int(screen_rect.bottom() - self.height() + 4)))
        self.move(x, y)

    def open_animated(self):
        if self._open_anim is not None:
            try: self._open_anim.stop()
            except Exception: pass
        if self._opacity_anim is not None:
            try: self._opacity_anim.stop()
            except Exception: pass
        self.panel.set_progress(0.0)
        self.setWindowOpacity(0.10)
        self.show()
        self.raise_()
        self._open_anim = QPropertyAnimation(self.panel, b"progress", self)
        self._open_anim.setDuration(265)
        self._open_anim.setStartValue(0.0)
        self._open_anim.setEndValue(1.0)
        self._open_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.setDuration(205)
        self._opacity_anim.setStartValue(0.10)
        self._opacity_anim.setEndValue(1.0)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._open_anim.start()
        self._opacity_anim.start()

    def show_immediate(self):
        self.panel.set_progress(1.0)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()

    def close_animated(self, finished=None):
        if not self.isVisible():
            if finished: finished()
            return
        if self._open_anim is not None:
            try: self._open_anim.stop()
            except Exception: pass
        if self._opacity_anim is not None:
            try: self._opacity_anim.stop()
            except Exception: pass
        self._open_anim = QPropertyAnimation(self.panel, b"progress", self)
        self._open_anim.setDuration(215)
        self._open_anim.setStartValue(float(self.panel.progress))
        self._open_anim.setEndValue(0.0)
        self._open_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._opacity_anim.setDuration(190)
        self._opacity_anim.setStartValue(float(self.windowOpacity()))
        self._opacity_anim.setEndValue(0.08)
        self._opacity_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        def done():
            self.hide()
            self.setWindowOpacity(1.0)
            if finished: finished()
        self._open_anim.finished.connect(done)
        self._open_anim.start()
        self._opacity_anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        cr = self._char_rect()
        if not self.character.isNull():
            p.drawPixmap(cr, self.character, QRectF(self.character.rect()))

        progress = float(self.panel.progress)
        if progress > 0.06:
            pr = self._panel_rect()
            if self.side == "left":
                start = QPoint(int(pr.right()), int(pr.top() + pr.height() * 0.37))
                end = QPoint(int(cr.left() + cr.width() * 0.15), int(cr.top() + cr.height() * 0.47))
                c1 = QPoint(start.x() + 26, start.y() + 12)
                c2 = QPoint(end.x() - 42, end.y() - 14)
            else:
                start = QPoint(int(pr.left()), int(pr.top() + pr.height() * 0.37))
                end = QPoint(int(cr.right() - cr.width() * 0.15), int(cr.top() + cr.height() * 0.47))
                c1 = QPoint(start.x() - 26, start.y() + 12)
                c2 = QPoint(end.x() + 42, end.y() - 14)
            path = QPainterPath(QPointF(start))
            path.cubicTo(QPointF(c1), QPointF(c2), QPointF(end))
            for width, alpha in ((8.0, int(18 * progress)), (5.0, int(35 * progress)), (2.2, int(220 * progress))):
                p.setPen(QPen(QColor(84, 255, 244, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
            p.setPen(QPen(QColor(210, 255, 252, int(230 * progress)), 2.0))
            p.setBrush(QColor(23, 118, 119, int(230 * progress)))
            p.drawEllipse(start, 10, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(239, 255, 254, int(255 * progress)))
            p.drawEllipse(start, 3, 3)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._char_rect().contains(event.position()):
            self.dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.drag_moved.emit(self.character_center_global())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            self._drag_offset = None
            self.drag_finished.emit(self.character_center_global())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        close_action = menu.addAction("收起美丽能力")
        settings_action = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == close_action:
            self.request_close.emit()
        elif chosen == settings_action:
            self.request_settings.emit()


class AbilitySidebarManager(QObject):
    ability_event = Signal(str, bool)

    def __init__(self, pet, cfg, character_path, label_paths, save_callback=None, open_settings_callback=None):
        super().__init__(pet)
        self.pet = pet
        self.cfg = cfg
        self.save_callback = save_callback
        self.open_settings_callback = open_settings_callback
        self.requested_open = False
        self.suspended = False
        self._closing = False
        self._pet_opacity_before = None

        self.cfg.setdefault("ability_sidebar", {})
        acfg = self.cfg["ability_sidebar"]
        acfg.setdefault("enabled", True)
        acfg.setdefault("voice_feedback_enabled", True)
        acfg.setdefault("voice_command_enabled", True)

        self.node = AbilityNode()
        self.overlay = AbilityOverlay(character_path, label_paths)
        self.node.clicked.connect(self.toggle)
        self.overlay.request_close.connect(self.close)
        self.overlay.request_settings.connect(self._open_settings)
        self.overlay.panel.ability_toggled.connect(self._on_ability_toggled)
        self.overlay.drag_moved.connect(self._move_pet_to_center)
        self.overlay.drag_finished.connect(self._finish_drag)

        self.timer = QTimer(self)
        self.timer.setInterval(90)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _cfg(self):
        return self.cfg.setdefault("ability_sidebar", {})

    def refresh_config(self):
        if not bool(self._cfg().get("enabled", True)):
            self.close()
            self.node.hide()

    def _open_settings(self):
        if callable(self.open_settings_callback):
            self.open_settings_callback()

    def _on_ability_toggled(self, key, enabled):
        self.ability_event.emit(str(key), bool(enabled))

    def _locked(self):
        return bool(self.cfg.get("lock_position", False) or self.cfg.get("click_through", False))

    def _high_priority_active(self):
        if not self.pet.isVisible():
            return True
        if bool(getattr(self.pet, "report_active", False)):
            return True
        if bool(getattr(self.pet, "dialogue_board_active", False)):
            return True
        state = str(getattr(self.pet, "current_state", "idle") or "idle")
        return state != "idle"

    def _screen_rect_for_pet(self):
        center = self.pet.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _preferred_side(self):
        rect = self.pet.frameGeometry()
        screen = self._screen_rect_for_pet()
        if screen is None:
            return "left"
        need = self.overlay.PANEL_W + self.overlay.GAP + 12
        left_space = rect.left() - screen.left()
        right_space = screen.right() - rect.right()
        if left_space >= need:
            return "left"
        if right_space >= need:
            return "right"
        return "left" if left_space >= right_space else "right"

    def _place_node(self):
        if not self.pet.isVisible():
            self.node.hide()
            return
        rect = self.pet.frameGeometry()
        side = self._preferred_side()
        if side == "left":
            x = rect.left() - self.node.width() // 2 + 2
        else:
            x = rect.right() - self.node.width() // 2 - 2
        y = int(rect.top() + rect.height() * 0.43 - self.node.height() / 2)
        self.node.move(int(x), int(y))

    def _hover_wants_node(self):
        if not self.pet.isVisible():
            return False
        pos = QCursor.pos()
        rect = self.pet.frameGeometry().adjusted(-45, -28, 45, 28)
        node_rect = self.node.frameGeometry().adjusted(-10, -10, 10, 10)
        return rect.contains(pos) or (self.node.isVisible() and node_rect.contains(pos))

    def _attach_overlay(self):
        self.overlay.set_side(self._preferred_side())
        self.overlay.place_for_pet(self.pet.frameGeometry(), self._screen_rect_for_pet())

    def _hide_pet_visual(self):
        if self._pet_opacity_before is None:
            try: self._pet_opacity_before = float(self.pet.windowOpacity())
            except Exception: self._pet_opacity_before = 1.0
        try: self.pet.setWindowOpacity(0.0)
        except Exception: pass

    def _restore_pet_visual(self):
        try:
            opacity = self._pet_opacity_before
            if opacity is None or opacity <= 0.01:
                opacity = max(0.2, min(1.0, float(self.cfg.get("opacity", 100)) / 100.0))
            self.pet.setWindowOpacity(float(opacity))
        except Exception:
            pass
        self._pet_opacity_before = None

    def open(self):
        if not bool(self._cfg().get("enabled", True)) or self._locked():
            return False
        self.requested_open = True
        self.overlay.panel.reset_switches()
        self.node.hide()
        if self._high_priority_active():
            self.suspended = True
            return True
        self.suspended = False
        self._attach_overlay()
        self._hide_pet_visual()
        self.overlay.open_animated()
        return True

    def close(self):
        self.requested_open = False
        self.suspended = False
        self.node.hide()
        self.overlay.panel.reset_switches()
        if self.overlay.isVisible() and not self._closing:
            self._closing = True
            def finished():
                self._closing = False
                self._restore_pet_visual()
            self.overlay.close_animated(finished)
        else:
            self.overlay.hide()
            self._restore_pet_visual()

    def toggle(self):
        if self.requested_open:
            self.close()
        else:
            self.open()

    def _suspend(self):
        if not self.requested_open:
            return
        self.suspended = True
        self.overlay.hide()
        self._restore_pet_visual()

    def _resume(self):
        if not self.requested_open or self._high_priority_active() or self._locked():
            return
        self.suspended = False
        self._attach_overlay()
        self._hide_pet_visual()
        self.overlay.show_immediate()

    def _move_pet_to_center(self, center):
        try:
            x = int(center.x() - self.pet.width() / 2)
            y = int(center.y() - self.pet.height() / 2)
            self.pet.move(x, y)
            self.cfg["x"], self.cfg["y"] = x, y
        except Exception:
            pass

    def _finish_drag(self, center):
        self._move_pet_to_center(center)
        if callable(self.save_callback):
            try: self.save_callback(self.cfg)
            except Exception: pass

    def _tick(self):
        if not bool(self._cfg().get("enabled", True)) or self._locked():
            if self.requested_open:
                self.close()
            self.node.hide()
            return
        if self.requested_open:
            self.node.hide()
            if self._high_priority_active():
                if not self.suspended:
                    self._suspend()
                return
            if self.suspended:
                self._resume()
                return
            if self.overlay.isVisible() and not self.overlay.dragging and not self._closing:
                self._attach_overlay()
            return
        if self._hover_wants_node():
            self._place_node()
            self.node.show()
            self.node.raise_()
        else:
            self.node.hide()

    def shutdown(self):
        try: self.timer.stop()
        except Exception: pass
        self.requested_open = False
        self.overlay.hide()
        self.node.hide()
        self._restore_pet_visual()
        self.overlay.deleteLater()
        self.node.deleteLater()
