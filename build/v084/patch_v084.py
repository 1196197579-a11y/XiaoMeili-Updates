# -*- coding: utf-8 -*-
from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


def _extract_worker_literal(source: str):
    m = re.search(r'(?m)^WORKER_CODE\s*=\s*(?:[rRuUbBfF]{0,2})?(?P<q>"""|\'\'\')', source)
    if not m:
        raise RuntimeError("V0.8.4 could not locate WORKER_CODE literal")
    quote = m.group("q")
    end = source.find(quote, m.end())
    if end < 0:
        raise RuntimeError("V0.8.4 could not locate end of WORKER_CODE literal")
    return m, quote, end, source[m.end():end]


def _replace_worker_literal(source: str, worker: str) -> str:
    m, quote, end, _ = _extract_worker_literal(source)
    if quote in worker:
        raise RuntimeError("V0.8.4 worker unexpectedly contains source quote delimiter")
    replacement = f"WORKER_CODE = r{quote}{worker}{quote}"
    return source[:m.start()] + replacement + source[end + len(quote):]


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"V0.8.4 expected exactly one {label}, found {count}")
    return text.replace(old, new, 1)


def patch(source_root: Path):
    source_root = Path(source_root).resolve()
    main = source_root / "app" / "src" / "main.py"
    speech = source_root / "app" / "src" / "speech_input.py"
    if not main.exists() or not speech.exists():
        raise FileNotFoundError("V0.8.4 expected V0.8.3 source files")

    main_text = main.read_text(encoding="utf-8")
    speech_text = speech.read_text(encoding="utf-8")
    if 'APP_VERSION = "0.8.3"' not in main_text:
        raise RuntimeError("V0.8.4 expected APP_VERSION 0.8.3 base")

    main_text = main_text.replace('APP_VERSION = "0.8.3"', 'APP_VERSION = "0.8.4"', 1)
    main_text = main_text.replace("V0.8.3", "V0.8.4")
    speech_text = speech_text.replace("V0.8.3", "V0.8.4")

    _m, _q, _end, worker = _extract_worker_literal(speech_text)

    worker = _replace_once(
        worker,
        '''def listen(args):
    import numpy as np
    import sounddevice as sd
    from funasr import AutoModel
''',
        '''def listen(args):
    import numpy as np
    import sounddevice as sd
    import torch
    from funasr import AutoModel
''',
        "torch import in listener",
    )

    old_call = '''        res = asr.generate(
            input=audio,
            cache={},
            language="中文",
            itn=True,
            hotwords=[x for x in str(args.hotwords).split() if x],
            batch_size=1,
        )
'''
    new_call = '''        # Fun-ASR-Nano's current ChatML bridge only constructs an audio
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
        res = asr.generate(
            input=audio_tensor,
            fs=16000,
            cache={},
            language="中文",
            itn=True,
            hotwords=[x for x in str(args.hotwords).split() if x],
            batch_size=1,
        )
'''
    worker = _replace_once(worker, old_call, new_call, "Nano tensor input conversion")

    # Upgrade desktop diagnostic labels so the next failure is immediately
    # distinguishable from the previous numpy-input bug.
    worker = worker.replace(
        '"ASR_EXCEPTION",\n                            f"Fun-ASR-Nano 识别失败：',
        '"ASR_EXCEPTION_V084",\n                            f"Fun-ASR-Nano 识别失败：',
    )
    worker = worker.replace(
        '"ASR_EXCEPTION",\n                                f"静音兜底后 ASR 失败：',
        '"ASR_EXCEPTION_V084",\n                                f"静音兜底后 ASR 失败：',
    )

    compile(worker, "speech_worker_v084.py", "exec")
    speech_text = _replace_worker_literal(speech_text, worker)

    main.write_text(main_text, encoding="utf-8")
    speech.write_text(speech_text, encoding="utf-8")

    py_compile.compile(str(main), doraise=True)
    py_compile.compile(str(speech), doraise=True)

    m = main.read_text(encoding="utf-8")
    sp = speech.read_text(encoding="utf-8")
    for token in (
        'APP_VERSION = "0.8.4"',
    ):
        if token not in m:
            raise RuntimeError(f"V0.8.4 main verification failed: {token}")
    for token in (
        "import torch",
        "torch.from_numpy(audio_np)",
        "input=audio_tensor",
        "fs=16000",
        "[ASR_INPUT]",
        "VAD_END_FALLBACK",
        "desktop_diagnostic(",
    ):
        if token not in sp:
            raise RuntimeError(f"V0.8.4 speech verification failed: {token}")

    print("Patched XiaoMeili source to V0.8.4 Nano torch.Tensor input repair")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v084.py <source_root>")
    patch(Path(sys.argv[1]))
