# -*- coding: utf-8 -*-
"""Lightweight speech-input bridge for XiaoMeili V0.8.5.

The frozen desktop app stays small. FunASR/FSMN-VAD live in the same external
Python environment already used by Qwen3-TTS and run in a separate CPU worker.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOGGER = logging.getLogger("XiaoMeili")


def _data_root() -> Path:
    if sys.platform == "win32":
        root = Path(os.getenv("PUBLIC") or r"C:\Users\Public") / "XiaoMeiliData"
    else:
        root = Path.home() / ".xiaomeili"
    root.mkdir(parents=True, exist_ok=True)
    return root


DATA_ROOT = _data_root()
VOICE_RUNTIME_ROOT = DATA_ROOT / "voice_runtime" / "qwen3_tts"
VENV_DIR = VOICE_RUNTIME_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
SPEECH_ROOT = DATA_ROOT / "speech_runtime" / "funasr"
ASR_MODEL_DIR = DATA_ROOT / "speech" / "fun_asr_nano_2512"
VAD_MODEL_DIR = DATA_ROOT / "speech" / "fsmn_vad"
ASR_MARKER = ASR_MODEL_DIR / ".xiaomeili_asr_ready_v080"
VAD_MARKER = VAD_MODEL_DIR / ".xiaomeili_vad_ready_v080"
RUNTIME_MARKER = SPEECH_ROOT / ".xiaomeili_runtime_ready_v080"
WORKER_SCRIPT = SPEECH_ROOT / "speech_worker.py"
SETUP_LOG = DATA_ROOT / "logs" / "speech_setup.log"
WORKER_LOG = DATA_ROOT / "logs" / "speech_worker.log"

ASR_MODEL_ID = "FunAudioLLM/Fun-ASR-Nano-2512"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
HOTWORDS = "美丽美丽 小美丽 无畏契约 VALORANT 贤者 KDA 保枪 大狙 狙击枪 步枪 冰墙 玉城"


WORKER_CODE = r'''# -*- coding: utf-8 -*-
import argparse
import contextlib
import json
import logging
import os
import queue
import re
import sys
import tempfile
import traceback
import threading
import wave
import time
from pathlib import Path

EVENT_PREFIX = "XMEVENT|"
EVENT_STREAM = sys.stdout


def emit(kind, **payload):
    row = {"event": kind, **payload}
    EVENT_STREAM.write(EVENT_PREFIX + json.dumps(row, ensure_ascii=False) + "\n")
    EVENT_STREAM.flush()


def setup_log(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=path, level=logging.INFO, encoding="utf-8", force=True,
                        format="%(asctime)s [%(levelname)s] %(message)s")


_DESKTOP_REPORT_ONCE = set()


def _desktop_dir():
    try:
        if sys.platform == "win32":
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            # CSIDL_DESKTOPDIRECTORY = 0x10, honors redirected/OneDrive desktop.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                p = Path(buf.value)
                p.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    for root in (os.environ.get("OneDrive"), os.environ.get("USERPROFILE"), str(Path.home())):
        if not root:
            continue
        p = Path(root) / "Desktop"
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            continue
    return Path.home()


def desktop_diagnostic(code, message, log_path="", extra=""):
    code = re.sub(r"[^A-Za-z0-9_-]+", "_", str(code or "UNKNOWN"))[:48]

    if code in {"ASR_EMPTY", "VAD_END_MISSING"}:
        logging.warning("[RECOVERABLE_SPEECH_EVENT] code=%s message=%s", code, message)
        return ""

    if code in _DESKTOP_REPORT_ONCE:
        return ""
    _DESKTOP_REPORT_ONCE.add(code)
    try:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        log_file = Path(log_path) if str(log_path or "").strip() else None
        base = log_file.parent if log_file is not None else Path.cwd()
        target_dir = base / "diagnostics" / "speech"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"speech_{stamp}_{code}.txt"
        tail = ""
        try:
            if log_file is not None and log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-180:])
        except Exception as exc:
            tail = f"<读取 speech_worker.log 失败: {exc}>"
        body = [
            "小美丽 V0.10.0 语音诊断日志",
            f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"故障代码: {code}",
            f"说明: {message}",
            f"原始日志: {log_path}",
        ]
        if extra:
            body.extend(["", "附加信息:", str(extra)])
        body.extend(["", "speech_worker.log 最后 180 行:", tail])
        target.write_text("\n".join(body), encoding="utf-8")
        logging.error("[INTERNAL_SPEECH_DIAGNOSTIC] %s code=%s message=%s", target, code, message)
        return str(target)
    except Exception:
        logging.exception("[INTERNAL_SPEECH_DIAGNOSTIC] failed to write diagnostic")
        return ""


def download_model(model_id, target):
    from modelscope import snapshot_download
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(model_id, local_dir=str(target))


def extract_text(result):
    if isinstance(result, list) and result:
        row = result[0]
    elif isinstance(result, dict):
        row = result
    else:
        return ""
    if isinstance(row, dict):
        for key in ("text", "sentence", "value"):
            val = row.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def parse_vad_events(res):
    events = []
    rows = res if isinstance(res, list) else [res]
    for row in rows:
        if not isinstance(row, dict):
            continue
        vals = row.get("value") or []
        for pair in vals:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                a, b = int(pair[0]), int(pair[1])
            except Exception:
                continue
            if a >= 0 and b < 0:
                events.append(("start", a))
            elif a < 0 and b >= 0:
                events.append(("end", b))
            elif a >= 0 and b >= 0:
                events.append(("start", a)); events.append(("end", b))
    return events


def resample_linear(x, src_rate, dst_rate=16000):
    import numpy as np
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if int(src_rate) == int(dst_rate) or x.size < 2:
        return x
    out_n = max(1, int(round(x.size * float(dst_rate) / float(src_rate))))
    old = np.linspace(0.0, 1.0, num=x.size, endpoint=False)
    new = np.linspace(0.0, 1.0, num=out_n, endpoint=False)
    return np.interp(new, old, x).astype(np.float32)


def listen(args):
    import numpy as np
    import sounddevice as sd
    import torch
    from funasr import AutoModel

    emit("state", code="loading", label="正在加载语音识别组件")
    vad = AutoModel(model=str(args.vad_model_dir), disable_update=True, device="cpu")
    asr_model_dir = Path(args.asr_model_dir)
    try:
        import funasr
        logging.info("[BOOT] FunASR=%s", getattr(funasr, "__version__", "unknown"))
    except Exception:
        logging.exception("[BOOT] failed to read FunASR version")
    try:
        asr = AutoModel(
            model=str(asr_model_dir),
            disable_update=True,
            device="cpu",
        )
        logging.info("[ASR_LOADER] built-in registry")
    except Exception:
        logging.exception("[ASR_LOADER] built-in loader failed; retrying remote_code")
        asr = AutoModel(
            model=str(asr_model_dir),
            trust_remote_code=True,
            remote_code=str(asr_model_dir / "model.py"),
            disable_update=True,
            device="cpu",
        )
        logging.info("[ASR_LOADER] remote_code fallback")

    device = None if int(args.device_index) < 0 else int(args.device_index)
    try:
        info = sd.query_devices(device, "input")
        default_rate = int(round(float(info.get("default_samplerate", 16000) or 16000)))
        logging.info("[MIC] device=%s name=%r default_rate=%s", device, info.get("name"), default_rate)
    except Exception:
        default_rate = 16000
    sample_rate = 16000
    try_rates = [16000]
    if default_rate != 16000:
        try_rates.append(default_rate)

    paused = threading.Event()
    stopping = threading.Event()
    q = queue.Queue(maxsize=30)

    def commands():
        while not stopping.is_set():
            line = sys.stdin.readline()
            if not line:
                stopping.set(); return
            cmd = line.strip().lower()
            if cmd == "pause":
                paused.set(); emit("state", code="paused", label="语音监听已暂停")
            elif cmd == "resume":
                paused.clear(); emit("state", code="listening", label="等待“美丽美丽”")
            elif cmd in {"stop", "quit", "shutdown"}:
                stopping.set(); return

    threading.Thread(target=commands, name="XiaoMeiliSpeechCommands", daemon=True).start()

    stream = None
    last_exc = None
    for rate in try_rates:
        block = max(160, int(rate * 0.20))
        def callback(indata, frames, time_info, status, _rate=rate):
            if stopping.is_set() or paused.is_set():
                return
            try:
                mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
                if _rate != 16000:
                    mono = resample_linear(mono, _rate, 16000)
                try:
                    q.put_nowait(mono)
                except queue.Full:
                    try: q.get_nowait()
                    except Exception: pass
                    try: q.put_nowait(mono)
                    except Exception: pass
            except Exception:
                pass
        try:
            stream = sd.InputStream(device=device, channels=1, samplerate=rate,
                                    dtype="float32", blocksize=block, callback=callback)
            stream.start(); sample_rate = rate; break
        except Exception as exc:
            last_exc = exc
            stream = None
    if stream is None:
        raise RuntimeError(f"无法打开麦克风：{last_exc}")

    emit("ready", sample_rate=sample_rate)
    emit("state", code="listening", label="等待“美丽美丽”")

    vad_cache = {}
    preroll = []
    speech = []
    active = False
    noise_floor_rms = 0.002
    active_peak_rms = 0.0
    silent_chunks = 0
    active_started_at = 0.0
    max_chunks = int(25 / 0.20)  # final hard cap 25 s
    silence_end_chunks = 4       # 0.8 s at 200 ms/chunk

    def recognize_and_emit(audio, reason):
        seconds = float(audio.size) / 16000.0 if getattr(audio, "size", 0) else 0.0
        logging.info("[ASR_BEGIN] reason=%s samples=%s seconds=%.3f", reason, getattr(audio, "size", 0), seconds)
        # Fun-ASR-Nano's current ChatML bridge only constructs an audio
        # request for str paths or torch.Tensor waveforms. A raw numpy array
        # reaches generate_chatml() but produces None, which later crashes in
        # data_template() with: TypeError: 'NoneType' object is not iterable.
        audio_np = np.ascontiguousarray(
            np.asarray(audio, dtype=np.float32).reshape(-1)
        )
        audio_tensor = torch.from_numpy(audio_np).to(dtype=torch.float32)
        logging.info(
            "[ASR_INPUT] type=torch.Tensor shape=%s dtype=%s fs=16000 min=%.6f max=%.6f rms=%.6f",
            tuple(audio_tensor.shape),
            audio_tensor.dtype,
            float(audio_np.min()) if audio_np.size else 0.0,
            float(audio_np.max()) if audio_np.size else 0.0,
            float(np.sqrt(np.mean(audio_np.astype(np.float64) ** 2))) if audio_np.size else 0.0,
        )
        asr_kwargs = {
            "cache": {},
            "language": "中文",
            "itn": True,
            "hotwords": [x for x in str(args.hotwords).split() if x],
            "batch_size": 1,
        }

        # IMPORTANT for FunASR 1.4.16 Fun-ASR-Nano:
        # Do NOT pass fs= here. Nano's data_load_speech() already calls
        # load_audio_text_image_video(..., fs=frontend.fs, **kwargs).
        # Passing fs through kwargs duplicates that keyword and crashes.
        try:
            logging.info("[ASR_TRANSPORT] primary=torch.Tensor implicit_frontend_fs")
            res = asr.generate(input=audio_tensor, **asr_kwargs)
        except Exception as tensor_exc:
            tensor_tb = traceback.format_exc()
            logging.exception("[ASR_TRANSPORT] tensor path failed; retrying PCM16 WAV file")
            tmp_path = None
            try:
                pcm16 = np.clip(audio_np, -1.0, 1.0)
                pcm16 = (pcm16 * 32767.0).astype(np.int16)
                fd, tmp_path = tempfile.mkstemp(prefix="xiaomeili_asr_", suffix=".wav")
                os.close(fd)
                with wave.open(tmp_path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(pcm16.tobytes())
                logging.warning("[ASR_TRANSPORT_FALLBACK] torch.Tensor -> wav path=%s", tmp_path)
                res = asr.generate(input=tmp_path, **asr_kwargs)
            except Exception as wav_exc:
                wav_tb = traceback.format_exc()
                raise RuntimeError(
                    "Fun-ASR-Nano tensor 与 WAV 两种输入方式均失败。"
                    f" tensor={type(tensor_exc).__name__}: {tensor_exc};"
                    f" wav={type(wav_exc).__name__}: {wav_exc}\n"
                    f"--- tensor traceback ---\n{tensor_tb}\n"
                    f"--- wav traceback ---\n{wav_tb}"
                ) from wav_exc
            finally:
                if tmp_path:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception:
                        pass

        text = extract_text(res)
        logging.info("[ASR_SUCCESS] text=%r", text)
        normalized = re.sub(r"[\s，,。.!！？?、:：]+", "", text or "")
        logging.info("[ASR_RAW] %r", text)
        logging.info("[ASR_NORMALIZED] %r", normalized)
        if text:
            emit("utterance", text=text)
        else:
            logging.warning("[ASR_EMPTY] no text returned")
        return text

    logging.info("[READY] speech worker listening")
    try:
        while not stopping.is_set():
            if paused.is_set():
                time.sleep(0.05)
                vad_cache = {}; preroll = []; speech = []; active = False
                active_peak_rms = 0.0; silent_chunks = 0; active_started_at = 0.0
                try:
                    while True: q.get_nowait()
                except Exception:
                    pass
                continue
            try:
                chunk = q.get(timeout=0.15)
            except queue.Empty:
                continue

            chunk_rms = float(np.sqrt(np.mean(np.asarray(chunk, dtype=np.float64) ** 2))) if getattr(chunk, "size", 0) else 0.0
            if not active:
                noise_floor_rms = (noise_floor_rms * 0.94) + (chunk_rms * 0.06)
            preroll.append(chunk)
            if len(preroll) > 3:
                preroll.pop(0)
            try:
                vad_res = vad.generate(input=chunk, cache=vad_cache, is_final=False, chunk_size=200)
                events = parse_vad_events(vad_res)
            except Exception as exc:
                logging.exception("VAD failed")
                desktop_diagnostic(
                    "VAD_EXCEPTION",
                    f"FSMN-VAD 调用失败：{type(exc).__name__}: {exc}",
                    args.log,
                    traceback.format_exc(),
                )
                emit("error", message=f"VAD 识别失败：{type(exc).__name__}: {exc}")
                events = []

            if active:
                speech.append(chunk)

            for kind, _ms in events:
                if kind == "start" and not active:
                    logging.info("[VAD_START] ms=%s", _ms)
                    active = True
                    speech = list(preroll)
                    active_peak_rms = max(chunk_rms, noise_floor_rms, 0.001)
                    silent_chunks = 0
                    active_started_at = time.monotonic()
                    logging.info("[ENDPOINT_START] rms=%.6f noise=%.6f", chunk_rms, noise_floor_rms)
                    emit("state", code="hearing", label="听到你说话了")
                elif kind == "end" and active:
                    logging.info("[VAD_END] ms=%s chunks=%s", _ms, len(speech))
                    active = False
                    audio = np.concatenate(speech) if speech else np.zeros(0, dtype=np.float32)
                    speech = []; preroll = []; vad_cache = {}
                    if audio.size < 1600:
                        emit("state", code="listening", label="等待“美丽美丽”")
                        continue
                    emit("state", code="recognizing", label="正在识别你说的话")
                    try:
                        recognize_and_emit(audio, "vad_end")
                    except Exception as exc:
                        logging.exception("ASR failed")
                        desktop_diagnostic(
                            "ASR_EXCEPTION_V085",
                            f"Fun-ASR-Nano 识别失败：{type(exc).__name__}: {exc}",
                            args.log,
                            traceback.format_exc(),
                        )
                        emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                    emit("state", code="listening", label="等待“美丽美丽”")

            # V0.8.5: FSMN-VAD on some Windows microphone/runtime combinations emits
            # START but never emits END. Use adaptive microphone-energy silence only as
            # an ENDPOINT fallback after VAD has already confirmed speech start.
            if active:
                active_peak_rms = max(active_peak_rms, chunk_rms)
                silence_threshold = max(
                    0.0035,
                    min(0.030, noise_floor_rms * 2.8),
                    min(0.030, active_peak_rms * 0.12),
                )
                if chunk_rms <= silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_end_chunks and len(speech) >= 5:
                    elapsed = max(0.0, time.monotonic() - active_started_at)
                    logging.warning(
                        "[VAD_END_FALLBACK] no FSMN end; forcing endpoint after %.3fs "
                        "silent_chunks=%s rms=%.6f threshold=%.6f noise=%.6f peak=%.6f",
                        elapsed, silent_chunks, chunk_rms, silence_threshold,
                        noise_floor_rms, active_peak_rms,
                    )
                    active = False
                    audio = np.concatenate(speech) if speech else np.zeros(0, dtype=np.float32)
                    speech = []; preroll = []; vad_cache = {}
                    silent_chunks = 0; active_peak_rms = 0.0; active_started_at = 0.0
                    if audio.size >= 1600:
                        emit("state", code="recognizing", label="正在识别你说的话")
                        try:
                            fallback_text = recognize_and_emit(audio, "energy_silence_fallback")
                            desktop_diagnostic(
                                "VAD_END_MISSING",
                                f"FSMN-VAD 检测到开始但未返回结束；已由 V0.8.5 静音兜底收句。ASR={fallback_text!r}",
                                args.log,
                                f"elapsed={elapsed:.3f}s threshold={silence_threshold:.6f}",
                            )
                        except Exception as exc:
                            logging.exception("ASR failed after energy endpoint fallback")
                            desktop_diagnostic(
                                "ASR_EXCEPTION_V085",
                                f"静音兜底后 ASR 失败：{type(exc).__name__}: {exc}",
                                args.log,
                                traceback.format_exc(),
                            )
                            emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                    emit("state", code="listening", label="等待“美丽美丽”")

            if active and len(speech) >= max_chunks:
                active = False
                audio = np.concatenate(speech); speech=[]; preroll=[]; vad_cache={}
                emit("state", code="recognizing", label="正在识别你说的话")
                try:
                    logging.warning("[VAD_HARD_CAP] forcing recognition at 25 s")
                    recognize_and_emit(audio, "hard_cap")
                except Exception as exc:
                    logging.exception("ASR failed at hard cap")
                    desktop_diagnostic(
                        "ASR_HARD_CAP_EXCEPTION",
                        f"25 秒强制收句后 ASR 失败：{type(exc).__name__}: {exc}",
                        args.log,
                        traceback.format_exc(),
                    )
                    emit("error", message=f"语音识别失败：{type(exc).__name__}: {exc}")
                emit("state", code="listening", label="等待“美丽美丽”")
    finally:
        try: stream.stop(); stream.close()
        except Exception: pass
        emit("state", code="stopped", label="语音监听已停止")



def diagnostic_file(args):
    """Offline, microphone-free VAD + ASR resource diagnostic."""
    import wave
    import numpy as np
    import torch
    from funasr import AutoModel

    started = time.monotonic()
    emit("diag_stage", code="loading", label="loading FSMN-VAD + Fun-ASR-Nano-2512", device="cpu")
    vad = AutoModel(model=str(args.vad_model_dir), disable_update=True, device="cpu")
    asr_model_dir = Path(args.asr_model_dir)
    try:
        asr = AutoModel(model=str(asr_model_dir), disable_update=True, device="cpu")
        loader = "registry"
    except Exception:
        logging.exception("[DIAG_ASR_LOADER] registry failed; retrying remote_code")
        asr = AutoModel(
            model=str(asr_model_dir),
            trust_remote_code=True,
            remote_code=str(asr_model_dir / "model.py"),
            disable_update=True,
            device="cpu",
        )
        loader = "remote_code"

    load_ms = int((time.monotonic() - started) * 1000)
    emit("diag_models_loaded", device="cpu", loader=loader, load_ms=load_ms)

    wav_path = Path(args.diagnostic_wav)
    with wave.open(str(wav_path), "rb") as wf:
        channels = int(wf.getnchannels())
        width = int(wf.getsampwidth())
        rate = int(wf.getframerate())
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise RuntimeError(f"diagnostic WAV must be PCM16, got sample width={width}")
    pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        pcm = resample_linear(pcm, rate, 16000)
    audio_np = np.asarray(pcm, dtype=np.float32).reshape(-1)
    audio_tensor = torch.from_numpy(audio_np).float().contiguous()

    repeats = max(1, min(8, int(args.diagnostic_repeat or 1)))
    hotwords = [x for x in str(args.hotwords).split() if x]
    for index in range(1, repeats + 1):
        vad_started = time.monotonic()
        vad_cache = {}
        vad_event_count = 0
        chunk_samples = 3200
        for offset in range(0, int(audio_np.size), chunk_samples):
            chunk = audio_np[offset:offset + chunk_samples]
            if chunk.size == 0:
                continue
            res = vad.generate(
                input=chunk,
                cache=vad_cache,
                is_final=(offset + chunk_samples >= int(audio_np.size)),
                chunk_size=200,
            )
            vad_event_count += len(parse_vad_events(res))
        vad_ms = int((time.monotonic() - vad_started) * 1000)

        asr_started = time.monotonic()
        kwargs = {
            "cache": {},
            "language": "中文",
            "itn": True,
            "hotwords": hotwords,
            "batch_size": 1,
        }
        try:
            res = asr.generate(input=audio_tensor, **kwargs)
        except Exception:
            logging.exception("[DIAG_ASR] tensor input failed; retrying WAV path")
            res = asr.generate(input=str(wav_path), **kwargs)
        asr_ms = int((time.monotonic() - asr_started) * 1000)
        text = extract_text(res)
        emit(
            "diag_run",
            run=index,
            vad_ms=vad_ms,
            asr_ms=asr_ms,
            vad_events=vad_event_count,
            text_chars=len(str(text or "")),
            device="cpu",
        )

    emit("diag_ready", device="cpu", repeat=repeats, hold_seconds=int(args.diagnostic_hold or 0))
    hold = max(0, min(600, int(args.diagnostic_hold or 0)))
    if hold:
        time.sleep(hold)
    emit("diag_done", device="cpu")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--asr-model-dir", required=True)
    ap.add_argument("--vad-model-dir", required=True)
    ap.add_argument("--download-asr", action="store_true")
    ap.add_argument("--download-vad", action="store_true")
    ap.add_argument("--listen", action="store_true")
    ap.add_argument("--diagnostic-wav", default="")
    ap.add_argument("--diagnostic-repeat", type=int, default=1)
    ap.add_argument("--diagnostic-hold", type=int, default=0)
    ap.add_argument("--device-index", type=int, default=-1)
    ap.add_argument("--hotwords", default="")
    args = ap.parse_args()
    setup_log(args.log)
    if args.download_asr:
        download_model("FunAudioLLM/Fun-ASR-Nano-2512", args.asr_model_dir); return 0
    if args.download_vad:
        download_model("iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", args.vad_model_dir); return 0
    if args.diagnostic_wav:
        if hasattr(EVENT_STREAM, "reconfigure"):
            EVENT_STREAM.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return diagnostic_file(args)
        except Exception as exc:
            logging.exception("Speech diagnostic failed")
            emit("error", message=f"语音输入诊断失败：{type(exc).__name__}: {exc}")
            return 1
    if args.listen:
        # Parent reads UTF-8 JSON lines; keep library progress on stderr.
        if hasattr(EVENT_STREAM, "reconfigure"):
            EVENT_STREAM.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                listen(args)
            return 0
        except Exception as exc:
            logging.exception("Speech listener failed")
            message = f"语音监听启动失败：{type(exc).__name__}: {exc}"
            desktop_diagnostic(
                "WORKER_FATAL",
                message,
                args.log,
                traceback.format_exc(),
            )
            emit("error", message=message)
            emit("state", code="error", label=message)
            return 1
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
'''


class SpeechInputService(QObject):
    setup_progress = Signal(int, str)
    setup_finished = Signal(bool, str)
    devices_ready = Signal(list)
    state_changed = Signal(str, str)
    utterance_ready = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_busy = False
        self._worker = None
        self._reader_thread = None
        self._stdin_lock = threading.Lock()
        self._last_state = ("stopped", "语音监听未启动")
        for p in (SPEECH_ROOT, ASR_MODEL_DIR, VAD_MODEL_DIR, SETUP_LOG.parent):
            p.mkdir(parents=True, exist_ok=True)
        self._write_worker()

    def _write_worker(self):
        try:
            old = WORKER_SCRIPT.read_text(encoding="utf-8") if WORKER_SCRIPT.exists() else ""
        except Exception:
            old = ""
        if old != WORKER_CODE:
            WORKER_SCRIPT.write_text(WORKER_CODE, encoding="utf-8")

    @staticmethod
    def _dir_size(path):
        try:
            return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())
        except Exception:
            return 0

    def ready(self):
        return (
            VENV_PYTHON.exists()
            and RUNTIME_MARKER.exists()
            and ASR_MARKER.exists()
            and VAD_MARKER.exists()
            and self._dir_size(ASR_MODEL_DIR) > 20_000_000
            and self._dir_size(VAD_MODEL_DIR) > 1_000_000
        )

    def component_status(self):
        if self.ready():
            return "FSMN-VAD + Fun-ASR-Nano-2512 已就绪（本地离线）"
        if not VENV_PYTHON.exists():
            return "请先准备「声音组件」，语音识别将共用同一套本地 Python 环境"
        return "首次使用需准备 FSMN-VAD 与 Fun-ASR-Nano-2512"

    @staticmethod
    def _run(args, timeout):
        SETUP_LOG.parent.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with open(SETUP_LOG, "a", encoding="utf-8") as log:
            log.write("\n$ " + " ".join(map(str, args)) + "\n")
            log.flush()
            proc = subprocess.run(args, stdout=log, stderr=log, timeout=timeout, creationflags=flags)
        if proc.returncode != 0:
            raise RuntimeError(f"命令执行失败（exit={proc.returncode}），详情见 {SETUP_LOG}")

    def prepare_async(self):
        if self.ready():
            self.setup_progress.emit(100, "语音输入组件已就绪")
            self.setup_finished.emit(True, "FSMN-VAD 与 Fun-ASR-Nano-2512 已就绪。")
            return
        if self._setup_busy:
            return
        self._setup_busy = True

        def job():
            ok = False
            try:
                if not VENV_PYTHON.exists():
                    raise RuntimeError("请先在「系统 → 组件与下载」准备 Qwen3-TTS 声音组件。")
                self.stop()
                self._write_worker()
                self.setup_progress.emit(8, "正在检查语音识别运行库…")
                self._run([
                    str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check",
                    "funasr==1.4.16", "modelscope>=1.29,<2", "sounddevice", "soundfile",
                ], 1800)
                RUNTIME_MARKER.write_text("0.8.0", encoding="utf-8")

                if not VAD_MARKER.exists():
                    self.setup_progress.emit(22, "正在下载 FSMN-VAD 语音起止模型…")
                    self._run([
                        str(VENV_PYTHON), str(WORKER_SCRIPT), "--download-vad",
                        "--asr-model-dir", str(ASR_MODEL_DIR), "--vad-model-dir", str(VAD_MODEL_DIR),
                        "--log", str(WORKER_LOG),
                    ], 1800)
                    VAD_MARKER.write_text("0.8.0", encoding="utf-8")

                if not ASR_MARKER.exists():
                    self.setup_progress.emit(45, "正在下载 Fun-ASR-Nano-2512 中文语音识别模型…")
                    self._run([
                        str(VENV_PYTHON), str(WORKER_SCRIPT), "--download-asr",
                        "--asr-model-dir", str(ASR_MODEL_DIR), "--vad-model-dir", str(VAD_MODEL_DIR),
                        "--log", str(WORKER_LOG),
                    ], 7200)
                    ASR_MARKER.write_text("0.8.0", encoding="utf-8")

                if not self.ready():
                    raise RuntimeError("语音输入组件下载完成，但本地校验未通过。")
                ok = True
                self.setup_progress.emit(100, "语音输入组件准备完成")
                msg = "FSMN-VAD + Fun-ASR-Nano-2512 已准备完成。"
            except Exception as exc:
                LOGGER.exception("准备语音输入组件失败")
                msg = f"语音输入组件准备失败：{type(exc).__name__}: {exc}"
            finally:
                self._setup_busy = False
                self.setup_finished.emit(ok, msg)
                if ok:
                    self.load_devices_async()

        threading.Thread(target=job, name="XiaoMeiliSpeechSetup", daemon=True).start()

    def input_devices(self):
        items = [("default", "系统默认麦克风")]
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            seen = set()
            for idx, dev in enumerate(devices):
                try:
                    if int(dev.get("max_input_channels", 0)) <= 0:
                        continue
                    name = str(dev.get("name", f"设备 {idx}"))
                    host_idx = int(dev.get("hostapi", -1))
                    host_name = str(hostapis[host_idx].get("name", "")) if 0 <= host_idx < len(hostapis) else ""
                    key = f"{idx}|{host_idx}|{name}"
                    label = f"{name} · {host_name}" if host_name else name
                    if label in seen:
                        label = f"{label} · #{idx}"
                    seen.add(label)
                    items.append((key, label))
                except Exception:
                    continue
        except Exception:
            LOGGER.exception("读取麦克风设备失败")
        return items

    def load_devices_async(self):
        self.devices_ready.emit(self.input_devices())

    @staticmethod
    def _device_index(device_key):
        if str(device_key or "default") == "default":
            return -1
        try:
            return int(str(device_key).split("|", 1)[0])
        except Exception:
            return -1

    def _alive(self):
        return self._worker is not None and self._worker.poll() is None

    def start(self, device_key="default"):
        if not self.ready():
            self._emit_state("not_ready", "语音输入组件尚未准备")
            return False
        if self._alive():
            self.resume(); return True
        self._write_worker()
        try:
            WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
            self._worker = subprocess.Popen(
                [
                    str(VENV_PYTHON), str(WORKER_SCRIPT), "--listen",
                    "--asr-model-dir", str(ASR_MODEL_DIR), "--vad-model-dir", str(VAD_MODEL_DIR),
                    "--device-index", str(self._device_index(device_key)),
                    "--hotwords", HOTWORDS, "--log", str(WORKER_LOG),
                ],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(WORKER_LOG, "a", encoding="utf-8"),
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._reader_thread = threading.Thread(target=self._reader_loop, name="XiaoMeiliSpeechReader", daemon=True)
            self._reader_thread.start()
            self._emit_state("loading", "正在加载语音识别组件")
            return True
        except Exception as exc:
            LOGGER.exception("启动语音监听失败")
            self._worker = None
            self.error.emit(f"启动语音监听失败：{type(exc).__name__}: {exc}")
            self._emit_state("error", "语音监听启动失败")
            return False

    def _reader_loop(self):
        proc = self._worker
        try:
            while proc is not None and proc.stdout is not None:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith("XMEVENT|"):
                    continue
                try:
                    evt = json.loads(line.split("|", 1)[1])
                except Exception:
                    continue
                kind = str(evt.get("event") or "")
                if kind == "state":
                    self._emit_state(str(evt.get("code") or ""), str(evt.get("label") or ""))
                elif kind == "utterance":
                    text = str(evt.get("text") or "").strip()
                    if text:
                        self.utterance_ready.emit(text)
                elif kind == "error":
                    self.error.emit(str(evt.get("message") or "语音输入工作进程发生错误"))
                elif kind == "ready":
                    self._emit_state("listening", "等待“美丽美丽”")
        except Exception:
            LOGGER.exception("读取语音工作进程输出失败")
        finally:
            if self._worker is proc:
                self._worker = None
                self._emit_state("stopped", "语音监听已停止")

    def _emit_state(self, code, label):
        self._last_state = (str(code), str(label))
        self.state_changed.emit(str(code), str(label))

    def current_state(self):
        return self._last_state

    def _command(self, text):
        if not self._alive() or self._worker.stdin is None:
            return False
        try:
            with self._stdin_lock:
                self._worker.stdin.write(str(text).strip() + "\n")
                self._worker.stdin.flush()
            return True
        except Exception:
            return False

    def pause(self):
        return self._command("pause")

    def resume(self):
        return self._command("resume")

    def stop(self):
        proc = self._worker
        if proc is None:
            return
        try:
            self._command("stop")
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try: proc.terminate()
            except Exception: pass
        self._worker = None
        self._emit_state("stopped", "语音监听已停止")

    def shutdown(self):
        self.stop()


# V0.10.0.5: one-shot microphone-free diagnostic entry point.
# It reuses the installed speech runtime/models and creates no temporary cleanup task.
def _v01005_pick_runtime_path(preferred_name, name_contains=(), value_contains=()):
    import os as _os
    from pathlib import Path as _Path
    value = globals().get(preferred_name)
    if value:
        try:
            p = _Path(value)
            if p.exists():
                return p
        except Exception:
            pass
    for key, raw in list(globals().items()):
        if not raw:
            continue
        upper = str(key).upper()
        if name_contains and not all(token.upper() in upper for token in name_contains):
            continue
        try:
            p = _Path(raw)
        except Exception:
            continue
        low = str(p).lower()
        if value_contains and not all(token.lower() in low for token in value_contains):
            continue
        if p.exists():
            return p
    return None


def _v01005_diagnostic_process(self, wav_path, repeat=4, hold_seconds=0):
    import subprocess as _sp
    from pathlib import Path as _Path
    try:
        if hasattr(self, "_write_worker"):
            self._write_worker()
    except Exception:
        pass

    python_path = _v01005_pick_runtime_path("VENV_PYTHON", ("PYTHON",), ("python",))
    worker_path = _v01005_pick_runtime_path("WORKER_SCRIPT", ("WORKER",), (".py",))
    asr_dir = _v01005_pick_runtime_path("ASR_MODEL_DIR", ("ASR", "MODEL"))
    vad_dir = _v01005_pick_runtime_path("VAD_MODEL_DIR", ("VAD", "MODEL"))
    missing = []
    if python_path is None: missing.append("VENV_PYTHON")
    if worker_path is None: missing.append("WORKER_SCRIPT")
    if asr_dir is None: missing.append("ASR_MODEL_DIR")
    if vad_dir is None: missing.append("VAD_MODEL_DIR")
    if missing:
        raise RuntimeError("语音输入诊断运行路径缺失：" + ", ".join(missing))

    wav = _Path(str(wav_path))
    if not wav.is_file():
        raise FileNotFoundError(f"诊断音频不存在：{wav}")
    diag_log = wav.parent / "speech_diagnostic_worker.log"
    hotwords = "小美丽 VALORANT 无畏契约 贤者 大狙 狙击"
    args = [
        str(python_path), str(worker_path),
        "--log", str(diag_log),
        "--asr-model-dir", str(asr_dir),
        "--vad-model-dir", str(vad_dir),
        "--diagnostic-wav", str(wav),
        "--diagnostic-repeat", str(max(1, int(repeat))),
        "--diagnostic-hold", str(max(0, int(hold_seconds))),
        "--hotwords", hotwords,
    ]
    return _sp.Popen(
        args,
        stdout=_sp.PIPE,
        stderr=_sp.DEVNULL,
        stdin=_sp.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0),
    )


SpeechInputService.diagnostic_process_v01005 = _v01005_diagnostic_process
