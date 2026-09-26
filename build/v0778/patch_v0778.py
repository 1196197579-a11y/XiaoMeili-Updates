# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.8 anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.7"',
        'APP_NAME = "小美丽 V0.7.7.8｜Result Geometry + Dark UI + Lock Menu Fix"\nAPP_VERSION = "0.7.7.8"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ------------------------------------------------------------------
    # 1. Result screen geometry.
    #
    # The 2026-09-24 vertical fix corrected Y but kept the old x=0.09..0.91
    # crop. The current five-card result layout starts much closer to the
    # viewport edges. Cropping 9% from both sides truncates card #1/#5 and then
    # splitting that shortened image into five equal slots shifts every slot.
    #
    # New crop: x=0.02..0.96. Its five equal slots line up with the real card
    # centers (~0.11, 0.30, 0.49, 0.68, 0.87) while preserving the proven Y.
    # ------------------------------------------------------------------
    s = must(
        s,
        'ROI_REPORT_CARDS_RADAR = (0.090, 0.500, 0.910, 0.770)',
        'ROI_REPORT_CARDS_RADAR = (0.020, 0.500, 0.960, 0.770)',
        "report radar horizontal crop",
    )
    s = must(
        s,
        'ROI_REPORT_CARDS = (0.090, 0.500, 0.910, 0.820)',
        'ROI_REPORT_CARDS = (0.020, 0.500, 0.960, 0.820)',
        "report parse horizontal crop",
    )

    s = s.replace(
        '# High-resolution parse crop calibrated to the 2026-09-24 result layout.\n'
        '# It now centers the player cards and fully includes nickname, ACS and K/D/A.',
        '# High-resolution parse crop calibrated to the 2026-09-27 five-card layout.\n'
        '# X now keeps the complete first/fifth cards; Y still includes nickname, ACS and K/D/A.',
        1,
    )

    # Freeze one native frame, then derive the card crop from THAT SAME frame.
    # This removes the old two-grab race during the result animation.
    old_cache = '''            vx, vy, vw, vh = viewport
            t0 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t0) * 1000)
            if cards is None or cards.size == 0:
                return False
'''
    new_cache = '''            vx, vy, vw, vh = viewport
            t0 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            cards = _roi(full_frame, ROI_REPORT_CARDS) if full_frame is not None and getattr(full_frame, "size", 0) else None
            if cards is None or cards.size == 0:
                # Defensive fallback for capture backends that cannot return a full viewport.
                cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t0) * 1000)
            if cards is None or cards.size == 0:
                return False
'''
    s = must(s, old_cache, new_cache, "same-frame candidate crop")

    old_capture = '''            vx, vy, vw, vh = viewport
            t1 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            frozen_cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t1) * 1000)
            self.report_snapshot_full = None if full_frame is None else full_frame.copy()
            self.report_snapshot_cards = None if frozen_cards is None else frozen_cards.copy()
'''
    new_capture = '''            vx, vy, vw, vh = viewport
            t1 = time.perf_counter()
            full_frame = grabber.grab(vx, vy, vw, vh)
            frozen_cards = _roi(full_frame, ROI_REPORT_CARDS) if full_frame is not None and getattr(full_frame, "size", 0) else None
            if frozen_cards is None or frozen_cards.size == 0:
                frozen_cards = _grab_relative_roi(grabber, viewport, ROI_REPORT_CARDS, None)
            self._ema_timing("capture", (time.perf_counter() - t1) * 1000)
            self.report_snapshot_full = None if full_frame is None else full_frame.copy()
            self.report_snapshot_cards = None if frozen_cards is None else frozen_cards.copy()
'''
    s = must(s, old_capture, new_capture, "same-frame frozen crop")

    # The top-level parse-fail PNG used to be the card ROI only. That made a
    # healthy ROI look like a broken/incomplete screenshot. Save the full game
    # snapshot under the familiar name and the OCR crop under a second name.
    old_fail = '''            try:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(str(DEBUG_DIR / f"report_locked_parse_fail_{stamp}.png"), self.report_snapshot_cards)
            except Exception:
                pass
'''
    new_fail = '''            try:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                full_debug = self.report_snapshot_full
                if full_debug is not None and getattr(full_debug, "size", 0):
                    cv2.imwrite(str(DEBUG_DIR / f"report_locked_parse_fail_{stamp}.png"), full_debug)
                else:
                    cv2.imwrite(str(DEBUG_DIR / f"report_locked_parse_fail_{stamp}.png"), self.report_snapshot_cards)
                cv2.imwrite(str(DEBUG_DIR / f"report_locked_cards_parse_fail_{stamp}.png"), self.report_snapshot_cards)
            except Exception:
                pass
'''
    s = must(s, old_fail, new_fail, "full parse-fail debug snapshot")

    # ------------------------------------------------------------------
    # 2. Dark theme.
    # Keep the user's existing deep teal background. Make cards visibly lighter
    # and explicitly paint the scroll host/viewport so Qt cannot leak its
    # default white palette between the cards.
    # ------------------------------------------------------------------
    s = must(s, '            card = "#182620"', '            card = "#1C3028"', "dark card")
    s = must(s, '            card_hover = "#1D3028"', '            card_hover = "#234037"', "dark card hover")
    s = must(s, '            border = "#2A4038"', '            border = "#315349"', "dark border")
    s = must(s, '            border_soft = "#253A33"', '            border_soft = "#2B493F"', "dark soft border")
    s = must(s, '            input_bg = "#111C18"', '            input_bg = "#15251F"', "dark input")
    s = must(s, '            input_hover = "#172722"', '            input_hover = "#1B3028"', "dark input hover")
    s = must(s, '            button_bg = "#17231F"', '            button_bg = "#192B24"', "dark button")
    s = must(s, '            button_hover = "#20342D"', '            button_hover = "#234037"', "dark button hover")
    s = must(s, '            progress_bg = "#1A2924"', '            progress_bg = "#1B3028"', "dark progress")

    old_scroll = '''    def _v774_scroll_grid(self, cards, columns=2):
        host = QWidget()
        grid = QGridLayout(host)
'''
    new_scroll = '''    def _v774_scroll_grid(self, cards, columns=2):
        host = QWidget()
        host.setObjectName("settingsScrollHost")
        grid = QGridLayout(host)
'''
    s = must(s, old_scroll, new_scroll, "scroll host object")

    old_scroll2 = '''        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll
'''
    new_scroll2 = '''        scroll = QScrollArea()
        scroll.setObjectName("settingsScrollArea")
        scroll.viewport().setObjectName("settingsScrollViewport")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll
'''
    s = must(s, old_scroll2, new_scroll2, "scroll viewport object")

    old_qscroll = '''            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
'''
    new_qscroll = '''            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea#settingsScrollArea,
            QWidget#settingsScrollHost,
            QWidget#settingsScrollViewport {{
                background: {bg}; border: none;
            }}
            QScrollBar:vertical {{
'''
    s = must(s, old_qscroll, new_qscroll, "dark scroll background")

    # ------------------------------------------------------------------
    # 3. Locked right-click state.
    #
    # V0.7.7.7 unlocked immediately on right-button DOWN. The same physical
    # click could then continue into Qt after click-through was removed, so the
    # context menu observed the *new unlocked* state and showed "锁定...".
    #
    # Keep click-through active for the entire right-click and unlock only
    # after button RELEASE. Also make the menu label state-aware as a fallback.
    # ------------------------------------------------------------------
    s = must(
        s,
        '        self._v0777_right_was_down = False\n',
        '        self._v0777_right_was_down = False\n'
        '        self._v0778_unlock_pending = False\n',
        "unlock pending init",
    )

    old_poll = r'''        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down
            if down and not was_down:
                pos = QCursor.pos()
                if self._cursor_hits_pet_shape(pos):
                    LOGGER.info("锁定状态检测到小美丽区域右键：解除游戏防误触锁定")
                    self.set_interaction_lock(False)
        except Exception:
            LOGGER.warning("锁定状态右键解锁检测失败", exc_info=True)
'''
    new_poll = r'''        locked = bool(self.cfg.get("lock_position", False))
        if not locked or sys.platform != "win32":
            self._v0777_right_was_down = False
            self._v0778_unlock_pending = False
            return
        try:
            VK_RBUTTON = 0x02
            down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            was_down = bool(getattr(self, "_v0777_right_was_down", False))
            self._v0777_right_was_down = down

            if down and not was_down:
                pos = QCursor.pos()
                self._v0778_unlock_pending = bool(self._cursor_hits_pet_shape(pos))
                if self._v0778_unlock_pending:
                    LOGGER.info("锁定状态检测到小美丽区域右键：等待释放后解锁")

            if (not down) and was_down and bool(getattr(self, "_v0778_unlock_pending", False)):
                self._v0778_unlock_pending = False
                LOGGER.info("锁定状态右键已释放：解除游戏防误触锁定")
                self.set_interaction_lock(False)
        except Exception:
            self._v0778_unlock_pending = False
            LOGGER.warning("锁定状态右键解锁检测失败", exc_info=True)
'''
    s = must(s, old_poll, new_poll, "unlock on release")

    old_menu = r'''    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        if locked:
            # Normally unreachable because the native window is click-through.
            self.set_interaction_lock(False)
            event.accept()
            return
        menu = QMenu(self)
        lock_action = menu.addAction("锁定小美丽（游戏防误触）")
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(True)
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

'''
    new_menu = r'''    def contextMenuEvent(self, event):
        locked = bool(self.cfg.get("lock_position", False))
        menu = QMenu(self)
        lock_action = menu.addAction(
            "解锁小美丽（游戏防误触）" if locked else "锁定小美丽（游戏防误触）"
        )
        menu.addSeparator()
        showhide = menu.addAction("显示/隐藏")
        settings = menu.addAction("设置")
        chosen = menu.exec(event.globalPos())
        if chosen == lock_action:
            self.set_interaction_lock(not locked)
        elif chosen == showhide:
            self.toggle_show_hide()
        elif chosen == settings:
            self.request_settings.emit()

'''
    s = must(s, old_menu, new_menu, "state-aware context menu")

    # Add geometry checks to the existing settings/UI self-test. This catches a
    # future accidental return to the too-narrow 9% crop.
    smoke_anchor = '''        brain.delete_memory(mid)

        return True
'''
    smoke_new = '''        brain.delete_memory(mid)

        rx1, ry1, rx2, ry2 = ROI_REPORT_CARDS
        if not (rx1 <= 0.03 and rx2 >= 0.95 and 0.49 <= ry1 <= 0.51 and 0.81 <= ry2 <= 0.83):
            raise RuntimeError(f"result-card ROI regressed: {ROI_REPORT_CARDS}")
        span = rx2 - rx1
        centers = [rx1 + span * ((i + 0.5) / 5.0) for i in range(5)]
        targets = [0.11, 0.30, 0.49, 0.68, 0.87]
        if any(abs(a - b) > 0.025 for a, b in zip(centers, targets)):
            raise RuntimeError(f"result-card slot centers misaligned: {centers}")

        dark_css = dialog._v0775_stylesheet(True)
        if "settingsScrollViewport" not in dark_css or "#1C3028" not in dark_css:
            raise RuntimeError("dark theme scroll/card palette regression")

        return True
'''
    s = must(s, smoke_anchor, smoke_new, "v0778 self-test")

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.8"',
        'ROI_REPORT_CARDS_RADAR = (0.020, 0.500, 0.960, 0.770)',
        'ROI_REPORT_CARDS = (0.020, 0.500, 0.960, 0.820)',
        'cards = _roi(full_frame, ROI_REPORT_CARDS)',
        'frozen_cards = _roi(full_frame, ROI_REPORT_CARDS)',
        'report_locked_cards_parse_fail_',
        'host.setObjectName("settingsScrollHost")',
        'scroll.viewport().setObjectName("settingsScrollViewport")',
        'card = "#1C3028"',
        'self._v0778_unlock_pending = False',
        '等待释放后解锁',
        '"解锁小美丽（游戏防误触）" if locked else "锁定小美丽（游戏防误触）"',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.8 verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.8 result geometry + dark UI + lock menu fix")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0778.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
