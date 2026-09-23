# -*- coding: utf-8 -*-
from __future__ import annotations
import py_compile
import shutil
import sys
from pathlib import Path

def must(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"missing v0.7.2 patch anchor: {label}")
    return text.replace(old, new, 1)

def patch(source_root: Path, repo_root: Path):
    main_path = source_root / "app" / "src" / "main.py"
    brain_path = source_root / "app" / "src" / "brain_qwen.py"
    ndm_src = repo_root / "build" / "v072" / "ndm_bridge.py"
    ndm_dst = source_root / "app" / "src" / "ndm_bridge.py"
    shutil.copy2(ndm_src, ndm_dst)

    s = main_path.read_text(encoding="utf-8")
    s = must(
        s,
        'APP_NAME = "小美丽 V0.7.1｜NDM Accelerated Local Brain + Qwen3-TTS"\nAPP_VERSION = "0.7.1"',
        'APP_NAME = "小美丽 V0.7.2｜NDM Progress Fix + Local Brain + Qwen3-TTS"\nAPP_VERSION = "0.7.2"',
        "version",
    )
    main_path.write_text(s, encoding="utf-8")

    b = brain_path.read_text(encoding="utf-8")
    old_note = '''            def note(message):
                self.setup_progress.emit(start_pct, str(message))
            ndm_download_and_import(
                url=url,
                filename=filename,
                download_root=self._ndm_download_dir,
                destination=dest,
                min_bytes=max(1, int(expected_min or 1)),
                progress_cb=note,
            )
            self.setup_progress.emit(end_pct, f"NDM 已完成：{filename}")
            return
'''
    new_note = '''            def note(message, done=0, total=0, speed_bps=0):
                try:
                    done = int(done or 0); total = int(total or 0)
                except Exception:
                    done = 0; total = 0
                if total > 0 and done > 0:
                    frac = max(0.0, min(1.0, done / total))
                    pct = start_pct + int((end_pct - start_pct) * frac)
                else:
                    pct = start_pct
                self.setup_progress.emit(max(start_pct, min(end_pct, pct)), str(message))
            expected_bytes = 0
            if dest == MODEL_FILE:
                expected_bytes = 5_030_000_000
            elif expected_min:
                expected_bytes = int(expected_min)
            ndm_download_and_import(
                url=url,
                filename=filename,
                download_root=self._ndm_download_dir,
                destination=dest,
                min_bytes=max(1, int(expected_min or 1)),
                expected_bytes=max(1, int(expected_bytes or expected_min or 1)),
                progress_cb=note,
            )
            self.setup_progress.emit(end_pct, f"NDM 已完成：{filename}")
            return
'''
    b = must(b, old_note, new_note, "NDM progress callback")
    brain_path.write_text(b, encoding="utf-8")

    py_compile.compile(str(main_path), doraise=True)
    py_compile.compile(str(brain_path), doraise=True)
    py_compile.compile(str(ndm_dst), doraise=True)
    print("Patched XiaoMeili source to V0.7.2 with robust NDM detection")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v072.py <source_root> <repo_root>")
    patch(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
