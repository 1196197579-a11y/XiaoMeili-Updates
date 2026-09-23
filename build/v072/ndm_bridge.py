# -*- coding: utf-8 -*-
"""Robust Neat Download Manager bridge for XiaoMeili V0.7.2."""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger("XiaoMeili")
NDM_ENDPOINT = "ws://127.0.0.1:10007/download"
NDM_PROTOCOL = "neatextension.v1"
_TEMP_SUFFIXES = {".part", ".tmp", ".download", ".crdownload", ".partial"}


def _ws_connect(timeout=3):
    import websocket
    return websocket.create_connection(
        NDM_ENDPOINT,
        timeout=float(timeout),
        subprotocols=[NDM_PROTOCOL],
        enable_multithread=False,
    )


def test_connection(timeout=3):
    try:
        ws = _ws_connect(timeout)
        try:
            return True, "已连接 Neat Download Manager"
        finally:
            ws.close()
    except Exception as exc:
        return False, f"NDM 未连接：{type(exc).__name__}: {exc}"


def send_download(url: str, filename: str, mime="application/octet-stream"):
    parsed = urlparse(str(url or ""))
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    lines = ["1:GET", f"2:{url}", "6:normal", f"4:{filename}"]
    if origin:
        lines.append(f"Origin: {origin}")
    if mime:
        lines.append(f"8:{mime}")
    ws = _ws_connect(4)
    try:
        ws.send("\r\n".join(lines) + "\r\n")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _norm_name(name: str):
    return str(name or "").lower().replace(" ", "")


def _candidate_files(root: Path, filename: str, started_at: float | None = None):
    wanted = Path(filename)
    wanted_stem = _norm_name(wanted.stem)
    wanted_suffix = wanted.suffix.lower()
    out = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except Exception:
                continue
            # Ignore obviously ancient unrelated files once a task has been sent.
            if started_at and st.st_mtime < started_at - 15:
                continue
            name = _norm_name(p.stem)
            suffix = p.suffix.lower()
            # NDM may ignore the extension-side requested filename and choose the server filename,
            # or append duplicate markers. Be deliberately tolerant.
            stem_match = (
                name == wanted_stem
                or name.startswith(wanted_stem + "(")
                or wanted_stem in name
            )
            suffix_match = (
                suffix == wanted_suffix
                or wanted_suffix in p.name.lower()
                or suffix in _TEMP_SUFFIXES
            )
            if stem_match and suffix_match:
                out.append(p)
    except Exception:
        pass
    return out


def _snapshot(root: Path, filename: str):
    snap = {}
    for p in _candidate_files(root, filename):
        try:
            st = p.stat()
            snap[str(p)] = (st.st_size, st.st_mtime_ns)
        except Exception:
            pass
    return snap


def _emit(cb, message, done=0, total=0, speed_bps=0):
    if not cb:
        return
    try:
        cb(message, int(done or 0), int(total or 0), float(speed_bps or 0))
    except TypeError:
        cb(message)


def _stable_final(path: Path, min_bytes: int, stable_seconds=4.0):
    # Require both size and mtime to remain unchanged. This avoids treating an NDM
    # preallocated target file as completed while segments are still being merged/written.
    try:
        st1 = path.stat()
        if st1.st_size < int(min_bytes or 1):
            return False
        if path.suffix.lower() in _TEMP_SUFFIXES:
            return False
        time.sleep(stable_seconds)
        st2 = path.stat()
        return (
            st2.st_size >= int(min_bytes or 1)
            and st1.st_size == st2.st_size
            and st1.st_mtime_ns == st2.st_mtime_ns
        )
    except Exception:
        return False


def _import_file(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except Exception:
            pass
    try:
        shutil.move(str(src), str(dest))
    except Exception:
        shutil.copy2(str(src), str(dest))
        try:
            src.unlink()
        except Exception:
            pass


def download_and_import(
    url: str,
    filename: str,
    download_root: str | Path,
    destination: str | Path,
    min_bytes: int,
    expected_bytes: int | None = None,
    progress_cb=None,
    timeout_seconds=21600,
):
    root = Path(download_root).expanduser()
    dest = Path(destination)
    if not root.exists():
        raise FileNotFoundError(f"NDM 下载目录不存在：{root}")

    expected = int(expected_bytes or 0)
    if expected <= 0:
        expected = int(min_bytes or 0)

    # First reuse any completed file already sitting in the NDM directory. This matters
    # when the user updated XiaoMeili while NDM kept downloading in the background.
    existing = sorted(_candidate_files(root, filename), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in existing:
        try:
            if _stable_final(p, min_bytes, 1.0):
                _emit(progress_cb, f"发现已完成文件，正在导入：{p.name}", p.stat().st_size, expected, 0)
                _import_file(p, dest)
                return dest
        except Exception:
            continue

    baseline = _snapshot(root, filename)
    ok, _ = test_connection()
    if not ok:
        raise RuntimeError("没有连接到 Neat Download Manager。请先打开 NDM，再重试。")

    started = time.time()
    send_download(url, filename)
    _emit(progress_cb, f"已发送到 NDM：{filename}，等待 NDM 写入文件…", 0, expected, 0)

    last_bytes = 0
    last_time = time.time()
    last_seen = None
    while time.time() - started < timeout_seconds:
        candidates = sorted(
            _candidate_files(root, filename, started_at=started),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )

        # If NDM renamed the file unexpectedly, fall back to the newest matching-extension
        # file created after this task started. This is limited to the chosen NDM directory.
        if not candidates:
            try:
                wanted_suffix = Path(filename).suffix.lower()
                for p in root.rglob("*"):
                    if not p.is_file():
                        continue
                    st = p.stat()
                    if st.st_mtime < started - 5:
                        continue
                    if wanted_suffix and (p.suffix.lower() == wanted_suffix or wanted_suffix in p.name.lower()):
                        candidates.append(p)
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            except Exception:
                pass

        if candidates:
            p = candidates[0]
            try:
                st = p.stat()
                now = time.time()
                dt = max(0.2, now - last_time)
                speed = max(0.0, (st.st_size - last_bytes) / dt) if last_seen == str(p) else 0.0
                last_bytes = st.st_size
                last_time = now
                last_seen = str(p)
                if expected > 0:
                    detail = f"NDM 下载中：{st.st_size/1024/1024/1024:.2f} / {expected/1024/1024/1024:.2f} GB"
                else:
                    detail = f"NDM 下载中：已写入 {st.st_size/1024/1024:.0f} MB"
                if speed > 0:
                    detail += f" · {speed/1024/1024:.1f} MB/s"
                _emit(progress_cb, detail, st.st_size, expected, speed)

                # A final-name file must be large enough and fully stable before import.
                if st.st_size >= int(min_bytes or 1) and _stable_final(p, min_bytes, 3.0):
                    final_size = p.stat().st_size
                    _emit(progress_cb, f"NDM 下载完成，正在导入：{p.name}", final_size, expected, 0)
                    _import_file(p, dest)
                    return dest
            except Exception:
                LOGGER.debug("NDM candidate scan transient error", exc_info=True)
        else:
            _emit(progress_cb, f"NDM 已接收任务，仍在等待文件出现在：{root}", 0, expected, 0)

        time.sleep(0.8)

    raise TimeoutError(f"等待 NDM 下载超时：{filename}")
