# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.10.0.5 could not locate speech WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.10.0.5 could not locate speech WORKER_CODE end")
    return m, quote, end, source[m.end():end]


def replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.10.0.5 diagnostic worker unexpectedly contains quote delimiter")
    return source[:m.start()] + f"WORKER_CODE = r{quote}{worker}{quote}" + source[end + len(quote):]


DIAGNOSTIC_FUNCTION = r'''
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


'''


SERVICE_EXTENSION = r'''

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
'''


def patch(path: Path):
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    source = path.read_text(encoding="utf-8")
    _m, _q, _end, worker = extract_worker_literal(source)

    if "def diagnostic_file(args):" not in worker:
        anchor = "\ndef main():\n"
        pos = worker.find(anchor)
        if pos < 0:
            raise RuntimeError("V0.10.0.5 speech worker main anchor missing")
        worker = worker[:pos + 1] + DIAGNOSTIC_FUNCTION + worker[pos + 1:]

    if '--diagnostic-wav' not in worker:
        anchor = '    ap.add_argument("--listen", action="store_true")\n'
        if anchor not in worker:
            raise RuntimeError("V0.10.0.5 speech --listen argument anchor missing")
        worker = worker.replace(
            anchor,
            anchor
            + '    ap.add_argument("--diagnostic-wav", default="")\n'
            + '    ap.add_argument("--diagnostic-repeat", type=int, default=1)\n'
            + '    ap.add_argument("--diagnostic-hold", type=int, default=0)\n',
            1,
        )

    diag_branch = '''    if args.diagnostic_wav:
        if hasattr(EVENT_STREAM, "reconfigure"):
            EVENT_STREAM.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return diagnostic_file(args)
        except Exception as exc:
            logging.exception("Speech diagnostic failed")
            emit("error", message=f"语音输入诊断失败：{type(exc).__name__}: {exc}")
            return 1
'''
    if "if args.diagnostic_wav:" not in worker:
        anchor = "    if args.listen:\n"
        if anchor not in worker:
            raise RuntimeError("V0.10.0.5 speech listen branch anchor missing")
        worker = worker.replace(anchor, diag_branch + anchor, 1)

    compile(worker, "speech_worker_v01005.py", "exec")
    source = replace_worker_literal(source, worker)

    if "SpeechInputService.diagnostic_process_v01005" not in source:
        source += SERVICE_EXTENSION

    path.write_text(source, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)

    check = path.read_text(encoding="utf-8")
    for token in (
        "def diagnostic_file(args):",
        "--diagnostic-wav",
        "--diagnostic-repeat",
        "--diagnostic-hold",
        'device="cpu"',
        "SpeechInputService.diagnostic_process_v01005",
        "diag_models_loaded",
        "diag_ready",
    ):
        if token not in check:
            raise RuntimeError("V0.10.0.5 speech diagnostic patch missing token: " + token)
    print("V0.10.0.5 speech offline diagnostic patch PASS")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_speech_v01005.py <speech_input.py>")
    patch(Path(sys.argv[1]))
