# -*- coding: utf-8 -*-
"""Transparent WebM import support for XiaoMeili action assets.

This module is deliberately independent from Qt so it can be validated without
starting the desktop pet. It only reads the user's source file and writes a new
app-owned transparent WebP destination. The original source is never modified.
"""
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image


class NoTransparentAlpha(RuntimeError):
    """Raised when a WebM is valid video but does not contain a usable alpha plane."""


def _decoder_candidates(codec: str):
    codec = str(codec or "").lower()
    if "vp9" in codec:
        return (("-c:v", "libvpx-vp9"),)
    if "vp8" in codec:
        return (("-c:v", "libvpx"),)
    # WebM alpha is normally VP8/VP9. Unknown codecs are not force-decoded,
    # because a wrong decoder could make a valid file look corrupt.
    return ((),)


def _probe_codec(path: Path) -> str:
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        meta = next(reader)
        return str(meta.get("codec") or "")
    finally:
        try:
            reader.close()
        except Exception:
            pass


def _alpha_pix_fmt(pix_fmt: str) -> bool:
    fmt = str(pix_fmt or "").split("(", 1)[0].strip().lower()
    return (
        fmt.startswith("yuva")
        or fmt.startswith("gbrap")
        or fmt in {"rgba", "bgra", "argb", "abgr", "ya8", "ya16le", "ya16be"}
    )


def _alpha_decoder(path: Path):
    if path.suffix.lower() != ".webm":
        raise NoTransparentAlpha("只有 WebM 会进入透明 Alpha 直读流程")
    codec = _probe_codec(path)
    last_error = None
    for candidate in _decoder_candidates(codec):
        params = list(candidate)
        reader = None
        try:
            reader = imageio_ffmpeg.read_frames(
                str(path), pix_fmt="rgba", bits_per_pixel=32,
                input_params=params or None,
            )
            meta = next(reader)
            if _alpha_pix_fmt(meta.get("pix_fmt", "")):
                return params, meta
        except Exception as exc:
            last_error = exc
        finally:
            try:
                if reader is not None:
                    reader.close()
            except Exception:
                pass
    if last_error is not None and codec and not any(x in codec.lower() for x in ("vp8", "vp9")):
        raise RuntimeError(f"透明 WebM 解码器无法读取该编码：{codec}") from last_error
    raise NoTransparentAlpha("未检测到 WebM 透明 Alpha 通道")


def has_transparent_alpha(path) -> bool:
    """Return True only when the WebM exposes an alpha-capable decoded pixel format."""
    try:
        _alpha_decoder(Path(path))
        return True
    except NoTransparentAlpha:
        return False


def _add_soft_white_glow(rgba, outline_px=1, glow_px=6,
                         outline_strength=0.42, glow_strength=0.24):
    """Match XiaoMeili's existing subtle white rim/glow without re-keying alpha."""
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        return rgba
    src = rgba.astype(np.float32)
    alpha = src[..., 3] / 255.0
    if float(alpha.max()) <= 0.001:
        return rgba

    a8 = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    opx = max(1, int(outline_px))
    gpx = max(opx + 1, int(glow_px))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (opx * 2 + 1, opx * 2 + 1))
    dilated = cv2.dilate(a8, kernel, iterations=1).astype(np.float32) / 255.0
    outline = np.clip(dilated - alpha, 0.0, 1.0) * float(outline_strength)

    kernel_glow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gpx * 2 + 1, gpx * 2 + 1))
    expanded = cv2.dilate(a8, kernel_glow, iterations=1)
    sigma = max(1.2, gpx * 0.62)
    blurred = cv2.GaussianBlur(expanded, (0, 0), sigmaX=sigma, sigmaY=sigma).astype(np.float32) / 255.0
    halo = np.clip(blurred - alpha, 0.0, 1.0) * float(glow_strength)
    white_a = np.maximum(outline, halo) * (1.0 - alpha)

    out_a = alpha + white_a * (1.0 - alpha)
    numer = src[..., :3] * alpha[..., None] + 255.0 * white_a[..., None] * (1.0 - alpha[..., None])
    denom = np.maximum(out_a[..., None], 1e-6)
    out_rgb = np.where(out_a[..., None] > 1e-6, numer / denom, 0.0)
    return np.clip(np.dstack([out_rgb, out_a * 255.0]), 0, 255).astype(np.uint8)


def convert_transparent_webm_to_webp(src, dst, max_width=420, target_fps=12):
    """Read WebM alpha directly and create XiaoMeili's normal transparent WebP cache.

    No chroma key/despill is applied. The source file is opened read-only; output
    is a new file under the caller-selected app cache path.
    """
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    params, _ = _alpha_decoder(src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    reader = imageio_ffmpeg.read_frames(
        str(src), pix_fmt="rgba", bits_per_pixel=32,
        input_params=params or None,
    )
    frames = []
    try:
        meta = next(reader)
        width, height = [int(v) for v in meta.get("size", (0, 0))]
        if width <= 0 or height <= 0:
            raise RuntimeError("透明 WebM 尺寸无效")
        fps = float(meta.get("fps") or 0.0)
        if not np.isfinite(fps) or fps <= 0.5:
            fps = 30.0
        out_fps = max(1.0, min(float(target_fps), fps))
        next_t = 0.0
        idx = 0
        max_frames = int(out_fps * 45)
        alpha_seen = False

        for raw in reader:
            if len(frames) >= max_frames:
                break
            t = idx / fps
            idx += 1
            if t + 1e-6 < next_t:
                continue
            next_t += 1.0 / out_fps
            arr = np.frombuffer(raw, dtype=np.uint8)
            expected = width * height * 4
            if arr.size != expected:
                raise RuntimeError("透明 WebM 解码帧尺寸异常")
            rgba = arr.reshape(height, width, 4).copy()
            if width > int(max_width):
                new_h = max(2, int(round(height * int(max_width) / width)))
                rgba = cv2.resize(rgba, (int(max_width), new_h), interpolation=cv2.INTER_AREA)
            if np.any(rgba[..., 3] < 250):
                alpha_seen = True
            rgba = _add_soft_white_glow(rgba)
            frames.append(Image.fromarray(rgba, "RGBA"))

        if not frames:
            raise RuntimeError("透明 WebM 没有可读取帧")
        if not alpha_seen:
            raise NoTransparentAlpha("WebM 声明了 Alpha，但未读取到实际透明像素")

        duration = max(20, int(round(1000.0 / out_fps)))
        kwargs = dict(save_all=True, append_images=frames[1:], duration=duration,
                      loop=1, lossless=True, quality=100, method=4)
        try:
            frames[0].save(dst, "WEBP", exact=True, **kwargs)
        except TypeError:
            frames[0].save(dst, "WEBP", **kwargs)
        return len(frames), out_fps
    finally:
        try:
            reader.close()
        except Exception:
            pass
        for frame in frames:
            try:
                frame.close()
            except Exception:
                pass
        frames.clear()
