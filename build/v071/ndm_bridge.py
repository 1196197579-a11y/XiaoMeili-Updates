# -*- coding: utf-8 -*-
"""Neat Download Manager bridge for XiaoMeili.

NeatDM's browser-extension receiver listens locally on:
  ws://127.0.0.1:10007/download
with WebSocket subprotocol:
  neatextension.v1

The protocol used here matches the browser-extension compatible text format.
"""
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
    url = str(url or "").strip()
    filename = str(filename or "").strip()
    if not url or not filename:
        raise ValueError("NDM download requires url and filename")
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    lines = [
        "1:GET",
        f"2:{url}",
        "6:normal",
        f"4:{filename}",
    ]
    if origin:
        lines.append(f"Origin: {origin}")
    if mime:
        lines.append(f"8:{mime}")
    message = "\r\n".join(lines) + "\r\n"
    ws = _ws_connect(4)
    try:
        ws.send(message)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _candidate_files(root: Path, filename: str):
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower()
    out = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() != suffix:
                continue
            name = p.stem
            if name == stem or name.startswith(stem + "(") or name.startswith(stem + " ("):
                out.append(p)
    except Exception:
        pass
    return out


def _is_stable(path: Path, min_bytes: int, stable_seconds=2.0):
    try:
        size1 = path.stat().st_size
        if size1 < int(min_bytes or 1):
            return False
        time.sleep(stable_seconds)
        size2 = path.stat().st_size
        return size1 == size2 and size2 >= int(min_bytes or 1)
    except Exception:
        return False


def download_and_import(
    url: str,
    filename: str,
    download_root: str | Path,
    destination: str | Path,
    min_bytes: int,
    progress_cb=None,
    timeout_seconds=21600,
):
    root = Path(download_root).expanduser()
    dest = Path(destination)
    if not root.exists():
        raise FileNotFoundError(f"NDM 下载目录不存在：{root}")

    # Reuse an already completed copy if one exists and passes the minimum size.
    existing = sorted(
        _candidate_files(root, filename),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    for p in existing:
        try:
            if p.stat().st_size >= int(min_bytes or 1) and _is_stable(p, min_bytes, 0.5):
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.unlink()
                shutil.move(str(p), str(dest))
                if progress_cb:
                    progress_cb(f"发现 NDM 已完成文件，正在导入：{filename}")
                return dest
        except Exception:
            continue

    ok, msg = test_connection()
    if not ok:
        raise RuntimeError("没有连接到 Neat Download Manager。请先打开 NDM，再重试。")

    started = time.time()
    send_download(url, filename)
    if progress_cb:
        progress_cb(f"已发送到 NDM：{filename}。实时速度请看 NDM 窗口，小美丽会在完成后自动接管。")

    # NDM generally exposes the final file after its segmented download/merge completes.
    # We recursively watch the configured root because NDM categories may create subfolders.
    while time.time() - started < timeout_seconds:
        candidates = sorted(
            _candidate_files(root, filename),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        for p in candidates:
            try:
                # Ignore stale incomplete/old copies unless they now look complete.
                if p.stat().st_size < int(min_bytes or 1):
                    continue
                if not _is_stable(p, min_bytes, 1.2):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.unlink()
                try:
                    shutil.move(str(p), str(dest))
                except Exception:
                    shutil.copy2(str(p), str(dest))
                    try:
                        p.unlink()
                    except Exception:
                        pass
                if progress_cb:
                    progress_cb(f"NDM 下载完成，已导入：{filename}")
                return dest
            except Exception:
                continue
        time.sleep(1.0)

    raise TimeoutError(f"等待 NDM 下载超时：{filename}")
