# -*- coding: utf-8 -*-
"""Cloud configuration + API secret helpers for XiaoMeili V0.10.0.7.

Security model on Windows:
- API Key is never stored in config.json or source code.
- It is encrypted with Windows DPAPI (Current User) and written under
  C:\\Users\\Public\\XiaoMeiliData\\cloud\\aliyun_api_key.dpapi.
- Only the same Windows user profile can decrypt it.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path


def _data_root() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    else:
        root = Path.home() / ".xiaomeili"
    root.mkdir(parents=True, exist_ok=True)
    return root


CLOUD_ROOT = _data_root() / "cloud"
CLOUD_ROOT.mkdir(parents=True, exist_ok=True)
SECRET_FILE = CLOUD_ROOT / "aliyun_api_key.dpapi"

DEFAULT_BRAIN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BRAIN_MODEL = "qwen3-8b"
DEFAULT_TTS_MODEL = "qwen-audio-3.1-tts-flash"
DEFAULT_TTS_VOICE = "qwen-audio-3.1-tts-flash-bailian-6d3dea9f00b74622854b4394fa6119f1"
DEFAULT_TTS_INSTRUCTION = ""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    if not data:
        data = b"\0"
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _protect_windows(data: bytes) -> bytes:
    in_blob, _in_buf = _blob(data)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), "XiaoMeili Aliyun API Key", None, None, None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect_windows(data: bytes) -> bytes:
    in_blob, _in_buf = _blob(data)
    out_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def save_api_key(api_key: str) -> None:
    key = str(api_key or "").strip()
    if not key:
        raise ValueError("API Key 不能为空。")
    CLOUD_ROOT.mkdir(parents=True, exist_ok=True)
    raw = key.encode("utf-8")
    if os.name == "nt":
        payload = b"DPAPI1\n" + base64.b64encode(_protect_windows(raw))
    else:
        # Non-Windows fallback exists only for source-level development/tests.
        # The production target is Windows and uses DPAPI above.
        payload = b"DEV1\n" + base64.b64encode(raw)
    temp = SECRET_FILE.with_suffix(".tmp")
    temp.write_bytes(payload)
    temp.replace(SECRET_FILE)


def load_api_key() -> str:
    try:
        payload = SECRET_FILE.read_bytes()
        header, encoded = payload.split(b"\n", 1)
        data = base64.b64decode(encoded.strip())
        if header == b"DPAPI1" and os.name == "nt":
            return _unprotect_windows(data).decode("utf-8").strip()
        if header == b"DEV1" and os.name != "nt":
            return data.decode("utf-8").strip()
    except Exception:
        return ""
    return ""


def has_api_key() -> bool:
    return bool(load_api_key())


def clear_api_key() -> None:
    try:
        SECRET_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def cloud_cfg(cfg: dict) -> dict:
    cloud = cfg.get("cloud", {}) if isinstance(cfg, dict) and isinstance(cfg.get("cloud"), dict) else {}
    return {
        "mode": str(cloud.get("mode") or "cloud_preferred").strip().lower(),
        "brain_base_url": str(cloud.get("brain_base_url") or DEFAULT_BRAIN_BASE_URL).strip().rstrip("/"),
        "brain_model": str(cloud.get("brain_model") or DEFAULT_BRAIN_MODEL).strip(),
        "tts_model": str(cloud.get("tts_model") or DEFAULT_TTS_MODEL).strip(),
        "tts_voice": str(cloud.get("tts_voice") or DEFAULT_TTS_VOICE).strip(),
        "tts_instruction": str(cloud.get("tts_instruction") if cloud.get("tts_instruction") is not None else DEFAULT_TTS_INSTRUCTION).strip(),
        "fallback_local": bool(cloud.get("fallback_local", True)),
        "first_response_timeout_ms": max(1800, min(8000, int(cloud.get("first_response_timeout_ms", 3200) or 3200))),
    }



def audio_tts_ws_url(brain_base_url: str) -> str:
    """Derive the Beijing workspace WebSocket endpoint from the saved OpenAI base URL.

    Example:
      https://ws-xxxx.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
    ->wss://ws-xxxx.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference

    Falls back to the shared Beijing endpoint for legacy configs.
    """
    from urllib.parse import urlparse
    raw = str(brain_base_url or DEFAULT_BRAIN_BASE_URL).strip()
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = str(parsed.netloc or "").strip()
    if host:
        return f"wss://{host}/api-ws/v1/inference"
    return "wss://dashscope.aliyuncs.com/api-ws/v1/inference"

def brain_endpoint(base_url: str) -> str:
    base = str(base_url or DEFAULT_BRAIN_BASE_URL).strip().rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def test_brain_connection(api_key: str, base_url: str, model: str = DEFAULT_BRAIN_MODEL, timeout: float = 8.0):
    key = str(api_key or "").strip()
    if not key:
        return False, "尚未保存阿里云 API Key。", None
    body = {
        "model": str(model or DEFAULT_BRAIN_MODEL),
        "messages": [{"role": "user", "content": "只回复：连接成功"}],
        "enable_thinking": False,
        "stream": False,
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        brain_endpoint(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        elapsed = int((time.perf_counter() - started) * 1000)
        text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            try:
                from cloud_usage import record_brain_usage
                inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                if inp or out:
                    record_brain_usage(inp, out, tag="connection_test")
            except Exception:
                pass
        if not text:
            return False, "API 已连接，但模型没有返回文本。", elapsed
        return True, f"云端大脑连接正常 · {elapsed}ms", elapsed
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return False, f"连接失败：{type(exc).__name__}: {exc}", elapsed
