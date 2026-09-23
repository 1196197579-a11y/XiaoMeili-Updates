# -*- coding: utf-8 -*-
"""Qwen3-TTS voice backend for XiaoMeili V0.6.2.

The heavy TTS runtime lives in its own Python environment under XiaoMeiliData.
The desktop EXE stays small and talks to a persistent local worker process.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOGGER = logging.getLogger("XiaoMeili")


def _user_root() -> Path:
    if sys.platform == "win32":
        base = os.getenv("PUBLIC") or r"C:\Users\Public"
        p = Path(base) / "XiaoMeiliData"
    else:
        p = Path.home() / ".xiaomeili"
    p.mkdir(parents=True, exist_ok=True)
    return p


USER = _user_root()
RUNTIME_ROOT = USER / "voice_runtime" / "qwen3_tts"
VENV_DIR = RUNTIME_ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
MODEL_DIR = USER / "voice" / "qwen3_tts_1_7b_customvoice"
VOICE_CACHE_DIR = USER / "voice_cache"
WORKER_SCRIPT = RUNTIME_ROOT / "qwen_worker.py"
WORKER_LOG = USER / "logs" / "qwen3_tts_worker.log"
RUNTIME_LOG = USER / "logs" / "qwen3_tts_setup.log"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
EXPECTED_MODEL_BYTES = 3_500_000_000
EXPECTED_TOKENIZER_BYTES = 600_000_000
EXPECTED_TOTAL_MODEL_BYTES = 4_450_000_000

# Two official native-Chinese female timbres, exposed as four XiaoMeili-friendly
# presets. The speaker identity remains fixed; only delivery style changes.
PRESETS = {
    "vivian_natural": {
        "name": "Vivianï½œæ¸…äº®è‡ªç„¶å°‘å¥³",
        "speaker": "Vivian",
        "instruct": "è¯·ç”¨æ ‡å‡†æ™®é€šè¯ï¼Œè‡ªç„¶æ¸…äº®çš„å¹´è½»å°‘å¥³å£°çº¿è¯´è¯ã€‚è¯­æ°”çµåŠ¨ä½†å…‹åˆ¶ï¼Œåƒæ—¥å¸¸èŠå¤©ï¼Œä¸è¦æ’­éŸ³è…”ï¼Œä¸è¦å¤¸å¼ å–èŒï¼Œä¸è¦å¤–å›½å£éŸ³ã€‚",
    },
    "vivian_cool": {
        "name": "Vivianï½œæ¸…å†·å°ç¾Žä¸½",
        "speaker": "Vivian",
        "instruct": "è¯·ç”¨æ ‡å‡†æ™®é€šè¯ï¼Œå¹´è½»æ¸…å†·çš„å°‘å¥³å£°çº¿è¯´è¯ã€‚è¯­æ°”è‡ªä¿¡ã€ç•¥å¸¦ä¸€ç‚¹å‚²å¨‡å’Œé…·æ„Ÿï¼Œå’¬å­—è‡ªç„¶ï¼Œä¸è¦æ’­éŸ³è…”ï¼Œä¸è¦å¤¸å¼ ï¼Œä¸è¦å¤–å›½å£éŸ³ã€‚",
    },
    "serena_soft": {
        "name": "Serenaï½œæ¸©æŸ”å°‘å¥³",
        "speaker": "Serena",
        "instruct": "è¯·ç”¨æ ‡å‡†æ™®é€šè¯ï¼Œæ¸©æŸ”è‡ªç„¶çš„å¹´è½»å°‘å¥³å£°çº¿è¯´è¯ã€‚å£°éŸ³æŸ”å’Œä½†ä¸è¦æ°”å£°è¿‡é‡ï¼ŒåƒçœŸå®žèŠå¤©ï¼Œä¸è¦æ’­éŸ³è…”ï¼Œä¸è¦å¤¸å¼ å–èŒï¼Œä¸è¦å¤–å›½å£éŸ³ã€‚",
    },
    "serena_lively": {
        "name": "Serenaï½œæ´»æ³¼å°‘å¥³",
        "speaker": "Serena",
        "instruct": "è¯·ç”¨æ ‡å‡†æ™®é€šè¯ï¼Œæ´»æ³¼è‡ªç„¶çš„å¹´è½»å°‘å¥³å£°çº¿è¯´è¯ã€‚è¯­æ°”è½»å¿«ã€æœ‰ä¸€ç‚¹ä¿çš®ï¼Œä½†ä¿æŒçœŸå®žå£è¯­æ„Ÿï¼Œä¸è¦æ’­éŸ³è…”ï¼Œä¸è¦å¤¸å¼ å–èŒï¼Œä¸è¦å¤–å›½å£éŸ³ã€‚",
    },
}


WORKER_CODE = r'''# -*- coding: utf-8 -*-
import argparse, json, logging, os, socket, sys, traceback
from pathlib import Path


def setup_log(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=path, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s [%(levelname)s] %(message)s")


def download_model(model_dir):
    model_dir = str(Path(model_dir))
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    try:
        from modelscope import snapshot_download
        logging.info("Downloading model via ModelScope: %s", model_dir)
        snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", local_dir=model_dir)
        return
    except Exception:
        logging.exception("ModelScope download failed, falling back to Hugging Face")
    from huggingface_hub import snapshot_download
    snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", local_dir=model_dir)


def load_model(model_dir):
    import torch
    from qwen_tts import Qwen3TTSModel
    if torch.cuda.is_available():
        device_map = "cuda:0"
        dtype = torch.bfloat16
    else:
        device_map = "cpu"
        dtype = torch.float32
    logging.info("Loading Qwen3-TTS on %s dtype=%s", device_map, dtype)
    model = Qwen3TTSModel.from_pretrained(
        str(model_dir), device_map=device_map, dtype=dtype, attn_implementation="sdpa"
    )
    return model


def send_json(conn, obj):
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    conn.sendall(data)


def recv_json(conn):
    chunks = []
    while True:
        part = conn.recv(65536)
        if not part:
            break
        chunks.append(part)
        if b"\n" in part:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    return json.loads(raw.decode("utf-8"))


def serve(port, model_dir):
    import soundfile as sf
    model = None
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(port)))
    s.listen(4)
    logging.info("Worker listening on 127.0.0.1:%s", port)
    while True:
        conn, _ = s.accept()
        with conn:
            try:
                req = recv_json(conn)
                cmd = req.get("cmd")
                if cmd == "ping":
                    import torch
                    send_json(conn, {"ok": True, "cuda": bool(torch.cuda.is_available())})
                    continue
                if cmd == "shutdown":
                    send_json(conn, {"ok": True})
                    break
                if cmd != "synthesize":
                    raise ValueError("unknown command")
                if model is None:
                    model = load_model(model_dir)
                text = str(req.get("text") or "").strip()
                speaker = str(req.get("speaker") or "Vivian")
                instruct = str(req.get("instruct") or "").strip()
                out = str(req.get("output") or "").strip()
                if not text or not out:
                    raise ValueError("missing text/output")
                import torch
                torch.manual_seed(20260923)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(20260923)
                wavs, sr = model.generate_custom_voice(
                    text=text, language="Chinese", speaker=speaker, instruct=instruct
                )
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                sf.write(out, wavs[0], sr)
                send_json(conn, {"ok": True, "sample_rate": int(sr), "output": out})
            except Exception as e:
                logging.exception("Worker request failed")
                send_json(conn, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    setup_log(args.log)
    try:
        if args.download:
            download_model(args.model_dir)
            return 0
        if args.self_test:
            import torch, qwen_tts, transformers, soundfile
            print(json.dumps({"ok": True, "cuda": bool(torch.cuda.is_available()), "torch": torch.__version__}))
            return 0
        if args.serve:
            serve(args.port, args.model_dir)
            return 0
        return 2
    except Exception:
        logging.exception(!,ƒÒ! ãvVFW7B# ¢&WGW&â.ŠúÞ˜	þzˆÞ[êîhZ.Kˆx+ž8" ¢–b7VVBâãƒ ¢&WGW&â.ŠúÞ˜	þiˆîi‹î[ú¾KˆK©¾ûÈÎKØnKùÞhÈkˆ^i›8" ¢–b7VVBâãC ¢&WGW&â.ŠúÞ˜	þzˆÞ[êî[ú¾Kˆx+ž8" ¢&WGW&â.KÛþyJŽˆz®xKnjÚ>[‹ŽŠúÞ˜	þ8"  ¢FVb&Wf–Wr‡6VÆbÂFW‡BÂfö–6Uö–BÂ7VVCÓã“ ¢FW‡BÒ7G"‡FW‡B÷"""’ç7G&—‚¢fö–6Uö–BÒ7G"‡fö–6Uö–B÷"""’ç7G&—‚¢–bæ÷BFW‡C ¢6VÆbç7–çF†W6—5öf–æ—6†VBæVÖ—B„fÇ6RÂ.Šû~‹é>XZ^Šù^Y
Îih~ZÙ~8""¢&WGW&à¢–bfö–6Uö–Bæ÷B–â$U4UE3 ¢6VÆbç7–çF†W6—5öf–æ—6†VBæVÖ—B„fÇ6RÂ.Šû~XXŽ˜žhºžKˆKŠ¢vVã2ÕEE2KŠÞih~Z;{«þ8""¢&WGW&à¢–bæ÷B6VÆbç&VG’‚“ ¢6VÆbç7–çF†W6—5öf–æ—6†VBæVÖ—B„fÇ6RÂ.Šû~XXŽXxnZHrvVã2ÕEE2ŠúÞ™û>{¸NK»n8""¢&WGW&à¢–b6VÆbå÷7–çF…ö'W7“ ¢6VÆbç7–çF†W6—5öf–æ—6†VBæVÖ—B„fÇ6RÂ.Kˆ®KˆiÚŠúÞ™û>‹ùŽYÊŽyIþh‰ûÈÎŠû~zˆÞzØž8""¢&WGW&à¢6VÆbå÷7–çF…ö'W7’ÒG'VP¢6VÆbç7–çF†W6—5÷7F'FVBæVÖ—B‚ ¢FVb¦ö"‚“ ¢ö²ÒfÇ6P¢G'“ ¢6VÆbå÷7F'E÷v÷&¶W"‚¢&W6WBÒ$U4UE5·fö–6Uö–EÐ¢–ç7G'V7BÒ&W6WE²&–ç7G'V7B%Ò²6VÆbå÷7VVEö–ç7G'V7F–öâ‡7VVB¢÷WBÒdô”4Uô44„UôD•"ò'†–öÖV–Æ•÷vVã5÷GG5÷&Wf–Wrçvb ¢&W7Ò6VÆbå÷&WVW7B‡°¢&6ÖB#¢'7–çF†W6—¦R"Â'FW‡B#¢FW‡BÂ'7V¶W"#¢&W6WE²'7V¶W"%ÒÀ¢&–ç7G'V7B#¢–ç7G'V7BÂ&÷WGWB#¢7G"†÷WB¢ÒÂF–ÖV÷WCÓ3¢–bæ÷B&W7ævWB‚&ö²"“ ¢&—6R'VçF–ÖTW'&÷"‡&W7ævWB‚&W'&÷""’÷"%vVã2ÕEE2YŽh‰ZK‹JR"¢–b7—2çÆFf÷&ÒÓÒ'v–ã3"# ¢–×÷'Bv–ç6÷Væ@¢v–ç6÷VæBåÆ•6÷VæB‡7G"†÷WB’Âv–ç6÷VæBå4äEôd”ÄTäÔRÂv–ç6÷VæBå4äEô5”ä2¢ö²ÒG'VP¢×6rÒb.[{.i*ÞiKîûÉ§·&W6WE²væÖRu×Ò ¢W†6WBW†6WF–öâ2S ¢ÄôttU"æW†6WF–öâ‚%vVã2ÕEE2Šù^Y
ÎyIþh‰ZK‹JR"¢×6rÒb.Šù^Y
ÎZK‹J^ûÉ§·G—R†R’åõöæÖUõ÷Ó¢¶WÒ ¢f–æÆÇ“ ¢6VÆbå÷7–çF…ö'W7’ÒfÇ6P¢6VÆbç7–çF†W6—5öf–æ—6†VBæVÖ—B†ö²Â×6r¢F‡&VF–æråF‡&VB‡F&vWCÖ¦ö"ÂæÖSÒ%†–ôÖV–Æ•vVåfö–6U7–çF‚"ÂFVÖöãÕG'VR’ç7F'B‚ ¢FVb6‡WFF÷vâ‡6VÆb“ ¢v—F‚6VÆbåöÆö6³ ¢G'“ ¢–b6VÆbå÷v÷&¶W%öÆ—fR‚“ ¢G'“ ¢6VÆbå÷&WVW7B‡²&6ÖB#¢'6‡WFF÷vâ'ÒÂF–ÖV÷WCÓ2¢W†6WBW†6WF–öã ¢70¢G'“ ¢6VÆbå÷v÷&¶W%÷&ö2çv—B‡F–ÖV÷WCÓB¢W†6WBW†6WF–öã ¢6VÆbå÷v÷&¶W%÷&ö2çFW&Ö–æFR‚¢W†6WBW†6WF–öã ¢70¢6VÆbå÷v÷&¶W%÷&ö2ÒæöæP¢6VÆbå÷v÷&¶W%÷÷'BÒæöæP¢G'“ ¢–b6VÆbå÷v÷&¶W%÷7FF÷WC ¢6VÆbå÷v÷&¶W%÷7FF÷WBæ6Æ÷6R‚¢W†6WBW†6WF–öã ¢70¢6VÆbå÷v÷&¶W%÷7FF÷WBÒæöæP¢6VÆbå÷v÷&¶W%÷7FFW'"ÒæöæP 