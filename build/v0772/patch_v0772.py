# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def must(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing v0.7.7.2 anchor: {label}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s, n = re.subn(
        r'APP_NAME\s*=\s*"[^"]*"\s*\nAPP_VERSION\s*=\s*"0\.7\.7\.1"',
        'APP_NAME = "小美丽 V0.7.7.2｜Drag Physics + Storage Hotfix"\nAPP_VERSION = "0.7.7.2"',
        s,
        count=1,
    )
    if n != 1:
        raise RuntimeError("version replacement failed")

    # ---------- drag layer: stronger physics + stable gaze ----------
    init_old = '''        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0

        self.timer = QTimer(self)
'''
    init_new = '''        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_bias_x = self.gaze_bias_y = 0.0
        self.gaze_motion_x = self.gaze_motion_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.phase = 0.0

        self.timer = QTimer(self)
'''
    s = must(s, init_old, init_new, "drag physics init")

    reset_old = '''        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.recovering = False
'''
    reset_new = '''        self.gaze_target_x = self.gaze_target_y = 0.0
        self.gaze_bias_x = self.gaze_bias_y = 0.0
        self.gaze_motion_x = self.gaze_motion_y = 0.0
        self.gaze_x = self.gaze_y = 0.0
        self.motion_energy = 0.0
        self.phase = 0.0
        self.recovering = False
'''
    s = must(s, reset_old, reset_new, "drag physics reset")

    feed_start = s.index("    def feed_motion(self, dx, dy):\n", s.index("class DragInteractionLayer(QWidget):"))
    feed_end = s.index("    def begin_recover(self):\n", feed_start)
    feed_new = r'''    def set_cursor_focus(self, local_x, local_y, width, height):
        """Keep the dragged pose looking at the grab point, just like the V2 mouse-follow feel."""
        if not self.active:
            return
        try:
            w = max(1.0, float(width))
            h = max(1.0, float(height))
            # Eye centre in the supplied dangling-pose canvas.
            nx = (float(local_x) / w - 0.37) / 0.36
            ny = (float(local_y) / h - 0.61) / 0.34
            self.gaze_bias_x = max(-1.0, min(1.0, nx))
            self.gaze_bias_y = max(-1.0, min(1.0, ny))
        except Exception:
            pass

    def feed_motion(self, dx, dy):
        if not self.active:
            return

        # Use real drag velocity as an impulse. V0.7.7.1 normalised by 16 px and then
        # faded too quickly, so ordinary slow dragging was visually almost static.
        vx = max(-2.4, min(2.4, float(dx) / 7.0))
        vy = max(-2.0, min(2.0, float(dy) / 7.0))

        self.target_x = max(-2.6, min(2.6, self.target_x * 0.30 - vx * 1.15))
        self.target_y = max(-2.2, min(2.2, self.target_y * 0.30 - vy * 1.00))
        self.swing_x = max(-2.6, min(2.6, self.swing_x * 0.42 - vx * 1.35))

        # Motion is also injected into the eyes. The stable bias still points to the
        # cursor/grab position; velocity only adds a small lively glance.
        self.gaze_motion_x = max(-0.70, min(0.70, vx * 0.28))
        self.gaze_motion_y = max(-0.50, min(0.50, vy * 0.22))
        self.motion_energy = min(
            1.0,
            max(self.motion_energy * 0.82, min(1.0, (abs(vx) + abs(vy)) * 0.42)),
        )

'''
    s = s[:feed_start] + feed_new + s[feed_end:]

    tick_start = s.index("    def _tick(self):\n", s.index("class DragInteractionLayer(QWidget):"))
    tick_end = s.index("    def _draw(self, painter", tick_start)
    tick_new = r'''    def _tick(self):
        if not self.active:
            self.timer.stop()
            return

        # Momentum persists long enough to be readable at normal desktop drag speeds.
        self.target_x *= 0.925
        self.target_y *= 0.925
        self.swing_x *= 0.935
        self.gaze_motion_x *= 0.88
        self.gaze_motion_y *= 0.88
        self.motion_energy *= 0.965
        self.phase += 0.16

        wave = __import__("math").sin(self.phase) * self.motion_energy
        wave2 = __import__("math").sin(self.phase * 0.73 + 0.9) * self.motion_energy

        self.body_x = self._follow(self.body_x, self.target_x * 0.52 + wave * 0.12, 0.13)
        self.body_y = self._follow(self.body_y, self.target_y * 0.34 + wave2 * 0.08, 0.12)

        self.head_x = self._follow(self.head_x, self.target_x * 0.72 + wave * 0.18, 0.17)
        self.head_y = self._follow(self.head_y, self.target_y * 0.46 + wave2 * 0.10, 0.16)

        self.front2_x = self._follow(self.front2_x, self.target_x * 0.90 + wave * 0.28, 0.13)
        self.front2_y = self._follow(self.front2_y, self.target_y * 0.58 + wave2 * 0.15, 0.12)
        self.front_x = self._follow(self.front_x, self.target_x * 1.08 + wave * 0.36, 0.115)
        self.front_y = self._follow(self.front_y, self.target_y * 0.68 + wave2 * 0.18, 0.105)

        self.back_x = self._follow(self.back_x, self.target_x * 1.72 + wave * 0.62, 0.075)
        self.back_y = self._follow(self.back_y, self.target_y * 1.05 + wave2 * 0.24, 0.08)
        self.ear_x = self._follow(self.ear_x, self.target_x * 1.82 + wave * 0.70, 0.082)
        self.ear_y = self._follow(self.ear_y, self.target_y * 1.10 + wave2 * 0.30, 0.085)

        self.gaze_target_x = max(-1.0, min(1.0, self.gaze_bias_x * 0.82 + self.gaze_motion_x))
        self.gaze_target_y = max(-1.0, min(1.0, self.gaze_bias_y * 0.74 + self.gaze_motion_y))
        self.gaze_x = self._follow(self.gaze_x, self.gaze_target_x, 0.24)
        self.gaze_y = self._follow(self.gaze_y, self.gaze_target_y, 0.22)

        self.update()

        if self.recovering:
            # During release, also relax the stable cursor bias toward centre.
            self.gaze_bias_x *= 0.84
            self.gaze_bias_y *= 0.84
            values = (
                self.body_x, self.body_y, self.head_x, self.head_y,
                self.front_x, self.front_y, self.front2_x, self.front2_y,
                self.back_x, self.back_y, self.ear_x, self.ear_y,
                self.swing_x, self.gaze_x, self.gaze_y,
            )
            elapsed = time.monotonic() - self.recover_started
            if elapsed >= 0.38 or max(abs(v) for v in values) < 0.010:
                self.active = False
                self.recovering = False
                self.timer.stop()
                self.reset_pose()
                self.hide()
                self.settled.emit()

'''
    s = s[:tick_start] + tick_new + s[tick_end:]

    # Increase actual on-screen translation. Component-specific amplitudes still come from _tick.
    s = must(
        s,
        '''        dx = float(nx) * side * 0.040 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.030 + float(extra_px_y) * (side / 512.0)
''',
        '''        dx = float(nx) * side * 0.070 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.052 + float(extra_px_y) * (side / 512.0)
''',
        "draw translation amplitude",
    )
    # _draw_crop has the same old pair; replace the next occurrence too.
    s = must(
        s,
        '''        dx = float(nx) * side * 0.040 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.030 + float(extra_px_y) * (side / 512.0)
''',
        '''        dx = float(nx) * side * 0.070 + float(extra_px_x) * (side / 512.0)
        dy = float(ny) * side * 0.052 + float(extra_px_y) * (side / 512.0)
''',
        "crop translation amplitude",
    )

    # Correct earring z order. The combined earrings layer must sit behind the face/head.
    paint_old = '''        self._draw(cp, "front2", x0, y0, side, self.front2_x, self.front2_y,
                   rot=self.front2_x * 2.5 + self.swing_x * 0.9, pivot=(0.30, 0.70))

        head_rot = self.head_x * 2.8
        self._draw(cp, "head", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))
'''
    paint_new = '''        self._draw(cp, "front2", x0, y0, side, self.front2_x, self.front2_y,
                   rot=self.front2_x * 3.2 + self.swing_x * 1.2, pivot=(0.30, 0.70))

        # Earrings are physically behind the face. In V0.7.7.1 they were painted after
        # the eyes/head, which put the viewer-left turquoise earring on top of the cheek.
        self._draw(cp, "earrings", x0, y0, side, self.ear_x, self.ear_y,
                   rot=self.ear_x * 8.5 + self.swing_x * 3.0, pivot=(0.50, 0.48))

        head_rot = self.head_x * 4.0 + __import__("math").sin(self.phase * 0.82) * self.motion_energy * 1.1
        self._draw(cp, "head", x0, y0, side, self.head_x, self.head_y,
                   rot=head_rot, pivot=(0.46, 0.42))
'''
    s = must(s, paint_old, paint_new, "earring behind head order")

    old_ear_after = '''        self._draw(cp, "earrings", x0, y0, side, self.ear_x, self.ear_y,
                   rot=self.ear_x * 6.0 + self.swing_x * 2.0, pivot=(0.50, 0.48))
        self._draw(cp, "front", x0, y0, side, self.front_x, self.front_y,
                   rot=self.front_x * 4.4 + self.swing_x * 1.8, pivot=(0.45, 0.36))
'''
    new_ear_after = '''        self._draw(cp, "front", x0, y0, side, self.front_x, self.front_y,
                   rot=self.front_x * 6.4 + self.swing_x * 2.8
                       + __import__("math").sin(self.phase * 0.94 + 0.4) * self.motion_energy * 1.8,
                   pivot=(0.45, 0.36))
'''
    s = must(s, old_ear_after, new_ear_after, "remove foreground earrings")

    # Make ponytail/body motion visibly different in paint rotations as well.
    s = must(
        s,
        '''        self._draw(cp, "back", x0, y0, side, self.back_x, self.back_y,
                   rot=self.back_x * 5.2 + self.swing_x * 2.6, pivot=(0.62, 0.28))
        self._draw(cp, "body", x0, y0, side, self.body_x, self.body_y,
                   rot=self.body_x * 2.0, pivot=(0.52, 0.48))
''',
        '''        self._draw(cp, "back", x0, y0, side, self.back_x, self.back_y,
                   rot=self.back_x * 8.2 + self.swing_x * 4.0
                       + __import__("math").sin(self.phase) * self.motion_energy * 3.6,
                   pivot=(0.62, 0.28))
        self._draw(cp, "body", x0, y0, side, self.body_x, self.body_y,
                   rot=self.body_x * 3.1
                       + __import__("math").sin(self.phase * 0.72 + 1.1) * self.motion_energy * 0.9,
                   pivot=(0.52, 0.48))
''',
        "visible back/body rotation",
    )

    # Give pupils a larger but still constrained range.
    s = must(
        s,
        '''        eye_dx = max(-3.4, min(3.4, self.gaze_x * 3.4))
        eye_dy = max(-2.2, min(2.2, self.gaze_y * 2.2))
''',
        '''        eye_dx = max(-5.2, min(5.2, self.gaze_x * 5.2))
        eye_dy = max(-3.2, min(3.2, self.gaze_y * 3.2))
''',
        "pupil travel",
    )

    # Feed the stable grab point into gaze on every move.
    s = must(
        s,
        '''    def _feed_drag_interaction(self, dx, dy):
        if self.drag_visual_active:
            self.drag_layer.feed_motion(dx, dy)
''',
        '''    def _feed_drag_interaction(self, dx, dy):
        if self.drag_visual_active:
            self.drag_layer.feed_motion(dx, dy)
            if self.drag_offset is not None:
                self.drag_layer.set_cursor_focus(
                    self.drag_offset.x(), self.drag_offset.y(),
                    self.width(), self.height(),
                )
''',
        "drag gaze feed",
    )

    # ---------- storage migration: robust handshake ----------
    storage_start = s.index("    def start_storage_migration(self, target):", s.index("class AppController(QObject):"))
    storage_end = s.index("    def quit(self):", storage_start)
    storage_method = r'''    def start_storage_migration(self, target):
        try:
            if not getattr(sys, "frozen", False):
                raise RuntimeError("开发模式不执行存储迁移，请在正式 XiaoMeili.exe 中操作。")
            helper = Path(resource("assets/storage_migrate.ps1"))
            if not helper.exists():
                raise FileNotFoundError(f"存储迁移助手缺失：{helper}")

            source = xiaomeili_logical_data_root()
            target = Path(str(target or r"D:\XiaoMeiliData"))
            desktop_log = desktop_dir() / "小美丽_D盘迁移日志_请上传给ChatGPT.txt"
            ready_file = Path(tempfile.gettempdir()) / f"XiaoMeili_storage_ready_{os.getpid()}.txt"
            try:
                ready_file.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                desktop_log.unlink(missing_ok=True)
            except Exception:
                pass

            args = [
                "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(helper),
                "-Source", str(source),
                "-Target", str(target),
                "-ParentPid", str(os.getpid()),
                "-ExePath", str(Path(sys.executable)),
                "-DesktopLog", str(desktop_log),
                "-ReadyFile", str(ready_file),
            ]
            proc = subprocess.Popen(
                args,
                cwd=str(Path(sys.executable).parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )

            # V0.7.7.2: Windows Defender / PowerShell cold start can take longer than the
            # old 4-second window. Wait up to 20 seconds. We accept either the explicit
            # READY file or the helper's first log line as proof that the script parsed
            # and entered its protected try/catch path.
            ready = False
            for _ in range(200):
                if ready_file.exists():
                    ready = True
                    break

                rc = proc.poll()
                if rc is not None:
                    detail = ""
                    try:
                        if desktop_log.exists():
                            detail = desktop_log.read_text(
                                encoding="utf-8-sig", errors="replace"
                            )[-3000:]
                    except Exception:
                        pass
                    raise RuntimeError(f"存储迁移助手启动失败（exit={rc}）。{detail}")

                try:
                    if desktop_log.exists():
                        probe = desktop_log.read_text(
                            encoding="utf-8-sig", errors="replace"
                        )
                        if "D-drive migration helper started." in probe:
                            ready = True
                            break
                except Exception:
                    pass

                time.sleep(0.10)

            if not ready:
                try:
                    proc.terminate()
                except Exception:
                    pass
                detail = ""
                try:
                    if desktop_log.exists():
                        detail = desktop_log.read_text(
                            encoding="utf-8-sig", errors="replace"
                        )[-3000:]
                except Exception:
                    pass
                raise RuntimeError(
                    "存储迁移助手 20 秒内没有完成启动握手。"
                    "为保护现有数据，小美丽保持运行且没有开始迁移。"
                    + (f"\n\n迁移助手日志：\n{detail}" if detail else "")
                )

            LOGGER.info("D盘迁移助手握手成功：%s -> %s", source, target)
            self.quit()
        except Exception as exc:
            LOGGER.exception("启动 D 盘迁移失败")
            QMessageBox.critical(
                None,
                "小美丽存储迁移失败",
                f"没有改动现有数据。错误：{type(exc).__name__}: {exc}\n\n"
                "如果桌面生成了「小美丽_D盘迁移日志_请上传给ChatGPT.txt」，请直接上传给我。",
            )
            if self.settings:
                try:
                    self.settings.storage_migrate_btn.setEnabled(True)
                    self.settings._refresh_storage_status()
                except Exception:
                    pass

'''
    s = s[:storage_start] + storage_method + s[storage_end:]

    main_path.write_text(s, encoding="utf-8")
    py_compile.compile(str(main_path), doraise=True)

    final = main_path.read_text(encoding="utf-8")
    checks = [
        'APP_VERSION = "0.7.7.2"',
        'def set_cursor_focus(self, local_x, local_y, width, height):',
        'self.gaze_bias_x = self.gaze_bias_y = 0.0',
        'self.target_x * 1.72',
        'self.ear_x * 8.5',
        'eye_dx = max(-5.2',
        '存储迁移助手 20 秒内没有完成启动握手',
        'D-drive migration helper started.',
    ]
    for token in checks:
        if token not in final:
            raise RuntimeError(f"v0.7.7.2 static verification failed: {token}")

    print("Patched XiaoMeili source to V0.7.7.2 drag physics + storage hotfix")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v0772.py <source_root>")
    patch(Path(sys.argv[1]).resolve())
