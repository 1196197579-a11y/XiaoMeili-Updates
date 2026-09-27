# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def _extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.8.5 could not locate WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.8.5 could not locate end of WORKER_CODE literal")
    return m, quote, end, source[m.end():end]


def _replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = _extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.8.5 worker unexpectedly contains source quote delimiter")
    replacement = f"WORKER_CODE = r{quote}{worker}{quote}"
    return source[:m.start()] + replacement + source[end + len(quote):]


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"V0.8.5 expected exactly one {label}, found {count}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    source_root = Path(source_root).resolve()
    main = source_root / "app" / "src" / "main.py"
    speech = source_root / "app" / "src" / "speech_input.py"
    if not main.exists() or not speech.exists():
        raise FileNotFoundError("V0.8.5 expected V0.8.4 source files")

    main_text = main.read_text(encoding="utf-8")
    speech_text = speech.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.4"' not in main_text:
        raise RuntimeError("V0.8.5 expected APP_VERSION 0.8.4 base")

    main_text = main_text.replace('APP_VERSION = "0.8.4"', 'APP_VERSION = "0.8.5"', 1)
    main_text = main_text.replace("V0.8.4", "V0.8.5")
    speech_text = speech_text.replace("V0.8.4", "V0.8.5")

    _m, _q, _end, worker = _extract_worker_literal(speech_text)

    # Add stdlib helpers used by the WAV compatibility fallback.
    worker = _replace_once(
        worker,
        "import sys\nimport traceback\nimport threading\n",
        "import sys\nimport tempfile\nimport traceback\nimport threading\nimport wave\n",
        "worker compatibility imports",
    )

    old = '''        res = asr.generate(
            input=audio_tensor,
            fs=16000,
            cache={},
            language="中文",
            itn=True,
            hotwords=[x for x in str(args.hotwords).split() if x],
            batch_size=1,
        )
        text = extract_text(res)
'''
    new = '''        asr_kwargs = {
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
                    f" wav={type(wav_exc).__name__}: {wav_exc}\\n"
                    f"--- tensor traceback ---\\n{tensor_tb}\\n"
                    f"--- wav traceback ---\\n{wav_tb}"
                ) from wav_exc
            finally:
                if tmp_path:
                    try:
                        Path(tmp_path).unlink(missing_ok=True)
                    except Exception:
                        pass

        text = extract_text(res)
        logging.info("[ASR_SUCCESS] text=%r", text)
'''
    worker = _replace_once(worker, old, new, "Nano dual transport call")

    # Make V0.8.5 diagnostics distinguishable from V0.8.4.
    worker = worker.replace("ASR_EXCEPTION_V084", "ASR_EXCEPTION_V085")

    compile(worker, "speech_worker_v085.py", "exec")
    speech_text = _replace_worker_literal(speech_text, worker)

    main.write_text(main_text, encoding="utf-8")
    speech.write_text(speech_text, encoding="utf-8")

    py_compile.compile(str(main), doraise=True)
    py_compile.compile(str(speech), doraise=True)

    m = main.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.5"' not in m:
        raise RuntimeError("V0.8.5 main verification failed")
    for token in (
        "implicit_frontend_fs",
        "asr.generate(input=audio_tensor, **asr_kwargs)",
        "ASR_TRANSPORT_FALLBACK",
        "tempfile.mkstemp",
        "wave.open",
        "[ASR_SUCCESS]",
        "ASR_EXCEPTION_V085",
    ):
        if token not in sp:
            raise RuntimeError(f"V0.8.5 speech verification failed: {token}")
    if "input=audio_tensor,\n            fs=16000" in sp:
        raise RuntimeError("V0.8.5 still passes duplicate fs to Nano")

    print("Patched XiaoMeili source to V0.8.5 Nano dual-transport repair")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v085.py <source_root>")
    patch(Path(sys.argv[1]))
